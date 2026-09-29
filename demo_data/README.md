# `demo_data/` — the synthetic dataset

Everything in this directory is **invented**. No company, person, email
address, case or number here corresponds to anything real. It exists so that a
fresh clone of this repository can be run end to end without access to the
customer data the platform was actually built against — that data is not in
this repository and never will be.

```bash
mkdir -p data && cp demo_data/accounts.csv demo_data/support_cases.xlsx \
    demo_data/associates.xlsx demo_data/company_backgrounds.json data/
python setup_database2.py --from-source
streamlit run app1.py
```

## What is here

| File | Rows | Contents |
|---|---|---|
| `accounts.csv` | 30 | Fictional customer accounts across 14 sectors and 4 regions |
| `associates.xlsx` | 25 | Fictional support engineers, reporting to 5 managers |
| `support_cases.xlsx` | 250 | Fictional cases, spread over ~18 months |
| `company_backgrounds.json` | 30 | HQ city and a one-line blurb per account |
| `seed_users.json` | 2 | The two identities given a pre-created login |

## Demo logins

| Role | Email | Password |
|---|---|---|
| Admin | `admin@redhat.com` | `ADMIN_PASSWORD`, default `admin2026` |
| Manager | `adaeze.nwachukwu@redhat.com` | `SEED_MANAGER_PASSWORD`, default `manager123` |
| Associate | `theo.krishnan@redhat.com` | `SEED_ASSOCIATE_PASSWORD`, default `associate123` |

No password is stored in any file here. They come from those environment
variables at load time, and the defaults are published — set real ones before
putting this anywhere another person can reach it.

Adaeze Nwachukwu deliberately has **no row** in `associates.xlsx`. Managers are
referenced through `manager_name` / `manager_email` only; an address appearing
in both that column and `email` is treated as a role conflict and cannot
register. The real dataset has the same shape.

## What is real about it

The *values* are invented. The *vocabularies* are not — severities, statuses,
support tiers, regions, shifts, SBR teams and Red Hat product names are the
exact strings the application keys off. Scoring weights, colour maps and SLA
targets are dictionaries looked up by those strings, so a synthetic dataset
using different wording would silently score zero everywhere and render grey.
See [`docs/DATA_FORMAT.md`](../docs/DATA_FORMAT.md#controlled-vocabularies--the-strings-that-must-match-exactly).

## Two things the demo data cannot show you

Both are honest limits of synthetic data, and both are documented where they
appear rather than hidden:

**The escalation-risk model scores at chance.** `escalated` is set by an
independent coin flip, so there is no relationship between the features and
the label for the model to find. Held-out AUC lands around 0.5. On the real
extract it is 0.91. The model reporting its own poor accuracy here, instead of
showing confident-looking scores, is the feature working correctly.

**Recurring patterns are thin.** 250 cases drawn from 16 problem statements
rarely repeat a product-and-statement pair five times, so the default
threshold finds nothing and the UI says so. Drag *Minimum repeats* down to 3
to see the two that qualify.

## Regenerating

```bash
python tools/make_demo_data.py
```

The seed is fixed (`SEED = 20260930`) and the reference date is fixed
(`AS_OF = 2026-06-11`), so this is deterministic — everyone who runs it gets
byte-identical files, and the worked examples in the handbook stay true. Edit
the constants at the top of that script to change the size or the shape.

Read `tools/make_demo_data.py` alongside
[`docs/DATA_FORMAT.md`](../docs/DATA_FORMAT.md): the document specifies the
format, and the script is that specification made executable.
