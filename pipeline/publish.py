import json
import os
import shutil
import subprocess
import urllib.request
import uuid
from datetime import datetime
from decimal import Decimal

from pipeline.alerts import alert
from pipeline.analyst.report_schema import Report
from pipeline.config import Settings
from pipeline.db import connect
from pipeline.localize import attach_translations, translation_map
from pipeline.safeguards import stale_sources


def update_exchange_rate(settings: Settings) -> dict:
    day = datetime.now(settings.tz).date().isoformat()
    with connect(settings.database, readonly=True) as conn:
        row = conn.execute("SELECT * FROM exchange_rates WHERE date=?", (day,)).fetchone()
    if row:
        return dict(row)
    try:
        request = urllib.request.Request(
            "https://api.frankfurter.dev/v2/rates?base=KRW&quotes=CNY",
            headers={"User-Agent": "SeoulBeautyPrice/0.1"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = json.load(response)
        item = raw[0]
        rate = Decimal(str(item["rate"]))
        if item["base"] != "KRW" or item["quote"] != "CNY" or not 0 < rate < 1:
            raise ValueError("Invalid exchange rate")
        with connect(settings.database) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO exchange_rates VALUES (?,?,?,?)",
                (
                    day,
                    item["date"],
                    str(rate),
                    "Frankfurter v2",
                ),
            )
        return {"date": day, "observed_date": item["date"], "krw_cny": str(rate)}
    except Exception:
        alert(
            settings,
            "exchange_rate_failed",
            "Exchange rate unavailable; using explicitly dated cache",
        )
        with connect(settings.database, readonly=True) as conn:
            old = conn.execute("SELECT * FROM exchange_rates ORDER BY date DESC LIMIT 1").fetchone()
        return dict(old) if old else {}


def render_report(conn, report: Report) -> dict:
    sections = []
    for field, title in [
        ("price_drops", "价格回落"),
        ("new_offers", "新上架观察"),
        ("anomalies", "异常价格观察"),
    ]:
        entries = []
        for entry in getattr(report, field):
            row = conn.execute(
                "SELECT i.id,COALESCE((SELECT h.price_krw FROM option_history h "
                "WHERE h.option_id=o.id AND h.observed_date<=? "
                "ORDER BY h.observed_date DESC LIMIT 1),o.price_krw) AS price_krw,"
                "c.name_ko AS clinic_name FROM offer_items i "
                "JOIN options o ON o.id=i.option_id JOIN events e ON e.id=o.event_id "
                "JOIN clinics c ON c.id=e.clinic_id WHERE i.id=?",
                (report.date.isoformat(), entry.offer_item_id),
            ).fetchone()
            if row is None:
                raise ValueError("Cannot render report with unknown offer ID")
            entries.append({**dict(row), "note": entry.note})
        sections.append({"title": title, "entries": entries})
    return {"date": report.date.isoformat(), "sections": sections}


def site_payload(settings: Settings, *, include_draft: bool = False) -> dict:
    day = datetime.now(settings.tz).date().isoformat()
    with connect(settings.database, readonly=True) as conn:
        rows = conn.execute(
            "SELECT v.*,o.name_raw AS option_name,e.title_raw AS event_title,"
            "c.name_ko AS clinic_name,c.address_ko AS address,e.url,"
            "COALESCE(l.label,'unranked') AS label FROM v_offers v "
            "JOIN events e ON e.id=v.event_id JOIN clinics c ON c.id=v.clinic_id "
            "JOIN options o ON o.id=v.option_id "
            "LEFT JOIN labels l ON l.offer_item_id=v.offer_item_id AND l.date=?",
            (day,),
        ).fetchall()
        offers = []
        for row in rows:
            data = dict(row)
            data["id"] = data.pop("offer_item_id")
            data["conditions"] = json.loads(data["conditions"])
            data["extra_fees"] = json.loads(data["extra_fees"])
            data["history"] = [
                {"date": r["observed_date"], "price_krw": r["price_krw"]}
                for r in conn.execute(
                    "SELECT observed_date,price_krw FROM option_history WHERE option_id=? "
                    "ORDER BY observed_date DESC LIMIT 14",
                    (data["option_id"],),
                )
            ]
            offers.append(data)
        clinic_ids = {o["clinic_id"] for o in offers}
        clinics = []
        for row in conn.execute("SELECT * FROM clinics WHERE merged_into IS NULL"):
            if row["id"] not in clinic_ids:
                continue
            clinics.append(
                {
                    "id": row["id"],
                    "name": row["name_ko"],
                    "address": row["address_ko"],
                    "registered": bool(row["foreign_patient_registered"])
                    if row["foreign_patient_registered"] is not None
                    else None,
                    "urls": sorted({o["url"] for o in offers if o["clinic_id"] == row["id"]}),
                }
            )
        rate_row = conn.execute(
            "SELECT * FROM exchange_rates ORDER BY date DESC LIMIT 1"
        ).fetchone()
        report_row = conn.execute(
            "SELECT report_json FROM daily_reports WHERE published=1 "
            + ("OR date=? " if include_draft else "")
            + "ORDER BY date DESC LIMIT 1",
            (day,) if include_draft else (),
        ).fetchone()
        report = (
            render_report(conn, Report.model_validate_json(report_row[0])) if report_row else None
        )
        stats = [dict(r) for r in conn.execute("SELECT * FROM bucket_stats WHERE date=?", (day,))]
        raw_options = [
            dict(r)
            for r in conn.execute(
                "SELECT o.id,o.name_raw AS option_name,o.sessions_raw,o.price_krw,"
                "o.coupon_price_krw,o.vat,e.id AS event_id,e.title_raw AS event_title,"
                "e.source,e.url,e.last_seen AS observed_date,c.id AS clinic_id,"
                "c.name_ko AS clinic_name,c.address_ko AS address "
                "FROM options o JOIN events e ON e.id=o.event_id "
                "JOIN clinics c ON c.id=e.clinic_id WHERE o.active=1 AND e.status='active' "
                "ORDER BY e.last_seen DESC,e.id DESC,o.id"
            )
        ]
        translations = translation_map(conn)
    return attach_translations(
        {
            "mode": "live" if offers else "empty",
            "generated_at": datetime.now(settings.tz).isoformat(),
            "offers": offers,
            "clinics": clinics,
            "report": report,
            "rate": {"krw_cny": float(rate_row["krw_cny"]), "date": rate_row["observed_date"]}
            if rate_row
            else None,
            "stale_sources": stale_sources(settings, day),
            "bucket_stats": stats,
            "raw_options": raw_options,
        },
        translations,
    )


def build_site(settings: Settings, *, include_draft: bool = False, builder=None) -> dict:
    release_id = uuid.uuid4().hex
    root = settings.publish_dir.resolve()
    release = root / "releases" / release_id
    release.mkdir(parents=True)
    payload = site_payload(settings, include_draft=include_draft)
    data_file = release / "source-data.json"
    data_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    output = release / "site"
    try:
        if builder:
            builder(output, payload)
        else:
            env = os.environ.copy()
            env["SITE_DATA_PATH"] = str(data_file)
            npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
            if not npm:
                raise ValueError("npm is required to build the static website")
            result = subprocess.run(
                [npm, "run", "build", "--", "--outDir", str(output)],
                cwd=settings.web_dir,
                env=env,
                capture_output=True,
                timeout=300,
            )
            if result.returncode:
                raise ValueError("Astro build failed; existing publication was not replaced")
        if not (output / "index.html").is_file():
            raise ValueError("Static build produced no index.html")
        # Immutable release + atomic symlink keeps the old site until the build succeeds.
        link = root / (".current-" + release_id)
        try:
            link.symlink_to(output, target_is_directory=True)
            os.replace(link, root / "current")
        except OSError:
            # Without symlink privilege, preserve the release but do not fake publication.
            raise ValueError("Atomic publication requires directory symlink support") from None
        with connect(settings.database) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO publication_state VALUES (1,?,?)",
                (datetime.now(settings.tz).isoformat(), str(output)),
            )
            if include_draft:
                conn.execute(
                    "UPDATE daily_reports SET published=1 WHERE date=?",
                    (datetime.now(settings.tz).date().isoformat(),),
                )
        return {"offers": len(payload["offers"]), "release": release_id}
    except Exception:
        alert(settings, "build_failed", "Static build not published; previous version retained")
        raise
