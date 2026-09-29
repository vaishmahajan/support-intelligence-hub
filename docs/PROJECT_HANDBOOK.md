<div align="center">

# 📕 Red Hat Support Operations Platform
### Capstone #2 — Complete Project Handbook

**Customer Intelligence Dashboard · Associates Dashboard · My Desk · REST API**

<br>

*Everything a new engineer needs to take this project over.*
*No prior context assumed.*

<br>

| | |
|---|---|
| **Version** | 2.0 |
| **Handbook date** | 30 September 2026 |
| **Status** | Feature complete · 185 tests green · hardened for hosting |
| **Data** | Static extract (see [Chapter 14](#chapter-14--going-live-with-real-data)) |

</div>

---

## 📑 Table of Contents

| # | Chapter | What you get |
|---|---|---|
| 1 | [What This Project Is](#chapter-1--what-this-project-is) | The one-paragraph version, then the honest version |
| 2 | [Who It Is For](#chapter-2--who-it-is-for) | Three personas and what each one sees |
| 3 | [Quick Start](#chapter-3--quick-start-5-minutes) | Running in five minutes |
| 4 | [System Architecture](#chapter-4--system-architecture) | Diagrams of every moving part |
| 5 | [The Data](#chapter-5--the-data) | Where it comes from, schema, and its quirks |
| 6 | [Authentication & RBAC](#chapter-6--authentication--rbac) | Login, JWT, roles, cross-app handoff |
| 7 | [Customer Intelligence Dashboard](#chapter-7--customer-intelligence-dashboard-app1py) | Port 8501, feature by feature |
| 8 | [Associates Dashboard](#chapter-8--associates-dashboard-app2py) | Port 8502, feature by feature |
| 9 | [My Desk — The Operations Workspace](#chapter-9--my-desk--the-operations-workspace) | The heart of the product |
| 10 | [Every Calculation Explained](#chapter-10--every-calculation-explained) | **With worked examples on real rows** |
| 11 | [The REST API](#chapter-11--the-rest-api) | Endpoints, auth, anti-scraping |
| 12 | [Testing](#chapter-12--testing) | 185 tests, what each file guards |
| 13 | [Deployment](#chapter-13--deployment) | Local · Podman · Docker · OpenShift |
| 14 | [Going Live With Real Data](#chapter-14--going-live-with-real-data) | The one thing still missing |
| 15 | [Configuration Reference](#chapter-15--configuration-reference) | Every environment variable |
| 16 | [Troubleshooting](#chapter-16--troubleshooting) | Symptoms → causes → fixes |
| 17 | [File-by-File Map](#chapter-17--file-by-file-map) | What lives where |
| 18 | [Design Rules & Glossary](#chapter-18--design-rules--glossary) | The rules that must not be broken |
| A | [Complete Inventory](#appendix-a--complete-inventory-databases-tables-tools--configs) | Database, every table & column, every tool, every config file |
| B | [Complete Feature Inventory](#appendix-b--complete-feature-inventory) | Every component and feature, what it is for, and the extras |

---
---

# Chapter 1 — What This Project Is

## The one-paragraph version

Two Streamlit web dashboards, a FastAPI REST service and a PostgreSQL database
that together give Red Hat's Customer Experience & Engagement (CEE) organisation
a view of its support operation. One dashboard looks at it from the **customer**
side (which accounts are healthy, which are drifting). The other looks at it from
the **engineer** side (who is skilled in what, which teams are loaded) — and
contains **My Desk**, a working queue that tells an individual support engineer
what to do next.

## The honest version

The project began as retrospective business intelligence: charts answering *"how
did we do last quarter?"* That is useful to a manager and nearly useless to the
person answering cases at 2am. My Desk was added to fix that, and it is now the
default landing tab for every role.

The distinction matters and is worth preserving:

<table>
<tr><th width="50%">Retrospective BI (the original tabs)</th><th width="50%">Operational workspace (My Desk)</th></tr>
<tr>
<td>

- "Average CSAT was 4.1 last quarter"
- "This SBR closed 340 cases"
- "Escalation rate is trending down"

*Answers: how did we do?*

</td>
<td>

- "Work case 3000010 next, here is why"
- "This exact symptom was closed 7 times before"
- "Ask Priya — she closed 4 of them"

*Answers: what do I do in the next hour?*

</td>
</tr>
</table>

## What makes this project unusual

Three rules were enforced throughout and you should keep enforcing them. They
are the reason a support engineer can trust the screen.

> ### ⚠️ Rule 1 — Never invent data
> If the dataset does not contain something, the UI says **"not recorded in
> this dataset"**. It never fabricates a log line, a timestamp, a customer
> quote, a root cause or an engineer's availability. Chapter 9 has several
> places where a blank space is shown on purpose.

> ### ⚠️ Rule 2 — Never fake an action
> Buttons that would need write access to the real case system (*Update
> status*, *Reassign*, *Escalate*) are rendered **disabled with the reason
> printed next to them**. The analytics database is read-only for case data. A
> green button that silently does nothing is worse than no button.

> ### ⚠️ Rule 3 — Never call arithmetic a prediction
> Recurring issues are labelled **"Observed historical pattern"**, not an AI
> prediction, because they are a `GROUP BY` over closed cases. The one genuine
> model in the project (escalation risk) reports its own held-out accuracy so
> you can decide whether to believe it.

---
---

# Chapter 2 — Who It Is For

## Primary persona: the CEE support engineer

> **Theo Krishnan** — Support Engineer, RHOAI SBR, NASA shift.
> Opens the tool at the start of a shift. Has 15–20 open cases. Needs to know
> which one to touch first, whether anyone has seen this symptom before, and
> who to pull in if it needs specialist help. **Does not want a chart.**

Everything in My Desk is built for Theo. The test for any new feature is:
*does it change what they do in the next hour?* If not, it belongs in one of
the analytics tabs, not in the queue.

## Secondary persona: the team manager

> **Adaeze Nwachukwu** — Manager. Needs the same queue but across their whole
> team, plus workload distribution and SBR backlog. Switches My Desk into
> **Team Queue** mode.

Deliberately **not** provided: a "best engineer" ranking. Case counts do not
mean the same thing across severities and products, so a leaderboard would be
actively misleading.

## Tertiary persona: the platform admin

> **System Administrator** — full access to every account and engineer, plus a
> **System** tab showing data freshness, database engine, record counts, and an
> explicit list of *fields this dashboard does not have and what each absence
> costs*.

## What each role sees

```mermaid
graph TD
    L["🔐 Login<br/>email + password"] --> W{"Workspace<br/>selector"}
    W -->|"Customer"| C["📊 Customer Intelligence<br/>:8501"]
    W -->|"Associates"| A["👥 Associates Dashboard<br/>:8502"]

    A --> T1["🗂️ My Desk<br/><i>default tab, all roles</i>"]
    A --> T2["👤 Associates View"]
    A --> T3["🏢 Team / SBR View"]
    A --> T4["🎓 Skills View"]

    T1 --> R1["<b>associate</b><br/>own cases only<br/>no Team Queue control"]
    T1 --> R2["<b>manager</b><br/>own + team<br/>Team Queue + Workload"]
    T1 --> R3["<b>admin</b><br/>anyone<br/>+ System tab"]

    T3 -.->|"manager & admin only"| X["🔒"]

    style L fill:#EE0000,color:#fff,stroke:#333
    style W fill:#8B5CF6,color:#fff,stroke:#333
    style C fill:#3B82F6,color:#fff,stroke:#333
    style A fill:#3B82F6,color:#fff,stroke:#333
    style T1 fill:#10B981,color:#fff,stroke:#333
    style X fill:#EF4444,color:#fff,stroke:#333
```

| Capability | Associate | Manager | Admin |
|---|:---:|:---:|:---:|
| My Desk — own cases | ✅ | ✅ | ✅ |
| My Desk — Team Queue toggle | ❌ *not rendered* | ✅ | ✅ |
| Team Workload tab | ❌ | ✅ | ✅ |
| Team / SBR View | ❌ | ✅ | ✅ |
| Associates View · Skills View | ✅ | ✅ | ✅ |
| System tab (diagnostics) | ❌ | ❌ | ✅ |
| Data Management — upload · create · delete | ❌ | ❌ | ✅ |
| AI skill extraction (`ai_extract`) | ❌ | ✅ | ✅ |
| Customer Intelligence dashboard | ✅ | ✅ | ✅ |

> 💡 **Note on the associate role:** the Team Queue control is *not rendered at
> all* rather than shown-and-disabled. Hiding the existence of a capability is
> a deliberate choice — a disabled control invites a support ticket.

---
---

# Chapter 3 — Quick Start (5 minutes)

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.10+ (tested on 3.14.7) | Everything is Python |
| pip | any recent | Dependencies |
| Podman or Docker | optional | Containerised run |
| PostgreSQL | optional | Falls back to SQLite automatically |

## The five commands

```bash
# 1 — get the code
git clone <repo-url>
cd Capstone2

# 2 — dependencies
pip install -r requirements.txt

# 3 — configuration (defaults work as-is for local development)
cp .env.sample .env

# 4 — build the database from the source data files
python setup_database2.py

# 5 — run both dashboards
./start.sh
```

`start.sh` launches both and prints the URLs. To run them separately:

```bash
streamlit run app1.py --server.port 8501    # Customer Intelligence
streamlit run app2.py --server.port 8502    # Associates + My Desk
uvicorn api:app --port 8503                 # REST API (optional)
```

## 🔗 Where to open it

| What | URL | Notes |
|---|---|---|
| **Customer Intelligence** | <http://localhost:8501> | Start here — it is the entry point |
| **Associates + My Desk** | <http://localhost:8502> | |
| **API interactive docs** | <http://localhost:8503/docs> | Swagger UI |
| **API health** | <http://localhost:8503/health> | Public, no auth |

## 🔑 Login credentials

There are **two separate credential sets**, and mixing them up is the most
common first-day mistake. The dashboards take an **email**; the REST API takes
a **username**. They are not the same accounts and they do not share passwords.

### Dashboard logins — app1 :8501 and app2 :8502

Both dashboards accept all three. Single sign-on: log in on one and the
workspace switcher carries you to the other without logging in again.

| Role | Email | Password | Where it comes from |
|---|---|---|---|
| 🔴 **Admin** | `admin@redhat.com` | `admin2026` | Hardcoded account, hashed at startup from `ADMIN_PASSWORD` |
| 🟡 **Manager** | `adaeze.nwachukwu@redhat.com` | `manager123` | `registered_users` row, bcrypt-seeded by `setup_database2.py` |
| 🟢 **Associate** | `theo.krishnan@redhat.com` | `associate123` | `registered_users` row, bcrypt-seeded by `setup_database2.py` |

> ⚠️ **The role dropdown must match the account.** Signing in as
> `adaeze.nwachukwu@redhat.com` with **Associate** selected fails, even with the
> right password. The role is checked against the database row, not just the
> UI. This is deliberate — it stops a manager quietly downgrading themselves
> into an associate's data scope and vice versa.

What each one lands on:

| Login as | You get |
|---|---|
| Associate | My Desk in **My Cases** mode. No Team Queue control at all, no Team / SBR View tab |
| Manager | My Desk plus the **Team Queue** toggle, Team Workload, and the Team / SBR View tab |
| Admin | Everything a manager sees, plus the **System** tab |

### REST API logins — :8503

Different usernames (no `@redhat.com`) and different default passwords:

| Role | Username | Password | Env variable |
|---|---|---|---|
| 🔴 Admin | `admin` | `admin2026` | `ADMIN_PASSWORD` |
| 🟡 Manager | `manager` | `manager2026` | `MANAGER_PASSWORD` |
| 🟢 Associate | `associate` | `associate2026` | `ASSOCIATE_PASSWORD` |

```bash
curl -s -X POST http://localhost:8503/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"manager","password":"manager2026"}'
```

> 🚫 A dashboard token will **not** work on the API and an API token will not
> work on the dashboards, even though both are signed with the same key. The
> `typ` claim keeps them apart — see [Chapter 6](#chapter-6--authentication--rbac).

### Changing them

```bash
# .env
ADMIN_PASSWORD=<12+ characters>
MANAGER_PASSWORD=<12+ characters>
ASSOCIATE_PASSWORD=<12+ characters>
```

`ADMIN_PASSWORD` and the two API passwords take effect on restart. The two
**dashboard** accounts are bcrypt hashes in the database, so changing them
means either re-running `setup_database2.py` or updating the row:

```bash
python -c "
from passlib.context import CryptContext
from db import get_connection, PARAM
h = CryptContext(schemes=['bcrypt']).hash('your-new-password')
with get_connection() as c:
    c.cursor().execute(
        f'UPDATE registered_users SET password_hash = {PARAM} WHERE email = {PARAM}',
        (h, 'adaeze.nwachukwu@redhat.com'))
    c.commit()
"
```

### Adding a real user

Both dashboards have a **Register** tab. Two rules are enforced at the data
layer, not just in the UI:

1. the address must end in `@redhat.com`, **and**
2. it must already exist in the source data — as an associate's email for an
   associate account, or as a manager's email for a manager account

So you cannot self-register as a manager, and you cannot invent a person.
There is no registration path for admin; it is the single hardcoded account.

> 🚫 **Every password on this page is published in this repository, so treat
> them as public.** They are development defaults only. Setting
> `APP_ENV=production` makes the app **refuse to start** until all of them are
> replaced — see Chapter 15 for the exact rules and Chapter 13 for deployment.

## Verify it worked

```bash
pytest tests/ -q          # expect: 185 passed
curl -s localhost:8503/health
```

---
---

# Chapter 4 — System Architecture

## The whole system at a glance

```mermaid
graph TB
    subgraph browser["🌐 Browser"]
        U["Support engineer<br/>manager · admin"]
    end

    subgraph net["🐳 Container network"]
        direction TB
        subgraph apps["Application tier"]
            A1["📊 app1.py<br/>Customer Intelligence<br/><b>Streamlit :8501</b>"]
            A2["👥 app2.py + my_desk.py<br/>Associates + My Desk<br/><b>Streamlit :8502</b>"]
            AP["⚡ api.py<br/>REST API<br/><b>uvicorn :8503</b>"]
        end

        subgraph shared["Shared modules"]
            CF["config.py<br/><i>secrets, URLs, validation</i>"]
            DB["db.py<br/><i>PG / SQLite switch</i>"]
            WU["workspace_utils.py<br/><i>cross-app links</i>"]
            LG["login_guard.py<br/><i>lockout</i>"]
        end

        PG[("🗄️ PostgreSQL 16<br/><b>:5432</b><br/>accounts · associates<br/>support_cases · skills<br/>registered_users")]
    end

    AI["🤖 IBM Granite 3.1-8B<br/>OpenAI-compatible API<br/><i>external</i>"]

    U -->|HTTPS| A1
    U -->|HTTPS| A2
    A1 <-->|"JWT handoff<br/>?token=&view="| A2
    A1 --> DB
    A2 --> DB
    AP --> DB
    DB --> PG
    A1 & A2 & AP --> CF
    A1 & A2 --> WU
    A1 & A2 --> LG
    A1 -.->|"on demand"| AI
    A2 -.->|"on demand"| AI

    style U fill:#1E293B,color:#fff
    style A1 fill:#3B82F6,color:#fff
    style A2 fill:#3B82F6,color:#fff
    style AP fill:#8B5CF6,color:#fff
    style PG fill:#336791,color:#fff
    style AI fill:#F59E0B,color:#fff
    style CF fill:#10B981,color:#fff
    style DB fill:#10B981,color:#fff
    style WU fill:#10B981,color:#fff
    style LG fill:#10B981,color:#fff
```

## Ports and services

| Service | File | Port | Process | Public in production? |
|---|---|---|---|---|
| Customer Intelligence | `app1.py` | 8501 | Streamlit | Via Caddy only |
| Associates + My Desk | `app2.py`, `my_desk.py` | 8502 | Streamlit | Via Caddy only |
| REST API | `api.py` | 8503 | uvicorn | Via Caddy only |
| PostgreSQL | — | 5432 (5433 on host locally) | postgres:16-alpine | ❌ never |
| TLS proxy | `Caddyfile` | 80, 443 | caddy:2-alpine | ✅ the only one |

## Are the two dashboards one project?

**Yes.** This question comes up constantly, so here is the evidence. They run as
separate processes on purpose (they must never be merged), but they are one
system joined at five points:

```mermaid
graph LR
    A1["app1.py<br/>:8501"]
    A2["app2.py<br/>:8502"]

    A1 ---|"1️⃣ same db.py, same tables"| A2
    A1 ---|"2️⃣ same registered_users + JWT secret"| A2
    A1 ---|"3️⃣ workspace_selector.py gate"| A2
    A1 ---|"4️⃣ build_switch_url() carries the session"| A2
    A1 ---|"5️⃣ one docker-compose network"| A2

    style A1 fill:#3B82F6,color:#fff
    style A2 fill:#3B82F6,color:#fff
```

| # | Join | Mechanism |
|---|---|---|
| 1 | **Database** | Both import `db.py`; both read `accounts`, `associates`, `support_cases`, `registered_users`. app2 also reads `skills`. |
| 2 | **Authentication** | Same `registered_users` table, same bcrypt hashes, same `JWT_SECRET_KEY`. A token minted by one validates on the other. |
| 3 | **Landing gate** | `workspace_selector.py` is the shared chooser shown after login. |
| 4 | **Navigation** | `workspace_switcher.py` + `workspace_utils.build_switch_url()` hand the session across so you stay logged in. |
| 5 | **Deployment** | One `docker-compose.yml`, one network, one Postgres. |

## Request lifecycle — a page load in My Desk

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant S as app2.py
    participant C as config.py
    participant D as db.py
    participant P as PostgreSQL
    participant M as my_desk.py

    B->>S: GET / (session cookie / ?token=)
    S->>C: read validated secrets
    S->>S: decode JWT → role, email
    alt not authenticated
        S-->>B: login page
    else authenticated
        S->>D: load_data()  @st.cache_data
        D->>P: SELECT accounts/associates/cases/skills
        P-->>D: 4 DataFrames
        D-->>S: cached 
        S->>M: render_my_desk(cases, associates, skills, accounts, role, email)
        M->>M: resolve_scope() → which cases is this user allowed to see
        M->>M: desk_reference_time() → anchor clock to newest timestamp
        M->>M: build_queue() → age, SLA ratio, priority score, sort
        M->>M: action_context() → specialist + repeat products
        M-->>B: queue, KPIs, tabs
    end
```

> 💡 **`@st.cache_data`** means the four DataFrames are read from Postgres once
> and reused across reruns. Every widget interaction in Streamlit re-executes
> the whole script top to bottom — without caching, every click would hit the
> database.

---
---

# Chapter 5 — The Data

## Where the data comes from

> 🔒 **No source data ships with this repository, and none ever will.**
> The dataset this project was built against is Red Hat customer and employee
> information — account names, annual revenues, contract dates, engineer names
> and email addresses, and free-text case descriptions. `data/` is in
> `.gitignore`, and the repository's history was started fresh so those files
> have never been in a commit. What you clone is the *application*; you supply
> the data.

You have two ways to get a running system:

| | **Demo dataset** *(recommended first run)* | **Your own dataset** |
|---|---|---|
| Where | `demo_data/`, committed | `data/`, gitignored, you create it |
| Contents | 30 accounts · 25 engineers · 250 cases, entirely invented | whatever you have |
| Regenerate | `python tools/make_demo_data.py` | — |
| Schema | identical to the real one | must match — [`docs/DATA_FORMAT.md`](DATA_FORMAT.md) |

```bash
cp demo_data/*.csv demo_data/*.xlsx demo_data/*.json data/   # or drop in your own
python setup_database2.py --from-source
```

**The three files the loader requires**, whichever route you take:

| File | Format | Contents | Demo rows |
|---|---|---|---|
| `data/accounts.csv` | CSV | Enterprise customer accounts | 30 |
| `data/support_cases.xlsx` | Excel | Support cases | 250 |
| `data/associates.xlsx` | Excel | Support engineers | 25 |

Two more are **optional** — missing either one is handled, not an error:

| File | Format | If absent |
|---|---|---|
| `data/company_backgrounds.json` | `{"Account Name": ["HQ city", "one-line blurb"]}` | `hq_location` and `company_background` stay `NULL`; Customer Intelligence simply shows less |
| `data/seed_users.json` | `[{"email", "role", "display_name"}]` | the two demo logins are seeded instead — [Chapter 6](#the-three-accounts) |

Exact columns, types and nullability for all five: **[`docs/DATA_FORMAT.md`](DATA_FORMAT.md)**.

**The loader:** `setup_database2.py` reads those files and builds the database.
It is not a migration tool — it is a one-shot build.

```mermaid
graph LR
    F1["📄 accounts.csv"] --> S["⚙️ setup_database2.py"]
    F2["📊 support_cases.xlsx"] --> S
    F3["📊 associates.xlsx"] --> S
    F4["📄 company_backgrounds.json<br/><i>optional</i>"] -.-> S
    F5["📄 seed_users.json<br/><i>optional</i>"] -.-> S

    S -->|"derive"| D1["revenue_segment<br/><i>bucketed from annual_revenue</i>"]
    S -->|"derive"| D2["skills table<br/><i>top 5 skills per associate,<br/>mined from case history</i>"]
    S -->|"derive"| D3["time_to_resolve_hours<br/><i>resolution − creation</i>"]
    S -->|"seed"| D4["registered_users<br/><i>2 logins, bcrypt hashed;<br/>admin is separate</i>"]

    D1 & D2 & D3 & D4 --> PG[("🗄️ PostgreSQL / SQLite")]

    style S fill:#8B5CF6,color:#fff
    style PG fill:#336791,color:#fff
```

```bash
python setup_database2.py            # build from data/ (default)
python setup_database2.py --help     # see all options
```

> ⚠️ **Without this step the apps will not start.** There is no database to
> read. If `data/` is empty the loader exits with
> `ERROR: Missing source files: [...]` rather than creating empty tables.

> 📊 **Row counts in this handbook refer to the private extract** — 202
> accounts, 1,000 cases, 228 associates, 1,015 derived skill rows — because
> that is the deployment the screenshots and Appendix A were taken from. On
> the demo dataset every count is smaller; nothing else changes.

## Entity relationship

```mermaid
erDiagram
    ACCOUNTS ||--o{ SUPPORT_CASES : "raises"
    ASSOCIATES ||--o{ SUPPORT_CASES : "owns"
    ASSOCIATES ||--o{ SKILLS : "holds"
    REGISTERED_USERS }o--|| ASSOCIATES : "logs in as"
    SUPPORT_CASES ||--o{ DESK_USER_STATE : "annotated by"

    ACCOUNTS {
        varchar account_id PK
        text account_name
        varchar sector
        bigint annual_revenue
        varchar revenue_segment
        date contract_start_date
        date contract_end_date
        varchar support_tier "Premium Plus|Premium|Standard|Self-Support"
        varchar tam_assigned
        varchar region "APAC|EMEA|LATAM|NASA"
        integer employee_count
        text hq_location
        text company_background
    }

    SUPPORT_CASES {
        varchar case_number PK
        varchar account_id FK
        text account_name
        varchar case_owner FK
        varchar severity "Severity 1-4"
        varchar status "Open|In Progress|Waiting on Customer|Waiting on Engineering|Resolved|Closed"
        varchar product_name "28 distinct"
        varchar product_version
        varchar sbr "14 distinct"
        date creation_date
        date last_updated
        date resolution_date
        date closed_date
        integer escalated "0|1"
        numeric csat_score "1-5"
        numeric time_to_resolve_hours
        text problem_statement "84 distinct"
        text description
        varchar business_hours "Business Hours|Follow-the-Sun"
        varchar sovereign_support
    }

    ASSOCIATES {
        varchar associate_id PK
        text associate_name
        varchar email
        varchar sbr
        varchar shift "APAC|EMEA|India|NASA"
        varchar skill_level
        varchar manager_name
        varchar manager_email
        date hire_date
        text certifications
        integer active
    }

    SKILLS {
        serial id PK
        varchar associate_id FK
        varchar skill_name
        integer skill_rank "1-5"
        numeric relevance_score
    }

    REGISTERED_USERS {
        serial id PK
        varchar email UK
        text password_hash "bcrypt"
        varchar role "manager|associate"
        text display_name
    }

    DESK_USER_STATE {
        text user_email PK
        text kind PK "note|bookmark|snapshot"
        text case_number PK
        text payload
        text updated_at
    }
```

Schema source: `db/init/01_schema.sql` (auto-runs on first `compose up`).

Two tables are **created on demand by the application**, additively, and never
touch the schema file:

| Table | Created by | Purpose | If the DB refuses |
|---|---|---|---|
| `desk_user_state` | `my_desk.py` | Private notes, follow-up bookmarks, last-seen snapshot | Degrades to session-only, and the UI says so |
| `login_attempts` | `login_guard.py` | Failed-login counters and lockout | Degrades to in-process memory |

## Dataset vocabulary

Know these values — filters, colours and rules all key off them.

| Field | Values |
|---|---|
| **severity** | `Severity 1 (Urgent)` · `Severity 2 (High)` · `Severity 3 (Normal)` · `Severity 4 (Low)` |
| **status** | `Open` · `In Progress` · `Waiting on Customer` · `Waiting on Engineering` · `Resolved` · `Closed` |
| **support_tier** | `Premium Plus` · `Premium` · `Standard` · `Self-Support` |
| **region** | `APAC` · `EMEA` · `LATAM` · `NASA` |
| **shift** | `APAC` · `EMEA` · `India` · `NASA` |
| **business_hours** | `Business Hours` · `Follow-the-Sun` |
| **sbr** (14) | ACM · API Management · Ansible · Ceph · Identity Management · JBoss Middleware · Kernel · OCS · RHOAI · Shift · Shift Hosted · Stack · SysMgmt · Virtualization |
| **product_name** | 28 distinct, e.g. Red Hat OpenShift Container Platform, Red Hat Ansible Platform, Red Hat 3scale API Management |

Status grouping used throughout the code (`my_desk.py`):

```python
CLOSED_STATUSES     = ("Resolved", "Closed")                                 # excluded from the queue
ACTIONABLE_STATUSES = ("Open", "In Progress", "Waiting on Engineering")      # engineer's move
WAITING_STATUSES    = ("Waiting on Customer",)                               # de-prioritised, never hidden
```

## 🚨 Four dataset quirks that will confuse you

These are **properties of the synthetic fixture**, not bugs in the code. Every
one of them shaped a design decision.

### 1. Open cases were never closed → 100% SLA breach

The generator created open cases and never advanced them. Measured against the
data as it stands today:

```
open cases:          569
median age:          376 days
SLA labels:          {'Breached': 569}
```

Every single open case is past its target. This is **real arithmetic on fake
data**, not a calculation error. It is also the single biggest reason the tool
is not yet ready for live users — see Chapter 14.

### 2. Each SBR maps to only 1–3 products

Product-level gap analysis is therefore structurally impossible — there is
nothing to compare. Skill-level comparison is the one with signal, which is
why *My Performance* compares skills against SBR peers rather than products.

### 3. Only 84 distinct problem statements across 1,000 cases

Symptoms repeat **verbatim**. This is why pattern detection groups on the
*exact* normalised problem statement: it is fully deterministic and
reproducible, needs no clustering model, and in this dataset genuinely works.
The UI states that exact grouping is a **lower bound** — two differently-worded
descriptions of the same fault will not be grouped.

### 4. `description` contains zero reproduction-step mentions

So the escalation-readiness checklist lists "Reproduction steps" as
**unavailable** rather than scoring it as a failure. Marking something failed
when the data simply cannot express it would be dishonest.

## The reference clock — why ages are not wall-clock

Because the data is a fixed export, using `datetime.now()` would age every open
case by however long ago the extract was taken. A three-month-old export would
show every case as three months more overdue than it is.

```python
def desk_reference_time(cases_df):
    """Newest timestamp in the data, never running ahead of real time."""
```

It scans `creation_date`, `last_updated` and `resolution_date`, takes the
maximum, and clamps to `now`. On the current extract:

```
reference clock: 2026-06-11 00:00:00
```

Every age, SLA ratio and staleness figure in My Desk is measured from that
instant. The tab prints its data-as-of date and never presents a static extract
as a live feed.

---
---

# Chapter 6 — Authentication & RBAC

## The login flow

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant A as app1 / app2
    participant G as login_guard.py
    participant DB as PostgreSQL
    participant W as workspace_selector

    U->>A: email + password + role
    A->>G: check(email)
    alt locked out
        G-->>A: "Too many failed attempts. Try again in 4m 12s."
        A-->>U: ❌ blocked
    else allowed
        A->>DB: SELECT password_hash, display_name, role<br/>FROM registered_users WHERE email=?
        DB-->>A: row
        A->>A: bcrypt verify + role must match exactly
        alt wrong
            A->>G: record_failure(email)
            A-->>U: ❌ Invalid credentials
        else correct
            A->>G: clear(email)
            A->>A: mint JWT {sub, role, exp, typ:"session"}
            A-->>W: _workspace gate
            W-->>U: choose Customer or Associates
        end
    end
```

## Three kinds of token

All three are signed with the same `JWT_SECRET_KEY` (HS256), so a `typ` claim
distinguishes them. This matters: a token that leaks from one context must not
be usable in another.

| `typ` | Minted by | Lifetime | Where it lives | Accepted by |
|---|---|---|---|---|
| `session` | Dashboard login | 60 min (7 days with *remember me*) | Browser URL `?token=` | Dashboards only |
| `handoff` | `workspace_utils.mint_handoff()` | **60 seconds** | Cross-app link | Dashboards only |
| *(none)* | `POST /auth/login` on the API | 60 min | `Authorization: Bearer` | REST API only |

```python
# api.py — a dashboard token cannot call the API
if payload.get("typ") in ("session", "handoff"):
    raise HTTPException(401, "This is a dashboard token, not an API token.")
```

## Cross-app handoff — how you stay logged in between :8501 and :8502

```mermaid
sequenceDiagram
    autonumber
    participant U as Browser
    participant A2 as app2 (:8502)
    participant WU as workspace_utils
    participant A1 as app1 (:8501)

    Note over A2: engineer clicks<br/>"View Drakemoor Petroleum in Customer Intelligence →"
    A2->>WU: build_switch_url("customer", session_jwt)
    WU->>WU: decode session JWT
    WU->>WU: mint {sub, role, typ:"handoff", exp:+60s}
    WU-->>A2: https://cust.example.com/?token=<60s>&view=ACC-0014
    U->>A1: follows the link
    A1->>A1: decode, typ == "handoff" ✔
    A1->>A1: resolve display name from DB by role
    A1->>A1: mint a fresh 60-min session token
    A1->>A1: replace ?token= in the URL
    A1->>A1: selected_account = ACC-0014
    A1-->>U: logged in, on the right account
```

Why not just pass the session token? Because it is a 60-minute credential
sitting in a URL — it lands in browser history, bookmarks, referrer headers and
proxy logs. A 60-second handoff token is dead by the time it reaches a log file.

Verified behaviour:

```
link token typ=handoff  ttl=60s     (session token ttl was 7200s)
app1: logged in as Theo Krishnan | account: ACC-0020
traded for typ=session ttl=3600s
URL token replaced: True
```

## The three accounts

| Role | Dashboard login | Password | API username | API password |
|---|---|---|---|---|
| 🔴 Admin | `admin@redhat.com` | `admin2026` | `admin` | `admin2026` |
| 🟡 Manager | `adaeze.nwachukwu@redhat.com` | `manager123` | `manager` | `manager2026` |
| 🟢 Associate | `theo.krishnan@redhat.com` | `associate123` | `associate` | `associate2026` |

Admin is a hardcoded account hashed at startup from `ADMIN_PASSWORD`. The other
two are bcrypt rows in `registered_users`, seeded by `setup_database2.py`.

**No password is stored in a file, and neither are the identities.** The two
logins have to be people who exist in `associates.xlsx` — otherwise the
registration gate in *Registration rules* below would reject the very accounts
the seeder created. So the seeder reads *who* from an optional gitignored file
and *what password* from the environment:

```python
SEED_USERS_FILE = DATA_DIR / "seed_users.json"     # identities only, gitignored

_DEMO_SEED_USERS = [                               # used when that file is absent
    {"email": "adaeze.nwachukwu@redhat.com", "role": "manager",
     "display_name": "Adaeze Nwachukwu"},
    {"email": "theo.krishnan@redhat.com", "role": "associate",
     "display_name": "Theo Krishnan"},
]

def seed_test_users(engine):
    _pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    _pw_for = {
        "manager":   os.getenv("SEED_MANAGER_PASSWORD",   "manager123"),
        "associate": os.getenv("SEED_ASSOCIATE_PASSWORD", "associate123"),
    }
    users = [(u["email"], _pwd.hash(_pw_for.get(u["role"], "associate123")),
              u["role"], u["display_name"])
             for u in _load_seed_users()]
```

| If you are running… | `data/seed_users.json` | Who gets seeded |
|---|---|---|
| the demo dataset | absent | `adaeze.nwachukwu@` / `theo.krishnan@` — the two above. The manager appears only in `manager_email`, the associate only in `email`; [that distinction matters](DATA_FORMAT.md#the-registration-gate) |
| your own dataset | you write it | whoever you name in it, who must exist in your `associates.xlsx` |

```json
[
  {"email": "you@redhat.com", "role": "manager", "display_name": "Your Name"}
]
```

A malformed or unreadable file prints a warning and falls back to the demo
pair rather than aborting the load. Format details: [`docs/DATA_FORMAT.md`](DATA_FORMAT.md).

> 🔐 **Set both passwords before any deployment anyone else can reach.**
> `manager123` / `associate123` are development defaults, printed in this
> handbook, and therefore public.
> ```bash
> export SEED_MANAGER_PASSWORD='…'
> export SEED_ASSOCIATE_PASSWORD='…'
> python setup_database2.py --from-source
> ```

Note the API passwords differ from the dashboard ones — they come from separate
environment variables. Full detail, including how to change them, is in
[Chapter 3](#chapter-3--quick-start-5-minutes).

## Registration rules

- Only `@redhat.com` addresses **that already exist in the source data** can register
- A manager cannot register as an associate, and vice versa — enforced at the data level, not just the UI
- Admin has no registration path; it is the single hardcoded account
- The role dropdown at login must match the stored role, or the sign-in fails

## Password reset

*Forgot password?* on the login screen (`reset_password()` in both apps). It is
a **change-password** flow, not an email-recovery one: you must supply the
**current** password along with the new one and the confirmation, and the role
must match. It re-hashes with bcrypt and `UPDATE`s `registered_users`.

The button is **disabled for admin** — the admin password comes from
`ADMIN_PASSWORD` at startup and is not stored in the table, so there is nothing
to update. Change the environment variable and restart instead.

> 💡 There is no out-of-band recovery. If a user forgets their password
> entirely, an admin re-hashes it directly (§3, *Changing them*). Building real
> recovery means adding mail delivery — see the dead `password_reset_otps`
> table in [A.1](#a1-databases) for where an earlier attempt stopped.

## Rate limiting

| Setting | Default | Variable |
|---|---|---|
| Attempts before lockout | 5 | `MAX_LOGIN_ATTEMPTS` |
| Lockout duration | 300 s | `LOCKOUT_SECONDS` |

State lives in the `login_attempts` table, so it survives a restart and is
shared across replicas. Previously it was a module-level dict, which meant a
restart cleared it and two replicas gave an attacker 10 attempts instead of 5.

## Anti-scraping on the API

`middleware.py` blocks direct `curl`/`wget`/`scrapy` access. Legitimate
front-end callers send an HMAC-SHA256 signed token:

```python
ts    = str(int(time.time()))
msg   = f"capstone2:{ts}".encode()
token = hmac.new(FRONTEND_SECRET.encode(), msg, hashlib.sha256).hexdigest()[:32]
headers = {"x-frontend-token": token, "x-frontend-ts": ts, "User-Agent": "Mozilla/5.0 ..."}
```

---
---

# Chapter 7 — Customer Intelligence Dashboard (`app1.py`)

**Port 8501.** The account-facing view: *which customers are healthy, and which
need attention?*

## Feature map

```mermaid
graph TD
    H["🏠 Customer Intelligence :8501"]
    H --> K["📊 KPI strip<br/>Accounts · Avg CSAT · Avg TTR · Escalations"]
    H --> F["🔎 Global filters<br/>Account · Sector · Product · Tier · Region · Revenue"]
    H --> G["📈 Operational graph<br/>cases opened over time, date-range filtered"]
    H --> C["🃏 Account cards<br/>sorted by volume or escalations"]
    C --> D["🔍 Account detail"]
    D --> D1["time-based chart"]
    D --> D2["HQ location + company background"]
    D --> D3["key details + contract state"]
    D --> D4["🤖 AI business summary<br/><i>on demand</i>"]
    D --> D5["top associates on this account"]
    H --> CM["⚖️ Compare mode<br/>up to 5 accounts side by side"]
    H --> CB["💬 AI chatbot<br/>account-level Q&A"]

    style H fill:#3B82F6,color:#fff
    style D4 fill:#F59E0B,color:#fff
    style CB fill:#F59E0B,color:#fff
```

## The features in detail

### KPI strip
Total Accounts · Average CSAT · Average Time to Resolve · Total Escalations.
Recomputed against whatever the global filters currently select.

### Global filters
Account ID/Name, **Sector**, **Products**, **Support Tier (Entitlement)**,
**Region**, **Revenue Segment** — all multi-select, and they compose (every
filter is an AND). A saved-filter button keeps a combination for next time.

Inside an account, a second row filters its cases by **Severity**, **Status**,
**Product** and **Case Owner**.

A **date preset** selector drives the operational graph — *All Time · Today ·
Yesterday · Last 7 Days · Last 30 Days · Last Quarter · Custom*, where Custom
reveals a from/to pair (`f_custom_from`, `f_custom_to`).

> ⚠️ The presets are measured against the **reference clock**, not today's
> date — see [Chapter 5](#the-reference-clock--why-ages-are-not-wall-clock).
> On a static extract "Last 7 Days" against wall-clock time would return
> nothing at all.

### Account cards
Each card carries the **health score** badge (see Chapter 10), open case count,
CSAT, support tier, and contract state. Six sort orders:

```
Total Cases (High to Low)   ·  Escalations (High to Low)  ·  CSAT (Low to High)
Revenue (High to Low)       ·  Health Score (Low to High) ·  Account Name
```

The defaults point at trouble: *Total Cases (High to Low)* out of the box, and
CSAT and Health Score both sort **worst first**.

Contract badge logic:

| Condition | Badge |
|---|---|
| `contract_end_date < today` | 🔴 **Expired** |
| within 90 days | 🟡 **Expiring Soon** |
| otherwise | 🟢 **Active** |

### Account detail view
Time-based case chart, HQ location, company background, key details, and the
associates who have worked this account most.

### AI business summary
Explicitly **on demand** — a *Generate Insights* button, never automatic. Calls
the IBM Granite endpoint with account facts and asks for a business-level
summary. If the endpoint is unreachable the failure is shown as a message; it
does not fabricate a summary.

### AI chatbot
A floating chat for account-level questions. Scoped to the data on screen.

### Compare mode
Bulk-select up to 5 accounts for a side-by-side comparison.

---
---

# Chapter 8 — Associates Dashboard (`app2.py`)

**Port 8502.** The engineer-facing view. Four tabs; **My Desk is the default
for every role**.

```python
_tab_labels = ["My Desk", "Associates", "Team / SBR View", "Skills View"]
```

## Associates View *(all roles)*
Cards sorted by resolved/owned tickets. Per associate: cases owned, cases
resolved, average satisfaction, top 5 skills. Plus shift insights with charts
and an AI summary.

## Team / SBR View *(manager & admin only)*
Every associate and skill for a selected SBR team, with an AI-powered team
performance summary.

## Skills View *(all roles)*
Associates and skills sorted by top skills, a skill summary with its associated
product, and AI-powered skills analysis.

## Data Management *(admin only)*

`ROLE_PERMISSIONS["data_ingest"]` is `True` for **admin only** — managers do
not get this, despite having `team_view` and `ai_extract`. It appears twice,
in the sidebar and in the Associates view, and has four tabs:

| Tab | What it does |
|---|---|
| **CSV Upload** | Validates against six required columns (`case_number`, `account_name`, `severity`, `status`, `product_name`, `case_owner`), skips rows with empty required fields and says how many, then `INSERT`s |
| **Manual Entry** | Creates one case. Auto-assigns the next `case_number` from `MAX()+1`, defaults status to `Open` and `escalated` to `0` |
| **Delete Case** | Shows the case first, then requires a second *Yes, Delete* confirmation |
| **Export Data** | CSV / Excel download of the current selection |

Every path calls `load_all_data.clear()` afterwards, so the cache cannot serve
a stale copy of a table that just changed.

## The guided tour

**21 spotlight steps** (25 screens once the intro and closing panels are
counted — `_s_total = len(_tour_steps) + 4`), highlighting real elements on the
page rather than a mock-up. Each step declares which tab it belongs to, and the
tour switches tabs for you:

```python
{"sel": ".st-key-desk_card_top", "nav_tab": "My Desk", "title": "...", "desc": "..."}
```

Steps 1–14 walk My Desk (header → freshness → search → KPIs → what changed →
handoff → filters → queue → a real case card → its detail → action centre →
SLA targets → tabs). Steps 15–17 cover the Associates view. The next two are
**role-dependent**: managers and admins get Team Dashboard and Team Analytics;
associates get Anomaly Detection and Charts & Insights instead. The last two
cover Skills.

> 💡 The tour targets `.st-key-*` CSS selectors, which Streamlit generates from
> `st.container(key="...")`. Those keyed containers exist **purely** so the tour
> has something stable to point at — they add no layout of their own. If you
> rename a key, fix the tour step.

---
---

# Chapter 9 — My Desk — The Operations Workspace

This is the heart of the product. `my_desk.py`, ~2,900 lines, rendered by
`render_my_desk()`.

## Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Good morning, Yuki                        data as of 11 Jun 2026       │  desk_header
├──────────────────────────────────────────────────────────────────────────┤
│  🔎 Search: case number · account · associate · symptom text             │  desk_search_box
│  [ My Cases | Team Queue ]  (managers/admins only)   ⚙ SLA targets       │  desk_scope / desk_slatargets
├──────────────────────────────────────────────────────────────────────────┤
│   17      4       11        2         6          3                       │  desk_kpis
│  open  critical  SLA-risk  escal.  waiting    aging                      │
├──────────────────────────────────────────────────────────────────────────┤
│  📋 What changed since your last visit  (+2 new, 1 resolved, 3 aged)     │  desk_changed
├──────────────────────────────────────────────────────────────────────────┤
│  📝 [ Write shift handoff brief ]                                        │  desk_handoff
├──────────────────────────────────────────────────────────────────────────┤
│  Chips:  Critical(4)  SLA risk(11)  Escalated(2)  Aging(3)  …            │  desk_filters
├──────────────────────────────────────────────────────────────────────────┤
│  ╔══ #3000010  Drakemoor Petroleum                  priority 97 ═════╗  │  desk_card_top
│  ║  Sev 1 · Open · Advanced Cluster Mgmt 8.1 · Premium · 🔴 Breached ║  │
│  ║  ➜ Review escalation history before the next customer contact     ║  │
│  ║    "carries the escalation flag, so someone above the engineer    ║  │
│  ║     is already watching it"                                       ║  │
│  ║  ┌ Timeline │ Similar │ Potential SMEs │ Readiness │ Notes ┐      ║  │
│  ╚═══════════════════════════════════════════════════════════════════╝  │
│  … more cases …                                                          │  desk_queue
└──────────────────────────────────────────────────────────────────────────┘
```

## Tab structure — changes with role and mode

```mermaid
graph TD
    M{"mode"}
    M -->|"My Cases"| P1["Work Queue"]
    M -->|"My Cases"| P2["My Follow-ups"]
    M -->|"My Cases"| P7["My Performance"]
    M -->|"Team Queue<br/>(mgr/admin)"| T1["Team Queue"]
    M -->|"Team Queue"| T2["Team Workload"]

    M --> S1["SLA & Aging"]
    M --> S2["Escalation Risk"]
    M --> S3["Similar & Patterns"]
    M --> S4["Trends & Anomalies"]
    M -->|"admin only"| S5["System"]

    style M fill:#8B5CF6,color:#fff
    style P1 fill:#10B981,color:#fff
    style T1 fill:#10B981,color:#fff
    style S5 fill:#EF4444,color:#fff
```

## Above the tabs

| Element | What it does |
|---|---|
| **Global search** | One box over case number, account, associate and symptom text |
| **My Cases / Team Queue** | Managers and admins only. Associates never see the control |
| **SLA targets** | Editable per severity; everything downstream recomputes |
| **Pressure strip** | Six counts: open · critical · SLA risk · escalated · waiting · aging |
| **What changed** | Diffed against a snapshot recorded on your *previous* visit — new cases, resolved cases, cases that aged into a worse SLA state |

## The queue

Every card carries a **Recommended Next Action** with the rule that produced
it, a **priority score**, and the case facts. Chapter 10 explains both
calculations.

**Quick filter chips:** Critical · SLA risk · Escalated · Aging · Waiting on
customer · High tier · My products. Counts shown on each chip; chips combine
with AND.

> ⚠️ **Implementation trap — do not reintroduce.** The counts go through
> `format_func`, and the option *values* are the bare labels. An earlier
> version baked the count into the option string, so changing an SLA target
> rewrote every option and silently cleared the user's selection.

## The shift handoff brief

One button writes the over-to-you note under five **fixed** headings:

```
**Critical**  ·  **SLA risk**  ·  **Waiting on customer**  ·  **Escalations**  ·  **Recommended follow-ups**
```

Uses the Granite endpoint when reachable and a **deterministic local brief**
composed from the same facts when it is not. The AI is explicitly instructed
not to invent timestamps, log contents or customer statements, and to write
*"None in this queue."* rather than padding an empty section. AI output is
HTML-sanitised before rendering and the source is labelled either way.

## The case workspace

Opening a case gives a **customer context strip** — tier, TAM, region, contract
end with renewal warning, case history, escalations, CSAT, a 🟢/🟡/🔴 risk pill,
and a link through to that account in the Customer Intelligence dashboard — an
**action centre**, and five tabs.

### Timeline
Created → Last update → Waiting → Resolved, built **only** from timestamps the
dataset actually holds. First response time and escalation time are shown as
*"not recorded in this dataset"* rather than estimated.

### Similar cases
TF-IDF matches with similarity %, product, severity, resolve time, escalated
flag, CSAT, owner, SBR and shift, plus a note on how each may help.

### Potential SMEs
Ranked by documented experience. The column is **"shift on record"**, never
"available" — the dataset holds a shift pattern, not a rota.

### Escalation readiness
An 11-point checklist scored from structured fields and from what the
description actually contains. Checks the data cannot support are listed as
**unavailable** rather than silently passed.

### Private notes
Per user, stored in `desk_user_state`, labelled with which backend is in force.

### Action centre
```
[ Update status ]  🔒 disabled — the analytics database is read-only for case data
[ Reassign ]       🔒 disabled — same reason
[ Escalate ]       🔒 disabled — same reason
[ ⭐ Follow up ]    ✅ enabled — writes to desk_user_state
[ 📝 Add note ]     ✅ enabled
```

## The analysis tabs

| Tab | Contents |
|---|---|
| **My Follow-ups** | Cases you starred, with note and next action. Resolvable even after they leave your personal scope |
| **SLA & Aging** | Age-bucket histogram split by SLA state, breach rate per severity, configured target vs. historical median, worst-offenders table |
| **Escalation Risk** | Every open case scored, top two drivers named in plain English, plus the model's own held-out AUC |
| **Similar & Patterns** | Free-text TF-IDF search over closed cases + **observed historical patterns** |
| **Trends & Anomalies** | Poisson z-score detection on product/version arrival rates |
| **My Performance** | Personal CSAT drill-down and skill gap vs. SBR peers |
| **Team Workload** | Open, critical, SLA-risk, escalated, waiting and oldest case per engineer, plus SBR backlog. **Deliberately not a ranking** |
| **System** *(admin)* | Data-as-of date, extract age, DB engine, state-store backend, record counts, timestamp coverage, and an explicit list of missing fields and what each absence costs |

## Accessibility & motion

All motion is CSS-only (card fade-in, SLA bar fill, timeline draw) and fully
disabled under `prefers-reduced-motion`.

---
---

# Chapter 10 — Every Calculation Explained

> This chapter is the answer to *"on what basis did you calculate that?"* Every
> formula below is the one in the code and every constant is the real constant.
> Worked examples marked *(real row from the demo dataset)* come from
> `demo_data/`, which ships with this repository — load it and you will get the
> same numbers. The rest are labelled as illustrations.

> ⚠️ **No figure in this chapter comes from the private extract.** The customer
> data this project was built against is not in the repository (see
> [Chapter 5](#chapter-5--the-data)). Two measured results that *could* only be
> produced on that extract — the escalation-model AUC in
> [§10.5](#honesty-check--held-out-performance-measured) and the pattern count
> in [§10.9](#109-observed-historical-patterns) — are labelled as such, with
> what the demo set gives instead.

**Golden rule for all of them:** these are *arithmetic over recorded fields*.
They are ranking aids, not predictions. Nothing here calls an outcome.

---

## 10.1 Case Priority Score — the queue order

**Where:** `my_desk.py` → `compute_priority()`
**Question it answers:** *of my 17 open cases, which do I open first?*

### The formula

```
priority = severity + pressure + staleness + tier + escalated
if status is a waiting status:  priority *= 0.45
priority = min(priority, 100)
```

### The five components

**1. Severity — up to 40 points.** The single largest term, because severity is
the customer's own statement of impact.

| Severity | Points (`SEV_WEIGHT`) |
|---|---|
| 1 (Urgent) | **40** |
| 2 (High) | 28 |
| 3 (Normal) | 16 |
| 4 (Low) | 8 |

**2. SLA pressure — up to 25 points.** Log-scaled, not linear:

```python
pressure = min(log1p(sla_ratio) / log1p(200), 1.0) * 25
sla_ratio = age_hours / sla_target_hours
```

Why logarithmic? The difference between 0.5× and 1.0× of target is the
difference between comfortable and breached — that must move the number a lot.
The difference between 50× and 100× over is the difference between very late
and very late — that should barely move it. A linear scale would let one
ancient case dominate the whole queue forever.

| `sla_ratio` | pressure |
|---|---|
| 0.5 | 1.9 |
| 1.0 (at target) | 3.3 |
| 2.0 | 5.2 |
| 10 | 11.3 |
| 50 | 18.5 |
| 200+ | 25.0 (capped) |

**3. Staleness — up to 15 points.** Same log shape, on days since the last
update, saturating at 120 days:

```python
stale = min(log1p(stale_hours / 24) / log1p(120), 1.0) * 15
```

**4. Support tier — up to 10 points.**

| Tier | Points (`TIER_WEIGHT`) |
|---|---|
| Premium Plus | **10** |
| Premium | 7 |
| Standard | 3 |
| Self-Support | 0 |

**5. Escalated — flat 10 points.** Someone above the engineer is already
watching.

**The waiting damping — ×0.45.** If the case is waiting on the customer, the
engineer cannot progress it. It is not *closed*, so it does not vanish, but it
should not sit at the top of a queue of things you can actually do. This is the
one multiplier in the whole model, and it is deliberate.

### Worked example — case #3000010 *(real row from the demo dataset)*

Every figure below comes from `demo_data/support_cases.xlsx`, which ships with
this repository, so you can reproduce it exactly. It is the highest-priority
open case in that dataset.

| Field | Value |
|---|---|
| Account | Drakemoor Petroleum (`ACC-0020`) |
| Severity | 1 (Urgent) |
| Status | Open |
| Product | Red Hat Advanced Cluster Management 8.1 |
| Support tier | Premium |
| Escalated | yes |
| Age | 7,996 h (333 days) |
| Since last update | 6,929 h (289 days) |
| SLA target (Sev 1) | 24 h |
| SLA ratio | 333.2× |
| SLA label | 🔴 Breached |

```
severity   Sev 1                                          →  40.0
pressure   log1p(333.2)/log1p(200) = 5.811/5.303 = 1.096
             → min(1.096, 1) × 25                         →  25.0   (capped)
staleness  log1p(6929/24)/log1p(120) = 5.669/4.796 = 1.182
             → min(1.182, 1) × 15                         →  15.0   (capped)
tier       Premium                                        →   7.0
escalated  flag set                                       →  10.0
                                                             ─────
                                                   subtotal   97.0
status "Open" is not a waiting status → no damping
clip to 100                                                   97.0
                                             ══════════════════════
                                             PRIORITY        → 97.0
```

**Counter-example — the same case, waiting on the customer.**
If the status were `Waiting on Customer`, 97.0 would become
`97.0 × 0.45 = 43.7` and it would drop below every actionable Sev 2.

> 💡 **Only `Waiting on Customer` damps the score** — `WAITING_STATUSES` is a
> one-element tuple with exactly one member. `Waiting on Engineering` is still
> *your* problem, so it keeps its full weight. That is a deliberate
> disagreement with how most case systems group those two statuses together.

### Contrast — case #3000057, where nothing is capped

The case above saturates both log terms, which makes it a poor illustration of
the curves. The fourth-ranked case does not:

| Field | Value |
|---|---|
| Account | Greenfield Retail Group (`ACC-0022`) |
| Severity | 1 (Urgent) · **Status** Open · **Tier** Premium Plus |
| Escalated | no |
| Age | 4,708 h · **SLA ratio** 196.2× · 🔴 Breached |
| Since last update | 1,925 h (80 days) |

```
severity   Sev 1                                          →  40.0
pressure   log1p(196.2)/log1p(200) = 5.285/5.303 = 0.997
             → × 25                                       →  24.9
staleness  log1p(1925/24)/log1p(120) = 4.397/4.796 = 0.917
             → × 15                                       →  13.8
tier       Premium Plus                                   →  10.0
escalated  not set                                        →   0.0
                                             ══════════════════════
                                             PRIORITY        → 88.7
```

Read the two together and the model's shape is visible. #3000057 is **196×**
past its target and still earns 24.9 of the 25 available pressure points —
196× and 333× are, correctly, almost the same amount of "late". The 8.3-point
gap between the two cases is almost entirely the escalation flag, not the
extra 137× of lateness. **That is the intended behaviour**: an ageing case
should not be able to outrank everything forever simply by continuing to age.

### Recommended Next Action

The score orders the queue; a separate **rule ladder** says what to do. First
matching rule wins, and the card always shows the reason:

| Order | Condition | Action | Reason shown |
|---|---|---|---|
| 1 | Escalated | Review escalation history before the next customer contact | *"carries the escalation flag, so someone above the engineer is already watching it"* |
| 2 | SLA breached | Contact the customer with a status update | *"past its SLA target"* |
| 3 | SLA at risk | Progress before the target elapses | *"approaching its SLA target"* |
| 4 | Waiting on customer, stale | Send a chase | *"waiting on the customer with no update for N days"* |
| 5 | Severity 1/2 | Work it next | *"high severity"* |
| — | otherwise | Continue normal handling | — |

Case #3000010 hits rule 1: **"Review escalation history before the next
customer contact."**

---

## 10.2 SLA State — green / gold / red

**Where:** `my_desk.py` → `sla_state()`

```python
sla_ratio = age_hours / sla_target_hours
```

| Ratio | State | Colour |
|---|---|---|
| `< 0.75` | On Track | 🟢 green |
| `< 1.00` | At Risk | 🟡 gold |
| `≥ 1.00` | Breached | 🔴 red |

**Default targets** (`DEFAULT_SLA_HOURS`), editable in the UI:

| Severity | Target |
|---|---|
| 1 (Urgent) | 24 h |
| 2 (High) | 48 h |
| 3 (Normal) | 120 h |
| 4 (Low) | 240 h |

> ⚠️ **In this dataset every one of the 569 open cases is Breached.** Median
> open-case age is **376 days** against a maximum target of 10 days. That is a
> property of the sample data, not a bug in the calculation — see §5.6. Raise
> the targets in the UI to get a spread while exploring.

---

## 10.3 Account Health Score — the badge on the account card

**Where:** `app1.py` → `health_score()`
**Range:** 0–100, four components.

```
health = csat_part + escalation_part + closure_part + speed_part
```

| Component | Max | Formula |
|---|---|---|
| Satisfaction | 40 | `csat / 5 × 40` |
| Escalation restraint | 25 | `max(0, 25 × (1 − escalation_rate × 5))` |
| Closure | 20 | `closed_cases / total_cases × 20` |
| Speed | 15 | `max(0, 15 × (1 − min(ttr_hours, 720) / 720))` |

**Why ×5 on the escalation rate?** It makes 20% escalation the zero point.
An account escalating one case in five has an escalation problem, and the
component should already be exhausted there rather than decaying gently to 0%.

**Why cap TTR at 720 hours?** 30 days. Beyond that, "slow" is slow; the exact
figure adds no information and a single 2-year outlier would otherwise wipe out
the component for the whole account.

### Missing-data rules — stated, not hidden

| Situation | Score used | Why |
|---|---|---|
| No CSAT recorded | 20.0 for that component | Neutral midpoint — not 40 (unearned) and not 0 (unfair) |
| No TTR recorded | 7.5 for that component | Same reasoning |
| No cases at all | **50.0 overall** | No evidence either way |

### The badge

| Score | Badge |
|---|---|
| ≥ 75 | 🟢 Healthy |
| ≥ 55 | 🟡 Watch |
| ≥ 35 | 🟠 At Risk |
| < 35 | 🔴 Critical |

### Worked example — a hypothetical account with real-shaped numbers

```
14 cases, 9 closed, avg CSAT 4.2, 1 escalation, avg TTR 96 h

satisfaction   4.2 / 5 × 40                        = 33.60
escalations    esc_rate = 1/14 = 0.0714
               max(0, 25 × (1 − 0.0714×5))
               = 25 × (1 − 0.357) = 25 × 0.643     = 16.07
closure        9 / 14 × 20                         = 12.86
speed          max(0, 15 × (1 − 96/720))
               = 15 × 0.8667                       = 13.00
                                                     ─────
                                        HEALTH     = 75.53  →  🟢 Healthy
```

Change one thing — 3 escalations instead of 1:

```
escalations    esc_rate = 3/14 = 0.214
               25 × (1 − 1.071) = negative → max(0, …) = 0.00
                                        HEALTH     = 59.46  →  🟡 Watch
```

Three escalations out of fourteen drops the account a whole band. That is the
intended sensitivity.

---

## 10.4 Account Risk Pill — the 🟢/🟡/🔴 on the case workspace

**Where:** `my_desk.py` → `account_risk()`
A points model, deliberately simple enough to explain to a customer.

| Signal | +2 points | +1 point |
|---|---|---|
| Open cases | ≥ 8 | ≥ 4 |
| Escalations | ≥ 3 | ≥ 1 |
| Average CSAT | < 3.0 | < 3.8 |
| Breached cases | ≥ 3 | ≥ 1 |

| Total | Verdict |
|---|---|
| ≥ 5 | 🔴 High attention |
| ≥ 2 | 🟡 Attention |
| < 2 | 🟢 Stable |
| account not found | **"Unknown"** — never assumed healthy |

### Worked example — `ACC-0020` *(real row from the demo dataset)*

The account behind the §10.1 case, so the two read together. Reproduce it with
`demo_data/` loaded.

```
Drakemoor Petroleum: 15 cases, 7 open · 3 escalations · CSAT 3.00 · 7 breached

open cases     7  — ≥ 4, but not ≥ 8   →  +1
escalations    3  ≥ 3                  →  +2
CSAT           3.00 — < 3.8, not < 3.0 →  +1
breached       7  ≥ 3                  →  +2
                                          ──
                                     total 6  →  🔴 High attention
```

> 💡 **CSAT 3.00 scores +1, not +2.** The test is `csat < 3.0`, strictly less
> than. Exactly 3.00 falls through to the `< 3.8` branch. That boundary is
> worth knowing before someone reports it as a bug.

Every one of the four signals fires, but only two of them at full weight. The
account is in the red band on breadth of evidence rather than on any single
alarming number — which is the argument for a points model over a weighted
average, where one very bad signal can drag a verdict on its own.

---

## 10.5 Escalation Risk — the scored model

**Where:** `my_desk.py` → smoothed naive Bayes in log-odds space.
**This is the only statistical model in the project**, and it reports its own
accuracy rather than asking to be trusted.

### Features

```python
RISK_FEATURES = ["severity", "product_name", "sbr",
                 "account_id", "support_tier", "business_hours"]
RISK_SHRINKAGE = 20
```

### The smoothing

For each feature value, the escalation rate is shrunk toward the global base
rate:

```
rate = (successes + base_rate × K) / (count + K)        K = 20
```

**Why?** A product with 1 historical case that escalated has a raw rate of
100%. Without shrinkage it would outrank a product with 400 cases and a
genuine 30% rate. With K=20, that single case moves the estimate barely at all:

| Cases seen | Escalated | Raw rate | Smoothed (base = 12%) |
|---|---|---|---|
| 1 | 1 | 100% | 15.8% |
| 5 | 5 | 100% | 33.0% |
| 50 | 50 | 100% | 74.9% |
| 400 | 120 | 30% | 29.1% |

Evidence has to *earn* its influence.

### Scoring

Start from the base-rate logit, add each feature's logit delta, convert back:

```
score = sigmoid( logit(base) + Σ (logit(rate_f) − logit(base)) )
```

The **top two positive deltas** are named on screen in plain English — *"driven
by: product (OpenShift 4.13), support tier (Premium Plus)"*. A score with no
explanation is not actionable.

### Honesty check — held-out performance, measured

`evaluate_risk_model()` holds out 25% of cases, fits on the rest and reports
the result next to the scores. On the 1,000-case private extract:

```
AUC 0.9138   ·   n_test 250   ·   positives 19   ·   top-decile capture 0.4211
```

Read that as: rank the 250 held-out cases by score and the top 10% contains
**42% of the cases that actually escalated**. The wording on screen is
**"observed historical pattern"** — never "prediction".

> ⚠️ **On `demo_data/` this number is near chance, and that is correct.**
> The generator sets `escalated` with an independent coin flip
> (`tools/make_demo_data.py`), so there is no relationship between the features
> and the label to find. Expect an AUC around 0.5 — currently **0.483 on 63
> held-out cases**, which is chance, not a bug and not a regression. The model
> is doing exactly what an honest model should do on noise: fail to beat the
> base rate, and say so.
>
> This is also the cleanest demonstration of why the figure is reported at all.
> A model that only ever showed scores would look identical on both datasets.

---

## 10.6 Similar Cases — TF-IDF cosine

**Where:** `my_desk.py`. Pure Python + an inverted index. No scikit-learn — the
similarity is transparent and the dependency list stays short.

```
idf(term)    = log((n_docs + 1) / (docs_with_term + 1)) + 1
weight(term) = (1 + log(tf)) × idf(term)
```

Vectors are L2-normalised, so cosine similarity is a plain dot product.
Results are floored at `similarity > 0.01` to keep noise out.

**Why sublinear `1 + log(tf)`?** A case description saying "timeout" eight
times is not eight times more about timeouts than one saying it once.

**Why `+1` inside the idf log?** Guards against divide-by-zero for an unseen
term and keeps every idf positive, so no term can contribute negative
similarity.

### Worked example

```
Corpus: 1,000 closed cases
"timeout" appears in 40 of them,  "the" appears in 1,000

idf("timeout") = log(1001/41)  + 1 = 3.198 + 1 = 4.198
idf("the")     = log(1001/1001)+ 1 = 0.000 + 1 = 1.000

Query mentions "timeout" twice:
  weight = (1 + log 2) × 4.198 = 1.693 × 4.198 = 7.11
Query mentions "the" twice:
  weight = (1 + log 2) × 1.000 = 1.69
```

"timeout" carries **4.2×** the weight of "the" per occurrence. That is the
whole point of idf, and it is why no stop-word list is needed.

---

## 10.7 Potential SMEs — the ranking, and what it is not

**Where:** `my_desk.py`. Weighted evidence sum, max 6 engineers
(`SPECIALIST_MAX_ENGINEERS = 6`).

| Evidence | Weight (`SME_WEIGHTS`) |
|---|---|
| Worked a **similar case** (TF-IDF match) | **3.0** |
| Worked this **exact product version** | **3.0** |
| Worked this **product** | 2.0 |
| Skill match | 1.5 |
| Same SBR | 1.0 |

### Worked example

```
Engineer A: 2 similar cases, same version, same product, same SBR
  2 × 3.0  +  3.0  +  2.0  +  1.0                        = 12.0

Engineer B: same product, skill match, same SBR
  2.0  +  1.5  +  1.0                                    =  4.5
```

Engineer A ranks first, and the card lists *why*: "worked 2 similar cases · same
version · same product · same SBR".

> 🚫 **The column is "shift on record" — never "available".**
> The dataset holds `shift_on_record`, a historical shift pattern. It does not
> hold a rota, a calendar, or a presence signal. Rendering it as "Available"
> would be inventing a fact, and the engineer acting on it would call someone
> who is asleep. The header everywhere is **Potential SME**.

---

## 10.8 Anomaly Detection — Poisson z-score

**Where:** `my_desk.py` → `detect_anomalies(window_days=90, min_cases=3, z_threshold=2.0)`

For each product/version, compare cases arriving in the recent window against
the expected rate from the historical baseline:

```python
z = (observed − expected) / max(sqrt(max(expected, 0.5)), 0.7)
```

Flagged when `z ≥ 2.0` and `observed ≥ 3`.

**Why `sqrt(expected)`?** For a Poisson process the standard deviation *is* the
square root of the mean, so no separate variance estimate is needed.

**Why the two floors (`0.5` and `0.7`)?** Without them, an expected count near
zero makes the denominator near zero and *every* arrival looks like a
5-sigma event. The floors stop a rare product generating permanent false alarms.

### Worked example

```
Product X, expected 4.0 cases in the window, observed 12

z = (12 − 4.0) / max(sqrt(4.0), 0.7)
  = 8.0 / 2.0
  = 4.0        →  ≥ 2.0 and observed ≥ 3  →  🚩 flagged
```

Same product, observed 6:

```
z = (6 − 4.0) / 2.0 = 1.0   →  below threshold  →  not flagged
```

The UI wording is *"arrival rate above the historical baseline"* — a statement
about counts, not a claim about cause.

---

## 10.9 Observed Historical Patterns

**Where:** the *Similar & Patterns* tab, via `recurring_patterns()`. Groups
closed cases by product + symptom shape and reports what actually happened:
how many cases, median resolve time, escalation rate, typical owner SBR.

The threshold is a slider — **"Minimum repeats", 3 to 15, default 5**. The
case workspace calls the same function with `min_cases=3`, because there you
are asking about one specific symptom and want weaker evidence shown.

| Dataset | Patterns at the default threshold |
|---|---|
| Private extract (1,000 cases) | **40** |
| `demo_data/` (250 cases) | **0** — and 2 at `min_cases=3` |

> 💡 **Zero patterns on the demo set is the honest answer, not an empty tab.**
> 250 cases drawn from 16 problem statements rarely repeat a *product +
> statement* pair five times. When nothing clears the bar the UI says so —
> *"No problem statement repeats 5 or more times in the closed history. Lower
> the threshold to see weaker patterns."* — instead of padding the list. Drag
> the slider to 3 to see the two patterns that do qualify.

The heading is literally **"Observed historical pattern"**. It is a `GROUP BY`,
not a model, and the UI says so.

---

## 10.10 Escalation Readiness — the 11-point checklist

**Where:** `my_desk.py` → `escalation_readiness()`

| Kind | Count | Examples |
|---|---|---|
| Structured-field checks | 5 | severity set, product set, account identified, owner assigned, SLA target known |
| Text checks (regex over `description`) | 5 | error text quoted, version mentioned, environment described, impact stated, steps attempted |
| Prior-art check | 1 | at least one similar closed case exists |

Anything the dataset cannot support appears under **`_READINESS_UNAVAILABLE`**
— reproduction steps, diagnostic bundle (`sos report` / `must-gather`),
customer business impact statement, and so on — labelled *"not available in
current case data"* rather than counted as a pass or a fail.

> That distinction matters: a checklist that silently passes a check it cannot
> evaluate is worse than no checklist, because the engineer escalates believing
> the box was ticked.

---

## 10.11 Age Buckets

`AGE_BUCKETS`, used by the SLA & Aging histogram:

```
< 1 day  ·  1–3 days  ·  3–7 days  ·  1–4 weeks  ·  1–3 months  ·  > 3 months
```

---

## 10.12 Summary — what each number is

| Feature | Kind | Predictive? |
|---|---|---|
| Priority score | Weighted sum of recorded fields | No |
| SLA state | Ratio against a configured target | No |
| Health score | Weighted sum of recorded fields | No |
| Account risk | Points model | No |
| Escalation risk | Smoothed naive Bayes, AUC reported | **Historical pattern only** |
| Similar cases | TF-IDF cosine | No |
| Potential SMEs | Weighted evidence sum | No |
| Anomalies | Poisson z-score on counts | No |
| Patterns | `GROUP BY` over closed cases | No |
| Readiness | Rule checklist | No |

**Nothing in this product predicts an outcome.** Every number is arithmetic
over something the dataset actually recorded, and every one of them is
explained on screen at the point of use.

---
---

# Chapter 11 — The REST API

**Port 8503.** FastAPI. Interactive docs at `/docs`, OpenAPI schema at
`/openapi.json`.

## Endpoints

| Method | Path | Tag | Auth |
|---|---|---|---|
| `POST` | `/auth/login` | Auth | — |
| `GET` | `/auth/me` | Auth | Bearer |
| `GET` | `/health` | System | — |
| `GET` | `/api/v1/associates` | Associates | Bearer |
| `GET` | `/api/v1/associates/{associate_id}` | Associates | Bearer |
| `GET` | `/api/v1/cases` | Cases | Bearer |
| `GET` | `/api/v1/skills` | Skills | Bearer |
| `GET` | `/api/v1/skills/prevalence` | Skills | Bearer |
| `GET` | `/api/v1/teams` | Teams | Bearer |
| `GET` | `/api/v1/teams/{sbr}` | Teams | Bearer |
| `GET` | `/api/v1/stats/overview` | Statistics | Bearer |
| `GET` | `/api/v1/stats/by-shift` | Statistics | Bearer |
| `GET` | `/api/v1/stats/by-severity` | Statistics | Bearer |
| `GET` | `/api/v1/accounts` | Accounts | Bearer |

## Calling it

```bash
# 1. get a token
TOKEN=$(curl -s -X POST http://localhost:8503/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin2026"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. use it
curl -s http://localhost:8503/api/v1/stats/overview \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

## Two gotchas

**1. A dashboard token will not work here.** By design:

```json
{"detail": "This is a dashboard token, not an API token. Obtain one from POST /auth/login."}
```

**2. Plain `curl` may be blocked.** `middleware.py` rejects scraper
user-agents. Legitimate callers sign a request:

```python
import hmac, hashlib, time, requests
ts = str(int(time.time()))
tok = hmac.new(FRONTEND_SECRET.encode(), f"capstone2:{ts}".encode(),
               hashlib.sha256).hexdigest()[:32]
requests.get("http://localhost:8503/api/v1/cases",
             headers={"Authorization": f"Bearer {TOKEN}",
                      "x-frontend-token": tok, "x-frontend-ts": ts,
                      "User-Agent": "Mozilla/5.0"})
```

## CORS

The allow-list is **derived from the public URLs**, not a wildcard:

```python
_ALLOWED_ORIGINS = config.cors_origins()   # from PUBLIC_CUSTOMER_URL / PUBLIC_ASSOCIATES_URL
```

Override with `CORS_ORIGINS=https://a.example.com,https://b.example.com`.

---
---

# Chapter 12 — Testing

**185 tests. All green.** Run them before and after every change.

```bash
python -m pytest tests/ -q                     # everything
python -m pytest tests/test_my_desk.py -v      # one file
python -m pytest tests/ -q -k "priority"       # by name
python -m pytest tests/ -q --tb=short          # short tracebacks
```

| File | Tests | Covers |
|---|---:|---|
| `tests/test_my_desk.py` | **67** | Every calculation in Chapter 10 — priority, SLA, TF-IDF, SME ranking, anomalies, readiness, scope resolution, state store |
| `tests/test_html_render.py` | **34** | No raw HTML leaks into the rendered page, for `my_desk.py`, `app1.py`, `app2.py` |
| `tests/test_hosting.py` | **27** | Production config refusal, CORS derivation, handoff TTL, API token scoping, DB-backed lockout |
| `tests/test_api.py` | 26 | Every endpoint, auth, error paths |
| `tests/test_data.py` | 23 | Schema integrity, referential consistency, loaders |
| `tests/test_auth.py` | 8 | JWT lifecycle, bcrypt, role matching |

## What `test_html_render.py` actually guards

Streamlit renders Markdown, and **CommonMark ends an HTML block at a blank
line**. A multi-line HTML template with a blank line in the middle gets its
tail rendered as literal text — the user sees `</div>` on the page. The fix is
`_html()` in `workspace_utils.py`, which collapses a template onto one line:

```python
_HTML_WS = re.compile(r"\n\s*")
def _html(markup):
    return _HTML_WS.sub(" ", markup).strip()
```

The test boots each app with Streamlit's headless `AppTest`, walks every
rendered markdown block, and fails if a closing tag survives as text.

> `<style>`, `<script>`, `<pre>` and `<textarea>` are CommonMark **type 1**
> blocks — they end at their closing tag and are immune to blank lines. The
> test knows this; a naive grep does not, which is why a grep over the source
> reports false positives.

## `test_hosting.py` boots a subprocess

`config.py` validates **at import time**, so a test cannot simply set an env
var and re-import. Each case spawns a fresh interpreter with
`DOTENV_DISABLE=1` so the local `.env` cannot interfere:

```python
def _boot(**overrides):
    env = {**os.environ, "DOTENV_DISABLE": "1", **overrides}
    return subprocess.run([sys.executable, "-c", "import config"], env=env, ...)
```

There is also an **AST guard** that walks every module and fails if any of them
falls back to a hardcoded secret instead of going through `config.py`.

---
---

# Chapter 13 — Deployment

Four ways to run this, from a laptop to a cluster.

```mermaid
graph LR
    A["💻 Local Python<br/>streamlit run"] --> B["🐳 Podman / Docker Compose<br/>dev overlay"]
    B --> C["🔒 Compose + Caddy<br/>docker-compose.prod.yml"]
    C --> D["☸️ OpenShift<br/>Routes + edge TLS"]

    style A fill:#94A3B8,color:#fff
    style B fill:#3B82F6,color:#fff
    style C fill:#10B981,color:#fff
    style D fill:#EE0000,color:#fff
```

---

## 13.1 Local Python — what is running right now

This is how the project is running on the development machine today:

```bash
cd ~/Python_project/Capstone2
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env          # edit it

./start.sh                   # both dashboards
# or individually:
streamlit run app1.py --server.port 8501
streamlit run app2.py --server.port 8502
uvicorn api:app --host 0.0.0.0 --port 8503 --reload
```

| Service | URL |
|---|---|
| Customer Intelligence | http://localhost:8501 |
| Associates Dashboard | http://localhost:8502 |
| REST API | http://localhost:8503 |
| API docs | http://localhost:8503/docs |

To detach them from the terminal:

```bash
setsid nohup streamlit run app1.py --server.port 8501 --server.headless true \
  > /tmp/app1.log 2>&1 < /dev/null & disown
setsid nohup streamlit run app2.py --server.port 8502 --server.headless true \
  > /tmp/app2.log 2>&1 < /dev/null & disown
```

```bash
# stop them
pkill -f "streamlit run app1.py"
pkill -f "streamlit run app2.py"
```

> ⚠️ `pkill -f "streamlit run app1.py"` run in the *same* compound command that
> starts app1 will kill it again (and returns exit 144). Run the kill on its
> own line.

---

## 13.2 Podman — development

Podman is the container engine on this machine (**podman 5.8.4**). Everything
below works identically with `docker` — swap the command name.

```bash
# build
podman-compose -f docker-compose.yml build

# start everything (db, seed, api, both dashboards)
podman-compose -f docker-compose.yml up -d

# watch it come up
podman-compose -f docker-compose.yml ps
podman-compose -f docker-compose.yml logs -f customer-dashboard

# stop
podman-compose -f docker-compose.yml down

# stop AND delete the database volume (full reset)
podman-compose -f docker-compose.yml down -v
```

### Single container, no compose

```bash
podman build -t capstone2:latest .

podman run -d --name capstone2-customer \
  -p 8501:8501 --env-file .env \
  capstone2:latest \
  streamlit run app1.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
```

### Useful Podman commands

```bash
podman ps -a                                   # what is running
podman logs -f capstone2-customer              # follow logs
podman exec -it capstone2-customer /bin/bash   # shell inside
podman image prune -a                          # reclaim disk
podman volume ls                               # find the db volume
```

---

## 13.3 Podman / Docker — production with TLS

`docker-compose.prod.yml` is an **overlay**. Never run it alone — it only
contains the differences from the dev file.

```bash
# 1. real secrets
python -c "import secrets;print(secrets.token_urlsafe(48))"   # JWT_SECRET_KEY
python -c "import secrets;print(secrets.token_urlsafe(48))"   # FRONTEND_TOKEN_SECRET

# 2. edit .env — APP_ENV=production, real passwords, real domains

# 3. DNS: point cust./assoc./api. at this host's public IP  (Caddy needs
#    this to complete the Let's Encrypt challenge)

# 4. launch
podman-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
# docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### What the overlay changes

| Setting | Dev | Production overlay |
|---|---|---|
| Source code | bind-mounted | baked into the image (`volumes: !override []`) |
| API worker | `uvicorn --reload` | `uvicorn --workers 4` |
| Postgres port | published on 5433 | **not published** |
| App ports | 8501/8502/8503 published | **not published** — reached via Caddy |
| TLS | none | Caddy, automatic Let's Encrypt |
| `APP_ENV` | `development` | `production` — startup fails on a weak secret |
| Health checks | none | all three services |
| Logs | unbounded | json-file, 10 MB × 5 |
| Published ports | many | **only 80 and 443, on `proxy`** |

### Verify the merge before you launch

```bash
podman-compose -f docker-compose.yml -f docker-compose.prod.yml config
```

Check: no `ports:` on db/api/dashboards, no `--reload`, `APP_ENV: production`
on all three, and `proxy` publishing 80/443.

### Caddy

`Caddyfile` terminates TLS and applies a hardening snippet to all three sites:

```
(hardening) {
    header {
        Referrer-Policy "no-referrer"
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "SAMEORIGIN"
        -Server
    }
}
```

`Referrer-Policy: no-referrer` matters specifically here: the session token
rides in the URL, and without this header every outbound link would leak it in
the `Referer` header.

### Operating it

```bash
# health
curl -sf https://api.example.com/health
podman-compose -f docker-compose.yml -f docker-compose.prod.yml ps

# logs
podman-compose -f docker-compose.yml -f docker-compose.prod.yml logs -f proxy

# rolling restart of one service
podman-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build api

# backup the database
podman exec -t capstone2_db_1 pg_dump -U capstone capstone2 > backup_$(date +%F).sql

# restore
cat backup_2026-06-11.sql | podman exec -i capstone2_db_1 psql -U capstone capstone2
```

> 💾 **Back up the `caddy_data` volume.** It holds the issued certificates.
> Losing it forces re-issuance, and Let's Encrypt rate-limits that.

---

## 13.4 OpenShift

Manifests live in **`docs/openshift/`**. OpenShift supplies TLS through a
`Route` with edge termination, so **Caddy is not used** — the Route replaces it.

```mermaid
graph TB
    U["🌐 Browser"] -->|"HTTPS"| R1["Route: cust-…apps.cluster"]
    U -->|"HTTPS"| R2["Route: assoc-…apps.cluster"]
    U -->|"HTTPS"| R3["Route: api-…apps.cluster"]

    R1 --> S1["Service customer-dashboard:8501"]
    R2 --> S2["Service associates-dashboard:8502"]
    R3 --> S3["Service api:8503"]

    S1 --> D1["Deployment app1"]
    S2 --> D2["Deployment app2"]
    S3 --> D3["Deployment api"]

    D1 --> PG["StatefulSet postgres:16<br/>PVC 5Gi"]
    D2 --> PG
    D3 --> PG

    SEC["🔐 Secret capstone2-secrets"] -.-> D1
    SEC -.-> D2
    SEC -.-> D3
    CM["📄 ConfigMap capstone2-config"] -.-> D1
    CM -.-> D2
    CM -.-> D3

    style R1 fill:#EE0000,color:#fff
    style R2 fill:#EE0000,color:#fff
    style R3 fill:#EE0000,color:#fff
    style PG fill:#336791,color:#fff
    style SEC fill:#F59E0B,color:#fff
```

### Step 1 — log in and create the project

```bash
oc login --server=https://api.your-cluster.example.com:6443
oc new-project capstone2
oc project capstone2
```

### Step 2 — create the secrets

Never commit these. Generate and create them imperatively:

```bash
oc create secret generic capstone2-secrets \
  --from-literal=POSTGRES_USER=capstone \
  --from-literal=POSTGRES_PASSWORD="$(python -c 'import secrets;print(secrets.token_urlsafe(24))')" \
  --from-literal=POSTGRES_DB=capstone2 \
  --from-literal=JWT_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  --from-literal=FRONTEND_TOKEN_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  --from-literal=ADMIN_PASSWORD="$(python -c 'import secrets;print(secrets.token_urlsafe(12))')" \
  --from-literal=MANAGER_PASSWORD="$(python -c 'import secrets;print(secrets.token_urlsafe(12))')" \
  --from-literal=ASSOCIATE_PASSWORD="$(python -c 'import secrets;print(secrets.token_urlsafe(12))')" \
  --from-literal=AI_API_TOKEN="your-granite-token"

# read them back when you need to log in
oc get secret capstone2-secrets -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 -d; echo
```

### Step 3 — build the image in the cluster

OpenShift can build straight from the Dockerfile — no local registry needed:

```bash
oc new-build --name=capstone2 --binary --strategy=docker
oc start-build capstone2 --from-dir=. --follow
oc get istag capstone2:latest        # confirm the image exists
```

### Step 4 — apply the manifests

```bash
oc apply -f docs/openshift/
oc get pods -w
```

### Step 5 — set the public URLs from the real Route hostnames

The Routes get their hostnames from the cluster, so the URLs are not known
until they exist. Patch the ConfigMap and restart:

```bash
CUST=$(oc get route customer-dashboard -o jsonpath='{.spec.host}')
ASSOC=$(oc get route associates-dashboard -o jsonpath='{.spec.host}')
API=$(oc get route api -o jsonpath='{.spec.host}')

oc patch configmap capstone2-config --type merge -p "{\"data\":{
  \"PUBLIC_CUSTOMER_URL\":\"https://$CUST\",
  \"PUBLIC_ASSOCIATES_URL\":\"https://$ASSOC\",
  \"PUBLIC_API_URL\":\"https://$API\"}}"

oc rollout restart deployment/customer-dashboard deployment/associates-dashboard deployment/api
oc rollout status deployment/customer-dashboard
```

> ⚠️ Skip this step and every cross-app link points at `localhost`, and the
> API's CORS allow-list rejects the dashboards.

### Step 6 — seed the database

```bash
oc get pods -l app=api
oc exec deployment/api -- python setup_database2.py
```

### Step 7 — open it

```bash
echo "https://$(oc get route customer-dashboard -o jsonpath='{.spec.host}')"
echo "https://$(oc get route associates-dashboard -o jsonpath='{.spec.host}')"
echo "https://$(oc get route api -o jsonpath='{.spec.host}')/docs"
```

### Operating it on OpenShift

```bash
oc get pods                                   # status
oc logs -f deployment/customer-dashboard      # follow logs
oc rsh deployment/api                         # shell in
oc scale deployment/customer-dashboard --replicas=3
oc rollout restart deployment/api
oc rollout undo deployment/api                # roll back
oc describe pod <pod>                         # why is it not starting
oc get events --sort-by=.lastTimestamp
```

### OpenShift-specific notes

| Topic | What to know |
|---|---|
| **Streamlit + replicas** | Streamlit holds per-session state in the server process. Scaling past 1 replica needs sticky sessions — the Routes set `haproxy.router.openshift.io/balance: source`. Without it a user bounces between pods and appears logged out |
| **Login lockout** | Already safe across replicas — `login_guard.py` stores attempts in Postgres, not in memory |
| **Random UID** | OpenShift runs containers as an arbitrary UID. The image writes nothing outside `/tmp`, so no `chmod` dance is needed |
| **`APP_ENV=production`** | Set in the ConfigMap. A weak secret fails the pod at startup — that is the intended behaviour, check `oc logs` for the list |
| **Postgres** | The StatefulSet is fine for a demo. For anything real, use a managed database and point `DATABASE_URL` at it |

---
---

# Chapter 14 — Going Live With Real Data

> **This is the single biggest gap in the project, and it is a known one.**
> Everything today runs on a **static extract**. There is no refresh path, no
> incremental load, and no live connection to a case system. The product is
> honest about this — the header says *"data as of 11 Jun 2026"* and the
> System tab shows the extract age — but honest is not the same as live.

## 14.1 What has to change

```mermaid
graph LR
    subgraph NOW["📦 Today — static"]
        X1["3 source files"] --> X2["setup_database2.py<br/>(manual, one shot)"] --> X3["PostgreSQL"]
    end

    subgraph LIVE["🔄 Live"]
        Y1["Case system<br/>API / CDC / export"] --> Y2["ingest job<br/>scheduled"] --> Y3["staging tables"]
        Y3 --> Y4["validate"] --> Y5["upsert"] --> Y6["PostgreSQL"]
        Y6 --> Y7["bump data_as_of<br/>clear caches"]
    end

    NOW ==>|"replace the loader,<br/>not the app"| LIVE

    style X2 fill:#94A3B8,color:#fff
    style Y2 fill:#10B981,color:#fff
    style Y7 fill:#F59E0B,color:#fff
```

**The good news:** the application layer does not need to change. Every
calculation reads from the database through `db.py` and every one of them is
recomputed per request. Point the same tables at fresher rows and the whole
product becomes live. The work is **all in the loader**.

## 14.2 The five things to build

### 1. An ingest job

Replace the one-shot `setup_database2.py` with something that can run
repeatedly. The minimum contract:

```python
# ingest.py  — sketch, not yet implemented
def ingest(since: datetime) -> IngestResult:
    rows = fetch_cases_updated_since(since)   # API / export / CDC
    with staging_transaction() as tx:
        load_into_staging(tx, rows)
        problems = validate(tx)               # fail loudly, do not silently drop
        if problems:
            raise IngestFailed(problems)
        upsert_into_live(tx)                  # ON CONFLICT (case_number) DO UPDATE
    record_watermark(max(r.last_update for r in rows))
    return IngestResult(inserted=..., updated=..., as_of=...)
```

**Upsert, never truncate-and-reload.** `desk_user_state` holds user follow-ups
and private notes keyed by case number. A truncate wipes the engineer's
working set.

### 2. A watermark

Store the high-water mark of `last_update_date` and pull only rows past it.
Without this, every run is a full reload and the job gets slower every day.

```sql
CREATE TABLE IF NOT EXISTS ingest_watermark (
    source       TEXT PRIMARY KEY,
    last_seen    TIMESTAMP NOT NULL,
    last_run_at  TIMESTAMP NOT NULL,
    rows_loaded  INTEGER   NOT NULL DEFAULT 0
);
```

### 3. Cache invalidation

Streamlit caches with `@st.cache_data`. Fresh rows behind a warm cache means
the engineer stares at yesterday's queue. Key the cache on the extract stamp so
a new load invalidates it automatically:

```python
@st.cache_data(ttl=300)
def load_cases(as_of_stamp: str):   # <- include the stamp in the signature
    ...
load_cases(current_data_as_of())    # changes → cache miss → refresh
```

A `ttl` alone is a weaker fallback: it bounds staleness but does not track it.

### 4. Reference-clock removal

`desk_reference_time()` currently returns the **latest timestamp in the
dataset** (`2026-06-11 00:00:00`) rather than `now()`, so that a months-old
extract does not show every case as absurdly overdue. With live data, switch it
to real wall-clock time:

```python
def desk_reference_time():
    if LIVE_DATA:            # feature flag
        return datetime.now(timezone.utc)
    return max_timestamp_in_dataset()
```

Do this **and** re-check the SLA targets in the same change. Every calculation
that depends on age — priority, SLA state, staleness, aging buckets, anomaly
windows — moves at once.

### 5. Freshness monitoring

The System tab already shows extract age. Add an alert when it exceeds the
ingest interval — a silently dead ingest job that leaves a plausible-looking
dashboard on screen is worse than an outage, because nobody notices.

## 14.3 Adding a new field

Say the live feed carries `first_response_at`, which the extract does not.

```mermaid
graph LR
    A["1 ── schema<br/>db/init/01_schema.sql"] --> B["2 ── loader<br/>map + backfill NULL"]
    B --> C["3 ── read path<br/>db.py query"]
    C --> D["4 ── calculation<br/>my_desk.py"]
    D --> E["5 ── UI<br/>timeline / readiness"]
    E --> F["6 ── tests<br/>+ null case"]
    F --> G["7 ── System tab<br/>coverage %"]

    style A fill:#3B82F6,color:#fff
    style F fill:#10B981,color:#fff
```

```sql
-- 1. schema  (nullable — old rows will not have it)
ALTER TABLE support_cases ADD COLUMN first_response_at TIMESTAMP;
```

Then, in order:

| Step | File | What |
|---|---|---|
| 2 | ingest | Map the source field. Leave historical rows `NULL`, do **not** estimate |
| 3 | `db.py` | Add it to the case query |
| 4 | `my_desk.py` | Use it where the code currently says *"not recorded in this dataset"* |
| 5 | UI | Timeline gains a real first-response marker; readiness gains a real check |
| 6 | `tests/` | **Add a test for the NULL case.** Mixed coverage is the normal state during a backfill |
| 7 | System tab | Report coverage — *"first response recorded on 64% of cases"* |

> 🚫 **Never backfill an estimate.** If 400 historical cases have no first
> response time, they must keep saying *"not recorded"*. An interpolated value
> is an invented fact, and it will be quoted to a customer. This is rule #1 of
> the project (§1.3).

## 14.4 Adding a new data source

A new source (say, a knowledge-base article feed for the Similar tab) follows
the same shape:

1. **New table**, with a foreign key to something that already exists
2. **Loader** with its own watermark row
3. **Read function** in `db.py` — not a raw query scattered through the UI
4. **Graceful degradation.** The table may be empty or the load may have
   failed. Every feature that uses it must render a clear *"no articles
   indexed"* rather than an empty box or a traceback — this is exactly how
   `desk_user_state` and `login_attempts` already behave
5. **Tests** for both the populated and the empty case

## 14.5 Scheduling the ingest

**Compose** — a sidecar with a loop, or a host cron:

```bash
# every 15 minutes
*/15 * * * * cd /opt/capstone2 && podman-compose -f docker-compose.yml -f docker-compose.prod.yml run --rm seed python ingest.py >> /var/log/capstone2-ingest.log 2>&1
```

**OpenShift** — a `CronJob`:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: capstone2-ingest
spec:
  schedule: "*/15 * * * *"
  concurrencyPolicy: Forbid        # never two loads at once
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: ingest
              image: image-registry.openshift-image-registry.svc:5000/capstone2/capstone2:latest
              command: ["python", "ingest.py"]
              envFrom:
                - configMapRef: {name: capstone2-config}
                - secretRef:    {name: capstone2-secrets}
              env:
                - name: DATABASE_URL
                  value: postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@postgres:5432/$(POSTGRES_DB)
```

`concurrencyPolicy: Forbid` matters — two overlapping loads racing on the same
upsert will deadlock or interleave partial state.

## 14.6 What live data fixes for free

| Today | With live data |
|---|---|
| 100% of open cases show 🔴 Breached | A real spread of green / gold / red |
| Median open-case age 376 days | Realistic ages, so the aging buckets mean something |
| "What changed" compares against an unchanging extract | Genuinely new and newly-resolved cases |
| Anomaly detection over a frozen window | Real arrival-rate spikes, worth acting on |
| Priority ordering is stable forever | Reorders as cases age and progress |

None of those need a code change beyond §14.2 — they are all downstream of the
reference clock and fresher rows.

---
---

# Chapter 15 — Configuration Reference

`config.py` is the single source of truth. **It validates at import time**, so
a bad configuration fails at startup with a list of every problem, not at 3 a.m.
on the first request.

```python
import config     # ← raises RuntimeError here if production config is wrong
```

## Every variable

| Variable | Default (dev) | Required in prod | Notes |
|---|---|---|---|
| `APP_ENV` | `development` | — | `production` turns on all validation |
| `DATABASE_URL` | SQLite fallback | ✅ | PostgreSQL connection string |
| `POSTGRES_USER` / `_PASSWORD` / `_DB` | `capstone` / weak / `capstone2` | ✅ | Password min 12 chars |
| `POSTGRES_HOST` / `_PORT` | `localhost` / `5433` | — | |
| `JWT_SECRET_KEY` | published placeholder | ✅ **min 32** | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `JWT_EXPIRE_MINUTES` | `60` | — | |
| `FRONTEND_TOKEN_SECRET` | published placeholder | ✅ **min 32** | Anti-scraping HMAC key |
| `ADMIN_PASSWORD` | `admin2026` | ✅ **min 12** | |
| `MANAGER_PASSWORD` | `manager2026` | ✅ **min 12** | |
| `ASSOCIATE_PASSWORD` | `associate2026` | ✅ **min 12** | |
| `PUBLIC_CUSTOMER_URL` | `http://localhost:8501` | ✅ | Must be `https://` |
| `PUBLIC_ASSOCIATES_URL` | `http://localhost:8502` | ✅ | Must be `https://` |
| `PUBLIC_API_URL` | `http://localhost:8503` | ✅ | Must be `https://` |
| `CORS_ORIGINS` | derived from the URLs above | — | Comma-separated override |
| `ALLOW_INSECURE_HTTP` | `false` | — | Permits `http://` when TLS ends elsewhere |
| `DOTENV_DISABLE` | `false` | — | Ignore any `.env`; environment only |
| `MAX_LOGIN_ATTEMPTS` | `5` | — | |
| `LOCKOUT_SECONDS` | `300` | — | |
| `HANDOFF_TTL_SECONDS` | `60` | — | Cross-app link lifetime |
| `AI_ENDPOINT_URL` | Granite endpoint | — | Features degrade gracefully if unset |
| `AI_MODEL_ID` | `ibm-granite/granite-3.1-8b-instruct` | — | |
| `AI_API_TOKEN` | placeholder | — | |
| `CUSTOMER_DOMAIN` / `ASSOCIATES_DOMAIN` / `API_DOMAIN` | — | ✅ *(Caddy only)* | For the TLS proxy |
| `ACME_EMAIL` | — | ✅ *(Caddy only)* | Certificate renewal notices |

## The validation rules

```python
_MIN_SECRET_LEN = 32          # 12 for passwords
_PUBLISHED      = { ... }     # every weak value that appears in this repository
```

In `production`, `validate()` collects **all** of these and raises one
`RuntimeError` listing every one:

| Rule | Failure message |
|---|---|
| Secret missing | `JWT_SECRET_KEY is not set` |
| Secret too short | `JWT_SECRET_KEY must be at least 32 characters` |
| Secret published in this repo | `JWT_SECRET_KEY is a placeholder published in this repository` |
| URL still `localhost` | `PUBLIC_CUSTOMER_URL must be a real public URL` |
| URL is plain `http://` | `PUBLIC_CUSTOMER_URL must use https:// (or set ALLOW_INSECURE_HTTP=true)` |

Collecting them all is deliberate: fixing one secret only to hit the next on
restart wastes a deployment cycle each time.

## Dotenv precedence

```python
load_dotenv(override=False)    # the real environment WINS over .env
```

This was a genuine bug when it read `override=True`: a `.env` baked into the
image would silently override what the orchestrator injected, so a correctly
configured cluster would still boot with laptop secrets. `DOTENV_DISABLE=1`
ignores `.env` entirely and is what the OpenShift ConfigMap sets.

## Generating secrets

```bash
python -c "import secrets;print(secrets.token_urlsafe(48))"   # 64 chars
openssl rand -base64 48
```

---
---

# Chapter 16 — Troubleshooting

## Startup

| Symptom | Cause | Fix |
|---|---|---|
| `RuntimeError` listing several config problems | `APP_ENV=production` and weak/missing secrets | Fix **every** item listed — it prints them all at once |
| `PUBLIC_CUSTOMER_URL must use https://` | Plain HTTP in production | Use HTTPS, or `ALLOW_INSECURE_HTTP=true` if TLS ends upstream |
| App boots with the wrong secrets in a container | A `.env` was baked into the image | `DOTENV_DISABLE=1` |
| `Address already in use` | Old Streamlit still running | `pkill -f "streamlit run app1.py"` — on its own line |
| `pkill` returns exit 144 | It killed the compound command that was also starting the app | Run the kill separately, then start the app |

## Database

| Symptom | Fix |
|---|---|
| `could not connect to server` | `podman-compose ps` — is `db` healthy? Check `DATABASE_URL` host: `db` inside compose, `localhost` outside |
| Empty dashboards | Seed did not run: `podman-compose run --rm seed python setup_database2.py` |
| *"notes are not being saved"* | `desk_user_state` could not be created. The UI names the active backend — check DB write permission |
| Lockout not shared across replicas | `login_attempts` table missing; `login_guard.backend()` returns `"memory"` |

## Authentication

| Symptom | Cause |
|---|---|
| Logged out on refresh | The `?token=` was stripped from the URL |
| Cross-app link says *"session expired"* | Handoff token is 60 s by design — it was clicked late, or clocks are skewed. Re-click it |
| `This is a dashboard token, not an API token` | Correct behaviour. Get an API token from `POST /auth/login` |
| *"Too many failed attempts"* | 5 failures → 5-minute lockout. Wait, or `DELETE FROM login_attempts WHERE email='…'` |
| Registration refused | Only `@redhat.com` addresses that exist in the source data, with a matching role |

## UI

| Symptom | Cause | Fix |
|---|---|---|
| Raw `</div>` visible on the page | A multi-line HTML template with a blank line — CommonMark ends the block there | Wrap it in `_html()` from `workspace_utils.py`. `pytest tests/test_html_render.py` |
| Every case shows 🔴 Breached | Correct for this dataset — 569/569 open cases, median age 376 days | Raise the SLA targets in the UI while exploring |
| Filter chips clear themselves when an SLA target changes | Counts baked into the option *values* | Keep counts in `format_func`; option values stay bare labels |
| Guided tour highlights nothing | A `st.container(key=…)` was renamed | Fix the `sel` in the tour step |
| No AI summary | Endpoint unreachable or `AI_API_TOKEN` unset | Handoff falls back to a deterministic local brief. Other AI panels say so rather than inventing |

## Containers

```bash
podman-compose ps                         # what is up
podman logs -f <container>                # why it died
podman-compose -f docker-compose.yml -f docker-compose.prod.yml config   # merged config
podman exec -it <container> /bin/bash     # look inside
podman-compose down -v                    # nuke the database and start over
```

## OpenShift

| Symptom | Fix |
|---|---|
| `CrashLoopBackOff` | `oc logs <pod>` — usually config validation. Fix the Secret and `oc rollout restart` |
| `CreateContainerConfigError` | `capstone2-secrets` missing or a key absent. `oc describe pod <pod>` names it |
| Cross-app links point at localhost | `PUBLIC_*_URL` still `REPLACE-ME` — do §13.4 step 5 |
| CORS errors from the dashboards | Same cause: the API derives its allow-list from those URLs |
| Random logouts under load | Sticky sessions missing. Confirm `haproxy.router.openshift.io/balance: source` on the Route |
| Websocket disconnects after 30 s | Route `timeout` annotation missing |

---
---

# Chapter 17 — File-by-File Map

```mermaid
graph TD
    subgraph ENTRY["🚪 Entry points"]
        A1["app1.py<br/>4,566 lines"]
        A2["app2.py<br/>6,493 lines"]
        AP["api.py<br/>439 lines"]
    end
    subgraph SHARED["🔧 Shared modules"]
        MD["my_desk.py<br/>3,319 lines"]
        WU["workspace_utils.py"]
        WS["workspace_selector.py"]
        WX["workspace_switcher.py"]
        CF["config.py"]
        LG["login_guard.py"]
        DB["db.py"]
        MW["middleware.py"]
    end
    subgraph DATA["💾 Data"]
        SD["setup_database2.py"]
        SC["db/init/01_schema.sql"]
        XL["data/*.xlsx · *.csv"]
    end

    A1 --> WU & WS & WX & CF & LG & DB
    A2 --> MD & WU & WS & WX & CF & LG & DB
    AP --> CF & DB & MW
    MD --> WU & DB
    SD --> XL & DB
    DB --> SC

    style A1 fill:#3B82F6,color:#fff
    style A2 fill:#3B82F6,color:#fff
    style AP fill:#8B5CF6,color:#fff
    style MD fill:#10B981,color:#fff
    style CF fill:#F59E0B,color:#fff
```

## Application code

| File | Lines | Responsibility |
|---|---:|---|
| `app2.py` | 6,493 | Associates dashboard (:8502). Login, RBAC, 4 tabs, 19-step guided tour. **Renders My Desk** |
| `app1.py` | 4,566 | Customer Intelligence dashboard (:8501). Account cards, health scores, compare mode, AI chatbot |
| `my_desk.py` | 3,319 | **The operations workspace.** Every calculation in Chapter 10 lives here |
| `setup_database2.py` | 508 | One-shot loader: Excel/CSV → PostgreSQL. Replace this to go live (Ch 14) |
| `api.py` | 439 | FastAPI REST service (:8503), 14 endpoints |
| `config.py` | 165 | **Single source of truth for secrets and URLs.** Validates at import |
| `workspace_selector.py` | 123 | The post-login gate: Customer or Associates |
| `login_guard.py` | 116 | DB-backed login lockout, shared across replicas |
| `middleware.py` | 105 | Anti-scraping HMAC verification for the API |
| `workspace_utils.py` | 99 | `_html()`, handoff minting, cross-app URL building |
| `db.py` | 95 | Connection layer. PostgreSQL primary, SQLite fallback (`IS_PG`, `PARAM`) |
| `workspace_switcher.py` | 60 | The in-app switch control |

## Tests — 185

| File | Lines | Tests |
|---|---:|---:|
| `tests/test_my_desk.py` | 545 | 67 |
| `tests/test_hosting.py` | 252 | 27 |
| `tests/test_html_render.py` | 248 | 34 |
| `tests/test_api.py` | 184 | 26 |
| `tests/test_data.py` | 138 | 23 |
| `tests/test_auth.py` | 74 | 8 |
| `tests/conftest.py` | 45 | — |

## Data, deployment, docs

| File | What |
|---|---|
| `data/support_cases.xlsx` | 1,000 cases |
| `data/associates.xlsx` | 228 associates, 1,015 skills |
| `data/accounts.xlsx` / `.csv` | 202 accounts |
| `db/init/01_schema.sql` | 84 lines — the six-table schema |
| `Dockerfile` | `python:3.11-slim`, exposes 8501/8502/8503 |
| `docker-compose.yml` | Dev: bind mounts, `--reload`, published ports |
| `docker-compose.prod.yml` | **Overlay.** TLS, health checks, no published app ports |
| `Caddyfile` | TLS termination + security headers |
| `docs/openshift/*.yaml` | ConfigMap, Postgres StatefulSet, 3 × Deployment/Service/Route |
| `start.sh` | Launch both dashboards locally |
| `.env.sample` | Every variable, commented |
| `README.md` | Quick reference + the Hosting chapter |
| `docs/PROJECT_HANDBOOK.md` | This book |

## The two key shared abstractions

**`db.py`** — never open a connection yourself:

```python
from db import get_connection, get_dict_connection, get_engine, IS_PG, PARAM

with get_connection() as conn:
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM support_cases WHERE case_number = {PARAM}", (num,))
```

`PARAM` is `%s` on PostgreSQL and `?` on SQLite. Hardcoding either breaks the
other backend — and the SQLite path is what the test suite runs on.

**`workspace_utils._html()`** — every multi-line HTML template goes through it:

```python
from workspace_utils import _html
st.markdown(_html(f"""
    <div class="card">
      <span>{title}</span>
    </div>
"""), unsafe_allow_html=True)
```

---
---

# Chapter 18 — Design Rules & Glossary

## 18.1 The rules — read these before writing any code

### 🚫 Never invent data

The hardest rule and the most important. The product must **never** generate:

| Never invent | Say instead |
|---|---|
| Log contents | *"Not available in current case data."* |
| Customer statements or sentiment | *"Not available in current case data."* |
| Timestamps the dataset does not hold | *"not recorded in this dataset"* |
| Technical root causes | *"Not available in current case data."* |
| Engineer availability | **"shift on record"**, never "available" |
| SLA commitments | Only the configured target |
| Troubleshooting steps taken | *"Not available in current case data."* |
| Resolution details | *"Not available in current case data."* |

Why so strict? A support engineer reads this screen and then talks to a
customer. An invented detail becomes something Red Hat said.

### 🚫 Never fake an action

A button that looks like it works but does nothing is worse than no button.
Status change, reassign and escalate are rendered **disabled with the reason
shown**: *"the analytics database is read-only for case data"*.

### 🚫 Never call arithmetic a prediction

The escalation model is a smoothed naive Bayes over historical rates. The UI
says **"observed historical pattern"** and shows its own held-out AUC. It never
says "predicted", "will escalate", or "likely to".

### 🚫 Never break what exists

| Rule | Why |
|---|---|
| `app1.py` and `app2.py` stay separate | Two audiences, two deployments. They are joined by shared modules and SSO, not merged |
| Do not break the guided tours | They point at `.st-key-*` selectors; renaming a container key breaks a step |
| Do not break RBAC or authentication | Three roles, enforced at the data layer, not just the UI |
| Do not change the PostgreSQL architecture | SQLite is the *fallback*, not an alternative |
| No unnecessary dependencies | TF-IDF and naive Bayes are pure Python on purpose |
| Existing tests stay green | 185, all passing. Add, never remove |

### ⚖️ Incremental, not redesigned

CSS tweaks over component replacements. If a change would make the product
unrecognisable to someone who used it last week, it is out of scope.

## 18.2 Three accepted risks

These are **known and deliberately accepted**. Do not "discover" them as new
findings, and do not silently patch them.

**1. The session JWT lives in the browser URL.**
Streamlit cannot set cookies natively, and the `?token=` parameter *is* the
refresh-persistence mechanism — removing it breaks existing authentication.
Mitigated three ways instead:

- cross-app links carry a **60-second** `typ="handoff"` token, not the session token
- the REST API **rejects** `typ` of `session` or `handoff`
- Caddy sets `Referrer-Policy: no-referrer`, so the URL never leaves in a `Referer` header

The real fix is cookie-based sessions via a custom component or an
authenticating proxy. That is a redesign, not a patch.

**2. The data is a static extract with no refresh path.**
No application change addresses this; it needs a live feed. Chapter 14 is the
plan.

**3. The production config gate cannot reach the seeded dashboard passwords.**
`config.py` refuses to start when `ADMIN_PASSWORD`, `MANAGER_PASSWORD` or
`ASSOCIATE_PASSWORD` is left at a value published in this repository. It
cannot do the same for `SEED_MANAGER_PASSWORD` and `SEED_ASSOCIATE_PASSWORD`,
because by the time any application imports `config.py` those two exist only
as bcrypt hashes in `registered_users` — there is no plaintext left to compare
against the published list.

Closing it properly means either importing `config.py` into
`setup_database2.py` (which would make the loader enforce the *entire*
production configuration, including public URLs, before it will seed — a
larger behavioural change than it looks) or storing a marker alongside the
hash. Neither is a patch. Until then the mitigation is procedural and stated
in three places: set both variables **before** the database build, because
afterwards the value is a hash and changing the variable does nothing.

## 18.3 Glossary

| Term | Meaning |
|---|---|
| **SBR** | Strategic Business Representative — the team a case is routed to (14 in this dataset) |
| **TAM** | Technical Account Manager |
| **CSAT** | Customer Satisfaction score, 1–5 |
| **TTR** | Time To Resolve, hours |
| **SLA ratio** | `age_hours / sla_target_hours`. ≥ 1.0 is breached |
| **Priority score** | 0–100 weighted sum. Queue order, not a prediction (§10.1) |
| **Health score** | 0–100 account badge, four components (§10.3) |
| **Potential SME** | An engineer with documented experience. **Not** an availability claim |
| **Shift on record** | The historical shift pattern in the data. Not a rota |
| **Handoff token** | 60-second JWT for cross-app links, `typ="handoff"` |
| **Session token** | 60-minute JWT in the browser URL, `typ="session"` |
| **Reference clock** | `2026-06-11 00:00:00` — latest timestamp in the extract, used instead of `now()` |
| **Waiting status** | A status where the engineer cannot progress. Priority × 0.45 |
| **Observed historical pattern** | A `GROUP BY` over closed cases. Never a prediction |
| **Overlay** | `docker-compose.prod.yml` — differences only, never run alone |
| **Type 1 HTML block** | CommonMark: `<style>`, `<script>`, `<pre>`, `<textarea>`. Immune to blank lines; everything else is not (§12) |

## 18.4 The 60-second version for whoever inherits this

```
WHAT   An operational workspace for Red Hat support engineers, plus an
       account-health dashboard for managers.

WHERE  app2.py :8502 is where engineers live (My Desk is the default tab).
       app1.py :8501 is the account view. api.py :8503 is the REST service.
       They share config.py, db.py, workspace_utils.py and one JWT secret.

DATA   PostgreSQL 16. 1,000 cases · 228 associates · 202 accounts.
       A STATIC EXTRACT — the clock is frozen at 2026-06-11. See Chapter 14.

MATHS  Every number is arithmetic over recorded fields, explained on screen,
       and tested. Chapter 10 has the formulas and worked examples.

RULES  Never invent data. Never fake an action. Never call arithmetic a
       prediction. Never break the two apps apart or merge them together.

LOGIN  dashboards (email)        admin@redhat.com             / admin2026
                                 adaeze.nwachukwu@redhat.com  / manager123
                                 theo.krishnan@redhat.com     / associate123
       REST API  (username)      admin / manager / associate
                                 admin2026 / manager2026 / associate2026
       All public — APP_ENV=production refuses to start until they change.

RUN    ./start.sh                                          (laptop)
       podman-compose -f docker-compose.yml up -d          (containers)
       + -f docker-compose.prod.yml                        (TLS, hardened)
       oc apply -f docs/openshift/                         (cluster)

TEST   python -m pytest tests/ -q      →  185 passed
```

---
---

# Appendix A — Complete Inventory: Databases, Tables, Tools & Configs

> Everything the project touches, in one place: the database and its name, every
> table and column, every index, every dependency with the version actually
> installed, and every configuration file. Verified against the live system, not
> copied from the schema file.

---

## A.1 Databases

### The primary database — PostgreSQL

| Property | Value |
|---|---|
| **Engine** | PostgreSQL |
| **Version declared** in `docker-compose.yml` | `postgres:16-alpine` |
| **Version actually running** on this machine | **PostgreSQL 18.6** (host install, not the container) |
| **Database name** | **`capstone2`** |
| **Schema** | `public` |
| **User / role** | **`capstone`** |
| **Host · port — local dev right now** | `localhost:5432` |
| **Host · port — compose** | `localhost:5433` on the host, `db:5432` inside the network |
| **Host · port — OpenShift** | `postgres:5432` (headless Service) |
| **Connection string** | `postgresql://capstone:<password>@localhost:5432/capstone2` |
| **Set by** | `DATABASE_URL` in `.env` |
| **Data volume** | `pgdata` (compose) · `pgdata` PVC 5Gi (OpenShift) |
| **Tables** | **7** |

> ⚠️ **The declared and running versions differ.** The compose file pins
> `postgres:16-alpine`, but the database this workstation is actually pointed at
> is a locally installed **PostgreSQL 18.6 on port 5432** — not the compose
> container on 5433. Both work; the application uses nothing version-specific.
> Check which one you are on before you conclude a data problem is a code
> problem — see the commands in [A.7](#a7-inspection-commands).

### The fallback database — SQLite

| Property | Value |
|---|---|
| **File** | `capstone2.db` in the repository root |
| **Path constant** | `db.py` → `_SQLITE_PATH` |
| **Used when** | `DATABASE_URL` is unset, is not `postgresql…`, or the connection test fails |
| **Who uses it** | The **test suite** — all 185 tests run on SQLite |
| **Gitignored** | Yes (`*.db`) |

`db.py` decides once, at import, and the rest of the code just asks:

```python
IS_PG = _check_pg()          # tries a real connection with connect_timeout=3
PARAM = "%s" if IS_PG else "?"
```

```mermaid
graph TD
    S["import db"] --> Q{"DATABASE_URL starts<br/>with postgresql?"}
    Q -->|no| SQ["SQLite<br/>capstone2.db"]
    Q -->|yes| T{"psycopg2 connect<br/>succeeds in 3s?"}
    T -->|no| SQ
    T -->|yes| PG["PostgreSQL<br/>capstone2"]
    PG --> P1["IS_PG = True<br/>PARAM = '%s'"]
    SQ --> P2["IS_PG = False<br/>PARAM = '?'"]

    style PG fill:#336791,color:#fff
    style SQ fill:#94A3B8,color:#fff
```

> 🚫 **Never hardcode `%s` or `?` in a query.** Always use `PARAM`. Hardcoding
> either one breaks the other backend, and SQLite is what CI runs on — so a
> `%s` slips through local PostgreSQL testing and fails every test.

### Two files you can ignore

| File | What it is |
|---|---|
| `redhat_dashboard.db` | **0 bytes, dead.** A leftover from an early iteration. Nothing reads it |
| `capstone2.db` → `password_reset_otps` table | A table that exists only in the old SQLite file, not in the PostgreSQL schema. Not used by any current code path |

---

## A.2 Every table, every column

Seven tables. Five are created from the schema file; two are created on demand
by the code that needs them.

| # | Table | Columns | Live rows | Created by |
|---|---|---:|---:|---|
| 1 | `accounts` | 15 | 202 | `db/init/01_schema.sql` |
| 2 | `associates` | 12 | 228 | `db/init/01_schema.sql` |
| 3 | `support_cases` | 22 | 1,000 | `db/init/01_schema.sql` |
| 4 | `skills` | 6 | 1,015 | `db/init/01_schema.sql` |
| 5 | `registered_users` | 6 | 2 | `db/init/01_schema.sql` |
| 6 | `desk_user_state` | 5 | 68 | `my_desk.py` → `_STATE_DDL`, on demand |
| 7 | `login_attempts` | 4 | 1 | `login_guard.py` → `_DDL`, on demand |

### 1. `accounts` — 202 rows

| Column | Type | Notes |
|---|---|---|
| `account_id` | `VARCHAR(20)` | **PK** |
| `account_name` | `TEXT NOT NULL` | |
| `sector` | `VARCHAR(100)` | Filter facet |
| `account_notes` | `TEXT` | |
| `annual_revenue` | `BIGINT` | |
| `contract_start_date` | `DATE` | |
| `contract_end_date` | `DATE` | Drives the Expired / Expiring Soon / Active badge |
| `support_tier` | `VARCHAR(50)` | Premium Plus · Premium · Standard · Self-Support |
| `tam_assigned` | `VARCHAR(200)` | |
| `region` | `VARCHAR(50)` | APAC · EMEA · LATAM · NASA |
| `employee_count` | `INTEGER` | |
| `created_at` | `TIMESTAMP DEFAULT NOW()` | Row insert time, **not** a business date |
| `revenue_segment` | `VARCHAR(50)` | Bucketed from `annual_revenue` by the loader |
| `hq_location` | `TEXT` | |
| `company_background` | `TEXT` | |

### 2. `associates` — 228 rows

| Column | Type | Notes |
|---|---|---|
| `associate_id` | `VARCHAR(20)` | **PK** |
| `associate_name` | `TEXT NOT NULL` | |
| `email` | `VARCHAR(200)` | Gates registration — must already exist here |
| `sbr` | `VARCHAR(100)` | 16 distinct teams — two more than `support_cases.sbr` ever uses |
| `shift` | `VARCHAR(50)` | Rendered as **"shift on record"**, never "available" |
| `skill_level` | `VARCHAR(50)` | |
| `manager_name` | `VARCHAR(200)` | Defines a manager's team scope |
| `manager_email` | `VARCHAR(200)` | Gates manager registration |
| `hire_date` | `DATE` | |
| `certifications` | `TEXT` | |
| `active` | `INTEGER DEFAULT 1` | |
| `created_at` | `TIMESTAMP DEFAULT NOW()` | |

### 3. `support_cases` — 1,000 rows

The central table. Every calculation in Chapter 10 reads from it.

| Column | Type | Used by |
|---|---|---|
| `case_number` | `VARCHAR(30)` | **PK**. Joins `desk_user_state` |
| `account_id` | `VARCHAR(20)` | FK → `accounts` |
| `account_name` | `TEXT` | Denormalised for display |
| `case_owner` | `VARCHAR(200)` | FK-ish → `associates.associate_name`. Drives **My Cases** scope |
| `severity` | `VARCHAR(50)` | Severity 1–4 → `SEV_WEIGHT` and the SLA target |
| `status` | `VARCHAR(50)` | Open · In Progress · Waiting on Customer · Waiting on Engineering · Resolved · Closed |
| `product_name` | `VARCHAR(200)` | 28 distinct. Risk feature, anomaly key |
| `creation_date` | `DATE` | Case **age**, therefore SLA ratio and priority |
| `closed_date` | `DATE` | |
| `escalated` | `INTEGER DEFAULT 0` | 0/1. Flat +10 priority, and rule 1 of the next-action ladder |
| `csat_score` | `NUMERIC(3,2)` | 1–5. Health score, account risk |
| `time_to_resolve_hours` | `NUMERIC(10,2)` | Health score speed component |
| `case_summary` | `TEXT` | |
| `created_at` | `TIMESTAMP DEFAULT NOW()` | Row insert time |
| `sbr` | `VARCHAR(100)` | 14 distinct. Team scope, risk feature |
| `problem_statement` | `TEXT` | 84 distinct. Pattern grouping |
| `description` | `TEXT` | **TF-IDF corpus** and the readiness text checks |
| `product_version` | `VARCHAR(100)` | SME weight 3.0, anomaly key |
| `sovereign_support` | `VARCHAR(50)` | |
| `business_hours` | `VARCHAR(50)` | Risk feature |
| `last_updated` | `DATE` | **Staleness** component of the priority score |
| `resolution_date` | `DATE` | Timeline |

> 🚫 **Fields that do not exist**, and therefore must never be shown: first
> response time, escalation timestamp, reproduction steps, diagnostic bundle
> reference, customer sentiment, engineer availability. The System tab lists
> them and says what each absence costs.

### 4. `skills` — 1,015 rows

| Column | Type | Notes |
|---|---|---|
| `id` | `SERIAL` | **PK** |
| `associate_id` | `VARCHAR(20)` | **FK → `associates(associate_id)`** — the only declared FK in the schema |
| `associate_name` | `TEXT` | Denormalised |
| `skill_name` | `VARCHAR(200)` | |
| `skill_rank` | `INTEGER` | 1–5 |
| `relevance_score` | `NUMERIC(5,2)` | |

Derived, not loaded: `setup_database2.py` → `build_skills_table()` mines the
top 5 skills per associate from their case history.

### 5. `registered_users` — 2 rows

| Column | Type | Notes |
|---|---|---|
| `id` | `SERIAL` | **PK** |
| `email` | `VARCHAR(200)` | **UNIQUE NOT NULL** |
| `password_hash` | `TEXT NOT NULL` | bcrypt via passlib |
| `role` | `VARCHAR(20)` | **`CHECK(role IN ('manager','associate'))`** — admin is *not* storable here |
| `display_name` | `TEXT NOT NULL` | The name in "Good morning, Yuki" |
| `created_at` | `TIMESTAMP DEFAULT NOW()` | |

The `CHECK` constraint is why admin is a hardcoded account: the database will
reject `role = 'admin'`.

### 6. `desk_user_state` — 68 rows · created on demand

Follow-ups and private notes. **The only table the application writes to during
normal use.**

| Column | Type | Notes |
|---|---|---|
| `user_email` | `TEXT NOT NULL` | **PK part 1** |
| `kind` | `TEXT NOT NULL` | **PK part 2** — `follow_up` or `note` |
| `case_number` | `TEXT NOT NULL` | **PK part 3** |
| `payload` | `TEXT` | Note body / follow-up metadata |
| `updated_at` | `TEXT` | |

Created by `my_desk.py` → `_STATE_DDL`. If the `CREATE TABLE` fails (no write
permission), `_state_backend()` returns `"session"` and notes live only for the
browser session — and the UI says which backend is in force rather than
pretending the save worked.

### 7. `login_attempts` — 1 row · created on demand

| Column | Type (PostgreSQL) | Type (SQLite) |
|---|---|---|
| `email` | `TEXT` **PK** | same |
| `attempts` | `INTEGER NOT NULL DEFAULT 0` | same |
| `locked_until` | `DOUBLE PRECISION` | `REAL` |
| `updated_at` | `DOUBLE PRECISION` | `REAL` |

Created by `login_guard.py` → `_DDL` (`_DDL_SQLITE` swaps the float type). This
table is what makes the 5-attempt lockout survive a restart and hold across
replicas. If it cannot be created, `backend()` returns `"memory"` and the
lockout degrades to per-process.

---

## A.3 Indexes

29 in the live database: 7 primary keys, 1 unique constraint, and 21 explicit
indexes.

| Table | Indexes |
|---|---|
| `accounts` | `accounts_pkey` · `idx_accounts_account_id` · `idx_accounts_region` · `idx_accounts_revenue_segment` · `idx_accounts_sector` · `idx_accounts_support_tier` |
| `associates` | `associates_pkey` · `idx_associates_associate_id` · `idx_associates_manager` · `idx_associates_sbr` |
| `support_cases` | `support_cases_pkey` · `idx_cases_account` · `idx_cases_account_id` · `idx_cases_case_owner` · `idx_cases_creation_date` · `idx_cases_escalated` · `idx_cases_owner` · `idx_cases_product` · `idx_cases_sbr` · `idx_cases_severity` · `idx_cases_status` |
| `skills` | `skills_pkey` · `idx_skills_assoc` · `idx_skills_associate_id` · `idx_skills_skill_name` |
| `registered_users` | `registered_users_pkey` · `registered_users_email_key` |
| `desk_user_state` | `desk_user_state_pkey` (composite: email + kind + case) |
| `login_attempts` | `login_attempts_pkey` |

Indexes come from **two places** — `db/init/01_schema.sql` creates five, and
`setup_database2.py` → `create_indexes()` creates eighteen more.

**Four of them are redundant** — the two files index the same column under
different names, and two more shadow a primary key:

| Redundant index | Duplicates |
|---|---|
| `idx_cases_owner` | `idx_cases_case_owner` — both `btree (case_owner)` |
| `idx_skills_assoc` | `idx_skills_associate_id` — both `btree (associate_id)` |
| `idx_accounts_account_id` | `accounts_pkey` — both `btree (account_id)` |
| `idx_associates_associate_id` | `associates_pkey` — both `btree (associate_id)` |

> 💡 Harmless at this size — a little write throughput and disk on a 1,000-row
> table. If you consolidate, drop the duplicates from `01_schema.sql` and let
> `create_indexes()` be the single owner.

---

## A.4 Which module touches which table

| Table | Read by | Written by |
|---|---|---|
| `accounts` | `app1.py`, `app2.py`, `my_desk.py`, `api.py` | `setup_database2.py` only |
| `associates` | `app2.py`, `my_desk.py`, `api.py` | `setup_database2.py` only |
| `support_cases` | `app1.py`, `app2.py`, `my_desk.py`, `api.py` | `setup_database2.py`; **`app2.py` Data Management — admin only** (`INSERT` from CSV upload, `INSERT` from Manual Entry, `DELETE` from Delete Case) |
| `skills` | `app2.py`, `my_desk.py`, `api.py` | `setup_database2.py`; **`app2.py`** — *Add All Inferred Skills to Profile* (`INSERT`, needs `ai_extract`) |
| `registered_users` | `app1.py`, `app2.py` (login) | `app1.py`, `app2.py` (registration + password reset), `setup_database2.py` (seed) |
| `desk_user_state` | `my_desk.py` | **`my_desk.py`** — follow-ups and notes |
| `login_attempts` | `login_guard.py` | `login_guard.py` |

**Writes are narrow and gated.** `accounts` and `associates` are genuinely
read-only at runtime — only the loader touches them. `support_cases` and
`skills` have exactly the write paths listed above and nowhere else; both sit
behind a `ROLE_PERMISSIONS` check, and the delete requires a typed
confirmation.

> ⚠️ **My Desk still has no case-write path**, which is why its *Update status*
> / *Reassign* / *Escalate* buttons are rendered disabled with the reason
> shown. Do not wire them to the `app2.py` ingest helpers — those create and
> delete whole rows, they do not transition a case, and faking a status change
> on a static extract would be inventing data (§18.1).

---

## A.5 Tools and runtime

### System-level

| Tool | Version here | Role | Config file |
|---|---|---|---|
| **Python** | 3.14.7 (local) · 3.11-slim (container) | Runtime | `requirements.txt` |
| **PostgreSQL** | 18.6 local · `postgres:16-alpine` in compose · `rhel9/postgresql-16` on OpenShift | Primary database | `db/init/01_schema.sql`, `DATABASE_URL` |
| **SQLite** | stdlib `sqlite3` | Fallback + test database | none — path in `db.py` |
| **Podman** | 5.8.4 | Container engine (Docker-compatible) | `Dockerfile`, `docker-compose*.yml` |
| **podman-compose** | 5.8.4 | Orchestration | `docker-compose.yml` + `.prod.yml` |
| **Caddy** | `caddy:2-alpine` | TLS termination, security headers | `Caddyfile` |
| **OpenShift** | any 4.x | Cluster deployment | `docs/openshift/*.yaml` |
| **IBM Granite 3.1-8B** | hosted | AI summaries, chatbot, handoff brief | `AI_ENDPOINT_URL`, `AI_MODEL_ID`, `AI_API_TOKEN` |

> Docker is **not installed on this machine** — only Podman. Every `docker`
> command in this book works by swapping in `podman`; they are CLI-compatible
> for everything the project uses.

### Python dependencies

Declared in `requirements.txt`. The right-hand column is what is actually
installed here — worth checking, because pinned and installed have drifted.

| Package | Pin in `requirements.txt` | Installed | Used for |
|---|---|---|---|
| `streamlit` | `>=1.30.0` | **1.60.0** | Both dashboards; `AppTest` powers the render tests |
| `pandas` | `>=2.0.0` | **3.0.5** | Every DataFrame in the project |
| `numpy` | `>=1.24.0` | **2.5.1** | Numerics behind the scoring models |
| `plotly` | `>=5.18.0` | **6.9.0** | Every chart |
| `sqlalchemy` | `>=2.0.0` | **2.0.51** | Engine + pooling in `db.py` (`pool_size=5`, `max_overflow=10`, `pool_pre_ping`, `pool_recycle=300`) |
| `python-dotenv` | `>=1.0.0` | **1.2.2** | `.env` loading, always `override=False` |
| `requests` | `>=2.31.0` | **2.33.1** | Calls to the Granite endpoint |
| `openpyxl` | `>=3.1.0` | **3.1.5** | Reads the three `.xlsx` source files |
| `reportlab` | `>=4.0.0` | **5.0.0** | ⚠️ **Nothing imports it.** Declared for a PDF export that was never built — exports are CSV and Excel. Safe to drop |
| `python-jose[cryptography]` | `>=3.3.0` | **3.5.0** | JWT encode/decode, HS256 |
| `psycopg2-binary` | `>=2.9.9` | **2.9.12** | PostgreSQL driver |
| `fastapi` | `>=0.109.0` | **0.140.1** | The REST API |
| `uvicorn[standard]` | `>=0.27.0` | **0.51.0** | ASGI server |
| `passlib[bcrypt]` | `>=1.7.4` | **1.7.4** | Password hashing wrapper |
| `bcrypt` | `>=4.0.0,<4.1.0` | **4.3.0** ⚠️ | The hash itself |
| `cryptography` | `>=42.0.0` | **50.0.0** | Backs python-jose |
| `pytest` | *(not pinned)* | **9.1.1** | Test runner |

> ⚠️ **`bcrypt` is out of its pin.** `requirements.txt` says `<4.1.0`; 4.3.0 is
> installed. The upper bound was a passlib-compatibility workaround from an
> older release and no longer bites — all 185 tests pass, including the auth
> ones — but a fresh `pip install -r requirements.txt` will **downgrade** you
> to 4.0.x and produce a different environment from this one. Either widen the
> pin or accept the downgrade knowingly; do not leave it ambiguous.

---

## A.6 Every configuration file

| File | Purpose | In git? | Read by |
|---|---|---|---|
| **`.env`** | Real secrets and URLs for this machine | ❌ **gitignored** | `config.py`, `db.py`, compose `env_file` |
| **`.env.sample`** | Template with every variable, commented | ✅ | Humans — `cp .env.sample .env` |
| **`config.py`** | **Single source of truth.** Validates at import | ✅ | `app1.py`, `app2.py`, `api.py`, `middleware.py` |
| **`.streamlit/config.toml`** | Streamlit theme and server behaviour | ✅ | Streamlit, both apps |
| **`.streamlit/secrets.toml`** | Empty — a comment only. The app uses its own JWT auth | ✅ | Streamlit (must exist, or it warns) |
| **`requirements.txt`** | Python dependencies | ✅ | `pip`, `Dockerfile` |
| **`Dockerfile`** | Image: `python:3.11-slim`, `build-essential libpq-dev curl`, exposes 8501/8502/8503 | ✅ | Podman / Docker / OpenShift build |
| **`.dockerignore`** | Keeps the build context small | ✅ | Image build |
| **`docker-compose.yml`** | Dev: 5 services, bind mounts, `--reload`, published ports | ✅ | compose |
| **`docker-compose.prod.yml`** | **Overlay.** TLS, health checks, no published app ports | ✅ | compose, with the base file |
| **`Caddyfile`** | TLS + the `(hardening)` header snippet, 3 subdomain blocks | ✅ | The `proxy` container |
| **`db/init/01_schema.sql`** | 5 tables + 5 indexes. Auto-runs on first compose up | ✅ | Postgres entrypoint, `setup_database2.py` |
| **`docs/openshift/00-configmap.yaml`** | Non-secret cluster config | ✅ | `oc apply` |
| **`docs/openshift/10-postgres.yaml`** | StatefulSet + headless Service + 5Gi PVC | ✅ | `oc apply` |
| **`docs/openshift/20-api.yaml`** | Deployment + Service + Route, :8503 | ✅ | `oc apply` |
| **`docs/openshift/30-customer-dashboard.yaml`** | Deployment + Service + Route, :8501 | ✅ | `oc apply` |
| **`docs/openshift/40-associates-dashboard.yaml`** | Deployment + Service + Route, :8502 | ✅ | `oc apply` |
| **`start.sh`** | Launches both dashboards locally | ✅ | You |
| **`.gitignore`** | Excludes `.env`, `*.db`, `venv/`, `__pycache__/`, `.pytest_cache/`, … | ✅ | git |
| **`tests/conftest.py`** | Shared pytest fixtures | ✅ | pytest |

> ✅ **No live secret is committed.** `.env` is gitignored and
> `.streamlit/secrets.toml` contains a single comment line. Everything in
> `.env.sample` is a placeholder, and `APP_ENV=production` refuses to start on
> any of them.

### `.streamlit/config.toml` in full

```toml
[theme]
base = "light"
primaryColor = "#6366F1"
backgroundColor = "#F0F4F8"
secondaryBackgroundColor = "#FFFFFF"
textColor = "#1E293B"
font = "sans serif"

[server]
headless = true
fileWatcherType = "none"     # no inotify watchers — matters in a container
runOnSave = false
maxUploadSize = 50           # MB, for the CSV upload feature

[browser]
gatherUsageStats = false

[runner]
fastReruns = true            # re-runs cancel the previous run instead of queueing
```

### Which config wins

```mermaid
graph LR
    A["OS environment<br/>(compose · ConfigMap · Secret)"] -->|"highest"| C["config.py"]
    B[".env file"] -->|"only fills gaps"| C
    D["built-in dev defaults"] -->|"lowest"| C
    C --> V{"APP_ENV ==<br/>production?"}
    V -->|yes| F["validate() — raise on any<br/>missing · short · published · http:// value"]
    V -->|no| P["permissive, localhost URLs"]

    style C fill:#F59E0B,color:#fff
    style F fill:#EE0000,color:#fff
```

`load_dotenv(override=False)` is what makes the real environment beat `.env`,
and `DOTENV_DISABLE=1` skips `.env` entirely. Both matter in a container: a
`.env` accidentally baked into the image must never override what the
orchestrator injects.

---

## A.7 Inspection commands

```bash
# which database am I actually on?
python -c "from db import DATABASE_URL, IS_PG; print(IS_PG, DATABASE_URL)"

# name, user, version
psql "$DATABASE_URL" -c "SELECT current_database(), current_user, version()"

# every table with its row count
psql "$DATABASE_URL" -c "
SELECT relname AS table, n_live_tup AS rows
FROM pg_stat_user_tables ORDER BY relname"

# every column of one table
psql "$DATABASE_URL" -c "\d+ support_cases"

# every index
psql "$DATABASE_URL" -c "
SELECT tablename, indexname FROM pg_indexes
WHERE schemaname='public' ORDER BY tablename, indexname"

# table sizes on disk
psql "$DATABASE_URL" -c "
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_catalog.pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC"
```

```bash
# the SQLite fallback
sqlite3 capstone2.db ".tables"
sqlite3 capstone2.db ".schema support_cases"

# installed versions vs the pins
pip list --format=columns
pip check                      # dependency conflicts

# which config the app resolved to
python -c "
import config
print('env       ', config.APP_ENV)
print('customer  ', config.CUSTOMER_URL)
print('associates', config.ASSOCIATES_URL)
print('api       ', config.API_URL)
print('cors      ', config.cors_origins())"

# which state backend is live
python -c "import login_guard; print('lockout backend:', login_guard.backend())"
```

```bash
# container / cluster
podman-compose ps
podman exec -it capstone2_db_1 psql -U capstone -d capstone2
oc get pods,svc,route,cm,secret,pvc -l app.kubernetes.io/part-of=capstone2
```

---
---

---
---

# Appendix B — Complete Feature Inventory

> Every component, every feature, what it is for, and where it is explained in
> full. Chapters 7–11 describe the features; this appendix is the checklist —
> use it to confirm nothing is missing, or to find the chapter that covers the
> thing you are looking at.

---

## B.1 The ten components

| # | Component | File | Port | What it is |
|---|---|---|---|---|
| 1 | **Customer Intelligence Dashboard** | `app1.py` ~4,100 ln | 8501 | Account-facing — which customers are healthy, which need attention |
| 2 | **Associates Dashboard** | `app2.py` ~5,200 ln | 8502 | Engineer-facing — four tabs, My Desk default for every role |
| 3 | **My Desk** | `my_desk.py` ~3,000 ln | *(inside 8502)* | The operations workspace — the heart of the product |
| 4 | **REST API** | `api.py` | 8503 | 14 FastAPI endpoints, JWT-secured, `/docs` + `/openapi.json` |
| 5 | **Database layer** | `db.py` | — | PostgreSQL ⇄ SQLite abstraction — `IS_PG`, `PARAM`, pooled engine |
| 6 | **Configuration** | `config.py` | — | Single source of truth; fails fast in production |
| 7 | **Login guard** | `login_guard.py` | — | DB-backed lockout that survives restarts and spans replicas |
| 8 | **API middleware** | `middleware.py` | — | Anti-scraping, HMAC request signing, CORS |
| 9 | **Shared helpers** | `workspace_utils.py` | — | `_html()` sanitiser + shared render helpers |
| 10 | **Data loader** | `setup_database2.py` | — | Excel → database, derives the skills table, creates 18 indexes |

Full dependency graph and line counts: [Chapter 17](#chapter-17--file-by-file-map).

---

## B.2 Customer Intelligence Dashboard — `app1.py` :8501

| Feature | Use | Detail |
|---|---|---|
| **KPI strip** | Accounts · Avg CSAT · Avg TTR · Escalations, recomputed against the live filter set | [Ch 7](#kpi-strip) |
| **Six global filters** | Account, Sector, Products, Support Tier, Region, Revenue Segment — multi-select, AND-composed | [Ch 7](#global-filters) |
| **Saved filters** | Name a filter combination and re-apply it later | [Ch 7](#global-filters) |
| **Seven date presets** | All Time · Today · Yesterday · Last 7/30 Days · Last Quarter · Custom | [Ch 7](#global-filters) |
| **Operational graph** | Cases opened over time, driven by the date preset | [Ch 7](#feature-map) |
| **Account cards** | Health badge, open cases, CSAT, tier, contract state | [Ch 7](#account-cards) |
| **Six sort orders** | Defaults point at trouble — CSAT and Health sort worst-first | [Ch 7](#account-cards) |
| **Contract badge** | 🔴 Expired · 🟡 Expiring within 90 days · 🟢 Active | [Ch 7](#account-cards) |
| **Account detail** | Time chart, HQ location, company background, key details, top associates | [Ch 7](#account-detail-view) |
| **Four inner filters** | Severity · Status · Product · Case Owner, within one account | [Ch 7](#global-filters) |
| **AI business summary** | On demand only — never auto-fires, shows failures rather than fabricating | [Ch 7](#ai-business-summary) |
| **AI chatbot** | Account-level Q&A, scoped to the data on screen | [Ch 7](#ai-chatbot) |
| **Compare mode** | 2–5 accounts side by side | [Ch 7](#compare-mode) |
| **Four exports** | CSV + Excel | [B.7](#b7-every-export) |
| **Auth surface** | Login · Register · Forgot password | [Ch 6](#chapter-6--authentication--rbac) |

---

## B.3 Associates Dashboard — `app2.py` :8502

| Tab / feature | Access | Use | Detail |
|---|---|---|---|
| **My Desk** | all | Default tab for every role | [B.4](#b4-my-desk--my_deskpy) |
| **Associates View** | all | Cards by resolved/owned; cases owned, resolved, avg satisfaction, top 5 skills; shift insights + charts + AI summary | [Ch 8](#associates-view-all-roles) |
| **Team / SBR View** | manager · admin | Every associate and skill in a selected SBR + AI team-performance summary | [Ch 8](#team--sbr-view-manager--admin-only) |
| **Skills View** | all | Associates and skills by top skill, skill→product mapping, AI skills analysis | [Ch 8](#skills-view-all-roles) |
| **AI skill extraction** | `ai_extract` — manager · admin | Infers skills from case history; *Add All Inferred Skills to Profile* `INSERT`s into `skills` | [A.4](#a4-which-module-touches-which-table) |
| **Data Management** | **admin only** | CSV Upload · Manual Entry · Delete Case · Export Data | [Ch 8](#data-management-admin-only) |
| **Guided tour** | all | 21 steps / 25 screens, real elements, auto tab-switching, role-branching | [Ch 8](#the-guided-tour) |
| **Four exports** | all | CSV + Excel | [B.7](#b7-every-export) |

---

## B.4 My Desk — `my_desk.py`

### Above the tabs

| Feature | Use | Detail |
|---|---|---|
| **Global search** | One box across case number, account, associate, symptom text | [Ch 9](#above-the-tabs) |
| **My Cases / Team Queue** | Manager & admin only — *not rendered* for associates, not disabled | [Ch 9](#above-the-tabs) |
| **Editable SLA targets** | Per severity; every downstream number recomputes | [Ch 10.2](#102-sla-state--green--gold--red) |
| **Pressure strip** | open · critical · SLA-risk · escalated · waiting · aging | [Ch 9](#above-the-tabs) |
| **What changed since your last visit** | Diffed against a snapshot from your *previous* session | [Ch 9](#above-the-tabs) |
| **Shift handoff brief** | Five fixed headings; Granite when reachable, deterministic local brief when not; source always labelled | [Ch 9](#the-shift-handoff-brief) |

### The queue

| Feature | Use | Detail |
|---|---|---|
| **Recommended Next Action** | Named rule, so the advice is auditable | [Ch 10.12](#1012-summary--what-each-number-is) |
| **Priority score** | The queue order | [Ch 10.1](#101-case-priority-score--the-queue-order) |
| **Seven quick-filter chips** | Critical · SLA risk · Escalated · Aging · Waiting on customer · High tier · My products, with live counts, AND-combined | [Ch 9](#the-queue) |

### The case workspace

Customer context strip — tier, TAM, region, contract end with renewal warning,
case history, escalations, CSAT, a 🟢/🟡/🔴 risk pill, and a deep link to the
account in app1 — plus an action centre and five tabs.

| Tab | Use | Detail |
|---|---|---|
| **Timeline** | Only real timestamps; missing ones say *"not recorded in this dataset"* | [Ch 9](#timeline) |
| **Similar cases** | TF-IDF matches with similarity %, and how each may help | [Ch 10.6](#106-similar-cases--tf-idf-cosine) |
| **Potential SMEs** | Ranked by documented experience; **"shift on record"**, never "available" | [Ch 10.7](#107-potential-smes--the-ranking-and-what-it-is-not) |
| **Escalation readiness** | 11-point checklist; unsupported checks marked *unavailable* | [Ch 10.10](#1010-escalation-readiness--the-11-point-checklist) |
| **Private notes** | Per user, `desk_user_state`, backend labelled | [Ch 9](#private-notes) |

**Action centre** — `⭐ Follow up` and `📝 Add note` enabled; `Update status`,
`Reassign`, `Escalate` disabled **with the reason shown**.

### Analysis tabs

| Tab | Use | Detail |
|---|---|---|
| **My Follow-ups** | Starred cases with note and next action; resolvable after they leave your scope | [Ch 9](#the-analysis-tabs) |
| **SLA & Aging** | Age histogram by SLA state, breach rate per severity, target vs. historical median, worst offenders | [Ch 10.2](#102-sla-state--green--gold--red) |
| **Escalation Risk** | Every open case scored, top two drivers in plain English, model's own held-out AUC | [Ch 10.5](#105-escalation-risk--the-scored-model) |
| **Similar & Patterns** | Free-text TF-IDF over closed cases + observed historical patterns | [Ch 10.9](#109-observed-historical-patterns) |
| **Trends & Anomalies** | Poisson z-score on product/version arrival rates | [Ch 10.8](#108-anomaly-detection--poisson-z-score) |
| **My Performance** | Personal CSAT drill-down and skill gap vs. SBR peers | [Ch 9](#the-analysis-tabs) |
| **Team Workload** | Per-engineer load and SBR backlog. **Deliberately not a ranking** | [Ch 9](#the-analysis-tabs) |
| **System** *(admin)* | Data-as-of, extract age, DB engine, state backend, record counts, and the missing-field list with what each absence costs | [Ch 9](#the-analysis-tabs) |

**Accessibility** — all motion is CSS-only and fully disabled under
`prefers-reduced-motion`.

---

## B.5 The calculation engine — 12 models

Every formula, constant and worked example is in
[Chapter 10](#chapter-10--every-calculation-explained). Nothing here is a
library call; all of it is pure Python over the dataset.

| § | Model | Method |
|---|---|---|
| 10.1 | **Case Priority Score** | Weighted severity × tier × age × staleness × escalation |
| 10.2 | **SLA State** | elapsed ÷ per-severity target → 🟢 / 🟡 / 🔴 |
| 10.3 | **Account Health Score** | Composite of CSAT, speed, escalation rate, volume |
| 10.4 | **Account Risk Pill** | Banded risk indicator on the case workspace |
| 10.5 | **Escalation Risk** | Smoothed naive Bayes in log-odds space — reports its own held-out AUC |
| 10.6 | **Similar Cases** | Hand-rolled TF-IDF + cosine similarity |
| 10.7 | **Potential SMEs** | Weighted experience ranking (product version weight 3.0) |
| 10.8 | **Anomaly Detection** | Poisson z-score on arrival rates |
| 10.9 | **Observed Historical Patterns** | Frequency mining — labelled observation, never prediction |
| 10.10 | **Escalation Readiness** | 11-point checklist over structured fields and description text |
| 10.11 | **Age Buckets** | Measured against the reference clock, not wall-clock |
| 10.12 | **Next Action ladder** | Ordered rule set; the firing rule is always named |

---

## B.6 The REST API surface

14 endpoints — full table, curl examples and the two gotchas in
[Chapter 11](#chapter-11--the-rest-api).

Guarded by: JWT Bearer · `typ`-claim scoping (a dashboard token is rejected
with an explanatory message) · scraper user-agent blocking · HMAC-SHA256
request signing · a CORS allow-list derived from the public URLs, never a
wildcard.

---

## B.7 Every export

**17 download buttons.** Everything on screen can leave the app as a file —
there is no "screenshot the dashboard" step anywhere in the product.

| Where | Button | File |
|---|---|---|
| app1 · Accounts | Download CSV | `accounts_export.csv` |
| app1 · Accounts | Download Excel | `accounts_export.xlsx` |
| app1 · Account detail | Download Cases CSV | `{account_id}_cases.csv` |
| app1 · Bulk select | Export CSV | `bulk_accounts.csv` |
| app2 · Associates | Download CSV | `associates_export.csv` |
| app2 · Associates | Download Excel | `associates_export.xlsx` |
| app2 · Associate detail | Download Cases CSV | `{associate_id}_cases.csv` |
| app2 · Bulk select | Export CSV | `bulk_associates.csv` |
| My Desk · queue | Export current queue (CSV) | `my_desk_queue.csv` |
| My Desk · handoff | Copy as text | `shift_handoff.txt` |
| My Desk · case | Export case summary | `case_{n}_summary.txt` |
| My Desk · case | Download brief | `case_{n}_brief.txt` |
| My Desk · case | *(account cases)* | `account_{id}_cases.csv` |
| My Desk · Similar | Export similar cases (CSV) | `case_{n}_similar.csv` — includes the similarity score |
| My Desk · Team Workload | Export team workload (CSV) | `team_workload.csv` |
| My Desk · Patterns | Export patterns (CSV) | `recurring_patterns.csv` |
| My Desk · Escalation Risk | Export risk-scored queue (CSV) | `escalation_risk.csv` |

Excel export goes through `openpyxl`. **`reportlab` is declared in
`requirements.txt` but nothing imports it** — a PDF export that was never
built; see [A.5](#a5-tools-and-runtime).

---

## B.8 The extras — what was built beyond a working dashboard

None of these were needed to "show charts". Each row is what the extra buys.

| Extra | Why it exists |
|---|---|
| **My Desk itself** | The pivot from retrospective analytics to daily case work. Everything else is reporting; this is what an engineer opens at shift start |
| **Shift handoff brief + local fallback** | The one AI feature that still works when the endpoint is down — deterministic text composed from the same facts |
| **What changed since your last visit** | Gives the dashboard a memory, so a returning user sees the delta rather than re-reading the whole queue |
| **Editable SLA targets** | Makes every downstream number *yours* rather than a hardcoded assumption |
| **The honesty layer** | Missing fields named; "shift on record" not "available"; "observed pattern" not "prediction"; disabled buttons carry their reason; AI output always labelled. **This is a feature** — it is what makes the numbers trustable |
| **Guided tour, 21 steps, role-branching** | Onboarding with no training session; spotlights real elements, not screenshots |
| **Cross-app JWT handoff** | One login across :8501 and :8502 |
| **DB-backed login lockout** | Replaced a module-level dict: a restart used to clear it, and two replicas gave an attacker 10 attempts instead of 5 |
| **`config.py` fail-fast validation** | `APP_ENV=production` refuses to boot on a placeholder secret, a short key, or an `http://` URL |
| **Anti-scraping + HMAC signing** | A Bearer token alone is not enough for a public-facing API |
| **`_html()` sanitiser** | Fixes the CommonMark type-6 block bug that leaked raw HTML into rendered pages |
| **CSS-only motion + `prefers-reduced-motion`** | Accessibility with zero JavaScript |
| **185 tests**, incl. `test_html_render.py` (AppTest) and `test_hosting.py` (real subprocess) | Regression protection on the UI *and* on the deployment path |
| **Production hosting stack** | Compose overlay, Caddy auto-TLS with hardening headers, 5 OpenShift manifests with sticky-session Routes — and deliberately no committed Secret |
| **This handbook** | 18 chapters + two appendices, 17 diagrams, generated to styled HTML by `docs/build_handbook.py` with no new dependency |

---
---

---

<div align="center">

### End of handbook

**Red Hat CEE BI Capstone #2** · Associates Analytics Platform
185 tests · 18 chapters · every number explained

*If something in here is wrong, the code is right and this file is out of
date — fix the file.*

</div>
