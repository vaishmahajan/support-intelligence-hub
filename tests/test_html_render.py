"""Guards against HTML leaking into the page as literal text.

Two distinct failure modes, both seen in this project:

1. A whitespace-only line inside a multi-line HTML template. CommonMark treats
   it as a blank line, closes the HTML block early, and renders the remainder
   as literal text or an indented code block. It only triggers when an
   interpolated value comes back empty, so it hides until real data hits it.
   `_html()` collapses templates onto one line, which removes the possibility.

2. HTML handed to a writer with no `unsafe_allow_html` parameter
   (`st.caption`, `st.info`, `st.success`, ...), which escapes and shows it.

`<style>`/`<script>`/`<pre>` are CommonMark *type 1* blocks: they terminate at
their closing tag rather than at a blank line, so they are exempt from (1).
"""
import ast
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import my_desk as md  # noqa: E402

SOURCES = ["my_desk.py", "app2.py", "app1.py"]

TYPE1 = re.compile(r"^\s*<\s*(style|script|pre|textarea)\b", re.I)
BLOCK_OPEN = re.compile(
    r"^\s*<\s*/?\s*(div|span|table|tr|td|th|p|a|b|i|ul|ol|li|section|h[1-6])\b", re.I)
ANY_TAG = re.compile(
    r"<\s*/?\s*(div|span|b|i|br|a|p|table|tr|td|th|ul|ol|li|h[1-6]|img)\b", re.I)
HTML_HELPERS = {"_pill", "_kpi", "_html", "_md_lite"}
NO_HTML_API = {"caption", "info", "warning", "success", "error", "write", "text",
               "metric", "toast", "subheader", "header", "title"}


def _literals(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n.value


def _calls_html_helper(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if name in HTML_HELPERS:
                return True
    return False


def _st_calls(path):
    tree = ast.parse(open(os.path.join(ROOT, path)).read())
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.args):
            yield n


# ── the collapse helper itself ────────────────────────────────────────────────

class TestHtmlHelper:
    def test_collapses_every_newline(self):
        assert "\n" not in md._html("<div>\n  <span>x</span>\n</div>")

    def test_empty_interpolation_leaves_no_blank_line(self):
        tag = ""
        out = md._html(f"""<div>
            {tag}
            <span>after</span>
        </div>""")
        assert "\n" not in out
        assert "<span>after</span>" in out

    def test_content_is_preserved(self):
        out = md._html("<div>\n  hello <b>world</b>\n</div>")
        assert "hello <b>world</b>" in out

    def test_idempotent(self):
        once = md._html("<div>\n  x\n</div>")
        assert md._html(once) == once


# ── source-level guards ───────────────────────────────────────────────────────

@pytest.mark.parametrize("path", SOURCES)
class TestSource:
    def test_multiline_markdown_is_collapsed(self, path):
        """Every st.markdown HTML *template* must go through _html().

        What matters is a newline inside a string literal — that is what can
        become a whitespace-only line. An expression merely spanning several
        source lines (a concatenation of single-line fragments) is fine.
        """
        bad = []
        for n in _st_calls(path):
            if n.func.attr != "markdown":
                continue
            a = n.args[0]
            if isinstance(a, ast.Call) and getattr(a.func, "id", None) == "_html":
                continue
            lits = list(_literals(a))
            if lits and TYPE1.match(lits[0]):
                continue  # <style>/<script> cannot break on a blank line
            if any("\n" in s for s in lits):
                bad.append(f"{path}:{n.lineno}")
        assert not bad, "multi-line HTML not wrapped in _html(): " + ", ".join(bad)

    def test_markdown_with_html_allows_html(self, path):
        bad = []
        for n in _st_calls(path):
            if n.func.attr != "markdown":
                continue
            kw = {k.arg for k in n.keywords if k.arg}
            a = n.args[0]
            if (any(ANY_TAG.search(s) for s in _literals(a)) or _calls_html_helper(a)) \
                    and "unsafe_allow_html" not in kw:
                bad.append(f"{path}:{n.lineno}")
        assert not bad, "st.markdown with HTML but no unsafe_allow_html: " + ", ".join(bad)

    def test_html_never_goes_to_a_plain_text_writer(self, path):
        """st.caption/info/success/... escape HTML, so tags would be visible."""
        bad = []
        for n in _st_calls(path):
            if n.func.attr not in NO_HTML_API:
                continue
            a = n.args[0]
            if any(ANY_TAG.search(s) for s in _literals(a)) or _calls_html_helper(a):
                bad.append(f"{path}:{n.lineno} (st.{n.func.attr})")
        assert not bad, "HTML passed to a text-only writer: " + ", ".join(bad)


# ── render-level guard ────────────────────────────────────────────────────────

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402


def _broken_blocks(at):
    """Markdown elements whose HTML block is closed early by a blank line."""
    out = []
    for m in at.markdown:
        v = m.value
        if not isinstance(v, str) or "\n" not in v:
            continue
        if TYPE1.match(v) or not BLOCK_OPEN.match(v):
            continue
        lines = v.split("\n")
        for i, ln in enumerate(lines[:-1]):
            if ln.strip() == "" and any(x.strip() for x in lines[i + 1:]):
                out.append(v[:120])
                break
    return out


def _app(role, email, extra=None):
    at = AppTest.from_file(os.path.join(ROOT, "app2.py"), default_timeout=900)
    state = {"authenticated": True, "username": email, "role": role,
             "display_name": "Theo Krishnan", "_tour_seen": True, "_tour_step": 0,
             "dash_tab": "My Desk", "_workspace": "selected",
             "selected_associate": None}
    state.update(extra or {})
    for k, v in state.items():
        at.session_state[k] = v
    return at


RENDER_CASES = [
    ("associate", "theo.krishnan@redhat.com", {}),
    ("manager", "adaeze.nwachukwu@redhat.com", {}),
    ("manager", "adaeze.nwachukwu@redhat.com", {"desk_mode": "Team Queue"}),
    ("admin", "admin@redhat.com", {}),
    ("associate", "theo.krishnan@redhat.com", {"desk_sim_q": "etcd not rejoining"}),
    ("associate", "theo.krishnan@redhat.com", {"desk_search": "NASA"}),
    ("associate", "theo.krishnan@redhat.com", {"dash_tab": "Associates"}),
    ("manager", "adaeze.nwachukwu@redhat.com", {"dash_tab": "Team / SBR View"}),
    ("associate", "theo.krishnan@redhat.com", {"dash_tab": "Skills View"}),
]


@pytest.mark.parametrize("role,email,extra", RENDER_CASES)
def test_no_broken_html_blocks_on_screen(role, email, extra):
    at = _app(role, email, extra)
    at.run()
    assert not at.exception, at.exception
    broken = _broken_blocks(at)
    assert not broken, f"HTML block closed early ({role}, {extra}): {broken}"


@pytest.mark.parametrize("role,email,extra", RENDER_CASES[:4])
def test_no_live_script_survives_to_the_page(role, email, extra):
    at = _app(role, email, extra)
    at.run()
    leaks = [m.value[:100] for m in at.markdown
             if isinstance(m.value, str) and not TYPE1.match(m.value)
             and re.search(r"<script|javascript:|\son(click|error|load)\s*=",
                           m.value, re.I)]
    assert not leaks, f"active content reached the page: {leaks}"


# ── the same guard on the Customer dashboard ──────────────────────────────────

def _app1(state):
    at = AppTest.from_file(os.path.join(ROOT, "app1.py"), default_timeout=900)
    for k, v in state.items():
        at.session_state[k] = v
    return at


def _signed_in(role, email, **extra):
    """app1 gates on _workspace, so an authenticated state must also pass it."""
    return dict({"authenticated": True, "username": email, "role": role,
                 "display_name": "Theo Krishnan", "_workspace": "selected"},
                **extra)


APP1_CASES = [
    ("login page", {}),
    ("workspace gate", {"authenticated": True, "username": "admin@redhat.com",
                        "role": "admin", "display_name": "System Administrator"}),
    ("associate", _signed_in("associate", "theo.krishnan@redhat.com")),
    ("manager", _signed_in("manager", "adaeze.nwachukwu@redhat.com")),
    ("admin", _signed_in("admin", "admin@redhat.com")),
]


@pytest.mark.parametrize("label,state", APP1_CASES, ids=[c[0] for c in APP1_CASES])
def test_app1_has_no_broken_html_blocks(label, state):
    at = _app1(state)
    at.run()
    assert not at.exception, at.exception
    broken = _broken_blocks(at)
    assert not broken, f"HTML block closed early ({label}): {broken}"


@pytest.mark.parametrize("label,state", APP1_CASES[:3], ids=[c[0] for c in APP1_CASES[:3]])
def test_app1_no_live_script_survives_to_the_page(label, state):
    at = _app1(state)
    at.run()
    leaks = [m.value[:100] for m in at.markdown
             if isinstance(m.value, str) and not TYPE1.match(m.value)
             and re.search(r"<script|javascript:|\son(click|error|load)\s*=",
                           m.value, re.I)]
    assert not leaks, f"active content reached the page ({label}): {leaks}"
