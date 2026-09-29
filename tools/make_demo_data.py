#!/usr/bin/env python3
"""Generate the synthetic demo dataset in `demo_data/`.

    python tools/make_demo_data.py

The real dataset this project was built against is Red Hat customer data and is
never committed — `data/` is gitignored. This script produces a structurally
identical stand-in so that a fresh clone can be run end to end:

    demo_data/accounts.csv            30 fictional accounts
    demo_data/associates.xlsx         25 fictional engineers under 5 managers
    demo_data/support_cases.xlsx     250 fictional cases
    demo_data/company_backgrounds.json  optional HQ + blurb lookup
    demo_data/seed_users.json           the two demo logins

Every company and person here is invented. The category vocabularies (sectors,
regions, severities, SBR teams, Red Hat product names) are real because the
application's filters, colour maps and scoring weights key off those exact
strings — see handbook Chapter 5.

The seed is fixed, so everyone who runs this gets byte-identical files and the
worked examples in the documentation stay true.
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "demo_data"
SEED = 20260930
# The reference clock. Cases are generated behind this date so that "age" and
# every SLA calculation behave the same way they do on the real extract.
AS_OF = datetime(2026, 6, 11)

rng = random.Random(SEED)

# ── vocabularies (real strings — the app keys off them) ───────────────────

SECTORS = ["Aerospace & Defense", "Banking & Finance", "Education & Research",
           "Energy & Utilities", "Government", "Healthcare & Pharma",
           "Insurance", "Manufacturing", "Media & Entertainment", "Oil & Gas",
           "Retail & E-Commerce", "Technology", "Telecommunications",
           "Transport & Logistics"]
TIERS = ["Premium Plus", "Premium", "Standard", "Self-Support"]
REGIONS = ["APAC", "EMEA", "LATAM", "NASA"]
SHIFTS = ["APAC", "EMEA", "India", "NASA"]
LEVELS = ["Associate", "Mid-Level", "Senior", "Staff", "Principal"]
SBRS = ["ACM", "Ansible", "API Management", "Ceph", "Identity Management",
        "JBoss Middleware", "Kernel", "Networking", "OCS", "RHOAI", "Shift",
        "Shift Hosted", "Stack", "Storage", "SysMgmt", "Virtualization"]
SEVERITIES = ["Severity 1 (Urgent)", "Severity 2 (High)",
              "Severity 3 (Normal)", "Severity 4 (Low)"]
STATUSES = ["Open", "In Progress", "Waiting on Customer",
            "Waiting on Engineering", "Resolved", "Closed"]
BUSINESS_HOURS = ["Business Hours", "Follow-the-Sun"]

PRODUCTS = [
    ("Red Hat Enterprise Linux", "Kernel"), ("Red Hat OpenShift", "Shift"),
    ("Red Hat OpenShift Hosted", "Shift Hosted"), ("Red Hat Ansible Platform", "Ansible"),
    ("Red Hat Ceph", "Ceph"), ("Red Hat OpenShift Data Foundation", "OCS"),
    ("Red Hat Satellite", "SysMgmt"), ("Red Hat Identity Management", "Identity Management"),
    ("Red Hat JBoss EAP", "JBoss Middleware"), ("Red Hat AMQ (Messaging)", "JBoss Middleware"),
    ("Red Hat 3scale API Management", "API Management"),
    ("Red Hat Advanced Cluster Management", "ACM"),
    ("Red Hat OpenShift AI", "RHOAI"), ("Red Hat OpenShift Virtualization", "Virtualization"),
    ("Red Hat Enterprise Linux for SAP", "Kernel"), ("Red Hat Insights", "SysMgmt"),
]

# ── fictional companies ───────────────────────────────────────────────────

COMPANIES = [
    ("Northwind Defence Systems", "Aerospace & Defense", "Bristol, UK"),
    ("Aerolith Propulsion", "Aerospace & Defense", "Toulouse, France"),
    ("Meridian Trust Bank", "Banking & Finance", "Singapore"),
    ("Calderon Capital Group", "Banking & Finance", "Madrid, Spain"),
    ("Brightwater Credit Union", "Banking & Finance", "Auckland, New Zealand"),
    ("Aldergrove University", "Education & Research", "Vancouver, Canada"),
    ("Institut Pellworm", "Education & Research", "Hamburg, Germany"),
    ("Helios Grid Utilities", "Energy & Utilities", "Lisbon, Portugal"),
    ("Tarnwick Power Authority", "Energy & Utilities", "Leeds, UK"),
    ("Department of Civic Records", "Government", "Wellington, New Zealand"),
    ("Municipal Transit Authority", "Government", "Montreal, Canada"),
    ("Coastal Health Network", "Healthcare & Pharma", "Perth, Australia"),
    ("Veritas Biopharma", "Healthcare & Pharma", "Basel, Switzerland"),
    ("Ironvale Mutual Insurance", "Insurance", "Dublin, Ireland"),
    ("Stellar Assurance", "Insurance", "Oslo, Norway"),
    ("Kestrel Manufacturing", "Manufacturing", "Nagoya, Japan"),
    ("Pemberton Steelworks", "Manufacturing", "Pittsburgh, PA, USA"),
    ("Lumen Broadcasting", "Media & Entertainment", "Los Angeles, CA, USA"),
    ("Orchard Street Media", "Media & Entertainment", "Manchester, UK"),
    ("Drakemoor Petroleum", "Oil & Gas", "Stavanger, Norway"),
    ("Sunflare Resources", "Oil & Gas", "Calgary, Canada"),
    ("Greenfield Retail Group", "Retail & E-Commerce", "Rotterdam, Netherlands"),
    ("Basketline Commerce", "Retail & E-Commerce", "Austin, TX, USA"),
    ("Quillon Software", "Technology", "Bangalore, India"),
    ("Anvil Cloud Systems", "Technology", "Seattle, WA, USA"),
    ("Pinecrest Data Works", "Technology", "Tallinn, Estonia"),
    ("Cobalt Telecom", "Telecommunications", "São Paulo, Brazil"),
    ("Skyreach Communications", "Telecommunications", "Seoul, South Korea"),
    ("Harbourline Logistics", "Transport & Logistics", "Rotterdam, Netherlands"),
    ("Redstone Freight", "Transport & Logistics", "Memphis, TN, USA"),
]

BLURB = ("Fictional organisation generated for the demo dataset. "
         "Any resemblance to a real company is coincidental.")

# ── fictional people ──────────────────────────────────────────────────────

FIRST = ["Dana", "Morgan", "Rowan", "Priya", "Idris", "Noor", "Tobias", "Ingrid",
         "Mateo", "Saoirse", "Kwame", "Lena", "Hiro", "Amara", "Felix", "Yuki",
         "Nadia", "Oscar", "Ravi", "Freya", "Emeka", "Clara", "Jonas", "Meera",
         "Theo"]
LAST = ["Whitfield", "Reyes", "Okafor", "Nair", "Halvorsen", "Bianchi", "Duval",
        "Lindqvist", "Ferreira", "Okonkwo", "Marchetti", "Bergstrom", "Tanaka",
        "Adeyemi", "Kowalski", "Sato", "Haddad", "Lindgren", "Iyer", "Nilsen",
        "Balogun", "Novak", "Weber", "Krishnan", "Moreau"]

# Managers are a separate population, exactly as in the real extract: they are
# referenced by `manager_name` / `manager_email` but are NOT themselves rows in
# associates.xlsx. This matters — `_lookup_in_data()` treats an address that
# appears in *both* columns as a role conflict and refuses to register it, so a
# manager who is also an associate row could never sign up.
MANAGERS = [
    ("Adaeze Nwachukwu", "adaeze.nwachukwu@redhat.com"),
    ("Bjorn Aaltonen", "bjorn.aaltonen@redhat.com"),
    ("Camille Rousseau", "camille.rousseau@redhat.com"),
    ("Devendra Rangarajan", "devendra.rangarajan@redhat.com"),
    ("Esther Vandenberg", "esther.vandenberg@redhat.com"),
]

CERTS = ["RHCSA", "RHCE", "RHCA", "OpenShift Administrator", "Ansible Automation",
         "AWS SAA", "Azure Administrator", "CKA", "Ceph Storage Administrator"]

PROBLEMS = [
    "Cluster nodes entering NotReady state after patching",
    "Persistent volume claims stuck in Pending",
    "Authentication failures against the identity provider",
    "Message broker consumer lag growing without bound",
    "API gateway returning intermittent 503 responses",
    "Kernel panic on boot after errata update",
    "Backup job failing with a timeout",
    "Certificate renewal not propagating to all replicas",
    "Playbook run hangs on the gather-facts step",
    "Storage cluster reporting degraded placement groups",
    "Operator upgrade stalled midway through rollout",
    "Excessive memory consumption in the control plane",
    "Network policy blocking expected east-west traffic",
    "Model serving endpoint returning empty predictions",
    "Virtual machine live migration fails under load",
    "Satellite content sync not completing",
]

DESCRIPTION_TEMPLATES = [
    "Customer reports {p_low}. Issue began after a routine change window. "
    "Impact is limited to the {env} environment. Logs and a diagnostic bundle "
    "have been requested.",
    "{p} was observed during scheduled maintenance. The customer has a "
    "workaround in place but requires a permanent fix before the next release "
    "window. Affects the {env} environment.",
    "Escalated by the account team: {p_low}. Business impact is described as "
    "significant. Awaiting reproduction steps from the customer for the {env} "
    "environment.",
    "Intermittent occurrence of {p_low}. Not reproducible on demand. "
    "Monitoring has been enabled on the {env} cluster to capture the next "
    "instance.",
]
ENVS = ["production", "staging", "pre-production", "development"]


def _lower_first(s):
    """Lowercase the leading word unless it is an acronym — 'API' stays 'API'."""
    return s if len(s) > 1 and s[1].isupper() else s[0].lower() + s[1:]


def make_accounts():
    rows = []
    for i, (name, sector, hq) in enumerate(COMPANIES, start=1):
        start = AS_OF - timedelta(days=rng.randint(400, 1400))
        rows.append({
            "account_id": f"ACC-{i:04d}",
            "account_name": name,
            "sector": sector,
            "account_notes": rng.choice([
                "Standard commercial engagement.",
                "Multi-region deployment; change windows are tightly controlled.",
                "Renewal conversation scheduled with the account team.",
                "Migration programme in progress across several business units.",
            ]),
            "annual_revenue": rng.randrange(5_000_000, 90_000_000, 1_000),
            "contract_start_date": start.strftime("%Y-%m-%d"),
            "contract_end_date": (start + timedelta(days=rng.choice([365, 730, 1095]))
                                  ).strftime("%Y-%m-%d"),
            "support_tier": rng.choices(TIERS, weights=[2, 4, 3, 1])[0],
            "tam_assigned": (f"{rng.choice(FIRST)} {rng.choice(LAST)}"
                             if rng.random() > 0.45 else None),
            "region": rng.choice(REGIONS),
            "employee_count": rng.randrange(200, 250_000, 100),
            "created_at": (AS_OF - timedelta(days=rng.randint(30, 900))
                           ).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return pd.DataFrame(rows)


def make_associates():
    rows, used = [], set()
    for i in range(25):
        while True:
            fn, ln = rng.choice(FIRST), rng.choice(LAST)
            if (fn, ln) not in used:
                used.add((fn, ln))
                break
        name = f"{fn} {ln}"
        mgr_name, mgr_email = MANAGERS[i % len(MANAGERS)]
        rows.append({
            "associate_id": f"EMP-{i + 1:04d}",
            "associate_name": name,
            "email": f"{fn.lower()}.{ln.lower()}@redhat.com",
            "sbr": rng.choice(SBRS),
            "shift": rng.choice(SHIFTS),
            "skill_level": rng.choice(LEVELS),
            "hire_date": AS_OF - timedelta(days=rng.randint(200, 3200)),
            "certifications": ", ".join(rng.sample(CERTS, rng.randint(1, 3))),
            "active": 1,
            "manager_name": mgr_name,
            "manager_email": mgr_email,
        })
    return pd.DataFrame(rows)


def make_cases(accounts, associates):
    rows = []
    for n in range(250):
        acct = accounts.iloc[rng.randrange(len(accounts))]
        owner = associates.iloc[rng.randrange(len(associates))]
        product, sbr = rng.choice(PRODUCTS)
        severity = rng.choices(SEVERITIES, weights=[1, 3, 5, 2])[0]
        created = AS_OF - timedelta(days=rng.randint(1, 540),
                                    hours=rng.randint(0, 23))
        status = rng.choices(STATUSES, weights=[3, 4, 2, 1, 3, 4])[0]
        closed = status in ("Resolved", "Closed")
        problem = rng.choice(PROBLEMS)
        resolution = (created + timedelta(hours=rng.randint(4, 900))) if closed else None
        if resolution and resolution > AS_OF:
            resolution = AS_OF - timedelta(hours=rng.randint(1, 48))
        last_updated = created + timedelta(
            hours=rng.randint(1, max(2, int((AS_OF - created).total_seconds() // 3600))))
        if resolution is not None and resolution > last_updated:
            # A closed case cannot have been last touched before it closed.
            last_updated = resolution
        rows.append({
            "case_number": 3_000_000 + n,
            "account_id": acct["account_id"],
            "account_name": acct["account_name"],
            "creation_date": created,
            "severity": severity,
            "status": status,
            "csat_score": (float(rng.choices([1, 2, 3, 4, 5],
                                             weights=[1, 1, 2, 4, 5])[0])
                           if closed and rng.random() > 0.25 else None),
            "sbr": sbr,
            "problem_statement": problem,
            "description": rng.choice(DESCRIPTION_TEMPLATES).format(
                p=problem, p_low=_lower_first(problem), env=rng.choice(ENVS)),
            "product_name": product,
            "product_version": round(rng.uniform(1.0, 9.9), 1),
            "sovereign_support": 1 if rng.random() > 0.9 else 0,
            "business_hours": rng.choice(BUSINESS_HOURS),
            "case_owner": owner["associate_name"],
            "last_updated": last_updated,
            "resolution_date": resolution,
            "escalated": 1 if rng.random() > 0.86 else 0,
        })
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(exist_ok=True)

    accounts = make_accounts()
    associates = make_associates()
    cases = make_cases(accounts, associates)

    accounts.to_csv(OUT / "accounts.csv", index=False)
    associates.to_excel(OUT / "associates.xlsx", index=False)
    cases.to_excel(OUT / "support_cases.xlsx", index=False)

    (OUT / "company_backgrounds.json").write_text(json.dumps(
        {name: [hq, BLURB] for name, _, hq in COMPANIES}, indent=2), encoding="utf-8")

    # Two logins the registration gate will accept: a manager who appears only
    # in manager_email, and one of their own reports. Identities only —
    # passwords come from SEED_MANAGER_PASSWORD / SEED_ASSOCIATE_PASSWORD at
    # load time, so no credential is ever written to a file.
    mgr_name, mgr_email = MANAGERS[0]
    # Someone who actually reports to that manager, so the Team Queue and the
    # demo logins tell a coherent story.
    assoc = associates[associates["manager_email"] == mgr_email].iloc[0]
    (OUT / "seed_users.json").write_text(json.dumps([
        {"email": mgr_email, "role": "manager", "display_name": mgr_name},
        {"email": assoc["email"], "role": "associate",
         "display_name": assoc["associate_name"]},
    ], indent=2), encoding="utf-8")

    print(f"✓ {OUT}")
    for f in sorted(OUT.iterdir()):
        print(f"    {f.name:28} {f.stat().st_size / 1024:7.1f} KB")
    print(f"\n  accounts {len(accounts)} · associates {len(associates)} "
          f"(+{len(MANAGERS)} managers) · cases {len(cases)}")
    print(f"  demo manager   {mgr_email}   (SEED_MANAGER_PASSWORD)")
    print(f"  demo associate {assoc['email']}   (SEED_ASSOCIATE_PASSWORD)")


if __name__ == "__main__":
    main()
