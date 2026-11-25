ALTER TABLE options ADD COLUMN vat TEXT NOT NULL DEFAULT 'unknown'
    CHECK (vat IN ('included', 'excluded', 'unknown'));
ALTER TABLE options ADD COLUMN extra_fees TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(extra_fees));
ALTER TABLE offer_items ADD COLUMN content_hash TEXT;
CREATE TABLE source_runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    date TEXT NOT NULL,
    ok INTEGER NOT NULL CHECK (ok IN (0, 1)),
    discovered INTEGER NOT NULL DEFAULT 0,
    collected INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    UNIQUE(source, date)
);
CREATE TABLE event_absences (
    event_id INTEGER NOT NULL REFERENCES events(id),
    date TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(reason IN ('sitemap_missing', 'http_404')),
    PRIMARY KEY(event_id, date)
);
CREATE TABLE ai_calls (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    purpose TEXT NOT NULL,
    model TEXT NOT NULL,
    reserved_usd TEXT NOT NULL,
    actual_usd TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    state TEXT NOT NULL CHECK(state IN ('reserved', 'complete', 'failed')),
    created_at TEXT NOT NULL
);
CREATE TABLE exchange_rates (
    date TEXT PRIMARY KEY,
    observed_date TEXT NOT NULL,
    krw_cny TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE TABLE proposal_evidence (
    proposal_id INTEGER NOT NULL REFERENCES dictionary_proposals(id),
    option_id INTEGER NOT NULL REFERENCES options(id),
    PRIMARY KEY(proposal_id, option_id)
);
CREATE TABLE publication_state (
    id INTEGER PRIMARY KEY CHECK(id=1),
    published_at TEXT NOT NULL,
    path TEXT NOT NULL
);
DROP VIEW v_offers;
CREATE VIEW v_offers AS
SELECT i.id AS offer_item_id, i.option_id, e.id AS event_id, e.clinic_id,
       e.source, e.status, i.procedure_id, i.brand_id, i.tier, i.quantity, i.unit,
       i.sessions, i.is_bundle, i.price_from, i.conditions, i.extra_fees, i.vat,
       i.unit_price_krw, i.bucket_key, o.price_krw, o.coupon_price_krw,
       e.last_seen AS observed_date
FROM offer_items i JOIN options o ON o.id=i.option_id JOIN events e ON e.id=o.event_id
WHERE o.active=1 AND e.status='active' AND i.content_hash=o.content_hash
AND EXISTS (SELECT 1 FROM extractions x WHERE x.option_id=o.id
            AND x.content_hash=o.content_hash AND x.valid=1);
