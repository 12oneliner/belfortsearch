-- Миграция 001: начальная схема (ТЗ п.13).
-- Компании, контакты, проверки сайтов, запуски, ошибки источников, дубли.

CREATE TABLE IF NOT EXISTS companies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    niche TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    address TEXT,
    phone TEXT,
    normalized_phone TEXT NOT NULL DEFAULT '',
    normalized_name TEXT NOT NULL DEFAULT '',
    card_url TEXT,
    source_name TEXT NOT NULL DEFAULT '',
    rating REAL,
    reviews_count INTEGER,
    website_status TEXT NOT NULL DEFAULT 'NOT_CHECKED',
    score INTEGER NOT NULL DEFAULT 0,
    score_explanation TEXT,
    rejection_reason TEXT,
    processing_status TEXT NOT NULL DEFAULT 'found',
    first_seen TEXT NOT NULL DEFAULT '',
    last_checked TEXT NOT NULL DEFAULT '',
    last_review_date TEXT,
    has_work_photos INTEGER,
    social_activity TEXT
);

CREATE INDEX IF NOT EXISTS idx_companies_norm_phone ON companies(normalized_phone);
CREATE INDEX IF NOT EXISTS idx_companies_norm_name ON companies(normalized_name);
CREATE INDEX IF NOT EXISTS idx_companies_city ON companies(city);
CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(processing_status);
CREATE INDEX IF NOT EXISTS idx_companies_score ON companies(score DESC);

CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_type TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL DEFAULT '',
    role TEXT,
    source TEXT NOT NULL DEFAULT '',
    proof_url TEXT,
    confidence TEXT NOT NULL DEFAULT 'low'
);

CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company_id);

CREATE TABLE IF NOT EXISTS website_checks (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'NOT_CHECKED',
    evidence TEXT,
    checked_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_website_checks_company ON website_checks(company_id);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT,
    niche TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    sources TEXT NOT NULL DEFAULT '[]',
    target_leads INTEGER NOT NULL DEFAULT 50,
    found INTEGER NOT NULL DEFAULT 0,
    unique_count INTEGER NOT NULL DEFAULT 0,
    checked_websites INTEGER NOT NULL DEFAULT 0,
    confirmed_no_website INTEGER NOT NULL DEFAULT 0,
    quality_leads INTEGER NOT NULL DEFAULT 0,
    rejected INTEGER NOT NULL DEFAULT 0,
    doubtful INTEGER NOT NULL DEFAULT 0,
    errors TEXT
);

CREATE TABLE IF NOT EXISTS source_errors (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_source_errors_run ON source_errors(run_id);

CREATE TABLE IF NOT EXISTS duplicates (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    duplicate_of_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    auto_merged INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_duplicates_company ON duplicates(company_id);

CREATE TABLE IF NOT EXISTS history (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL DEFAULT '',
    old_value TEXT,
    new_value TEXT,
    changed_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_history_company ON history(company_id);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT ''
);
