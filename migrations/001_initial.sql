CREATE TABLE clinics (
    id INTEGER PRIMARY KEY,
    name_ko TEXT NOT NULL,
    name_zh TEXT,
    address_ko TEXT NOT NULL,
    district TEXT,
    area TEXT,
    foreign_patient_registered INTEGER CHECK (foreign_patient_registered IN (0, 1)),
    merged_into INTEGER REFERENCES clinics(id),
    UNIQUE (name_ko, address_ko),
    CHECK (merged_into IS NULL OR merged_into != id)
);
CREATE TABLE clinic_sources (
    clinic_id INTEGER NOT NULL REFERENCES clinics(id),
    source TEXT NOT NULL CHECK (source IN ('babitalk', 'yeoshin', 'unni')),
    source_clinic_id TEXT NOT NULL,
    url TEXT NOT NULL,
    PRIMARY KEY (source, source_clinic_id)
);
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('babitalk', 'yeoshin', 'unni')),
    source_event_id TEXT NOT NULL,
    url TEXT NOT NULL,
    clinic_id INTEGER REFERENCES clinics(id),
    title_raw TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'ended')),
    UNIQUE (source, source_event_id)
);
CREATE TABLE options (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id),
    source_option_id TEXT NOT NULL,
    name_raw TEXT NOT NULL,
    sessions_raw TEXT,
    list_price_krw INTEGER CHECK (list_price_krw > 0),
    price_krw INTEGER NOT NULL CHECK (price_krw > 0),
    coupon_price_krw INTEGER CHECK (coupon_price_krw > 0),
    content_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    UNIQUE (event_id, source_option_id)
);
CREATE TABLE option_history (
    option_id INTEGER NOT NULL REFERENCES options(id),
    observed_date TEXT NOT NULL,
    price_krw INTEGER NOT NULL CHECK (price_krw > 0),
    coupon_price_krw INTEGER CHECK (coupon_price_krw > 0),
    PRIMARY KEY (option_id, observed_date)
);
CREATE TABLE extractions (
    id INTEGER PRIMARY KEY,
    option_id INTEGER NOT NULL REFERENCES options(id),
    content_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    extracted_json TEXT NOT NULL CHECK (json_valid(extracted_json)),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    valid INTEGER NOT NULL CHECK (valid IN (0, 1)),
    invalid_reasons TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(invalid_reasons)),
    created_at TEXT NOT NULL,
    UNIQUE (option_id, content_hash, model)
);
CREATE TABLE offer_items (
    id INTEGER PRIMARY KEY,
    option_id INTEGER NOT NULL REFERENCES options(id),
    procedure_id TEXT NOT NULL,
    brand_id TEXT,
    tier TEXT NOT NULL CHECK (tier IN ('import', 'domestic', 'single', 'unknown')),
    quantity REAL CHECK (quantity > 0),
    unit TEXT CHECK (unit IN ('shot', 'unit', 'cc', 'session', 'area', 'vial')),
    area TEXT,
    sessions INTEGER NOT NULL CHECK (sessions > 0),
    is_bundle INTEGER NOT NULL CHECK (is_bundle IN (0, 1)),
    price_from INTEGER NOT NULL CHECK (price_from IN (0, 1)),
    conditions TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(conditions)),
    extra_fees TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(extra_fees)),
    vat TEXT NOT NULL CHECK (vat IN ('included', 'excluded', 'unknown')),
    unit_price_krw REAL CHECK (unit_price_krw > 0),
    bucket_key TEXT
);
CREATE TABLE bucket_stats (
    date TEXT NOT NULL,
    bucket_key TEXT NOT NULL,
    n INTEGER NOT NULL CHECK (n >= 0),
    p5 REAL,
    p25 REAL,
    median REAL,
    p75 REAL,
    PRIMARY KEY (date, bucket_key)
);
CREATE TABLE labels (
    date TEXT NOT NULL,
    offer_item_id INTEGER NOT NULL REFERENCES offer_items(id),
    label TEXT NOT NULL CHECK (
        label IN ('cheap', 'normal', 'expensive', 'anomaly_low', 'unranked')
    ),
    PRIMARY KEY (date, offer_item_id)
);
CREATE TABLE raw_snapshots (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    http_status INTEGER NOT NULL,
    body_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    snapshot_kind TEXT NOT NULL DEFAULT 'fact_projection_v1',
    UNIQUE (source, url, sha256)
);
CREATE TABLE dictionary_proposals (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    term_raw TEXT NOT NULL,
    suggested_procedure TEXT NOT NULL,
    reason TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 0 CHECK (seen_count >= 0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'applied', 'rejected')),
    UNIQUE (date, term_raw, suggested_procedure)
);
CREATE TABLE daily_reports (
    date TEXT PRIMARY KEY,
    report_json TEXT NOT NULL CHECK (json_valid(report_json)),
    published INTEGER NOT NULL DEFAULT 0 CHECK (published IN (0, 1))
);
CREATE TABLE run_log (
    run_id TEXT NOT NULL,
    step TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER CHECK (ok IN (0, 1)),
    counts_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(counts_json)),
    error TEXT,
    PRIMARY KEY (run_id, step)
);
CREATE TABLE source_state (
    source TEXT NOT NULL,
    date TEXT NOT NULL,
    stopped INTEGER NOT NULL DEFAULT 0 CHECK (stopped IN (0, 1)),
    reason TEXT,
    PRIMARY KEY (source, date)
);
CREATE TABLE discovered_urls (
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    lastmod TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_fetched TEXT,
    fetched_lastmod TEXT,
    last_outcome TEXT,
    PRIMARY KEY (source, url)
);
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY,
    source TEXT,
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0 CHECK (delivered IN (0, 1)),
    UNIQUE (source, date, code)
);
CREATE INDEX ix_events_clinic ON events(clinic_id, status);
CREATE INDEX ix_options_event ON options(event_id, active);
CREATE INDEX ix_offer_bucket ON offer_items(bucket_key);
CREATE INDEX ix_history_date ON option_history(observed_date);
-- Only structured facts are exposed to the future analyst. No raw titles/names/areas.
CREATE VIEW v_offers AS
SELECT i.id AS offer_item_id, i.option_id, e.id AS event_id, e.clinic_id,
       e.source, e.status, i.procedure_id, i.brand_id, i.tier, i.quantity, i.unit,
       i.sessions, i.is_bundle, i.price_from, i.conditions, i.extra_fees, i.vat,
       i.unit_price_krw, i.bucket_key, o.price_krw, o.coupon_price_krw,
       e.last_seen AS observed_date
FROM offer_items i JOIN options o ON o.id = i.option_id JOIN events e ON e.id = o.event_id
WHERE o.active = 1 AND e.status = 'active';
CREATE VIEW v_bucket_stats AS SELECT date, bucket_key, n, p5, p25, median, p75 FROM bucket_stats;
CREATE VIEW v_price_changes AS
SELECT option_id, observed_date, price_krw,
       LAG(price_krw) OVER (PARTITION BY option_id ORDER BY observed_date) AS previous_price_krw
FROM option_history;
