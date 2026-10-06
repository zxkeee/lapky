-- Користувачі (через Telegram), менеджери притулків, заявки на додавання / «це мій притулок».
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL UNIQUE,
    username    TEXT,
    first_name  TEXT,
    role        TEXT    NOT NULL DEFAULT 'volunteer',  -- volunteer / admin
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS shelter_managers (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    shelter_id INTEGER NOT NULL REFERENCES shelters(id) ON DELETE CASCADE,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, shelter_id)
);
CREATE INDEX IF NOT EXISTS idx_managers_shelter ON shelter_managers(shelter_id);

CREATE TABLE IF NOT EXISTS applications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT    NOT NULL,                       -- new_shelter / claim
    shelter_id INTEGER REFERENCES shelters(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    payload    TEXT    NOT NULL DEFAULT '{}',          -- JSON
    status     TEXT    NOT NULL DEFAULT 'pending',     -- pending / approved / rejected
    admin_note TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
