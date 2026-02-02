CREATE TABLE IF NOT EXISTS access_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code_hash TEXT NOT NULL UNIQUE,
    label TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    access_code_id INTEGER NOT NULL,
    ip_address TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_activity_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (access_code_id) REFERENCES access_codes(id)
);

CREATE TABLE IF NOT EXISTS login_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_address TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 0,
    access_code_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS watch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    access_code_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    check_type TEXT NOT NULL DEFAULT 'html',
    url TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT 'GET',
    headers TEXT DEFAULT '{}',
    body TEXT DEFAULT '',
    selector_type TEXT NOT NULL DEFAULT 'css',
    selector TEXT NOT NULL DEFAULT '',
    notification_type TEXT NOT NULL DEFAULT 'telegram',
    notification_config TEXT NOT NULL DEFAULT '{}',
    message_template TEXT NOT NULL DEFAULT '',
    current_value TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    interval_minutes INTEGER NOT NULL DEFAULT 5,
    last_checked_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (access_code_id) REFERENCES access_codes(id)
);

CREATE TABLE IF NOT EXISTS request_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_item_id INTEGER NOT NULL,
    executed_at TEXT NOT NULL DEFAULT (datetime('now')),
    http_status INTEGER,
    parsed_value TEXT,
    previous_value TEXT,
    value_changed INTEGER NOT NULL DEFAULT 0,
    notification_sent INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    duration_ms INTEGER,
    FOREIGN KEY (watch_item_id) REFERENCES watch_items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
CREATE INDEX IF NOT EXISTS idx_sessions_last_activity ON sessions(last_activity_at);
CREATE INDEX IF NOT EXISTS idx_login_logs_ip_created ON login_logs(ip_address, created_at);
CREATE INDEX IF NOT EXISTS idx_watch_items_status ON watch_items(status);
CREATE INDEX IF NOT EXISTS idx_watch_items_access_code ON watch_items(access_code_id);
CREATE INDEX IF NOT EXISTS idx_request_logs_item_executed ON request_logs(watch_item_id, executed_at);
CREATE INDEX IF NOT EXISTS idx_request_logs_executed ON request_logs(executed_at);
