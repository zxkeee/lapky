CREATE TABLE IF NOT EXISTS shelters (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    urgency_level  TEXT    NOT NULL DEFAULT 'white'
                   CHECK (urgency_level IN ('red', 'orange', 'white', 'green')),
    city           TEXT    NOT NULL,
    district       TEXT,
    address        TEXT    NOT NULL,
    lat            REAL    NOT NULL,
    lng            REAL    NOT NULL,
    phone          TEXT,
    contact_person TEXT,
    social_links   TEXT    NOT NULL DEFAULT '[]',   -- JSON-масив посилань
    requisites     TEXT,                            -- IBAN / номер картки
    bank           TEXT,
    source_url     TEXT,                            -- звідки взяли дані
    verified_at    TEXT,                            -- дата останньої перевірки (YYYY-MM-DD)
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS needs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shelter_id  INTEGER NOT NULL REFERENCES shelters(id) ON DELETE CASCADE,
    category    TEXT    NOT NULL
                CHECK (category IN ('housing', 'food', 'care', 'finance', 'volunteer')),
    subcategory TEXT
                CHECK (subcategory IS NULL OR subcategory IN ('kids', 'adult', 'sterilized', 'medical')),
    text        TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_needs_shelter  ON needs(shelter_id);
CREATE INDEX IF NOT EXISTS idx_needs_category ON needs(category, subcategory);
