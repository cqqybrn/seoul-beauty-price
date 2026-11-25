CREATE TABLE extraction_batches (
    name TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    imported INTEGER NOT NULL DEFAULT 0 CHECK(imported IN (0,1))
);
CREATE TABLE extraction_batch_items (
    batch_name TEXT NOT NULL REFERENCES extraction_batches(name),
    option_id INTEGER NOT NULL REFERENCES options(id),
    content_hash TEXT NOT NULL,
    call_id TEXT NOT NULL REFERENCES ai_calls(id),
    PRIMARY KEY(batch_name,option_id)
);
