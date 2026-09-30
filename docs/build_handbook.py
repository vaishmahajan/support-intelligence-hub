#!/usr/bin/env python3
"""Render the project's Markdown docs as styled, self-contained HTML books.

    python docs/build_handbook.py            # rebuild every document below
    python docs/build_handbook.py --open     # ... and open them in a browser

Documents are listed in DOCUMENTS. Adding one is a single line there; the
styling, sidebar, diagram support and a card on the index page all come along
for free.

This directory doubles as the GitHub Pages source, so the build also writes an
`index.html` landing page — Pages serves a directory listing for nothing, and
a bare 404 at the site root is a poor front door.

There is one source of truth — the Markdown file. Maintaining a second
hand-written HTML copy guarantees the two drift apart, so this script derives
the HTML instead: Red Hat brand colours and fonts, a sticky chapter sidebar,
and Mermaid diagrams rendered in the browser.

No new dependencies. `markdown` is not in requirements.txt and this project
keeps its dependency list short (see handbook §18.1), so the small subset of
Markdown the handbook actually uses is parsed here: headings, tables, fenced
code, mermaid fences, blockquotes, lists, horizontal rules, inline emphasis /
code / links, and raw HTML pass-through.

Fonts and the Mermaid runtime come from a CDN, so the diagrams need network
access the first time the page is opened. Everything else renders offline.
"""

import html
import re
import sys
import webbrowser
from collections import namedtuple
from pathlib import Path

DOCS = Path(__file__).resolve().parent

#: src = markdown input, out = html output, title = <title> and index card
#: heading, brand = sidebar heading, blurb = one line on the index page.
Doc = namedtuple("Doc", "src out title brand blurb")

DOCUMENTS = [
    Doc("PROJECT_HANDBOOK.md", "PROJECT_HANDBOOK.html",
        "Project Handbook", "Project Handbook",
        "The whole system from scratch — architecture, who it is for, every "
        "feature and what it is for, the scoring models with worked examples "
        "you can reproduce, and the commands to run, containerise and deploy "
        "it."),
    Doc("DATA_FORMAT.md", "DATA_FORMAT.html",
        "Source Data Format", "Data Format",
        "No customer data ships with this project. This is the column-by-column "
        "spec for the four source files you supply yourself, how they join, the "
        "vocabularies that must match exactly, and a validator to run before "
        "you load."),
]

#: Shown on the index page and in each document's sidebar.
SITE_TITLE = "Red Hat Support Operations Platform"
REPO_URL = "https://github.com/vaishmahajan/support-intelligence-hub"


# ── inline ────────────────────────────────────────────────────────────────

_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITAL = re.compile(r"(?<![\*\w])\*([^\*\n]+?)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def inline(text):
    """Escape, then apply the inline markup the handbook uses."""
    # Code spans are pulled out first so their contents are never treated as
    # emphasis — `**` inside a code span must stay literal.
    spans = []

    def stash(m):
        spans.append(html.escape(m.group(1)))
        return f"\x00{len(spans) - 1}\x00"

    text = _CODE.sub(stash, text)
    text = html.escape(text)
    text = _LINK.sub(r'<a href="\2">\1</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITAL.sub(r"<em>\1</em>", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{spans[int(m.group(1))]}</code>", text)
    return text


def slug(title):
    """GitHub's heading-anchor algorithm, so in-document links keep working."""
    t = re.sub(r"[*`]", "", title).strip().lower()
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[^\w\s-]", "", t)
    return t.replace(" ", "-")


# ── blocks ────────────────────────────────────────────────────────────────

def split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_divider(line):
    return bool(re.fullmatch(r"\|?[\s:|-]+\|[\s:|-]*", line.strip())) and "-" in line


def convert(md):
    lines = md.split("\n")
    out, toc = [], []
    # A repeated heading text must not produce a repeated id. GitHub appends
    # -1, -2 … to later occurrences, so the first one keeps the bare slug and
    # existing links to it stay correct.
    seen = {}
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # fenced code / mermaid
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            i += 1
            body = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            text = "\n".join(body)
            if lang == "mermaid":
                out.append(f'<div class="mermaid">{html.escape(text)}</div>')
            else:
                cls = f' class="language-{lang}"' if lang else ""
                label = f'<span class="lang">{html.escape(lang)}</span>' if lang else ""
                out.append(f'<div class="codeblock">{label}'
                           f"<pre><code{cls}>{html.escape(text)}</code></pre></div>")
            continue

        # raw HTML pass-through (the cover block and the one hand-built table)
        if line.startswith("<"):
            out.append(line)
            i += 1
            continue

        # horizontal rule
        if stripped == "---":
            out.append("<hr>")
            i += 1
            continue

        # heading
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            level, title = len(m.group(1)), m.group(2).strip()
            anchor = base = slug(title)
            n = seen.get(base, 0)
            seen[base] = n + 1
            if n:
                anchor = f"{base}-{n}"
            if level <= 2 and title.lower() != "table of contents":
                toc.append((level, title, anchor))
            out.append(f'<h{level} id="{anchor}">{inline(title)}'
                       f'<a class="anchor" href="#{anchor}">#</a></h{level}>')
            i += 1
            continue

        # table
        if stripped.startswith("|") and i + 1 < len(lines) and is_divider(lines[i + 1]):
            header = split_row(line)
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            body = "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
                for r in rows
            )
            # `| | |` is the borderless-layout idiom (the cover block uses it);
            # an all-empty header row must not render as a black bar.
            if any(c.strip() for c in header):
                head = "".join(f"<th>{inline(c)}</th>" for c in header)
                head = f"<thead><tr>{head}</tr></thead>"
                cls = "tablewrap"
            else:
                head, cls = "", "tablewrap headless"
            out.append(f'<div class="{cls}"><table>{head}'
                       f"<tbody>{body}</tbody></table></div>")
            continue

        # blockquote (callout)
        if stripped.startswith(">"):
            body = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                body.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            joined = "\n".join(body).strip()
            # The leading emoji picks the accent colour.
            kind = ("warn" if joined.startswith(("⚠️", "🚫", "💾"))
                    else "tip" if joined.startswith(("💡", "✅")) else "note")
            paras = "".join(f"<p>{inline(p.strip())}</p>"
                            for p in re.split(r"\n\s*\n", joined) if p.strip())
            out.append(f'<blockquote class="{kind}">{paras}</blockquote>')
            continue

        # list
        if re.match(r"^\s*([-*]|\d+\.)\s+", line):
            ordered = bool(re.match(r"^\s*\d+\.\s+", line))
            items = []
            while i < len(lines) and re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]):
                items.append(re.sub(r"^\s*([-*]|\d+\.)\s+", "", lines[i]))
                i += 1
            tag = "ol" if ordered else "ul"
            body = "".join(f"<li>{inline(it)}</li>" for it in items)
            out.append(f"<{tag}>{body}</{tag}>")
            continue

        # blank
        if not stripped:
            i += 1
            continue

        # paragraph
        para = []
        while (i < len(lines) and lines[i].strip()
               and not lines[i].startswith("<")
               and not lines[i].strip().startswith(("```", ">", "|", "#"))
               and lines[i].strip() != "---"
               and not re.match(r"^\s*([-*]|\d+\.)\s+", lines[i])):
            para.append(lines[i].strip())
            i += 1
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
        else:
            i += 1

    return "\n".join(out), toc


def build_toc(toc):
    items = []
    for level, title, anchor in toc:
        if title.startswith("📕") or title.startswith("📑"):
            continue
        cls = "l1" if level == 1 else "l2"
        label = re.sub(r"^Chapter (\d+) — ", r'<b>\1</b> ', html.escape(title))
        label = re.sub(r"[*`]", "", label)
        items.append(f'<a class="{cls}" href="#{anchor}">{label}</a>')
    return "\n".join(items)


# ── page ──────────────────────────────────────────────────────────────────

# Red Hat brand palette. Red Hat Display / Text / Mono are the official
# typefaces and are served free from Google Fonts.
CSS = """
:root{
  --rh-red:#EE0000; --rh-red-dark:#A30000; --ink:#151515; --ink-soft:#4D4D4D;
  --line:#D2D2D2; --bg:#FFFFFF; --bg-soft:#F5F5F5; --bg-code:#1B1D21;
  --blue:#0066CC; --green:#3E8635; --gold:#F0AB00; --purple:#5752D1;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth; scroll-padding-top:1.5rem}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:"Red Hat Text","Red Hat Display",-apple-system,"Segoe UI",sans-serif;
  font-size:16.5px; line-height:1.68; -webkit-font-smoothing:antialiased;
}
.layout{display:grid; grid-template-columns:300px minmax(0,1fr); gap:0; max-width:1500px; margin:0 auto}

/* ── sidebar ───────────────────────────────────────── */
nav{
  position:sticky; top:0; align-self:start; height:100vh; overflow-y:auto;
  padding:1.6rem 1rem 3rem 1.4rem; border-right:1px solid var(--line);
  background:var(--bg-soft); font-size:.86rem;
}
nav .brand{
  font-family:"Red Hat Display",sans-serif; font-weight:900; font-size:1.02rem;
  color:var(--rh-red); letter-spacing:-.01em; line-height:1.3; margin-bottom:.15rem;
}
nav .sub{color:var(--ink-soft); font-size:.76rem; margin-bottom:1.1rem}
nav a{display:block; color:var(--ink-soft); text-decoration:none; padding:.26rem .6rem;
      border-radius:5px; border-left:3px solid transparent}
nav a:hover{background:#e8e8e8; color:var(--ink)}
nav a.l1{font-weight:600; color:var(--ink); margin-top:.5rem}
nav a.l1 b{display:inline-block; min-width:1.5em; color:var(--rh-red)}
nav a.l2{padding-left:1.9rem; font-size:.81rem}
nav a:target,nav a.active{border-left-color:var(--rh-red); background:#fff}

/* ── content ───────────────────────────────────────── */
main{padding:2.4rem 3.2rem 7rem; min-width:0}
h1,h2,h3,h4{font-family:"Red Hat Display",sans-serif; letter-spacing:-.018em; line-height:1.22}
h1{
  font-size:2.35rem; font-weight:900; margin:3.4rem 0 1.4rem; padding-bottom:.5rem;
  border-bottom:4px solid var(--rh-red); color:var(--ink);
}
h1:first-child{margin-top:0}
h2{font-size:1.58rem; font-weight:800; margin:2.5rem 0 .9rem; color:var(--rh-red-dark)}
h3{font-size:1.18rem; font-weight:700; margin:1.9rem 0 .6rem; color:var(--ink)}
h4{font-size:1rem; font-weight:700; margin:1.4rem 0 .5rem; color:var(--ink-soft)}
.anchor{opacity:0; margin-left:.45rem; color:var(--line); text-decoration:none; font-weight:400}
h1:hover .anchor,h2:hover .anchor,h3:hover .anchor{opacity:1}
p{margin:.85rem 0}
a{color:var(--blue)} a:hover{color:var(--rh-red)}
hr{border:0; border-top:1px solid var(--line); margin:2.6rem 0}
hr + hr{display:none}
ul,ol{margin:.85rem 0; padding-left:1.5rem}
li{margin:.3rem 0}
strong{font-weight:700}

/* ── code ──────────────────────────────────────────── */
code{
  font-family:"Red Hat Mono",ui-monospace,"SF Mono",Menlo,monospace;
  font-size:.875em; background:#F0F0F0; padding:.13em .38em; border-radius:4px;
  color:var(--rh-red-dark);
}
.codeblock{position:relative; margin:1.2rem 0}
.codeblock .lang{
  position:absolute; top:0; right:0; padding:.2rem .7rem; font-size:.68rem;
  font-family:"Red Hat Mono",monospace; letter-spacing:.08em; text-transform:uppercase;
  color:#8A8D90; background:#26292D; border-radius:0 8px 0 8px;
}
pre{
  margin:0; background:var(--bg-code); color:#E8E8E8; padding:1.05rem 1.25rem;
  border-radius:8px; overflow-x:auto; border-left:4px solid var(--rh-red);
}
pre code{background:none; color:inherit; padding:0; font-size:.855rem; line-height:1.6}

/* ── tables ────────────────────────────────────────── */
.tablewrap{overflow-x:auto; margin:1.3rem 0}
table{border-collapse:collapse; width:100%; font-size:.92rem}
th{
  background:var(--ink); color:#fff; font-family:"Red Hat Display",sans-serif;
  font-weight:700; text-align:left; padding:.62rem .85rem; font-size:.86rem;
  letter-spacing:.01em;
}
td{padding:.55rem .85rem; border-bottom:1px solid var(--line); vertical-align:top}
tbody tr:nth-child(even){background:#FAFAFA}
tbody tr:hover{background:#FFF4F4}
table table,td>table{font-size:.9rem}
.headless td:first-child{font-weight:600; white-space:nowrap}

/* ── callouts ──────────────────────────────────────── */
blockquote{
  margin:1.3rem 0; padding:.85rem 1.2rem; border-radius:0 8px 8px 0;
  border-left:5px solid var(--blue); background:#F0F7FF;
}
blockquote.warn{border-left-color:var(--rh-red); background:#FFF5F5}
blockquote.tip{border-left-color:var(--green); background:#F3FAF2}
blockquote p{margin:.4rem 0}
blockquote p:first-child{margin-top:0} blockquote p:last-child{margin-bottom:0}

/* ── mermaid ───────────────────────────────────────── */
.mermaid{
  margin:1.6rem 0; padding:1.2rem; background:var(--bg-soft);
  border:1px solid var(--line); border-radius:10px; text-align:center; overflow-x:auto;
}
.mermaid svg{max-width:100%; height:auto}

/* ── cover ─────────────────────────────────────────── */
div[align="center"]:first-of-type{
  padding:3rem 2rem 2.2rem; margin-bottom:1rem;
  background:linear-gradient(135deg,#1B1D21 0%,#3C0000 55%,#A30000 100%);
  color:#fff; border-radius:12px;
}
div[align="center"]:first-of-type h1{
  color:#fff; border-bottom:none; font-size:2.9rem; margin:0 0 .3rem;
}
div[align="center"]:first-of-type h3{color:#FFD6D6; font-weight:500; margin:0 0 1.1rem}
div[align="center"]:first-of-type em{color:#FFC7C7}
div[align="center"]:first-of-type .tablewrap{max-width:620px; margin:1.2rem auto 0}
div[align="center"]:first-of-type table{font-size:.9rem}
div[align="center"]:first-of-type th{background:rgba(255,255,255,.12)}
div[align="center"]:first-of-type td{
  border-bottom:1px solid rgba(255,255,255,.18); color:#fff;
}
div[align="center"]:first-of-type tbody tr:nth-child(even),
div[align="center"]:first-of-type tbody tr:hover{background:rgba(255,255,255,.05)}
div[align="center"]:first-of-type code{background:rgba(255,255,255,.15); color:#FFD6D6}
div[align="center"]:first-of-type a{color:#FFC7C7}

/* ── print ─────────────────────────────────────────── */
@media print{
  nav{display:none} .layout{grid-template-columns:1fr} main{padding:0}
  h1{page-break-before:always; page-break-after:avoid}
  h1:first-of-type{page-break-before:avoid}
  h2,h3{page-break-after:avoid}
  pre,table,.mermaid,blockquote{page-break-inside:avoid}
  body{font-size:10.5pt}
}
@media (max-width:1000px){
  .layout{grid-template-columns:1fr} nav{position:static; height:auto; border-right:none;
  border-bottom:1px solid var(--line)} main{padding:1.5rem 1.2rem 4rem}
}
"""

#: Only the index page needs these — it has no sidebar and no chapter flow.
INDEX_CSS = """
body{background:var(--bg-soft)}
.wrap{max-width:860px; margin:0 auto; padding:4.5rem 1.5rem 6rem}
.hero{
  padding:3rem 2.4rem 2.6rem; border-radius:14px; color:#fff; margin-bottom:2.4rem;
  background:linear-gradient(135deg,#1B1D21 0%,#3C0000 55%,#A30000 100%);
}
.hero h1{color:#fff; border-bottom:none; margin:0 0 .5rem; font-size:2.6rem}
.hero p{color:#FFD6D6; margin:0; font-size:1.05rem; max-width:52ch}
.card{
  display:block; text-decoration:none; color:inherit; background:var(--bg);
  border:1px solid var(--line); border-left:5px solid var(--rh-red);
  border-radius:10px; padding:1.5rem 1.7rem; margin-bottom:1.2rem;
  transition:box-shadow .15s ease, transform .15s ease;
}
.card:hover{box-shadow:0 6px 22px rgba(0,0,0,.09); transform:translateY(-2px)}
.card h2{margin:0 0 .5rem; font-size:1.34rem}
.card p{margin:0 0 .9rem; color:var(--ink-soft); font-size:.95rem}
.card .go{color:var(--rh-red); font-weight:700; font-size:.9rem}
.foot{margin-top:2.6rem; font-size:.9rem; color:var(--ink-soft)}
"""

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Documentation</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Red+Hat+Display:wght@400;500;700;800;900&family=Red+Hat+Text:wght@400;500;600;700&family=Red+Hat+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>{title}</h1>
    <p>Documentation for the Red Hat CEE BI Capstone #2 platform.</p>
  </div>
  {cards}
  <p class="foot">Source, demo dataset and setup instructions:
     <a href="{repo}">{repo}</a>.
     No customer or employee data is published anywhere in this project.</p>
</div>
</body>
</html>
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Red+Hat+Display:wght@400;500;700;800;900&family=Red+Hat+Text:wght@400;500;600;700&family=Red+Hat+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>
<div class="layout">
<nav>
  <div class="brand">{brand}</div>
  <div class="sub">Red Hat CEE BI Capstone #2</div>
  {toc}
</nav>
<main>
{body}
</main>
</div>

<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
mermaid.initialize({{
  startOnLoad: true,
  theme: "base",
  themeVariables: {{
    primaryColor: "#F5F5F5", primaryTextColor: "#151515", primaryBorderColor: "#8A8D90",
    lineColor: "#6A6E73", secondaryColor: "#FFF4F4", tertiaryColor: "#FFFFFF",
    fontFamily: '"Red Hat Text", sans-serif', fontSize: "14px"
  }},
  flowchart: {{ curve: "basis", htmlLabels: true }},
  securityLevel: "loose"
}});
</script>

<script>
// Highlight in the sidebar whichever chapter is currently on screen.
(function () {{
  const links = new Map(
    [...document.querySelectorAll('nav a')].map(a => [a.getAttribute('href').slice(1), a]));
  const order = [...links.keys()];
  const visible = new Set();

  const observer = new IntersectionObserver(entries => {{
    for (const e of entries) {{
      e.isIntersecting ? visible.add(e.target.id) : visible.delete(e.target.id);
    }}
    for (const a of links.values()) a.classList.remove('active');
    const current = order.find(id => visible.has(id));
    if (current) links.get(current).classList.add('active');
  }}, {{ rootMargin: '0px 0px -75% 0px' }});

  document.querySelectorAll('h1[id], h2[id]').forEach(h => observer.observe(h));
}})();
</script>
</body>
</html>
"""


def render(doc):
    source, target = DOCS / doc.src, DOCS / doc.out
    if not source.exists():
        sys.exit(f"not found: {source}")
    body, toc = convert(source.read_text(encoding="utf-8"))
    target.write_text(TEMPLATE.format(css=CSS, toc=build_toc(toc), body=body,
                                      title=html.escape(f"{SITE_TITLE} — {doc.title}"),
                                      brand=html.escape(doc.brand)),
                      encoding="utf-8")
    print(f"✓ {target}  ({target.stat().st_size / 1024:.0f} KB, {len(toc)} headings, "
          f"{body.count('class=\"mermaid\"')} diagrams)")
    return target


def write_index():
    """The GitHub Pages front door — one card per document in DOCUMENTS."""
    cards = "\n".join(
        f'<a class="card" href="{html.escape(d.out)}">'
        f'<h2>{html.escape(d.title)}</h2>'
        f'<p>{html.escape(d.blurb)}</p>'
        f'<span class="go">Read it &rarr;</span></a>'
        for d in DOCUMENTS
    )
    target = DOCS / "index.html"
    target.write_text(INDEX_TEMPLATE.format(
        css=CSS + INDEX_CSS, title=html.escape(SITE_TITLE), cards=cards,
        repo=html.escape(REPO_URL)), encoding="utf-8")
    print(f"✓ {target}  ({target.stat().st_size / 1024:.0f} KB, "
          f"{len(DOCUMENTS)} documents)")
    return target


def main():
    built = [render(doc) for doc in DOCUMENTS]
    built.insert(0, write_index())
    # GitHub Pages runs Jekyll over this directory otherwise, which buys us
    # nothing — every page here is already finished HTML — and can only break.
    (DOCS / ".nojekyll").touch()
    if "--open" in sys.argv:
        for t in built:
            webbrowser.open(t.as_uri())


if __name__ == "__main__":
    main()
