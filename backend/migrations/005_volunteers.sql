-- Волонтерський функціонал: «беру потребу», підписки, завдання, черга сповіщень для бота.
CREATE TABLE IF NOT EXISTS need_pledges (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    need_id    INTEGER NOT NULL REFERENCES needs(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status     TEXT    NOT NULL DEFAULT 'active',      -- active / done / cancelled
    note       TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pledges_need ON need_pledges(need_id, status);
CREATE INDEX IF NOT EXISTS idx_pledges_user ON need_pledges(user_id, status);

CREATE TABLE IF NOT EXISTS subscriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    shelter_id  INTEGER REFERENCES shelters(id) ON DELETE CASCADE,
    oblast      TEXT,
    only_urgent INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_subscriptions_unique
    ON subscriptions(user_id, COALESCE(shelter_id, 0), COALESCE(oblast, ''));
CREATE INDEX IF NOT EXISTS idx_subscriptions_shelter ON subscriptions(shelter_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_oblast  ON subscriptions(oblast);

CREATE TABLE IF NOT EXISTS volunteer_tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shelter_id  INTEGER NOT NULL REFERENCES shelters(id) ON DELETE CASCADE,
    title       TEXT    NOT NULL,
    description TEXT,
    starts_at   TEXT    NOT NULL,                      -- 'YYYY-MM-DD HH:MM', місцевий час
    slots       INTEGER NOT NULL DEFAULT 1,
    status      TEXT    NOT NULL DEFAULT 'open',       -- open / closed
    reminded    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_shelter ON volunteer_tasks(shelter_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_starts  ON volunteer_tasks(status, starts_at);

CREATE TABLE IF NOT EXISTS task_signups (
    task_id    INTEGER NOT NULL REFERENCES volunteer_tasks(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (task_id, user_id)
);

CREATE TABLE IF NOT EXISTS outbox (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    text        TEXT    NOT NULL,                      -- HTML
    buttons     TEXT    NOT NULL DEFAULT '[]',         -- JSON: [[{"text", "url" | "callback_data"}]]
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    sent_at     TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(sent_at, attempts);
