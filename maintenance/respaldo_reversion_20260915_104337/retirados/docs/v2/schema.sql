PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at_utc TEXT NOT NULL
);
CREATE TABLE profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    integration_enabled INTEGER NOT NULL DEFAULT 0 CHECK (integration_enabled IN (0,1)),
    created_at_utc TEXT NOT NULL
);
CREATE TABLE local_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
CREATE TABLE encryption_keys (
    id TEXT PRIMARY KEY,
    wrapped_key BLOB NOT NULL,
    provider TEXT NOT NULL CHECK(provider = 'windows-dpapi'),
    created_at_utc TEXT NOT NULL
);
CREATE TABLE secrets (
    id TEXT PRIMARY KEY,
    key_id TEXT NOT NULL REFERENCES encryption_keys(id),
    nonce BLOB NOT NULL,
    ciphertext BLOB NOT NULL,
    UNIQUE(key_id, nonce)
);
CREATE TABLE devices (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(id),
    device_code TEXT NOT NULL,
    name TEXT NOT NULL,
    brand TEXT NOT NULL CHECK(brand IN ('zkteco','hikvision')),
    protocol TEXT NOT NULL,
    model TEXT,
    host TEXT NOT NULL,
    port INTEGER NOT NULL CHECK(port BETWEEN 1 AND 65535),
    username TEXT,
    secret_id TEXT REFERENCES secrets(id),
    timezone TEXT NOT NULL DEFAULT 'America/Argentina/Buenos_Aires',
    options_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    UNIQUE(profile_id, device_code)
);
CREATE TABLE external_connections (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(id),
    name TEXT NOT NULL,
    dialect TEXT NOT NULL,
    host TEXT,
    port INTEGER CHECK(port BETWEEN 1 AND 65535),
    database_name TEXT,
    username TEXT,
    secret_id TEXT REFERENCES secrets(id),
    options_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE destination_mappings (
    id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL REFERENCES external_connections(id),
    schema_name TEXT,
    table_name TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    datetime_mode TEXT NOT NULL CHECK(datetime_mode IN ('combined','split')),
    columns_json TEXT NOT NULL,
    event_values_json TEXT NOT NULL DEFAULT '{}',
    employee_resolver_json TEXT NOT NULL,
    organization_json TEXT NOT NULL,
    idempotency_column TEXT
);
CREATE TABLE attendance (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES devices(id),
    card_number TEXT NOT NULL,
    occurred_at_local TEXT NOT NULL,
    timezone TEXT NOT NULL,
    occurred_at_utc TEXT,
    source_timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    verification_method TEXT NOT NULL,
    source_event_id TEXT,
    fingerprint TEXT NOT NULL UNIQUE,
    downloaded_at_utc TEXT NOT NULL
);
CREATE INDEX attendance_filter ON attendance(device_id, occurred_at_local, card_number);
CREATE TABLE export_batches (
    id TEXT PRIMARY KEY,
    mapping_id TEXT NOT NULL REFERENCES destination_mappings(id),
    mapping_revision INTEGER NOT NULL,
    organization_id TEXT,
    started_at_utc TEXT NOT NULL,
    finished_at_utc TEXT,
    status TEXT NOT NULL CHECK(status IN ('running','completed','failed','cancelled','uncertain')),
    error_code TEXT
);
CREATE TABLE export_items (
    batch_id TEXT NOT NULL REFERENCES export_batches(id),
    attendance_id TEXT NOT NULL REFERENCES attendance(id),
    target_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','confirmed','failed','uncertain')),
    error_code TEXT,
    PRIMARY KEY(batch_id, attendance_id)
);
CREATE INDEX export_identity ON export_items(target_key, attendance_id, status);
CREATE TABLE license_state (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    secret_id TEXT NOT NULL UNIQUE REFERENCES secrets(id)
);
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    profile_id TEXT REFERENCES profiles(id),
    operation TEXT NOT NULL,
    entity_id TEXT,
    occurred_at_utc TEXT NOT NULL,
    result_code TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);
