import json
import urllib.parse
import urllib.request
from datetime import datetime

from pipeline.config import Settings
from pipeline.db import connect


def alert(settings: Settings, code: str, message: str, source: str = "pipeline") -> None:
    with connect(settings.database) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO alerts(source,date,code,message) VALUES (?,?,?,?)",
            (source, datetime.now(settings.tz).date().isoformat(), code, message[:1000]),
        )


def send_pending(settings: Settings) -> int:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return 0
    with connect(settings.database, readonly=True) as conn:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE delivered=0 ORDER BY id LIMIT 20"
        ).fetchall()
    count = 0
    for row in rows:
        payload = urllib.parse.urlencode(
            {
                "chat_id": settings.telegram_chat_id,
                "text": f"[{row['source']}/{row['code']}] {row['date']}\n{row['message']}",
            }
        ).encode()
        # Telegram responses and request URLs (which contain tokens) must never enter logs.
        try:
            token = settings.telegram_bot_token.get_secret_value()
            request = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage", data=payload, method="POST"
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.load(response)
            if not result.get("ok"):
                continue
        except Exception:
            continue
        with connect(settings.database) as conn:
            conn.execute("UPDATE alerts SET delivered=1 WHERE id=?", (row["id"],))
        count += 1
    return count


def heartbeat(settings: Settings, suffix: str = "") -> None:
    if not settings.healthchecks_url:
        return
    url = settings.healthchecks_url.get_secret_value().rstrip("/") + suffix
    if not url.startswith("https://"):
        raise ValueError("Healthchecks URL must be HTTPS")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=15):
            pass
    except Exception:
        alert(settings, "heartbeat_failed", "Unable to deliver monitoring heartbeat")
