-- Capstone2 PostgreSQL Schema
-- Auto-runs on first docker-compose up

CREATE TABLE IF NOT EXISTS accounts (
    account_id      VARCHAR(20) PRIMARY KEY,
    account_name    TEXT NOT NULL,
    sector          VARCHAR(100),
    account_notes   TEXT,
    annual_revenue  BIGINT,
    contract_start_date DATE,
    contract_end_date   DATE,
    support_tier    VARCHAR(50),
    tam_assigned    VARCHAR(200),
    region          VARCHAR(50),
    employee_count  INTEGER,
    created_at      TIMESTAMP DEFAULT NOW(),
    revenue_segment VARCHAR(50),
    hq_location     TEXT,
    company_background TEXT
);

CREATE TABLE IF NOT EXISTS associates (
    associate_id    VARCHAR(20) PRIMARY KEY,
    associate_name  TEXT NOT NULL,
    email           VARCHAR(200),
    sbr             VARCHAR(100),
    shift           VARCHAR(50),
    skill_level     VARCHAR(50),
    manager_name    VARCHAR(200),
    manager_email   VARCHAR(200),
    hire_date       DATE,
    certifications  TEXT,
    active          INTEGER DEFAULT 1,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS support_cases (
    case_number     VARCHAR(30) PRIMARY KEY,
    account_id      VARCHAR(20),
    account_name    TEXT,
    case_owner      VARCHAR(200),
    severity        VARCHAR(50),
    status          VARCHAR(50),
    product_name    VARCHAR(200),
    creation_date   DATE,
    closed_date     DATE,
    escalated       INTEGER DEFAULT 0,
    csat_score      NUMERIC(3,2),
    time_to_resolve_hours NUMERIC(10,2),
    case_summary    TEXT,
    created_at      TIMESTAMP DEFAULT NOW(),
    sbr             VARCHAR(100),
    problem_statement TEXT,
    description     TEXT,
    product_version VARCHAR(100),
    sovereign_support VARCHAR(50),
    business_hours  VARCHAR(50),
    last_updated    DATE,
    resolution_date DATE
);

CREATE TABLE IF NOT EXISTS skills (
    id              SERIAL PRIMARY KEY,
    associate_id    VARCHAR(20) REFERENCES associates(associate_id),
    associate_name  TEXT,
    skill_name      VARCHAR(200),
    skill_rank      INTEGER,
    relevance_score NUMERIC(5,2)
);

CREATE INDEX IF NOT EXISTS idx_cases_owner ON support_cases(case_owner);
CREATE INDEX IF NOT EXISTS idx_cases_account ON support_cases(account_name);
CREATE INDEX IF NOT EXISTS idx_cases_severity ON support_cases(severity);
CREATE INDEX IF NOT EXISTS idx_skills_assoc ON skills(associate_id);
CREATE INDEX IF NOT EXISTS idx_associates_sbr ON associates(sbr);

CREATE TABLE IF NOT EXISTS registered_users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(200) UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    role            VARCHAR(20) NOT NULL CHECK(role IN ('manager','associate')),
    display_name    TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW()
);
