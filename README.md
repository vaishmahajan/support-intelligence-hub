# Capstone #2 — Customer Intelligence & Associates Dashboard

A containerized analytics platform with two Streamlit dashboards, a FastAPI REST API, and PostgreSQL persistence. Built for the Red Hat Interns Capstone program.

> 📕 **New here? Read [`docs/PROJECT_HANDBOOK.md`](docs/PROJECT_HANDBOOK.md)** — the
> complete 18-chapter handbook: architecture, every feature, every calculation
> with worked examples, deployment (Podman · Docker · OpenShift), and how to
> move to live data. This README is the quick reference; the handbook is the
> full story.
>
> Styled and browsable, with the diagrams rendered:
> **<https://vaishmahajan.github.io/support-intelligence-hub/>**
> (or build it yourself with `python docs/build_handbook.py --open`).
>
> 📦 **No data ships with this repository.** Start with the synthetic
> [`demo_data/`](demo_data/), or bring your own to the schema in
> [`docs/DATA_FORMAT.md`](docs/DATA_FORMAT.md). See
> [Data Sources](#data-sources).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│               Container Compose Network                     │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Customer     │  │  Associates  │  │  FastAPI REST    │  │
│  │  Dashboard    │  │  Dashboard   │  │  API             │  │
│  │  (Streamlit)  │  │  (Streamlit) │  │  (uvicorn)       │  │
│  │  Port 8501    │  │  Port 8502   │  │  Port 8503       │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────────┘  │
│         │                 │                  │              │
│         └─────────────────┼──────────────────┘              │
│                           │                                 │
│                  ┌────────▼────────┐                        │
│                  │  PostgreSQL 16  │                        │
│                  │  Port 5433      │                        │
│                  └─────────────────┘                        │
└─────────────────────────────────────────────────────────────┘
```

| Component | Port | Description |
|---|---|---|
| **Customer Intelligence Dashboard** (`app1.py`) | 8501 | Account health, case trends, escalation tracking, AI insights |
| **Associates Dashboard** (`app2.py`) | 8502 | Associate performance, skills matrix, SBR/team analytics |
| **REST API** (`api.py`) | 8503 | JWT-secured endpoints for accounts, cases, associates, skills, teams |
| **PostgreSQL 16** | 5433 | Accounts, support cases, associates, skills, registered users |

---

## Getting Started

### Prerequisites

- Python 3.10+
- pip

### Local Setup (Without Docker)

```bash
# 1. Clone the repository
git clone <repo-url>
cd Capstone2

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create environment file
cp .env.sample .env
# Edit .env — fill in your AI_ENDPOINT_URL, AI_MODEL_ID, and AI_API_TOKEN
# All other values (JWT secret, admin password, DB config) are pre-filled and ready to use

# 4. Provide source data — none ships with this repo (see "Data Sources" below)
mkdir -p data
cp demo_data/accounts.csv demo_data/support_cases.xlsx \
   demo_data/associates.xlsx demo_data/company_backgrounds.json data/

# 5. Build the database from those files
python setup_database2.py
# Reads CSV/Excel from data/ and creates capstone2.db (SQLite)
# Without this step, the app will not start

# 6. Run the dashboards (each in a separate terminal)
streamlit run app1.py --server.port 8501    # Customer Dashboard
streamlit run app2.py --server.port 8502    # Associates Dashboard
uvicorn api:app --port 8503                 # REST API (optional)
```

Open in your browser:
- Customer Dashboard: http://localhost:8501
- Associates Dashboard: http://localhost:8502
- API Docs: http://localhost:8503/docs

### Containerized Setup (Docker / Podman)

```bash
# 1. Clone and configure
git clone <repo-url>
cd Capstone2
cp .env.sample .env
# Edit .env — fill in AI_ENDPOINT_URL, AI_MODEL_ID, AI_API_TOKEN

# 2. Provide source data — the container seeds from data/, which ships empty
mkdir -p data
cp demo_data/accounts.csv demo_data/support_cases.xlsx \
   demo_data/associates.xlsx demo_data/company_backgrounds.json data/

# 3. Build and start all services
docker compose up --build        # Docker
podman-compose up --build        # Podman (Fedora/RHEL)
```

This automatically starts PostgreSQL, seeds the database from `data/`, and launches all three services.

To stop: `docker compose down` or `podman-compose down`

---

## Hosting

The local setup above is tuned for a laptop. Three of its defaults are actively
unsafe on a server — the source directory is bind-mounted into every container,
uvicorn runs with `--reload`, and Postgres is published on a host port — so
hosting uses an overlay rather than the base file alone.

### 1. Generate real secrets

```bash
python -c "import secrets;print(secrets.token_urlsafe(48))"   # once per secret
```

Replace `JWT_SECRET_KEY`, `FRONTEND_TOKEN_SECRET`, `POSTGRES_PASSWORD` and the
three role passwords in `.env`. The values shipped in `.env.sample` are
published in this repository, which makes them public — anyone holding the
default `JWT_SECRET_KEY` can mint an admin token.

### 2. Set `APP_ENV=production`

`config.py` then validates the whole configuration at import and refuses to
start if anything is unsafe, listing every problem at once:

```
RuntimeError: Refusing to start: APP_ENV=production but the configuration is
not production-safe.

  - JWT_SECRET_KEY is set to a value published in this repository. It is public — choose a new one.
  - ADMIN_PASSWORD is 9 characters; at least 12 are required in production.
  - PUBLIC_CUSTOMER_URL uses plain http://. Session tokens would travel unencrypted.
```

A container that dies on boot with that message is doing its job. It beats one
that starts happily and signs tokens with a key from a public README.

### 3. Point the public URLs at real hostnames

```bash
PUBLIC_CUSTOMER_URL=https://cust.example.com
PUBLIC_ASSOCIATES_URL=https://assoc.example.com
PUBLIC_API_URL=https://api.example.com
```

Cross-app links and the API's CORS allow-list are both built from these, so
they stay in step instead of drifting apart. Leaving them unset in production
is fatal rather than silent — otherwise every cross-app link would point at the
viewer's own `localhost`.

### 4. Set the proxy domains and bring it up

```bash
CUSTOMER_DOMAIN=cust.example.com
ASSOCIATES_DOMAIN=assoc.example.com
API_DOMAIN=api.example.com
ACME_EMAIL=you@example.com
```

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Caddy obtains and renews Let's Encrypt certificates automatically. It is the
only service with a published port; the dashboards, the API and Postgres are
all private to the compose network.

> ☸️ **On OpenShift, skip Caddy** — a `Route` with edge termination does the
> same job. Manifests are in [`docs/openshift/`](docs/openshift/); the full
> walkthrough is handbook §13.4.

### What the overlay changes

| | Local | Hosted |
|---|---|---|
| Source | Bind-mounted (`.:/app`) | Baked into the image |
| API | `uvicorn --reload` | `uvicorn --workers 4` |
| Postgres | Published on 5433 | Private to the network |
| Dashboards | Published on 8501/8502 | Private; reached via Caddy |
| TLS | None | Caddy + automatic Let's Encrypt |
| Health checks | Postgres only | Every service |
| Logs | Unbounded | Rotated at 10 MB × 5 |

### Session and token handling

- **Cross-app links carry a 60-second handoff token**, not the 60-minute
  session JWT. Copy the link to a colleague and it is already dead. The
  receiving app trades it for a full session on arrival.
- **The REST API rejects dashboard tokens.** All three token kinds are signed
  with the same key, so `typ` distinguishes them: a `session` or `handoff`
  token picked out of a URL gets a 401 from the API.
- **`Referrer-Policy: no-referrer`** is set by the proxy, so the session token
  in the query string is not handed to third-party sites in outbound links.

### Known limitations

Three things are genuinely not solved, and it is better to name them than to
imply otherwise:

1. **The session token lives in the URL.** That is how login survives a page
   refresh — Streamlit cannot set cookies natively. The measures above shrink
   the blast radius but do not remove it: the token still reaches browser
   history and any proxy that logs full URLs. A cookie-based session, via a
   small custom component or an authenticating reverse proxy, is the real fix.
2. **The data is a static extract with no refresh path.** `setup_database2.py`
   loads CSV/Excel files once. The synthetic generator never closed its open
   cases, so their median age is around 375 days and the dashboard shows a
   100% SLA breach rate — that is an artefact of the fixture, not a finding.
   Before real support engineers use this, it needs a live feed from the actual
   case system. No amount of application hardening substitutes for that.
3. **The production config gate cannot see the seeded dashboard passwords.**
   `config.py` refuses to start if `ADMIN_PASSWORD` or the API passwords are
   left at a published value, but the manager and associate passwords are
   bcrypt hashes in `registered_users` by the time the app reads anything —
   there is no plaintext left to compare against the published list. Set
   `SEED_MANAGER_PASSWORD` and `SEED_ASSOCIATE_PASSWORD` before the database
   build; nothing will remind you.

---

## Apple Silicon & Cross-Platform Support

All container images (`python:3.11-slim`, `postgres:16-alpine`) are multi-architecture and run natively on both Intel and Apple Silicon (M1/M2/M3/M4). No extra configuration needed.

| Platform | Compose Tool |
|---|---|
| macOS (Apple Silicon M1–M4) | `docker compose` |
| macOS (Intel) | `docker compose` |
| Fedora / RHEL | `podman-compose` |
| Ubuntu / Debian | `docker compose` |
| Windows | `docker compose` |

---

## Environment Configuration

Copy `.env.sample` to `.env` and fill in the AI values. Everything else is pre-configured:

| Variable | What to do | Default |
|---|---|---|
| `AI_ENDPOINT_URL` | Pre-configured | `granite-3-1-8b-instruct` endpoint |
| `AI_MODEL_ID` | Pre-configured | `ibm-granite/granite-3.1-8b-instruct` |
| `AI_API_TOKEN` | **Fill in** — your API token | placeholder |
| `POSTGRES_USER` | Ready to use | `capstone` |
| `POSTGRES_PASSWORD` | Ready to use | `change_me_in_production` |
| `POSTGRES_DB` | Ready to use | `capstone2` |
| `POSTGRES_PORT` | Ready to use | `5433` |
| `JWT_SECRET_KEY` | Ready to use | `capstone2-jwt-secret-change-in-prod` |
| `ADMIN_PASSWORD` | Ready to use | `admin2026` |
| `FRONTEND_TOKEN_SECRET` | Ready to use | pre-configured |

> **Note:** `.env` is gitignored and will not be pushed. Only `.env.sample` is in the repository.

---

## Login Credentials

### Pre-configured Test Accounts

These accounts are auto-created by `setup_database2.py` — ready to use immediately after setup. The manager and associate identities come from the demo dataset; if you supply `data/seed_users.json`, yours are used instead.

| Role | Email | Password | Set with |
|---|---|---|---|
| **Admin** | `admin@redhat.com` | `admin2026` | `ADMIN_PASSWORD` |
| **Manager** | `adaeze.nwachukwu@redhat.com` | `manager123` | `SEED_MANAGER_PASSWORD` |
| **Associate** | `theo.krishnan@redhat.com` | `associate123` | `SEED_ASSOCIATE_PASSWORD` |

> **These defaults are published, so they are public.** Set all three
> environment variables **before** running `setup_database2.py` for anything
> another person can reach — the manager and associate passwords are hashed
> into the database at seed time, so changing them afterwards means reseeding
> or updating the hash by hand.
>
> `APP_ENV=production` blocks a published `ADMIN_PASSWORD` at startup, but it
> cannot check `SEED_MANAGER_PASSWORD` / `SEED_ASSOCIATE_PASSWORD` — by then
> they are bcrypt hashes in a table, not values it can compare. Those two are
> on you.

### Registering New Users

- Select the **Sign Up** tab on the login page
- Only `@redhat.com` emails that exist in the source data can register
- A manager cannot register as an associate and vice versa
- Admin role has no registration — only the hardcoded admin account

---

## Data Sources

> **No source data ships with this repository. You supply your own.**
>
> This platform was built against Red Hat customer and employee records —
> account names, revenues, contract dates, engineer names and emails, and
> free-text case descriptions. None of that belongs in a public repository, so
> `data/` is gitignored and has never been committed. What you clone is the
> application.

You need three files in `data/`. Two more are optional.

| File | Required | Description |
|---|---|---|
| `data/accounts.csv` | ✅ | Customer accounts |
| `data/support_cases.xlsx` | ✅ | Support cases |
| `data/associates.xlsx` | ✅ | Support engineers |
| `data/company_backgrounds.json` | ⬜ | HQ city + one-line blurb per account |
| `data/seed_users.json` | ⬜ | Which two identities get a pre-created login |

### Option A — use the demo dataset (recommended first run)

A complete synthetic dataset is committed in **[`demo_data/`](demo_data/)**:
30 accounts, 25 engineers under 5 managers, 250 cases. Every company and
person in it is invented; the category vocabularies are real because the
application keys off those exact strings.

```bash
mkdir -p data
cp demo_data/accounts.csv demo_data/support_cases.xlsx \
   demo_data/associates.xlsx demo_data/company_backgrounds.json data/
python setup_database2.py --from-source
```

Regenerate it at any size with `python tools/make_demo_data.py` — the seed is
fixed, so the output is byte-identical every time.

### Option B — bring your own data

Build the three files to the schema in **[`docs/DATA_FORMAT.md`](docs/DATA_FORMAT.md)**
(also rendered as [`docs/DATA_FORMAT.html`](docs/DATA_FORMAT.html)). It gives
every column with its type and nullability, the controlled vocabularies that
must match exactly, how the files join, a copy-paste validation script, and a
troubleshooting table.

Then drop them in `data/` and run the same command:

```bash
python setup_database2.py --from-source
```

Two things worth knowing before you start:

- **Severity, status and support tier are controlled vocabularies.** Scoring
  weights and SLA targets are dictionaries keyed by those exact strings. A
  value outside the set does not raise an error — it silently scores zero and
  renders grey, which is harder to notice.
- **Cases join to engineers by *name*, not by ID.** A trailing space in
  `case_owner` orphans a case from every team view with no warning. Run the
  validator in `DATA_FORMAT.md` before your first load.

### Adding data later, through the app

Admins get a **Data Management** panel in the Associates dashboard: CSV
upload, manual single-case entry, delete, and export. The CSV importer needs
six columns — `case_number, account_name, severity, status, product_name,
case_owner` — and it reports missing columns, incomplete rows and duplicate
case numbers before writing anything. Managers and associates do not have this
panel.

### What the loader derives

Supply the raw fields; `setup_database2.py` computes the rest:

- `revenue_segment`, bucketed from `annual_revenue`
- `time_to_resolve_hours`, from `resolution_date − creation_date`
- `hq_location` and `company_background`, joined from the optional JSON map
- the entire `skills` table — top 5 skills per engineer, mined from their case
  history, SBR and certifications

---

## Customer Intelligence Dashboard (Port 8501)

- **KPI Indicators**: Total Accounts, Avg CSAT, Avg Time to Resolve, Total Escalations
- **Global Filters**: Account ID/Name, Sector, Products, Support Tier, Region, Revenue Segment
- **Operational Graph**: Cases opened over time with date range filters
- **Account Cards**: Sorted by case volume/escalation with health scores
- **Account Detail View**: Time-based chart, HQ location, company background, key details
- **AI Business Summary**: On-demand insights per account via "Generate Insights" button
- **AI Chatbot**: Interactive floating chat for account-level Q&A
- **Associate Analysis**: Top associates per account based on case data
- **Compare Mode**: Bulk select up to 5 accounts for side-by-side comparison

---

## Associates Dashboard (Port 8502)

- **Filters**: Geo/Shift, Manager, SBR, Accounts, Product, Severity, Skills, Certification
- **3-Role RBAC**: Admin (full access), Manager (team views), Associate (personal dashboard)
- **Data Upload**: Upload new CSV data that auto-updates statistics

### My Desk (All Roles) — `my_desk.py`

A support operations workspace, not another BI tab. It answers *what do I work on
right now*, then *why does it matter*, *have we seen this before*, *who can help*,
*should I escalate*, *what do I do next*. Everything else in the dashboard is
retrospective; this tab is not. It is the default tab for all three roles.

Above the tabs: a **global search bar** (case number, account, associate, or symptom
text), a **My Cases / Team Queue** selector for managers and admins, editable **SLA
targets**, a six-count **pressure strip**, and a **What changed** panel diffed
against a snapshot recorded on your previous visit.

#### The queue

- **Recommended Next Action** — every case card names one action and the rule that
  produced it: escalated → review the escalation history; waiting on customer →
  send a follow-up; past target → update the customer; stale → log a customer-facing
  update; repeated product issue → review resolved cases; specialised product → ask
  a matching engineer. These are deterministic rules over fields in the case row —
  not a prediction, not a model — so the recommendation can be argued with.
- **Priority score** — 0–100 from severity, SLA pressure, time since last update,
  support tier and the escalation flag. SLA pressure and staleness are log-scaled so
  a queue of badly aged cases still spreads across the range instead of pinning at
  the ceiling. Cases waiting on the customer are damped, never hidden.
- **Quick filters** — Critical, SLA risk, Escalated, Aging, Waiting on customer,
  High tier, My products. Counts on the chips, chips combine with AND.
- **Shift handoff brief** — one button writes the over-to-you note under fixed
  headings: Critical / SLA risk / Waiting on customer / Escalations / Recommended
  follow-ups. Uses the Granite endpoint when reachable, and a deterministic local
  brief composed from the same facts when it is not. AI output is HTML-sanitised
  before rendering, and the source is labelled either way.

#### The case workspace

Open any case for a customer context strip (tier, TAM, region, contract end with
renewal warning, case history, escalations, CSAT, a 🟢/🟡/🔴 risk pill, and a link
through to this account in the Customer Intelligence dashboard — it carries your
JWT and the account id, so the hop lands on the account rather than a login page),
an **action center**, and five tabs:

- **Timeline** — Created → Last update → Waiting → Resolved, built only from
  timestamps the dataset actually holds. First response and escalation time are
  shown as *not recorded in this dataset* rather than invented.
- **Similar cases** — TF-IDF matches with similarity %, product, severity, resolve
  time, escalated, CSAT, owner, SBR and shift, plus how each may help.
- **Potential SMEs** — ranked by same version, same product, similar closed cases,
  same SBR and matching skills, each row explaining its own score. The column is
  *shift on record*, never "available" — the dataset holds no rota.
- **Escalation readiness** — an 11-point checklist scored from structured fields and
  from what the case description actually contains. Checks the data cannot support
  (reproduction steps, diagnostic bundles, customer-confirmed severity) are listed
  as unavailable rather than silently passed.
- **Private notes** — session or DB-backed per user, labelled with which one is in
  force.

Plus an **AI case brief** with the same local fallback. Actions that would need
write access to the case system (update status, reassign, escalate, request
information) are rendered **disabled with the reason stated** — the analytics
database is read-only for case data, and a green button that does nothing is worse
than no button. Notes, follow-ups and snapshots persist to an additive
`desk_user_state` table created on demand, degrading to session-only if the
database declines.

#### The other tabs

- **My Follow-ups** — cases you starred, with their note and next action, resolvable
  even after they leave your personal scope.
- **SLA & Aging** — age-bucket histogram split by SLA state, breach rate per severity,
  configured target vs. historical median resolve time, worst-offenders table.
- **Escalation Risk** — smoothed naive-Bayes over severity, product, SBR, account and
  business-hours flag, scoring every open case with the top two drivers named in
  plain English. Reports its own held-out AUC (0.914) and top-decile capture so the
  number can be trusted or ignored on evidence.
- **Similar & Patterns** — free-text TF-IDF search over every closed case, plus
  **observed historical patterns**: problem statements that repeat on the same
  product, with how many accounts they hit, median fix time and escalation rate.
  Counted from closed history — labelled as history, not prediction.
- **Trends & Anomalies** — Poisson z-score detection flags product/version
  combinations arriving faster than their own baseline.
- **My Performance** — personal CSAT drill-down and a skill gap view against your
  SBR peers, ranked by how many of them hold each skill.
- **Team Workload** (manager/admin) — open, critical, SLA-risk, escalated, waiting
  and oldest case per engineer, plus SBR backlog. Deliberately not a ranking: there
  is no "best engineer" column, because case counts do not mean the same thing
  across severities and products.
- **System** (admin) — data-as-of date, extract age, database engine, state-store
  backend, record counts, timestamp coverage, and an explicit list of the fields
  this dashboard does not have and what each absence costs.

Scope follows RBAC: an associate sees their own cases and the Team Queue control is
**not rendered at all**; a manager can switch to their team and drill into one
engineer; an admin can pick anyone.

Ages run on the newest timestamp in the dataset rather than wall-clock time, so a
stale extract doesn't age every open case into a false breach. The tab states its
data-as-of date and never presents the static extract as a live feed.

Motion is CSS-only (card fade-in, SLA bar fill, timeline draw) and fully disabled
under `prefers-reduced-motion`.

### Associate View (All Roles)
- Cards with associates sorted by resolved/owned tickets
- Per-associate: cases owned, resolved, avg satisfaction, top 5 skills
- Shift insights with charts and AI summary

### Team/SBR View (Manager & Admin Only)
- All associates and skills for a selected SBR team
- AI-powered team performance summary

### Skills View (All Roles)
- Associates and skills sorted by top skills
- Skill summary with associated product
- AI-powered skills analysis

---

## REST API (Port 8503)

All `/api/v1/*` endpoints require JWT Bearer token. Anti-scraping middleware blocks direct curl/wget access.

### Quick Test
```bash
# Login and get token
curl -X POST http://localhost:8503/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin2026"}'
```

### Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/login` | Get JWT token |
| GET | `/auth/me` | Current user info |
| GET | `/api/v1/accounts` | List accounts (filter: sector, region) |
| GET | `/api/v1/associates` | List associates (filter: sbr, shift, manager) |
| GET | `/api/v1/associates/{id}` | Associate detail with cases and skills |
| GET | `/api/v1/cases` | List cases (filter: severity, status, product) |
| GET | `/api/v1/skills` | List skills (filter: skill_name, min_rank) |
| GET | `/api/v1/skills/prevalence` | Skill prevalence stats |
| GET | `/api/v1/teams` | SBR teams with member counts |
| GET | `/api/v1/teams/{sbr}` | Team detail with performance stats |
| GET | `/api/v1/stats/overview` | Dashboard KPIs |
| GET | `/api/v1/stats/by-shift` | Stats by shift/geo |
| GET | `/api/v1/stats/by-severity` | Stats by case severity |
| GET | `/health` | Health check (public) |

API docs: http://localhost:8503/docs

---

## Security

| Feature | Implementation |
|---|---|
| **Authentication** | JWT Bearer tokens (HS256) via `python-jose` |
| **Password Hashing** | bcrypt via `passlib` |
| **Token Expiry** | 60 minutes (configurable) |
| **RBAC** | 3 roles — Admin, Manager, Associate with granular access |
| **Rate Limiting** | 5 failed login attempts = 5 minute lockout |
| **Anti-Scraping** | HMAC-SHA256 signed frontend tokens, User-Agent validation |
| **CORS** | Restricted to localhost dashboard ports only |
| **Role Isolation** | Cross-role registration blocked at data level |
| **Secret Validation** | `APP_ENV=production` refuses to start on a missing, short, or repo-published secret |
| **Token Scoping** | Dashboard (`typ=session`) and handoff (`typ=handoff`) tokens are rejected by the REST API |
| **Cross-App Links** | Carry a 60-second handoff token, not the 60-minute session JWT |
| **Lockout Durability** | Failed attempts stored in PostgreSQL — survives restart, shared across replicas |
| **TLS** | Caddy reverse proxy with automatic Let's Encrypt certificates and HSTS |

---

## Testing

```bash
# Install test deps
pip install pytest httpx

# Run all 185 tests
pytest tests/ -v
```

| File | Tests | What it checks |
|---|---|---|
| `test_data.py` | 25 | Table existence, columns, unique IDs, CSAT range, FK integrity |
| `test_api.py` | 23 | Endpoints, filtering, pagination, auth enforcement, 404s |
| `test_auth.py` | 9 | JWT structure, expiry, invalid tokens, RBAC per role |
| `test_my_desk.py` | 67 | Priority score, SLA & aging, next-best-action rules, similarity search, SME ranking, escalation readiness, recurring patterns, timeline honesty, risk-model bounds, local brief sections, RBAC visibility, empty-queue and small-queue edge cases |
| `test_hosting.py` | 27 | Production config refuses weak/missing/published secrets, CORS follows the public URLs, cross-app links carry a 60s token not a session, API rejects dashboard tokens, lockout is shared across processes |
| `test_html_render.py` | 34 | HTML never leaks to the page as literal text — every multi-line template in `app1.py`, `app2.py` and `my_desk.py` collapsed, no HTML sent to text-only writers, no block closed early at render time on either dashboard, no active content survives sanitising |

---

## Project Structure

```
Capstone2/
├── app1.py                  # Customer Intelligence Dashboard (Streamlit)
├── app2.py                  # Associates Dashboard (Streamlit)
├── api.py                   # FastAPI REST API with JWT auth
├── config.py                # Central config — fails fast on unsafe production settings
├── login_guard.py           # DB-backed login lockout (shared across replicas)
├── db.py                    # Database helpers (PostgreSQL + SQLite fallback)
├── middleware.py             # Anti-scraping middleware
├── setup_database2.py       # Database setup — reads data/ and builds DB
├── my_desk.py               # My Desk — support operations workspace (queue, next action,
│                            #   case workspace, SME engine, patterns, handoff brief)
├── workspace_switcher.py    # Header workspace switcher component
├── workspace_selector.py    # Full-page workspace chooser
├── workspace_utils.py       # Shared workspace utilities (cross-app URLs, _html)
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container image
├── docker-compose.yml       # 5-service orchestration (local development)
├── docker-compose.prod.yml  # Production overlay — TLS proxy, health checks, no bind mounts
├── Caddyfile                # TLS termination and security headers
├── start.sh                 # Startup script
├── .env.sample              # Environment template (copy to .env)
├── .gitignore
├── data/                    # GITIGNORED — you supply this; nothing ships here
├── demo_data/               # Synthetic stand-in, safe to publish
│   ├── README.md            # What it is and what it cannot demonstrate
│   ├── accounts.csv         # 30 fictional accounts
│   ├── support_cases.xlsx   # 250 fictional cases
│   ├── associates.xlsx      # 25 fictional engineers under 5 managers
│   ├── company_backgrounds.json
│   └── seed_users.json      # Identities only — never passwords
├── tools/
│   └── make_demo_data.py    # Deterministic generator for demo_data/
├── db/init/
│   └── 01_schema.sql        # PostgreSQL schema
├── docs/
│   ├── PROJECT_HANDBOOK.md  # The complete 18-chapter handbook — start here
│   ├── DATA_FORMAT.md       # Source-file schemas, vocabularies, validation
│   ├── build_handbook.py    # Renders both docs as styled HTML with diagrams
│   └── openshift/           # ConfigMap, Postgres StatefulSet, Deployments, Routes
├── tests/
│   ├── conftest.py          # Shared test fixtures
│   ├── test_api.py          # API tests (26)
│   ├── test_auth.py         # Auth tests (8)
│   ├── test_data.py         # Data integrity tests (23)
│   ├── test_my_desk.py      # My Desk logic + render tests (67)
│   ├── test_hosting.py      # Production config + auth hardening guards (27)
│   └── test_html_render.py  # HTML-leak regression guards (34)
└── .streamlit/
    └── config.toml          # Streamlit theme config
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Streamlit, Plotly, Custom CSS (glassmorphism) |
| Backend | FastAPI, uvicorn |
| Database | PostgreSQL 16 (primary), SQLite (local fallback) |
| ORM | SQLAlchemy, psycopg2, pandas |
| Auth | JWT (python-jose, HS256), bcrypt (passlib) |
| AI/LLM | IBM Granite via OpenAI-compatible API |
| DevOps | Docker / Podman Compose |
| Testing | pytest, httpx, FastAPI TestClient |
