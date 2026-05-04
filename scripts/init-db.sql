-- Project Aegis — PostgreSQL initialization
-- Runs once when the postgres container is first created.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Audit log (immutable, INSERT only via trigger) ────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type   TEXT        NOT NULL,
    actor        TEXT        NOT NULL,
    payload      JSONB       NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Prevent updates/deletes on the audit log
CREATE OR REPLACE RULE audit_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE OR REPLACE RULE audit_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;

-- ── Blockchain snapshot (optional persistence) ───────────────────────────
CREATE TABLE IF NOT EXISTS blockchain_snapshot (
    id           BIGSERIAL   PRIMARY KEY,
    block_index  INTEGER     NOT NULL UNIQUE,
    block_hash   TEXT        NOT NULL,
    validator    TEXT        NOT NULL,
    block_data   JSONB       NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Security alerts ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS security_alerts (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    severity     TEXT        NOT NULL,
    title        TEXT        NOT NULL,
    description  TEXT,
    score        FLOAT       NOT NULL DEFAULT 0.0,
    resolved     BOOLEAN     NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Oracle: projects & invoices ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS oracle_projects (
    project_id   TEXT        PRIMARY KEY,
    name         TEXT        NOT NULL,
    budget       NUMERIC     NOT NULL,
    frozen       BOOLEAN     NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oracle_invoices (
    invoice_id    UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id    TEXT        NOT NULL REFERENCES oracle_projects(project_id),
    milestone_id  TEXT        NOT NULL,
    amount        NUMERIC     NOT NULL,
    submitted_by  TEXT        NOT NULL,
    status        TEXT        NOT NULL DEFAULT 'pending',
    freeze_reason TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Payment ledger ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS payment_ledger (
    record_id    TEXT        PRIMARY KEY,
    module_id    TEXT        NOT NULL,
    tenant_id    TEXT        NOT NULL,
    event_type   TEXT        NOT NULL,
    unit_price   NUMERIC     NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── VDI sessions ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vdi_sessions (
    session_id    UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id       TEXT        NOT NULL,
    tenant_id     TEXT        NOT NULL,
    state         TEXT        NOT NULL DEFAULT 'provisioning',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    terminated_at TIMESTAMPTZ
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_audit_actor    ON audit_log(actor);
CREATE INDEX IF NOT EXISTS idx_audit_type     ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_alert_severity ON security_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_payment_tenant ON payment_ledger(tenant_id, module_id);
