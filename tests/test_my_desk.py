"""My Desk operational logic — deterministic unit tests.

Everything here runs on synthetic frames built in-test, so it is independent of
the database contents and of the Streamlit runtime. The rendering layer is
covered separately by the AppTest smoke tests at the bottom.
"""
import datetime
import os
import re
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import my_desk as md

REF = pd.Timestamp("2026-06-11 09:00")


# ── fixtures ──────────────────────────────────────────────────────────────────

def _case(n, **kw):
    base = {
        "case_number": f"300{n:04d}",
        "account_id": "ACC-1",
        "account_name": "Northwind Systems",
        "creation_date": REF - pd.Timedelta(days=10),
        "severity": "Severity 3 (Normal)",
        "status": "Open",
        "csat_score": 4.0,
        "sbr": "Platform",
        "problem_statement": "pods stuck in crashloopbackoff after upgrade",
        "description": "Customer environment is RHEL 9. No workaround found.",
        "product_name": "Red Hat OpenShift",
        "product_version": "4.14",
        "sovereign_support": "No",
        "business_hours": "Yes",
        "case_owner": "Theo Krishnan",
        "last_updated": REF - pd.Timedelta(days=2),
        "resolution_date": pd.NaT,
        "escalated": 0,
        "time_to_resolve_hours": float("nan"),
    }
    base.update(kw)
    return base


@pytest.fixture
def cases():
    rows = [
        _case(1, severity="Severity 1 (Urgent)", status="Open",
              last_updated=REF - pd.Timedelta(hours=40)),
        _case(2, severity="Severity 2 (High)", status="In Progress", escalated=1),
        _case(3, status="Waiting on Customer",
              last_updated=REF - pd.Timedelta(days=12)),
        _case(4, severity="Severity 4 (Low)", status="Open"),
        _case(5, status="Waiting on Engineering", case_owner="Priya Nair"),
    ]
    # closed history, so similarity / SME / pattern code has something to chew on
    for i in range(6, 16):
        rows.append(_case(
            i, status="Closed", resolution_date=REF - pd.Timedelta(days=30),
            time_to_resolve_hours=48.0, csat_score=4.5,
            case_owner="Priya Nair" if i % 2 else "Theo Krishnan",
            escalated=1 if i in (6, 7) else 0))
    return pd.DataFrame(rows)


@pytest.fixture
def accounts():
    return pd.DataFrame([{
        "account_id": "ACC-1", "account_name": "Northwind Systems",
        "support_tier": "Premium", "region": "NA", "sector": "Finance",
        "tam_assigned": "Yes", "contract_end_date": REF + pd.Timedelta(days=200),
    }])


@pytest.fixture
def associates():
    return pd.DataFrame([
        {"associate_id": "A1", "associate_name": "Theo Krishnan", "sbr": "Platform",
         "shift": "EMEA", "skill_level": "Senior", "email": "theo.krishnan@redhat.com",
         "manager_email": "adaeze.nwachukwu@redhat.com"},
        {"associate_id": "A2", "associate_name": "Priya Nair", "sbr": "Platform",
         "shift": "NASA", "skill_level": "Principal", "email": "priya.nair@redhat.com",
         "manager_email": "adaeze.nwachukwu@redhat.com"},
    ])


@pytest.fixture
def skills():
    return pd.DataFrame([
        {"associate_id": "A1", "skill_name": "OpenShift", "skill_rank": 1},
        {"associate_id": "A2", "skill_name": "OpenShift", "skill_rank": 1},
        {"associate_id": "A2", "skill_name": "etcd", "skill_rank": 2},
    ])


@pytest.fixture
def queue(cases, accounts):
    return md.build_queue(cases, accounts, owners=None, ref=REF,
                          sla_hours=md.DEFAULT_SLA_HOURS)


# ── queue construction & priority score ───────────────────────────────────────

class TestQueue:
    def test_only_open_cases(self, queue):
        assert len(queue) == 5
        assert not queue["status"].isin(md.CLOSED_STATUSES).any()

    def test_owner_scoping(self, cases, accounts):
        q = md.build_queue(cases, accounts, owners=["Priya Nair"], ref=REF,
                           sla_hours=md.DEFAULT_SLA_HOURS)
        assert set(q["case_owner"]) == {"Priya Nair"}

    def test_empty_owner_list_gives_empty_queue(self, cases, accounts):
        q = md.build_queue(cases, accounts, owners=[], ref=REF,
                           sla_hours=md.DEFAULT_SLA_HOURS)
        assert q.empty

    def test_priority_in_range(self, queue):
        assert queue["priority"].between(0, 100).all()

    def test_priority_sorted_descending(self, queue):
        assert queue["priority"].is_monotonic_decreasing

    def test_severity_dominates_at_equal_age(self, cases, accounts):
        two = pd.DataFrame([
            _case(20, severity="Severity 1 (Urgent)"),
            _case(21, severity="Severity 4 (Low)"),
        ])
        q = md.build_queue(two, accounts, owners=None, ref=REF,
                           sla_hours=md.DEFAULT_SLA_HOURS)
        assert q.iloc[0]["severity"].startswith("Severity 1")

    def test_waiting_on_customer_is_damped_not_dropped(self, cases, accounts):
        pair = pd.DataFrame([
            _case(30, status="Open"),
            _case(31, status="Waiting on Customer"),
        ])
        q = md.build_queue(pair, accounts, owners=None, ref=REF,
                           sla_hours=md.DEFAULT_SLA_HOURS)
        assert len(q) == 2
        open_p = q[q["status"] == "Open"]["priority"].iloc[0]
        wait_p = q[q["status"] == "Waiting on Customer"]["priority"].iloc[0]
        assert wait_p < open_p

    def test_log_scaling_keeps_extremes_apart(self, accounts):
        # A case 200x over target must still outrank one 2x over.
        pair = pd.DataFrame([
            _case(40, creation_date=REF - pd.Timedelta(hours=240)),
            _case(41, creation_date=REF - pd.Timedelta(hours=24000)),
        ])
        q = md.build_queue(pair, accounts, owners=None, ref=REF,
                           sla_hours=md.DEFAULT_SLA_HOURS)
        assert q.iloc[0]["case_number"] == "3000041"
        assert q["priority"].nunique() == 2, "log scale must not saturate both to 100"


# ── SLA & aging ───────────────────────────────────────────────────────────────

class TestSLA:
    def test_target_follows_severity(self, queue):
        for _, r in queue.iterrows():
            assert r["sla_target"] == md.DEFAULT_SLA_HOURS[r["severity"]]

    def test_labels_partition_the_queue(self, queue):
        assert set(queue["sla_label"]) <= {"On Track", "At Risk", "Breached"}

    def test_breached_when_past_target(self, accounts):
        df = pd.DataFrame([_case(50, creation_date=REF - pd.Timedelta(hours=500))])
        q = md.build_queue(df, accounts, owners=None, ref=REF,
                           sla_hours=md.DEFAULT_SLA_HOURS)
        assert q.iloc[0]["sla_label"] == "Breached"
        assert q.iloc[0]["sla_ratio"] > 1

    def test_on_track_when_fresh(self, accounts):
        df = pd.DataFrame([_case(51, creation_date=REF - pd.Timedelta(hours=1))])
        q = md.build_queue(df, accounts, owners=None, ref=REF,
                           sla_hours=md.DEFAULT_SLA_HOURS)
        assert q.iloc[0]["sla_label"] == "On Track"

    def test_custom_targets_are_honoured(self, cases, accounts):
        tight = {s: 1 for s in md.SEV_ORDER}
        q = md.build_queue(cases, accounts, owners=None, ref=REF, sla_hours=tight)
        assert (q["sla_label"] == "Breached").all()

    def test_stale_hours_measured_from_last_update(self, queue):
        r = queue[queue["case_number"] == "3000003"].iloc[0]
        assert 280 < r["stale_hours"] < 300  # 12 days

    def test_age_buckets_are_ordered_and_total(self, queue):
        labels = [md._age_bucket(h) for h in queue["age_hours"]]
        assert all(lb in [b[2] for b in md.AGE_BUCKETS] for lb in labels)
        assert md._age_bucket(1) != md._age_bucket(100000)

    def test_reference_time_is_dataset_clock(self, cases):
        ref = md.desk_reference_time(cases)
        assert ref >= cases["last_updated"].max()


# ── next best action ──────────────────────────────────────────────────────────

class TestNextBestAction:
    def test_escalated_wins_over_everything(self, queue):
        r = queue[queue["case_number"] == "3000002"].iloc[0]
        action, reason = md.next_best_action(r)
        assert "escalation" in action.lower()
        assert reason

    def test_waiting_on_customer_gets_a_chase(self, queue):
        r = queue[queue["case_number"] == "3000003"].iloc[0]
        action, _ = md.next_best_action(r)
        assert "follow" in action.lower() or "customer" in action.lower()

    def test_breached_sla_asks_for_a_customer_update(self, accounts):
        df = pd.DataFrame([_case(60, creation_date=REF - pd.Timedelta(hours=900))])
        q = md.build_queue(df, accounts, owners=None, ref=REF,
                           sla_hours=md.DEFAULT_SLA_HOURS)
        action, _ = md.next_best_action(q.iloc[0])
        assert "update" in action.lower()

    def test_repeat_product_points_at_history(self, accounts):
        # Fresh Sev-4 case: no SLA or staleness rule can fire ahead of the
        # repeat-product rule, so this isolates that branch.
        df = pd.DataFrame([_case(61, severity="Severity 4 (Low)",
                                 creation_date=REF - pd.Timedelta(hours=2),
                                 last_updated=REF - pd.Timedelta(hours=1))])
        q = md.build_queue(df, accounts, owners=None, ref=REF,
                           sla_hours=md.DEFAULT_SLA_HOURS)
        action, reason = md.next_best_action(
            q.iloc[0], repeat_products=("Red Hat OpenShift",))
        assert "similar" in action.lower() or "resolved" in action.lower()
        assert "Red Hat OpenShift" in reason or "before" in reason.lower()

    def test_sla_pressure_outranks_the_repeat_rule(self, accounts):
        # Rule order is deliberate: a breach beats a research prompt.
        df = pd.DataFrame([_case(62, creation_date=REF - pd.Timedelta(hours=900))])
        q = md.build_queue(df, accounts, owners=None, ref=REF,
                           sla_hours=md.DEFAULT_SLA_HOURS)
        action, _ = md.next_best_action(
            q.iloc[0], repeat_products=("Red Hat OpenShift",))
        assert "update" in action.lower()

    def test_always_returns_a_reason(self, queue):
        for _, r in queue.iterrows():
            action, reason = md.next_best_action(r)
            assert action and reason
            assert not action.endswith(" ")

    def test_action_context_shapes(self, cases):
        ctx = md.action_context(cases)
        assert "specialist_products" in ctx and "repeat_products" in ctx


# ── similarity search ─────────────────────────────────────────────────────────

class TestSimilarity:
    def test_exact_match_scores_highest(self):
        docs = ("etcd member not rejoining cluster",
                "etcd member restarted cleanly",
                "invoice export fails")
        hits = md.search_similar("etcd member not rejoining cluster", docs, top_k=3)
        assert hits[0][0] == 0
        assert len(hits) >= 2 and hits[0][1] > hits[1][1]
        assert all(i != 2 for i, _ in hits), "unrelated doc must score below the floor"

    def test_unrelated_query_returns_nothing_or_low(self):
        docs = ("etcd member not rejoining cluster", "pods stuck in crashloopbackoff")
        hits = md.search_similar("zzzq wibble frobnicate", docs, top_k=3)
        assert not hits or hits[0][1] < 0.1

    def test_empty_query_is_safe(self):
        assert md.search_similar("", ("anything",), top_k=3) == []

    def test_top_k_respected(self):
        docs = tuple(f"cluster node failure {i}" for i in range(20))
        assert len(md.search_similar("cluster node failure", docs, top_k=5)) <= 5

    def test_scores_are_bounded(self):
        docs = ("cluster node failure", "cluster node failure")
        for _, s in md.search_similar("cluster node failure", docs, top_k=2):
            assert 0 <= s <= 1.0001


# ── SME ranking ───────────────────────────────────────────────────────────────

class TestSME:
    def test_returns_ranked_frame(self, queue, cases, associates, skills):
        r = queue.iloc[0]
        smes = md.find_smes(r, cases, associates, skills, top_k=4)
        assert not smes.empty
        assert smes["match_score"].is_monotonic_decreasing

    def test_never_claims_availability(self, queue, cases, associates, skills):
        smes = md.find_smes(queue.iloc[0], cases, associates, skills)
        cols = " ".join(smes.columns).lower()
        assert "available" not in cols
        assert "shift_on_record" in smes.columns

    def test_every_row_explains_itself(self, queue, cases, associates, skills):
        smes = md.find_smes(queue.iloc[0], cases, associates, skills)
        assert smes["why"].astype(str).str.len().gt(0).all()

    def test_exclusion_is_honoured(self, queue, cases, associates, skills):
        smes = md.find_smes(queue.iloc[0], cases, associates, skills,
                            exclude="Priya Nair")
        assert "Priya Nair" not in set(smes["associate"])

    def test_top_k_respected(self, queue, cases, associates, skills):
        assert len(md.find_smes(queue.iloc[0], cases, associates, skills, top_k=1)) <= 1


# ── escalation readiness ──────────────────────────────────────────────────────

class TestReadiness:
    def test_shape(self, queue, cases):
        rd = md.escalation_readiness(queue.iloc[0], cases)
        assert rd["total"] == len(rd["items"])
        assert 0 <= rd["passed"] <= rd["total"]

    def test_unavailable_items_are_declared_not_faked(self, queue, cases):
        rd = md.escalation_readiness(queue.iloc[0], cases)
        assert rd["unavailable"], "fields absent from the dataset must be listed"
        labels = {lbl for lbl, _, _ in rd["items"]}
        assert not (labels & set(rd["unavailable"]))

    def test_rich_description_passes_more_checks(self, cases):
        poor = _case(70, description="x")
        rich = _case(71, description=(
            "Customer environment is RHEL 9 on bare metal. Business impact: "
            "production outage blocking month-end close. Started after the 4.14 "
            "upgrade on Tuesday. Logs show 'etcdserver: request timed out'. "
            "We already tried restarting the kubelet and rotating certificates."))
        a = md.escalation_readiness(pd.Series(poor), cases)
        b = md.escalation_readiness(pd.Series(rich), cases)
        assert b["passed"] > a["passed"]

    def test_score_never_exceeds_total(self, queue, cases):
        for _, r in queue.iterrows():
            rd = md.escalation_readiness(r, cases)
            assert rd["passed"] <= rd["total"]


# ── recurring patterns ────────────────────────────────────────────────────────

class TestPatterns:
    def test_detects_the_repeated_statement(self, cases):
        pats = md.recurring_patterns(cases, min_cases=4)
        assert not pats.empty
        assert pats.iloc[0]["cases"] >= 4

    def test_threshold_is_respected(self, cases):
        assert md.recurring_patterns(cases, min_cases=999).empty

    def test_only_counts_closed_cases(self, cases):
        pats = md.recurring_patterns(cases, min_cases=4)
        closed = int(cases["status"].isin(md.CLOSED_STATUSES).sum())
        assert int(pats["cases"].sum()) <= closed

    def test_empty_frame_is_safe(self):
        assert md.recurring_patterns(pd.DataFrame(
            columns=["status", "problem_statement", "product_name"])).empty


# ── timeline, risk, diffs ─────────────────────────────────────────────────────

class TestTimelineAndRisk:
    def test_timeline_never_invents_a_first_response(self, queue):
        tl = md.case_timeline(queue.iloc[0], REF)
        fr = [t for t in tl if t[0].lower().startswith("first response")]
        assert fr and fr[0][1] is None

    def test_timeline_starts_at_creation(self, queue):
        assert md.case_timeline(queue.iloc[0], REF)[0][1] is not None

    def test_account_risk_levels(self, cases, queue):
        level, color, factors = md.account_risk("ACC-1", cases, queue)
        assert level in ("Stable", "Attention", "High attention")
        assert isinstance(factors, list)

    def test_unknown_account_is_not_guessed_at(self, cases):
        level, _, factors = md.account_risk("NOPE", cases)
        assert level == "Unknown"
        assert factors and "No cases" in factors[0]

    def test_diff_against_no_snapshot_is_none(self, queue):
        assert md.diff_snapshot(None, md.queue_signature(queue), queue) is None

    def test_diff_spots_a_new_case(self, queue):
        cur = md.queue_signature(queue)
        prev = dict(list(cur.items())[1:])
        changes = md.diff_snapshot(prev, cur, queue)
        assert changes and any("new" in t.lower() for _, t in changes)

    def test_identical_snapshots_report_nothing(self, queue):
        sig = md.queue_signature(queue)
        assert md.diff_snapshot(sig, sig, queue) == []


# ── escalation risk model ─────────────────────────────────────────────────────

class TestRiskModel:
    def test_probabilities_bounded(self, cases, queue):
        model = md.fit_escalation_model(cases)
        scored = md.score_escalation_risk(queue, model)
        assert scored["esc_risk"].between(0, 1).all()

    def test_every_open_case_is_scored(self, cases, queue):
        model = md.fit_escalation_model(cases)
        assert len(md.score_escalation_risk(queue, model)) == len(queue)


# ── local brief & AI guards ───────────────────────────────────────────────────

class TestBrief:
    def test_local_brief_has_every_spec_section(self, queue, cases):
        txt = md._local_brief(queue, REF, "Theo Krishnan", "My cases", cases)
        for section in ("Critical", "SLA risk", "Waiting on customer",
                        "Escalations", "Recommended follow-ups"):
            assert section in txt

    def test_local_brief_only_cites_real_cases(self, queue, cases):
        txt = md._local_brief(queue, REF, "Theo Krishnan", "My cases", cases)
        cited = {w.lstrip("#") for w in txt.split() if w.startswith("#300")}
        assert cited <= set(queue["case_number"])

    def test_ai_error_strings_are_rejected(self):
        for marker in md._AI_ERROR_MARKERS:
            assert md._ai_failed(marker + " — check the endpoint")
        assert md._ai_failed("")
        assert md._ai_failed(None)
        assert not md._ai_failed("Critical: case 3000001 needs an update.")

    def test_html_is_sanitised(self):
        out = md._md_lite("<script>alert(1)</script> hello")
        assert "<script" not in out.lower()

    def test_html_collapse_removes_blank_lines(self):
        out = md._html("<div>\n   \n  <span>x</span>\n</div>")
        assert "\n" not in out


# ── rendering smoke tests (Streamlit AppTest) ─────────────────────────────────

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _app(role, email, extra=None):
    at = AppTest.from_file(os.path.join(ROOT, "app2.py"), default_timeout=600)
    state = {"authenticated": True, "username": email, "role": role,
             "display_name": "Theo Krishnan", "_tour_seen": True, "_tour_step": 0,
             "dash_tab": "My Desk", "_workspace": "selected",
             "selected_associate": None}
    state.update(extra or {})
    for k, v in state.items():
        at.session_state[k] = v
    return at


@pytest.fixture(scope="module")
def associate_app():
    at = _app("associate", "theo.krishnan@redhat.com")
    at.run()
    return at


@pytest.fixture(scope="module")
def manager_app():
    at = _app("manager", "adaeze.nwachukwu@redhat.com")
    at.run()
    return at


class TestRender:
    def test_associate_desk_renders(self, associate_app):
        assert not associate_app.exception, associate_app.exception

    def test_desk_is_the_default_tab(self, associate_app):
        assert associate_app.session_state["dash_tab"] == "My Desk"

    def test_associate_cannot_switch_to_team_queue(self, associate_app):
        # The control is not rendered at all, so there is nothing to poke at.
        assert "desk_mode" not in associate_app.session_state
        assert "desk_scope_who" not in associate_app.session_state

    def test_manager_can_switch_to_team_queue(self, manager_app):
        assert "desk_mode" in manager_app.session_state

    def test_manager_desk_renders(self, manager_app):
        assert not manager_app.exception, manager_app.exception

    def test_admin_desk_renders(self):
        at = _app("admin", "admin@redhat.com")
        at.run()
        assert not at.exception, at.exception
        assert "desk_mode" in at.session_state

    def test_no_slider_crash_on_a_small_queue(self):
        # A five-case queue must not build a slider whose min equals its max.
        at = _app("associate", "theo.krishnan@redhat.com")
        at.run()
        for s in at.get("slider"):
            assert s.min != s.max

    def test_handoff_falls_back_without_ai(self):
        at = _app("associate", "theo.krishnan@redhat.com")
        at.run()
        btn = [b for b in at.button if b.key == "desk_handoff_btn"]
        if not btn:
            pytest.skip("no queue for this login in the current dataset")
        btn[0].click()
        at.run()
        assert not at.exception, at.exception
        assert "desk_handoff_text" in at.session_state
        brief = at.session_state["desk_handoff_text"]
        assert "Critical" in brief and "Recommended follow-ups" in brief

    def test_quick_filter_selection_survives_a_rerun(self):
        # Chip option values must not embed live counts, or changing an SLA
        # target would rewrite the options and silently clear the selection.
        at = _app("associate", "theo.krishnan@redhat.com",
                  {"desk_chips": ["\U0001F525 Critical"]})
        at.run()
        assert not at.exception, at.exception
        assert at.session_state["desk_chips"] == ["\U0001F525 Critical"]

    def test_quick_filter_labels_are_count_free(self):
        for label, _, _, _ in md.QUICK_FILTERS:
            assert not any(ch.isdigit() for ch in label)

    def test_customer_dashboard_link_stays_in_tab(self, associate_app):
        # Every anchor pointing at the other dashboard, not just whichever one
        # happens to render for this login — a cross-app hop carries a handoff
        # token with a 60-second life, so a new tab wastes most of it.
        html = " ".join(m.value for m in associate_app.markdown)
        anchors = re.findall(r"<a\s[^>]*>", html)
        crossing = [a for a in anchors if config.CUSTOMER_URL in a]
        assert crossing, "no link to the customer dashboard rendered at all"
        assert all('target="_self"' in a for a in crossing), crossing

    def test_data_freshness_is_stated(self, associate_app):
        text = " ".join(m.value for m in associate_app.markdown)
        text += " ".join(c.value for c in associate_app.caption)
        assert "Data as of" in text or "static extract" in text
