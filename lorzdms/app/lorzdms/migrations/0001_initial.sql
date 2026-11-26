-- LorzDMS Grundschema. Zeitstempel als ISO-8601-UTC-Text, JSON als Text.

CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    ha_user_id TEXT UNIQUE,
    name TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'none' CHECK (role IN ('none','viewer','editor','admin')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_seen_at TEXT
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE secrets (
    key TEXT PRIMARY KEY,
    ciphertext BLOB NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE google_accounts (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    scopes TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'connected',
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE sources (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('local','upload','gmail','drive')),
    name TEXT NOT NULL,
    account_id INTEGER REFERENCES google_accounts(id),
    config TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    poll_interval_seconds INTEGER NOT NULL DEFAULT 300,
    cursor TEXT,
    last_sync_at TEXT,
    last_status TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL
);

-- Freigegebene Drive-Ordner. Schreiboperationen nur unterhalb von role='archive'
-- bzw. role='review'. role='inbox' darf nur gelesen und daraus verschoben werden.
CREATE TABLE drive_folders (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES google_accounts(id),
    drive_id TEXT NOT NULL,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    parent_drive_id TEXT,
    role TEXT NOT NULL CHECK (role IN ('archive_root','archive','inbox','review')),
    description TEXT,
    synced_at TEXT,
    UNIQUE (account_id, drive_id)
);

CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    source_id INTEGER REFERENCES sources(id),
    source_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    mime_type TEXT,
    size_bytes INTEGER,
    sha256 TEXT,
    md5 TEXT,
    text_sha256 TEXT,
    state TEXT NOT NULL,
    state_changed_at TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'members' CHECK (visibility IN ('members','admins')),
    title TEXT,
    document_type TEXT,
    sender TEXT,
    document_date TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    email_meta TEXT,
    confidence REAL,
    decision TEXT,
    target_folder_drive_id TEXT,
    target_name TEXT,
    drive_file_id TEXT,
    drive_web_link TEXT,
    signed_pdf INTEGER NOT NULL DEFAULT 0,
    ocr_used INTEGER NOT NULL DEFAULT 0,
    ocr_seconds REAL,
    page_count INTEGER,
    duplicate_of INTEGER REFERENCES documents(id),
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    UNIQUE (source_kind, source_ref)
);
CREATE INDEX idx_documents_state ON documents(state);
CREATE INDEX idx_documents_sha256 ON documents(sha256);
CREATE INDEX idx_documents_created ON documents(created_at);

CREATE TABLE document_text (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    pages TEXT NOT NULL DEFAULT '[]',
    method TEXT NOT NULL
);

-- Volltextindex (SQLite-spezifisch, rowid = documents.id)
CREATE VIRTUAL TABLE documents_fts USING fts5(
    title, filename, sender, document_type, body,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- Verarbeitungsjournal: keine Dokumenteninhalte, nur Schritte und Metadaten.
CREATE TABLE journal (
    id INTEGER PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    step TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok','info','warn','error')),
    message TEXT NOT NULL,
    data TEXT
);
CREATE INDEX idx_journal_doc ON journal(document_id);
CREATE INDEX idx_journal_ts ON journal(ts);

-- Jede Drive-Veränderung wird vor der Ausführung festgehalten (Rückgängig-Funktion).
CREATE TABLE drive_operations (
    id INTEGER PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    kind TEXT NOT NULL CHECK (kind IN ('move','upload','undo')),
    drive_file_id TEXT,
    from_parents TEXT,
    to_parent TEXT NOT NULL,
    old_name TEXT,
    new_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','done','failed','undone')),
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE rules (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    enabled INTEGER NOT NULL DEFAULT 1,
    conditions TEXT NOT NULL,
    actions TEXT NOT NULL,
    stop_processing INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    priority INTEGER NOT NULL DEFAULT 100,
    state TEXT NOT NULL CHECK (state IN ('queued','running','done','dead','cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    run_after TEXT NOT NULL,
    lease_until TEXT,
    worker TEXT,
    dedupe_key TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX idx_jobs_claim ON jobs(state, priority, run_after);
CREATE UNIQUE INDEX idx_jobs_dedupe ON jobs(dedupe_key) WHERE dedupe_key IS NOT NULL AND state IN ('queued','running');

CREATE TABLE oauth_states (
    state TEXT PRIMARY KEY,
    code_verifier TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    scopes TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id),
    expires_at TEXT NOT NULL
);

-- Sicherheitsrelevantes Audit-Log (keine Dokumenteninhalte).
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    target TEXT,
    details TEXT
);
