CREATE TABLE localized_texts (
    source_hash TEXT PRIMARY KEY,
    source_text TEXT NOT NULL,
    text_zh TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);
