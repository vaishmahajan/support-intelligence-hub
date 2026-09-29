"""My Desk — personal work queue, SLA aging, and similar-case search.

Adds an *operational* layer ("what do I work on right now?") on top of the
retrospective analytics already in app2.py.

Standalone module — imports nothing from app2.py, so it wires in with a single
call and cannot create a circular import. Design tokens below mirror app2.py.
"""

from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from urllib.parse import quote

from workspace_utils import build_switch_url, _html

# ═══════════════════════════════════════════════════════════════════════════════
# DESIGN TOKENS — mirrors app2.py
# ═══════════════════════════════════════════════════════════════════════════════

PF_SURFACE  = "#FFFFFF"
PF_BORDER   = "#E2E8F0"
PF_TEXT     = "#1E293B"
PF_TEXT_SEC = "#64748B"
PF_RADIUS   = "16px"

RH_GRAY   = "#94A3B8"
RH_GREEN  = "#10B981"
RH_GOLD   = "#F59E0B"
RH_ORANGE = "#FB923C"
RH_PURPLE = "#8B5CF6"
RH_TEAL   = "#06B6D4"
RH_BLUE   = "#3B82F6"
RH_RED    = "#EF4444"

CHART_TPL  = "plotly_white"
CHART_GRID = "rgba(0,0,0,0.06)"

SEVERITY_COLORS = {
    "Severity 1 (Urgent)": RH_RED,
    "Severity 2 (High)": RH_GOLD,
    "Severity 3 (Normal)": RH_TEAL,
    "Severity 4 (Low)": RH_GRAY,
}

STATUS_COLORS = {
    "Open": RH_RED, "In Progress": RH_GOLD,
    "Waiting on Customer": RH_ORANGE, "Waiting on Engineering": RH_PURPLE,
    "Resolved": RH_GREEN, "Closed": RH_GRAY,
}

TIER_COLORS = {
    "Premium Plus": "#6366F1", "Premium": RH_BLUE,
    "Standard": RH_TEAL, "Self-Support": RH_GRAY,
}

# ═══════════════════════════════════════════════════════════════════════════════
# QUEUE MODEL
# ═══════════════════════════════════════════════════════════════════════════════

CLOSED_STATUSES = ("Resolved", "Closed")

#: Statuses where the next move belongs to the engineer.
ACTIONABLE_STATUSES = ("Open", "In Progress", "Waiting on Engineering")

#: Statuses parked on someone else — de-prioritised, never hidden.
WAITING_STATUSES = ("Waiting on Customer",)

#: Default first-resolution targets in hours. Editable in the UI.
DEFAULT_SLA_HOURS = {
    "Severity 1 (Urgent)": 24,
    "Severity 2 (High)": 48,
    "Severity 3 (Normal)": 120,
    "Severity 4 (Low)": 240,
}

SEV_ORDER = ["Severity 1 (Urgent)", "Severity 2 (High)",
             "Severity 3 (Normal)", "Severity 4 (Low)"]

#: Contribution of raw severity to the priority score (out of 100).
SEV_WEIGHT = {
    "Severity 1 (Urgent)": 40, "Severity 2 (High)": 28,
    "Severity 3 (Normal)": 16, "Severity 4 (Low)": 8,
}

TIER_WEIGHT = {"Premium Plus": 10, "Premium": 7, "Standard": 3, "Self-Support": 0}

#: Multiplier applied when the ball is in the customer's court.
WAITING_DAMPING = 0.45

AGE_BUCKETS = [(0, 24, "< 1 day"), (24, 72, "1-3 days"), (72, 168, "3-7 days"),
               (168, 720, "1-4 weeks"), (720, 2160, "1-3 months"),
               (2160, math.inf, "> 3 months")]


def desk_reference_time(cases_df):
    """The clock 'My Desk' runs on.

    Case data is a fixed export, so wall-clock `now` would age every open case
    by however long ago the extract was taken. Anchor to the newest timestamp
    in the data instead, and never run ahead of real time.
    """
    stamps = [pd.Timestamp.now()]
    for col in ("creation_date", "last_updated", "resolution_date"):
        if col in cases_df.columns:
            mx = pd.to_datetime(cases_df[col], errors="coerce").max()
            if pd.notna(mx):
                stamps.append(mx)
    data_max = max(s for s in stamps[1:]) if len(stamps) > 1 else stamps[0]
    return min(data_max, pd.Timestamp.now())


def sla_state(ratio):
    """Map age/target into a traffic light."""
    if pd.isna(ratio):
        return "On Track", RH_GREEN
    if ratio < 0.75:
        return "On Track", RH_GREEN
    if ratio < 1.0:
        return "At Risk", RH_GOLD
    return "Breached", RH_RED


def build_queue(cases_df, accounts_df=None, owners=None, ref=None, sla_hours=None):
    """Return open cases scored and sorted by how urgently they need attention.

    Priority (0-100) = severity + SLA pressure + staleness + account tier
                       + escalation, damped when waiting on the customer.
    """
    ref = ref if ref is not None else desk_reference_time(cases_df)
    sla_hours = sla_hours or DEFAULT_SLA_HOURS

    q = cases_df[~cases_df["status"].isin(CLOSED_STATUSES)].copy()
    if owners is not None:
        q = q[q["case_owner"].isin(owners)]
    if q.empty:
        return q.assign(age_hours=[], stale_hours=[], sla_target=[], sla_ratio=[],
                        sla_label=[], sla_color=[], priority=[], support_tier=[])

    created = pd.to_datetime(q["creation_date"], errors="coerce")
    touched = pd.to_datetime(q.get("last_updated"), errors="coerce")

    q["age_hours"] = (ref - created).dt.total_seconds() / 3600
    q["stale_hours"] = (ref - touched).dt.total_seconds() / 3600
    q["age_hours"] = q["age_hours"].clip(lower=0)
    q["stale_hours"] = q["stale_hours"].clip(lower=0).fillna(q["age_hours"])

    q["sla_target"] = q["severity"].map(sla_hours).fillna(240).astype(float)
    q["sla_ratio"] = q["age_hours"] / q["sla_target"].clip(lower=1)
    _states = q["sla_ratio"].apply(sla_state)
    q["sla_label"] = [s[0] for s in _states]
    q["sla_color"] = [s[1] for s in _states]

    # ── Account context (support tier drives priority) ──
    if accounts_df is not None and "support_tier" in accounts_df.columns:
        ctx_cols = [c for c in ("account_id", "support_tier", "tam_assigned", "region",
                                "sector", "revenue_segment", "contract_end_date",
                                "hq_location") if c in accounts_df.columns]
        q = q.merge(accounts_df[ctx_cols], on="account_id", how="left")
    if "support_tier" not in q.columns:
        q["support_tier"] = None

    # ── Priority score ──
    # SLA pressure and staleness are log-scaled: a linear term saturates the
    # moment a case crosses its target, which flattens the whole ranking on any
    # backlog that has been sitting for a while. Log keeps 1.2x target and
    # 200x target distinguishable.
    sev = q["severity"].map(SEV_WEIGHT).fillna(8)
    pressure = (np.log1p(q["sla_ratio"].clip(lower=0)) / math.log1p(200)).clip(upper=1.0) * 25
    stale_days = q["stale_hours"] / 24
    stale = (np.log1p(stale_days.clip(lower=0)) / math.log1p(120)).clip(upper=1.0) * 15
    tier = q["support_tier"].map(TIER_WEIGHT).fillna(0)
    esc = pd.to_numeric(q.get("escalated", 0), errors="coerce").fillna(0).clip(0, 1) * 10

    score = sev + pressure + stale + tier + esc
    score = score.where(~q["status"].isin(WAITING_STATUSES), score * WAITING_DAMPING)
    q["priority"] = score.clip(upper=100).round(1)

    return q.sort_values("priority", ascending=False).reset_index(drop=True)


def _fmt_age(hours):
    if pd.isna(hours):
        return "—"
    if hours < 48:
        return f"{hours:.0f}h"
    days = hours / 24
    if days < 60:
        return f"{days:.0f}d"
    return f"{days / 30.4:.1f}mo"


def _age_bucket(hours):
    for lo, hi, label in AGE_BUCKETS:
        if lo <= hours < hi:
            return label
    return AGE_BUCKETS[-1][2]


# ═══════════════════════════════════════════════════════════════════════════════
# ESCALATION RISK — smoothed naive-Bayes on historical escalations
# ═══════════════════════════════════════════════════════════════════════════════

#: Features the risk model conditions on. All categorical, all already in the data.
RISK_FEATURES = ["severity", "product_name", "sbr", "account_id",
                 "support_tier", "business_hours"]

#: Shrinkage strength. A level seen fewer than ~K times is pulled toward the
#: global rate, so a product with 2 cases and 1 escalation cannot dominate.
RISK_SHRINKAGE = 20


def _logit(p):
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


@st.cache_data(show_spinner=False)
def _fit_risk_model(payload):
    """Fit per-level escalation rates. `payload` is a hashable tuple of columns."""
    feats, cols, y = payload
    n = len(y)
    base = (sum(y) / n) if n else 0.0
    tables = {}
    for f, col in zip(feats, cols):
        agg = {}
        for lvl, flag in zip(col, y):
            s, c = agg.get(lvl, (0, 0))
            agg[lvl] = (s + flag, c + 1)
        tables[f] = {lvl: (s + base * RISK_SHRINKAGE) / (c + RISK_SHRINKAGE)
                     for lvl, (s, c) in agg.items()}
    return base, tables


def fit_escalation_model(cases_df):
    """Train on every historical case that has a settled escalation outcome."""
    hist = cases_df.dropna(subset=["severity"])
    y = tuple(int(v) for v in
              pd.to_numeric(hist.get("escalated", 0), errors="coerce").fillna(0).clip(0, 1))
    feats = tuple(f for f in RISK_FEATURES if f in hist.columns)
    cols = tuple(tuple(hist[f].astype(str)) for f in feats)
    base, tables = _fit_risk_model((feats, cols, y))
    return {"base": base, "tables": tables, "features": feats, "n": len(y),
            "escalations": sum(y)}


def score_escalation_risk(df, model):
    """Add `esc_risk` (0-1) and `risk_drivers` to a case frame."""
    if df.empty:
        return df.assign(esc_risk=[], risk_drivers=[])
    base, tables = model["base"], model["tables"]
    base_lo = _logit(base)

    lo = pd.Series(base_lo, index=df.index, dtype=float)
    contribs = {}
    for f in model["features"]:
        if f not in df.columns:
            continue
        rates = df[f].astype(str).map(tables[f])
        delta = rates.apply(lambda r: (_logit(r) - base_lo) if pd.notna(r) else 0.0)
        contribs[f] = delta
        lo = lo + delta

    out = df.copy()
    out["esc_risk"] = 1 / (1 + np.exp(-lo))

    # Human-readable "why" — the two features that moved the odds most.
    if contribs:
        cdf = pd.DataFrame(contribs)
        def _why(row):
            top = row.reindex(row.abs().sort_values(ascending=False).index)[:2]
            return ", ".join(
                f"{'+' if v > 0 else ''}{v:.1f} {f.replace('_name', '').replace('_id', '')}"
                for f, v in top.items() if abs(v) > 0.05)
        out["risk_drivers"] = cdf.apply(_why, axis=1)
    else:
        out["risk_drivers"] = ""
    return out


def evaluate_risk_model(cases_df, seed=7, holdout=0.25):
    """Honest holdout AUC so the score can be reported with its accuracy."""
    hist = cases_df.dropna(subset=["severity"]).reset_index(drop=True)
    y_all = pd.to_numeric(hist.get("escalated", 0), errors="coerce").fillna(0).clip(0, 1).astype(int)
    n = len(hist)
    if n < 50 or y_all.sum() < 5:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.permutation(n)
    cut = int(n * (1 - holdout))
    tr, te = hist.iloc[idx[:cut]], hist.iloc[idx[cut:]]
    if y_all.iloc[idx[cut:]].nunique() < 2:
        return None
    model = fit_escalation_model(tr)
    scored = score_escalation_risk(te, model)
    y = y_all.iloc[idx[cut:]].values
    p = scored["esc_risk"].values

    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return None
    # Rank-based AUC (ties count a half).
    order = np.argsort(p)
    ranks = np.empty(len(p), dtype=float)
    ranks[order] = np.arange(1, len(p) + 1)
    # Average ranks within ties.
    s = pd.Series(p)
    ranks = s.rank(method="average").values
    auc = (ranks[y == 1].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))

    thresh = np.quantile(p, 0.9)
    capture = y[p >= thresh].sum() / max(y.sum(), 1)
    return {"auc": auc, "n_test": len(te), "positives": int(y.sum()),
            "top_decile_capture": capture}


# ═══════════════════════════════════════════════════════════════════════════════
# PRODUCT / VERSION ANOMALY DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_anomalies(cases_df, ref, window_days=90, min_cases=3, z_threshold=2.0):
    """Flag product+version combinations whose case volume spiked recently.

    Compares the trailing `window_days` against the average of every earlier
    window of the same length. Poisson-style z, so a jump from 1 to 3 on a
    quiet product ranks alongside a bigger jump on a noisy one.
    """
    created = pd.to_datetime(cases_df["creation_date"], errors="coerce")
    d = cases_df.assign(_created=created).dropna(subset=["_created"])
    if d.empty:
        return pd.DataFrame()

    cutoff = ref - pd.Timedelta(days=window_days)
    cur = d[(d["_created"] > cutoff) & (d["_created"] <= ref)]
    hist = d[d["_created"] <= cutoff]
    if cur.empty or hist.empty:
        return pd.DataFrame()

    span = max((cutoff - d["_created"].min()).days / window_days, 1.0)

    rows = []
    for (prod, ver), g in cur.groupby(["product_name", "product_version"], dropna=False):
        obs = len(g)
        if obs < min_cases:
            continue
        prior = hist[(hist["product_name"] == prod) & (hist["product_version"] == ver)]
        exp = len(prior) / span
        z = (obs - exp) / max(math.sqrt(max(exp, 0.5)), 0.7)
        if z < z_threshold:
            continue
        esc = int(pd.to_numeric(g.get("escalated", 0), errors="coerce").fillna(0).sum())
        sev1_2 = int(g["severity"].isin(SEV_ORDER[:2]).sum())
        rows.append({
            "product_name": prod, "product_version": ver,
            "cases_in_window": obs, "expected": round(exp, 1),
            "lift": round(obs / max(exp, 0.1), 1), "z": round(z, 1),
            "escalated": esc, "sev1_2": sev1_2,
            "accounts": g["account_name"].nunique(),
            "top_symptom": (g["problem_statement"].mode().iloc[0]
                            if not g["problem_statement"].mode().empty else ""),
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("z", ascending=False).reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════════
# SIMILAR-CASE SEARCH — TF-IDF cosine, pure Python (no new dependency)
# ═══════════════════════════════════════════════════════════════════════════════

_TOKEN_RE = re.compile(r"[a-z][a-z0-9_+.\-]{1,}")

_STOP = frozenset("""
the and for with that this from not are was were has have had but you your our
when while after before during into onto over under above below then than they them
there their been being able also only just very much more most some any all can could
should would may might must will shall does did done doing each other another such
about across against among around because both cases case issue issues red hat
customer support engineer team via per due able need needs needed
""".split())


def _tokenize(text):
    return [t for t in _TOKEN_RE.findall(str(text).lower())
            if len(t) > 2 and t not in _STOP]


@st.cache_data(show_spinner=False)
def _build_tfidf_index(docs):
    """Build an inverted TF-IDF index. `docs` is a hashable tuple of strings."""
    n = len(docs)
    tfs, df_counts = [], {}
    for doc in docs:
        tf = {}
        for tok in _tokenize(doc):
            tf[tok] = tf.get(tok, 0) + 1
        tfs.append(tf)
        for tok in tf:
            df_counts[tok] = df_counts.get(tok, 0) + 1

    idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df_counts.items()}

    inverted = {}
    for i, tf in enumerate(tfs):
        weights = {t: (1 + math.log(c)) * idf[t] for t, c in tf.items()}
        norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        for t, w in weights.items():
            inverted.setdefault(t, []).append((i, w / norm))
    return idf, inverted, n


def search_similar(query, docs, top_k=5):
    """Return [(doc_index, cosine_similarity)] for the closest documents."""
    if not query or not str(query).strip() or not docs:
        return []
    idf, inverted, _ = _build_tfidf_index(tuple(docs))

    q_tf = {}
    for tok in _tokenize(query):
        q_tf[tok] = q_tf.get(tok, 0) + 1
    q_w = {t: (1 + math.log(c)) * idf[t] for t, c in q_tf.items() if t in idf}
    if not q_w:
        return []
    q_norm = math.sqrt(sum(w * w for w in q_w.values())) or 1.0

    scores = {}
    for t, w in q_w.items():
        wq = w / q_norm
        for doc_i, wd in inverted.get(t, ()):
            scores[doc_i] = scores.get(doc_i, 0.0) + wq * wd

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [(i, s) for i, s in ranked[:top_k] if s > 0.01]


# ═══════════════════════════════════════════════════════════════════════════════
# RECOMMENDED NEXT ACTION — deterministic rules, not a prediction
# ═══════════════════════════════════════════════════════════════════════════════
#
# Every rule below fires on a condition that is directly readable from the case
# row. The engineer is told which condition fired, so the recommendation can be
# argued with rather than taken on faith. This is NOT a model.

#: Products handled by few enough engineers that "ask a specialist" beats "keep
#: digging". Computed from the data at call time, not hardcoded.
SPECIALIST_MAX_ENGINEERS = 6


def next_best_action(row, specialist_products=(), repeat_products=()):
    """Return (action, reason) for one case. First matching rule wins.

    Rules are ordered by how much the engineer's next hour is worth spending
    on them. `specialist_products` and `repeat_products` come from
    `action_context()` so the caller computes them once for the whole queue.
    """
    status = str(row.get("status", ""))
    ratio = row.get("sla_ratio")
    stale_h = row.get("stale_hours")
    escalated = int(pd.to_numeric(row.get("escalated", 0), errors="coerce") or 0) == 1
    tier = row.get("support_tier")
    product = row.get("product_name")
    sev = str(row.get("severity", ""))

    if escalated:
        return ("Review escalation history before the next customer contact",
                "This case carries the escalation flag, so someone above the "
                "engineer is already watching it.")

    if status in WAITING_STATUSES:
        if pd.notna(stale_h) and stale_h > 168:
            return ("Send a follow-up — request the information again",
                    f"Parked on the customer and silent for "
                    f"{_fmt_age(stale_h)}. Waiting is not a plan past a week.")
        return ("Confirm what you are waiting for is written in the case",
                "Waiting on customer. A specific, dated request gets answered; "
                "'any update?' does not.")

    if pd.notna(ratio) and ratio >= 1.0:
        return ("Update the customer before they chase you",
                f"Already {ratio:.1f}x the {row.get('sla_target', 0):.0f}h target. "
                f"A written update resets the conversation even when the fix is "
                f"not ready.")

    if pd.notna(ratio) and ratio >= 0.75:
        return ("Update customer before the SLA target",
                f"At {ratio * 100:.0f}% of the {row.get('sla_target', 0):.0f}h "
                f"target — inside the window where an update still lands early.")

    if pd.notna(stale_h) and stale_h > 72:
        return ("Add a customer-facing update",
                f"No update logged for {_fmt_age(stale_h)}. Silence is what turns "
                f"a slow case into an escalated one.")

    if product in repeat_products:
        return ("Review the resolved cases on this same symptom",
                f"This exact problem statement has been closed before on "
                f"{product}. Read those first rather than starting cold.")

    if tier in ("Premium Plus", "Premium"):
        return ("Prioritise customer communication",
                f"{tier} tier account — contractually the shortest response "
                f"expectations in the book.")

    if product in specialist_products:
        return ("Ask an engineer with matching product expertise",
                f"Few engineers in the dataset have closed {product} cases, so "
                f"this is a narrow specialism rather than common ground.")

    if sev.startswith("Severity 1"):
        return ("Work this before anything else in the queue",
                "Severity 1 and inside target — the one case where being early "
                "is still possible.")

    return ("Progress the technical investigation",
            "No SLA, staleness, escalation or account-tier condition is firing. "
            "This case is simply next in the ranking.")


def action_context(cases_df):
    """Queue-wide facts the per-case rules need. Computed once."""
    closed = cases_df[cases_df["status"].isin(CLOSED_STATUSES)]

    engineers = closed.groupby("product_name")["case_owner"].nunique()
    specialist = set(engineers[engineers <= SPECIALIST_MAX_ENGINEERS].index)

    key = closed["problem_statement"].astype(str).str.lower().str.strip()
    repeats = closed.assign(_k=key).groupby(["product_name", "_k"]).size()
    repeat_products = set(repeats[repeats >= 3].index.get_level_values(0))

    return {"specialist_products": specialist, "repeat_products": repeat_products}


# ═══════════════════════════════════════════════════════════════════════════════
# ESCALATION READINESS — is the case actually ready to hand to engineering?
# ═══════════════════════════════════════════════════════════════════════════════
#
# Six checks read structured fields. Five read the free-text description, which
# in this dataset genuinely carries environment / impact / timeline / log /
# troubleshooting statements. Anything the dataset does not record at all is
# listed separately as unavailable and kept OUT of the score, so the number is
# never inflated by pretending absent data is a failed check.

_READINESS_TEXT_CHECKS = [
    ("Environment described",
     r"production environment|staging|uat|test environment|development environment|"
     r"environment\s*:|on-prem|disconnected|air-?gapped"),
    ("Business impact stated",
     r"affecting [\w\+, ]*users|affecting all|business impact|revenue|outage|"
     r"customers? (are )?impacted|jobs are failing|unable to"),
    ("Onset / timeline recorded",
     r"first observed on|timeline\s*:|detected the anomaly at|started occurring|"
     r"since \d|after (the )?(upgrade|migration|update|patch)"),
    ("Log or error evidence referenced",
     r"logs show|log entries|stack trace|traceback|error message|returning \d{3}|"
     r"errors? in|exception"),
    ("Prior troubleshooting recorded",
     r"has attempted|already tried|attempted|workaround|restarted|rolled? back|"
     r"troubleshoot|on-call engineer confirmed|escalation requested"),
]

#: Fields a support engineer would want before escalating that this dataset
#: simply does not carry. Listed honestly rather than scored as failures.
_READINESS_UNAVAILABLE = [
    "Reproduction steps",
    "Attached diagnostic bundle (sos report / must-gather)",
    "Customer-confirmed severity justification",
]


def escalation_readiness(row, cases_df=None):
    """Return {items, passed, total, unavailable} for one case.

    `items` is [(label, ok, detail)]. Only checks that CAN be evaluated from the
    dataset count toward `total`.
    """
    desc = str(row.get("description") or "")
    stmt = str(row.get("problem_statement") or "").strip()

    items = [
        ("Problem statement", bool(stmt) and stmt.lower() != "nan",
         stmt[:70] if stmt else "empty"),
        ("Product identified", pd.notna(row.get("product_name")),
         str(row.get("product_name") or "—")),
        ("Product version identified", pd.notna(row.get("product_version")),
         str(row.get("product_version") or "—")),
        ("Severity set", pd.notna(row.get("severity")),
         str(row.get("severity") or "—")),
        ("Account and support tier known",
         pd.notna(row.get("account_name")) and pd.notna(row.get("support_tier")),
         f"{row.get('account_name', '—')} · {row.get('support_tier', 'tier unknown')}"),
    ]

    for label, pattern in _READINESS_TEXT_CHECKS:
        hit = re.search(pattern, desc, flags=re.IGNORECASE)
        items.append((label, bool(hit),
                      f"“…{desc[max(hit.start() - 20, 0):hit.end() + 30].strip()}…”"
                      if hit else "no statement found in the case description"))

    # Eleventh check: is there prior art to point engineering at?
    if cases_df is not None and stmt:
        closed = cases_df[cases_df["status"].isin(CLOSED_STATUSES)]
        same = closed[closed["problem_statement"].astype(str).str.lower().str.strip()
                      == stmt.lower()]
        items.append(("Similar resolved case identified", len(same) > 0,
                      f"{len(same)} closed case{'s' if len(same) != 1 else ''} with "
                      f"this exact problem statement" if len(same)
                      else "no closed case matches this statement"))

    passed = sum(1 for _, ok, _ in items if ok)
    return {"items": items, "passed": passed, "total": len(items),
            "unavailable": _READINESS_UNAVAILABLE}


# ═══════════════════════════════════════════════════════════════════════════════
# POTENTIAL SME ENGINE
# ═══════════════════════════════════════════════════════════════════════════════
#
# Deliberately called "potential SME" and never "available engineer" — the
# dataset records a shift pattern, not a rota or a presence signal.

SME_WEIGHTS = {
    "same_version": 3.0,   # closed a case on this exact product+version
    "same_product": 2.0,   # closed a case on this product
    "similar_case": 3.0,   # closed a case with this exact problem statement
    "same_sbr": 1.0,       # sits in the SBR that owns this work
    "skill_match": 1.5,    # product name appears in their ranked skills
}


def find_smes(row, cases_df, associates_df, skills_df, top_k=4, exclude=None):
    """Rank engineers by documented experience with this kind of case."""
    closed = cases_df[cases_df["status"].isin(CLOSED_STATUSES)]
    if closed.empty:
        return pd.DataFrame()

    product = row.get("product_name")
    version = row.get("product_version")
    sbr = row.get("sbr")
    stmt = str(row.get("problem_statement") or "").lower().strip()

    prod_hist = closed[closed["product_name"] == product]
    ver_hist = prod_hist[prod_hist["product_version"] == version]
    stmt_hist = closed[closed["problem_statement"].astype(str).str.lower().str.strip()
                       == stmt] if stmt else closed.iloc[0:0]

    cand = set(prod_hist["case_owner"].dropna()) | set(stmt_hist["case_owner"].dropna())
    cand.discard(exclude)
    if not cand:
        return pd.DataFrame()

    prod_n = prod_hist["case_owner"].value_counts()
    ver_n = ver_hist["case_owner"].value_counts()
    stmt_n = stmt_hist["case_owner"].value_counts()

    rows = []
    for name in cand:
        a = associates_df[associates_df["associate_name"] == name]
        a_row = a.iloc[0] if not a.empty else None
        aid = a_row["associate_id"] if a_row is not None else None

        sk = (skills_df[skills_df["associate_id"] == aid].sort_values("skill_rank")
              if aid is not None else skills_df.iloc[0:0])
        skill_names = list(sk["skill_name"].astype(str))
        prod_tokens = set(_tokenize(product))
        matched_skill = next(
            (s for s in skill_names if prod_tokens & set(_tokenize(s))), None)

        mine = closed[closed["case_owner"] == name]
        score = (
            SME_WEIGHTS["same_version"] * min(ver_n.get(name, 0), 5) / 5
            + SME_WEIGHTS["same_product"] * min(prod_n.get(name, 0), 10) / 10
            + SME_WEIGHTS["similar_case"] * min(stmt_n.get(name, 0), 5) / 5
            + SME_WEIGHTS["same_sbr"] * (1.0 if a_row is not None
                                         and a_row.get("sbr") == sbr else 0.0)
            + SME_WEIGHTS["skill_match"] * (1.0 if matched_skill else 0.0)
        )

        evidence = []
        if stmt_n.get(name, 0):
            evidence.append(f"{stmt_n[name]} case(s) on this exact symptom")
        if ver_n.get(name, 0):
            evidence.append(f"{ver_n[name]} on {product} {version}")
        elif prod_n.get(name, 0):
            evidence.append(f"{prod_n[name]} on {product}")
        if a_row is not None and a_row.get("sbr") == sbr:
            evidence.append("same SBR")
        if matched_skill:
            evidence.append(f"ranked skill: {matched_skill}")

        rows.append({
            "associate": name,
            "sbr": a_row.get("sbr") if a_row is not None else "—",
            "shift_on_record": a_row.get("shift") if a_row is not None else "—",
            "relevant_skill": matched_skill or (skill_names[0] if skill_names else "—"),
            "matching_cases": int(prod_n.get(name, 0) + stmt_n.get(name, 0)),
            "cases_resolved": int(len(mine)),
            "avg_resolve_hours": round(
                pd.to_numeric(mine["time_to_resolve_hours"], errors="coerce").mean(), 1)
            if len(mine) else None,
            "avg_csat": round(pd.to_numeric(mine["csat_score"], errors="coerce").mean(), 2)
            if len(mine) else None,
            "match_score": round(score, 2),
            "why": "; ".join(evidence) or "closed cases on this product",
        })

    out = pd.DataFrame(rows).sort_values(
        ["match_score", "cases_resolved"], ascending=False)
    return out.head(top_k).reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════════
# RECURRING ISSUE DETECTION — observed history, not prediction
# ═══════════════════════════════════════════════════════════════════════════════

def recurring_patterns(cases_df, min_cases=4, product=None, statement=None):
    """Group closed cases by product + normalised problem statement.

    Exact-statement grouping is deliberate: it is fully deterministic and
    reproducible, and in this dataset symptoms genuinely repeat verbatim
    across accounts. Nothing here is inferred.
    """
    closed = cases_df[cases_df["status"].isin(CLOSED_STATUSES)].copy()
    if closed.empty:
        return pd.DataFrame()
    closed["_key"] = closed["problem_statement"].astype(str).str.lower().str.strip()
    if product is not None:
        closed = closed[closed["product_name"] == product]
    if statement is not None:
        closed = closed[closed["_key"] == str(statement).lower().strip()]
    if closed.empty:
        return pd.DataFrame()

    rows = []
    for (prod, key), g in closed.groupby(["product_name", "_key"], dropna=False):
        if len(g) < min_cases:
            continue
        esc = pd.to_numeric(g.get("escalated", 0), errors="coerce").fillna(0)
        rows.append({
            "product_name": prod,
            "problem_statement": g["problem_statement"].iloc[0],
            "cases": len(g),
            "accounts": g["account_name"].nunique(),
            "versions": ", ".join(sorted(str(v) for v in g["product_version"].dropna().unique())[:6]),
            "avg_resolve_hours": round(
                pd.to_numeric(g["time_to_resolve_hours"], errors="coerce").mean(), 1),
            "escalation_rate": round(esc.mean() * 100, 1),
            "avg_csat": round(pd.to_numeric(g["csat_score"], errors="coerce").mean(), 2),
            "engineers": ", ".join(g["case_owner"].value_counts().head(3).index),
            "sbr": g["sbr"].mode().iloc[0] if not g["sbr"].mode().empty else "—",
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("cases", ascending=False).reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════════
# CASE TIMELINE — only milestones the dataset actually records
# ═══════════════════════════════════════════════════════════════════════════════

def case_timeline(row, ref):
    """Return [(label, timestamp_or_None, note, color)] in chronological order.

    The dataset has three timestamps and an escalation flag with no timestamp.
    First response, customer replies and individual updates are not recorded,
    so they are returned as explicitly missing rather than interpolated.
    """
    created = pd.to_datetime(row.get("creation_date"), errors="coerce")
    touched = pd.to_datetime(row.get("last_updated"), errors="coerce")
    resolved = pd.to_datetime(row.get("resolution_date"), errors="coerce")
    escalated = int(pd.to_numeric(row.get("escalated", 0), errors="coerce") or 0) == 1
    status = str(row.get("status", ""))

    ev = [("Case created", created, "creation_date", RH_BLUE)]

    ev.append(("First response", None,
               "not recorded in this dataset — no first-response field exists",
               RH_GRAY))

    if pd.notna(touched):
        note = "last_updated"
        if pd.notna(created) and touched <= created:
            note = "last_updated — no update logged since creation"
        ev.append(("Last update logged", touched, note, RH_GOLD))

    if escalated:
        ev.append(("Escalated", None,
                   "escalation flag is set; the dataset records no escalation "
                   "timestamp, so this is placed by status, not by time",
                   RH_PURPLE))

    if status in WAITING_STATUSES:
        ev.append(("Waiting on customer", None,
                   "current status — the dataset records no reply history",
                   RH_ORANGE))

    if pd.notna(resolved):
        ev.append(("Resolved", resolved, "resolution_date", RH_GREEN))
    elif status in CLOSED_STATUSES:
        ev.append(("Closed", None, "status is closed but no resolution_date is set",
                   RH_GRAY))
    else:
        ev.append(("Still open", None,
                   f"open for {_fmt_age((ref - created).total_seconds() / 3600)} "
                   f"as of the dataset clock" if pd.notna(created) else "open",
                   RH_RED))
    return ev


# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOMER RISK CONTEXT — measurable conditions only
# ═══════════════════════════════════════════════════════════════════════════════

def account_risk(account_id, cases_df, queue_df=None):
    """Return (level, color, factors) from open volume, escalations, CSAT, SLA."""
    acct = cases_df[cases_df["account_id"] == account_id]
    if acct.empty:
        return "Unknown", RH_GRAY, ["No cases on record for this account."]

    open_n = int((~acct["status"].isin(CLOSED_STATUSES)).sum())
    esc_n = int(pd.to_numeric(acct.get("escalated", 0), errors="coerce").fillna(0).sum())
    csat = pd.to_numeric(acct.get("csat_score"), errors="coerce").mean()
    breached = 0
    if queue_df is not None and not queue_df.empty and "sla_label" in queue_df.columns:
        breached = int(((queue_df["account_id"] == account_id)
                        & (queue_df["sla_label"] == "Breached")).sum())

    factors, points = [], 0
    if open_n >= 8:
        points += 2
        factors.append(f"{open_n} cases currently open")
    elif open_n >= 4:
        points += 1
        factors.append(f"{open_n} cases currently open")
    else:
        factors.append(f"{open_n} case{'s' if open_n != 1 else ''} currently open")

    if esc_n >= 3:
        points += 2
        factors.append(f"{esc_n} escalations on record")
    elif esc_n >= 1:
        points += 1
        factors.append(f"{esc_n} escalation{'s' if esc_n != 1 else ''} on record")
    else:
        factors.append("no escalations on record")

    if pd.notna(csat):
        if csat < 3.0:
            points += 2
            factors.append(f"average CSAT {csat:.2f}/5")
        elif csat < 3.8:
            points += 1
            factors.append(f"average CSAT {csat:.2f}/5")
        else:
            factors.append(f"average CSAT {csat:.2f}/5")
    else:
        factors.append("no CSAT scores recorded")

    if breached >= 3:
        points += 2
        factors.append(f"{breached} open cases past SLA target")
    elif breached >= 1:
        points += 1
        factors.append(f"{breached} open case{'s' if breached != 1 else ''} past SLA target")

    if points >= 5:
        return "High attention", RH_RED, factors
    if points >= 2:
        return "Attention", RH_GOLD, factors
    return "Stable", RH_GREEN, factors


# ═══════════════════════════════════════════════════════════════════════════════
# PER-USER STATE — private notes, follow-ups, and the last-seen snapshot
# ═══════════════════════════════════════════════════════════════════════════════
#
# Additive table created on demand. No existing table or schema file is touched.
# If the database refuses the write (read-only replica, missing grant) every
# helper degrades to session-only state and the UI says so out loud.

_STATE_DDL = """
CREATE TABLE IF NOT EXISTS desk_user_state (
    user_email   TEXT NOT NULL,
    kind         TEXT NOT NULL,
    case_number  TEXT NOT NULL,
    payload      TEXT,
    updated_at   TEXT,
    PRIMARY KEY (user_email, kind, case_number)
)
"""


def _state_backend():
    """'db' if the state table is usable, otherwise 'session'. Cached per run."""
    if "_desk_state_backend" in st.session_state:
        return st.session_state["_desk_state_backend"]
    backend = "session"
    try:
        from db import get_connection
        conn = get_connection()
        conn.execute(_STATE_DDL)
        conn.commit()
        conn.close()
        backend = "db"
    except Exception:
        backend = "session"
    st.session_state["_desk_state_backend"] = backend
    return backend


def _session_state_store():
    return st.session_state.setdefault("_desk_state_fallback", {})


def state_get(user_email, kind):
    """Return {case_number: payload} for one user and one kind of state."""
    if _state_backend() == "db":
        try:
            from db import get_connection, PARAM
            conn = get_connection()
            cur = conn.execute(
                f"SELECT case_number, payload FROM desk_user_state "
                f"WHERE user_email={PARAM} AND kind={PARAM}",
                (user_email, kind))
            out = {str(r[0]): r[1] for r in cur.fetchall()}
            conn.close()
            return out
        except Exception:
            pass
    return dict(_session_state_store().get((user_email, kind), {}))


def state_put(user_email, kind, case_number, payload):
    ts = pd.Timestamp.now().isoformat(timespec="seconds")
    if _state_backend() == "db":
        try:
            from db import get_connection, PARAM, IS_PG
            conn = get_connection()
            conn.execute(
                f"DELETE FROM desk_user_state WHERE user_email={PARAM} "
                f"AND kind={PARAM} AND case_number={PARAM}",
                (user_email, kind, str(case_number)))
            conn.execute(
                f"INSERT INTO desk_user_state "
                f"(user_email, kind, case_number, payload, updated_at) "
                f"VALUES ({PARAM},{PARAM},{PARAM},{PARAM},{PARAM})",
                (user_email, kind, str(case_number), payload, ts))
            conn.commit()
            conn.close()
            return True
        except Exception:
            pass
    _session_state_store().setdefault((user_email, kind), {})[str(case_number)] = payload
    return False


def state_delete(user_email, kind, case_number):
    if _state_backend() == "db":
        try:
            from db import get_connection, PARAM
            conn = get_connection()
            conn.execute(
                f"DELETE FROM desk_user_state WHERE user_email={PARAM} "
                f"AND kind={PARAM} AND case_number={PARAM}",
                (user_email, kind, str(case_number)))
            conn.commit()
            conn.close()
            return True
        except Exception:
            pass
    _session_state_store().get((user_email, kind), {}).pop(str(case_number), None)
    return False


def queue_signature(q):
    """A compact, comparable fingerprint of the queue, keyed by case number."""
    if q.empty:
        return {}
    return {
        str(r["case_number"]): "|".join([
            str(r.get("status", "")),
            str(int(pd.to_numeric(r.get("escalated", 0), errors="coerce") or 0)),
            str(r.get("sla_label", "")),
            str(pd.to_datetime(r.get("last_updated"), errors="coerce")),
        ])
        for _, r in q.iterrows()
    }


def diff_snapshot(previous, current, q):
    """Return a list of (icon, text) describing what moved since `previous`."""
    if not previous:
        return None
    added = [c for c in current if c not in previous]
    gone = [c for c in previous if c not in current]
    changed = [c for c in current if c in previous and current[c] != previous[c]]

    by_case = {str(r["case_number"]): r for _, r in q.iterrows()} if not q.empty else {}
    now_esc = [c for c in changed
               if previous[c].split("|")[1] == "0" and current[c].split("|")[1] == "1"]
    now_wait = [c for c in changed
                if by_case.get(c) is not None
                and str(by_case[c].get("status")) in WAITING_STATUSES
                and previous[c].split("|")[0] not in WAITING_STATUSES]
    now_breach = [c for c in changed
                  if previous[c].split("|")[2] != "Breached"
                  and current[c].split("|")[2] == "Breached"]

    out = []
    if added:
        out.append(("+", f"{len(added)} new case{'s' if len(added) != 1 else ''} in your queue"))
    if gone:
        out.append(("−", f"{len(gone)} case{'s' if len(gone) != 1 else ''} left your queue "
                         f"(closed or reassigned)"))
    if now_esc:
        out.append(("!", f"{len(now_esc)} newly escalated"))
    if now_breach:
        out.append(("!", f"{len(now_breach)} newly past SLA target"))
    if now_wait:
        out.append(("~", f"{len(now_wait)} moved to Waiting on Customer"))
    other = len(changed) - len(set(now_esc) | set(now_wait) | set(now_breach))
    if other > 0:
        out.append(("~", f"{other} case{'s' if other != 1 else ''} updated"))
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# HTML HELPERS — match app2.py card language
# ═══════════════════════════════════════════════════════════════════════════════

def _pill(text, color, solid=False):
    if solid:
        return (f'<span style="background:{color};color:#fff;padding:2px 9px;'
                f'border-radius:9999px;font-size:0.65rem;font-weight:700;'
                f'white-space:nowrap;">{text}</span>')
    rgb = ",".join(str(int(color.lstrip("#")[i:i + 2], 16)) for i in (0, 2, 4))
    return (f'<span style="background:rgba({rgb},0.12);color:{color};padding:2px 9px;'
            f'border-radius:9999px;font-size:0.65rem;font-weight:700;'
            f'white-space:nowrap;">{text}</span>')


def _kpi(label, value, color, sub=""):
    return _html(f"""<div style="flex:1;min-width:130px;background:var(--secondary-background-color,{PF_SURFACE});
        border:1px solid var(--border-color,{PF_BORDER});border-left:3px solid {color};
        border-radius:12px;padding:12px 16px;">
        <div style="font-size:1.5rem;font-weight:800;color:{color};line-height:1.1;">{value}</div>
        <div style="font-size:0.66rem;color:{PF_TEXT_SEC};text-transform:uppercase;
            font-weight:700;letter-spacing:.05em;margin-top:2px;">{label}</div>
        <div style="font-size:0.66rem;color:{PF_TEXT_SEC};margin-top:2px;">{sub}</div>
    </div>""")


def _section(title, subtitle=""):
    st.markdown(_html(f"""<div style="margin:18px 0 10px;">
        <div style="font-size:1.0rem;font-weight:800;color:var(--text-color,{PF_TEXT});">{title}</div>
        <div style="font-size:0.75rem;color:{PF_TEXT_SEC};">{subtitle}</div>
    </div>"""), unsafe_allow_html=True)


#: Motion language. Deliberately short and non-looping — support software
#: should feel fast, and an animation that repeats is an animation in the way.
_DESK_CSS = """
<style>
@keyframes _deskIn { from { opacity:0; transform:translateY(6px); }
                     to   { opacity:1; transform:translateY(0); } }
@keyframes _deskBar { from { width:0; } }
@keyframes _deskDraw { from { transform:scaleX(0); } to { transform:scaleX(1); } }
.desk-card { animation:_deskIn .32s cubic-bezier(.22,.8,.3,1) both; }
.desk-sla-fill { animation:_deskBar .6s cubic-bezier(.22,.8,.3,1) both;
                 transition:width .4s ease; }
.desk-tl-rail { transform-origin:left center; animation:_deskDraw .5s
                cubic-bezier(.22,.8,.3,1) both; }
.desk-reveal { animation:_deskIn .4s cubic-bezier(.22,.8,.3,1) both; }
@media (prefers-reduced-motion: reduce) {
  .desk-card, .desk-sla-fill, .desk-tl-rail, .desk-reveal { animation:none!important; }
}
</style>
"""


def _inject_desk_css():
    """render_my_desk runs once per script run, so a plain emit is enough."""
    st.markdown(_DESK_CSS, unsafe_allow_html=True)


def _stagger(i, step=0.03, cap=0.30):
    """Animation delay for the i-th card in a list."""
    return f"animation-delay:{min(i * step, cap):.2f}s;"


def _fig_layout(fig, height=320):
    fig.update_layout(
        template=CHART_TPL, height=height, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=PF_TEXT, size=11), showlegend=False,
    )
    fig.update_xaxes(gridcolor=CHART_GRID, zeroline=False)
    fig.update_yaxes(gridcolor=CHART_GRID, zeroline=False)
    return fig


# ═══════════════════════════════════════════════════════════════════════════════
# SCOPE RESOLUTION (RBAC)
# ═══════════════════════════════════════════════════════════════════════════════

def resolve_scope(associates_df, role, user_email):
    """Return (owner_names, scope_label, scope_options) for the current user."""
    email = (user_email or "").lower()
    me = associates_df[associates_df["email"].str.lower() == email] \
        if "email" in associates_df.columns else associates_df.iloc[0:0]
    my_name = me.iloc[0]["associate_name"] if not me.empty else None

    if role == "associate":
        return ([my_name] if my_name else []), "My cases", []

    if role == "manager":
        team = associates_df[
            associates_df.get("manager_email", pd.Series(dtype=str))
            .fillna("").str.lower() == email
        ]
        opts = ["My team"] + ([f"Just me ({my_name})"] if my_name else []) + ["Everyone"]
        return sorted(team["associate_name"].dropna().unique()), "My team", opts

    return None, "Everyone", ["Everyone", "By associate"]


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def _greeting(ref):
    """Time-of-day greeting from the wall clock — the engineer's clock, not the
    dataset's. The dataset clock governs case ages only."""
    h = pd.Timestamp.now().hour
    return "Good morning" if h < 12 else ("Good afternoon" if h < 18 else "Good evening")


def render_my_desk(cases_df, associates_df, skills_df, accounts_df,
                   role="associate", user_email="", display_name="",
                   ai_fn=None):
    """Render the My Desk tab.

    ai_fn: optional callable(messages, max_tokens) -> str used for the shift
    handoff brief and case briefs. Every AI surface has a deterministic local
    fallback, so the tab is fully usable with no endpoint configured.
    """
    _inject_desk_css()
    ref = desk_reference_time(cases_df)
    my_owners, _, _ = resolve_scope(associates_df, role, user_email)

    # ── Header ─────────────────────────────────────────────────────────────────
    # Containers below carry explicit keys purely so the guided tour has stable
    # `.st-key-*` selectors to spotlight. They add no layout of their own.
    who = display_name or (my_owners[0] if my_owners else "there")
    _hdr = st.container(key="desk_header")
    with _hdr:
        st.markdown(_html(f"""<div class="desk-reveal" style="background:linear-gradient(135deg,
            rgba(99,102,241,0.06),rgba(6,182,212,0.03));border:1px solid
            var(--border-color,{PF_BORDER});border-radius:{PF_RADIUS};
            padding:14px 20px;margin-bottom:10px;display:flex;
            justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;">
            <div>
                <div style="font-size:1.15rem;font-weight:800;
                    color:var(--text-color,{PF_TEXT});">{_greeting(ref)}, {who}</div>
                <div style="font-size:0.75rem;color:{PF_TEXT_SEC};">Your operational
                    workspace — what needs you now, why, and who can help.</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:0.62rem;color:{PF_TEXT_SEC};text-transform:uppercase;
                    font-weight:700;letter-spacing:.05em;">Data as of</div>
                <div style="font-size:0.92rem;font-weight:800;
                    color:var(--text-color,{PF_TEXT});">{ref:%d %b %Y}</div>
            </div>
        </div>"""), unsafe_allow_html=True)

    with st.container(key="desk_search_box"):
        _render_global_search(cases_df, associates_df, accounts_df)

    # ── My Cases / Team Queue (RBAC) ───────────────────────────────────────────
    # Associates never see the team mode at all — it is not rendered, not merely
    # disabled, so there is no control to poke at.
    mode = "My Cases"
    if role in ("manager", "admin"):
        with st.container(key="desk_scope"):
            mode = st.segmented_control(
                "Scope", ["My Cases", "Team Queue"], default="My Cases",
                key="desk_mode", label_visibility="collapsed") or "My Cases"

    drill = None
    if mode == "Team Queue":
        if role == "manager":
            team = associates_df[
                associates_df.get("manager_email", pd.Series(dtype=str))
                .fillna("").str.lower() == (user_email or "").lower()]
            owners = sorted(team["associate_name"].dropna().unique())
            scope_label = f"My team ({len(owners)} engineers)"
        else:
            owners, scope_label = None, "All associates"
        pool = sorted(owners) if owners else sorted(
            associates_df["associate_name"].dropna().unique())
        drill = st.selectbox("Filter to one associate (optional)",
                             ["— whole team —"] + list(pool), key="desk_scope_who")
        if drill and drill != "— whole team —":
            owners, scope_label = [drill], drill
        else:
            drill = None
    else:
        owners = my_owners or []
        scope_label = "My cases"

    if owners is not None and not owners:
        st.info("No associate record is linked to this login, so there is no personal "
                "queue. Everything that does not depend on ownership — similar-case "
                "search, recurring patterns, team queue — still works.")

    # ── SLA targets (configurable) ─────────────────────────────────────────────
    with st.container(key="desk_slatargets"):
        with st.expander("SLA targets (hours to first resolution)", expanded=False):
            st.caption("Defaults are standard enterprise support targets. Adjust to "
                       "match your own commitments — every badge and chart below "
                       "recalculates.")
            sc = st.columns(4)
            sla = {}
            for i, sev in enumerate(SEV_ORDER):
                with sc[i]:
                    sla[sev] = st.number_input(
                        sev.split(" (")[0], min_value=1, max_value=2000,
                        value=int(DEFAULT_SLA_HOURS[sev]), step=1, key=f"desk_sla_{i}")

    q = build_queue(cases_df, accounts_df, owners=owners, ref=ref, sla_hours=sla)

    # ── KPI strip ──────────────────────────────────────────────────────────────
    total = len(q)
    breached = int((q["sla_label"] == "Breached").sum()) if total else 0
    at_risk = int((q["sla_label"] == "At Risk").sum()) if total else 0
    stale7 = int((q["stale_hours"] > 168).sum()) if total else 0
    esc = int(pd.to_numeric(q.get("escalated", 0), errors="coerce").fillna(0).sum()) if total else 0
    actionable = int(q["status"].isin(ACTIONABLE_STATUSES).sum()) if total else 0

    _kpi_box = st.container(key="desk_kpis")
    _kpi_box.markdown(
        f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:6px;">'
        + _kpi("Open cases", total, "#6366F1", scope_label)
        + _kpi("Needs my move", actionable, RH_BLUE, "not waiting on customer")
        + _kpi("SLA breached", breached, RH_RED, f"{(breached / total * 100) if total else 0:.0f}% of queue")
        + _kpi("At risk", at_risk, RH_GOLD, "within 25% of target")
        + _kpi("Untouched 7d+", stale7, RH_ORANGE, "no update logged")
        + _kpi("Escalated", esc, RH_PURPLE, "customer escalation flag")
        + "</div>", unsafe_allow_html=True)

    with st.container(key="desk_freshness"):
        st.caption(
            f"Clock anchored to the newest timestamp in the dataset — "
            f"**{ref:%d %b %Y, %H:%M}**. Ages and SLA state are measured from there, "
            f"not from wall-clock time. This is a static extract, not a live feed.")

    if total and breached / total > 0.9:
        st.warning(
            f"**{breached / total * 100:.0f}% of this queue is past target.** The open "
            f"cases in this extract were never closed by the source system, so they age "
            f"indefinitely and the breached/at-risk split stops discriminating. Rank by "
            f"the **priority score** instead — it stays meaningful because SLA pressure "
            f"and staleness are log-scaled, so a case 2x over target still sorts below "
            f"one 200x over. Raise the targets above to restore the traffic light.",
            icon=":material/info:")

    with st.container(key="desk_changed"):
        _render_what_changed(q, user_email or "anonymous", scope_label)

    # ── Tabs ───────────────────────────────────────────────────────────────────
    if mode == "Team Queue":
        labels = ["Team Queue", "Team Workload", "SLA & Aging", "Escalation Risk",
                  "Similar & Patterns", "Trends & Anomalies"]
    else:
        labels = ["Work Queue", "My Follow-ups", "SLA & Aging", "Escalation Risk",
                  "Similar & Patterns", "Trends & Anomalies", "My Performance"]
    if role == "admin":
        labels.append("System")

    with st.container(key="desk_tabs"):
        tabs = dict(zip(labels, st.tabs(labels)))
    ctx = action_context(cases_df)

    if mode == "Team Queue":
        with tabs["Team Queue"]:
            _render_queue(q, cases_df, accounts_df, skills_df, associates_df, ref,
                          scope_label, ai_fn, display_name, ctx, user_email, role)
        with tabs["Team Workload"]:
            _render_workload(q, associates_df, ref, scope_label)
    else:
        with tabs["Work Queue"]:
            _render_queue(q, cases_df, accounts_df, skills_df, associates_df, ref,
                          scope_label, ai_fn, display_name, ctx, user_email, role)
        with tabs["My Follow-ups"]:
            _render_followups(cases_df, accounts_df, ref, sla, user_email or "anonymous",
                              ctx)
        with tabs["My Performance"]:
            _render_performance(cases_df, associates_df, skills_df, owners,
                                scope_label, ref)

    with tabs["SLA & Aging"]:
        _render_sla(q, cases_df, sla, ref)
    with tabs["Escalation Risk"]:
        _render_risk(q, cases_df, scope_label)
    with tabs["Similar & Patterns"]:
        _render_similar(cases_df, associates_df, skills_df)
    with tabs["Trends & Anomalies"]:
        _render_trends(cases_df, ref)
    if role == "admin":
        with tabs["System"]:
            _render_system(cases_df, associates_df, skills_df, accounts_df, ref)


# ═══════════════════════════════════════════════════════════════════════════════
# WHAT CHANGED — diffed against a persisted per-user snapshot
# ═══════════════════════════════════════════════════════════════════════════════

def _render_what_changed(q, user_email, scope_label):
    """Compare the queue against the snapshot stored the last time this user
    looked. With a static extract nothing moves, and that is what it says."""
    sig = queue_signature(q)
    stored = state_get(user_email, "snapshot")
    previous = {k: v for k, v in stored.items() if k != "__meta__"}
    meta = stored.get("__meta__")

    changes = diff_snapshot(previous, sig, q)

    with st.expander("What changed", expanded=bool(changes)):
        if changes is None:
            st.caption("First time looking at this queue on this login — nothing to "
                       "compare against yet. The current state has been recorded, and "
                       "the next visit will diff against it.")
        elif not changes:
            backend = _state_backend()
            st.caption(
                f"Nothing has moved since you last opened this queue"
                + (f" ({meta})." if meta else ".")
                + " The dataset is a static extract, so this stays empty until new "
                  "data is loaded through the upload page."
                + ("" if backend == "db" else
                   " Snapshots are session-only on this instance — the database "
                   "would not accept the state table."))
        else:
            st.markdown(
                '<div class="desk-reveal" style="display:flex;gap:8px;flex-wrap:wrap;">'
                + "".join(
                    f'<span style="background:rgba(99,102,241,0.09);border:1px solid '
                    f'rgba(99,102,241,0.2);border-radius:9999px;padding:4px 12px;'
                    f'font-size:0.75rem;font-weight:600;color:var(--text-color,{PF_TEXT});">'
                    f'<b style="color:#6366F1;">{icon}</b> {text}</span>'
                    for icon, text in changes)
                + "</div>", unsafe_allow_html=True)
            st.caption(f"Since your previous visit{f' ({meta})' if meta else ''}, "
                       f"scope: {scope_label}.")

        if st.button("Record current state as the new baseline",
                     key="desk_wc_snap", help="Future visits diff against this."):
            state_put(user_email, "snapshot", "__meta__",
                      pd.Timestamp.now().strftime("%d %b %Y %H:%M"))
            for case, val in sig.items():
                state_put(user_email, "snapshot", case, val)
            for stale in set(previous) - set(sig):
                state_delete(user_email, "snapshot", stale)
            st.rerun()

    if previous == {} and sig:
        # Silently seed the first baseline so the next visit has something real.
        state_put(user_email, "snapshot", "__meta__",
                  pd.Timestamp.now().strftime("%d %b %Y %H:%M"))
        for case, val in sig.items():
            state_put(user_email, "snapshot", case, val)


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL SEARCH — case number / account / associate / symptom
# ═══════════════════════════════════════════════════════════════════════════════

def _render_global_search(cases_df, associates_df, accounts_df):
    term = st.text_input(
        "Search", key="desk_search", label_visibility="collapsed",
        placeholder="Jump to anything — case number, account, associate, or a symptom…")
    if not term or not term.strip():
        return
    t = term.strip().lower()

    hit_cases = cases_df[
        cases_df["case_number"].astype(str).str.contains(t, case=False, na=False)
        | cases_df["problem_statement"].astype(str).str.contains(t, case=False, na=False)
    ]
    hit_accts = accounts_df[
        accounts_df["account_name"].astype(str).str.contains(t, case=False, na=False)
        | accounts_df["account_id"].astype(str).str.contains(t, case=False, na=False)
    ]
    hit_assoc = associates_df[
        associates_df["associate_name"].astype(str).str.contains(t, case=False, na=False)
        | associates_df["email"].astype(str).str.contains(t, case=False, na=False)
    ]

    n = len(hit_cases) + len(hit_accts) + len(hit_assoc)
    if not n:
        st.caption(f"Nothing matches “{term}”.")
        return

    with st.container(border=True):
        st.caption(f"{n} match{'es' if n != 1 else ''} for “{term}”")
        if not hit_assoc.empty:
            st.markdown(f"**Associates ({len(hit_assoc)})**")
            st.dataframe(hit_assoc[[c for c in ("associate_id", "associate_name", "email",
                                                "sbr", "shift", "skill_level", "manager_name")
                                    if c in hit_assoc.columns]].head(8),
                         use_container_width=True, hide_index=True)
        if not hit_accts.empty:
            st.markdown(f"**Accounts ({len(hit_accts)})**")
            st.dataframe(hit_accts[[c for c in ("account_id", "account_name", "sector",
                                                "support_tier", "region", "tam_assigned")
                                    if c in hit_accts.columns]].head(8),
                         use_container_width=True, hide_index=True)
        if not hit_cases.empty:
            st.markdown(f"**Cases ({len(hit_cases)})**")
            st.dataframe(hit_cases[[c for c in ("case_number", "severity", "status",
                                                "account_name", "product_name",
                                                "case_owner", "problem_statement")
                                    if c in hit_cases.columns]].head(12),
                         use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — WORK QUEUE
# ═══════════════════════════════════════════════════════════════════════════════

#: One-click triage filters. Each is a plain predicate over the queue frame so
#: the label and the behaviour cannot drift apart.
QUICK_FILTERS = [
    ("🔥 Critical", "critical",
     lambda v, ctx: v[v["severity"].isin(SEV_ORDER[:2])],
     "Severity 1 and 2"),
    ("⚠ SLA risk", "sla",
     lambda v, ctx: v[v["sla_label"].isin(("At Risk", "Breached"))],
     "at or past target"),
    ("🚨 Escalated", "esc",
     lambda v, ctx: v[pd.to_numeric(v.get("escalated", 0), errors="coerce").fillna(0) == 1],
     "escalation flag set"),
    ("⏳ Aging", "aging",
     lambda v, ctx: v[v["stale_hours"] > 168],
     "no update for 7 days"),
    ("👤 Waiting", "wait",
     lambda v, ctx: v[v["status"].isin(WAITING_STATUSES)],
     "ball is with the customer"),
    ("⭐ High tier", "tier",
     lambda v, ctx: v[v["support_tier"].isin(("Premium Plus", "Premium"))],
     "Premium and Premium Plus accounts"),
    ("🛠 My products", "prod",
     lambda v, ctx: v[v["product_name"].isin(ctx.get("my_products", set()))],
     "products you have closed cases on"),
]


def _render_quick_filters(q, my_products):
    """Chip row. Returns the filtered frame and the active chip labels."""
    st.markdown(f'<div style="font-size:0.72rem;color:{PF_TEXT_SEC};font-weight:700;'
                f'text-transform:uppercase;letter-spacing:.05em;margin:2px 0 6px;">'
                f'What needs attention?</div>', unsafe_allow_html=True)

    ctx = {"my_products": my_products}
    counts = {key: len(fn(q, ctx)) for _, key, fn, _ in QUICK_FILTERS}
    by_option = {label: key for label, key, _, _ in QUICK_FILTERS}

    # The option values are the bare labels and the count goes through
    # format_func. If the count were baked into the option string, changing an
    # SLA target or the scope would rewrite every option and silently drop the
    # user's selection on the next run.
    picked = st.segmented_control(
        "Quick filters", list(by_option), selection_mode="multi",
        format_func=lambda o: f"{o} ({counts[by_option[o]]})",
        key="desk_chips", label_visibility="collapsed",
        help="Chips combine with AND. Counts are for the unfiltered queue.") or []

    active = [by_option[p] for p in picked]
    view = q
    for _, key, fn, _ in QUICK_FILTERS:
        if key in active:
            view = fn(view, ctx)

    if active:
        names = [f"{label} — {why}" for label, key, _, why in QUICK_FILTERS
                 if key in active]
        st.caption("Active filters: " + " · ".join(names))
    return view, active


def _render_queue(q, cases_df, accounts_df, skills_df, associates_df, ref,
                  scope_label, ai_fn=None, display_name="", ctx=None,
                  user_email="", role="associate"):
    ctx = ctx or action_context(cases_df)
    user_email = user_email or "anonymous"

    if q.empty:
        st.success(f"**Queue is clear.** Nothing is open in {scope_label.lower()}. "
                   f"Similar-case search and recurring patterns still work if you are "
                   f"researching something.", icon=":material/check_circle:")
        return

    with st.container(key="desk_handoff"):
        _render_handoff(q, ref, ai_fn, display_name, scope_label, cases_df)

    my_products = set(
        cases_df[cases_df["case_owner"].isin(q["case_owner"].unique())]
        ["product_name"].dropna().astype(str))
    with st.container(key="desk_filters"):
        view, active = _render_quick_filters(q, my_products)

    with st.expander("More filters", expanded=False):
        f1, f2, f3 = st.columns(3)
        with f1:
            sev_f = st.multiselect("Severity",
                                   [s for s in SEV_ORDER if s in set(q["severity"])],
                                   key="desk_q_sev")
        with f2:
            st_f = st.multiselect("Status", sorted(q["status"].dropna().unique()),
                                  key="desk_q_status")
        with f3:
            sla_f = st.multiselect("SLA state", ["Breached", "At Risk", "On Track"],
                                   key="desk_q_sla")
    if sev_f:
        view = view[view["severity"].isin(sev_f)]
    if st_f:
        view = view[view["status"].isin(st_f)]
    if sla_f:
        view = view[view["sla_label"].isin(sla_f)]

    if view.empty:
        st.info(f"**No cases match.** {len(q)} case{'s' if len(q) != 1 else ''} "
                f"{'are' if len(q) != 1 else 'is'} open in {scope_label.lower()}, but "
                f"none clears every active filter. Deselect a chip to widen the view.",
                icon=":material/filter_alt_off:")
        return

    _section(f"{len(view)} case{'s' if len(view) != 1 else ''} · ranked by priority",
             "Priority = severity + SLA pressure + time since last update + account tier "
             "+ escalation. Cases waiting on the customer are damped, never hidden. "
             "Every card carries a Recommended Next Action and the rule behind it.")

    # A slider needs min < max; short queues just render in full.
    hi = min(100, len(view))
    if hi > 5:
        show_n = st.slider("Cases to show", 5, hi, min(15, hi), key="desk_q_n")
    else:
        show_n = hi

    bookmarks = state_get(user_email, "bookmark")
    with st.container(key="desk_queue"):
        for i, (_, r) in enumerate(view.head(show_n).iterrows()):
            # The top card gets its own key so the guided tour can spotlight a
            # real case rather than a mock-up.
            box = st.container(key="desk_card_top") if i == 0 else st.container()
            with box:
                _render_case_card(r, cases_df, skills_df, associates_df, accounts_df,
                                  ref, ctx, user_email, role, bookmarks, i, ai_fn)

    csv = view.drop(columns=["sla_color"], errors="ignore").to_csv(index=False).encode()
    st.download_button("Export current queue (CSV)", csv,
                       file_name="my_desk_queue.csv", mime="text/csv",
                       key="desk_q_export",
                       help="Exports exactly the rows shown under the active filters.")


# ── Shift handoff brief ────────────────────────────────────────────────────────

#: call_ai() reports failure by returning one of these strings rather than
#: raising, so a naive truthiness check would render the error as the brief.
_AI_ERROR_MARKERS = (
    "could not connect to ai endpoint",
    "the ai took too long",
    "ai endpoint returned an error",
)


def _ai_failed(resp):
    if not resp or not str(resp).strip():
        return True
    low = str(resp).strip().lower()
    return any(low.startswith(m) for m in _AI_ERROR_MARKERS)


def _sanitize_html(text):
    """Strip active content — model output is rendered with unsafe_allow_html."""
    out = re.sub(r"<\s*(script|iframe|object|embed|style|link|meta)[^>]*>.*?</\s*\1\s*>",
                 "", str(text), flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"<\s*(script|iframe|object|embed|style|link|meta)[^>]*/?\s*>", "",
                 out, flags=re.IGNORECASE)
    out = re.sub(r"\bon\w+\s*=\s*[\"'][^\"']*[\"']", "", out, flags=re.IGNORECASE)
    out = re.sub(r"javascript\s*:", "", out, flags=re.IGNORECASE)
    return out


def _md_lite(text):
    """Minimal markdown -> HTML. Bold, bullets, paragraphs."""
    text = _sanitize_html(text)
    out = []
    for raw in str(text).splitlines():
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", raw.strip())
        line = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", line)
        if not line:
            continue
        if line.startswith(("- ", "* ", "• ")):
            out.append(f'<li style="margin:3px 0;">{line[2:].strip()}</li>')
        elif re.match(r"^\d+[.)]\s", line):
            out.append(f'<li style="margin:3px 0;">{re.sub(r"^\d+[.)]\s*", "", line)}</li>')
        else:
            out.append(f'<p style="margin:6px 0;">{line}</p>')
    html = "".join(out)
    return re.sub(r"(<li.*?</li>)+", lambda m: f'<ul style="margin:4px 0 4px 18px;padding:0;">{m.group(0)}</ul>',
                  html)


def _handoff_facts(q, ref, top_n=8):
    """Deterministic facts the brief is built from — also the AI's only input."""
    top = q.head(top_n)
    lines = []
    for _, r in top.iterrows():
        esc = " ESCALATED" if int(pd.to_numeric(r.get("escalated", 0), errors="coerce") or 0) == 1 else ""
        lines.append(
            f"- #{r['case_number']} | {r['severity']} | {r['status']}{esc} | "
            f"{r.get('account_name', '?')} ({r.get('support_tier', 'n/a')} tier) | "
            f"{r.get('product_name', '?')} {r.get('product_version', '')} | "
            f"age {_fmt_age(r['age_hours'])}, {r['sla_ratio']:.1f}x target, "
            f"last touched {_fmt_age(r['stale_hours'])} ago | {r['problem_statement']}")
    return "\n".join(lines)


def _local_brief(q, ref, display_name, scope_label, cases_df=None):
    """Fallback brief when no AI endpoint is reachable. Pure facts, no model.

    Section order follows the shift-handoff convention: what is on fire, what is
    about to be, what is parked, what is already hot, what needs chasing.
    """
    esc_flag = pd.to_numeric(q.get("escalated", 0), errors="coerce").fillna(0) == 1
    sev12 = q[q["severity"].isin(SEV_ORDER[:2]) & ~esc_flag
              & ~q["status"].isin(WAITING_STATUSES)]
    at_risk = q[q["sla_label"].isin(("At Risk", "Breached")) & ~esc_flag]
    waiting = q[q["status"].isin(WAITING_STATUSES)]
    esc = q[esc_flag]
    stale = q[(q["stale_hours"] > 168) & ~q["status"].isin(WAITING_STATUSES)]

    ctx = action_context(cases_df) if cases_df is not None else {}

    def line(r, extra=""):
        stmt = str(r["problem_statement"]).rstrip().rstrip(".")
        return (f"- #{r['case_number']} — {r.get('account_name', '?')} "
                f"({r.get('support_tier', 'tier n/a')}), "
                f"{r['severity'].split(' (')[0]}. {stmt}.{extra}")

    parts = [
        "SHIFT HANDOFF",
        f"**{display_name or scope_label} · queue as of {ref:%d %b %Y %H:%M}**",
        f"{len(q)} open: {len(sev12)} critical and unblocked, {len(esc)} escalated, "
        f"{len(at_risk)} at or past SLA target, {len(waiting)} waiting on the "
        f"customer, {len(stale)} untouched for over a week.",
    ]

    parts += ["", "**Critical**"]
    if sev12.empty:
        parts.append("- Nothing at Sev1/Sev2 that is not already escalated or parked.")
    for _, r in sev12.head(4).iterrows():
        parts.append(line(r, f" Currently {r['status'].lower()}, last touched "
                             f"{_fmt_age(r['stale_hours'])} ago."))

    parts += ["", "**SLA risk**"]
    if at_risk.empty:
        parts.append("- Every open case is inside its target.")
    for _, r in at_risk.head(4).iterrows():
        parts.append(line(r, f" {r['sla_ratio']:.1f}x the {r['sla_target']:.0f}h target."))

    parts += ["", "**Waiting on customer**"]
    if waiting.empty:
        parts.append("- Nothing parked on the customer.")
    for _, r in waiting.head(4).iterrows():
        parts.append(line(r, f" Silent for {_fmt_age(r['stale_hours'])}."))

    parts += ["", "**Escalations**"]
    if esc.empty:
        parts.append("- No case in this queue carries the escalation flag.")
    for _, r in esc.head(4).iterrows():
        parts.append(line(r, f" Open {_fmt_age(r['age_hours'])}."))

    parts += ["", "**Recommended follow-ups**"]
    if stale.empty and waiting.empty:
        parts.append("- Nothing is going stale. Work the priority order.")
    for _, r in stale.head(4).iterrows():
        action, _ = next_best_action(r, ctx.get("specialist_products", ()),
                                     ctx.get("repeat_products", ()))
        parts.append(f"- #{r['case_number']} ({r.get('account_name', '?')}) — "
                     f"{action.lower()}; no update logged for "
                     f"{_fmt_age(r['stale_hours'])}.")

    parts += ["", "Every line above is read from the case extract. Nothing is "
                  "inferred, and no field absent from the data is filled in."]
    return "\n".join(parts)


def _render_handoff(q, ref, ai_fn, display_name, scope_label, cases_df=None):
    c1, c2 = st.columns([1.2, 4])
    with c1:
        clicked = st.button("Generate handoff brief", key="desk_handoff_btn",
                            type="primary", use_container_width=True,
                            help="Summarise this queue for the incoming shift.")
    with c2:
        st.caption("Shift change? Generate a brief covering what is hot, what is "
                   "blocked, and what the next engineer should pick up first.")

    if clicked:
        brief, source = None, "local"
        if ai_fn is not None:
            prompt = (
                "You are writing a support shift handoff note for the engineer taking "
                "over. Use ONLY the case facts below. Never invent case numbers, "
                "customers, timestamps, root causes, log contents, customer "
                "statements or actions. If a section has no matching cases, write "
                "'None in this queue.' — do not pad it.\n\n"
                f"Engineer: {display_name or scope_label}\n"
                f"Queue: {len(q)} open cases. Reference time {ref:%Y-%m-%d %H:%M}.\n\n"
                f"Top cases by priority:\n{_handoff_facts(q, ref)}\n\n"
                "Write under 220 words. Use exactly these bold section headings, in "
                "this order: **Critical**, **SLA risk**, **Waiting on customer**, "
                "**Escalations**, **Recommended follow-ups**. Under each, one bullet "
                "per case in the form '- #CASE — account, what it is, why it matters'. "
                "Be terse and specific."
            )
            try:
                with st.spinner("Writing the handoff brief…"):
                    resp = ai_fn([{"role": "user", "content": prompt}], 620)
                if not _ai_failed(resp):
                    brief, source = str(resp).strip(), "ai"
            except Exception:
                brief = None
        if brief is None:
            brief = _local_brief(q, ref, display_name, scope_label, cases_df)
        st.session_state["desk_handoff_text"] = brief
        st.session_state["desk_handoff_src"] = source

    if st.session_state.get("desk_handoff_text"):
        src = st.session_state.get("desk_handoff_src", "local")
        badge = (_pill("AI generated", "#6366F1", solid=True) if src == "ai"
                 else _pill("Generated locally — no AI endpoint", RH_GRAY))
        st.markdown(_html(f"""<div style="background:linear-gradient(135deg,rgba(99,102,241,0.05),
            rgba(139,92,246,0.03));border:1.5px solid rgba(99,102,241,0.18);
            border-radius:14px;padding:16px 20px;margin:4px 0 14px;">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
                <span style="font-weight:800;font-size:0.9rem;color:var(--text-color,{PF_TEXT});">
                    Shift Handoff Brief</span>{badge}</div>
            <div style="font-size:0.82rem;line-height:1.6;color:var(--text-color,{PF_TEXT});">
                {_md_lite(st.session_state['desk_handoff_text'])}</div>
        </div>"""), unsafe_allow_html=True)
        st.download_button("Copy as text", st.session_state["desk_handoff_text"],
                           file_name="shift_handoff.txt", mime="text/plain",
                           key="desk_handoff_dl")


def _render_case_card(r, cases_df, skills_df, associates_df, accounts_df, ref,
                      ctx, user_email, role, bookmarks, idx=0, ai_fn=None):
    sev_c = SEVERITY_COLORS.get(r["severity"], RH_GRAY)
    stat_c = STATUS_COLORS.get(r["status"], RH_GRAY)
    tier = r.get("support_tier")
    pri = r["priority"]
    pri_c = RH_RED if pri >= 70 else (RH_GOLD if pri >= 45 else RH_TEAL)

    pills = [_pill(r["severity"].replace("Severity ", "S").replace(" (", " ").rstrip(")"), sev_c, solid=True),
             _pill(r["status"], stat_c)]
    if pd.notna(tier):
        pills.append(_pill(tier, TIER_COLORS.get(tier, RH_GRAY)))
    if int(pd.to_numeric(r.get("escalated", 0), errors="coerce") or 0) == 1:
        pills.append(_pill("ESCALATED", RH_PURPLE, solid=True))
    if int(pd.to_numeric(r.get("sovereign_support", 0), errors="coerce") or 0) == 1:
        pills.append(_pill("Sovereign", "#6366F1"))
    if r.get("business_hours") == "Follow-the-Sun":
        pills.append(_pill("Follow-the-Sun", RH_TEAL))

    if str(r["case_number"]) in bookmarks:
        pills.append(_pill("★ FOLLOWING", RH_GOLD, solid=True))

    ratio = r["sla_ratio"]
    sla_txt = (f"{r['sla_label']} · {ratio:.1f}x target"
               if pd.notna(ratio) else r["sla_label"])
    bar_pct = min(ratio / 2.0 * 100, 100) if pd.notna(ratio) else 0

    action, reason = next_best_action(
        r, ctx.get("specialist_products", ()), ctx.get("repeat_products", ()))
    nba = _html(f"""<div style="margin-top:11px;padding:9px 12px;border-radius:9px;
        background:rgba(99,102,241,0.06);border-left:3px solid #6366F1;">
        <div style="font-size:0.6rem;color:{PF_TEXT_SEC};text-transform:uppercase;
            font-weight:700;letter-spacing:.05em;">Recommended next action</div>
        <div style="font-size:0.82rem;font-weight:700;margin-top:2px;
            color:var(--text-color,{PF_TEXT});">→ {action}</div>
        <div style="font-size:0.7rem;color:{PF_TEXT_SEC};margin-top:3px;">{reason}</div>
    </div>""")

    st.markdown(_html(f"""<div class="desk-card" style="{_stagger(idx)}
        background:var(--secondary-background-color,{PF_SURFACE});
        border:1px solid var(--border-color,{PF_BORDER});border-left:4px solid {pri_c};
        border-radius:12px;padding:14px 18px;margin-bottom:8px;">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:14px;">
            <div style="min-width:0;flex:1;">
                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px;">
                    <span style="font-weight:800;font-size:0.9rem;color:var(--text-color,{PF_TEXT});">
                        #{r['case_number']}</span>
                    {"".join(pills)}
                </div>
                <div style="font-size:0.85rem;color:var(--text-color,{PF_TEXT});line-height:1.45;
                    margin-bottom:6px;">{r.get('problem_statement', '')}</div>
                <div style="font-size:0.72rem;color:{PF_TEXT_SEC};">
                    {r.get('account_name', '—')} &nbsp;·&nbsp; {r.get('product_name', '—')}
                    {r.get('product_version', '')} &nbsp;·&nbsp; {r.get('sbr', '—')}
                    &nbsp;·&nbsp; owner: {r.get('case_owner', '—')}
                </div>
            </div>
            <div style="text-align:right;flex-shrink:0;">
                <div style="font-size:1.35rem;font-weight:800;color:{pri_c};line-height:1;">{pri:.0f}</div>
                <div style="font-size:0.6rem;color:{PF_TEXT_SEC};text-transform:uppercase;
                    font-weight:700;letter-spacing:.05em;">priority</div>
            </div>
        </div>
        <div style="display:flex;gap:18px;align-items:center;margin-top:10px;flex-wrap:wrap;">
            <div style="flex:1;min-width:160px;">
                <div style="height:5px;background:{PF_BORDER};border-radius:9999px;overflow:hidden;">
                    <div class="desk-sla-fill" style="height:100%;width:{bar_pct:.0f}%;
                        background:{r['sla_color']};border-radius:9999px;"></div></div>
                <div style="font-size:0.66rem;color:{r['sla_color']};font-weight:700;margin-top:3px;">
                    {sla_txt}</div>
            </div>
            <div style="font-size:0.7rem;color:{PF_TEXT_SEC};">
                Age <b style="color:var(--text-color,{PF_TEXT});">{_fmt_age(r['age_hours'])}</b>
                &nbsp;·&nbsp; Target {r['sla_target']:.0f}h
                &nbsp;·&nbsp; Last update <b style="color:var(--text-color,{PF_TEXT});">{_fmt_age(r['stale_hours'])}</b> ago
            </div>
        </div>
        {nba}
    </div>"""), unsafe_allow_html=True)

    with st.expander(f"Open case #{r['case_number']} — context, timeline, actions",
                     expanded=False):
        box = st.container(key="desk_detail_top") if idx == 0 else st.container()
        with box:
            _render_case_detail(r, cases_df, skills_df, associates_df, accounts_df,
                                ref, user_email, role, bookmarks, ai_fn, action,
                                reason, idx)


# ── Case detail / action center ────────────────────────────────────────────────

def _render_case_detail(r, cases_df, skills_df, associates_df, accounts_df, ref,
                        user_email, role, bookmarks, ai_fn, action, reason, idx=0):
    cn = str(r["case_number"])
    _render_customer_strip(r, cases_df, ref)
    box = st.container(key="desk_actions_top") if idx == 0 else st.container()
    with box:
        _render_case_actions(r, cases_df, user_email, role, bookmarks, action, reason)

    d1, d2, d3, d4, d5 = st.tabs(
        ["Timeline", "Similar cases", "Potential SMEs", "Escalation readiness",
         "Private notes"])
    with d1:
        _render_timeline(r, ref)
        st.markdown(
            f'<div style="font-size:0.78rem;color:{PF_TEXT_SEC};margin-top:12px;">'
            f'<b style="color:var(--text-color,{PF_TEXT});">Case description</b><br>'
            f'{r.get("description", "—")}</div>', unsafe_allow_html=True)
    with d2:
        _render_case_similar(r, cases_df, associates_df)
    with d3:
        _render_case_smes(r, cases_df, associates_df, skills_df)
    with d4:
        _render_readiness(r, cases_df)
    with d5:
        _render_notes(cn, user_email)

    st.divider()
    _render_case_brief(r, cases_df, associates_df, skills_df, ref, ai_fn)


def _render_customer_strip(r, cases_df, ref):
    """Compact account context. Deliberately not a copy of app1 — the link
    below goes there for the full customer picture."""
    acct_id = r.get("account_id")
    acct_cases = cases_df[cases_df["account_id"] == acct_id]
    open_n = int((~acct_cases["status"].isin(CLOSED_STATUSES)).sum())
    esc_n = int(pd.to_numeric(acct_cases.get("escalated", 0), errors="coerce").fillna(0).sum())
    csat = pd.to_numeric(acct_cases.get("csat_score"), errors="coerce").mean()
    level, lc, factors = account_risk(acct_id, cases_df)

    contract_end = pd.to_datetime(r.get("contract_end_date"), errors="coerce")
    renew = "—"
    if pd.notna(contract_end):
        days = (contract_end - ref).days
        rc = RH_RED if days < 90 else (RH_GOLD if days < 180 else RH_GREEN)
        renew = (f'<b style="color:{rc};">{contract_end:%d %b %Y}</b> ({days:+d}d)')

    def cell(label, value):
        return (f'<div style="min-width:118px;"><div style="font-size:0.58rem;'
                f'color:{PF_TEXT_SEC};text-transform:uppercase;font-weight:700;'
                f'letter-spacing:.05em;">{label}</div><div style="font-size:0.8rem;'
                f'color:var(--text-color,{PF_TEXT});font-weight:600;">{value}</div></div>')

    st.markdown(_html(f"""<div style="background:var(--secondary-background-color,{PF_SURFACE});
        border:1px solid var(--border-color,{PF_BORDER});border-left:4px solid {lc};
        border-radius:12px;padding:12px 16px;margin-bottom:10px;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:9px;flex-wrap:wrap;">
            <span style="font-weight:800;font-size:0.92rem;color:var(--text-color,{PF_TEXT});">
                {r.get('account_name', '—')}</span>
            {_pill(level, lc, solid=True)}
            {_pill(str(r.get('support_tier') or 'tier unknown'),
                   TIER_COLORS.get(r.get('support_tier'), RH_GRAY))}
        </div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;">
            {cell('Account ID', r.get('account_id', '—'))}
            {cell('TAM', r.get('tam_assigned') if pd.notna(r.get('tam_assigned')) else 'None assigned')}
            {cell('Region', r.get('region', '—'))}
            {cell('HQ', r.get('hq_location', '—'))}
            {cell('Revenue segment', r.get('revenue_segment', '—'))}
            {cell('Contract ends', renew)}
            {cell('Open cases', open_n)}
            {cell('Escalations', esc_n)}
            {cell('Historical CSAT', f'{csat:.2f}/5' if pd.notna(csat) else 'none recorded')}
        </div>
    </div>"""), unsafe_allow_html=True)

    st.caption("Customer context — " + "; ".join(factors) +
               f". Rated **{level}** from those four measured conditions only.")
    # Hand the JWT across the way the workspace switcher already does, and deep
    # link to this case's account via ?view= — app1 reads both on load. Without
    # the token the hop lands on the login page instead of the account.
    acct = r.get("account_id")
    url = build_switch_url("customer", st.session_state.get("jwt_token", ""))
    if pd.notna(acct) and str(acct).strip():
        url += f"&view={quote(str(acct))}"
    st.markdown(
        f'<a href="{url}" target="_self" '
        f'style="font-size:0.76rem;font-weight:700;color:#6366F1;'
        f'text-decoration:none;">View {r.get("account_name", "customer")} in '
        f'Customer Intelligence →</a>',
        unsafe_allow_html=True)


#: Actions that would write to the case-management system. The dataset is a
#: read-only analytics extract with no case-management backend behind it, so
#: these are rendered disabled with the reason stated rather than faked.
_UNAVAILABLE_ACTIONS = [
    ("Open in case system", "no case-management URL or ID mapping in the dataset"),
    ("Update status", "would write to support_cases, the analytics source of record"),
    ("Assign / reassign", "no ownership-write endpoint exists"),
    ("Escalate", "escalation is a workflow in the case system, not a column to set"),
    ("Mark waiting on customer", "same write path as Update status"),
    ("Request information", "needs an outbound customer-comms integration"),
]


def _render_case_actions(r, cases_df, user_email, role, bookmarks, action, reason):
    cn = str(r["case_number"])
    st.markdown(f'<div style="font-size:0.62rem;color:{PF_TEXT_SEC};'
                f'text-transform:uppercase;font-weight:700;letter-spacing:.05em;'
                f'margin-bottom:5px;">Action center</div>', unsafe_allow_html=True)

    a1, a2, a3 = st.columns(3)
    following = cn in bookmarks
    with a1:
        if st.button("★ Unfollow" if following else "☆ Follow case",
                     key=f"desk_bm_{cn}", use_container_width=True,
                     help="Adds the case to My Follow-ups. Private to your login."):
            if following:
                state_delete(user_email, "bookmark", cn)
            else:
                state_put(user_email, "bookmark", cn, reason)
            st.rerun()
    with a2:
        summary = _case_summary_text(r, cases_df, action, reason)
        st.download_button("Export case summary", summary,
                           file_name=f"case_{cn}_summary.txt", mime="text/plain",
                           key=f"desk_exp_{cn}", use_container_width=True)
    with a3:
        st.download_button(
            "Export account history (CSV)",
            cases_df[cases_df["account_id"] == r.get("account_id")].to_csv(index=False).encode(),
            file_name=f"account_{r.get('account_id')}_cases.csv", mime="text/csv",
            key=f"desk_expacct_{cn}", use_container_width=True)

    with st.popover("Actions needing case-system access", use_container_width=False):
        st.caption("This dashboard reads a static analytics extract. These actions "
                   "would change the source of record, so they are disabled rather "
                   "than simulated — a green button that does nothing is worse than "
                   "no button.")
        for label, why in _UNAVAILABLE_ACTIONS:
            st.button(label, key=f"desk_na_{cn}_{label[:9]}", disabled=True,
                      use_container_width=True, help=why)
            st.caption(why)


def _case_summary_text(r, cases_df, action, reason):
    """Deterministic plain-text case summary — no model involved."""
    rd = escalation_readiness(r, cases_df)
    lines = [
        f"CASE #{r['case_number']}",
        "=" * 46,
        f"Account        : {r.get('account_name', '—')} ({r.get('account_id', '—')})",
        f"Support tier   : {r.get('support_tier', '—')}",
        f"Product        : {r.get('product_name', '—')} {r.get('product_version', '')}",
        f"Severity       : {r.get('severity', '—')}",
        f"Status         : {r.get('status', '—')}",
        f"SBR            : {r.get('sbr', '—')}",
        f"Owner          : {r.get('case_owner', '—')}",
        f"Created        : {pd.to_datetime(r.get('creation_date'), errors='coerce')}",
        f"Last updated   : {pd.to_datetime(r.get('last_updated'), errors='coerce')}",
        f"Age            : {_fmt_age(r.get('age_hours'))}"
        f"  ({r.get('sla_ratio', float('nan')):.1f}x the {r.get('sla_target', 0):.0f}h target)",
        f"Escalated      : {'yes' if int(pd.to_numeric(r.get('escalated', 0), errors='coerce') or 0) else 'no'}",
        "",
        "PROBLEM",
        str(r.get("problem_statement", "—")),
        "",
        "DESCRIPTION",
        str(r.get("description", "—")),
        "",
        f"RECOMMENDED NEXT ACTION",
        f"-> {action}",
        f"   Why: {reason}",
        "",
        f"ESCALATION READINESS: {rd['passed']}/{rd['total']}",
    ]
    for label, ok, detail in rd["items"]:
        lines.append(f"  [{'x' if ok else ' '}] {label} — {detail}")
    lines += ["", "NOT AVAILABLE IN THIS DATASET"]
    lines += [f"  - {u}" for u in rd["unavailable"]]
    lines += ["", "Generated by My Desk from the case extract. No field above is "
                  "inferred or generated."]
    return "\n".join(lines)


def _render_timeline(r, ref):
    events = case_timeline(r, ref)
    rows = ""
    for label, ts, note, color in events:
        when = f"{ts:%d %b %Y, %H:%M}" if ts is not None and pd.notna(ts) else "—"
        dot_fill = color if (ts is not None and pd.notna(ts)) else "transparent"
        rows += _html(f"""<div style="display:flex;gap:12px;align-items:flex-start;
            padding-bottom:14px;position:relative;">
            <div style="width:11px;height:11px;border-radius:50%;background:{dot_fill};
                border:2px solid {color};flex-shrink:0;margin-top:3px;z-index:1;"></div>
            <div style="flex:1;min-width:0;">
                <div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;">
                    <span style="font-size:0.82rem;font-weight:700;
                        color:var(--text-color,{PF_TEXT});">{label}</span>
                    <span style="font-size:0.74rem;color:{color};font-weight:600;">{when}</span>
                </div>
                <div style="font-size:0.7rem;color:{PF_TEXT_SEC};">{note}</div>
            </div>
        </div>""")

    st.markdown(_html(f"""<div style="position:relative;padding-left:5px;margin-top:4px;">
        <div class="desk-tl-rail" style="position:absolute;left:10px;top:6px;bottom:18px;
            width:2px;background:{PF_BORDER};transform-origin:top center;"></div>
        {rows}
    </div>"""), unsafe_allow_html=True)
    st.caption("Only milestones the dataset records are shown. First response, "
               "individual updates and customer replies are not captured by the "
               "source extract, so they are marked missing rather than estimated.")


def _render_case_similar(r, cases_df, associates_df):
    stmt = str(r.get("problem_statement") or "")
    hist = cases_df[cases_df["status"].isin(CLOSED_STATUSES)].reset_index(drop=True)
    if hist.empty or not stmt.strip():
        st.info("No resolved cases to compare against.")
        return
    with st.spinner("Finding similar cases…"):
        docs = tuple(f"{p} {p} {d}" for p, d in zip(
            hist["problem_statement"].fillna("").astype(str),
            hist.get("description", pd.Series("", index=hist.index)).fillna("").astype(str)))
        hits = search_similar(f"{stmt} {r.get('product_name', '')}", docs, top_k=5)
    if not hits:
        st.info("**No close historical match.** Nothing in the resolved set scores "
                "above the similarity floor for this symptom — this one may be new.")
        return

    ttrs = [hist.iloc[i]["time_to_resolve_hours"] for i, _ in hits]
    ttrs = [t for t in ttrs if pd.notna(t)]
    st.caption(f"{len(hits)} resolved case{'s' if len(hits) != 1 else ''} above the "
               f"similarity floor"
               + (f" · median resolve {pd.Series(ttrs).median():.0f}h" if ttrs else ""))

    for i, score in hits:
        m = hist.iloc[i]
        esc = int(pd.to_numeric(m.get("escalated", 0), errors="coerce") or 0) == 1
        ttr = f"{m['time_to_resolve_hours']:.0f}h" if pd.notna(m["time_to_resolve_hours"]) else "—"
        csat = f"{m['csat_score']:.0f}/5" if pd.notna(m.get("csat_score")) else "—"
        a = associates_df[associates_df["associate_name"] == m.get("case_owner")]
        shift = a.iloc[0]["shift"] if not a.empty else "—"
        st.markdown(_html(f"""<div style="border:1px solid var(--border-color,{PF_BORDER});
            border-left:3px solid {RH_TEAL};border-radius:10px;padding:9px 13px;
            margin-bottom:6px;">
            <div style="display:flex;justify-content:space-between;gap:10px;">
                <span style="font-size:0.8rem;font-weight:700;
                    color:var(--text-color,{PF_TEXT});">#{m['case_number']}</span>
                <span style="font-size:0.78rem;font-weight:800;color:{RH_TEAL};">
                    {score * 100:.0f}% match</span>
            </div>
            <div style="font-size:0.78rem;color:var(--text-color,{PF_TEXT});
                margin-top:2px;">{m['problem_statement']}</div>
            <div style="font-size:0.7rem;color:{PF_TEXT_SEC};margin-top:3px;">
                {m.get('product_name', '—')} {m.get('product_version', '')} ·
                {m.get('severity', '—')} · took {ttr} ·
                {'escalated' if esc else 'no escalation'} · CSAT {csat} ·
                closed by {m.get('case_owner', '—')} ({m.get('sbr', '—')}, {shift})
            </div>
        </div>"""), unsafe_allow_html=True)

    with st.expander("How these may help", expanded=False):
        esc_rate = sum(int(pd.to_numeric(hist.iloc[i].get("escalated", 0),
                                         errors="coerce") or 0) for i, _ in hits) / len(hits)
        st.markdown(
            f"- Median time to resolve across these matches: "
            f"**{pd.Series(ttrs).median():.0f}h**" if ttrs else
            "- No resolve times recorded on the matches.")
        st.markdown(f"- {esc_rate * 100:.0f}% of them escalated before closing.")
        st.markdown(f"- Engineers who closed them: "
                    f"**{', '.join(sorted({str(hist.iloc[i]['case_owner']) for i, _ in hits}))}**")
        st.caption("Summarised from the matched case rows only — resolution notes are "
                   "not stored in this dataset, so no fix steps can be quoted.")

    st.download_button(
        "Export similar cases (CSV)",
        hist.iloc[[i for i, _ in hits]].assign(
            similarity=[round(s, 4) for _, s in hits]).to_csv(index=False).encode(),
        file_name=f"case_{r['case_number']}_similar.csv", mime="text/csv",
        key=f"desk_simexp_{r['case_number']}")


def _render_case_smes(r, cases_df, associates_df, skills_df):
    with st.spinner("Finding potential SMEs…"):
        smes = find_smes(r, cases_df, associates_df, skills_df,
                         exclude=r.get("case_owner"))
    if smes.empty:
        st.info(f"**No other engineer has closed a {r.get('product_name')} case** in "
                f"this dataset, so there is no documented expertise to point at. The "
                f"SBR owning this work is {r.get('sbr', '—')}.")
        return

    for _, e in smes.iterrows():
        st.markdown(_html(f"""<div style="border:1px solid var(--border-color,{PF_BORDER});
            border-left:3px solid #6366F1;border-radius:10px;padding:10px 14px;
            margin-bottom:6px;">
            <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;">
                <span style="font-size:0.85rem;font-weight:800;
                    color:var(--text-color,{PF_TEXT});">{e['associate']}</span>
                <span style="font-size:0.7rem;color:{PF_TEXT_SEC};">
                    match score {e['match_score']}</span>
            </div>
            <div style="font-size:0.72rem;color:{PF_TEXT_SEC};margin-top:3px;">
                {e['sbr']} · shift on record: {e['shift_on_record']} ·
                relevant skill: <b style="color:var(--text-color,{PF_TEXT});">
                {e['relevant_skill']}</b>
            </div>
            <div style="font-size:0.72rem;color:{PF_TEXT_SEC};margin-top:2px;">
                {e['matching_cases']} matching case(s) ·
                {e['cases_resolved']} resolved overall ·
                avg {e['avg_resolve_hours'] if pd.notna(e['avg_resolve_hours']) else '—'}h ·
                CSAT {e['avg_csat'] if pd.notna(e['avg_csat']) else '—'}
            </div>
            <div style="font-size:0.7rem;color:#6366F1;margin-top:4px;">
                Why: {e['why']}</div>
        </div>"""), unsafe_allow_html=True)

    st.caption("Ranked on documented history: cases closed on this exact symptom, "
               "this product and version, same SBR, and matching ranked skills. "
               "**Shift is the pattern on record, not a presence signal** — the "
               "dataset has no rota, so nobody here is confirmed available now.")


def _render_readiness(r, cases_df):
    rd = escalation_readiness(r, cases_df)
    pct = rd["passed"] / rd["total"] * 100 if rd["total"] else 0
    col = RH_GREEN if pct >= 80 else (RH_GOLD if pct >= 55 else RH_RED)

    st.markdown(_html(f"""<div style="display:flex;align-items:center;gap:14px;
        margin-bottom:10px;">
        <div style="font-size:1.6rem;font-weight:800;color:{col};line-height:1;">
            {rd['passed']}/{rd['total']}</div>
        <div style="flex:1;">
            <div style="font-size:0.78rem;font-weight:700;
                color:var(--text-color,{PF_TEXT});">Escalation readiness</div>
            <div style="height:6px;background:{PF_BORDER};border-radius:9999px;
                overflow:hidden;margin-top:4px;">
                <div class="desk-sla-fill" style="height:100%;width:{pct:.0f}%;
                    background:{col};border-radius:9999px;"></div></div>
        </div>
    </div>"""), unsafe_allow_html=True)

    for label, ok, detail in rd["items"]:
        mark = "✓" if ok else "✗"
        c = RH_GREEN if ok else RH_RED
        st.markdown(_html(f"""<div style="display:flex;gap:9px;padding:3px 0;
            font-size:0.78rem;">
            <span style="color:{c};font-weight:800;">{mark}</span>
            <span style="color:var(--text-color,{PF_TEXT});min-width:210px;">{label}</span>
            <span style="color:{PF_TEXT_SEC};flex:1;">{detail}</span>
        </div>"""), unsafe_allow_html=True)

    st.markdown(f'<div style="font-size:0.72rem;color:{PF_TEXT_SEC};margin-top:10px;">'
                f'<b>Not available in current dataset</b> — excluded from the score '
                f'rather than counted as a failure:<br>'
                + "<br>".join(f"· {u}" for u in rd["unavailable"]) + "</div>",
                unsafe_allow_html=True)
    st.caption("The five text checks search the case description for an explicit "
               "statement. A ✗ means the description does not say it, not that the "
               "information does not exist somewhere else.")


def _render_notes(case_number, user_email):
    notes = state_get(user_email, "note")
    existing = notes.get(case_number, "")
    backend = _state_backend()

    st.markdown(_html(f"""<div style="display:flex;gap:8px;align-items:center;
        margin-bottom:6px;">
        {_pill("PRIVATE NOTE", RH_PURPLE, solid=True)}
        <span style="font-size:0.72rem;color:{PF_TEXT_SEC};">Visible only to
            {user_email}. Never written to the case record or shown to the customer.</span>
    </div>"""), unsafe_allow_html=True)

    txt = st.text_area("Note", value=existing, height=110,
                       key=f"desk_note_{case_number}", label_visibility="collapsed",
                       placeholder="Waiting for customer logs. Check upgrade docs. "
                                   "Discuss with SME next shift…")
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Save note", key=f"desk_notesave_{case_number}",
                     use_container_width=True):
            if txt.strip():
                state_put(user_email, "note", case_number, txt.strip())
            else:
                state_delete(user_email, "note", case_number)
            st.rerun()
    with c2:
        if existing and st.button("Delete note", key=f"desk_notedel_{case_number}",
                                  use_container_width=True):
            state_delete(user_email, "note", case_number)
            st.rerun()

    st.caption("Saved to the database for this login."
               if backend == "db" else
               "**Session-only** — the database would not accept the notes table on "
               "this instance, so this note is lost when the session ends.")


# ── AI case brief ──────────────────────────────────────────────────────────────

def _local_case_brief(r, cases_df, associates_df, skills_df, ref):
    """Deterministic brief. Every line is a field read, never a generation."""
    stmt = str(r.get("problem_statement") or "—").rstrip().rstrip(".")
    acct_cases = cases_df[cases_df["account_id"] == r.get("account_id")]
    esc_n = int(pd.to_numeric(acct_cases.get("escalated", 0), errors="coerce").fillna(0).sum())
    patterns = recurring_patterns(cases_df, min_cases=3,
                                  product=r.get("product_name"),
                                  statement=r.get("problem_statement"))
    smes = find_smes(r, cases_df, associates_df, skills_df, top_k=1,
                     exclude=r.get("case_owner"))
    action, reason = next_best_action(r, (), ())

    sim_line = "Not available in current case data."
    if not patterns.empty:
        p = patterns.iloc[0]
        sim_line = (f"{int(p['cases'])} closed cases share this exact problem "
                    f"statement on {p['product_name']}, across "
                    f"{int(p['accounts'])} accounts. Average resolve "
                    f"{p['avg_resolve_hours']:.0f}h, {p['escalation_rate']:.0f}% "
                    f"of them escalated.")
    sme_line = ("Not available in current case data."
                if smes.empty else
                f"{smes.iloc[0]['associate']} ({smes.iloc[0]['sbr']}, shift on record "
                f"{smes.iloc[0]['shift_on_record']}) — {smes.iloc[0]['why']}.")

    return "\n".join([
        f"**Customer:** {r.get('account_name', '—')} · "
        f"{r.get('support_tier', 'tier unknown')} tier · "
        f"TAM {r.get('tam_assigned') if pd.notna(r.get('tam_assigned')) else 'none assigned'}",
        f"**Problem:** {stmt}.",
        f"**Product:** {r.get('product_name', '—')} {r.get('product_version', '')}",
        f"**Severity:** {r.get('severity', '—')}",
        f"**Current status:** {r.get('status', '—')}, owned by "
        f"{r.get('case_owner', '—')}, last updated "
        f"{_fmt_age(r.get('stale_hours'))} ago.",
        f"**SLA:** {_fmt_age(r.get('age_hours'))} old against a "
        f"{r.get('sla_target', 0):.0f}h target — {r.get('sla_label', '—')} at "
        f"{r.get('sla_ratio', float('nan')):.1f}x.",
        f"**Relevant history:** {len(acct_cases)} cases on this account, "
        f"{esc_n} escalation{'s' if esc_n != 1 else ''} on record.",
        f"**Similar cases:** {sim_line}",
        f"**Potential SME:** {sme_line}",
        f"**Recommended next step:** {action} — {reason}",
    ])


def _render_case_brief(r, cases_df, associates_df, skills_df, ref, ai_fn):
    cn = str(r["case_number"])
    key = f"desk_brief_{cn}"
    c1, c2 = st.columns([1.3, 4])
    with c1:
        clicked = st.button("Generate case brief", key=f"{key}_btn", type="primary",
                            use_container_width=True)
    with c2:
        st.caption("One-paragraph technical and business context for this case, built "
                   "from the case and account rows. Falls back to a deterministic "
                   "summary when no AI endpoint answers.")

    if clicked:
        local = _local_case_brief(r, cases_df, associates_df, skills_df, ref)
        brief, source = local, "local"
        if ai_fn is not None:
            with st.spinner("Analyzing case…"):
                prompt = (
                    "Rewrite the support case brief below into tight prose for the "
                    "engineer picking it up. Use ONLY the facts given. Never invent "
                    "logs, root causes, customer statements, timestamps, engineer "
                    "availability or resolution steps. If a line says 'Not available "
                    "in current case data', keep that wording. Keep every heading.\n\n"
                    + local)
                try:
                    resp = ai_fn([{"role": "user", "content": prompt}], 600)
                    if not _ai_failed(resp):
                        brief, source = str(resp).strip(), "ai"
                except Exception:
                    pass
        st.session_state[key] = brief
        st.session_state[f"{key}_src"] = source

    if st.session_state.get(key):
        src = st.session_state.get(f"{key}_src", "local")
        badge = (_pill("AI generated", "#6366F1", solid=True) if src == "ai"
                 else _pill("Generated locally — no AI endpoint", RH_GRAY))
        st.markdown(_html(f"""<div class="desk-reveal" style="background:
            rgba(99,102,241,0.04);border:1.5px solid rgba(99,102,241,0.16);
            border-radius:12px;padding:14px 18px;margin-top:8px;">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
                <span style="font-weight:800;font-size:0.85rem;
                    color:var(--text-color,{PF_TEXT});">Case Brief</span>{badge}</div>
            <div style="font-size:0.81rem;line-height:1.6;
                color:var(--text-color,{PF_TEXT});">
                {_md_lite(st.session_state[key])}</div>
        </div>"""), unsafe_allow_html=True)
        st.download_button("Download brief", st.session_state[key],
                           file_name=f"case_{cn}_brief.txt", mime="text/plain",
                           key=f"{key}_dl")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB — MY FOLLOW-UPS
# ═══════════════════════════════════════════════════════════════════════════════

def _render_followups(cases_df, accounts_df, ref, sla, user_email, ctx):
    _section("My follow-ups",
             "Cases you starred. Kept separate from the queue so something can stay "
             "on your radar even after it drops out of the top of the ranking.")

    marks = state_get(user_email, "bookmark")
    notes = state_get(user_email, "note")
    if not marks:
        st.info("**Nothing followed yet.** Open any case in the Work Queue and use "
                "**☆ Follow case** in its action center. Followed cases collect here "
                "with their SLA state and recommended next action, whether or not "
                "they are still near the top of your queue.",
                icon=":material/star:")
        return

    all_q = build_queue(cases_df, accounts_df, owners=None, ref=ref, sla_hours=sla)
    followed = all_q[all_q["case_number"].astype(str).isin(marks.keys())]
    missing = set(marks) - set(followed["case_number"].astype(str))

    st.caption(f"{len(followed)} open · {len(missing)} no longer open. "
               + ("Stored in the database for this login."
                  if _state_backend() == "db" else
                  "**Session-only** on this instance — the database would not accept "
                  "the state table."))

    for i, (_, r) in enumerate(followed.sort_values("priority", ascending=False).iterrows()):
        cn = str(r["case_number"])
        action, reason = next_best_action(
            r, ctx.get("specialist_products", ()), ctx.get("repeat_products", ()))
        note = notes.get(cn, "")
        c1, c2 = st.columns([6, 1])
        with c1:
            st.markdown(_html(f"""<div class="desk-card" style="{_stagger(i)}
                border:1px solid var(--border-color,{PF_BORDER});
                border-left:4px solid {r['sla_color']};border-radius:11px;
                padding:11px 15px;margin-bottom:6px;">
                <div style="display:flex;gap:9px;align-items:center;flex-wrap:wrap;">
                    <span style="font-weight:800;font-size:0.85rem;
                        color:var(--text-color,{PF_TEXT});">#{cn}</span>
                    {_pill(r['severity'].replace('Severity ', 'S').replace(' (', ' ').rstrip(')'),
                           SEVERITY_COLORS.get(r['severity'], RH_GRAY), solid=True)}
                    {_pill(r['status'], STATUS_COLORS.get(r['status'], RH_GRAY))}
                    {_pill(r['sla_label'], r['sla_color'])}
                </div>
                <div style="font-size:0.8rem;color:var(--text-color,{PF_TEXT});
                    margin-top:4px;">{r['problem_statement']}</div>
                <div style="font-size:0.7rem;color:{PF_TEXT_SEC};margin-top:3px;">
                    {r.get('account_name', '—')} · last update
                    {_fmt_age(r['stale_hours'])} ago ·
                    followed because: {marks.get(cn, '—')}</div>
                <div style="font-size:0.72rem;color:#6366F1;font-weight:600;
                    margin-top:4px;">→ {action}</div>
                {f'<div style="font-size:0.72rem;color:{PF_TEXT_SEC};margin-top:3px;">'
                 f'<b>Private note:</b> {note}</div>' if note else ''}
            </div>"""), unsafe_allow_html=True)
        with c2:
            if st.button("Remove", key=f"desk_fu_rm_{cn}", use_container_width=True):
                state_delete(user_email, "bookmark", cn)
                st.rerun()

    if missing:
        st.caption(f"Closed or reassigned since you followed them: "
                   f"{', '.join('#' + m for m in sorted(missing))}")
        if st.button("Clear those", key="desk_fu_clear"):
            for m in missing:
                state_delete(user_email, "bookmark", m)
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB — TEAM WORKLOAD (manager / admin)
# ═══════════════════════════════════════════════════════════════════════════════

def _render_workload(q, associates_df, ref, scope_label):
    _section("Team workload",
             "Where the backlog actually sits. This is a load view for routing "
             "decisions — it is deliberately not a ranking, and there is no "
             "'best engineer' column.")

    if q.empty:
        st.info(f"**No open cases in {scope_label.lower()}.** Nothing to balance.",
                icon=":material/check_circle:")
        return

    esc = pd.to_numeric(q.get("escalated", 0), errors="coerce").fillna(0)
    wl = q.assign(_esc=esc).groupby("case_owner").agg(
        open_cases=("case_number", "count"),
        critical=("severity", lambda s: int(s.isin(SEV_ORDER[:2]).sum())),
        sla_risk=("sla_label", lambda s: int(s.isin(("At Risk", "Breached")).sum())),
        escalated=("_esc", "sum"),
        waiting=("status", lambda s: int(s.isin(WAITING_STATUSES).sum())),
        avg_age_days=("age_hours", lambda s: round(s.mean() / 24, 1)),
        oldest_days=("age_hours", lambda s: round(s.max() / 24, 1)),
    ).reset_index().rename(columns={"case_owner": "engineer"})

    meta = associates_df[["associate_name", "sbr", "shift"]].rename(
        columns={"associate_name": "engineer"})
    wl = wl.merge(meta, on="engineer", how="left")
    wl["escalated"] = wl["escalated"].astype(int)

    st.markdown(
        '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px;">'
        + _kpi("Engineers with load", len(wl), "#6366F1", scope_label)
        + _kpi("Median open per engineer", f"{wl['open_cases'].median():.0f}", RH_BLUE,
               f"heaviest carries {wl['open_cases'].max()}")
        + _kpi("Engineers with 3+ critical",
               int((wl["critical"] >= 3).sum()), RH_RED, "Sev1/Sev2 concentration")
        + _kpi("Oldest case in team", f"{wl['oldest_days'].max():.0f}d", RH_ORANGE,
               "by creation date")
        + "</div>", unsafe_allow_html=True)

    st.caption("Click any column header to sort. Nothing here is normalised into a "
               "score, because case counts do not mean the same thing across "
               "severities or products.")
    st.dataframe(
        wl[["engineer", "sbr", "shift", "open_cases", "critical", "sla_risk",
            "escalated", "waiting", "avg_age_days", "oldest_days"]]
        .sort_values("open_cases", ascending=False),
        use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        _section("Backlog by SBR", "Which team is carrying the open work.")
        by_sbr = (q.groupby("sbr").agg(
            open_cases=("case_number", "count"),
            critical=("severity", lambda s: int(s.isin(SEV_ORDER[:2]).sum())))
            .sort_values("open_cases", ascending=False).reset_index())
        fig = go.Figure()
        fig.add_bar(x=by_sbr["open_cases"], y=by_sbr["sbr"], orientation="h",
                    marker_color=RH_BLUE, name="open",
                    hovertemplate="%{y}<br>%{x} open<extra></extra>")
        fig.add_bar(x=by_sbr["critical"], y=by_sbr["sbr"], orientation="h",
                    marker_color=RH_RED, name="Sev1/2",
                    hovertemplate="%{y}<br>%{x} critical<extra></extra>")
        fig.update_layout(barmode="overlay", showlegend=True,
                          legend=dict(orientation="h", y=1.12, x=0))
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(_fig_layout(fig, max(240, 26 * len(by_sbr))),
                        use_container_width=True, key="desk_wl_sbr")
    with c2:
        _section("Where SLA risk is concentrated",
                 "Engineers carrying the most cases at or past target.")
        risky = wl[wl["sla_risk"] > 0].nlargest(10, "sla_risk")
        if risky.empty:
            st.success("**No SLA risk anywhere in this team.** Every open case is "
                       "inside its configured target.")
        else:
            fig2 = go.Figure(go.Bar(
                x=risky["sla_risk"], y=risky["engineer"], orientation="h",
                marker_color=RH_GOLD,
                customdata=risky["open_cases"],
                hovertemplate="%{y}<br>%{x} at/past target of %{customdata} open"
                              "<extra></extra>"))
            fig2.update_yaxes(autorange="reversed")
            st.plotly_chart(_fig_layout(fig2, max(240, 26 * len(risky))),
                            use_container_width=True, key="desk_wl_risk")

    skills_here = sorted(q["product_name"].dropna().unique())
    st.caption(f"Products represented in this backlog: {', '.join(skills_here[:12])}"
               + (f" and {len(skills_here) - 12} more." if len(skills_here) > 12 else "."))
    st.download_button("Export team workload (CSV)", wl.to_csv(index=False).encode(),
                       file_name="team_workload.csv", mime="text/csv",
                       key="desk_wl_export")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB — SYSTEM (admin only)
# ═══════════════════════════════════════════════════════════════════════════════

def _render_system(cases_df, associates_df, skills_df, accounts_df, ref):
    _section("Data freshness and system state",
             "Admin only. What this dashboard is actually reading, and how old it is.")

    stamps = {}
    for col in ("creation_date", "last_updated", "resolution_date"):
        if col in cases_df.columns:
            s = pd.to_datetime(cases_df[col], errors="coerce")
            if s.notna().any():
                stamps[col] = (s.min(), s.max())

    newest = max((v[1] for v in stamps.values()), default=pd.NaT)
    lag = (pd.Timestamp.now() - newest).days if pd.notna(newest) else None

    try:
        from db import IS_PG, DATABASE_URL
        engine = "PostgreSQL" if IS_PG else "SQLite (local fallback)"
        target = DATABASE_URL.split("@")[-1] if IS_PG and DATABASE_URL else "capstone2.db"
        db_ok = True
    except Exception:
        engine, target, db_ok = "unknown", "—", False

    st.markdown(
        '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px;">'
        + _kpi("Data as of", f"{newest:%d %b %Y}" if pd.notna(newest) else "—",
               "#6366F1", "newest timestamp in the extract")
        + _kpi("Extract age", f"{lag}d" if lag is not None else "—",
               RH_RED if (lag or 0) > 30 else RH_GOLD, "behind wall-clock today")
        + _kpi("Database", engine, RH_GREEN if db_ok else RH_RED, target)
        + _kpi("State store", _state_backend(), RH_TEAL,
               "private notes and follow-ups")
        + "</div>", unsafe_allow_html=True)

    if lag is not None and lag > 30:
        st.warning(
            f"**This extract is {lag} days behind today.** Every age and SLA figure "
            f"in My Desk is measured from {newest:%d %b %Y}, not from now, which is "
            f"why a case created in June does not read as three months overdue. "
            f"Treat all operational metrics here as a snapshot of that date — they "
            f"are not live production numbers.", icon=":material/schedule:")

    c1, c2 = st.columns(2)
    with c1:
        _section("Record counts", "What loaded for this session.")
        st.dataframe(pd.DataFrame([
            {"table": "support_cases", "rows": len(cases_df),
             "note": f"{int((~cases_df['status'].isin(CLOSED_STATUSES)).sum())} open"},
            {"table": "accounts", "rows": len(accounts_df),
             "note": f"{accounts_df['support_tier'].nunique()} tiers"},
            {"table": "associates", "rows": len(associates_df),
             "note": f"{associates_df['sbr'].nunique()} SBRs"},
            {"table": "skills", "rows": len(skills_df),
             "note": f"{skills_df['skill_name'].nunique()} distinct skills"},
        ]), use_container_width=True, hide_index=True)
    with c2:
        _section("Timestamp coverage", "Range of each date column in the extract.")
        st.dataframe(pd.DataFrame([
            {"column": k, "earliest": f"{v[0]:%d %b %Y}", "latest": f"{v[1]:%d %b %Y}",
             "populated": int(pd.to_datetime(cases_df[k], errors="coerce").notna().sum())}
            for k, v in stamps.items()
        ]), use_container_width=True, hide_index=True)

    _section("Fields this dashboard deliberately does not have",
             "Listed so nobody builds a decision on something the data cannot support.")
    st.dataframe(pd.DataFrame([
        {"missing": "First-response timestamp",
         "consequence": "Case Timeline shows created / updated / resolved only"},
        {"missing": "Per-update event log",
         "consequence": "'Last update' is a single timestamp, not a history"},
        {"missing": "Escalation timestamp",
         "consequence": "Escalation shows as a flag with no position in time"},
        {"missing": "Engineer presence or rota",
         "consequence": "SMEs show 'shift on record', never 'available now'"},
        {"missing": "Resolution notes / fix steps",
         "consequence": "Similar cases report outcomes, never a suggested fix"},
        {"missing": "Reproduction steps, diagnostic bundles",
         "consequence": "Excluded from the escalation readiness score"},
    ]), use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — SLA & AGING
# ═══════════════════════════════════════════════════════════════════════════════

def _render_sla(q, cases_df, sla, ref):
    if q.empty:
        st.info("No open cases in this scope.")
        return

    _section("Where the queue is aging",
             "Open cases bucketed by age, split by SLA state. Red bars are already "
             "past target and are the backlog that grows escalations.")

    q = q.copy()
    q["bucket"] = q["age_hours"].apply(_age_bucket)
    order = [b[2] for b in AGE_BUCKETS]

    fig = go.Figure()
    for label, color in (("On Track", RH_GREEN), ("At Risk", RH_GOLD), ("Breached", RH_RED)):
        sub = q[q["sla_label"] == label]
        counts = sub["bucket"].value_counts().reindex(order).fillna(0)
        fig.add_bar(x=order, y=counts.values, name=label, marker_color=color,
                    hovertemplate=f"{label}<br>%{{x}}: %{{y}} cases<extra></extra>")
    fig.update_layout(barmode="stack", showlegend=True,
                      legend=dict(orientation="h", y=1.12, x=0))
    st.plotly_chart(_fig_layout(fig, 300), use_container_width=True,
                    key="desk_sla_aging")

    c1, c2 = st.columns([1, 1])

    with c1:
        _section("Breach rate by severity", "Share of each severity's open cases past target.")
        rows = []
        for sev in SEV_ORDER:
            sub = q[q["severity"] == sev]
            if sub.empty:
                continue
            br = (sub["sla_label"] == "Breached").mean() * 100
            rows.append((sev, len(sub), br, sub["age_hours"].median()))
        if rows:
            fig2 = go.Figure(go.Bar(
                x=[r[2] for r in rows],
                y=[r[0].split(" (")[0] for r in rows],
                orientation="h",
                marker_color=[SEVERITY_COLORS.get(r[0], RH_GRAY) for r in rows],
                text=[f"{r[2]:.0f}%  ({r[1]} open)" for r in rows],
                textposition="outside",
                hovertemplate="%{y}<br>%{x:.0f}% breached<extra></extra>"))
            fig2.update_xaxes(range=[0, 115], ticksuffix="%")
            st.plotly_chart(_fig_layout(fig2, 260), use_container_width=True,
                            key="desk_sla_bysev")

    with c2:
        _section("Target vs. what actually happens",
                 "Your configured target against historical median resolve time for "
                 "cases that did close.")
        hist = cases_df[cases_df["status"].isin(CLOSED_STATUSES)]
        med = pd.to_numeric(hist["time_to_resolve_hours"], errors="coerce") \
            .groupby(hist["severity"]).median()
        fig3 = go.Figure()
        labels = [s.split(" (")[0] for s in SEV_ORDER]
        fig3.add_bar(name="Your target", x=labels, y=[sla[s] for s in SEV_ORDER],
                     marker_color="#6366F1")
        fig3.add_bar(name="Historical median", x=labels,
                     y=[med.get(s, 0) for s in SEV_ORDER], marker_color=RH_GRAY)
        fig3.update_layout(barmode="group", showlegend=True,
                           legend=dict(orientation="h", y=1.15, x=0),
                           yaxis_title="hours")
        st.plotly_chart(_fig_layout(fig3, 260), use_container_width=True,
                        key="desk_sla_target")

    _section("Worst offenders", "Longest-running open cases — triage or escalate these first.")
    cols = [c for c in ("case_number", "severity", "status", "account_name",
                        "support_tier", "product_name", "case_owner") if c in q.columns]
    worst = q.nlargest(20, "age_hours")[cols + ["age_hours", "sla_ratio", "stale_hours"]].copy()
    worst["age"] = worst["age_hours"].apply(_fmt_age)
    worst["over target"] = worst["sla_ratio"].apply(lambda v: f"{v:.1f}x")
    worst["last update"] = worst["stale_hours"].apply(_fmt_age)
    st.dataframe(worst[cols + ["age", "over target", "last update"]],
                 use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — SIMILAR CASE SEARCH
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def _resolved_corpus(n_rows, cols_sig, problem, desc, product):
    """Weight the problem statement over the long description."""
    return tuple(f"{p} {p} {d} {pr}" for p, d, pr in zip(problem, desc, product))


def _render_similar(cases_df, associates_df, skills_df):
    """Two halves: search on demand, and the patterns that repeat unprompted."""
    _render_similar_search(cases_df, associates_df, skills_df)
    st.divider()
    _render_patterns(cases_df, associates_df)


def _render_similar_search(cases_df, associates_df, skills_df):
    _section("Have we seen this before?",
             "Paste a problem statement or error signature. Ranked against every "
             "resolved and closed case using TF-IDF cosine similarity.")

    hist = cases_df[cases_df["status"].isin(CLOSED_STATUSES)].reset_index(drop=True)
    if hist.empty:
        st.info("No resolved cases in the dataset to search against.")
        return

    docs = _resolved_corpus(
        len(hist), "ps|desc|prod",
        tuple(hist["problem_statement"].fillna("").astype(str)),
        tuple(hist.get("description", pd.Series("", index=hist.index)).fillna("").astype(str)),
        tuple(hist["product_name"].fillna("").astype(str)),
    )

    query = st.text_area(
        "Symptom / error / problem statement",
        placeholder="e.g. pods stuck in CrashLoopBackOff after upgrade; etcd member "
                    "not rejoining cluster",
        height=90, key="desk_sim_q")

    c1, c2 = st.columns([1, 3])
    with c1:
        k = st.slider("Results", 3, 15, 5, key="desk_sim_k")
    with c2:
        prod_filter = st.multiselect("Restrict to product (optional)",
                                     sorted(hist["product_name"].dropna().unique()),
                                     key="desk_sim_prod")

    if not query.strip():
        st.caption(f"Searching {len(hist):,} resolved cases. Longer, more specific "
                   f"text gives sharper matches than a single keyword.")
        return

    hits = search_similar(query, docs, top_k=k * 4)
    if not hits:
        st.warning("No similar cases found. Try different or more specific wording.")
        return

    rows = [(hist.iloc[i], s) for i, s in hits]
    if prod_filter:
        rows = [(r, s) for r, s in rows if r["product_name"] in prod_filter]
    rows = rows[:k]
    if not rows:
        st.warning("No matches inside that product filter.")
        return

    ttrs = [r["time_to_resolve_hours"] for r, _ in rows
            if pd.notna(r["time_to_resolve_hours"])]
    escs = sum(int(pd.to_numeric(r.get("escalated", 0), errors="coerce") or 0) for r, _ in rows)
    st.markdown(
        f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 14px;">'
        + _kpi("Matches", len(rows), "#6366F1", "above similarity floor")
        + _kpi("Median resolve", f"{pd.Series(ttrs).median():.0f}h" if ttrs else "—",
               RH_TEAL, "for these cases")
        + _kpi("Escalated", f"{escs}/{len(rows)}", RH_PURPLE, "how often this got hot")
        + "</div>", unsafe_allow_html=True)

    for r, score in rows:
        sev_c = SEVERITY_COLORS.get(r["severity"], RH_GRAY)
        pct = min(score * 100, 100)
        mc = RH_GREEN if pct >= 45 else (RH_GOLD if pct >= 25 else RH_GRAY)
        esc_pill = (_pill("ESCALATED", RH_PURPLE, solid=True)
                    if int(pd.to_numeric(r.get("escalated", 0), errors="coerce") or 0) == 1 else "")
        ttr = (f"{r['time_to_resolve_hours']:.0f}h"
               if pd.notna(r["time_to_resolve_hours"]) else "—")
        csat = f"{r['csat_score']:.0f}/5" if pd.notna(r.get("csat_score")) else "—"

        st.markdown(_html(f"""<div style="background:var(--secondary-background-color,{PF_SURFACE});
            border:1px solid var(--border-color,{PF_BORDER});border-left:4px solid {mc};
            border-radius:12px;padding:13px 17px;margin-bottom:8px;">
            <div style="display:flex;justify-content:space-between;gap:14px;align-items:flex-start;">
                <div style="flex:1;min-width:0;">
                    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:5px;">
                        <span style="font-weight:800;font-size:0.88rem;color:var(--text-color,{PF_TEXT});">
                            #{r['case_number']}</span>
                        {_pill(r['severity'].replace('Severity ', 'S').replace(' (', ' ').rstrip(')'), sev_c, solid=True)}
                        {_pill(r['status'], STATUS_COLORS.get(r['status'], RH_GRAY))}
                        {esc_pill}
                    </div>
                    <div style="font-size:0.84rem;color:var(--text-color,{PF_TEXT});line-height:1.45;">
                        {r['problem_statement']}</div>
                    <div style="font-size:0.72rem;color:{PF_TEXT_SEC};margin-top:5px;">
                        {r.get('product_name', '—')} {r.get('product_version', '')}
                        &nbsp;·&nbsp; resolved by <b style="color:var(--text-color,{PF_TEXT});">
                        {r.get('case_owner', '—')}</b>
                        &nbsp;·&nbsp; took {ttr} &nbsp;·&nbsp; CSAT {csat}
                        &nbsp;·&nbsp; {r.get('sbr', '—')}
                    </div>
                </div>
                <div style="text-align:right;flex-shrink:0;">
                    <div style="font-size:1.2rem;font-weight:800;color:{mc};line-height:1;">{pct:.0f}%</div>
                    <div style="font-size:0.6rem;color:{PF_TEXT_SEC};text-transform:uppercase;
                        font-weight:700;letter-spacing:.05em;">match</div>
                </div>
            </div>
        </div>"""), unsafe_allow_html=True)

        with st.expander(f"Full description · #{r['case_number']}", expanded=False):
            st.markdown(f'<div style="font-size:0.8rem;line-height:1.6;color:{PF_TEXT_SEC};">'
                        f'{r.get("description", "—")}</div>', unsafe_allow_html=True)

    # ── Expert roll-up from the matches ──
    owners = pd.Series([r["case_owner"] for r, _ in rows]).value_counts()
    if not owners.empty:
        _section("Ask these engineers",
                 "They closed the cases most similar to yours. Shift is shown so you "
                 "know who is reachable now.")
        cards = ""
        for name, cnt in owners.head(3).items():
            a = associates_df[associates_df["associate_name"] == name]
            shift = a.iloc[0]["shift"] if not a.empty else "—"
            sbr = a.iloc[0]["sbr"] if not a.empty else "—"
            lvl = a.iloc[0].get("skill_level", "—") if not a.empty else "—"
            aid = a.iloc[0]["associate_id"] if not a.empty else None
            sk = skills_df[skills_df["associate_id"] == aid].sort_values("skill_rank").head(3) \
                if aid is not None else skills_df.iloc[0:0]
            pills = " ".join(_pill(s, SKILL_COLORS_LOCAL[i % len(SKILL_COLORS_LOCAL)], solid=True)
                             for i, s in enumerate(sk["skill_name"]))
            cards += f"""<div style="flex:1;min-width:230px;background:var(--secondary-background-color,{PF_SURFACE});
                border:1px solid var(--border-color,{PF_BORDER});border-radius:12px;padding:12px 15px;">
                <div style="font-weight:800;font-size:0.85rem;color:var(--text-color,{PF_TEXT});">{name}</div>
                <div style="font-size:0.7rem;color:{PF_TEXT_SEC};margin:3px 0 7px;">
                    {sbr} · {shift} · {lvl} · {cnt} matching case{'s' if cnt != 1 else ''}</div>
                <div style="display:flex;gap:4px;flex-wrap:wrap;">{pills}</div>
            </div>"""
        st.markdown(f'<div style="display:flex;gap:10px;flex-wrap:wrap;">{cards}</div>',
                    unsafe_allow_html=True)


def _render_patterns(cases_df, associates_df):
    _section("Observed historical patterns",
             "The same problem statement, closed more than once on the same product. "
             "This is counted from closed cases — it is history, not a prediction, "
             "and nothing here is modelled.")

    c1, c2 = st.columns([1, 2])
    with c1:
        min_cases = st.slider("Minimum repeats", 3, 15, 5, key="desk_pat_min",
                              help="How many closed cases must share a statement "
                                   "before it counts as a pattern.")
    with c2:
        prods = sorted(cases_df["product_name"].dropna().unique())
        pick = st.multiselect("Product", prods, key="desk_pat_prod")

    pats = recurring_patterns(cases_df, min_cases=min_cases)
    if pats.empty:
        st.success(f"No problem statement repeats {min_cases} or more times in the "
                   f"closed history. Lower the threshold to see weaker patterns.",
                   icon=":material/check_circle:")
        return
    if pick:
        pats = pats[pats["product_name"].isin(pick)]
        if pats.empty:
            st.info("No repeating statement on those products at this threshold.")
            return

    open_now = cases_df[~cases_df["status"].isin(CLOSED_STATUSES)].copy()
    open_now["_key"] = open_now["problem_statement"].astype(str).str.lower().str.strip()
    open_counts = open_now.groupby(["product_name", "_key"]).size()

    covered = int(pats["cases"].sum())
    st.markdown(
        '<div style="display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 14px;">'
        + _kpi("Patterns", len(pats), RH_PURPLE, f"{min_cases}+ closed repeats each")
        + _kpi("Cases covered", f"{covered:,}", "#6366F1",
               f"{covered / max(len(cases_df), 1) * 100:.0f}% of all cases")
        + _kpi("Widest reach", f"{int(pats['accounts'].max())} accounts",
               RH_TEAL, "one statement, this many customers")
        + "</div>", unsafe_allow_html=True)

    for i, p in pats.head(10).iterrows():
        key = str(p["problem_statement"]).lower().strip()
        still_open = int(open_counts.get((p["product_name"], key), 0))
        esc_c = RH_RED if p["escalation_rate"] >= 25 else (
            RH_GOLD if p["escalation_rate"] >= 10 else RH_GREEN)
        open_pill = (_pill(f"{still_open} OPEN NOW", RH_ORANGE, solid=True)
                     if still_open else "")
        ttr = f"{p['avg_resolve_hours']:.0f}h" if pd.notna(p["avg_resolve_hours"]) else "—"
        csat = f"{p['avg_csat']:.1f}/5" if pd.notna(p["avg_csat"]) else "—"

        st.markdown(_html(f"""<div class="desk-card" style="{_stagger(i)}
            background:var(--secondary-background-color,{PF_SURFACE});
            border:1px solid var(--border-color,{PF_BORDER});
            border-left:4px solid {RH_PURPLE};border-radius:12px;
            padding:13px 17px;margin-bottom:8px;">
            <div style="display:flex;justify-content:space-between;gap:14px;align-items:flex-start;">
                <div style="flex:1;min-width:0;">
                    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:5px;">
                        {_pill(p['product_name'], RH_BLUE, solid=True)}
                        {_pill(p['sbr'], RH_GRAY)}{open_pill}
                    </div>
                    <div style="font-size:0.85rem;font-weight:600;line-height:1.45;
                        color:var(--text-color,{PF_TEXT});">{p['problem_statement']}</div>
                    <div style="font-size:0.72rem;color:{PF_TEXT_SEC};margin-top:5px;">
                        {p['accounts']} account{'s' if p['accounts'] != 1 else ''}
                        &nbsp;·&nbsp; versions {p['versions'] or '—'}
                        &nbsp;·&nbsp; median fix {ttr}
                        &nbsp;·&nbsp; CSAT {csat}
                        &nbsp;·&nbsp; usually closed by {p['engineers']}
                    </div>
                </div>
                <div style="text-align:right;flex-shrink:0;">
                    <div style="font-size:1.35rem;font-weight:800;color:{RH_PURPLE};line-height:1;">
                        {p['cases']}</div>
                    <div style="font-size:0.6rem;color:{PF_TEXT_SEC};text-transform:uppercase;
                        font-weight:700;letter-spacing:.05em;">closed</div>
                    <div style="font-size:0.72rem;font-weight:700;color:{esc_c};margin-top:5px;">
                        {p['escalation_rate']:.0f}% escalated</div>
                </div>
            </div>
        </div>"""), unsafe_allow_html=True)

    st.caption(
        "Grouping is on the exact problem statement, so wording variants are counted "
        "separately — the real repeat rate is at least this high, never lower. "
        "A high escalation rate on a pattern is the useful signal: it says this "
        "symptom tends to go wrong even when an experienced engineer takes it.")

    st.download_button("Export patterns (CSV)", pats.to_csv(index=False),
                       file_name="recurring_patterns.csv", mime="text/csv",
                       key="desk_pat_dl")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB — ESCALATION RISK
# ═══════════════════════════════════════════════════════════════════════════════

def _render_risk(q, cases_df, scope_label):
    _section("Which open cases are heading for an escalation",
             "Scored against every historical case. The point is to intervene "
             "before the customer escalates, not to report it afterwards.")

    if q.empty:
        st.info("No open cases in this scope.")
        return

    model = fit_escalation_model(cases_df)
    ev = evaluate_risk_model(cases_df)
    scored = score_escalation_risk(q, model).sort_values("esc_risk", ascending=False)

    if ev:
        st.caption(
            f"Smoothed naive-Bayes over {', '.join(model['features'])}, fitted on "
            f"{model['n']:,} cases ({model['escalations']} escalations, "
            f"{model['base'] * 100:.1f}% base rate). Held-out **AUC "
            f"{ev['auc']:.3f}** on {ev['n_test']} unseen cases; the top-scoring decile "
            f"contains **{ev['top_decile_capture'] * 100:.0f}%** of all escalations in "
            f"that holdout. Rare feature values are shrunk toward the base rate so a "
            f"product with two cases cannot dominate.")

    hi = scored[scored["esc_risk"] >= 0.25]
    med = scored[(scored["esc_risk"] >= 0.10) & (scored["esc_risk"] < 0.25)]
    exp_esc = scored["esc_risk"].sum()

    st.markdown(
        '<div style="display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 14px;">'
        + _kpi("High risk", len(hi), RH_RED, "25%+ chance of escalating")
        + _kpi("Elevated", len(med), RH_GOLD, "10-25%")
        + _kpi("Expected escalations", f"{exp_esc:.0f}", RH_PURPLE,
               f"across {len(scored)} open cases")
        + _kpi("Scope", scope_label, "#6366F1", "")
        + "</div>", unsafe_allow_html=True)

    if model["base"] > 0:
        sev_rates = (pd.to_numeric(cases_df.get("escalated", 0), errors="coerce")
                     .fillna(0).groupby(cases_df["severity"]).mean())
        never = [s for s in SEV_ORDER if sev_rates.get(s, 0) == 0]
        if never:
            st.info(
                f"In this dataset **no {' or '.join(s.split(' (')[0] for s in never)} "
                f"case has ever escalated**, so the model scores them near zero and "
                f"severity dominates the ranking. That is a property of the source "
                f"data, not of the model — on data where low-severity cases do "
                f"escalate, product, account and SBR carry more of the signal.",
                icon=":material/info:")

    top = scored.head(12)
    if top.empty or top["esc_risk"].max() < 0.02:
        st.success("Nothing in this queue looks likely to escalate.")
        return

    _section("Intervene on these first", "Risk drivers show which factors moved the "
                                         "odds, in log-odds against the base rate.")
    for _, r in top.iterrows():
        risk = r["esc_risk"]
        rc = RH_RED if risk >= 0.4 else (RH_GOLD if risk >= 0.2 else RH_TEAL)
        already = int(pd.to_numeric(r.get("escalated", 0), errors="coerce") or 0) == 1
        tag = (_pill("ALREADY ESCALATED", RH_PURPLE, solid=True) if already else "")
        st.markdown(_html(f"""<div style="background:var(--secondary-background-color,{PF_SURFACE});
            border:1px solid var(--border-color,{PF_BORDER});border-left:4px solid {rc};
            border-radius:12px;padding:12px 16px;margin-bottom:7px;">
            <div style="display:flex;justify-content:space-between;gap:14px;align-items:flex-start;">
                <div style="flex:1;min-width:0;">
                    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:4px;">
                        <span style="font-weight:800;font-size:0.86rem;color:var(--text-color,{PF_TEXT});">
                            #{r['case_number']}</span>
                        {_pill(r['severity'].replace('Severity ', 'S').replace(' (', ' ').rstrip(')'),
                               SEVERITY_COLORS.get(r['severity'], RH_GRAY), solid=True)}
                        {_pill(r['status'], STATUS_COLORS.get(r['status'], RH_GRAY))}
                        {tag}
                    </div>
                    <div style="font-size:0.82rem;color:var(--text-color,{PF_TEXT});line-height:1.4;">
                        {r['problem_statement']}</div>
                    <div style="font-size:0.7rem;color:{PF_TEXT_SEC};margin-top:4px;">
                        {r.get('account_name', '—')} · {r.get('product_name', '—')}
                        · age {_fmt_age(r['age_hours'])}
                        · drivers: <b>{r.get('risk_drivers', '—') or 'base rate only'}</b></div>
                </div>
                <div style="text-align:right;flex-shrink:0;">
                    <div style="font-size:1.2rem;font-weight:800;color:{rc};line-height:1;">
                        {risk * 100:.0f}%</div>
                    <div style="font-size:0.6rem;color:{PF_TEXT_SEC};text-transform:uppercase;
                        font-weight:700;letter-spacing:.05em;">esc. risk</div>
                </div>
            </div>
        </div>"""), unsafe_allow_html=True)

    out = scored[[c for c in ("case_number", "severity", "status", "account_name",
                              "product_name", "case_owner", "esc_risk", "risk_drivers")
                  if c in scored.columns]]
    st.download_button("Export risk-scored queue (CSV)", out.to_csv(index=False).encode(),
                       file_name="escalation_risk.csv", mime="text/csv", key="desk_risk_dl")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB — TRENDS & ANOMALIES
# ═══════════════════════════════════════════════════════════════════════════════

def _render_trends(cases_df, ref):
    _section("Is something new breaking?",
             "Compares case volume per product and version in a recent window "
             "against every earlier window of the same length. Early warning for "
             "a known issue before it floods the queue.")

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        window = st.selectbox("Recent window", [30, 60, 90, 120], index=2,
                              format_func=lambda d: f"Last {d} days", key="desk_an_w")
    with c2:
        min_cases = st.slider("Minimum cases to flag", 2, 10, 3, key="desk_an_min")
    with c3:
        z_thr = st.slider("Sensitivity (z-score)", 1.0, 4.0, 2.0, 0.5, key="desk_an_z")

    an = detect_anomalies(cases_df, ref, window_days=window,
                          min_cases=min_cases, z_threshold=z_thr)

    if an.empty:
        st.success(f"No product or version is spiking in the last {window} days at "
                   f"these thresholds. Loosen the sensitivity to see weaker signals.")
    else:
        st.markdown(
            '<div style="display:flex;gap:10px;flex-wrap:wrap;margin:4px 0 12px;">'
            + _kpi("Spiking", len(an), RH_ORANGE, "product + version combos")
            + _kpi("Cases involved", int(an["cases_in_window"].sum()), "#6366F1",
                   f"in the last {window} days")
            + _kpi("Sev1/Sev2", int(an["sev1_2"].sum()), RH_RED, "inside the spikes")
            + _kpi("Escalated", int(an["escalated"].sum()), RH_PURPLE, "already hot")
            + "</div>", unsafe_allow_html=True)

        for _, a in an.iterrows():
            lift_c = RH_RED if a["z"] >= 3 else RH_ORANGE
            st.markdown(_html(f"""<div style="background:var(--secondary-background-color,{PF_SURFACE});
                border:1px solid var(--border-color,{PF_BORDER});border-left:4px solid {lift_c};
                border-radius:12px;padding:12px 16px;margin-bottom:7px;">
                <div style="display:flex;justify-content:space-between;gap:14px;align-items:flex-start;">
                    <div style="flex:1;min-width:0;">
                        <div style="font-weight:800;font-size:0.86rem;color:var(--text-color,{PF_TEXT});">
                            {a['product_name']} <span style="color:{PF_TEXT_SEC};">v{a['product_version']}</span></div>
                        <div style="font-size:0.8rem;color:var(--text-color,{PF_TEXT});margin-top:4px;
                            line-height:1.4;">{a['top_symptom']}</div>
                        <div style="font-size:0.7rem;color:{PF_TEXT_SEC};margin-top:4px;">
                            {a['cases_in_window']} cases vs {a['expected']} expected ·
                            {a['accounts']} distinct account{'s' if a['accounts'] != 1 else ''} ·
                            {a['sev1_2']} at Sev1/Sev2 · {a['escalated']} escalated</div>
                    </div>
                    <div style="text-align:right;flex-shrink:0;">
                        <div style="font-size:1.2rem;font-weight:800;color:{lift_c};line-height:1;">
                            {a['lift']}x</div>
                        <div style="font-size:0.6rem;color:{PF_TEXT_SEC};text-transform:uppercase;
                            font-weight:700;letter-spacing:.05em;">vs baseline</div>
                    </div>
                </div>
            </div>"""), unsafe_allow_html=True)

    # ── Volume trend for a chosen product ──
    _section("Volume over time", "Pick a product to see its case history by month, "
                                 "split by severity.")
    prod = st.selectbox("Product", sorted(cases_df["product_name"].dropna().unique()),
                        key="desk_an_prod")
    sub = cases_df[cases_df["product_name"] == prod].copy()
    sub["_m"] = pd.to_datetime(sub["creation_date"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    sub = sub.dropna(subset=["_m"])
    if sub.empty:
        st.info("No dated cases for this product.")
        return
    piv = sub.pivot_table(index="_m", columns="severity", values="case_number",
                          aggfunc="count").fillna(0).sort_index()
    fig = go.Figure()
    for sev in SEV_ORDER:
        if sev in piv.columns:
            fig.add_bar(x=piv.index, y=piv[sev], name=sev.split(" (")[0],
                        marker_color=SEVERITY_COLORS.get(sev, RH_GRAY))
    fig.update_layout(barmode="stack", showlegend=True,
                      legend=dict(orientation="h", y=1.14, x=0), yaxis_title="cases")
    st.plotly_chart(_fig_layout(fig, 320), use_container_width=True, key="desk_an_trend")

    vers = (sub.groupby("product_version")
            .agg(cases=("case_number", "count"),
                 escalations=("escalated", "sum"),
                 avg_csat=("csat_score", "mean"),
                 avg_ttr=("time_to_resolve_hours", "mean"))
            .sort_values("cases", ascending=False).round(2).reset_index())
    st.markdown(f"**Versions of {prod}**")
    st.dataframe(vers, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB — MY PERFORMANCE (CSAT drill-down + skill gap)
# ═══════════════════════════════════════════════════════════════════════════════

def _render_performance(cases_df, associates_df, skills_df, owners, scope_label, ref):
    if owners is None:
        st.info("Pick a specific associate or team in the Scope selector above to see "
                "a personal CSAT and skill breakdown.")
        return
    if not owners:
        st.info("No associate record is linked to this login.")
        return

    mine = cases_df[cases_df["case_owner"].isin(owners)]
    if mine.empty:
        st.info("No cases are assigned in this scope.")
        return

    csat = pd.to_numeric(mine["csat_score"], errors="coerce")
    rated = mine[csat.notna()].assign(_csat=csat[csat.notna()])
    overall = csat.mean()
    peer = pd.to_numeric(cases_df["csat_score"], errors="coerce").mean()

    # ── CSAT drill-down ───────────────────────────────────────────────────────
    _section("What is actually moving my CSAT",
             "A score on its own is not actionable. These are the specific cases "
             "pulling it down, and what they have in common.")

    low = rated[rated["_csat"] <= 2]
    st.markdown(
        '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;">'
        + _kpi("My CSAT", f"{overall:.2f}" if pd.notna(overall) else "—",
               RH_GREEN if pd.notna(overall) and overall >= peer else RH_GOLD,
               f"peer average {peer:.2f}")
        + _kpi("Rated cases", len(rated), "#6366F1", f"of {len(mine)} total")
        + _kpi("Detractors", len(low), RH_RED, "scored 1 or 2")
        + _kpi("Cost of detractors",
               f"{(overall - rated[rated['_csat'] > 2]['_csat'].mean()):+.2f}"
               if len(low) and len(rated) > len(low) else "—",
               RH_ORANGE, "vs excluding them")
        + "</div>", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        dist = rated["_csat"].round().value_counts().reindex([1, 2, 3, 4, 5]).fillna(0)
        fig = go.Figure(go.Bar(
            x=[str(int(i)) for i in dist.index], y=dist.values,
            marker_color=[RH_RED, RH_ORANGE, RH_GOLD, RH_TEAL, RH_GREEN],
            text=[int(v) for v in dist.values], textposition="outside"))
        fig.update_layout(xaxis_title="CSAT score", yaxis_title="cases")
        st.plotly_chart(_fig_layout(fig, 250), use_container_width=True,
                        key="desk_perf_dist")
    with c2:
        # Does slow resolution track bad scores?
        ttr = pd.to_numeric(rated["time_to_resolve_hours"], errors="coerce")
        ok = ttr.notna()
        if ok.sum() >= 5:
            corr = np.corrcoef(ttr[ok], rated["_csat"][ok])[0, 1]
            fig2 = go.Figure(go.Scatter(
                x=ttr[ok], y=rated["_csat"][ok], mode="markers",
                marker=dict(size=8, color=rated["_csat"][ok], colorscale="RdYlGn",
                            cmin=1, cmax=5, line=dict(width=0)),
                text=rated["case_number"][ok],
                hovertemplate="#%{text}<br>%{x:.0f}h → CSAT %{y}<extra></extra>"))
            fig2.update_layout(xaxis_title="hours to resolve", yaxis_title="CSAT")
            st.plotly_chart(_fig_layout(fig2, 250), use_container_width=True,
                            key="desk_perf_scatter")
            st.caption(f"Correlation between resolve time and CSAT: **{corr:+.2f}**. "
                       + ("Slower cases do score worse — speed is the lever."
                          if corr < -0.2 else
                          "Weak relationship — slow resolution is not what is hurting "
                          "these scores, so look at the cases themselves."))
        else:
            st.caption("Not enough resolved-and-rated cases to correlate resolve time "
                       "with CSAT.")

    if not low.empty:
        _section(f"Your {len(low)} detractor case{'s' if len(low) != 1 else ''}",
                 "Read these before your next one-to-one.")
        cols = [c for c in ("case_number", "_csat", "severity", "account_name",
                            "product_name", "time_to_resolve_hours", "escalated",
                            "problem_statement") if c in low.columns]
        det = low[cols].rename(columns={"_csat": "csat",
                                        "time_to_resolve_hours": "resolve_hrs"})
        st.dataframe(det.sort_values("csat"), use_container_width=True, hide_index=True)

        by_prod = (low.groupby("product_name").size().sort_values(ascending=False))
        if len(by_prod) and by_prod.iloc[0] >= 2:
            st.caption(f"Concentrated in **{by_prod.index[0]}** "
                       f"({by_prod.iloc[0]} of {len(low)} detractors) — that is the "
                       f"product to skill up on.")

    # ── Skill gap ─────────────────────────────────────────────────────────────
    _section("Skill gap against your SBR team",
             "Skills your SBR peers carry that you do not. Ranked by how many of "
             "them hold it — the common ones are where training pays back fastest.")

    me = associates_df[associates_df["associate_name"].isin(owners)]
    if me.empty:
        st.info("No associate record found for this scope.")
        return
    my_sbrs = sorted(me["sbr"].dropna().unique())
    my_ids = me["associate_id"].tolist()
    my_skills = skills_df[skills_df["associate_id"].isin(my_ids)]
    my_skill_set = {str(s).lower() for s in my_skills["skill_name"]}

    # Peers = same SBR, excluding you. Their skill spread is the bar to clear.
    peers = associates_df[associates_df["sbr"].isin(my_sbrs)
                          & ~associates_df["associate_id"].isin(my_ids)]
    peer_skills = skills_df[skills_df["associate_id"].isin(peers["associate_id"])]

    if peers.empty or peer_skills.empty:
        st.info("No SBR peers with recorded skills to compare against.")
    else:
        n_peers = peers["associate_id"].nunique()
        spread = (peer_skills.groupby("skill_name")["associate_id"].nunique()
                  .sort_values(ascending=False).reset_index(name="peers_with"))
        spread["pct"] = (spread["peers_with"] / n_peers * 100).round(0)
        spread["you_have_it"] = spread["skill_name"].str.lower().isin(my_skill_set)
        top = spread.head(12)

        fig3 = go.Figure(go.Bar(
            x=top["pct"], y=top["skill_name"], orientation="h",
            marker_color=[RH_GREEN if h else RH_RED for h in top["you_have_it"]],
            text=["you have it" if h else "GAP" for h in top["you_have_it"]],
            textposition="outside",
            customdata=top["peers_with"],
            hovertemplate="%{y}<br>%{customdata} of "
                          f"{n_peers} peers (%{{x}}%)<extra></extra>"))
        fig3.update_layout(
            xaxis_title=f"% of your {n_peers} peers in {', '.join(my_sbrs)} "
                        f"holding this skill",
            xaxis_range=[0, 115])
        fig3.update_yaxes(autorange="reversed")
        st.plotly_chart(_fig_layout(fig3, max(260, 28 * len(top))),
                        use_container_width=True, key="desk_perf_gap")

        gaps = spread[~spread["you_have_it"]]
        if gaps.empty:
            st.success(f"You hold every skill recorded across your {n_peers} SBR "
                       f"peers. No gap to close.")
        else:
            top_gap = gaps.iloc[0]
            st.warning(
                f"**Biggest gap: {top_gap['skill_name']}** — "
                f"{int(top_gap['peers_with'])} of your {n_peers} SBR peers "
                f"({int(top_gap['pct'])}%) list it and you do not. "
                f"{len(gaps)} skill{'s' if len(gaps) != 1 else ''} in total that "
                f"your team carries and you do not — the ones near the top are "
                f"table stakes on this team, not specialisms.",
                icon=":material/school:")
            st.dataframe(
                gaps[["skill_name", "peers_with", "pct"]].head(15).rename(
                    columns={"peers_with": "peers_holding_it", "pct": "% of team"}),
                use_container_width=True, hide_index=True)

    # Product coverage, as a footnote. In this dataset each SBR maps to only one
    # to three products, so product-level gaps almost never exist — skills carry
    # the signal instead.
    sbr_cases = cases_df[cases_df["sbr"].isin(my_sbrs)]
    if not sbr_cases.empty:
        sbr_products = set(sbr_cases["product_name"].dropna().astype(str))
        my_products = set(mine["product_name"].dropna().astype(str))
        untouched = sorted(sbr_products - my_products)
        if untouched:
            st.caption(
                f"Product coverage: {len(sbr_products) - len(untouched)} of "
                f"{len(sbr_products)} products handled in {', '.join(my_sbrs)} have "
                f"passed through your queue. Not yet worked: {', '.join(untouched)}.")
        else:
            covered = (f"the only product your SBR handles"
                       if len(sbr_products) == 1
                       else f"all {len(sbr_products)} products your SBR handles")
            st.caption(
                f"Product coverage: you have worked {covered}. Each SBR maps to only "
                f"a handful of products, so skills are the sharper measure above.")

    if not my_skills.empty:
        pills = " ".join(
            _pill(f"{r['skill_name']} · #{int(r['skill_rank'])}",
                  SKILL_COLORS_LOCAL[i % len(SKILL_COLORS_LOCAL)], solid=True)
            for i, (_, r) in enumerate(my_skills.sort_values("skill_rank").head(8).iterrows()))
        st.markdown(f'<div style="margin-top:10px;font-size:0.78rem;">'
                    f'<b style="color:var(--text-color,{PF_TEXT});">Your ranked skills</b>'
                    f'<div style="margin-top:6px;display:flex;gap:5px;flex-wrap:wrap;">'
                    f'{pills}</div></div>', unsafe_allow_html=True)


SKILL_COLORS_LOCAL = [
    "#6366F1", "#06B6D4", "#8B5CF6", "#10B981", "#F59E0B",
    "#3B82F6", "#FB923C", "#F43F5E", "#94A3B8", "#4F46E5",
]
