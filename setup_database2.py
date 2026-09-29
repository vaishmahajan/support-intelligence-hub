#!/usr/bin/env python3
"""
Database ingestion script for Capstone2.
Reads source Excel/CSV data and populates a PostgreSQL database (with SQLite fallback).

Usage:
    python setup_database2.py --from-source
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from passlib.context import CryptContext
from sqlalchemy import create_engine, text

try:
    load_dotenv()
except (AssertionError, Exception):
    pass

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = Path(__file__).parent / "capstone2.db"
DATABASE_URL = os.getenv("DATABASE_URL", "")

ACCOUNT_FILE = DATA_DIR / "accounts.csv"
CASES_FILE = DATA_DIR / "support_cases.xlsx"
ASSOCIATES_FILE = DATA_DIR / "associates.xlsx"

# Account HQ + one-line background, keyed by account_name.
#
# This is customer information, so it is NOT stored in this file. It is read
# from an optional JSON map beside the source data, and `data/` is gitignored.
# Missing file, or an account that is not in it, simply leaves hq_location and
# company_background NULL — the dashboards already handle that.
#
#   data/company_backgrounds.json
#   { "Example Corp": ["Berlin, Germany", "One-line description."] }
#
# `demo_data/company_backgrounds.json` ships a fictional one for the demo set.
BACKGROUNDS_FILE = DATA_DIR / "company_backgrounds.json"


def _load_company_backgrounds():
    if not BACKGROUNDS_FILE.exists():
        return {}
    try:
        with open(BACKGROUNDS_FILE, encoding="utf-8") as fh:
            return {k: tuple(v) for k, v in json.load(fh).items()}
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print(f"  warning: could not read {BACKGROUNDS_FILE.name} ({exc}); "
              f"HQ and background will be left empty")
        return {}


COMPANY_BACKGROUNDS = _load_company_backgrounds()

STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "because", "but", "and", "or", "if", "while", "that", "this", "it",
    "its", "also", "which", "what", "who", "whom", "their", "they", "them",
    "we", "he", "she", "his", "her", "our", "my", "your", "up",
    "about", "i", "me", "you", "us", "him",
    "customer", "issue", "issues", "error", "errors", "support", "case",
    "reported", "needs", "using", "used", "related", "due", "first",
    "production", "environment", "experiencing", "affecting", "observed",
    "logs", "show", "backend", "services", "configuration", "change",
    "resolution", "requested", "escalation", "monitoring", "detected",
    "anomaly", "confirmed", "immediate", "patching", "alert", "triggered",
    "critical", "system", "automated", "engineer", "users", "timeline",
    "connection", "refused", "morning", "monday", "window", "release",
    "upcoming", "read", "disk", "filesystem", "remount", "data",
}

PRODUCT_SKILL_KEYWORDS = {
    "openshift": "OpenShift",
    "kubernetes": "Kubernetes",
    "ansible": "Ansible",
    "satellite": "Red Hat Satellite",
    "rhel": "RHEL Administration",
    "enterprise linux": "RHEL Administration",
    "jboss": "JBoss Middleware",
    "eap": "JBoss EAP",
    "keycloak": "Identity Management",
    "single sign-on": "Identity Management",
    "sso": "Identity Management",
    "3scale": "API Management",
    "api management": "API Management",
    "ceph": "Ceph Storage",
    "gluster": "GlusterFS",
    "openstack": "OpenStack",
    "stack": "OpenStack",
    "virtualization": "Virtualization",
    "migration toolkit": "Migration Toolkit",
    "certificate": "Certificate Management",
    "directory server": "Directory Services",
    "ldap": "Directory Services",
    "smart management": "Smart Management",
    "insights": "Red Hat Insights",
    "cloudforms": "CloudForms",
    "quay": "Quay Registry",
    "acm": "Advanced Cluster Management",
    "advanced cluster": "Advanced Cluster Management",
    "serverless": "Serverless/Knative",
    "knative": "Serverless/Knative",
    "service mesh": "Service Mesh/Istio",
    "istio": "Service Mesh/Istio",
    "amq": "AMQ Messaging",
    "kafka": "AMQ Streams/Kafka",
    "fuse": "Red Hat Fuse",
    "integration": "Integration",
    "container": "Container Platform",
    "podman": "Container Tools",
    "buildah": "Container Tools",
    "kernel": "Kernel/OS",
    "networking": "Networking",
    "storage": "Storage",
    "performance": "Performance Tuning",
    "security": "Security/Compliance",
    "compliance": "Security/Compliance",
    "upgrade": "Upgrades & Migration",
    "migration": "Upgrades & Migration",
    "backup": "Backup & Recovery",
    "disaster recovery": "Backup & Recovery",
    "ha ": "High Availability",
    "high availability": "High Availability",
    "cluster": "Clustering",
    "monitoring": "Monitoring & Observability",
    "prometheus": "Monitoring & Observability",
    "grafana": "Monitoring & Observability",
    "troubleshooting": "Troubleshooting",
    "debugging": "Debugging",
    "rhoai": "OpenShift AI",
    "machine learning": "OpenShift AI",
    "ocs": "OpenShift Container Storage",
    "data foundation": "OpenShift Data Foundation",
}


def revenue_bucket(revenue):
    if pd.isna(revenue):
        return "Unknown"
    r = float(revenue)
    if r < 1_000_000:
        return "< $1M"
    elif r < 5_000_000:
        return "$1M - $5M"
    elif r < 10_000_000:
        return "$5M - $10M"
    elif r < 25_000_000:
        return "$10M - $25M"
    elif r < 50_000_000:
        return "$25M - $50M"
    else:
        return "> $50M"


def extract_skills_for_associate(associate_row, cases_df):
    skills = Counter()
    name = associate_row["associate_name"]
    sbr = associate_row.get("sbr", "")
    certs = str(associate_row.get("certifications", ""))

    owner_cases = cases_df[cases_df["case_owner"] == name]
    combined_text = " ".join(
        owner_cases["product_name"].dropna().tolist()
        + owner_cases["description"].dropna().tolist()
        + owner_cases["problem_statement"].dropna().tolist()
    ).lower()

    for keyword, skill_name in PRODUCT_SKILL_KEYWORDS.items():
        if keyword in combined_text:
            skills[skill_name] += combined_text.count(keyword)

    if sbr:
        sbr_lower = sbr.strip().lower()
        for keyword, skill_name in PRODUCT_SKILL_KEYWORDS.items():
            if keyword in sbr_lower:
                skills[skill_name] += 5

    cert_lower = certs.lower()
    cert_mappings = {
        "rhce": "RHEL Administration",
        "rhcsa": "RHEL Administration",
        "cka": "Kubernetes",
        "ckad": "Kubernetes",
        "ansible": "Ansible",
        "openshift": "OpenShift",
        "aws": "Cloud (AWS)",
        "azure": "Cloud (Azure)",
        "gcp": "Cloud (GCP)",
    }
    for cert_key, skill_name in cert_mappings.items():
        if cert_key in cert_lower:
            skills[skill_name] += 3

    return skills.most_common(5)


def load_accounts(engine):
    df = pd.read_csv(ACCOUNT_FILE)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    df["revenue_segment"] = df["annual_revenue"].apply(revenue_bucket)

    hqs = []
    backgrounds = []
    for name in df["account_name"]:
        info = COMPANY_BACKGROUNDS.get(name, (None, None))
        hqs.append(info[0])
        backgrounds.append(info[1])
    df["hq_location"] = hqs
    df["company_background"] = backgrounds

    for col in ["contract_start_date", "contract_end_date", "created_at"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    _mode = "append" if DATABASE_URL.startswith("postgresql") else "replace"
    df.to_sql("accounts", engine, if_exists=_mode, index=False)
    print(f"  accounts: {len(df)} rows loaded")
    return df


def load_support_cases(engine):
    df = pd.read_excel(CASES_FILE)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    if "sbr" in df.columns:
        df["sbr"] = df["sbr"].str.strip()

    for col in ["creation_date", "last_updated", "resolution_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    if "creation_date" in df.columns and "resolution_date" in df.columns:
        resolved = df["resolution_date"].notna() & df["creation_date"].notna()
        df.loc[resolved, "time_to_resolve_hours"] = (
            (df.loc[resolved, "resolution_date"] - df.loc[resolved, "creation_date"])
            .dt.total_seconds() / 3600
        ).round(2)

    _mode = "append" if DATABASE_URL.startswith("postgresql") else "replace"
    df.to_sql("support_cases", engine, if_exists=_mode, index=False)
    print(f"  support_cases: {len(df)} rows loaded")
    return df


def load_associates(engine):
    df = pd.read_excel(ASSOCIATES_FILE)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    if "hire_date" in df.columns:
        df["hire_date"] = pd.to_datetime(df["hire_date"], errors="coerce")

    _mode = "append" if DATABASE_URL.startswith("postgresql") else "replace"
    df.to_sql("associates", engine, if_exists=_mode, index=False)
    print(f"  associates: {len(df)} rows loaded")
    return df


def build_skills_table(engine, associates_df, cases_df):
    skills_rows = []
    for _, row in associates_df.iterrows():
        top_skills = extract_skills_for_associate(row, cases_df)
        for rank, (skill_name, score) in enumerate(top_skills, start=1):
            skills_rows.append({
                "associate_id": row["associate_id"],
                "associate_name": row["associate_name"],
                "skill_name": skill_name,
                "skill_rank": rank,
                "relevance_score": score,
            })
    skills_df = pd.DataFrame(skills_rows)
    _mode = "append" if DATABASE_URL.startswith("postgresql") else "replace"
    skills_df.to_sql("skills", engine, if_exists=_mode, index=False)
    print(f"  skills: {len(skills_df)} rows loaded ({associates_df.shape[0]} associates)")


def create_indexes(engine):
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_accounts_account_id ON accounts(account_id)",
        "CREATE INDEX IF NOT EXISTS idx_accounts_region ON accounts(region)",
        "CREATE INDEX IF NOT EXISTS idx_accounts_sector ON accounts(sector)",
        "CREATE INDEX IF NOT EXISTS idx_accounts_support_tier ON accounts(support_tier)",
        "CREATE INDEX IF NOT EXISTS idx_accounts_revenue_segment ON accounts(revenue_segment)",
        "CREATE INDEX IF NOT EXISTS idx_cases_account_id ON support_cases(account_id)",
        "CREATE INDEX IF NOT EXISTS idx_cases_sbr ON support_cases(sbr)",
        "CREATE INDEX IF NOT EXISTS idx_cases_status ON support_cases(status)",
        "CREATE INDEX IF NOT EXISTS idx_cases_product ON support_cases(product_name)",
        "CREATE INDEX IF NOT EXISTS idx_cases_severity ON support_cases(severity)",
        "CREATE INDEX IF NOT EXISTS idx_cases_escalated ON support_cases(escalated)",
        "CREATE INDEX IF NOT EXISTS idx_cases_case_owner ON support_cases(case_owner)",
        "CREATE INDEX IF NOT EXISTS idx_cases_creation_date ON support_cases(creation_date)",
        "CREATE INDEX IF NOT EXISTS idx_associates_sbr ON associates(sbr)",
        "CREATE INDEX IF NOT EXISTS idx_associates_manager ON associates(manager_name)",
        "CREATE INDEX IF NOT EXISTS idx_associates_associate_id ON associates(associate_id)",
        "CREATE INDEX IF NOT EXISTS idx_skills_associate_id ON skills(associate_id)",
        "CREATE INDEX IF NOT EXISTS idx_skills_skill_name ON skills(skill_name)",
    ]
    with engine.begin() as conn:
        for idx_sql in indexes:
            conn.execute(text(idx_sql))
    print(f"  indexes: {len(indexes)} created")


# Identities of the two seeded logins. Real names belong to the source data,
# so they are read from an optional gitignored file and fall back to the demo
# dataset's own engineers:
#
#   data/seed_users.json
#   [{"email": "...", "role": "manager", "display_name": "..."}]
#
# No password lives in that file, or in this one. Both come from the
# environment, defaulting to the documented development values.
SEED_USERS_FILE = DATA_DIR / "seed_users.json"

_DEMO_SEED_USERS = [
    {"email": "adaeze.nwachukwu@redhat.com", "role": "manager",
     "display_name": "Adaeze Nwachukwu"},
    {"email": "theo.krishnan@redhat.com", "role": "associate",
     "display_name": "Theo Krishnan"},
]


def _load_seed_users():
    if not SEED_USERS_FILE.exists():
        return _DEMO_SEED_USERS
    try:
        with open(SEED_USERS_FILE, encoding="utf-8") as fh:
            users = json.load(fh)
        if not isinstance(users, list) or not users:
            raise ValueError("expected a non-empty list")
        return users
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print(f"  warning: could not read {SEED_USERS_FILE.name} ({exc}); "
              f"seeding the demo users instead")
        return _DEMO_SEED_USERS


def seed_test_users(engine):
    _pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    _pw_for = {
        "manager": os.getenv("SEED_MANAGER_PASSWORD", "manager123"),
        "associate": os.getenv("SEED_ASSOCIATE_PASSWORD", "associate123"),
    }
    users = [
        (u["email"], _pwd.hash(_pw_for.get(u["role"], "associate123")),
         u["role"], u["display_name"])
        for u in _load_seed_users()
    ]
    is_pg = DATABASE_URL.startswith("postgresql")
    with engine.begin() as conn:
        if not is_pg:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS registered_users ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "email VARCHAR(200) UNIQUE NOT NULL,"
                "password_hash TEXT NOT NULL,"
                "role VARCHAR(20) NOT NULL CHECK(role IN ('manager','associate')),"
                "display_name TEXT NOT NULL,"
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            ))
        for email, pw_hash, role, name in users:
            if is_pg:
                conn.execute(text(
                    "INSERT INTO registered_users (email, password_hash, role, display_name) "
                    "VALUES (:e, :p, :r, :n) ON CONFLICT (email) DO NOTHING"
                ), {"e": email, "p": pw_hash, "r": role, "n": name})
            else:
                conn.execute(text(
                    "INSERT OR IGNORE INTO registered_users (email, password_hash, role, display_name) "
                    "VALUES (:e, :p, :r, :n)"
                ), {"e": email, "p": pw_hash, "r": role, "n": name})
    print(f"  test users: {len(users)} seeded (manager + associate)")


def verify_database(engine):
    with engine.connect() as conn:
        tables = ["accounts", "support_cases", "associates", "skills"]
        print("\n  Verification:")
        for table in tables:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
            print(f"    {table}: {count} rows")


def main():
    parser = argparse.ArgumentParser(description="Capstone2 Database Setup")
    parser.add_argument(
        "--from-source",
        action="store_true",
        default=True,
        help="Load data from source CSV/Excel files in ./data/ (default)",
    )
    args = parser.parse_args()

    missing = [f for f in [ACCOUNT_FILE, CASES_FILE, ASSOCIATES_FILE] if not f.exists()]
    if missing:
        print(f"ERROR: Missing source files: {missing}", file=sys.stderr)
        sys.exit(1)

    if DATABASE_URL.startswith("postgresql"):
        engine = create_engine(DATABASE_URL)
        print(f"Connecting to PostgreSQL...")
    else:
        if DB_PATH.exists():
            DB_PATH.unlink()
            print(f"Removed existing {DB_PATH.name}")
        engine = create_engine(f"sqlite:///{DB_PATH}")
        print(f"Creating {DB_PATH.name}...")

    if DATABASE_URL.startswith("postgresql"):
        with engine.begin() as conn:
            for tbl in ["skills", "support_cases", "associates", "accounts", "registered_users"]:
                conn.execute(text(f"DROP TABLE IF EXISTS {tbl} CASCADE"))
            print("  Cleared existing tables")
        with engine.begin() as conn:
            schema_path = Path(__file__).parent / "db" / "init" / "01_schema.sql"
            conn.execute(text(schema_path.read_text()))
            print("  Re-created schema")

    accounts_df = load_accounts(engine)
    cases_df = load_support_cases(engine)
    associates_df = load_associates(engine)
    build_skills_table(engine, associates_df, cases_df)
    create_indexes(engine)
    seed_test_users(engine)
    verify_database(engine)

    if DATABASE_URL.startswith("postgresql"):
        print(f"\nDone. Data loaded into PostgreSQL.")
    else:
        print(f"\nDone. Database saved to {DB_PATH}")


if __name__ == "__main__":
    main()
