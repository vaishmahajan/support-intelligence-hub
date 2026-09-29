#!/usr/bin/env python3
"""
Capstone2 — Intelligent Customer Dashboard (Business Requirement #1)

Tech Stack:
  Frontend  : Streamlit 1.30+ (Python web framework, reactive widgets)
  Database  : PostgreSQL 16 via psycopg2 (with SQLite fallback for local dev)
  Charts    : Plotly 5.18+ (interactive, dark-themed visualizations)
  AI        : OpenAI-compatible REST API (endpoint set via AI_ENDPOINT_URL)
  Config    : python-dotenv (.env for secrets, never hardcoded)
  Data      : Pandas 2.0+ (in-memory analytics, cached with @st.cache_data)
  API       : FastAPI + Bearer token auth (secure REST endpoints — see api.py)

Run:
  streamlit run app1.py --server.port 8501
"""

import os
import re
import json
import hashlib
import time
import html as html_mod
from datetime import datetime, date as _date_type, timedelta, timezone

import io
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import requests
import streamlit as st
from dotenv import load_dotenv
import streamlit.components.v1 as st_components
from jose import jwt, JWTError
from passlib.context import CryptContext
from db import get_connection, get_engine, PARAM, IS_PG
import config
import login_guard
from workspace_selector import render_workspace_selector
from workspace_switcher import render_workspace_switcher
# _html() collapses a multi-line HTML template onto one line. An interpolated
# value that comes back empty otherwise leaves a whitespace-only line, which
# markdown reads as a blank line: it closes the HTML block early and renders
# the rest of the template as literal text or an indented code block.
from workspace_utils import _html

load_dotenv(override=False)  # real environment wins; .env only fills gaps
AI_ENDPOINT_URL = os.getenv("AI_ENDPOINT_URL", "")
AI_MODEL_ID = os.getenv("AI_MODEL_ID", "")
AI_API_TOKEN = os.getenv("AI_API_TOKEN", "")
ADMIN_PASSWORD = config.ADMIN_PASSWORD

_pwd_ctx = None
def _get_pwd_ctx():
    global _pwd_ctx
    if _pwd_ctx is None:
        _pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return _pwd_ctx

_tables_init = False
def _init_tables():
    global _tables_init
    if _tables_init or IS_PG:
        return
    _tables_init = True
    conn = get_connection()
    conn.execute("""CREATE TABLE IF NOT EXISTS registered_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('manager','associate')),
        display_name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

_init_tables()

JWT_SECRET = config.JWT_SECRET
JWT_ALGORITHM = config.JWT_ALGORITHM
JWT_EXPIRE_MINUTES = config.JWT_EXPIRE_MINUTES
ADMIN_EMAIL = "admin@redhat.com"
_ADMIN_HASH = None
def _get_admin_hash():
    global _ADMIN_HASH
    if _ADMIN_HASH is None:
        _ADMIN_HASH = _get_pwd_ctx().hash(ADMIN_PASSWORD)
    return _ADMIN_HASH

CARDS_PER_PAGE = 12

st.set_page_config(
    page_title="Customer Intelligence Dashboard",
    page_icon="RH",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════════════════════
# STYLING — PatternFly Dark Theme
# ═══════════════════════════════════════════════════════════════════════════════

PF_BG       = "#F0F4F8"
PF_SURFACE  = "#FFFFFF"
PF_BORDER   = "#E2E8F0"
PF_BORDER_H = "#CBD5E1"
PF_TEXT     = "#1E293B"
PF_TEXT_SEC = "#64748B"
PF_RED      = "#8B5CF6"
PF_RED_DARK = "#7C3AED"
PF_RADIUS   = "16px"
PF_SHADOW   = "0 10px 25px -5px rgba(15,23,42,0.04)"
PF_SHADOW_H = "0 4px 12px rgba(0,0,0,0.08), 0 2px 6px rgba(0,0,0,0.04)"

RH_RED      = "#8B5CF6"
RH_RED_DARK = "#7C3AED"
RH_DARK_1   = "#0F172A"
RH_DARK_2   = "#1E293B"
RH_DARK_3   = "#334155"
RH_GRAY     = "#94A3B8"
RH_LIGHT    = "#CBD5E1"
RH_WHITE    = "#FFFFFF"
RH_BLUE     = "#3B82F6"
RH_TEAL     = "#06B6D4"
RH_GREEN    = "#10B981"
RH_ORANGE   = "#FB923C"
RH_GOLD     = "#F59E0B"
RH_PURPLE   = "#8B5CF6"

CHART_TPL  = "plotly_white"
CHART_FONT = "#1E293B"
CHART_FONT2 = "#64748B"
CHART_BG   = "rgba(0,0,0,0)"

GRADIENT_PAIRS = [
    ("#6366F1", "#A78BFA"),
    ("#06B6D4", "#67E8F9"),
    ("#8B5CF6", "#C4B5FD"),
    ("#3B82F6", "#93C5FD"),
    ("#10B981", "#6EE7B7"),
    ("#F59E0B", "#FCD34D"),
]

STATUS_COLORS = {
    "Open": "#EF4444", "In Progress": RH_GOLD,
    "Waiting on Customer": RH_ORANGE, "Waiting on Engineering": RH_PURPLE,
    "Resolved": RH_GREEN, "Closed": RH_GRAY,
}

CASE_COL_RENAME = {
    "case_number": "Case ID", "severity": "Severity", "status": "Status",
    "product_name": "Product", "problem_statement": "Description",
    "case_owner": "Case Owner", "account_name": "Account",
    "creation_date": "Created", "escalated": "Escalated",
    "csat_score": "CSAT Score", "time_to_resolve_hours": "Resolve Time (hrs)",
}


def _rename_cols(df):
    return df.rename(columns={k: v for k, v in CASE_COL_RENAME.items() if k in df.columns})


def _styled_layout(fig, height=380, yint=True, xint=False):
    y_opts = dict(
        tickfont=dict(color=CHART_FONT2, size=11),
        gridcolor="rgba(0,0,0,0.04)", gridwidth=1,
        zeroline=False, title_font=dict(color=CHART_FONT, size=12),
    )
    if yint:
        y_opts["tickformat"] = "d"
    x_opts = dict(
        tickfont=dict(color=CHART_FONT2, size=11),
        gridcolor="rgba(0,0,0,0.04)", gridwidth=1,
        zeroline=False, title_font=dict(color=CHART_FONT, size=12),
    )
    if xint:
        x_opts["tickformat"] = "d"
    fig.update_layout(
        template=CHART_TPL, paper_bgcolor=CHART_BG, plot_bgcolor=CHART_BG,
        height=height,
        margin=dict(l=40, r=20, t=40, b=40),
        font=dict(family="Red Hat Display, sans-serif"),
        xaxis=x_opts,
        yaxis=y_opts,
        legend=dict(orientation="h", y=1.12, font=dict(size=11, color=CHART_FONT)),
        transition=dict(duration=800, easing="cubic-in-out"),
        hoverlabel=dict(
            bgcolor="#1E293B", font_size=13, font_color="#F8FAFC",
            bordercolor="rgba(99,102,241,0.3)", font_family="Red Hat Text",
        ),
        hovermode="x unified",
    )
    return fig


@st.cache_data(show_spinner=False)
def _get_main_css():
    return f"""
<style>
/* ═══ MODERN INDIGO LIGHT DESIGN SYSTEM ═══ */
.stApp {{ background: {PF_BG} !important; }}
section[data-testid="stSidebar"] {{ background: #F8FAFC !important; border-right: 1px solid #E2E8F0; }}
section[data-testid="stSidebar"] > div {{ background: #F8FAFC !important; }}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div {{
    animation: slideRight 0.4s ease-out both;
}}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-child(2) {{ animation-delay: 0.05s; }}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-child(3) {{ animation-delay: 0.1s; }}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-child(4) {{ animation-delay: 0.15s; }}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:nth-child(5) {{ animation-delay: 0.2s; }}
header[data-testid="stHeader"] {{ background: transparent !important; height: 0 !important; }}
.block-container {{ padding: 0.5rem 2rem 1rem !important; max-width: 100% !important; }}

/* ── Website Header / Navbar ── */
.site-header {{
    display: flex; align-items: center; justify-content: space-between;
    background: linear-gradient(135deg, rgba(99,102,241,0.08) 0%, rgba(139,92,246,0.06) 50%, rgba(59,130,246,0.07) 100%);
    backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(99,102,241,0.15);
    border-radius: 20px;
    padding: 20px 32px;
    margin-bottom: 20px;
    box-shadow: 0 8px 32px rgba(99,102,241,0.08), 0 2px 8px rgba(0,0,0,0.04);
    animation: headerReveal 0.7s cubic-bezier(0.23,1,0.32,1) both;
    position: relative; overflow: hidden;
}}
.site-header::before {{
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3.5px;
    background: linear-gradient(90deg, #6366F1, #8B5CF6, #3B82F6, #06B6D4);
    border-radius: 20px 20px 0 0;
}}
@keyframes headerReveal {{
    from {{ opacity: 0; transform: translateY(-16px) scale(0.98); }}
    to   {{ opacity: 1; transform: translateY(0) scale(1); }}
}}
.site-header-brand {{
    display: flex; align-items: center; gap: 12px;
}}
.site-header-logo {{
    width: 46px; height: 46px; border-radius: 14px;
    background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 50%, #A78BFA 100%);
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    box-shadow: 0 6px 16px rgba(99,102,241,0.35);
    animation: logoPulse 3s ease-in-out infinite;
}}
@keyframes logoPulse {{
    0%,100% {{ box-shadow: 0 4px 12px rgba(99,102,241,0.3); }}
    50% {{ box-shadow: 0 4px 20px rgba(99,102,241,0.5); }}
}}
.site-header-logo svg {{ color: #FFFFFF; }}
.site-header-title {{
    font-size: 1.25rem; font-weight: 800; line-height: 1.2;
    background: linear-gradient(135deg, #1E293B, #6366F1);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
}}
.site-header-subtitle {{
    font-size: 0.76rem; color: {PF_TEXT_SEC};
    line-height: 1.3; margin-top: 3px; font-weight: 500;
}}
.site-header-center {{
    display: flex; align-items: center;
    font-size: 0.76rem; font-weight: 500; color: {PF_TEXT_SEC};
    background: rgba(255,255,255,0.5);
    border: 1px solid rgba(226,232,240,0.4);
    border-radius: 10px; padding: 6px 14px;
}}
.site-header-user {{
    display: flex; align-items: center; gap: 12px;
}}
.site-header-user-info {{
    text-align: right;
}}
.site-header-user-name {{
    font-size: 0.8rem; font-weight: 700; color: {PF_TEXT};
}}
.site-header-user-role {{
    display: inline-block; margin-top: 2px;
    padding: 2px 8px; border-radius: 6px;
    font-size: 0.6rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.05em;
}}
.site-header-avatar {{
    width: 42px; height: 42px; border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 15px; color: #FFFFFF; font-weight: 700; flex-shrink: 0;
    box-shadow: 0 4px 14px rgba(0,0,0,0.15);
    border: 2px solid rgba(255,255,255,0.6);
}}
.site-header-status {{
    display: flex; align-items: center; gap: 5px;
    font-size: 0.65rem; color: #10B981; font-weight: 600;
}}
.site-header-dot {{
    width: 7px; height: 7px; border-radius: 50%; background: #10B981;
    box-shadow: 0 0 6px rgba(16,185,129,0.5);
    animation: dotBlink 2s ease-in-out infinite;
}}
@keyframes dotBlink {{
    0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }}
}}

/* ── Page Load Spinner ── */
.page-loader {{
    position: fixed; top: 0; left: 0; width: 100%; height: 3px;
    z-index: 99999; overflow: hidden;
    animation: loaderSlide 1.2s ease-out forwards;
}}
.page-loader::after {{
    content: '';
    position: absolute; top: 0; left: -40%;
    width: 40%; height: 100%;
    background: linear-gradient(90deg, transparent, {PF_RED}, transparent);
    animation: loaderSweep 0.8s ease-in-out forwards;
}}
@keyframes loaderSweep {{
    0%   {{ left: -40%; }}
    100% {{ left: 100%; }}
}}
@keyframes loaderSlide {{
    0%   {{ opacity: 1; }}
    80%  {{ opacity: 1; }}
    100% {{ opacity: 0; }}
}}

/* ── KPI Metric Cards ── */
div[data-testid="stMetric"] {{
    background: {PF_SURFACE};
    border: 1px solid {PF_BORDER};
    border-left: 3px solid {PF_RED};
    border-radius: {PF_RADIUS};
    padding: 16px 20px;
    box-shadow: {PF_SHADOW};
    animation: fadeIn 0.4s ease-out both;
    transition: box-shadow 0.2s ease, border-color 0.2s ease;
}}
div[data-testid="stMetric"]:hover {{
    box-shadow: 0 20px 30px -8px rgba(99,102,241,0.12);
    border-color: {PF_RED};
    transform: translateY(-6px);
    animation: glowBorder 1.5s ease infinite;
}}
div[data-testid="stMetric"] label {{
    color: {PF_TEXT_SEC} !important;
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.04em !important;
}}
div[data-testid="stMetric"] [data-testid="stMetricValue"] {{
    color: {PF_TEXT} !important;
    font-size: 1.4rem !important;
    font-weight: 700 !important;
}}

/* ── Account Cards ── */
.acct-card {{
    background: {PF_SURFACE};
    border: 1px solid {PF_BORDER};
    border-radius: 16px;
    padding: 0;
    margin: 6px 0;
    height: 290px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02);
    transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
    animation: waterFlow 0.6s cubic-bezier(0.22, 1, 0.36, 1) both;
    position: relative;
    overflow: hidden;
}}
.acct-card:hover {{
    border-color: rgba(99,102,241,0.30);
    box-shadow: 0 20px 40px -12px rgba(99,102,241,0.18), 0 4px 12px rgba(0,0,0,0.05);
    transform: translateY(-6px) scale(1.008);
    cursor: pointer;
}}
.acct-card-header {{
    padding: 18px 20px 12px;
}}
.acct-name {{ color: {PF_TEXT}; font-size: 1rem; font-weight: 700; margin-bottom: 2px; line-height: 1.3; }}
.acct-meta {{
    color: {PF_TEXT_SEC}; font-size: 0.70rem;
    display: flex; align-items: center; gap: 4px; flex-wrap: wrap;
}}
.acct-metrics {{
    display: grid; grid-template-columns: repeat(3, 1fr);
    border-top: 1px solid rgba(226,232,240,0.6);
    border-bottom: 1px solid rgba(226,232,240,0.6);
}}
.acct-metric {{
    text-align: center; padding: 12px 4px;
    border-right: 1px solid rgba(226,232,240,0.6);
}}
.acct-metric:last-child {{ border-right: none; }}
.acct-metric-val {{
    color: {PF_TEXT}; font-size: 0.95rem; font-weight: 800; line-height: 1;
}}
.acct-metric-val.warn {{ color: #EF4444; }}
.acct-metric-lbl {{
    color: {PF_TEXT_SEC}; font-size: 0.62rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.04em;
    margin-top: 4px; opacity: 0.7;
}}
.acct-info {{
    padding: 8px 20px 16px;
    margin-top: auto;
}}
.acct-row  {{ display: flex; justify-content: space-between; padding: 3px 0; }}
.acct-lbl  {{ color: {PF_TEXT_SEC}; font-size: 0.74rem; }}
.acct-val  {{ color: {PF_TEXT}; font-size: 0.74rem; font-weight: 600; }}
.acct-val.warn {{ color: #EF4444; }}

/* ── Health Bar ── */
.health-bar-wrap {{
    padding: 0 20px 6px;
}}
.health-bar-track {{
    height: 5px; border-radius: 99px;
    background: rgba(226,232,240,0.6);
    overflow: hidden;
}}
.health-bar-fill {{
    height: 100%; border-radius: 99px;
    transition: width 1s cubic-bezier(0.22,1,0.36,1);
    animation: healthGrow 1.2s cubic-bezier(0.22,1,0.36,1) both;
    position: relative; overflow: hidden;
}}
.health-bar-fill::after {{
    content: '';
    position: absolute; top: 0; left: 0; right: 0; bottom: 0;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.35), transparent);
    background-size: 200% 100%;
    animation: progressGlow 1.8s ease 1.2s 1 both;
}}
@keyframes healthGrow {{
    from {{ width: 0; }}
}}

/* ── Health Score Badge ── */
.badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 9999px;
    font-size: 0.7rem;
    font-weight: 700;
}}
.badge-green  {{ background: {RH_GREEN}; color: {RH_WHITE}; }}
.badge-yellow {{ background: {RH_GOLD};  color: {RH_DARK_1}; }}
.badge-orange {{ background: {RH_ORANGE}; color: {RH_DARK_1}; }}
.badge-red    {{ background: {PF_RED};    color: {RH_WHITE}; }}

/* ── Contract Status ── */
.ctr        {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.7rem; font-weight: 600; }}
.ctr-active {{ background: rgba(62,134,53,0.12); color: {RH_GREEN}; border: 1px solid {RH_GREEN}; }}
.ctr-warn   {{ background: rgba(240,171,0,0.12); color: {RH_GOLD};  border: 1px solid {RH_GOLD}; }}
.ctr-exp    {{ background: rgba(239,68,68,0.10); color: #EF4444;   border: 1px solid #EF4444; }}

/* ── Back Bar ── */
.back-bar {{
    background: {PF_RED};
    padding: 10px 24px;
    border-radius: {PF_RADIUS};
    margin-bottom: 12px;
    cursor: pointer;
}}
.back-bar a {{
    color: {RH_WHITE} !important;
    text-decoration: none;
    font-weight: 600;
    font-size: 0.95rem;
}}

/* ── Detail Header ── */
.det-hdr {{
    background: {PF_SURFACE};
    border: 1px solid {PF_BORDER};
    border-top: 3px solid {PF_RED};
    border-radius: {PF_RADIUS};
    padding: 22px 26px;
    margin-bottom: 16px;
    animation: slideUp 0.4s ease-out both;
}}
.det-hdr h2 {{ color: {PF_TEXT}; margin: 0 0 4px 0; }}
.det-hdr p  {{ color: {PF_TEXT_SEC}; margin: 0; }}

/* ── Pagination ── */
.pg-bar {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 12px 0;
}}
.pg-num {{
    display: inline-block;
    padding: 4px 10px;
    border-radius: 9999px;
    font-size: 0.85rem;
    color: {PF_TEXT};
    cursor: pointer;
    border: 1px solid {PF_BORDER};
    background: {PF_SURFACE};
}}
.pg-num.active {{
    background: {PF_RED};
    color: {RH_WHITE};
    border-color: {PF_RED};
    font-weight: 700;
}}

/* ── Reduced Motion ── */
@media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }}
}}

/* ── Core Animations ── */
@keyframes fadeIn {{
    from {{ opacity: 0; }}
    to   {{ opacity: 1; }}
}}
@keyframes slideUp {{
    from {{ opacity: 0; transform: translateY(12px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
}}
@keyframes slideRight {{
    from {{ opacity: 0; transform: translateX(-12px); }}
    to   {{ opacity: 1; transform: translateX(0); }}
}}
@keyframes waterFlow {{
    0%   {{ opacity: 0; transform: translateY(18px) scale(0.97); filter: brightness(0.95); }}
    60%  {{ opacity: 0.7; transform: translateY(-4px) scale(1.005); filter: brightness(1.05); }}
    100% {{ opacity: 1; transform: translateY(0) scale(1); filter: brightness(1); }}
}}
@keyframes chartFadeIn {{
    from {{ opacity: 0; transform: translateY(16px) scale(0.98); }}
    to   {{ opacity: 1; transform: translateY(0) scale(1); }}
}}
@keyframes chartGlow {{
    0%   {{ box-shadow: 0 0 0 rgba(99,102,241,0); }}
    50%  {{ box-shadow: 0 0 20px rgba(99,102,241,0.06); }}
    100% {{ box-shadow: 0 0 0 rgba(99,102,241,0); }}
}}
@keyframes shimmer {{
    0%   {{ background-position: -200% 0; }}
    100% {{ background-position: 200% 0; }}
}}
@keyframes barGrow {{
    from {{ transform: scaleX(0); }}
    to   {{ transform: scaleX(1); }}
}}
@keyframes progressGlow {{
    0%   {{ background-position: -200% 0; }}
    100% {{ background-position: 200% 0; }}
}}
@keyframes sparkle {{
    0%   {{ transform: scale(1); filter: brightness(1); }}
    50%  {{ transform: scale(1.3); filter: brightness(1.4) drop-shadow(0 0 6px rgba(251,191,36,0.6)); }}
    100% {{ transform: scale(1); filter: brightness(1); }}
}}
@keyframes popupIn {{
    from {{ opacity: 0; transform: scale(0.92) translateY(8px); }}
    to   {{ opacity: 1; transform: scale(1) translateY(0); }}
}}
@keyframes rowSlideIn {{
    from {{ opacity: 0; transform: translateX(-8px); }}
    to   {{ opacity: 1; transform: translateX(0); }}
}}
@keyframes glowBorder {{
    0%,100% {{ border-color: rgba(99,102,241,0.15); }}
    50% {{ border-color: rgba(99,102,241,0.35); }}
}}
@keyframes skeletonPulse {{
    0%   {{ background-position: -200% 0; }}
    100% {{ background-position: 200% 0; }}
}}

/* ── Charts entrance ── */
[data-testid="stPlotlyChart"] {{
    animation: chartFadeIn 0.7s cubic-bezier(0.22,1,0.36,1) both,
               chartGlow 2.5s ease 0.7s both;
    border-radius: 12px;
    transition: transform 0.3s ease, box-shadow 0.3s ease;
}}
[data-testid="stPlotlyChart"]:nth-child(2) {{ animation-delay: 0.12s; }}
[data-testid="stPlotlyChart"]:nth-child(3) {{ animation-delay: 0.24s; }}
[data-testid="stPlotlyChart"]:hover {{
    transform: translateY(-4px);
    box-shadow: 0 12px 32px rgba(99,102,241,0.10), 0 4px 12px rgba(0,0,0,0.04);
}}

/* ── Metrics — shimmer sweep + stagger ── */
[data-testid="stMetric"] {{
    animation: waterFlow 0.6s cubic-bezier(0.22,1,0.36,1) both;
    position: relative;
    overflow: hidden;
}}
[data-testid="stMetric"]::after {{
    content: '';
    position: absolute; top: 0; left: 0; right: 0; bottom: 0;
    background: linear-gradient(90deg, transparent 0%, rgba(99,102,241,0.06) 50%, transparent 100%);
    background-size: 200% 100%;
    animation: shimmer 2s ease-in-out 0.6s 1 both;
    pointer-events: none; border-radius: inherit;
}}
[data-testid="stMetric"]:nth-of-type(2) {{ animation-delay: 0.05s; }}
[data-testid="stMetric"]:nth-of-type(3) {{ animation-delay: 0.10s; }}
[data-testid="stMetric"]:nth-of-type(4) {{ animation-delay: 0.15s; }}
[data-testid="stMetric"]:nth-of-type(5) {{ animation-delay: 0.20s; }}
[data-testid="stMetric"]:nth-of-type(6) {{ animation-delay: 0.25s; }}
[data-testid="stMetric"] [data-testid="stMetricDelta"] {{
    animation: slideRight 0.4s ease 0.8s both;
}}

/* ── Table rows stagger ── */
.stTabs [data-baseweb="tab-panel"] {{ animation: slideUp 0.4s ease-out both; }}
[data-testid="stDataFrame"] {{
    animation: waterFlow 0.6s cubic-bezier(0.22,1,0.36,1) 0.15s both;
}}
[data-testid="stDataFrame"] tr {{
    animation: rowSlideIn 0.35s ease both;
}}
[data-testid="stDataFrame"] tr:nth-child(1) {{ animation-delay: 0.05s; }}
[data-testid="stDataFrame"] tr:nth-child(2) {{ animation-delay: 0.09s; }}
[data-testid="stDataFrame"] tr:nth-child(3) {{ animation-delay: 0.13s; }}
[data-testid="stDataFrame"] tr:nth-child(4) {{ animation-delay: 0.17s; }}
[data-testid="stDataFrame"] tr:nth-child(5) {{ animation-delay: 0.21s; }}
[data-testid="stDataFrame"] tr:nth-child(6) {{ animation-delay: 0.25s; }}
[data-testid="stDataFrame"] tr:nth-child(7) {{ animation-delay: 0.29s; }}
[data-testid="stDataFrame"] tr:nth-child(8) {{ animation-delay: 0.33s; }}
[data-testid="stDataFrame"] tr:hover {{
    background: rgba(99,102,241,0.04) !important;
    border-left: 3px solid {PF_RED};
    transform: translateX(2px);
    transition: all 0.2s ease;
}}
.stMarkdown h3 {{ animation: fadeIn 0.3s ease-out both; }}

/* ── Popup / Modal ── */
[data-testid="stModal"] > div:first-child {{ animation: fadeIn 0.25s ease both; }}
div[role="dialog"] {{ animation: popupIn 0.35s cubic-bezier(0.34,1.56,0.64,1) both !important; }}

/* ── Favorite Star ── */
.fav-star {{
    cursor: pointer; font-size: 1.2rem;
    transition: transform 0.2s ease; display: inline-block;
}}
.fav-star:hover {{ transform: scale(1.25); }}
.fav-star.active {{ animation: sparkle 0.5s ease both; }}

/* ── Risk Distribution Bar ── */
.risk-bar-track {{
    display: flex; height: 12px; border-radius: 99px;
    overflow: hidden; background: #E2E8F0;
}}
.risk-bar-seg {{ height: 100%; transition: width 0.8s cubic-bezier(0.4,0,0.2,1); }}
.risk-legend {{
    display: flex; gap: 20px; margin-top: 8px;
    font-size: 0.78rem; align-items: center;
}}
.risk-dot {{
    width: 10px; height: 10px; border-radius: 50%;
    display: inline-block; margin-right: 5px;
}}

/* ── AI Skeleton ── */
.ai-skeleton {{
    background: linear-gradient(90deg, #F0F4F8 25%, #E2E8F0 50%, #F0F4F8 75%);
    background-size: 200% 100%;
    animation: skeletonPulse 1.5s ease-in-out infinite;
    border-radius: 8px; height: 16px; margin: 8px 0;
}}
.ai-skeleton.short {{ width: 60%; }}
.ai-skeleton.medium {{ width: 80%; }}

/* ── Saved Filter Pills ── */
.saved-filter-pill {{
    display: inline-flex; align-items: center; gap: 4px;
    padding: 4px 12px; border-radius: 9999px;
    font-size: 0.72rem; font-weight: 600;
    background: rgba(99,102,241,0.08);
    border: 1px solid rgba(99,102,241,0.15);
    color: {PF_TEXT}; cursor: pointer;
    transition: all 0.2s ease; animation: fadeIn 0.3s ease both;
}}
.saved-filter-pill:hover {{
    background: rgba(99,102,241,0.15);
    border-color: rgba(99,102,241,0.3);
    transform: translateY(-1px);
}}

/* ── Section Header Underline ── */
.stMarkdown h2::after, .stMarkdown h3::after {{
    content: '';
    display: block;
    width: 40px;
    height: 3px;
    background: linear-gradient(90deg, {PF_RED}, transparent);
    border-radius: 2px;
    margin-top: 6px;
}}

/* ── Button Hover / Active ── */
.stButton > button {{
    transition: transform 0.15s ease, box-shadow 0.2s ease, background 0.2s ease, color 0.2s ease !important;
}}
.stButton > button:hover {{
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 16px rgba(99,102,241,0.18) !important;
    background: #EEF2FF !important;
    border-color: #6366F1 !important;
    color: #1E293B !important;
}}
.stButton > button:active,
.stButton > button:focus {{
    transform: translateY(0) scale(0.98) !important;
    box-shadow: none !important;
    color: #1E293B !important;
    outline: none !important;
}}

/* ── Floating AI Chat FAB ── */
.ai-fab-wrap {{
    position: fixed;
    bottom: 32px;
    right: 32px;
    z-index: 10000;
    cursor: pointer;
}}
.ai-fab {{
    width: 56px;
    height: 56px;
    border-radius: 18px;
    background: linear-gradient(135deg, #6366F1, #8B5CF6);
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 6px 20px rgba(99,102,241,0.4);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
    position: relative;
}}
.ai-fab::after {{
    content: '';
    position: absolute;
    inset: -5px;
    border-radius: 22px;
    border: 2px solid rgba(99,102,241,0.3);
    animation: fabRing 2.5s ease-in-out infinite;
    pointer-events: none;
}}
@keyframes fabRing {{
    0%,100% {{ opacity: 0.6; transform: scale(1); }}
    50% {{ opacity: 0; transform: scale(1.2); }}
}}
.ai-fab:hover {{
    transform: scale(1.08);
    box-shadow: 0 8px 24px rgba(99,102,241,0.5);
}}
.ai-fab:active {{
    transform: scale(0.95);
    transition-duration: 0.1s;
}}
.ai-fab-icon {{
    display: flex;
    align-items: center;
    justify-content: center;
}}

/* ── Chat Dialog ── */
[data-testid="stModal"] > div:first-child {{
    background: rgba(15,23,42,0.35) !important;
    backdrop-filter: blur(6px) !important;
    -webkit-backdrop-filter: blur(6px) !important;
}}
div[role="dialog"]:has(.ai-chat-hdr) {{
    position: fixed !important;
    bottom: 84px !important;
    right: 32px !important;
    top: auto !important;
    left: auto !important;
    width: 400px !important;
    max-width: 90vw !important;
    max-height: 540px !important;
    margin: 0 !important;
    transform: none !important;
    border-radius: 20px !important;
    background: {PF_SURFACE} !important;
    border: 1px solid rgba(99,102,241,0.12) !important;
    box-shadow: 0 16px 48px rgba(99,102,241,0.15), 0 4px 16px rgba(0,0,0,0.1) !important;
    animation: slideUp 0.3s cubic-bezier(0.34,1.56,0.64,1) both !important;
    overflow: hidden !important;
}}

/* ── Chat Header ── */
.ai-chat-hdr {{
    background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 60%, #A78BFA 100%);
    padding: 16px 20px;
    display: flex;
    align-items: center;
    gap: 12px;
    border-bottom: none;
    margin: -1rem -1.5rem 0.5rem -1.5rem;
}}
.ai-chat-avatar {{
    width: 36px;
    height: 36px;
    border-radius: 12px;
    background: rgba(255,255,255,0.2);
    backdrop-filter: blur(8px);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}}
.ai-chat-hdr-text {{
    flex: 1;
    min-width: 0;
}}
.ai-chat-title {{
    color: #FFFFFF;
    font-weight: 700;
    font-size: 0.92rem;
    line-height: 1.3;
}}
.ai-chat-subtitle {{
    color: rgba(255,255,255,0.75);
    font-size: 0.68rem;
    font-weight: 400;
}}
.ai-chat-status {{
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.72rem;
    color: rgba(255,255,255,0.85);
    flex-shrink: 0;
}}
.ai-status-dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #4ADE80;
    display: inline-block;
    box-shadow: 0 0 6px rgba(74,222,128,0.6);
    animation: statusPulse 2s ease-in-out infinite;
}}
@keyframes statusPulse {{
    0%,100% {{ opacity:1; box-shadow: 0 0 6px rgba(74,222,128,0.6); }}
    50% {{ opacity:0.6; box-shadow: 0 0 12px rgba(74,222,128,0.4); }}
}}

/* ── Welcome Card ── */
.ai-welcome {{
    background: linear-gradient(180deg, rgba(99,102,241,0.04) 0%, {PF_SURFACE} 100%);
    border: 1px solid rgba(99,102,241,0.1);
    border-radius: 14px;
    padding: 20px;
    text-align: center;
}}
.ai-welcome h4 {{
    color: {PF_TEXT} !important;
    margin: 0 0 6px 0;
    font-size: 0.92rem;
}}
.ai-welcome p {{
    color: {PF_TEXT_SEC} !important;
    font-size: 0.78rem;
    margin: 0 0 14px 0;
    line-height: 1.5;
}}
.ai-suggestion {{
    background: rgba(99,102,241,0.06);
    border: 1px solid rgba(99,102,241,0.12);
    border-radius: 10px;
    padding: 10px 14px;
    color: {PF_TEXT} !important;
    font-size: 0.74rem;
    text-align: left;
    transition: all 0.2s ease;
    margin-bottom: 6px;
    cursor: pointer;
}}
.ai-suggestion:hover {{
    background: rgba(99,102,241,0.14);
    border-color: rgba(99,102,241,0.25);
    transform: translateX(4px);
}}

/* ── Chat Messages ── */
[data-testid="stChatMessage"] {{
    animation: fadeIn 0.3s ease-out both;
    border-radius: 12px !important;
    padding: 10px 14px !important;
    margin: 4px 0 !important;
}}

/* ── Responsive ── */
@media (max-width: 480px) {{
    div[role="dialog"]:has(.ai-chat-hdr) {{
        bottom: 0 !important;
        right: 0 !important;
        width: 100% !important;
        max-width: 100% !important;
        max-height: 90vh !important;
        border-radius: {PF_RADIUS} {PF_RADIUS} 0 0 !important;
    }}
    .ai-fab-wrap {{
        bottom: 20px;
        right: 20px;
    }}
    .ai-fab {{
        width: 48px;
        height: 48px;
        border-radius: 14px;
    }}
    .ai-fab svg {{
        width: 20px;
        height: 20px;
    }}
}}
@media (min-width: 481px) and (max-width: 768px) {{
    div[role="dialog"]:has(.ai-chat-hdr) {{
        width: 320px !important;
        bottom: 80px !important;
    }}
}}

/* ── Pills / Segmented Controls ── */
[data-testid="stPills"] > div,
[data-testid="stSegmentedControl"] > div {{
    background: linear-gradient(135deg, #FFFFFF 0%, #F8FAFC 100%) !important;
    border-radius: 14px !important;
    padding: 5px !important;
    border: 1.5px solid rgba(99,102,241,0.12) !important;
    box-shadow: 0 2px 8px rgba(99,102,241,0.06), 0 1px 3px rgba(0,0,0,0.03) !important;
    display: inline-flex !important;
    gap: 3px !important;
}}
[data-testid="stPills"] button,
[data-testid="stSegmentedControl"] button {{
    border-radius: 10px !important;
    border: none !important;
    padding: 9px 22px !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    color: #64748B !important;
    background: transparent !important;
    transition: all 0.25s cubic-bezier(0.4,0,0.2,1) !important;
    box-shadow: none !important;
    letter-spacing: 0.01em !important;
}}
[data-testid="stPills"] button[aria-checked="true"],
[data-testid="stPills"] button[data-active="true"],
[data-testid="stSegmentedControl"] button[aria-checked="true"],
[data-testid="stSegmentedControl"] button[data-active="true"] {{
    background: linear-gradient(135deg, #6366F1 0%, #818CF8 100%) !important;
    color: #FFFFFF !important;
    box-shadow: 0 4px 12px rgba(99,102,241,0.3), 0 1px 3px rgba(99,102,241,0.2) !important;
    font-weight: 700 !important;
}}
[data-testid="stPills"] button:hover,
[data-testid="stSegmentedControl"] button:hover {{
    background: rgba(99,102,241,0.08) !important;
    color: #4338CA !important;
}}
[data-testid="stPills"] label,
[data-testid="stSegmentedControl"] label {{
    display: none !important;
}}

/* ── Text Inputs ── */
div.stTextInput input {{
    border-radius: 10px !important;
    border: 1px solid #E2E8F0 !important;
    background: #FFFFFF !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04) !important;
    padding: 10px 16px !important;
    font-size: 0.85rem !important;
    color: #1E293B !important;
    font-family: "Red Hat Display", sans-serif !important;
    transition: all 0.2s ease !important;
    height: auto !important;
}}
div.stTextInput input:focus {{
    border-color: #6366F1 !important;
    box-shadow: 0 0 0 3px rgba(139,92,246,0.08) !important;
    outline: none !important;
}}
div.stTextInput input::placeholder {{
    color: #94A3B8 !important;
    font-weight: 400 !important;
}}
/* ── Header Search Bar (scoped to main_search key) ── */
div.stTextInput:has(input[aria-label="Search"]) input {{
    border-radius: 9999px !important;
    padding: 10px 36px 10px 38px !important;
    background: #FFFFFF url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%2394A3B8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.3-4.3'/%3E%3C/svg%3E") no-repeat 12px center !important;
    background-size: 16px !important;
}}
/* ── Search Clear Button ── */
.search-clear-btn {{
    position: absolute; right: 10px; top: 50%; transform: translateY(-50%);
    width: 22px; height: 22px; border-radius: 50%; border: none;
    background: #E2E8F0; color: #64748B; font-size: 13px; line-height: 22px;
    text-align: center; cursor: pointer; display: none; z-index: 2;
    padding: 0; transition: all 0.15s ease;
}}
.search-clear-btn:hover {{ background: #CBD5E1; color: #1E293B; }}

/* ── Selectbox ── */
div.stSelectbox [data-baseweb="select"] > div {{
    border-radius: 10px !important;
    border: 1px solid #E2E8F0 !important;
    background: #FFFFFF !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04) !important;
    padding: 2px 8px !important;
    transition: all 0.2s ease !important;
}}

/* ── Toggle ── */
[data-testid="stToggle"] {{
    background: #FFFFFF !important;
    border-radius: 12px !important;
    padding: 6px 16px !important;
    border: 1px solid #E2E8F0 !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04) !important;
    display: inline-flex !important;
    width: auto !important;
    margin-bottom: 12px !important;
}}
[data-testid="stToggle"] label {{
    gap: 10px !important;
    cursor: pointer !important;
}}
[data-testid="stToggle"] label p {{
    font-weight: 500 !important;
    font-size: 0.82rem !important;
    color: #475569 !important;
}}
[data-testid="stToggle"] label > span {{
    border-radius: 20px !important;
}}
[data-testid="stToggle"] input:checked ~ label > span {{
    background: #6366F1 !important;
}}
[data-testid="stToggle"] input:checked ~ label p {{
    color: #1E293B !important;
    font-weight: 600 !important;
}}

.ai-card {{
    background: var(--secondary-background-color, {PF_SURFACE});
    border: 1px solid var(--border-color, {PF_BORDER});
    border-left: 3px solid {PF_RED};
    border-radius: {PF_RADIUS};
    margin: 12px 0;
    overflow: hidden;
    animation: slideUp 0.4s ease both;
    transition: box-shadow 0.25s ease, border-color 0.25s ease;
    position: relative;
}}
.ai-card:hover {{
    box-shadow: {PF_SHADOW_H};
    border-color: {PF_BORDER_H};
}}
.ai-card-hdr {{
    display: flex; align-items: center; gap: 10px;
    padding: 14px 18px;
    border-bottom: 1px solid var(--border-color, {PF_BORDER});
}}
.ai-card-icon {{
    width: 28px; height: 28px; border-radius: {PF_RADIUS};
    background: {PF_RED};
    display: flex; align-items: center; justify-content: center;
    font-size: 12px; color: {RH_WHITE}; font-weight: 700; flex-shrink: 0;
}}
.ai-card-title {{
    font-weight: 600; font-size: 0.92rem;
    color: var(--text-color, {PF_TEXT});
}}
.ai-card-badge {{
    margin-left: auto; font-size: 0.68rem;
    color: var(--text-color, {PF_TEXT_SEC}); opacity: 0.55;
    white-space: nowrap;
}}
.ai-card-body {{
    padding: 16px 18px;
    font-size: 0.88rem; line-height: 1.65;
    color: var(--text-color, {PF_TEXT});
}}
.ai-card-body p {{ margin: 0 0 10px 0; }}
.ai-card-body p:last-child {{ margin-bottom: 0; }}
.ai-card-empty {{
    display: flex; align-items: center; gap: 10px;
    padding: 12px 18px;
}}
.ai-card-empty-icon {{
    width: 24px; height: 24px; border-radius: {PF_RADIUS};
    background: rgba(99,102,241,0.08);
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 12px; color: {PF_RED}; flex-shrink: 0;
}}
.ai-card-empty p {{
    color: var(--text-color, {PF_TEXT_SEC}); opacity: 0.6;
    font-size: 0.78rem; margin: 0;
}}

</style>
"""

st.markdown(_get_main_css(), unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# AI CARD HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _md_to_html(text):
    lines = text.split("\n")
    html_lines = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue
        if stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f'<h5 style="margin:8px 0 4px;font-size:0.85rem;font-weight:700;color:var(--text-color,{PF_TEXT});">{stripped[4:]}</h5>')
        elif stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f'<h4 style="margin:10px 0 4px;font-size:0.9rem;font-weight:700;color:var(--text-color,{PF_TEXT});">{stripped[3:]}</h4>')
        elif stripped.startswith("# "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f'<h3 style="margin:12px 0 6px;font-size:1rem;font-weight:700;color:var(--text-color,{PF_TEXT});">{stripped[2:]}</h3>')
        elif stripped.startswith(("- ", "* ")):
            if not in_list:
                html_lines.append('<ul style="margin:4px 0;padding-left:20px;">')
                in_list = True
            html_lines.append(f"<li>{stripped[2:]}</li>")
        elif len(stripped) > 2 and stripped[0].isdigit() and ". " in stripped[:4]:
            idx = stripped.index(". ")
            if not in_list:
                html_lines.append('<ol style="margin:4px 0;padding-left:20px;">')
                in_list = True
            html_lines.append(f"<li>{stripped[idx+2:]}</li>")
        else:
            if in_list:
                html_lines.append("</ul>" if html_lines[-2].startswith("<ul") or "<li>" in html_lines[-1] else "</ol>")
                in_list = False
            html_lines.append(f"<p style='margin:4px 0;'>{stripped}</p>")
    if in_list:
        html_lines.append("</ul>")
    result = "\n".join(html_lines)
    result = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', result)
    return result


def ai_card_html(title, content, show_badge=True):
    badge = '<span class="ai-card-badge">Powered by IBM Granite</span>' if show_badge else ''
    body = _md_to_html(content)
    return (
        f'<div class="ai-card">'
        f'<div class="ai-card-hdr">'
        f'<div class="ai-card-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.912 5.813a2 2 0 0 0 1.275 1.275L21 12l-5.813 1.912a2 2 0 0 0-1.275 1.275L12 21l-1.912-5.813a2 2 0 0 0-1.275-1.275L3 12l5.813-1.912a2 2 0 0 0 1.275-1.275L12 3Z"/></svg></div>'
        f'<span class="ai-card-title">{title}</span>'
        f'{badge}'
        f'</div>'
        f'<div class="ai-card-body">{body}</div>'
        f'</div>'
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADING (cached for fast reloads)
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600)
def load_all_data():
    engine = get_engine()
    accounts = pd.read_sql("SELECT * FROM accounts", engine)
    cases = pd.read_sql("SELECT * FROM support_cases", engine)
    associates = pd.read_sql("SELECT * FROM associates", engine)

    for col in ["contract_start_date", "contract_end_date", "created_at"]:
        if col in accounts.columns:
            accounts[col] = pd.to_datetime(accounts[col], errors="coerce")
    for col in ["creation_date", "last_updated", "resolution_date"]:
        if col in cases.columns:
            cases[col] = pd.to_datetime(cases[col], errors="coerce")
    if "hire_date" in associates.columns:
        associates["hire_date"] = pd.to_datetime(associates["hire_date"], errors="coerce")

    cases["csat_score"] = pd.to_numeric(cases["csat_score"], errors="coerce")
    cases["time_to_resolve_hours"] = pd.to_numeric(cases["time_to_resolve_hours"], errors="coerce")
    cases["escalated"] = cases["escalated"].astype(int)
    accounts["annual_revenue"] = pd.to_numeric(accounts["annual_revenue"], errors="coerce")

    return accounts, cases, associates


accounts_df, cases_df, associates_df = load_all_data()

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION PERSISTENCE (file-backed, survives browser refresh)
# ═══════════════════════════════════════════════════════════════════════════════

_SESSIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".sessions")
os.makedirs(_SESSIONS_DIR, exist_ok=True)

_PERSIST_KEYS = [
    "f_sectors", "f_products", "f_tiers", "f_regions", "f_revenue",
    "f_date_preset", "f_sort", "f_custom_from", "f_custom_to",
    "page", "det_p", "det_chart_dim", "op_grp", "_det_date_saved",
    "det_tab", "bookmarks", "saved_filters",
    "pinned_kpis", "_tour_seen",
]

def _sess_path(username):
    return os.path.join(_SESSIONS_DIR, hashlib.md5(username.encode()).hexdigest() + ".json")

def _save_session():
    username = st.session_state.get("username")
    if not username:
        return
    state = {}
    for k in _PERSIST_KEYS:
        if k in st.session_state:
            val = st.session_state[k]
            if isinstance(val, (list, tuple)):
                state[k] = [v.isoformat() if hasattr(v, "isoformat") else v for v in val]
            elif hasattr(val, "isoformat"):
                state[k] = val.isoformat()
            else:
                state[k] = val
    payload = json.dumps(state, sort_keys=True, default=str)
    new_hash = hashlib.md5(payload.encode()).hexdigest()
    if st.session_state.get("_sess_hash") == new_hash:
        return
    st.session_state["_sess_hash"] = new_hash
    try:
        with open(_sess_path(username), "w") as f:
            f.write(payload)
    except Exception:
        pass

def _load_session():
    username = st.session_state.get("username")
    if not username:
        return
    fpath = _sess_path(username)
    if not os.path.exists(fpath):
        return
    try:
        with open(fpath) as f:
            state = json.load(f)
    except Exception:
        return
    for k, v in state.items():
        if k in ("_det_date_saved", "f_custom_from", "f_custom_to") and isinstance(v, (list, str)):
            if isinstance(v, str):
                v = _date_type.fromisoformat(v)
            elif isinstance(v, list):
                v = [_date_type.fromisoformat(d) for d in v if d]
        st.session_state[k] = v


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ═══════════════════════════════════════════════════════════════════════════════

for k, v in [("selected_account", None), ("chat_history", []),
             ("ai_insight", None), ("page", 0), ("global_chat", []),
             ("authenticated", False), ("username", None),
             ("role", None), ("display_name", None),
             ("jwt_token", None), ("_workspace", None),
             ("bookmarks", []), ("saved_filters", {}),
             ("compare_ids", []), ("pinned_kpis", []),
             ("_bulk_ids", []), ("_anomaly_dismissed", []),
             ("_tour_step", 0), ("_tour_seen", False),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# ── Restore session from query-param JWT on refresh ──
if not st.session_state.get("authenticated") and st.query_params.get("token"):
    _qp_token = st.query_params["token"]
    _qp_payload = None
    try:
        _qp_payload = jwt.decode(_qp_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        _qp_payload = None
    if _qp_payload:
        _qp_role = _qp_payload.get("role", "associate")
        _qp_email = _qp_payload.get("sub", "")
        _qp_name = _qp_email
        if _qp_role == "admin":
            _qp_name = "System Administrator"
        elif _qp_role == "manager":
            _c = get_connection()
            _r = _c.execute(f"SELECT DISTINCT manager_name FROM associates WHERE LOWER(manager_email)={PARAM}", (_qp_email,)).fetchone()
            _c.close()
            if _r:
                _qp_name = _r[0]
        elif _qp_role == "associate":
            _c = get_connection()
            _r = _c.execute(f"SELECT associate_name FROM associates WHERE LOWER(email)={PARAM}", (_qp_email,)).fetchone()
            _c.close()
            if _r:
                _qp_name = _r[0]
        st.session_state.authenticated = True
        # A handoff token lives ~60s so the link cannot be reused. Trade it for
        # a full session token immediately, otherwise the next page refresh
        # would find an expired token in the URL and sign the user out.
        if _qp_payload.get("typ") == "handoff":
            _fresh = jwt.encode(
                {"sub": _qp_email, "role": _qp_role,
                 "iat": datetime.now(timezone.utc),
                 "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES),
                 "typ": "session"},
                JWT_SECRET, algorithm=JWT_ALGORITHM)
            _qp_token = _fresh
            st.query_params["token"] = _fresh
        st.session_state.jwt_token = _qp_token
        st.session_state.username = _qp_email
        st.session_state.role = _qp_role
        st.session_state.display_name = _qp_name
        st.session_state.login_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.session_state._workspace = "selected"
        _qp_view = st.query_params.get("view")
        if _qp_view:
            try:
                st.session_state.selected_account = _qp_view
            except (ValueError, TypeError):
                pass
        _load_session()
        st.rerun()

# ── Early workspace gate (skip heavy data loading if workspace not chosen) ──
if st.session_state.get("authenticated") and st.session_state.get("_workspace") != "selected":
    render_workspace_selector("customer")
    st.stop()

# ═══════════════════════════════════════════════════════════════════════════════
# AUTH HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _create_jwt(username, role, remember=False):
    from datetime import timezone, timedelta as td
    now = datetime.now(timezone.utc)
    exp = td(days=7) if remember else td(minutes=60)
    # typ marks this as a dashboard session token. The REST API refuses it,
    # so a token picked out of a URL cannot be replayed against the API.
    payload = {"sub": username, "role": role, "iat": now, "exp": now + exp,
               "typ": "session"}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _lookup_in_data(email, role):
    conn = get_connection()
    if role == "manager":
        row = conn.execute(
            f"SELECT DISTINCT manager_name FROM associates WHERE LOWER(manager_email) = {PARAM}",
            (email,)).fetchone()
        if row:
            conflict = conn.execute(
                f"SELECT 1 FROM associates WHERE LOWER(email) = {PARAM}", (email,)).fetchone()
            if conflict:
                conn.close()
                return None
    else:
        row = conn.execute(
            f"SELECT associate_name FROM associates WHERE LOWER(email) = {PARAM}",
            (email,)).fetchone()
        if row:
            conflict = conn.execute(
                f"SELECT 1 FROM associates WHERE LOWER(manager_email) = {PARAM}", (email,)).fetchone()
            if conflict:
                conn.close()
                return None
    conn.close()
    return row[0] if row else None


def register_user(email, password, role):
    email = email.strip().lower()
    if not email.endswith("@redhat.com"):
        return {"success": False, "message": "Only @redhat.com emails are allowed."}
    display_name = _lookup_in_data(email, role)
    if not display_name:
        other_role = "associate" if role == "manager" else "manager"
        if _lookup_in_data(email, other_role):
            return {"success": False,
                    "message": f"This email belongs to a {other_role} in the system. Please use the {other_role} login."}
        return {"success": False, "message": "Email not found in system. Contact your administrator."}
    conn = get_connection()
    existing = conn.execute(f"SELECT role FROM registered_users WHERE email = {PARAM}", (email,)).fetchone()
    if existing:
        conn.close()
        if existing[0] != role:
            return {"success": False, "message": f"This email is registered as {existing[0]}. Use the {existing[0]} tab to sign in."}
        return {"success": False, "message": "Already registered. Please login."}
    conn.execute(f"INSERT INTO registered_users (email, password_hash, role, display_name) VALUES ({PARAM}, {PARAM}, {PARAM}, {PARAM})",
                 (email, _get_pwd_ctx().hash(password), role, display_name))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Account created successfully. Please sign in."}


def reset_password(email, current_password, new_password, role):
    email = email.strip().lower()
    if not _lookup_in_data(email, role):
        return {"success": False, "message": "Email not found in system."}
    conn = get_connection()
    existing = conn.execute(f"SELECT role, password_hash FROM registered_users WHERE email = {PARAM}", (email,)).fetchone()
    if not existing:
        conn.close()
        return {"success": False, "message": "No account found. Please sign up first."}
    if existing[0] != role:
        conn.close()
        return {"success": False, "message": f"This email is registered as {existing[0]}. Use the {existing[0]} tab."}
    if not _get_pwd_ctx().verify(current_password, existing[1]):
        conn.close()
        return {"success": False, "message": "Current password is incorrect."}
    conn.execute(f"UPDATE registered_users SET password_hash = {PARAM} WHERE email = {PARAM}",
                 (_get_pwd_ctx().hash(new_password), email))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Password reset successfully. Please sign in."}


# Lockout state lives in the database (see login_guard) so it survives a
# restart and is shared by every replica. A process-local dict gave an
# attacker a fresh allowance per process.
def _check_rate_limit(email):
    return login_guard.check(email)


def _record_failed_login(email):
    login_guard.record_failure(email)


def _clear_login_attempts(email):
    login_guard.clear(email)


def authenticate(email, password, selected_role, remember=False):
    email = email.strip().lower()
    if selected_role == "admin":
        if email == ADMIN_EMAIL and _get_pwd_ctx().verify(password, _get_admin_hash()):
            return {"token": _create_jwt(email, "admin", remember), "role": "admin",
                    "display_name": "System Administrator"}
        return None
    if not _lookup_in_data(email, selected_role):
        return None
    conn = get_connection()
    row = conn.execute(f"SELECT password_hash, display_name, role FROM registered_users WHERE email = {PARAM}",
                       (email,)).fetchone()
    conn.close()
    if not row:
        return {"not_registered": True}
    if row[2] != selected_role:
        return None
    if not _get_pwd_ctx().verify(password, row[0]):
        return None
    return {"token": _create_jwt(email, selected_role, remember), "role": selected_role,
            "display_name": row[1]}


def check_session():
    token = st.session_state.get("jwt_token")
    if not token:
        return False
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return True
    except JWTError:
        for k in ["authenticated", "username", "role", "display_name", "jwt_token"]:
            if k in st.session_state:
                st.session_state[k] = None if k != "authenticated" else False
        if "token" in st.query_params:
            del st.query_params["token"]
        return False


def _validate_password_form(email, password, confirm):
    if not email or not password or not confirm:
        return "Please fill in all fields."
    if password != confirm:
        return "Passwords do not match."
    if len(password) < 6:
        return "Password must be at least 6 characters."
    return None




def render_login_page():
    show_error = st.session_state.pop("_login_error", False)
    error_msg = st.session_state.pop("_login_error_msg", "")
    show_success = st.session_state.pop("_login_success", False)
    success_msg = st.session_state.pop("_login_success_msg", "")

    if "login_step" not in st.session_state:
        st.session_state.login_step = "select"
    if "selected_login_role" not in st.session_state:
        st.session_state.selected_login_role = None

    st.markdown("""<style>
/* Red Hat Display loaded via system fallback */
[data-testid="stSidebar"]{display:none!important}
header[data-testid="stHeader"]{display:none!important}
#MainMenu{visibility:hidden}
footer{visibility:hidden}
.stApp{background:linear-gradient(135deg,#F5F3FF 0%,#F8F7F4 30%,#FDF2F8 60%,#F0FDF4 100%)!important;font-family:'Red Hat Display','Segoe UI',Roboto,sans-serif!important}
.block-container{max-width:920px!important;padding:20px 24px 40px!important;position:relative;z-index:1}

/* ── Animated Background Blobs ── */
.login-blobs{position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:0;pointer-events:none;overflow:hidden}
.blob{position:absolute;border-radius:50%;filter:blur(70px);opacity:0.7}
.blob-1{width:450px;height:450px;background:radial-gradient(circle,rgba(99,102,241,0.18),transparent 70%);top:-120px;right:-80px;animation:drift1 22s ease-in-out infinite}
.blob-2{width:380px;height:380px;background:radial-gradient(circle,rgba(59,130,246,0.3),transparent 70%);bottom:-100px;left:-60px;animation:drift2 18s ease-in-out infinite}
.blob-3{width:320px;height:320px;background:radial-gradient(circle,rgba(236,72,153,0.2),transparent 70%);top:35%;left:55%;animation:drift3 24s ease-in-out infinite}
.blob-4{width:280px;height:280px;background:radial-gradient(circle,rgba(6,182,212,0.25),transparent 70%);top:15%;left:8%;animation:drift4 20s ease-in-out infinite}
.blob-5{width:200px;height:200px;background:radial-gradient(circle,rgba(139,92,246,0.12),transparent 70%);bottom:25%;right:8%;animation:drift1 16s ease-in-out infinite reverse}
@keyframes drift1{0%,100%{transform:translate(0,0) scale(1)}25%{transform:translate(40px,-60px) scale(1.1)}50%{transform:translate(-20px,30px) scale(0.95)}75%{transform:translate(50px,40px) scale(1.05)}}
@keyframes drift2{0%,100%{transform:translate(0,0) scale(1)}25%{transform:translate(-50px,40px) scale(1.05)}50%{transform:translate(60px,-25px) scale(0.9)}75%{transform:translate(-30px,-50px) scale(1.1)}}
@keyframes drift3{0%,100%{transform:translate(0,0) scale(1)}25%{transform:translate(35px,55px) scale(0.9)}50%{transform:translate(-45px,-35px) scale(1.1)}75%{transform:translate(25px,-45px) scale(0.95)}}
@keyframes drift4{0%,100%{transform:translate(0,0) scale(1)}25%{transform:translate(-25px,-45px) scale(1.15)}50%{transform:translate(55px,25px) scale(0.85)}75%{transform:translate(-40px,35px) scale(1.05)}}

@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
@keyframes fadeUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-5px)}75%{transform:translateX(5px)}}
@keyframes iconBounce{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
@keyframes glowPulse{0%,100%{box-shadow:0 0 0 0 rgba(139,92,246,0.10)}50%{box-shadow:0 0 0 12px rgba(139,92,246,0)}}

/* ── Hero Section ── */
.login-hero{text-align:center;padding:10px 0 4px;animation:fadeUp 0.5s ease-out;position:relative;z-index:1}
.login-hero svg{filter:drop-shadow(0 4px 16px rgba(99,102,241,0.3));animation:float 4s ease-in-out infinite}
.login-hero .welcome-text{color:#6366F1;font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.2em;margin:4px 0 2px;animation:fadeUp 0.6s ease-out 0.2s both}
.login-hero h1{color:#1E293B;font-size:1.55rem;font-weight:800;margin:0 0 4px;letter-spacing:-0.02em;animation:fadeUp 0.6s ease-out 0.3s both}
.login-hero p{color:#64748B;font-size:0.85rem;margin:0 0 4px;animation:fadeUp 0.6s ease-out 0.4s both}

/* ── Glassmorphic Role Cards ── */
[data-testid="stVerticalBlockBorderWrapper"]{background:rgba(255,255,255,0.45)!important;backdrop-filter:blur(24px) saturate(180%)!important;-webkit-backdrop-filter:blur(24px) saturate(180%)!important;border:1px solid rgba(255,255,255,0.6)!important;border-radius:20px!important;overflow:hidden!important;transition:all 0.4s cubic-bezier(0.34,1.56,0.64,1)!important;box-shadow:0 8px 32px rgba(0,0,0,0.04),0 2px 8px rgba(0,0,0,0.03)!important;animation:fadeUp 0.6s ease-out both!important}
[data-testid="stVerticalBlockBorderWrapper"]:hover{background:rgba(255,255,255,0.7)!important;border-color:rgba(139,92,246,0.15)!important;transform:translateY(-8px) scale(1.02)!important;box-shadow:0 20px 48px rgba(0,0,0,0.08),0 8px 20px rgba(0,0,0,0.06)!important}
[data-testid="column"]:nth-child(1) [data-testid="stVerticalBlockBorderWrapper"]{border-top:3px solid #EF4444!important;animation-delay:0s!important}
[data-testid="column"]:nth-child(2) [data-testid="stVerticalBlockBorderWrapper"]{border-top:3px solid #3B82F6!important;animation-delay:0.12s!important}
[data-testid="column"]:nth-child(3) [data-testid="stVerticalBlockBorderWrapper"]{border-top:3px solid #10B981!important;animation-delay:0.24s!important}
[data-testid="column"]:nth-child(1) [data-testid="stVerticalBlockBorderWrapper"]:hover{border-color:#EF4444!important;box-shadow:0 20px 48px rgba(239,68,68,0.12),0 8px 20px rgba(0,0,0,0.06)!important}
[data-testid="column"]:nth-child(2) [data-testid="stVerticalBlockBorderWrapper"]:hover{border-color:#3B82F6!important;box-shadow:0 20px 48px rgba(59,130,246,0.12),0 8px 20px rgba(0,0,0,0.06)!important}
[data-testid="column"]:nth-child(3) [data-testid="stVerticalBlockBorderWrapper"]:hover{border-color:#10B981!important;box-shadow:0 20px 48px rgba(16,185,129,0.12),0 8px 20px rgba(0,0,0,0.06)!important}

/* ── Card Content ── */
.card-icon-circle{width:56px;height:56px;border-radius:16px;display:inline-flex;align-items:center;justify-content:center;margin-bottom:12px;font-size:26px;transition:all 0.4s cubic-bezier(0.34,1.56,0.64,1);animation:iconBounce 3s ease-in-out infinite}
[data-testid="stVerticalBlockBorderWrapper"]:hover .card-icon-circle{transform:scale(1.15) rotate(-8deg)}
.icon-admin{background:rgba(239,68,68,0.08);border:1.5px solid rgba(239,68,68,0.2)}
.icon-manager{background:rgba(59,130,246,0.08);border:1.5px solid rgba(59,130,246,0.2)}
.icon-associate{background:rgba(16,185,129,0.08);border:1.5px solid rgba(16,185,129,0.2)}
.card-role-name{color:#1E293B;font-size:1.05rem;font-weight:700;margin-bottom:5px}
.card-role-desc{color:#64748B;font-size:0.76rem;line-height:1.5;margin-bottom:14px}

/* ── Buttons ── */
.stButton > button[kind="primary"]{background:linear-gradient(135deg,#6366F1,#8B5CF6)!important;color:#fff!important;border:none!important;border-radius:12px!important;font-weight:700!important;font-size:12px!important;letter-spacing:.4px!important;padding:10px 20px!important;box-shadow:0 4px 15px rgba(139,92,246,0.3)!important;transition:all .3s cubic-bezier(0.34,1.56,0.64,1)!important}
.stButton > button[kind="primary"]:hover{background:linear-gradient(135deg,#4F46E5,#7C3AED)!important;color:#fff!important;transform:translateY(-2px) scale(1.02)!important;box-shadow:0 8px 25px rgba(139,92,246,0.4)!important}
.stButton > button[kind="primary"]:active,
.stButton > button[kind="primary"]:focus{background:linear-gradient(135deg,#4F46E5,#7C3AED)!important;color:#fff!important;transform:scale(0.97)!important;outline:none!important;box-shadow:0 4px 15px rgba(139,92,246,0.3)!important}

/* ── Role Tags ── */
.role-tag{display:inline-block;padding:5px 16px;border-radius:9999px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;animation:fadeUp 0.3s ease-out;backdrop-filter:blur(8px)}
.role-tag-admin{background:rgba(239,68,68,.1);color:#EF4444;box-shadow:0 2px 8px rgba(239,68,68,0.15)}
.role-tag-manager{background:rgba(59,130,246,.1);color:#3B82F6;box-shadow:0 2px 8px rgba(59,130,246,0.15)}
.role-tag-associate{background:rgba(16,185,129,.1);color:#10B981;box-shadow:0 2px 8px rgba(16,185,129,0.15)}

/* ── Messages ── */
.login-err{background:rgba(239,68,68,.08);backdrop-filter:blur(10px);border:1px solid rgba(239,68,68,.25);color:#DC2626;padding:10px 14px;border-radius:12px;font-size:12px;font-weight:600;text-align:center;animation:shake .4s}
.login-ok{background:rgba(34,197,94,.08);backdrop-filter:blur(10px);border:1px solid rgba(34,197,94,.25);color:#16A34A;padding:10px 14px;border-radius:12px;font-size:12px;font-weight:600;text-align:center}

/* ── Glassmorphic Form ── */
div[data-testid="stForm"]{background:rgba(255,255,255,0.45)!important;backdrop-filter:blur(24px) saturate(180%)!important;-webkit-backdrop-filter:blur(24px) saturate(180%)!important;border:1px solid rgba(255,255,255,0.6)!important;border-radius:20px!important;padding:28px 24px!important;box-shadow:0 8px 32px rgba(0,0,0,0.04),0 2px 8px rgba(0,0,0,0.03)!important;animation:fadeUp 0.4s ease-out both!important}
div[data-testid="stForm"] label{color:#64748B!important;font-size:11px!important;font-weight:600!important;text-transform:uppercase!important;letter-spacing:.04em!important}
div[data-testid="stForm"] input{background:rgba(248,250,252,0.6)!important;border:1px solid rgba(226,232,240,0.7)!important;color:#1E293B!important;border-radius:12px!important;font-size:14px!important;backdrop-filter:blur(5px)!important;transition:all 0.3s!important}
div[data-testid="stForm"] input:focus{border-color:#6366F1!important;box-shadow:0 0 0 3px rgba(139,92,246,.12)!important;background:rgba(255,255,255,0.85)!important}
div[data-testid="stForm"] button[type="submit"]{background:linear-gradient(135deg,#6366F1,#8B5CF6)!important;color:#fff!important;border:none!important;border-radius:12px!important;padding:12px 32px!important;font-weight:700!important;font-size:13px!important;letter-spacing:.5px!important;text-transform:uppercase!important;width:100%!important;transition:all .3s cubic-bezier(0.34,1.56,0.64,1)!important;box-shadow:0 4px 15px rgba(139,92,246,.3)!important}
div[data-testid="stForm"] button[type="submit"]:hover{background:linear-gradient(135deg,#4F46E5,#7C3AED)!important;color:#fff!important;transform:translateY(-2px)!important;box-shadow:0 8px 25px rgba(139,92,246,.4)!important}
div[data-testid="stForm"] button[type="submit"]:active,
div[data-testid="stForm"] button[type="submit"]:focus{background:linear-gradient(135deg,#4F46E5,#7C3AED)!important;color:#fff!important;outline:none!important;box-shadow:0 4px 15px rgba(139,92,246,.3)!important}
.stButton > button[kind="secondary"]{background:rgba(255,255,255,0.4)!important;backdrop-filter:blur(12px)!important;color:#64748B!important;border:1px solid rgba(226,232,240,0.5)!important;border-radius:12px!important;font-size:13px!important;font-weight:500!important;transition:all .3s!important}
.stButton > button[kind="secondary"]:hover{background:rgba(255,255,255,0.7)!important;border-color:#CBD5E1!important;color:#1E293B!important;transform:translateY(-1px)!important}
.stButton > button[kind="secondary"]:active,
.stButton > button[kind="secondary"]:focus{background:rgba(255,255,255,0.7)!important;color:#1E293B!important;outline:none!important;border-color:#CBD5E1!important}

/* ── Footer Stats ── */
.login-footer{text-align:center;padding:20px 0 0;animation:fadeUp 0.6s ease-out 0.5s both;position:relative;z-index:1}
.login-footer-item{display:inline-block;margin:0 14px;color:#94A3B8;font-size:0.72rem;font-weight:500}
.login-footer-item span{color:#64748B;font-weight:700}

</style>""", unsafe_allow_html=True)

    st.markdown(_html('''<div class="login-blobs">
        <div class="blob blob-1"></div>
        <div class="blob blob-2"></div>
        <div class="blob blob-3"></div>
        <div class="blob blob-4"></div>
        <div class="blob blob-5"></div>
    </div>'''), unsafe_allow_html=True)


    LOGO_SVG = '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" width="52" height="52" style="margin-bottom:12px"><circle cx="32" cy="32" r="30" fill="rgba(99,102,241,0.1)" stroke="#6366F1" stroke-width="2"/><rect x="14" y="34" width="8" height="14" rx="2" fill="#6366F1"/><rect x="24.5" y="24" width="8" height="24" rx="2" fill="#8B5CF6"/><rect x="35" y="18" width="8" height="30" rx="2" fill="#6366F1"/><rect x="45.5" y="28" width="8" height="20" rx="2" fill="#8B5CF6"/></svg>'

    role_labels = {
        "admin": ("Admin", "role-tag-admin"),
        "manager": ("Manager", "role-tag-manager"),
        "associate": ("Associate", "role-tag-associate"),
    }

    if st.session_state.login_step == "select":
        st.markdown(_html(f'''<div class="login-hero">
            {LOGO_SVG}
            <div class="welcome-text">Welcome to</div>
            <h1>Associates Analytics Platform</h1>
            <p>Select your role to continue</p>
        </div>'''), unsafe_allow_html=True)

        c1, c2, c3 = st.columns(3, gap="medium")
        with c1:
            with st.container(border=True):
                st.markdown(_html('''<div style="text-align:center;padding:4px 0">
                    <div class="card-icon-circle icon-admin"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/></svg></div>
                    <div class="card-role-name">Admin</div>
                    <div class="card-role-desc">Full system access</div>
                </div>'''), unsafe_allow_html=True)
                if st.button("Continue as Admin →", key="card_admin", use_container_width=True, type="primary"):
                    st.session_state.login_step = "form"
                    st.session_state.selected_login_role = "admin"
                    st.rerun()
        with c2:
            with st.container(border=True):
                st.markdown(_html('''<div style="text-align:center;padding:4px 0">
                    <div class="card-icon-circle icon-manager"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></div>
                    <div class="card-role-name">Manager</div>
                    <div class="card-role-desc">Team &amp; customer insights</div>
                </div>'''), unsafe_allow_html=True)
                if st.button("Continue as Manager →", key="card_manager", use_container_width=True, type="primary"):
                    st.session_state.login_step = "form"
                    st.session_state.selected_login_role = "manager"
                    st.rerun()
        with c3:
            with st.container(border=True):
                st.markdown(_html('''<div style="text-align:center;padding:4px 0">
                    <div class="card-icon-circle icon-associate"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8"/><path d="M12 17v4"/></svg></div>
                    <div class="card-role-name">Associate</div>
                    <div class="card-role-desc">Support &amp; case access</div>
                </div>'''), unsafe_allow_html=True)
                if st.button("Continue as Associate →", key="card_associate", use_container_width=True, type="primary"):
                    st.session_state.login_step = "form"
                    st.session_state.selected_login_role = "associate"
                    st.rerun()


    elif st.session_state.login_step == "form":
        role = st.session_state.selected_login_role or "associate"
        label, tag_cls = role_labels[role]
        _, form_col, _ = st.columns([1, 1.5, 1])
        with form_col:
            st.markdown(f'<div style="text-align:center;margin-bottom:4px"><span class="role-tag {tag_cls}">{label}</span></div>', unsafe_allow_html=True)
            st.markdown('<h2 style="text-align:center;color:#1E293B;font-size:1.2rem;font-weight:700;margin:0 0 16px">Sign In</h2>', unsafe_allow_html=True)
            if show_success:
                st.markdown(f'<div class="login-ok">{success_msg}</div>', unsafe_allow_html=True)
            if show_error:
                st.markdown(f'<div class="login-err">{error_msg or "Invalid email or password."}</div>', unsafe_allow_html=True)
            with st.form("login_form", clear_on_submit=False):
                email = st.text_input("Email", placeholder="name@redhat.com", key="login_email")
                password = st.text_input("Password", type="password", key="login_pass")
                remember = st.checkbox("Remember me", key="login_remember")
                submitted = st.form_submit_button("Sign In", use_container_width=True)
            if submitted:
                if not email or not password:
                    st.session_state._login_error = True
                    st.session_state._login_error_msg = "Please enter both email and password."
                    st.rerun()
                else:
                    _email_lower = email.strip().lower()
                    rate_msg = _check_rate_limit(_email_lower)
                    if rate_msg:
                        st.session_state._login_error = True
                        st.session_state._login_error_msg = rate_msg
                        st.rerun()
                    result = authenticate(email, password, role, remember=remember)
                    if result and isinstance(result, dict) and result.get("not_registered"):
                        _record_failed_login(_email_lower)
                        st.session_state._login_error = True
                        st.session_state._login_error_msg = "Account not found. Please sign up first."
                        st.rerun()
                    elif result and "token" in result:
                        _clear_login_attempts(_email_lower)
                        st.session_state.authenticated = True
                        st.session_state.jwt_token = result["token"]
                        st.session_state.username = _email_lower
                        st.session_state.role = result["role"]
                        st.session_state.display_name = result["display_name"]
                        st.session_state.login_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        st.session_state.login_step = "select"
                        st.session_state.selected_login_role = None
                        st.query_params["token"] = result["token"]
                        _load_session()
                        st.rerun()
                    else:
                        _record_failed_login(_email_lower)
                        st.session_state._login_error = True
                        st.session_state._login_error_msg = "Invalid credentials. Please check your email and password."
                        st.rerun()
            if role != "admin":
                col_forgot, col_signup = st.columns(2)
                with col_forgot:
                    if st.button("Forgot password?", key="goto_forgot", use_container_width=True):
                        st.session_state.login_step = "forgot"
                        st.rerun()
                with col_signup:
                    if st.button("Sign Up", key="goto_signup", use_container_width=True):
                        st.session_state.login_step = "signup"
                        st.rerun()
            else:
                if st.button("Forgot password?", key="goto_forgot_admin", use_container_width=True, disabled=True):
                    pass
            if st.button("Back", key="back_to_roles", use_container_width=True):
                st.session_state.login_step = "select"
                st.session_state.selected_login_role = None
                st.rerun()

    elif st.session_state.login_step == "signup":
        role = st.session_state.selected_login_role or "associate"
        label, tag_cls = role_labels[role]
        _, form_col, _ = st.columns([1, 1.5, 1])
        with form_col:
            st.markdown(f'<div style="text-align:center;margin-bottom:4px"><span class="role-tag {tag_cls}">{label}</span></div>', unsafe_allow_html=True)
            st.markdown('<h2 style="text-align:center;color:#1E293B;font-size:1.2rem;font-weight:700;margin:0 0 16px">Create Account</h2>', unsafe_allow_html=True)
            if show_error:
                st.markdown(f'<div class="login-err">{error_msg}</div>', unsafe_allow_html=True)
            with st.form("signup_form", clear_on_submit=False):
                s_email = st.text_input("Email", placeholder="name@redhat.com", key="signup_email")
                s_pass = st.text_input("Password", type="password", key="signup_pass")
                s_confirm = st.text_input("Confirm Password", type="password", key="signup_confirm")
                s_submitted = st.form_submit_button("Sign Up", use_container_width=True)
            if s_submitted:
                _vld_err = _validate_password_form(s_email, s_pass, s_confirm)
                if _vld_err:
                    st.session_state._login_error = True
                    st.session_state._login_error_msg = _vld_err
                    st.rerun()
                else:
                    result = register_user(s_email, s_pass, role)
                    if result["success"]:
                        st.session_state._login_success = True
                        st.session_state._login_success_msg = result["message"]
                        st.session_state.login_step = "form"
                        st.rerun()
                    else:
                        st.session_state._login_error = True
                        st.session_state._login_error_msg = result["message"]
                        st.rerun()
            if st.button("Already have an account? Sign In", key="goto_login", use_container_width=True):
                st.session_state.login_step = "form"
                st.rerun()
            if st.button("Back", key="back_to_roles_signup", use_container_width=True):
                st.session_state.login_step = "select"
                st.session_state.selected_login_role = None
                st.rerun()

    elif st.session_state.login_step == "forgot":
        role = st.session_state.selected_login_role or "associate"
        label, tag_cls = role_labels[role]
        _, form_col, _ = st.columns([1, 1.5, 1])
        with form_col:
            st.markdown(f'<div style="text-align:center;margin-bottom:4px"><span class="role-tag {tag_cls}">{label}</span></div>', unsafe_allow_html=True)
            st.markdown('<h2 style="text-align:center;color:#1E293B;font-size:1.2rem;font-weight:700;margin:0 0 16px">Reset Password</h2>', unsafe_allow_html=True)
            if show_success:
                st.markdown(f'<div class="login-ok">{success_msg}</div>', unsafe_allow_html=True)
            if show_error:
                st.markdown(f'<div class="login-err">{error_msg}</div>', unsafe_allow_html=True)
            with st.form("forgot_form", clear_on_submit=False):
                f_email = st.text_input("Email", placeholder="name@redhat.com", key="forgot_email")
                f_current = st.text_input("Current Password", type="password", key="forgot_current")
                f_pass = st.text_input("New Password", type="password", key="forgot_pass")
                f_confirm = st.text_input("Confirm New Password", type="password", key="forgot_confirm")
                f_submitted = st.form_submit_button("Reset Password", use_container_width=True)
            if f_submitted:
                if not f_current:
                    st.session_state._login_error = True
                    st.session_state._login_error_msg = "Please enter your current password."
                    st.rerun()
                _vld_err = _validate_password_form(f_email, f_pass, f_confirm)
                if _vld_err:
                    st.session_state._login_error = True
                    st.session_state._login_error_msg = _vld_err
                    st.rerun()
                else:
                    result = reset_password(f_email, f_current, f_pass, role)
                    if result["success"]:
                        st.session_state._login_success = True
                        st.session_state._login_success_msg = result["message"]
                        st.session_state.login_step = "form"
                        st.rerun()
                    else:
                        st.session_state._login_error = True
                        st.session_state._login_error_msg = result["message"]
                        st.rerun()
            if st.button("Back to Sign In", key="goto_login_forgot", use_container_width=True):
                st.session_state.login_step = "form"
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def health_score(acc_cases):
    """0-100 composite score from CSAT, escalation rate, resolution time, close ratio."""
    n = len(acc_cases)
    if n == 0:
        return 50.0
    csat = acc_cases["csat_score"].mean()
    csat_pts = (csat / 5.0 * 40) if pd.notna(csat) else 20.0
    esc_rate = acc_cases["escalated"].sum() / n
    esc_pts = max(0, 25 * (1 - esc_rate * 5))
    closed = acc_cases["status"].isin(["Resolved", "Closed"]).sum()
    close_pts = (closed / n) * 20
    ttr = acc_cases["time_to_resolve_hours"].mean()
    ttr_pts = max(0, 15 * (1 - min(ttr, 720) / 720)) if pd.notna(ttr) else 7.5
    return round(min(100, csat_pts + esc_pts + close_pts + ttr_pts), 1)


def health_html(score):
    if score >= 75:
        c = "badge-green"
    elif score >= 55:
        c = "badge-yellow"
    elif score >= 35:
        c = "badge-orange"
    else:
        c = "badge-red"
    return f'<span class="badge {c}">{score}</span>'


def contract_html(end_date):
    if pd.isna(end_date):
        return ""
    today = pd.Timestamp.now()
    if end_date < today:
        return '<span class="ctr ctr-exp">Expired</span>'
    elif end_date < today + pd.Timedelta(days=90):
        return '<span class="ctr ctr-warn">Expiring Soon</span>'
    return '<span class="ctr ctr-active">Active</span>'


def _get_ai_session():
    if "_ai_session" not in st.session_state:
        s = requests.Session()
        s.headers.update({
            "Authorization": f"Bearer {AI_API_TOKEN}",
            "Content-Type": "application/json",
        })
        s.verify = False
        st.session_state["_ai_session"] = s
    return st.session_state["_ai_session"]


def call_ai(messages, max_tokens=512):
    if not all([AI_ENDPOINT_URL, AI_API_TOKEN, AI_MODEL_ID]):
        return None
    try:
        resp = _get_ai_session().post(
            f"{AI_ENDPOINT_URL}/chat/completions",
            json={"model": AI_MODEL_ID, "messages": messages,
                  "max_tokens": max_tokens, "temperature": 0.2},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except requests.exceptions.Timeout:
        return "The AI took too long to respond. Please try a shorter question."
    except requests.exceptions.ConnectionError:
        return "Could not connect to AI endpoint. The server may be down or unreachable."
    except requests.exceptions.HTTPError as e:
        return f"AI endpoint returned an error (HTTP {e.response.status_code}). Please try again."
    except Exception:
        return None


def _sanitize_ai_input(text):
    cleaned = re.sub(r'<[^>]+>', '', str(text)).strip()
    return cleaned[:500] if cleaned else ""


def _sanitize_ai_output(text):
    if not text:
        return text
    out = re.sub(r'<\s*(script|iframe|object|embed|style)[^>]*>.*?</\s*\1\s*>', '', text, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r'<\s*(script|iframe|object|embed|style)[^>]*/?\s*>', '', out, flags=re.IGNORECASE)
    out = re.sub(r'\bon\w+\s*=\s*["\'][^"\']*["\']', '', out, flags=re.IGNORECASE)
    out = re.sub(r'javascript\s*:', '', out, flags=re.IGNORECASE)
    return out


def local_summary(account_name, c):
    """Structured fallback summary when AI endpoint is unavailable."""
    n = len(c)
    if n == 0:
        return f"No support cases recorded for **{account_name}** in the selected period."
    esc = int(c["escalated"].sum())
    avg_csat = c["csat_score"].mean()
    avg_ttr = c["time_to_resolve_hours"].mean()
    top_prod = c["product_name"].value_counts().head(3)
    open_c = len(c[c["status"].isin(["Open", "In Progress", "Waiting on Customer", "Waiting on Engineering"])])
    resolved = len(c[c["status"].isin(["Resolved", "Closed"])])
    res_rate = resolved / n * 100 if n else 0
    esc_rate = esc / n * 100 if n else 0
    ttr_str = f"{avg_ttr:.0f} hours" if pd.notna(avg_ttr) else "N/A"
    sevs = c["severity"].value_counts()
    sev_lines = " | ".join(f"{s}: {v}" for s, v in sevs.items())

    esc_products = c[c["escalated"] == 1]["product_name"].value_counts()
    esc_top = esc_products.index[0] if len(esc_products) > 0 else None

    csat_note = "Excellent" if avg_csat >= 4.5 else ("Good" if avg_csat >= 3.5 else ("Needs Improvement" if avg_csat >= 2.5 else "Critical"))
    if avg_csat >= 4.0 and esc_rate < 10:
        health = "Healthy"
    elif avg_csat >= 3.0:
        health = "Moderate — monitor closely"
    else:
        health = "At Risk — immediate attention needed"

    lines = [
        f"### Account Analysis — {account_name}\n",
        f"**Account Health:** {health}\n",
        f"**Case Overview:** {n} total cases | {resolved} resolved ({res_rate:.0f}%) | {open_c} open\n",
        f"**Quality Metrics:**",
        f"- CSAT Score: **{avg_csat:.1f}/5** ({csat_note})",
        f"- Avg Resolution Time: **{ttr_str}**",
        f"- Escalations: **{esc}** ({esc_rate:.1f}% rate)\n",
        f"**Severity Breakdown:** {sev_lines}\n",
        f"**Top Products:** {', '.join(f'{p} ({v} cases)' for p, v in top_prod.items())}\n",
    ]
    if esc_top:
        lines.append(f"**Escalation Focus:** Most escalations related to **{esc_top}**\n")
    lines.append(f"### Recommendations\n")
    recs = []
    if esc_rate > 20:
        recs.append(f"High escalation rate ({esc_rate:.0f}%) — assign a dedicated SME for **{top_prod.index[0]}** "
                     f"({top_prod.iloc[0]} cases) to reduce repeat escalations.")
    if pd.notna(avg_ttr) and avg_ttr > 200:
        recs.append(f"Average resolution time is **{avg_ttr:.0f} hours** — consider priority queuing for "
                     f"high-severity cases to bring TTR below 150 hours.")
    if res_rate < 50:
        recs.append(f"Resolution rate is only **{res_rate:.0f}%** ({open_c} open cases) — "
                     f"review blocked cases for reassignment or escalation path improvement.")
    if pd.notna(avg_csat) and avg_csat < 3.5:
        recs.append(f"CSAT at **{avg_csat:.1f}/5** needs improvement — schedule post-resolution follow-ups "
                     f"on the next 10 cases to identify recurring pain points.")
    if esc_top:
        esc_count = esc_products.iloc[0]
        recs.append(f"**{esc_top}** has {esc_count} escalation(s) — review root cause and "
                     f"consider proactive knowledge base updates for this product.")
    if not recs:
        recs.append(f"Account in good standing — CSAT {avg_csat:.1f}/5, escalation rate {esc_rate:.1f}%. "
                     f"Maintain current support cadence and consider this account for case study reference.")
    for r in recs:
        lines.append(f"- {r}")

    return "\n".join(lines)


def build_context(name, c):
    """Build stats context string for AI prompts."""
    n = len(c)
    if n == 0:
        return f"Account: {name}\nNo cases in selected period."
    esc = int(c["escalated"].sum())
    prods = c["product_name"].value_counts().head(5)
    sevs = c["severity"].value_counts()
    stats = c["status"].value_counts()
    owners = c["case_owner"].value_counts().head(5)
    esc_probs = c[c["escalated"] == 1]["problem_statement"].tolist()[:5]
    case_cols = ["case_number", "severity", "status", "product_name", "csat_score", "escalated"]
    case_table = c[case_cols].head(15).fillna({"csat_score": "Pending"}).to_string(index=False)
    return (
        f"Account: {name}\n"
        f"Total Cases: {n} | Escalations: {esc} ({esc/n*100:.1f}%)\n"
        f"Avg CSAT: {(f'{_avg_c:.1f}' if pd.notna(_avg_c := c['csat_score'].mean()) else 'N/A')}/5.0 | "
        f"Avg Resolution: {(f'{_avg_t:.0f}' if pd.notna(_avg_t := c['time_to_resolve_hours'].mean()) else 'N/A')} hrs\n"
        f"Products: {', '.join(f'{p} ({v})' for p,v in prods.items())}\n"
        f"Severity: {', '.join(f'{s}: {v}' for s,v in sevs.items())}\n"
        f"Status: {', '.join(f'{s}: {v}' for s,v in stats.items())}\n"
        f"Top Engineers: {', '.join(f'{o} ({v})' for o,v in owners.items())}\n"
        f"Escalated Issues: {'; '.join(esc_probs[:3]) if esc_probs else 'None'}\n\n"
        f"Cases (latest 15):\n{case_table}"
    )


def _generate_and_store_insight(acc_name, acc_cases, system_prompt):
    ctx = build_context(acc_name, acc_cases)
    msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Summarize this account:\n\n{ctx}"},
    ]
    with st.spinner("Generating insight..."):
        result = call_ai(msgs)
    if result:
        st.session_state.ai_insight = result
    else:
        st.session_state.ai_insight = local_summary(acc_name, acc_cases)


# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR FILTERS (only rendered when authenticated)
# ═══════════════════════════════════════════════════════════════════════════════

account_search = ""
selected_sectors = []
selected_products = []
selected_tiers = []
selected_regions = []
selected_revenue = []
date_preset = "All Time"
date_start, date_end = None, None
sort_by = "Total Cases (High to Low)"

if st.session_state.get("authenticated", False):
    user_role = st.session_state.get("role", "associate")
    role_cfg = {
        "admin":     {"color": "#6366F1", "icon": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/></svg>', "label": "Admin"},
        "manager":   {"color": "#F59E0B", "icon": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="14" x="2" y="7" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>', "label": "Manager"},
        "associate": {"color": "#3B82F6", "icon": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>', "label": "Associate"},
    }
    rc = role_cfg.get(user_role, role_cfg["associate"])
    st.sidebar.markdown(_html(f"""
    <div style="background:var(--secondary-background-color,{PF_SURFACE});
        border:1px solid var(--border-color,{PF_BORDER}); border-radius:{PF_RADIUS};
        border-top:3px solid {rc['color']};
        padding:14px 16px; margin-bottom:14px;
        box-shadow:{PF_SHADOW};">
        <div style="display:flex;align-items:center;gap:10px;">
            <div style="width:36px;height:36px;border-radius:{PF_RADIUS};background:{rc['color']};
                display:flex;align-items:center;justify-content:center;
                font-size:16px;color:#FFFFFF;font-weight:700;">
                {rc['icon']}
            </div>
            <div style="flex:1;min-width:0;">
                <div style="color:var(--text-color,{PF_TEXT});font-weight:700;font-size:0.9rem;">
                    {st.session_state.get('display_name','User')}
                </div>
                <span style="display:inline-block;padding:2px 8px;
                    border-radius:{PF_RADIUS};font-size:0.62rem;font-weight:700;
                    background:{rc['color']};color:#FFFFFF;
                    text-transform:uppercase;letter-spacing:0.04em;margin-top:3px;">
                    {rc['label']}
                </span>
                <div style="font-size:0.6rem;color:var(--text-color,{PF_TEXT_SEC});opacity:0.45;margin-top:4px;">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:2px"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> {st.session_state.get('login_time','')}
                </div>
            </div>
        </div>
    </div>
    """), unsafe_allow_html=True)

    if st.sidebar.button("Log Out", key="sidebar_logout", use_container_width=True):
        try:
            os.remove(_sess_path(st.session_state.get("username", "")))
        except Exception:
            pass
        for k in ["authenticated", "username", "role", "display_name",
                  "jwt_token", "selected_account", "ai_insight",
                  "chat_history", "global_chat", "login_time", "_workspace"]:
            if k in st.session_state:
                del st.session_state[k]
        for _qk in ["token", "view"]:
            if _qk in st.query_params:
                del st.query_params[_qk]
        st.rerun()

    st.sidebar.markdown(f'<div style="height:1px;background:linear-gradient(90deg,transparent,{PF_BORDER},transparent);margin:16px 0;"></div>', unsafe_allow_html=True)

    _sel_acct = st.session_state.get("selected_account")
    if _sel_acct:
        _sb_match = accounts_df[accounts_df["account_id"] == _sel_acct]
        if not _sb_match.empty:
            _sb_acc = _sb_match.iloc[0]
            _sb_cases = cases_df[cases_df["account_id"] == _sel_acct]
            _sb_h = health_score(_sb_cases)
            _sb_n = len(_sb_cases)
            _sb_esc = int(_sb_cases["escalated"].sum()) if _sb_n else 0
            _sb_csat = _sb_cases["csat_score"].mean()
            _sb_hclr = "#10B981" if _sb_h >= 75 else ("#F59E0B" if _sb_h >= 50 else "#EF4444")
            st.sidebar.markdown(f'<p style="color:var(--text-color,{PF_TEXT});font-size:0.9rem;font-weight:700;margin-bottom:8px;">Account Details</p>', unsafe_allow_html=True)
            st.sidebar.markdown(_html(f"""<div style="background:var(--secondary-background-color,{PF_SURFACE});
                border:1px solid var(--border-color,{PF_BORDER});border-radius:{PF_RADIUS};padding:14px 16px;margin-bottom:12px;">
                <div style="font-weight:800;font-size:0.95rem;color:var(--text-color,{PF_TEXT});margin-bottom:8px;">{_sb_acc['account_name']}</div>
                <div style="font-size:0.75rem;color:{PF_TEXT_SEC};margin-bottom:12px;">{_sb_acc['account_id']} &middot; {_sb_acc['sector']} &middot; {_sb_acc['region']}</div>
                <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px dashed {PF_BORDER};">
                    <span style="font-size:0.78rem;color:{PF_TEXT_SEC};">Health Score</span>
                    <span style="font-size:0.78rem;font-weight:700;color:{_sb_hclr};">{_sb_h:.0f}/100</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px dashed {PF_BORDER};">
                    <span style="font-size:0.78rem;color:{PF_TEXT_SEC};">Total Cases</span>
                    <span style="font-size:0.78rem;font-weight:700;color:var(--text-color,{PF_TEXT});">{_sb_n}</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px dashed {PF_BORDER};">
                    <span style="font-size:0.78rem;color:{PF_TEXT_SEC};">Escalations</span>
                    <span style="font-size:0.78rem;font-weight:700;color:{'#EF4444' if _sb_esc > 0 else PF_TEXT};">{_sb_esc}</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px dashed {PF_BORDER};">
                    <span style="font-size:0.78rem;color:{PF_TEXT_SEC};">Avg CSAT</span>
                    <span style="font-size:0.78rem;font-weight:700;color:var(--text-color,{PF_TEXT});">{f'{_sb_csat:.1f}/5' if pd.notna(_sb_csat) else 'N/A'}</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px dashed {PF_BORDER};">
                    <span style="font-size:0.78rem;color:{PF_TEXT_SEC};">Support Tier</span>
                    <span style="font-size:0.78rem;font-weight:700;color:var(--text-color,{PF_TEXT});">{_sb_acc['support_tier']}</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:6px 0;">
                    <span style="font-size:0.78rem;color:{PF_TEXT_SEC};">Contract</span>
                    <span style="font-size:0.78rem;font-weight:700;color:var(--text-color,{PF_TEXT});">{_sb_acc.get('contract_status', 'N/A')}</span>
                </div>
            </div>"""), unsafe_allow_html=True)
            if _sb_n > 0:
                _sb_sevs = _sb_cases["severity"].value_counts()
                _sev_colors = {"Urgent": "#EF4444", "High": "#F59E0B", "Medium": "#3B82F6", "Low": "#10B981"}
                _sb_sev_html = "".join(
                    f'<div style="display:flex;justify-content:space-between;padding:4px 0;">'
                    f'<div style="display:flex;align-items:center;gap:6px;">'
                    f'<div style="width:8px;height:8px;border-radius:50%;background:{_sev_colors.get(s, PF_TEXT_SEC)};"></div>'
                    f'<span style="font-size:0.75rem;color:var(--text-color,{PF_TEXT});">{s}</span></div>'
                    f'<span style="font-size:0.75rem;font-weight:700;color:var(--text-color,{PF_TEXT});">{v}</span></div>'
                    for s, v in _sb_sevs.items()
                )
                st.sidebar.markdown(_html(f"""<div style="background:var(--secondary-background-color,{PF_SURFACE});
                    border:1px solid var(--border-color,{PF_BORDER});border-radius:{PF_RADIUS};padding:14px 16px;margin-bottom:12px;">
                    <div style="font-size:0.78rem;font-weight:700;color:var(--text-color,{PF_TEXT});margin-bottom:8px;">Severity Breakdown</div>
                    {_sb_sev_html}
                </div>"""), unsafe_allow_html=True)
        st.sidebar.markdown(f'<div style="height:1px;background:linear-gradient(90deg,transparent,{PF_BORDER},transparent);margin:16px 0;"></div>', unsafe_allow_html=True)

    if not st.session_state.get("selected_account"):
        # ── Apply pending preset before widgets render ──
        _pending_preset = st.session_state.pop("_apply_preset", None)
        if _pending_preset:
            _saved_f_pre = st.session_state.get("saved_filters", {})
            if _pending_preset in _saved_f_pre:
                for fk, fv in _saved_f_pre[_pending_preset].items():
                    st.session_state[fk] = fv
                st.toast(f"Filter '{_pending_preset}' applied!")

        # ── Saved Presets (above filters) ──
        _saved_f = st.session_state.get("saved_filters", {})
        if _saved_f:
            st.sidebar.markdown(f'<p style="color:var(--text-color,{PF_TEXT});font-size:0.9rem;font-weight:700;margin-bottom:8px;">Saved Presets ({len(_saved_f)})</p>', unsafe_allow_html=True)
            _confirm_del = st.session_state.get("_confirm_del_preset")
            for fname, fvals in _saved_f.items():
                if _confirm_del == fname:
                    st.sidebar.markdown(
                        f'<div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.25);'
                        f'border-radius:10px;padding:10px 12px;margin-bottom:8px;">'
                        f'<div style="font-size:0.78rem;color:#DC2626;font-weight:600;margin-bottom:6px;">'
                        f'Delete "{fname}"?</div></div>', unsafe_allow_html=True)
                    _dc1, _dc2 = st.sidebar.columns(2)
                    with _dc1:
                        if st.button("Delete", key=f"sb_sf_yes_{fname}", use_container_width=True, type="primary"):
                            del st.session_state["saved_filters"][fname]
                            st.session_state.pop("_confirm_del_preset", None)
                            st.toast(f"Preset '{fname}' deleted")
                            st.rerun()
                    with _dc2:
                        if st.button("Cancel", key=f"sb_sf_no_{fname}", use_container_width=True):
                            st.session_state.pop("_confirm_del_preset", None)
                            st.rerun()
                else:
                    _sb_c1, _sb_c2 = st.sidebar.columns([3, 1])
                    with _sb_c1:
                        if st.button(f"📋 {fname}", key=f"sb_sf_{fname}", use_container_width=True):
                            st.session_state["_apply_preset"] = fname
                            st.rerun()
                    with _sb_c2:
                        if st.button("🗑️", key=f"sb_sf_del_{fname}", help=f"Delete '{fname}'"):
                            st.session_state["_confirm_del_preset"] = fname
                            st.rerun()
            st.sidebar.divider()

        st.sidebar.markdown(f'<p style="color:var(--text-color,{PF_TEXT});font-size:0.9rem;font-weight:700;margin-bottom:8px;">Filters</p>', unsafe_allow_html=True)

        selected_sectors  = st.sidebar.multiselect("Sector", sorted(accounts_df["sector"].dropna().unique()), key="f_sectors")
        selected_products = st.sidebar.multiselect("Products", sorted(cases_df["product_name"].dropna().unique()), key="f_products")
        selected_tiers    = st.sidebar.multiselect("Support Tier (Entitlement)", sorted(accounts_df["support_tier"].dropna().unique()), key="f_tiers")
        selected_regions  = st.sidebar.multiselect("Region", sorted(accounts_df["region"].dropna().unique()), key="f_regions")
        selected_revenue  = st.sidebar.multiselect("Revenue Segment", sorted(accounts_df["revenue_segment"].dropna().unique()), key="f_revenue")

        date_preset = st.sidebar.selectbox(
            "Date Range",
            ["All Time", "Today", "Yesterday", "Last 7 Days", "Last 30 Days", "Last Quarter", "Custom"],
            key="f_date_preset",
        )

        now = datetime.now()
        date_start, date_end = None, None

        if date_preset == "Today":
            date_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            date_end = now
        elif date_preset == "Yesterday":
            date_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            date_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif date_preset == "Last 7 Days":
            date_start, date_end = now - timedelta(days=7), now
        elif date_preset == "Last 30 Days":
            date_start, date_end = now - timedelta(days=30), now
        elif date_preset == "Last Quarter":
            date_start, date_end = now - timedelta(days=90), now
        elif date_preset == "Custom":
            min_d = cases_df["creation_date"].min().date() if cases_df["creation_date"].notna().any() else now.date() - timedelta(days=365)
            max_d = cases_df["creation_date"].max().date() if cases_df["creation_date"].notna().any() else now.date()
            c1, c2 = st.sidebar.columns(2)
            d1 = c1.date_input("From", min_d, min_value=min_d, max_value=max_d, key="f_custom_from")
            d2 = c2.date_input("To", max_d, min_value=min_d, max_value=max_d, key="f_custom_to")
            date_start = pd.Timestamp(d1)
            date_end = pd.Timestamp(d2) + timedelta(days=1)

        sort_by = st.sidebar.selectbox("Sort Accounts By", [
            "Total Cases (High to Low)",
            "Escalations (High to Low)",
            "CSAT (Low to High)",
            "Revenue (High to Low)",
            "Health Score (Low to High)",
            "Account Name",
        ], key="f_sort")

        st.sidebar.divider()
        if st.sidebar.button("Save Current Filters", key="sb_save_filter_btn",
                             use_container_width=True, icon=":material/bookmark_add:"):
            st.session_state["_show_save_filter"] = True

        with st.sidebar.expander("Export Data", expanded=False, icon=":material/download:"):
            _export_df = accounts_df[["account_id", "account_name", "sector", "region",
                                       "support_tier", "revenue_segment"]].copy()
            _export_df.columns = ["Account ID", "Account Name", "Sector", "Region",
                                  "Support Tier", "Revenue Segment"]
            st.markdown(f"**{len(_export_df):,}** accounts")
            _ex1, _ex2 = st.columns(2)
            with _ex1:
                _csv = _export_df.to_csv(index=False).encode("utf-8")
                st.download_button("Download CSV", _csv, "accounts_export.csv",
                                   "text/csv", key="sb_export_csv", use_container_width=True)
            with _ex2:
                _xls_buf = io.BytesIO()
                with pd.ExcelWriter(_xls_buf, engine="openpyxl") as writer:
                    _export_df.to_excel(writer, index=False, sheet_name="Accounts")
            st.download_button("Download Excel", _xls_buf.getvalue(),
                               "accounts_export.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key="sb_export_xlsx", use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# AUTH GATE — Show login or dashboard
# ═══════════════════════════════════════════════════════════════════════════════

if not st.session_state.get("authenticated", False):
    render_login_page()
    st.stop()

# ═══════════════════════════════════════════════════════════════════════════════
# APPLY FILTERS
# ═══════════════════════════════════════════════════════════════════════════════

f_accounts = accounts_df.copy()

_search_q = st.session_state.get("main_search", "")
if _search_q:
    q = _search_q.lower()
    f_accounts = f_accounts[
        f_accounts["account_id"].str.lower().str.contains(q, na=False)
        | f_accounts["account_name"].str.lower().str.contains(q, na=False)
    ]
if selected_sectors:
    f_accounts = f_accounts[f_accounts["sector"].isin(selected_sectors)]
if selected_regions:
    f_accounts = f_accounts[f_accounts["region"].isin(selected_regions)]
if selected_tiers:
    f_accounts = f_accounts[f_accounts["support_tier"].isin(selected_tiers)]
if selected_revenue:
    f_accounts = f_accounts[f_accounts["revenue_segment"].isin(selected_revenue)]

f_cases = cases_df[cases_df["account_id"].isin(f_accounts["account_id"])].copy()

if selected_products:
    f_cases = f_cases[f_cases["product_name"].isin(selected_products)]
if date_start is not None and date_end is not None:
    f_cases = f_cases[
        (f_cases["creation_date"] >= pd.Timestamp(date_start))
        & (f_cases["creation_date"] <= pd.Timestamp(date_end))
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# BUILD ACCOUNT STATS (for card gallery)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_stats(cases, accounts):
    agg = cases.groupby("account_id").agg(
        total_cases=("case_number", "count"),
        escalations=("escalated", "sum"),
        avg_csat=("csat_score", "mean"),
        avg_ttr=("time_to_resolve_hours", "mean"),
    ).reset_index()
    closed = (
        cases[cases["status"].isin(["Resolved", "Closed"])]
        .groupby("account_id").size().reset_index(name="closed_count")
    )
    agg = agg.merge(closed, on="account_id", how="left")
    agg["closed_count"] = agg["closed_count"].fillna(0).astype(int)

    merged = accounts[["account_id", "account_name", "sector", "region",
                        "revenue_segment", "support_tier", "annual_revenue",
                        "contract_end_date"]].merge(agg, on="account_id", how="left")
    merged["total_cases"] = merged["total_cases"].fillna(0).astype(int)
    merged["escalations"] = merged["escalations"].fillna(0).astype(int)
    merged["closed_count"] = merged["closed_count"].fillna(0).astype(int)

    tc = merged["total_cases"].clip(lower=1)
    csat_pts = pd.Series(20.0, index=merged.index)
    valid = merged["avg_csat"].notna()
    csat_pts[valid] = (merged.loc[valid, "avg_csat"] / 5.0) * 40
    esc_rate = merged["escalations"] / tc
    esc_pts = (25 * (1 - esc_rate * 5)).clip(lower=0)
    close_pts = (merged["closed_count"] / tc) * 20
    ttr_pts = pd.Series(7.5, index=merged.index)
    valid_ttr = merged["avg_ttr"].notna()
    ttr_pts[valid_ttr] = (15 * (1 - (merged.loc[valid_ttr, "avg_ttr"].clip(upper=720) / 720))).clip(lower=0)
    merged["health"] = (csat_pts + esc_pts + close_pts + ttr_pts).clip(upper=100).round(1)
    merged.drop(columns=["closed_count", "avg_ttr"], inplace=True, errors="ignore")
    return merged

acct_stats = _build_stats(f_cases, f_accounts)

sort_config = {
    "Total Cases (High to Low)":  ("total_cases", False),
    "Escalations (High to Low)":  ("escalations", False),
    "CSAT (Low to High)":         ("avg_csat", True),
    "Revenue (High to Low)":      ("annual_revenue", False),
    "Health Score (Low to High)":  ("health", True),
    "Account Name":               ("account_name", True),
}
s_col, s_asc = sort_config[sort_by]
acct_stats = acct_stats.sort_values(s_col, ascending=s_asc, na_position="last")


# ═══════════════════════════════════════════════════════════════════════════════
# ACCOUNT DETAIL VIEW
# ═══════════════════════════════════════════════════════════════════════════════


@st.dialog("Account Quick View")
def account_popup(account_id):
    acc = accounts_df[accounts_df["account_id"] == account_id]
    if acc.empty:
        st.error("Account not found.")
        return
    acc = acc.iloc[0]
    acc_cases = cases_df[cases_df["account_id"] == account_id]
    avg_c = acc_cases["csat_score"].mean() if len(acc_cases) else None
    esc = int(acc_cases["escalated"].sum()) if len(acc_cases) else 0
    avg_t = acc_cases["time_to_resolve_hours"].mean() if len(acc_cases) else None

    csat_s = f"{avg_c:.1f}" if pd.notna(avg_c) else "N/A"
    resolve_s = f"{avg_t:.0f}h" if pd.notna(avg_t) else "N/A"

    st.markdown(_html(f"""<div style="text-align:center;padding:10px 0 6px;">
        <div style="width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#8B5CF6,#A78BFA);
            display:inline-flex;align-items:center;justify-content:center;margin-bottom:8px;">
            <span style="color:#fff;font-size:1.2rem;font-weight:700;">{acc['account_name'][0]}</span>
        </div>
        <div style="font-size:1.05rem;font-weight:700;color:#1E293B;">{acc['account_name']}</div>
        <div style="font-size:0.75rem;color:#94A3B8;margin-top:2px;">{account_id} \u00b7 {acc['sector']} \u00b7 {acc['region']} \u00b7 {acc['support_tier']}</div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:10px 0;">
        <div style="background:#F8FAFC;border-radius:8px;padding:8px 12px;text-align:center;">
            <div style="font-size:0.68rem;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px;">Cases</div>
            <div style="font-size:1.1rem;font-weight:700;color:#1E293B;">{len(acc_cases)}</div>
        </div>
        <div style="background:#F8FAFC;border-radius:8px;padding:8px 12px;text-align:center;">
            <div style="font-size:0.68rem;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px;">Escalations</div>
            <div style="font-size:1.1rem;font-weight:700;color:{'#EF4444' if esc > 0 else '#1E293B'};">{esc}</div>
        </div>
        <div style="background:#F8FAFC;border-radius:8px;padding:8px 12px;text-align:center;">
            <div style="font-size:0.68rem;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px;">CSAT</div>
            <div style="font-size:1.1rem;font-weight:700;color:#1E293B;">{csat_s}</div>
        </div>
        <div style="background:#F8FAFC;border-radius:8px;padding:8px 12px;text-align:center;">
            <div style="font-size:0.68rem;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px;">Resolve</div>
            <div style="font-size:1.1rem;font-weight:700;color:#1E293B;">{resolve_s}</div>
        </div>
    </div>
    <div style="font-size:0.78rem;color:#64748B;text-align:center;margin:4px 0;">
        <b>HQ:</b> {acc.get('hq_location') if acc.get('hq_location') and str(acc.get('hq_location')) != 'nan' else 'N/A'} &nbsp;\u00b7&nbsp; <b>Revenue:</b> {acc.get('revenue_segment') if acc.get('revenue_segment') and str(acc.get('revenue_segment')) != 'nan' else 'N/A'}
    </div>"""), unsafe_allow_html=True)

    if st.button("AI Insight", key="popup_ai", type="primary", use_container_width=True):
        ctx_lines = [f"Account: {acc['account_name']}", f"Cases: {len(acc_cases)}"]
        if len(acc_cases):
            ctx_lines.append(f"Escalations: {esc}")
            ctx_lines.append(f"Avg CSAT: {avg_c:.1f}" if pd.notna(avg_c) else "Avg CSAT: N/A")
            top_prod = acc_cases["product_name"].value_counts().head(3)
            ctx_lines.append(f"Top products: {', '.join(top_prod.index.tolist())}")
        msgs = [
            {"role": "system", "content": "You are a Red Hat support analyst. Give account health analysis: 1) Status (Healthy/Attention/Risk) 2) Key metrics 3) Risk areas 4) Recommendations. Use exact numbers. Missing CSAT=pending. **Bold** key numbers. 8-12 lines."},
            {"role": "user", "content": "\n".join(ctx_lines)},
        ]
        with st.spinner("Generating..."):
            result = call_ai(msgs, max_tokens=300)
        st.markdown(result if result else f"**{acc['account_name']}** has {len(acc_cases)} cases with {esc} escalations.")


_DRILL_COLS = ["case_number", "severity", "status", "product_name",
               "case_owner", "account_name", "csat_score", "escalated", "creation_date"]


def _show_drill_table(drill, cols=None):
    cols = cols or _DRILL_COLS
    cols = [c for c in cols if c in drill.columns]
    st.dataframe(_rename_cols(drill[cols].sort_values("creation_date", ascending=False)),
                 use_container_width=True, hide_index=True)


@st.dialog("Category Breakdown", width="large")
def _category_drill_popup(category, source_cases, col, dim_label):
    drill = source_cases[source_cases[col].str.strip() == category]
    st.markdown(f"**{dim_label}: {category}** — {len(drill)} cases")
    if drill.empty:
        st.info("No cases found.")
        return
    _show_drill_table(drill)


@st.dialog("Region / Sector Cases", width="large")
def _sunburst_drill_popup(label, parent, source_cases):
    if label in source_cases["region"].values:
        drill = source_cases[source_cases["region"] == label]
        heading = f"Region: {label}"
    elif label in source_cases["sector"].values:
        drill = source_cases[source_cases["sector"] == label]
        if parent and parent in source_cases["region"].values:
            drill = drill[drill["region"] == parent]
        heading = f"{parent} › {label}" if parent else f"Sector: {label}"
    else:
        st.info("No matching data.")
        return
    if drill.empty:
        st.info("No cases found.")
        return
    st.markdown(f"**{heading}** — {len(drill)} cases")
    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        _f_sev = st.multiselect("Severity", sorted(drill["severity"].dropna().unique()), key="_drill_sev")
    with fc2:
        _f_sts = st.multiselect("Status", sorted(drill["status"].dropna().unique()), key="_drill_sts")
    with fc3:
        _f_prod = st.multiselect("Product", sorted(drill["product_name"].dropna().unique()), key="_drill_prod")
    with fc4:
        _f_owner = st.multiselect("Case Owner", sorted(drill["case_owner"].dropna().unique()), key="_drill_owner")
    if _f_sev:
        drill = drill[drill["severity"].isin(_f_sev)]
    if _f_sts:
        drill = drill[drill["status"].isin(_f_sts)]
    if _f_prod:
        drill = drill[drill["product_name"].isin(_f_prod)]
    if _f_owner:
        drill = drill[drill["case_owner"].isin(_f_owner)]
    st.caption(f"Showing {len(drill)} cases")
    _show_drill_table(drill)


@st.dialog("Cases in Period", width="large")
def _timeline_drill_popup(period_start, period_end, source_cases):
    drill = source_cases[
        (source_cases["creation_date"] >= period_start)
        & (source_cases["creation_date"] < period_end)
    ]
    st.markdown(f"**{period_start.strftime('%b %d, %Y')} — {period_end.strftime('%b %d, %Y')}** | {len(drill)} cases")
    if drill.empty:
        st.info("No cases in this period.")
        return
    _show_drill_table(drill)


@st.dialog("Associate Cases", width="large")
def _associate_drill_popup(assoc_name, source_cases):
    drill = source_cases[source_cases["case_owner"] == assoc_name]
    st.markdown(f"**{assoc_name}** — {len(drill)} cases on this account")
    if drill.empty:
        st.info("No cases found.")
        return
    _show_drill_table(drill, cols=["case_number", "severity", "status", "product_name",
                                    "problem_statement", "csat_score", "escalated", "creation_date"])


def render_detail(account_id):
    _acc_match = accounts_df[accounts_df["account_id"] == account_id]
    if _acc_match.empty:
        st.error("Account not found.")
        st.session_state.selected_account = None
        st.rerun()
        return
    acc = _acc_match.iloc[0]
    acc_cases = cases_df[cases_df["account_id"] == account_id].copy()
    h = health_score(acc_cases)

    st.markdown(f"""
    <style>
    .sticky-back {{
        position: fixed;
        top: 0; left: 0; right: 0;
        z-index: 9999;
        background: {PF_RED};
        padding: 10px 32px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.4);
        display: flex;
        align-items: center;
        gap: 16px;
    }}
    .sticky-back span {{
        color: {RH_WHITE};
        font-weight: 600;
        font-size: 0.95rem;
    }}
    .block-container {{ padding-top: 56px !important; }}
    </style>
    <div class="sticky-back">
        <span>{acc['account_name']}</span>
    </div>
    """, unsafe_allow_html=True)

    if st.button("Back to Dashboard", key="back_top", type="primary", use_container_width=True):
        st.session_state.selected_account = None
        st.session_state.chat_history = []
        st.session_state.ai_insight = None
        if "view" in st.query_params:
            del st.query_params["view"]
        st.rerun()

    st.markdown(_html(f"""<div class="det-hdr">
        <h2>{acc['account_name']} &nbsp;{health_html(h)} &nbsp;{contract_html(acc['contract_end_date'])}</h2>
        <p>{acc['account_id']} &nbsp;·&nbsp; {acc['sector']} &nbsp;·&nbsp; {acc['region']} &nbsp;·&nbsp; {acc['support_tier']}</p>
    </div>"""), unsafe_allow_html=True)

    # ── Tour continuation inside Detail View ──
    _tour_step_d = st.session_state.get("_tour_step", 0)
    _DASH_STEPS_D = 6
    _d_start = _DASH_STEPS_D + 1
    _s_total_d = _DASH_STEPS_D + 6
    if _tour_step_d >= _d_start and not st.session_state.get("_tour_seen"):
        _detail_steps = [
            {"icon": "🏢", "label": "WORKSPACE", "title": "Customer Workspace",
             "desc": "Viewing <b>%s</b>'s full workspace — Overview, Cases &amp; Trends, Associates, and AI Insights tabs." % acc["account_name"],
             "sel": "div[data-testid='stPills']"},
            {"icon": "📊", "label": "OVERVIEW", "title": "Account Metrics",
             "desc": "Key account metrics — open cases, CSAT, resolution time, and escalation rate at a glance.",
             "sel": "div[data-testid='stMetric']"},
            {"icon": "📋", "label": "CASES", "title": "Case Analysis",
             "desc": "Case timeline, distribution charts, and interactive filters. Group by Day/Week/Month/Quarter and click to drill down.",
             "sel": ".st-key-det_chart_unified", "nav_tab": "Cases & Trends"},
            {"icon": "👥", "label": "ASSOCIATES", "title": "Engineer Performance",
             "desc": "Top engineers ranked by solved cases, resolution rate, CSAT, and escalations. Click any bar for details.",
             "sel": ".st-key-det_top_assoc", "nav_tab": "Associates"},
            {"icon": "🤖", "label": "AI INSIGHTS", "title": "AI-Powered Analysis",
             "desc": "Generate AI health analysis with risk areas and recommendations. Use the chatbot for natural language Q&A.",
             "sel": "div[data-testid='stSubheader']", "nav_tab": "AI Insights"},
            {"icon": "🚀", "label": "ALL SET", "title": "You're Ready!",
             "desc": "Tour complete! You can now filter accounts, pin KPIs, analyze trends, and use AI insights. <b>Start exploring!</b>",
             "sel": "", "finish": True},
        ]
        _d_idx = _tour_step_d - _d_start
        if 0 <= _d_idx < len(_detail_steps):
            _dt = _detail_steps[_d_idx]
            _d_sel = _dt.get("sel", "")
            _d_finish = _dt.get("finish", False)

            if _dt.get("nav_tab"):
                st.session_state["det_tab"] = _dt["nav_tab"]

            _d_dots = "".join(
                '<span style="display:inline-block;width:%dpx;height:6px;border-radius:9999px;background:%s;margin:0 2px;transition:all .3s;"></span>'
                % (12 if i == (_tour_step_d - 1) else 6, "#fff" if i == (_tour_step_d - 1) else "rgba(255,255,255,.3)")
                for i in range(_s_total_d))

            st.markdown("""
            <style>
            @keyframes _tFadeIn { from{opacity:0;transform:scale(.96) translateY(12px)} to{opacity:1;transform:scale(1) translateY(0)} }
            @keyframes _tPulse { 0%%,100%%{box-shadow:0 0 0 0 rgba(99,102,241,.4)} 50%%{box-shadow:0 0 0 10px rgba(99,102,241,0)} }
            #tour-spotlight-box { position:fixed;z-index:100000;pointer-events:none;border:2px solid #6366F1;border-radius:12px;box-shadow:0 0 0 9999px rgba(15,23,42,0.65),0 0 30px rgba(99,102,241,0.25);transition:all 300ms cubic-bezier(0.4,0,0.2,1); }
            .st-key-dtour_popup { position:fixed!important;z-index:100002!important;width:380px!important;max-width:88vw!important;opacity:0; }
            .st-key-dtour_popup [data-testid="stVerticalBlock"] { gap:0!important; }
            .st-key-dtour_popup [data-testid="stHorizontalBlock"] { gap:.5rem!important;background:#F8FAFC;border-radius:0 0 18px 18px;padding:10px 16px!important;box-shadow:0 15px 40px rgba(0,0,0,.12); }
            .st-key-dtour_popup button { white-space:nowrap!important;font-size:.78rem!important;font-weight:600!important;padding:8px 18px!important;border-radius:10px!important;min-height:36px!important; }
            .st-key-dtour_popup button[kind="primary"] { background:linear-gradient(135deg,#6366F1,#818CF8)!important;border:none!important;box-shadow:0 4px 12px rgba(99,102,241,.3)!important; }
            .st-key-dtour_popup button[kind="secondary"] { background:#fff!important;color:#64748B!important;border:1px solid #E2E8F0!important; }
            </style>
            """, unsafe_allow_html=True)

            _djs_sel = _d_sel.replace("'", "\\'") if _d_sel else ""
            if _d_finish or not _djs_sel:
                _dtour_js = """<script>(function(){var P=window.parent,D=P.document;var old=D.getElementById('tour-spotlight-box');if(old)old.remove();var oldS=D.getElementById('tour-pos');if(oldS)oldS.remove();var sp=D.createElement('div');sp.id='tour-spotlight-box';sp.style.cssText='position:fixed;inset:0;z-index:100000;pointer-events:none;border:none;border-radius:0;box-shadow:0 0 0 9999px rgba(15,23,42,0.65);';D.body.appendChild(sp);P.scrollTo({top:0,behavior:'smooth'});function s(){var p=D.querySelector('.st-key-dtour_popup');if(!p){setTimeout(s,100);return}var st=D.createElement('style');st.id='tour-pos';st.textContent='.st-key-dtour_popup{left:50%!important;top:50%!important;transform:translate(-50%,-50%)!important;opacity:1!important;animation:_tFadeIn .4s cubic-bezier(.34,1.56,.64,1) both!important;}';D.head.appendChild(st)}setTimeout(s,200)})();</script>"""
            else:
                _dtour_js = """<script>(function(){var P=window.parent,D=P.document,SEL='%s',PCLS='.st-key-dtour_popup';var old=D.getElementById('tour-spotlight-box');if(old)old.remove();var oldS=D.getElementById('tour-pos');if(oldS)oldS.remove();var sp=D.createElement('div');sp.id='tour-spotlight-box';sp.style.cssText='position:fixed;left:0;top:0;width:0;height:0;z-index:100000;pointer-events:none;border:2px solid #6366F1;border-radius:12px;box-shadow:0 0 0 9999px rgba(15,23,42,0.65),0 0 30px rgba(99,102,241,0.25);transition:all 300ms cubic-bezier(0.4,0,0.2,1);opacity:0;';D.body.appendChild(sp);function waitEl(sel,cb){var el=D.querySelector(sel);if(el){cb(el);return}var obs=new MutationObserver(function(){el=D.querySelector(sel);if(el){obs.disconnect();cb(el)}});obs.observe(D.body,{childList:true,subtree:true});setTimeout(function(){obs.disconnect();if(!D.querySelector(sel))cb(null)},5000)}waitEl(SEL,function(el){if(!el){sp.style.cssText='position:fixed;inset:0;z-index:100000;pointer-events:none;border:none;border-radius:0;box-shadow:0 0 0 9999px rgba(15,23,42,0.65);opacity:1;';var fs=D.createElement('style');fs.id='tour-pos';fs.textContent=PCLS+'{left:50%%!important;top:50%%!important;transform:translate(-50%%,-50%%)!important;opacity:1!important;animation:_tFadeIn .4s cubic-bezier(.34,1.56,.64,1) both!important;}';D.head.appendChild(fs);return}var det=el.closest('details');if(det&&!det.open)det.open=true;el.scrollIntoView({behavior:'smooth',block:'center'});setTimeout(function(){var r=el.getBoundingClientRect(),pad=8;sp.style.left=(r.left-pad)+'px';sp.style.top=(r.top-pad)+'px';sp.style.width=(r.width+pad*2)+'px';sp.style.height=(r.height+pad*2)+'px';sp.style.opacity='1';posPopup(el)},600)});function posPopup(el){var popup=D.querySelector(PCLS);if(!popup){setTimeout(function(){posPopup(el)},100);return}var r=el.getBoundingClientRect(),vw=P.innerWidth,vh=P.innerHeight,pw=400,ph=popup.offsetHeight||380,gap=24,left,top;if(r.right+gap+pw<vw){left=r.right+gap;top=r.top}else if(r.left-gap-pw>0){left=r.left-gap-pw;top=r.top}else if(r.bottom+gap+ph<vh){left=Math.max(gap,r.left+(r.width-pw)/2);top=r.bottom+gap}else{left=Math.max(gap,r.left+(r.width-pw)/2);top=Math.max(gap,r.top-ph-gap)}left=Math.max(20,Math.min(left,vw-pw-20));top=Math.max(20,Math.min(top,vh-ph-20));var s=D.getElementById('tour-pos');if(s)s.remove();s=D.createElement('style');s.id='tour-pos';s.textContent=PCLS+'{left:'+left+'px!important;top:'+top+'px!important;opacity:1!important;animation:_tFadeIn .4s cubic-bezier(.34,1.56,.64,1) both!important;}';D.head.appendChild(s);function repos(){var nr=el.getBoundingClientRect(),pad=8;sp.style.left=(nr.left-pad)+'px';sp.style.top=(nr.top-pad)+'px';sp.style.width=(nr.width+pad*2)+'px';sp.style.height=(nr.height+pad*2)+'px';if(nr.right+gap+pw<vw){left=nr.right+gap;top=nr.top}else if(nr.left-gap-pw>0){left=nr.left-gap-pw;top=nr.top}else{left=Math.max(20,nr.left+(nr.width-pw)/2);top=nr.bottom+gap}left=Math.max(20,Math.min(left,vw-pw-20));top=Math.max(20,Math.min(top,vh-ph-20));s.textContent=PCLS+'{left:'+left+'px!important;top:'+top+'px!important;opacity:1!important;}'}P.addEventListener('scroll',repos,{passive:true});P.addEventListener('resize',repos,{passive:true})}})();</script>""" % _djs_sel
            st_components.html(_dtour_js, height=0)

            if _d_finish:
                _d_desc = """<div style="font-size:.85rem;color:#334155;line-height:1.65;">
                    Tour complete! You can now filter accounts, pin KPIs, analyze trends, and use AI insights.
                    <div style="margin-top:10px;font-size:.78rem;color:#64748B;">Use the <b>?</b> button in the header to restart anytime.</div></div>"""
            else:
                _d_desc = '<div style="font-size:.85rem;color:#334155;line-height:1.65;">%s</div>' % _dt["desc"]

            with st.container(key="dtour_popup"):
                st.markdown(_html("""
                <div style="background:#fff;border-radius:18px 18px 0 0;overflow:hidden;
                    box-shadow:0 25px 60px rgba(0,0,0,.25),0 0 0 1px rgba(99,102,241,.1);">
                    <div style="background:linear-gradient(135deg,#6366F1,#818CF8,#A78BFA);
                        padding:24px 24px 18px;position:relative;overflow:hidden;">
                        <div style="position:absolute;top:-25px;right:-25px;width:100px;height:100px;
                            border-radius:50%%;background:rgba(255,255,255,.08);"></div>
                        <div style="position:absolute;bottom:-15px;left:-15px;width:70px;height:70px;
                            border-radius:50%%;background:rgba(255,255,255,.05);"></div>
                        <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;position:relative;">
                            <div style="width:44px;height:44px;border-radius:13px;
                                background:rgba(255,255,255,.2);backdrop-filter:blur(8px);
                                display:flex;align-items:center;justify-content:center;
                                font-size:1.3rem;animation:_tPulse 2s ease-in-out infinite;">
                                %s</div>
                            <div>
                                <div style="font-size:.6rem;font-weight:700;text-transform:uppercase;
                                    letter-spacing:.12em;color:rgba(255,255,255,.7);">%s</div>
                                <div style="font-size:1.05rem;font-weight:800;color:#fff;margin-top:1px;">%s</div>
                            </div>
                        </div>
                        <div style="display:flex;align-items:center;gap:3px;">%s</div>
                    </div>
                    <div style="padding:18px 24px 8px;">%s</div>
                    <div style="padding:2px 24px 10px;">
                        <span style="font-size:.7rem;color:#94A3B8;font-weight:600;">Step %d of %d</span>
                    </div>
                </div>
                """ % (_dt["icon"], _dt["label"], _dt["title"], _d_dots, _d_desc, _tour_step_d, _s_total_d)), unsafe_allow_html=True)
                _dc1, _dc2, _dc3 = st.columns(3)
                with _dc1:
                    if st.button("← Back", key="_dtour_prev", use_container_width=True):
                        _prev = _tour_step_d - 1
                        if _prev <= _DASH_STEPS_D:
                            st.session_state["selected_account"] = None
                        st.session_state["_tour_step"] = _prev
                        st.rerun()
                with _dc2:
                    if _tour_step_d < _s_total_d:
                        if st.button("Next →", key="_dtour_next", type="primary", use_container_width=True):
                            st.session_state["_tour_step"] = _tour_step_d + 1
                            st.rerun()
                    else:
                        if st.button("Start Exploring →", key="_dtour_finish", type="primary", use_container_width=True):
                            st.session_state["_tour_step"] = 0
                            st.session_state["_tour_seen"] = True
                            st.session_state["selected_account"] = None
                            st.rerun()
                with _dc3:
                    if st.button("Skip Tour", key="_dtour_skip", use_container_width=True):
                        st.session_state["_tour_step"] = 0
                        st.session_state["_tour_seen"] = True
                        st.session_state["selected_account"] = None
                        st.rerun()
    else:
        st_components.html("""<script>(function(){var D=window.parent.document;var b=D.getElementById('tour-spotlight-box');if(b)b.remove();var s=D.getElementById('tour-pos');if(s)s.remove();})()</script>""", height=0)

    _det_active = st.pills("", ["Overview", "Cases & Trends", "Associates", "AI Insights"],
                           default="Overview", key="det_tab")
    if not _det_active:
        _det_active = "Overview"

    # ─────────── TAB 1: OVERVIEW ────────────
    if _det_active == "Overview":
        c1, c2, c3, c4 = st.columns(4)
        _hq_raw = acc.get("hq_location")
        hq = _hq_raw if _hq_raw and str(_hq_raw) != "nan" else "N/A"
        tam = acc.get("tam_assigned")
        tam_str = tam if tam and str(tam) != "nan" else "Not Assigned"
        end = acc["contract_end_date"]
        c1.markdown(f"**HQ:** {hq}")
        _rev_raw = acc.get("revenue_segment")
        c2.markdown(f"**Revenue:** {_rev_raw if _rev_raw and str(_rev_raw) != 'nan' else 'N/A'}")
        c3.markdown(f"**TAM:** {tam_str}")
        c4.markdown(f"**Contract End:** {end.strftime('%Y-%m-%d') if pd.notna(end) else 'N/A'}")

        _bg_raw = acc.get("company_background")
        bg = _bg_raw if _bg_raw and str(_bg_raw) != "nan" else "No background information available."
        st.info(f"**About:** {bg}")

        # Detail KPI Deltas (vs last 30 days)
        _dnow = pd.Timestamp.now()
        _d30 = _dnow - pd.Timedelta(days=30)
        _d60 = _dnow - pd.Timedelta(days=60)
        _dc = acc_cases[acc_cases["creation_date"] >= _d30]
        _dp = acc_cases[(acc_cases["creation_date"] >= _d60) & (acc_cases["creation_date"] < _d30)]
        _dc_esc = int(_dc["escalated"].sum())
        _dp_esc = int(_dp["escalated"].sum())

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Total Cases", len(acc_cases),
                  delta=f"{len(_dc)} this month" if len(_dc) else None)
        k2.metric("Escalations", int(acc_cases["escalated"].sum()),
                  delta=f"{_dc_esc - _dp_esc:+d}" if _dp_esc else None, delta_color="inverse")
        avg_c = acc_cases["csat_score"].mean()
        k3.metric("Avg CSAT", f"{avg_c:.1f}" if pd.notna(avg_c) else "N/A")
        avg_t = acc_cases["time_to_resolve_hours"].mean()
        k4.metric("Avg Resolve", f"{avg_t:.0f} hrs" if pd.notna(avg_t) else "N/A")
        open_n = len(acc_cases[acc_cases["status"].isin(
            ["Open", "In Progress", "Waiting on Customer", "Waiting on Engineering"])])
        k5.metric("Open Cases", open_n)
        k6.metric("Health Score", f"{h}/100")

        if len(acc_cases) == 0:
            st.warning("No cases found for this account with the current filters.")
            return

        if st.session_state.ai_insight:
            _ai_act1, _ai_act2, _ai_act3 = st.columns([6, 1, 1])
            with _ai_act2:
                if st.button("Regenerate", key="regen_ai_overview", type="secondary",
                             use_container_width=True, icon=":material/refresh:"):
                    st.session_state.ai_insight = None
                    st.rerun()
            with _ai_act3:
                if st.button("Close", key="close_ai_overview", type="secondary",
                             use_container_width=True, icon=":material/close:"):
                    st.session_state.ai_insight = None
            if st.session_state.ai_insight:
                st.markdown(ai_card_html("AI Account Insight", st.session_state.ai_insight),
                            unsafe_allow_html=True)
        else:
            if st.button("Generate AI Insight", key="gen_ai_overview",
                         type="primary", use_container_width=True,
                         icon=":material/auto_awesome:"):
                _generate_and_store_insight(
                    acc["account_name"], acc_cases,
                    "You are a Red Hat customer support analytics expert analyzing account health.\n\n"
                    "Structure your response with these sections using markdown headers:\n"
                    "### Case Overview\n"
                    "Summarize total cases, severity breakdown (with exact counts), "
                    "resolution rate, and average resolution time.\n\n"
                    "### Product & Escalation Analysis\n"
                    "List top products by case volume, escalation rate, "
                    "and key escalated issues with specific problem descriptions.\n\n"
                    "### Customer Satisfaction\n"
                    "Report CSAT score with rating (Excellent/Good/Needs Improvement/Critical), "
                    "identify any patterns in low-rated interactions.\n\n"
                    "### Recommendations\n"
                    "Give 2-3 specific, actionable recommendations based on the data. "
                    "Each recommendation must reference a specific metric or finding. "
                    "BAD: 'Improve resolution time.' "
                    "GOOD: 'Resolution time averages 106 hrs — assign a dedicated SME for "
                    "Red Hat AMQ cases (3 of 11) to reduce repeat escalations.'\n\n"
                    "Use exact numbers. Keep total under 200 words.")
                st.rerun()

        st.subheader("Case Activity Timeline")

        if "_det_date_saved" not in st.session_state:
            st.session_state["_det_date_saved"] = []
        if "det_date_range" not in st.session_state and st.session_state["_det_date_saved"]:
            st.session_state["det_date_range"] = tuple(st.session_state["_det_date_saved"])

        def _on_det_date_change():
            _v = st.session_state.get("det_date_range", ())
            st.session_state["_det_date_saved"] = list(_v) if _v else []

        _tl_col1, _tl_col2, _tl_col3 = st.columns([3, 2, 0.4])
        with _tl_col1:
            period = st.pills("Group by", ["Day", "Week", "Month", "Quarter"], default="Month", key="det_p")
            if not period:
                period = "Month"
        with _tl_col2:
            _min_dt = acc_cases["creation_date"].min().date() if len(acc_cases) else pd.Timestamp.now().date()
            _max_dt = acc_cases["creation_date"].max().date() if len(acc_cases) else pd.Timestamp.now().date()
            _date_range = st.date_input("Date Range (optional)", value=[],
                                        min_value=_min_dt, max_value=_max_dt, key="det_date_range",
                                        on_change=_on_det_date_change)
        with _tl_col3:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("✕", key="clear_det_date", help="Clear date filter"):
                st.session_state["_det_date_saved"] = []
                if "det_date_range" in st.session_state:
                    del st.session_state["det_date_range"]
                st.rerun()

        _tl_cases = acc_cases.copy()
        if isinstance(_date_range, (list, tuple)) and len(_date_range) == 2:
            _dr_start, _dr_end = pd.Timestamp(_date_range[0]), pd.Timestamp(_date_range[1]) + pd.Timedelta(days=1)
            _tl_cases = _tl_cases[(_tl_cases["creation_date"] >= _dr_start) & (_tl_cases["creation_date"] < _dr_end)]

        freq = {"Day": "D", "Week": "W", "Month": "MS", "Quarter": "QS"}[period]
        if len(_tl_cases) > 0:
            ts = _tl_cases.set_index("creation_date").resample(freq).agg(
                Cases=("case_number", "count"), Escalations=("escalated", "sum")
            ).reset_index()
        else:
            ts = pd.DataFrame(columns=["creation_date", "Cases", "Escalations"])
        if period == "Day":
            ts = ts[ts["Cases"] > 0].reset_index(drop=True)

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=ts["creation_date"], y=ts["Cases"], name="Cases",
            marker=dict(color=GRADIENT_PAIRS[0][0], line=dict(width=0)),
            text=ts["Cases"], textposition="outside",
            textfont=dict(size=11, color=CHART_FONT),
        ))
        fig.add_trace(go.Scatter(
            x=ts["creation_date"], y=ts["Escalations"], name="Escalations",
            mode="lines+markers", yaxis="y2",
            line=dict(color="#EF4444", width=2.5),
            marker=dict(size=7, color="#EF4444",
                        line=dict(width=1.5, color="white")),
        ))

        _styled_layout(fig, height=360)
        _xfmt = {"Day": ("%b %d, %Y", "D1"), "Week": ("%b %d", "604800000"),
                 "Month": ("%b %Y", "M1"), "Quarter": ("%b %Y", "M3")}
        _n_pts = len(ts)
        if period == "Day":
            if _n_pts > 90:
                _tf, _dt = "%b %Y", "M1"
            elif _n_pts > 30:
                _tf, _dt = "%b %d", "D7"
            else:
                _tf, _dt = "%b %d", None
        elif period == "Week":
            _tf, _dt = ("%b %d", "604800000") if _n_pts <= 52 else ("%b %Y", "M1")
        else:
            _tf, _dt = _xfmt[period]
        _xaxis_cfg = dict(tickformat=_tf, tickangle=-40)
        if _dt is not None:
            _xaxis_cfg["dtick"] = _dt
        fig.update_layout(
            xaxis_title="Period",
            xaxis=_xaxis_cfg,
            yaxis=dict(title="Cases", dtick=1, tickformat="d"),
            yaxis2=dict(title="Escalations", overlaying="y", side="right",
                        dtick=1, tickformat="d", showgrid=False,
                        tickfont=dict(color="#EF4444", size=11),
                        title_font=dict(color="#EF4444", size=12)),
            legend=dict(orientation="h", y=1.12, font=dict(size=11)),
            clickmode="event+select",
        )
        evt_tl = st.plotly_chart(fig, use_container_width=True, key="detail_timeline",
                                 on_select="rerun")
        if evt_tl and evt_tl.selection and not st.session_state.get("_dialog_open"):
            pts = evt_tl.selection.get("points", getattr(evt_tl.selection, "points", []))
            if pts:
                p = pts[0]
                px = p.get("x") if isinstance(p, dict) else getattr(p, "x", None)
                if px is not None:
                    clicked_dt = pd.Timestamp(px)
                    _offsets = {"D": {"days": 1}, "W": {"weeks": 1},
                                "MS": {"months": 1}, "QS": {"months": 3}}
                    p_end = clicked_dt + pd.DateOffset(**_offsets[freq])
                    if period == "Quarter":
                        _lbl = f"Q{(clicked_dt.month - 1) // 3 + 1} {clicked_dt.year}"
                    elif period == "Week":
                        _lbl = f"Week of {clicked_dt.strftime('%b %d, %Y')}"
                    else:
                        _lbl = clicked_dt.strftime(_xfmt[period][0])
                    st.session_state["_dialog_open"] = True
                    _timeline_drill_popup(clicked_dt, p_end, acc_cases)

    # ─────────── TAB 2: CASES & TRENDS ────────────
    if _det_active == "Cases & Trends":
        if len(acc_cases) == 0:
            st.warning("No cases to display.")
            return

        st.subheader("Case Distribution Analysis")
        st.caption("Explore how cases are distributed — click any bar for details")
        dim = st.pills("View cases by", ["Product", "Severity", "Status", "SBR Team"],
                       default="Product", key="det_chart_dim")
        if not dim:
            dim = "Product"

        sev_colors = {
            "Severity 1 (Urgent)": "#EF4444",
            "Severity 2 (High)": RH_GOLD,
            "Severity 3 (Normal)": RH_TEAL,
            "Severity 4 (Low)": RH_GRAY,
        }
        dim_map = {
            "Product":  ("product_name", 10),
            "Severity": ("severity",     None),
            "Status":   ("status",       None),
            "SBR Team": ("sbr",          8),
        }
        col, top_n = dim_map[dim]
        vc = acc_cases[col].str.strip().value_counts()
        if top_n:
            vc = vc.head(top_n)
        chart_df = vc.reset_index()
        chart_df.columns = [dim, "Cases"]

        color_map = {}
        if dim == "Severity":
            color_map = sev_colors
        elif dim == "Status":
            color_map = STATUS_COLORS

        dim_titles = {
            "Product":  "Cases by Product",
            "Severity": "Cases by Severity Level",
            "Status":   "Cases by Current Status",
            "SBR Team": "Cases by SBR Team",
        }

        if color_map:
            bar_colors = [color_map.get(v, GRADIENT_PAIRS[i % len(GRADIENT_PAIRS)][0]) for i, v in enumerate(chart_df[dim])]
        else:
            bar_colors = [GRADIENT_PAIRS[i % len(GRADIENT_PAIRS)][0] for i in range(len(chart_df))]
        fig_dim = go.Figure(go.Bar(
            x=chart_df["Cases"], y=chart_df[dim], orientation="h",
            marker=dict(color=bar_colors, line=dict(width=0)),
            text=chart_df["Cases"], textposition="outside",
            textfont=dict(color=CHART_FONT, size=12),
        ))
        _dim_max = int(chart_df["Cases"].max()) if len(chart_df) else 1
        _styled_layout(fig_dim, height=max(320, len(chart_df) * 42), yint=False, xint=True)
        fig_dim.update_layout(
            title=dict(text=dim_titles[dim], font=dict(color=CHART_FONT, size=14), x=0.5),
            yaxis=dict(autorange="reversed", title=dim),
            xaxis=dict(title="No. of Cases", dtick=max(1, _dim_max // 6),
                       range=[0, max(_dim_max * 1.3, 2)]),
            hovermode="closest", clickmode="event+select",
        )

        evt = st.plotly_chart(fig_dim, use_container_width=True, key="det_chart_unified",
                              on_select="rerun")
        _clicked_cat = None
        if evt and evt.selection:
            pts = evt.selection.get("points", getattr(evt.selection, "points", []))
            if pts:
                p = pts[0]
                _clicked_cat = p.get("y") if isinstance(p, dict) else getattr(p, "y", None)
        if _clicked_cat:
            drill = acc_cases[acc_cases[col].str.strip() == _clicked_cat]
            st.subheader(f"{_clicked_cat} — {len(drill)} Cases")
            if not drill.empty:
                _show_drill_table(drill)

        st.subheader("All Cases")
        show_cols = ["case_number", "severity", "status", "product_name",
                     "problem_statement", "case_owner", "creation_date",
                     "escalated", "csat_score"]
        st.dataframe(_rename_cols(acc_cases[show_cols].sort_values("creation_date", ascending=False)),
                     use_container_width=True, height=400)
        st.download_button("Download Cases CSV",
                           acc_cases[show_cols].to_csv(index=False),
                           f"{account_id}_cases.csv", "text/csv")

    # ─────────── TAB 3: ASSOCIATES ────────────
    if _det_active == "Associates":
        if len(acc_cases) == 0:
            st.warning("No case data available.")
            return

        st.subheader("Top Associates on This Account")
        owners = acc_cases["case_owner"].value_counts().head(10).reset_index()
        owners.columns = ["Associate", "Cases Owned"]
        owner_colors = [GRADIENT_PAIRS[i % len(GRADIENT_PAIRS)][0] for i in range(len(owners))]
        fo = go.Figure(go.Bar(
            x=owners["Cases Owned"],
            y=owners["Associate"],
            orientation="h",
            marker=dict(color=owner_colors, line=dict(width=0)),
            text=owners["Cases Owned"],
            textposition="outside",
            textfont=dict(color=CHART_FONT, size=13),
        ))
        max_val = int(owners["Cases Owned"].max()) if len(owners) else 1
        _styled_layout(fo, height=max(280, len(owners) * 38), yint=False, xint=True)
        fo.update_layout(
            xaxis=dict(title="Cases Owned", dtick=max(1, max_val // 6),
                       range=[0, max(max_val * 1.3, 2)]),
            yaxis=dict(autorange="reversed"),
        )
        evt_a = st.plotly_chart(fo, use_container_width=True, key="det_top_assoc",
                                on_select="rerun")
        _clicked_assoc = None
        if evt_a and evt_a.selection:
            pts = evt_a.selection.get("points", getattr(evt_a.selection, "points", []))
            if pts:
                p = pts[0]
                _clicked_assoc = p.get("y") if isinstance(p, dict) else getattr(p, "y", None)
        if _clicked_assoc:
            drill = acc_cases[acc_cases["case_owner"] == _clicked_assoc]
            _d_n = len(drill)
            _d_res = int(drill["status"].isin(["Resolved", "Closed"]).sum())
            _d_esc = int(drill["escalated"].sum())
            _d_csat = drill["csat_score"].mean()
            _d_ttr = drill["time_to_resolve_hours"].mean()

            st.markdown(f'<div style="font-size:1rem;font-weight:700;color:var(--text-color,{PF_TEXT});'
                        f'margin:16px 0 8px;">{_clicked_assoc}</div>',
                        unsafe_allow_html=True)
            _dk1, _dk2, _dk3, _dk4, _dk5 = st.columns(5)
            _dk1.metric("Cases Owned", _d_n)
            _dk2.metric("Resolved", _d_res)
            _dk3.metric("Escalated", _d_esc, delta_color="inverse")
            _dk4.metric("Avg CSAT", f"{_d_csat:.1f}/5" if pd.notna(_d_csat) else "N/A")
            _dk5.metric("Avg Resolve", f"{_d_ttr:.0f} hrs" if pd.notna(_d_ttr) else "N/A")

            if not drill.empty:
                _show_drill_table(drill, cols=["case_number", "severity", "status", "product_name",
                                                "problem_statement", "csat_score", "escalated", "creation_date"])

        all_names = acc_cases["case_owner"].dropna().unique().tolist()
        assoc_info = associates_df[associates_df["associate_name"].isin(all_names)].copy()
        if not assoc_info.empty:
            st.subheader("Engineer Profiles")
            disp = assoc_info[["associate_id", "associate_name", "sbr", "shift",
                               "skill_level", "certifications", "manager_name"]].copy()
            case_map = acc_cases["case_owner"].value_counts()
            disp["cases_on_account"] = disp["associate_name"].map(case_map).fillna(0).astype(int)
            disp = disp.rename(columns={
                "associate_id": "ID", "associate_name": "Engineer",
                "sbr": "SBR Team", "shift": "Geo / Shift",
                "skill_level": "Level", "certifications": "Certifications",
                "manager_name": "Manager", "cases_on_account": "Cases on Account",
            })
            st.dataframe(disp.sort_values("Cases on Account", ascending=False),
                         use_container_width=True, hide_index=True)

    # ─────────── TAB 4: AI INSIGHTS ────────────
    if _det_active == "AI Insights":
        if st.session_state.ai_insight:
            _ait1, _ait2, _ait3 = st.columns([6, 1, 1])
            with _ait2:
                if st.button("Regenerate", key="regen_ai_tab", type="secondary",
                             use_container_width=True, icon=":material/refresh:"):
                    st.session_state.ai_insight = None
                    st.rerun()
            with _ait3:
                if st.button("Close", key="close_ai_tab", type="secondary",
                             use_container_width=True, icon=":material/close:"):
                    st.session_state.ai_insight = None
                    st.rerun()
            if st.session_state.ai_insight:
                st.markdown(ai_card_html("AI Business Summary", st.session_state.ai_insight),
                            unsafe_allow_html=True)
        else:
            if st.button("Generate AI Insights", key="gen_ai",
                         use_container_width=True, type="primary",
                         icon=":material/auto_awesome:"):
                _generate_and_store_insight(
                    acc["account_name"], acc_cases,
                    "You are a Red Hat customer support analyst. Write a concise executive "
                    "summary about this account's support health.\n\n"
                    "Structure your response with these sections using markdown headers:\n"
                    "### Case Overview\n"
                    "Total cases, severity breakdown with counts, resolution rate, "
                    "average resolution time.\n\n"
                    "### Product & Escalation Analysis\n"
                    "Top products by volume, escalation rate, key escalated issues.\n\n"
                    "### Customer Satisfaction\n"
                    "CSAT score with rating, patterns in feedback.\n\n"
                    "### Recommendations\n"
                    "2-3 specific, data-backed recommendations. "
                    "BAD: 'Improve resolution time.' "
                    "GOOD: 'Resolution averages 106 hrs — assign dedicated SME for "
                    "top-volume product to cut repeat escalations.'\n\n"
                    "Use exact numbers. Do NOT show NaN — say 'pending' for open cases. "
                    "Keep under 200 words.")
                st.rerun()

        st.info("Use the **Insight Hub** button in the sidebar or the chat button at the bottom-right to ask questions about any account or the overall dashboard.")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

def render_dashboard():
    _user = st.session_state.get("display_name", "User")
    _role = st.session_state.get("role", "associate")
    _rc = {"admin": ("#6366F1", "Admin"), "manager": ("#F59E0B", "Manager"),
           "associate": ("#3B82F6", "Associate")}.get(_role, ("#3B82F6", "Associate"))
    _initials = "".join(w[0] for w in _user.split()[:2]).upper() if _user else "U"
    import datetime as _dt
    _now = _dt.datetime.now().strftime("%b %d, %Y  %I:%M %p")
    _role_bg = f"rgba({','.join(str(int(_rc[0].lstrip('#')[i:i+2],16)) for i in (0,2,4))},0.12)"
    _avatar_end = '#A78BFA' if _rc[0]=='#6366F1' else '#FBBF24' if _rc[0]=='#F59E0B' else '#60A5FA'
    st.markdown(_html(f"""
    <div class="site-header">
        <div class="site-header-brand">
            <div class="site-header-logo">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
            </div>
            <div>
                <div class="site-header-title">Customer Intelligence</div>
                <div class="site-header-subtitle">Real-time analytics &amp; account health</div>
            </div>
        </div>
        <div class="site-header-center">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="{PF_TEXT_SEC}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:4px;opacity:0.6"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            <span>{_now}</span>
        </div>
        <div class="site-header-user">
            <div class="site-header-status"><span class="site-header-dot"></span>Online</div>
            <div class="site-header-user-info">
                <div class="site-header-user-name">{_user}</div>
                <div class="site-header-user-role" style="background:{_role_bg};color:{_rc[0]};">{_rc[1]}</div>
            </div>
            <div class="site-header-avatar" style="background:linear-gradient(135deg,{_rc[0]},{_avatar_end});">{_initials}</div>
        </div>
    </div>
    """), unsafe_allow_html=True)

    _hdr_search, _hdr_spacer, _hdr_ws, _hdr_help, _hdr_logout = st.columns([4, 2, 4, 1, 1])
    with _hdr_search:
        st.text_input("Search", placeholder="Account ID / Name…", key="main_search", label_visibility="collapsed")
    with _hdr_ws:
        render_workspace_switcher("customer")
    with _hdr_help:
        if st.button("?", key="hdr_tour", help="Start guided tour",
                     type="secondary", use_container_width=True):
            st.session_state["_tour_step"] = 1
            st.session_state["_tour_seen"] = False
            st.session_state["selected_account"] = None
            st.rerun()
    with _hdr_logout:
        if st.button("⏻", key="hdr_logout", help="Log out",
                     type="secondary", use_container_width=True):
            try:
                os.remove(_sess_path(st.session_state.get("username", "")))
            except Exception:
                pass
            for k in ["authenticated", "username", "role", "display_name",
                      "jwt_token", "selected_account", "ai_insight",
                      "chat_history", "global_chat", "login_time", "_workspace"]:
                if k in st.session_state:
                    del st.session_state[k]
            for _qk in ["token", "view"]:
                if _qk in st.query_params:
                    del st.query_params[_qk]
            st.rerun()

    # ── Enterprise Guided Tour ──────────────────────────────────────────────────
    if not st.session_state.get("_tour_seen") and st.session_state.get("_tour_step", 0) == 0:
        st.session_state["_tour_step"] = 1

    _tour_step = st.session_state.get("_tour_step", 0)
    _DASH_STEPS_C = 6
    _s_total = _DASH_STEPS_C + 6
    if 1 <= _tour_step <= _DASH_STEPS_C:
        _tour_steps = [
            {"icon": "👋", "label": "WELCOME", "title": "Customer Intelligence",
             "desc": """<div style='margin-bottom:8px;'>Your central hub for real-time account health monitoring and enterprise analytics.</div>
             <div style='display:flex;align-items:center;gap:6px;margin-bottom:10px;font-size:.78rem;color:#64748B;'><span style='font-size:1rem;'>⏱</span> Estimated time: ~45 seconds</div>
             <div style='font-size:.78rem;color:#475569;line-height:1.8;'>
             <div>✓ Dashboard Overview &amp; Filters</div>
             <div>✓ Key Performance Indicators</div>
             <div>✓ Charts &amp; Analytics</div>
             <div>✓ Detail Views &amp; AI Insights</div></div>""",
             "sel": "", "welcome": True},
            {"icon": "🎛️", "label": "FILTERS", "title": "Global Filter Panel",
             "desc": "Filter the entire dashboard by Region, Account, Sector, Support Tier, and Date Range. Every visualization updates automatically.",
             "sel": "section[data-testid='stSidebar']"},
            {"icon": "📊", "label": "KPI METRICS", "title": "Executive Overview",
             "desc": "Key metrics — Total Accounts, CSAT, Resolve Time, Escalations, Open Cases, Revenue. Pin any metric to your My View.",
             "sel": "div[data-testid='stMetric']"},
            {"icon": "📈", "label": "TIMELINE", "title": "Case Trends",
             "desc": "Case volume and escalations over time. Hover to inspect, click to drill. Group by Day/Week/Month/Quarter.",
             "sel": ".st-key-dash_timeline", "expand_analytics": True},
            {"icon": "🍩", "label": "SUNBURST", "title": "Region & Sector",
             "desc": "Sunburst shows All Cases → Region → Sector. Click to drill down. Distribution charts break down by product, severity, or status.",
             "sel": ".st-key-sunburst_region_sector"},
            {"icon": "🏢", "label": "CARDS", "title": "Account Cards",
             "desc": "Each card shows health score, open cases, CSAT, tier, and contract info. Click View Details, or use Compare Mode and Bulk Select.",
             "sel": ".acct-card"},
        ]
        _step_idx = _tour_step - 1
        _ts = _tour_steps[_step_idx]
        _sel = _ts.get("sel", "")
        _is_welcome = _ts.get("welcome", False)

        if _ts.get("expand_analytics"):
            st.session_state.pop("_analytics_closed", None)

        _dots = "".join(
            '<span style="display:inline-block;width:%dpx;height:6px;border-radius:9999px;background:%s;margin:0 2px;transition:all .3s;"></span>'
            % (12 if i == _step_idx else 6, "#fff" if i == _step_idx else "rgba(255,255,255,.3)")
            for i in range(_s_total))

        st.markdown("""
        <style>
        @keyframes _tFadeIn { from{opacity:0;transform:scale(.96) translateY(12px)} to{opacity:1;transform:scale(1) translateY(0)} }
        @keyframes _tPulse { 0%%,100%%{box-shadow:0 0 0 0 rgba(99,102,241,.4)} 50%%{box-shadow:0 0 0 10px rgba(99,102,241,0)} }
        #tour-spotlight-box { position:fixed;z-index:100000;pointer-events:none;border:2px solid #6366F1;border-radius:12px;box-shadow:0 0 0 9999px rgba(15,23,42,0.65),0 0 30px rgba(99,102,241,0.25);transition:all 300ms cubic-bezier(0.4,0,0.2,1); }
        .st-key-tour_popup { position:fixed!important;z-index:100002!important;width:380px!important;max-width:88vw!important;opacity:0; }
        .st-key-tour_popup [data-testid="stVerticalBlock"] { gap:0!important; }
        .st-key-tour_popup [data-testid="stHorizontalBlock"] { gap:.5rem!important;background:#F8FAFC;border-radius:0 0 18px 18px;padding:10px 16px!important;box-shadow:0 15px 40px rgba(0,0,0,.12); }
        .st-key-tour_popup button { white-space:nowrap!important;font-size:.78rem!important;font-weight:600!important;padding:8px 18px!important;border-radius:10px!important;min-height:36px!important; }
        .st-key-tour_popup button[kind="primary"] { background:linear-gradient(135deg,#6366F1,#818CF8)!important;border:none!important;box-shadow:0 4px 12px rgba(99,102,241,.3)!important; }
        .st-key-tour_popup button[kind="secondary"] { background:#fff!important;color:#64748B!important;border:1px solid #E2E8F0!important; }
        </style>
        """, unsafe_allow_html=True)

        _js_sel = _sel.replace("'", "\\'") if _sel else ""
        if _is_welcome or not _js_sel:
            _tour_js = """<script>(function(){var P=window.parent,D=P.document;var old=D.getElementById('tour-spotlight-box');if(old)old.remove();var oldS=D.getElementById('tour-pos');if(oldS)oldS.remove();var sp=D.createElement('div');sp.id='tour-spotlight-box';sp.style.cssText='position:fixed;inset:0;z-index:100000;pointer-events:none;border:none;border-radius:0;box-shadow:0 0 0 9999px rgba(15,23,42,0.65);';D.body.appendChild(sp);P.scrollTo({top:0,behavior:'smooth'});function s(){var p=D.querySelector('.st-key-tour_popup');if(!p){setTimeout(s,100);return}var st=D.createElement('style');st.id='tour-pos';st.textContent='.st-key-tour_popup{left:50%!important;top:50%!important;transform:translate(-50%,-50%)!important;opacity:1!important;animation:_tFadeIn .4s cubic-bezier(.34,1.56,.64,1) both!important;}';D.head.appendChild(st)}setTimeout(s,200)})();</script>"""
        else:
            _expand_js = ""
            if _ts.get("expand_analytics"):
                _expand_js = "var det=D.querySelectorAll('details');for(var i=0;i<det.length;i++){if(!det[i].open)det[i].open=true;}"
            _tour_js = """<script>(function(){var P=window.parent,D=P.document,SEL='%s',PCLS='.st-key-tour_popup';var old=D.getElementById('tour-spotlight-box');if(old)old.remove();var oldS=D.getElementById('tour-pos');if(oldS)oldS.remove();%svar sp=D.createElement('div');sp.id='tour-spotlight-box';sp.style.cssText='position:fixed;left:0;top:0;width:0;height:0;z-index:100000;pointer-events:none;border:2px solid #6366F1;border-radius:12px;box-shadow:0 0 0 9999px rgba(15,23,42,0.65),0 0 30px rgba(99,102,241,0.25);transition:all 300ms cubic-bezier(0.4,0,0.2,1);opacity:0;';D.body.appendChild(sp);function waitEl(sel,cb){var el=D.querySelector(sel);if(el){cb(el);return}var obs=new MutationObserver(function(){el=D.querySelector(sel);if(el){obs.disconnect();cb(el)}});obs.observe(D.body,{childList:true,subtree:true});setTimeout(function(){obs.disconnect();if(!D.querySelector(sel))cb(null)},5000)}waitEl(SEL,function(el){if(!el){sp.style.cssText='position:fixed;inset:0;z-index:100000;pointer-events:none;border:none;border-radius:0;box-shadow:0 0 0 9999px rgba(15,23,42,0.65);opacity:1;';var fs=D.createElement('style');fs.id='tour-pos';fs.textContent=PCLS+'{left:50%%!important;top:50%%!important;transform:translate(-50%%,-50%%)!important;opacity:1!important;animation:_tFadeIn .4s cubic-bezier(.34,1.56,.64,1) both!important;}';D.head.appendChild(fs);return}var det=el.closest('details');if(det&&!det.open)det.open=true;el.scrollIntoView({behavior:'smooth',block:'center'});setTimeout(function(){var r=el.getBoundingClientRect(),pad=8;sp.style.left=(r.left-pad)+'px';sp.style.top=(r.top-pad)+'px';sp.style.width=(r.width+pad*2)+'px';sp.style.height=(r.height+pad*2)+'px';sp.style.opacity='1';posPopup(el)},600)});function posPopup(el){var popup=D.querySelector(PCLS);if(!popup){setTimeout(function(){posPopup(el)},100);return}var r=el.getBoundingClientRect(),vw=P.innerWidth,vh=P.innerHeight,pw=400,ph=popup.offsetHeight||380,gap=24,left,top;if(r.right+gap+pw<vw){left=r.right+gap;top=r.top}else if(r.left-gap-pw>0){left=r.left-gap-pw;top=r.top}else if(r.bottom+gap+ph<vh){left=Math.max(gap,r.left+(r.width-pw)/2);top=r.bottom+gap}else{left=Math.max(gap,r.left+(r.width-pw)/2);top=Math.max(gap,r.top-ph-gap)}left=Math.max(20,Math.min(left,vw-pw-20));top=Math.max(20,Math.min(top,vh-ph-20));var s=D.getElementById('tour-pos');if(s)s.remove();s=D.createElement('style');s.id='tour-pos';s.textContent=PCLS+'{left:'+left+'px!important;top:'+top+'px!important;opacity:1!important;animation:_tFadeIn .4s cubic-bezier(.34,1.56,.64,1) both!important;}';D.head.appendChild(s);function repos(){var nr=el.getBoundingClientRect(),pad=8;sp.style.left=(nr.left-pad)+'px';sp.style.top=(nr.top-pad)+'px';sp.style.width=(nr.width+pad*2)+'px';sp.style.height=(nr.height+pad*2)+'px';if(nr.right+gap+pw<vw){left=nr.right+gap;top=nr.top}else if(nr.left-gap-pw>0){left=nr.left-gap-pw;top=nr.top}else{left=Math.max(20,nr.left+(nr.width-pw)/2);top=nr.bottom+gap}left=Math.max(20,Math.min(left,vw-pw-20));top=Math.max(20,Math.min(top,vh-ph-20));s.textContent=PCLS+'{left:'+left+'px!important;top:'+top+'px!important;opacity:1!important;}'}P.addEventListener('scroll',repos,{passive:true});P.addEventListener('resize',repos,{passive:true})}})();</script>""" % (_js_sel, _expand_js)
        st_components.html(_tour_js, height=0)

        _btn_label = "Start Tour →" if _is_welcome else "Next →"
        with st.container(key="tour_popup"):
            st.markdown(_html("""
            <div style="background:#fff;border-radius:18px 18px 0 0;overflow:hidden;
                box-shadow:0 25px 60px rgba(0,0,0,.25),0 0 0 1px rgba(99,102,241,.1);">
                <div style="background:linear-gradient(135deg,#6366F1,#818CF8,#A78BFA);
                    padding:24px 24px 18px;position:relative;overflow:hidden;">
                    <div style="position:absolute;top:-25px;right:-25px;width:100px;height:100px;
                        border-radius:50%%;background:rgba(255,255,255,.08);"></div>
                    <div style="position:absolute;bottom:-15px;left:-15px;width:70px;height:70px;
                        border-radius:50%%;background:rgba(255,255,255,.05);"></div>
                    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;position:relative;">
                        <div style="width:44px;height:44px;border-radius:13px;
                            background:rgba(255,255,255,.2);backdrop-filter:blur(8px);
                            display:flex;align-items:center;justify-content:center;
                            font-size:1.3rem;animation:_tPulse 2s ease-in-out infinite;">
                            %s</div>
                        <div>
                            <div style="font-size:.6rem;font-weight:700;text-transform:uppercase;
                                letter-spacing:.12em;color:rgba(255,255,255,.7);">%s</div>
                            <div style="font-size:1.05rem;font-weight:800;color:#fff;margin-top:1px;">%s</div>
                        </div>
                    </div>
                    <div style="display:flex;align-items:center;gap:3px;">%s</div>
                </div>
                <div style="padding:18px 24px 8px;">
                    <div style="font-size:.85rem;color:#334155;line-height:1.65;">%s</div>
                </div>
                <div style="padding:2px 24px 10px;">
                    <span style="font-size:.7rem;color:#94A3B8;font-weight:600;">Step %d of %d</span>
                </div>
            </div>
            """ % (_ts["icon"], _ts["label"], _ts["title"], _dots, _ts["desc"], _tour_step, _s_total)), unsafe_allow_html=True)
            _tc1, _tc2, _tc3 = st.columns(3)
            with _tc1:
                if _tour_step > 1:
                    if st.button("← Back", key="_tour_prev", use_container_width=True):
                        st.session_state["_tour_step"] = _tour_step - 1
                        st.rerun()
            with _tc2:
                if st.button(_btn_label, key="_tour_next", type="primary", use_container_width=True):
                    _next = _tour_step + 1
                    if _next > _DASH_STEPS_C:
                        if not accounts_df.empty:
                            st.session_state["selected_account"] = accounts_df.iloc[0]["account_id"]
                            st.session_state["_tour_step"] = _DASH_STEPS_C + 1
                        else:
                            st.session_state["_tour_step"] = 0
                            st.session_state["_tour_seen"] = True
                    else:
                        st.session_state["_tour_step"] = _next
                    st.rerun()
            with _tc3:
                if st.button("Skip Tour", key="_tour_skip", use_container_width=True):
                    st.session_state["_tour_step"] = 0
                    st.session_state["_tour_seen"] = True
                    st.session_state["selected_account"] = None
                    st.rerun()
    else:
        st_components.html("""<script>(function(){var D=window.parent.document;var b=D.getElementById('tour-spotlight-box');if(b)b.remove();var s=D.getElementById('tour-pos');if(s)s.remove();})()</script>""", height=0)

    # ── KPI Trend Deltas (vs last 30 days) ──
    _now = pd.Timestamp.now()
    _30d = _now - pd.Timedelta(days=30)
    _60d = _now - pd.Timedelta(days=60)
    _cur = f_cases[f_cases["creation_date"] >= _30d]
    _prev = f_cases[(f_cases["creation_date"] >= _60d) & (f_cases["creation_date"] < _30d)]

    def _delta_pct(cur_val, prev_val):
        if prev_val == 0:
            return None
        return f"{((cur_val - prev_val) / prev_val) * 100:+.0f}%"

    def _delta_abs(cur_val, prev_val):
        d = cur_val - prev_val
        if d == 0:
            return None
        return f"{d:+.0f}"

    _esc_cur = int(_cur["escalated"].sum())
    _esc_prev = int(_prev["escalated"].sum())
    _open_stats = ["Open", "In Progress", "Waiting on Customer", "Waiting on Engineering"]
    _open_cur = len(_cur[_cur["status"].isin(_open_stats)])
    _open_prev = len(_prev[_prev["status"].isin(_open_stats)])
    _csat_cur = _cur["csat_score"].mean()
    _csat_prev = _prev["csat_score"].mean()
    _ttr_cur = _cur["time_to_resolve_hours"].mean()
    _ttr_prev = _prev["time_to_resolve_hours"].mean()

    avg_csat = f_cases["csat_score"].mean()
    avg_ttr = f_cases["time_to_resolve_hours"].mean()
    open_n = len(f_cases[f_cases["status"].isin(_open_stats)])
    total_rev = f_accounts["annual_revenue"].sum()
    rev_str = f"${total_rev/1e9:.2f}B" if total_rev >= 1e9 else f"${total_rev/1e6:.1f}M"
    _csat_d = f"{_csat_cur - _csat_prev:+.2f}" if pd.notna(_csat_cur) and pd.notna(_csat_prev) and _csat_cur != _csat_prev else None
    _ttr_d = f"{_ttr_cur - _ttr_prev:+.0f} hrs" if pd.notna(_ttr_cur) and pd.notna(_ttr_prev) and abs(_ttr_cur - _ttr_prev) > 0.5 else None

    _kpi_data = [
        ("Total Accounts", f"{len(f_accounts):,}", None, "normal"),
        ("Total Cases", f"{len(f_cases):,}", None, "normal"),
        ("Avg CSAT Score", f"{avg_csat:.1f}/5" if pd.notna(avg_csat) else "N/A", _csat_d, "normal"),
        ("Avg Time to Resolve", f"{avg_ttr:.0f} hrs" if pd.notna(avg_ttr) else "N/A", _ttr_d, "inverse"),
        ("Total Escalations", f"{int(f_cases['escalated'].sum()):,}", _delta_abs(_esc_cur, _esc_prev), "inverse"),
        ("Open Cases", f"{open_n:,}", _delta_abs(_open_cur, _open_prev), "inverse"),
        ("Total Revenue", rev_str, None, "normal"),
    ]

    # ── My View (pinned KPIs) ──
    _pins = st.session_state.get("pinned_kpis", [])
    if _pins:
        _pinned = [k for k in _kpi_data if k[0] in _pins]
        if _pinned:
            _mv_html = "".join(
                f'<div style="flex:1;min-width:140px;background:linear-gradient(135deg,rgba(99,102,241,0.06),rgba(139,92,246,0.04));'
                f'border:1px solid rgba(99,102,241,0.15);border-radius:14px;padding:16px 18px;text-align:center;">'
                f'<div style="font-size:0.68rem;font-weight:700;color:{PF_TEXT_SEC};text-transform:uppercase;'
                f'letter-spacing:0.06em;margin-bottom:6px;">{pl}</div>'
                f'<div style="font-size:1.4rem;font-weight:800;color:var(--text-color,{PF_TEXT});">{pv}</div>'
                f'{"<div style=&quot;font-size:0.72rem;margin-top:3px;color:" + ("#10B981" if not p_delta.startswith("-") else "#EF4444") + ";&quot;>" + p_delta + "</div>" if p_delta else ""}'
                f'</div>'
                for pl, pv, p_delta, _ in _pinned
            )
            st.markdown(_html(f"""<div style="margin-bottom:14px;">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
                    <span style="font-size:1rem;">📌</span>
                    <span style="font-weight:700;font-size:0.82rem;color:{PF_TEXT};letter-spacing:0.02em;">My View</span>
                    <span style="background:rgba(99,102,241,0.1);color:#6366F1;font-size:0.65rem;font-weight:700;
                          padding:2px 8px;border-radius:9999px;">{len(_pinned)}</span>
                </div>
                <div style="display:flex;gap:12px;flex-wrap:wrap;">{_mv_html}</div>
            </div>"""), unsafe_allow_html=True)
            _unpin_cols = st.columns(len(_pinned) + 2)
            for pi, (plabel, _, _, _) in enumerate(_pinned):
                with _unpin_cols[pi]:
                    if st.button(f"Unpin {plabel.split()[0]}", key=f"unpin_{plabel}",
                                 use_container_width=True):
                        st.session_state["pinned_kpis"] = [p for p in _pins if p != plabel]
                        st.rerun()

    # ── KPI Metrics ──
    _kpi_cols = st.columns(len(_kpi_data))
    for col, (label, val, delta, dcolor) in zip(_kpi_cols, _kpi_data):
        with col:
            st.metric(label, val, delta=delta, delta_color=dcolor)
    _pin_cols = st.columns(len(_kpi_data))
    for _pc, (label, _, _, _) in zip(_pin_cols, _kpi_data):
        with _pc:
            _is_pinned = label in st.session_state.get("pinned_kpis", [])
            _pin_lbl = f"Unpin" if _is_pinned else f"Pin"
            if st.button(_pin_lbl, key=f"pin_{label}",
                         help="Pin to My View" if not _is_pinned else "Remove from My View",
                         use_container_width=True):
                pins = list(st.session_state.get("pinned_kpis", []))
                if _is_pinned:
                    pins.remove(label)
                else:
                    pins.append(label)
                st.session_state["pinned_kpis"] = pins
                st.rerun()

    # ── Anomaly Detection Alerts ──
    _anomalies = []
    _dismissed = st.session_state.get("_anomaly_dismissed", [])
    if pd.notna(_csat_cur) and pd.notna(_csat_prev) and _csat_prev > 0:
        _csat_chg = (_csat_cur - _csat_prev) / _csat_prev * 100
        if _csat_chg < -15:
            _anomalies.append(("csat_drop", f"CSAT dropped {abs(_csat_chg):.0f}% in the last 30 days ({_csat_prev:.2f} → {_csat_cur:.2f})"))
    if _esc_prev > 0:
        _esc_chg = (_esc_cur - _esc_prev) / _esc_prev * 100
        if _esc_chg > 25:
            _anomalies.append(("esc_spike", f"Escalations spiked {_esc_chg:.0f}% in the last 30 days ({_esc_prev} → {_esc_cur})"))
    _at_risk_accts = acct_stats[acct_stats["health"] < 40] if "health" in acct_stats.columns else pd.DataFrame()
    if len(_at_risk_accts) > 0:
        _anomalies.append(("at_risk", f"{len(_at_risk_accts)} account(s) have health score below 40"))
    _active_anomalies = [(aid, msg) for aid, msg in _anomalies if aid not in _dismissed]
    if _active_anomalies:
        with st.expander(f"⚠ {len(_active_anomalies)} Anomaly Alert(s) Detected", expanded=True,
                         icon=":material/warning:"):
            for _aid, _amsg in _active_anomalies:
                _ac1, _ac2 = st.columns([6, 1])
                with _ac1:
                    st.warning(_amsg)
                with _ac2:
                    if st.button("Dismiss", key=f"dismiss_{_aid}"):
                        st.session_state["_anomaly_dismissed"] = _dismissed + [_aid]
                        st.rerun()
            if len(_active_anomalies) > 1:
                if st.button("Dismiss All", key="dismiss_all_anomalies"):
                    st.session_state["_anomaly_dismissed"] = _dismissed + [a[0] for a in _active_anomalies]
                    st.rerun()
            if any(aid == "at_risk" for aid, _ in _active_anomalies) and not _at_risk_accts.empty:
                st.dataframe(
                    _at_risk_accts[["account_name", "sector", "region", "total_cases", "avg_csat", "health"]].rename(
                        columns={"account_name": "Account", "total_cases": "Cases", "avg_csat": "CSAT", "health": "Health"}
                    ).sort_values("Health"),
                    use_container_width=True, hide_index=True, height=200)

    # ── Save Filter Dialog (triggered from sidebar) ──
    if st.session_state.get("_show_save_filter"):
        _sf_name = st.text_input("Filter preset name:", key="_sf_name_input")
        _sf_c1, _sf_c2 = st.columns(2)
        with _sf_c1:
            if st.button("Save", key="_sf_save") and _sf_name:
                _current_filters = {}
                for fk in ["f_sectors", "f_products", "f_tiers", "f_regions",
                           "f_revenue", "f_date_preset", "f_sort"]:
                    if fk in st.session_state and st.session_state[fk]:
                        _current_filters[fk] = st.session_state[fk]
                if _current_filters:
                    sf = st.session_state.get("saved_filters", {})
                    sf[_sf_name] = _current_filters
                    st.session_state["saved_filters"] = sf
                    st.session_state["_show_save_filter"] = False
                    st.toast(f"Filter '{_sf_name}' saved!")
                    st.rerun()
        with _sf_c2:
            if st.button("Cancel", key="_sf_cancel"):
                st.session_state["_show_save_filter"] = False
                st.rerun()

    # ── Risk Distribution (interactive — click to filter) ──
    _acc_stats = acct_stats.copy()
    _acc_stats["_health"] = _acc_stats["health"]
    _healthy = len(_acc_stats[_acc_stats["_health"] >= 70])
    _attention = len(_acc_stats[(_acc_stats["_health"] >= 40) & (_acc_stats["_health"] < 70)])
    _at_risk = len(_acc_stats[_acc_stats["_health"] < 40])
    _risk_total = max(_healthy + _attention + _at_risk, 1)
    _h_pct = _healthy / _risk_total * 100
    _a_pct = _attention / _risk_total * 100
    _r_pct = _at_risk / _risk_total * 100

    _active_risk = st.session_state.get("_risk_filter")
    st.markdown(_html(f"""<div style="background:{PF_SURFACE};
        border:1px solid {PF_BORDER};border-radius:{PF_RADIUS};
        padding:16px 20px;margin:4px 0 8px;animation:slideUp 0.5s ease both;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <span style="font-weight:700;font-size:0.88rem;color:{PF_TEXT};">
                Account Risk Distribution</span>
            <span style="font-size:0.72rem;color:{PF_TEXT_SEC};">
                Health score: CSAT &amp; escalation weighted · Healthy ≥70 · Attention 40-69 · At Risk &lt;40</span>
        </div>
        <div class="risk-bar-track">
            <div class="risk-bar-seg" style="width:{_h_pct}%;background:#10B981;"></div>
            <div class="risk-bar-seg" style="width:{_a_pct}%;background:#F59E0B;"></div>
            <div class="risk-bar-seg" style="width:{_r_pct}%;background:#EF4444;"></div>
        </div>
    </div>"""), unsafe_allow_html=True)

    _rc1, _rc2, _rc3 = st.columns(3)
    with _rc1:
        if st.button(f"🟢 Healthy ({_healthy})", key="_risk_healthy", use_container_width=True):
            st.session_state["_risk_popup"] = "healthy"
            st.rerun()
    with _rc2:
        if st.button(f"🟡 Needs Attention ({_attention})", key="_risk_attention", use_container_width=True):
            st.session_state["_risk_popup"] = "attention"
            st.rerun()
    with _rc3:
        if st.button(f"🔴 At Risk ({_at_risk})", key="_risk_at_risk", use_container_width=True):
            st.session_state["_risk_popup"] = "at_risk"
            st.rerun()

    _risk_popup = st.session_state.get("_risk_popup")
    if _risk_popup:
        _popup_labels = {"healthy": ("🟢 Healthy Accounts", "health ≥ 70"),
                         "attention": ("🟡 Needs Attention", "health 40–69"),
                         "at_risk": ("🔴 At Risk Accounts", "health < 40")}
        _pl, _pd = _popup_labels[_risk_popup]
        if _risk_popup == "healthy":
            _popup_df = _acc_stats[_acc_stats["_health"] >= 70]
        elif _risk_popup == "attention":
            _popup_df = _acc_stats[(_acc_stats["_health"] >= 40) & (_acc_stats["_health"] < 70)]
        else:
            _popup_df = _acc_stats[_acc_stats["_health"] < 40]
        _popup_df = _popup_df.sort_values("_health", ascending=(_risk_popup == "at_risk"))

        with st.expander(f"{_pl} — {len(_popup_df)} accounts ({_pd})", expanded=True):
            if _popup_df.empty:
                st.info("No accounts in this category.")
            else:
                _show_df = _popup_df[["account_name", "sector", "region", "support_tier",
                                      "total_cases", "escalations", "avg_csat", "_health"]].copy()
                _show_df.columns = ["Account", "Sector", "Region", "Tier",
                                    "Cases", "Escalations", "Avg CSAT", "Health"]
                _show_df["Avg CSAT"] = _show_df["Avg CSAT"].round(1)
                st.dataframe(_show_df, use_container_width=True, hide_index=True, height=320)
            if st.button("Close", key="_risk_popup_close"):
                del st.session_state["_risk_popup"]
                st.rerun()

    # ── Bookmarks Section ──
    _bookmarks = st.session_state.get("bookmarks", [])
    if _bookmarks and not st.session_state.get("compare_toggle"):
        _bk_accts = acct_stats[acct_stats["account_id"].isin(_bookmarks)]
        if not _bk_accts.empty:
            st.markdown(f'<div style="font-weight:700;font-size:0.92rem;color:{PF_TEXT};'
                        f'margin:8px 0 6px;animation:fadeIn 0.3s ease both;">'
                        f'⭐ Favorites ({len(_bk_accts)})</div>', unsafe_allow_html=True)
            _bk_cols = st.columns(min(len(_bk_accts), 4))
            for bi, (_, ba) in enumerate(_bk_accts.iterrows()):
                with _bk_cols[bi % len(_bk_cols)]:
                    _bc = f"{ba['avg_csat']:.1f}" if pd.notna(ba.get("avg_csat")) else "N/A"
                    st.markdown(_html(f"""<div style="background:{PF_SURFACE};
                        border:1px solid rgba(251,191,36,0.3);border-radius:{PF_RADIUS};
                        padding:10px 14px;animation:slideUp 0.4s ease both;cursor:pointer;">
                        <div style="display:flex;align-items:center;gap:8px;">
                            <span style="font-size:1rem;">⭐</span>
                            <div style="flex:1;min-width:0;">
                                <div style="font-weight:700;font-size:0.82rem;color:{PF_TEXT};
                                    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{ba['account_name']}</div>
                                <div style="font-size:0.66rem;color:{PF_TEXT_SEC};">{ba['sector']} · CSAT {_bc}</div>
                            </div>
                        </div>
                    </div>"""), unsafe_allow_html=True)
                    _fv_left, _fv_right = st.columns(2)
                    with _fv_left:
                        if st.button("View", key=f"bk_v_{ba['account_id']}", use_container_width=True):
                            st.session_state.selected_account = ba["account_id"]
                            st.query_params["view"] = str(ba["account_id"])
                            st.rerun()
                    with _fv_right:
                        if st.button("Remove", key=f"bk_rm_{ba['account_id']}", use_container_width=True):
                            st.session_state["bookmarks"] = [b for b in _bookmarks if b != ba["account_id"]]
                            st.rerun()

    st.markdown("")

    # ── Analytics & Insights (collapsible) ──
    if st.session_state.get("_analytics_closed"):
        if st.button("Show Analytics & Insights", key="_open_analytics",
                     icon=":material/insights:", use_container_width=True):
            del st.session_state["_analytics_closed"]
            st.rerun()
    else:
        with st.expander("Analytics & Insights", expanded=False, icon=":material/insights:"):
            # ── Case Activity Timeline — Bar + Line ──
            st.subheader("Case Activity Timeline")
            if len(f_cases) > 0:
                _tl_min = f_cases["creation_date"].min().date()
                _tl_max = f_cases["creation_date"].max().date()
                tl_left, tl_right = st.columns([3, 1])
                with tl_left:
                    grp = st.pills("Group by", ["Day", "Week", "Month", "Quarter"], default="Month", key="op_grp")
                    if not grp:
                        grp = "Month"
                with tl_right:
                    tl_range = st.date_input("Date range", value=[], key="tl_custom_range",
                                             min_value=_tl_min, max_value=_tl_max,
                                             label_visibility="collapsed")
    
                freq = {"Day": "D", "Week": "W", "Month": "MS", "Quarter": "QS"}[grp]
                tl_cases = f_cases.copy()
                if isinstance(tl_range, (list, tuple)) and len(tl_range) == 2:
                    tl_start, tl_end = pd.Timestamp(tl_range[0]), pd.Timestamp(tl_range[1])
                    tl_cases = tl_cases[(tl_cases["creation_date"] >= tl_start)
                                        & (tl_cases["creation_date"] <= tl_end)]
    
                if len(tl_cases) == 0:
                    st.info("No cases found in the selected date range.")
                else:
                    _resampled = tl_cases.set_index("creation_date").resample(freq)
                    ts = pd.DataFrame({
                        "creation_date": _resampled["case_number"].count().index,
                        "Cases": _resampled["case_number"].count().values,
                        "Escalations": _resampled["escalated"].sum().values,
                    })
    
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=ts["creation_date"], y=ts["Cases"], name="Cases",
                        mode="lines+markers",
                        line=dict(color=GRADIENT_PAIRS[0][0], width=2.5, shape="spline"),
                        marker=dict(size=7, color=GRADIENT_PAIRS[0][0], symbol="circle",
                                    line=dict(width=2, color="white")),
                        fill="tozeroy",
                        fillcolor=f"rgba({','.join(str(int(GRADIENT_PAIRS[0][0].lstrip('#')[i:i+2],16)) for i in (0,2,4))},0.15)",
                        hovertemplate="Cases: %{y}<extra></extra>",
                    ))
                    fig.add_trace(go.Scatter(
                        x=ts["creation_date"], y=ts["Escalations"], name="Escalations",
                        mode="lines+markers", yaxis="y2",
                        line=dict(color="#EF4444", width=2.5, shape="spline"),
                        marker=dict(size=7, color="#EF4444", symbol="diamond",
                                    line=dict(width=2, color="white")),
                        fill="tozeroy", fillcolor="rgba(239,68,68,0.08)",
                        hovertemplate="Escalations: %{y}<extra></extra>",
                    ))
    
                    max_cases = int(ts["Cases"].max()) if len(ts) else 10
                    max_esc = int(ts["Escalations"].max()) if len(ts) else 5
                    _styled_layout(fig, height=400)
                    fig.update_layout(
                        xaxis_title="Period",
                        yaxis=dict(title="Cases", dtick=max(1, max_cases // 6), tickformat="d",
                                   range=[0, max_cases * 1.3]),
                        yaxis2=dict(title="Escalations", overlaying="y", side="right",
                                    dtick=max(1, max_esc // 4), tickformat="d", showgrid=False,
                                    range=[0, max(max_esc * 1.5, 5)],
                                    tickfont=dict(color="#EF4444", size=11),
                                    title_font=dict(color="#EF4444", size=12)),
                        legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center",
                                    font=dict(size=11), bgcolor="rgba(0,0,0,0)"),
                        margin=dict(l=40, r=50, t=30, b=50),
                        hovermode="x unified",
                        clickmode="event+select",
                    )
                    st.plotly_chart(fig, use_container_width=True, key="dash_timeline")
            else:
                st.info("No cases found for the selected filters and date range.")
    
            # ── Combined Region & Sector Sunburst (always shows all regions) ──
            if len(cases_df) > 0:
                cases_with_meta = cases_df.merge(
                    accounts_df[["account_id", "region", "sector"]], on="account_id", how="left"
                )
    
                st.subheader("Cases by Region & Sector")
    
                region_colors = {"NASA": RH_TEAL, "EMEA": RH_BLUE, "APAC": RH_GOLD, "LATAM": RH_PURPLE}
                sector_palette = [p[0] for p in GRADIENT_PAIRS] + [RH_ORANGE, RH_GRAY, RH_TEAL, "#94A3B8"]
    
                rs = cases_with_meta.groupby(["region", "sector"]).size().reset_index(name="Cases")
                reg = cases_with_meta["region"].value_counts().reset_index()
                reg.columns = ["Region", "Cases"]
                total_cases = int(reg["Cases"].sum())
    
                ids = ["All Cases"]
                labels = ["All Cases"]
                parents = [""]
                values = [total_cases]
                colors_map = ["rgba(0,0,0,0)"]
    
                for _, rr in reg.iterrows():
                    ids.append(rr["Region"])
                    labels.append(rr["Region"])
                    parents.append("All Cases")
                    values.append(int(rr["Cases"]))
                    colors_map.append(region_colors.get(rr["Region"], "#94A3B8"))
    
                unique_sectors = rs["sector"].unique().tolist()
                s_cmap = {s: sector_palette[i % len(sector_palette)] for i, s in enumerate(unique_sectors)}
                for _, row in rs.iterrows():
                    node_id = f"{row['region']} - {row['sector']}"
                    ids.append(node_id)
                    labels.append(row["sector"])
                    parents.append(row["region"])
                    values.append(int(row["Cases"]))
                    colors_map.append(s_cmap.get(row["sector"], "#94A3B8"))
    
                fig_sun = go.Figure(go.Sunburst(
                    ids=ids, labels=labels, parents=parents, values=values,
                    branchvalues="total",
                    marker=dict(colors=colors_map, line=dict(width=2, color=PF_SURFACE)),
                    textinfo="label+value",
                    textfont=dict(size=11, family="Red Hat Display, sans-serif"),
                    insidetextorientation="auto",
                    hovertemplate="<b>%{label}</b><br>Cases: %{value}<br>%{percentRoot:.1%} of total<extra></extra>",
                ))
                fig_sun.update_layout(
                    paper_bgcolor=CHART_BG, plot_bgcolor=CHART_BG,
                    height=520,
                    margin=dict(l=20, r=20, t=30, b=10),
                    font=dict(family="Red Hat Display, sans-serif", color=CHART_FONT),
                    transition=dict(duration=800, easing="cubic-in-out"),
                )
    
                evt_sun = st.plotly_chart(fig_sun, use_container_width=True,
                                key="sunburst_region_sector", on_select="rerun")
                _region_names = set(reg["Region"].tolist())
                if evt_sun and evt_sun.selection and not st.session_state.get("_dialog_open"):
                    pts = evt_sun.selection.get("points", getattr(evt_sun.selection, "points", []))
                    if pts:
                        p = pts[0]
                        click_label = p.get("label") if isinstance(p, dict) else getattr(p, "label", None)
                        click_parent = p.get("parent") if isinstance(p, dict) else getattr(p, "parent", None)
                        if click_label and click_parent in _region_names:
                            st.session_state["_dialog_open"] = True
                            _sunburst_drill_popup(click_label, click_parent, cases_with_meta)

            if st.button("✕ Close Analytics", key="_close_analytics", use_container_width=True):
                st.session_state["_analytics_closed"] = True
                st.rerun()
    
    st.markdown("---")

    # ── Top 3 Accounts (follows selected sort) ──
    if len(acct_stats) >= 3:
        _sort_label = sort_by.split(" (")[0]
        st.subheader(f"Top 3 Accounts by {_sort_label}")
        _top3 = acct_stats.head(3)
        _t3_cols = st.columns(3)
        for i, (_, _t3) in enumerate(_top3.iterrows()):
            _h = _t3["health"]
            _hc = "#10B981" if _h >= 80 else ("#F59E0B" if _h >= 60 else ("#FB923C" if _h >= 40 else "#EF4444"))
            _cs = f"{_t3['avg_csat']:.1f}" if pd.notna(_t3["avg_csat"]) else "N/A"
            with _t3_cols[i]:
                st.markdown(_html(f"""<div style="background:{PF_SURFACE};border:1px solid {PF_BORDER};
                    border-radius:{PF_RADIUS};padding:16px;border-left:4px solid {_hc};
                    animation:waterFlow 0.6s ease both;">
                    <div style="font-weight:700;color:{PF_TEXT};font-size:0.92rem;margin-bottom:6px;">
                        {_t3['account_name']}</div>
                    <div style="font-size:0.78rem;color:{PF_TEXT_SEC};line-height:1.7;">
                        Cases: <b>{_t3['total_cases']}</b> &middot;
                        Escalations: <b>{_t3['escalations']}</b> &middot;
                        CSAT: <b>{_cs}</b> &middot;
                        Health: <b style="color:{_hc};">{_h}/100</b>
                    </div>
                </div>"""), unsafe_allow_html=True)
        st.markdown("")

    _ov_left, _ov_cmp, _ov_blk = st.columns([3, 1, 1])
    with _ov_left:
        st.subheader("Accounts Overview")
    with _ov_cmp:
        if st.session_state.pop("_pending_compare", False):
            st.session_state["compare_toggle"] = True
            st.session_state["bulk_toggle"] = False
            st.session_state["_bulk_ids"] = []
        _cmp_on = st.toggle("Compare Mode", key="compare_toggle",
                  help="Select 2-5 accounts below, then compare side-by-side")
        if _cmp_on and st.session_state.get("bulk_toggle"):
            st.session_state["bulk_toggle"] = False
            st.session_state["_bulk_ids"] = []
            st.rerun()
    with _ov_blk:
        _blk_on = st.toggle("Bulk Select", key="bulk_toggle",
                  help="Select multiple accounts for batch export or compare")
        if _blk_on and st.session_state.get("compare_toggle"):
            st.session_state["compare_toggle"] = False
            st.session_state["compare_ids"] = []
            st.rerun()
    # ── Compare Mode View ──
    if st.session_state.get("compare_toggle"):
        _cmp_ids = st.session_state.get("compare_ids", [])
        if len(_cmp_ids) < 2:
            st.info("Select 2-5 accounts using the checkboxes on cards below to compare them side-by-side.")
        else:
            _cmp_ids = _cmp_ids[:5]
            _cmp_data = acct_stats[acct_stats["account_id"].isin(_cmp_ids)]
            if len(_cmp_data) >= 2:
                st.markdown(f'<div style="font-weight:700;font-size:0.95rem;color:{PF_TEXT};'
                            f'margin:8px 0 6px;">Compare Accounts ({len(_cmp_data)})</div>',
                            unsafe_allow_html=True)
                _cmp_cols = st.columns(len(_cmp_data))
                for ci, (_, cr) in enumerate(_cmp_data.iterrows()):
                    with _cmp_cols[ci]:
                        _cc = f"{cr['avg_csat']:.1f}" if pd.notna(cr.get("avg_csat")) else "N/A"
                        _ch = cr.get("health", 0) or 0
                        _clr = GRADIENT_PAIRS[ci % len(GRADIENT_PAIRS)][0]
                        st.markdown(_html(f"""<div style="background:{PF_SURFACE};
                            border:2px solid {_clr};border-radius:{PF_RADIUS};padding:14px;
                            text-align:center;animation:slideUp 0.4s ease both;">
                            <div style="font-weight:700;color:{PF_TEXT};font-size:0.92rem;">{cr['account_name']}</div>
                            <div style="font-size:0.70rem;color:{PF_TEXT_SEC};margin:4px 0 10px;">{cr['sector']} · {cr['region']}</div>
                            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                                <div style="background:{PF_BG};border-radius:8px;padding:6px;">
                                    <div style="font-size:0.62rem;color:{PF_TEXT_SEC};text-transform:uppercase;">Cases</div>
                                    <div style="font-size:1rem;font-weight:800;color:{PF_TEXT};">{cr['total_cases']}</div>
                                </div>
                                <div style="background:{PF_BG};border-radius:8px;padding:6px;">
                                    <div style="font-size:0.62rem;color:{PF_TEXT_SEC};text-transform:uppercase;">Escalations</div>
                                    <div style="font-size:1rem;font-weight:800;color:{PF_TEXT};">{cr['escalations']}</div>
                                </div>
                                <div style="background:{PF_BG};border-radius:8px;padding:6px;">
                                    <div style="font-size:0.62rem;color:{PF_TEXT_SEC};text-transform:uppercase;">CSAT</div>
                                    <div style="font-size:1rem;font-weight:800;color:{PF_TEXT};">{_cc}</div>
                                </div>
                                <div style="background:{PF_BG};border-radius:8px;padding:6px;">
                                    <div style="font-size:0.62rem;color:{PF_TEXT_SEC};text-transform:uppercase;">Health</div>
                                    <div style="font-size:1rem;font-weight:800;color:{PF_TEXT};">{_ch}</div>
                                </div>
                            </div>
                        </div>"""), unsafe_allow_html=True)

                _cmp_fig = go.Figure()
                for ci, (_, cr) in enumerate(_cmp_data.iterrows()):
                    _clr = GRADIENT_PAIRS[ci % len(GRADIENT_PAIRS)][0]
                    _cmp_fig.add_trace(go.Bar(
                        x=["Cases", "Escalations", "Health"],
                        y=[cr["total_cases"], cr["escalations"], cr.get("health", 0) or 0],
                        name=cr["account_name"], marker=dict(color=_clr),
                        text=[cr["total_cases"], cr["escalations"], cr.get("health", 0) or 0],
                        textposition="outside",
                    ))
                _styled_layout(_cmp_fig, height=320)
                _cmp_fig.update_layout(barmode="group", xaxis_title="", yaxis_title="Count",
                                       legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center"))
                st.plotly_chart(_cmp_fig, use_container_width=True, key="compare_chart")

                # ── Comparison Analysis ──
                _cmp_sorted_health = _cmp_data.sort_values("health", ascending=False)
                _analysis_items = []

                _best = _cmp_sorted_health.iloc[0]
                _worst = _cmp_sorted_health.iloc[-1]
                _health_gap = (_best.get("health", 0) or 0) - (_worst.get("health", 0) or 0)
                if _health_gap > 0:
                    _analysis_items.append(
                        f"<b>{_best['account_name']}</b> leads with a health score "
                        f"<b>{_health_gap:.0f} points higher</b> than <b>{_worst['account_name']}</b>"
                    )

                for _, _rr in _cmp_data.iterrows():
                    _acc_cases = f_cases[f_cases["account_id"] == _rr["account_id"]]
                    _esc_r = (_rr["escalations"] / max(_rr["total_cases"], 1)) * 100
                    if _esc_r > 10:
                        _analysis_items.append(
                            f"<b>{_rr['account_name']}</b> has a <b>{_esc_r:.0f}% escalation rate</b> — needs attention"
                        )

                _sev_rows = []
                for _, _rr in _cmp_data.iterrows():
                    _acc_cases = f_cases[f_cases["account_id"] == _rr["account_id"]]
                    _high_sev = len(_acc_cases[_acc_cases["severity"].str.contains("1|2", na=False)])
                    if _high_sev > 0:
                        _sev_rows.append(f"<b>{_rr['account_name']}</b>: {_high_sev} high-severity (Sev 1/2)")
                if _sev_rows:
                    _analysis_items.append("Severity breakdown — " + " vs ".join(_sev_rows))

                _products_per_acct = {}
                for _, _rr in _cmp_data.iterrows():
                    _acc_cases = f_cases[f_cases["account_id"] == _rr["account_id"]]
                    _products_per_acct[_rr["account_name"]] = set(_acc_cases["product_name"].dropna().unique())
                _all_names = list(_products_per_acct.keys())
                if len(_all_names) >= 2:
                    _common = set.intersection(*_products_per_acct.values())
                    if _common:
                        _analysis_items.append(
                            f"Shared products across all accounts: <b>{', '.join(sorted(_common)[:4])}</b>"
                            + (f" (+{len(_common)-4} more)" if len(_common) > 4 else "")
                        )
                    else:
                        _analysis_items.append("No overlapping products between these accounts")

                _ttr_parts = []
                for _, _rr in _cmp_data.iterrows():
                    _acc_cases = f_cases[f_cases["account_id"] == _rr["account_id"]]
                    _avg_ttr = _acc_cases["time_to_resolve_hours"].mean()
                    if pd.notna(_avg_ttr):
                        _ttr_parts.append((_rr["account_name"], _avg_ttr))
                if len(_ttr_parts) >= 2:
                    _ttr_parts.sort(key=lambda x: x[1])
                    _analysis_items.append(
                        f"Avg resolution time — <b>{_ttr_parts[0][0]}</b>: {_ttr_parts[0][1]:.0f} hrs "
                        f"vs <b>{_ttr_parts[-1][0]}</b>: {_ttr_parts[-1][1]:.0f} hrs"
                    )

                _open_parts = []
                for _, _rr in _cmp_data.iterrows():
                    _acc_cases = f_cases[f_cases["account_id"] == _rr["account_id"]]
                    _open_c = len(_acc_cases[_acc_cases["status"].isin(["Open", "In Progress", "Waiting on Customer", "Waiting on Engineering"])])
                    if _open_c > 0:
                        _open_parts.append(f"<b>{_rr['account_name']}</b>: {_open_c} open")
                if _open_parts:
                    _analysis_items.append("Active cases — " + ", ".join(_open_parts))

                _rec_items = []
                if _health_gap > 20:
                    _rec_items.append(
                        f"<b>Recommendation:</b> Review support practices from <b>{_best['account_name']}</b> "
                        f"(health {_best.get('health', 0) or 0:.0f}) and apply to <b>{_worst['account_name']}</b> "
                        f"(health {_worst.get('health', 0) or 0:.0f}) to close the gap"
                    )
                for _, _rr in _cmp_data.iterrows():
                    _esc_r = (_rr["escalations"] / max(_rr["total_cases"], 1)) * 100
                    if _esc_r > 15:
                        _acc_cases = f_cases[f_cases["account_id"] == _rr["account_id"]]
                        _esc_prod = _acc_cases[_acc_cases["escalated"] == 1]["product_name"].value_counts()
                        if len(_esc_prod) > 0:
                            _rec_items.append(
                                f"<b>Action:</b> <b>{_rr['account_name']}</b> — assign dedicated SME for "
                                f"<b>{_esc_prod.index[0]}</b> (top escalation product) to reduce {_esc_r:.0f}% escalation rate"
                            )
                if not _rec_items and _ttr_parts and len(_ttr_parts) >= 2 and _ttr_parts[-1][1] > 200:
                    _rec_items.append(
                        f"<b>Recommendation:</b> <b>{_ttr_parts[-1][0]}</b> has avg TTR of {_ttr_parts[-1][1]:.0f} hrs — "
                        f"consider priority queuing or additional resources to match <b>{_ttr_parts[0][0]}</b>'s {_ttr_parts[0][1]:.0f} hrs"
                    )
                _analysis_items.extend(_rec_items)

                if not _analysis_items:
                    _analysis_items.append("Accounts are performing similarly across all metrics")

                _analysis_html = "".join(
                    f'<div style="display:flex;align-items:flex-start;gap:8px;padding:6px 0;'
                    f'border-bottom:1px dashed {PF_BORDER};">'
                    f'<span style="color:#6366F1;font-size:0.85rem;margin-top:1px;">&#9679;</span>'
                    f'<span style="font-size:0.82rem;color:{PF_TEXT};line-height:1.5;">{item}</span></div>'
                    for item in _analysis_items
                )
                st.markdown(_html(f"""<div style="background:var(--secondary-background-color,{PF_SURFACE});
                    border:1px solid var(--border-color,{PF_BORDER});border-radius:{PF_RADIUS};
                    padding:16px 18px;margin:12px 0;">
                    <div style="font-weight:700;font-size:0.85rem;color:{PF_TEXT};margin-bottom:10px;
                        display:flex;align-items:center;gap:8px;">
                        <span style="font-size:1rem;">&#128202;</span> Comparison Analysis
                    </div>
                    {_analysis_html}
                </div>"""), unsafe_allow_html=True)

                if st.button("Clear Comparison", key="_cmp_clear", use_container_width=True):
                    st.session_state["compare_ids"] = []
                    st.rerun()

    _total_all = len(accounts_df)
    _total_filtered = len(f_accounts)
    if _total_filtered < _total_all:
        st.caption(f"Showing **{_total_filtered}** of **{_total_all}** accounts after applying filters")
    else:
        st.caption(f"Showing all **{_total_all}** accounts")

    ov_f1, ov_f2, ov_f3 = st.columns([3, 2, 2])
    with ov_f1:
        ov_search = st.text_input("Search", placeholder="Account name or ID…",
                                   key="ov_acct_search", label_visibility="collapsed")
    with ov_f2:
        ov_health = st.selectbox("Health", ["All Health", "Healthy (80+)", "Moderate (60-79)",
                                             "At Risk (40-59)", "Critical (<40)"],
                                  key="ov_health_filter", label_visibility="collapsed")
    with ov_f3:
        ov_tier = st.selectbox("Tier", ["All Tiers"] + sorted(
            acct_stats["support_tier"].dropna().unique().tolist()),
            key="ov_tier_filter", label_visibility="collapsed")

    _ov_stats = acct_stats.copy()
    if ov_search:
        _q = ov_search.lower()
        _ov_stats = _ov_stats[
            _ov_stats["account_name"].str.lower().str.contains(_q, na=False)
            | _ov_stats["account_id"].str.lower().str.contains(_q, na=False)
        ]
    if ov_health != "All Health":
        if "80+" in ov_health:
            _ov_stats = _ov_stats[_ov_stats["health"] >= 80]
        elif "60-79" in ov_health:
            _ov_stats = _ov_stats[(_ov_stats["health"] >= 60) & (_ov_stats["health"] < 80)]
        elif "40-59" in ov_health:
            _ov_stats = _ov_stats[(_ov_stats["health"] >= 40) & (_ov_stats["health"] < 60)]
        else:
            _ov_stats = _ov_stats[_ov_stats["health"] < 40]
    if ov_tier != "All Tiers":
        _ov_stats = _ov_stats[_ov_stats["support_tier"] == ov_tier]

    total = len(_ov_stats)
    total_pages = max(1, -(-total // CARDS_PER_PAGE))
    if st.session_state.page >= total_pages:
        st.session_state.page = 0

    pg = st.session_state.page
    start = pg * CARDS_PER_PAGE
    end = min(start + CARDS_PER_PAGE, total)
    page_data = _ov_stats.iloc[start:end]

    st.caption(f"Showing {start+1}–{end} of {total} accounts  ·  Page {pg+1} of {total_pages}")

    if st.session_state.get("bulk_toggle"):
        _bk_sel, _bk_all, _bk_clr = st.columns([4, 1, 1])
        with _bk_sel:
            _n_sel = len(st.session_state.get("_bulk_ids", []))
            st.markdown(f'<div style="font-size:0.85rem;color:{PF_TEXT_SEC};padding:6px 0;">'
                        f'<b>{_n_sel}</b> account{"s" if _n_sel != 1 else ""} selected</div>',
                        unsafe_allow_html=True)
        with _bk_all:
            if st.button("Select All", key="_bulk_all", use_container_width=True):
                st.session_state["_bulk_ids"] = page_data["account_id"].tolist()
                st.rerun()
        with _bk_clr:
            if st.button("Clear All", key="_bulk_clr", use_container_width=True):
                st.session_state["_bulk_ids"] = []
                st.rerun()

    for i in range(0, len(page_data), 3):
        chunk = page_data.iloc[i:i+3]
        cols = st.columns(3)
        for idx, (_, row) in enumerate(chunk.iterrows()):
            with cols[idx]:
                csat_s = f"{row['avg_csat']:.1f}" if pd.notna(row["avg_csat"]) else "N/A"
                _health = row['health']
                _h_clr = "#10B981" if _health >= 80 else ("#F59E0B" if _health >= 60 else ("#FB923C" if _health >= 40 else "#EF4444"))
                esc_c = "acct-metric-val warn" if row["escalations"] > 0 else "acct-metric-val"
                st.markdown(_html(f"""<div class="acct-card" style="border-top:3px solid {_h_clr};">
                    <div class="acct-card-header">
                        <div class="acct-name">{row['account_name']} {health_html(row['health'])}</div>
                        <div class="acct-meta">{row['account_id']} &middot; {row.get('sector','')} &middot; {row.get('region','')} {contract_html(row['contract_end_date'])}</div>
                    </div>
                    <div class="acct-metrics">
                        <div class="acct-metric"><div class="acct-metric-val">{row['total_cases']}</div><div class="acct-metric-lbl">Cases</div></div>
                        <div class="acct-metric"><div class="{esc_c}">{row['escalations']}</div><div class="acct-metric-lbl">Escalations</div></div>
                        <div class="acct-metric"><div class="acct-metric-val">{csat_s}</div><div class="acct-metric-lbl">CSAT</div></div>
                    </div>
                    <div class="acct-info">
                        <div class="acct-row"><span class="acct-lbl">Tier</span><span class="acct-val">{row.get('support_tier','N/A')}</span></div>
                        <div class="acct-row"><span class="acct-lbl">Revenue</span><span class="acct-val">{row.get('revenue_segment','N/A')}</span></div>
                    </div>
                    <div class="health-bar-wrap">
                        <div class="health-bar-track">
                            <div class="health-bar-fill" style="width:{min(_health, 100)}%;background:{_h_clr};"></div>
                        </div>
                    </div>
                </div>"""), unsafe_allow_html=True)
                qc, vc, bkc = st.columns([2, 2, 1])
                with qc:
                    if st.button("Quick View", key=f"q_{row['account_id']}", use_container_width=True):
                        account_popup(row["account_id"])
                with vc:
                    if st.button("View Details", key=f"v_{row['account_id']}", use_container_width=True, type="primary"):
                        st.session_state.selected_account = row["account_id"]
                        st.session_state.chat_history = []
                        st.session_state.ai_insight = None
                        st.query_params["view"] = str(row["account_id"])
                        st.rerun()
                with bkc:
                    _is_bk = row["account_id"] in st.session_state.get("bookmarks", [])
                    _bk_label = "⭐" if _is_bk else "☆"
                    if st.button(_bk_label, key=f"bk_{row['account_id']}",
                                 use_container_width=True,
                                 help="Add to favorites" if not _is_bk else "Remove from favorites"):
                        bks = list(st.session_state.get("bookmarks", []))
                        if _is_bk:
                            bks.remove(row["account_id"])
                        else:
                            bks.append(row["account_id"])
                        st.session_state["bookmarks"] = bks
                        st.rerun()
                if st.session_state.get("compare_toggle"):
                    _in_cmp = row["account_id"] in st.session_state.get("compare_ids", [])
                    if st.checkbox("Compare", value=_in_cmp,
                                   key=f"cmp_{row['account_id']}"):
                        if not _in_cmp:
                            cids = list(st.session_state.get("compare_ids", []))
                            if len(cids) < 5:
                                cids.append(row["account_id"])
                                st.session_state["compare_ids"] = cids
                                st.rerun()
                    elif _in_cmp:
                        cids = list(st.session_state.get("compare_ids", []))
                        cids.remove(row["account_id"])
                        st.session_state["compare_ids"] = cids
                        st.rerun()
                if st.session_state.get("bulk_toggle"):
                    _in_blk = row["account_id"] in st.session_state.get("_bulk_ids", [])
                    if st.checkbox("Select", value=_in_blk,
                                   key=f"blk_{row['account_id']}"):
                        if not _in_blk:
                            bids = list(st.session_state.get("_bulk_ids", []))
                            bids.append(row["account_id"])
                            st.session_state["_bulk_ids"] = bids
                            st.rerun()
                    elif _in_blk:
                        bids = list(st.session_state.get("_bulk_ids", []))
                        bids.remove(row["account_id"])
                        st.session_state["_bulk_ids"] = bids
                        st.rerun()

    # ── Bulk Action Bar ──
    _blk_ids = st.session_state.get("_bulk_ids", [])
    if st.session_state.get("bulk_toggle") and _blk_ids:
        st.markdown(_html(f"""<div style="background:linear-gradient(135deg,#6366F1,#818CF8);
            border-radius:12px;padding:12px 20px;margin:12px 0;
            display:flex;align-items:center;justify-content:space-between;
            box-shadow:0 8px 24px rgba(99,102,241,0.25);">
            <span style="color:#fff;font-weight:700;font-size:0.9rem;">
                {len(_blk_ids)} account{"s" if len(_blk_ids) != 1 else ""} selected
            </span>
        </div>"""), unsafe_allow_html=True)
        _ba1, _ba2, _ba3 = st.columns(3)
        with _ba1:
            _bulk_export = acct_stats[acct_stats["account_id"].isin(_blk_ids)]
            st.download_button("Export CSV", _bulk_export.to_csv(index=False),
                               "bulk_accounts.csv", "text/csv",
                               key="_bulk_csv", use_container_width=True)
        with _ba2:
            if st.button("Compare Selected", key="_bulk_cmp", use_container_width=True,
                         disabled=len(_blk_ids) < 2):
                st.session_state["compare_ids"] = _blk_ids[:5]
                st.session_state["_pending_compare"] = True
                st.rerun()
        with _ba3:
            if st.button("Clear Selection", key="_bulk_clear2", use_container_width=True):
                st.session_state["_bulk_ids"] = []
                st.rerun()

    prev_col, pages_col, next_col, goto_col = st.columns([1, 4, 1, 2])

    with prev_col:
        if st.button("Previous", disabled=(pg == 0), key="pg_prev", use_container_width=True):
            st.session_state.page = pg - 1
            st.rerun()

    with pages_col:
        max_visible = 7
        if total_pages <= max_visible:
            page_nums = list(range(1, total_pages + 1))
        else:
            half = max_visible // 2
            if pg + 1 <= half + 1:
                page_nums = list(range(1, max_visible + 1))
            elif pg + 1 >= total_pages - half:
                page_nums = list(range(total_pages - max_visible + 1, total_pages + 1))
            else:
                page_nums = list(range(pg + 1 - half, pg + 1 + half + 1))

        labels = [f'<span class="pg-num{"  active" if n == pg + 1 else ""}">{n}</span>' for n in page_nums]
        st.markdown(
            f'<div class="pg-bar">{"&nbsp;".join(labels)}</div>',
            unsafe_allow_html=True,
        )

    with next_col:
        if st.button("Next", disabled=(pg >= total_pages - 1), key="pg_next", use_container_width=True):
            st.session_state.page = pg + 1
            st.rerun()

    with goto_col:
        go_page = st.number_input(
            "Go to page", min_value=1, max_value=total_pages,
            value=pg + 1, step=1, key="goto_page", label_visibility="collapsed",
        )
        if go_page != pg + 1:
            st.session_state.page = go_page - 1
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# FLOATING AI CHATBOT (accessible from every page)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_chat_context():
    """Build system prompt with data context for the AI chatbot."""
    _sel_account = st.session_state.get("selected_account")
    priority_note = ""

    if _sel_account:
        try:
            acc = accounts_df[accounts_df["account_id"] == _sel_account].iloc[0]
            acc_c = f_cases[f_cases["account_id"] == _sel_account]
            ctx = build_context(acc["account_name"], acc_c)
            case_detail = acc_c[
                ["case_number", "severity", "status", "product_name",
                 "case_owner", "escalated",
                 "csat_score", "time_to_resolve_hours"]
            ].fillna({"csat_score": "Pending", "time_to_resolve_hours": "Pending"}).to_csv(index=False)
            ctx += f"\n\nAll {len(acc_c)} cases for this account:\n{case_detail}"
            other_count = len(f_cases) - len(acc_c)
            ctx += f"\n\nDashboard also has {other_count} cases from {f_cases['account_id'].nunique() - 1} other accounts."
            ctx_label = f"Account Detail: {acc['account_name']}"
            priority_note = (
                f"The user is currently viewing account **{acc['account_name']}**'s detail page. "
                f"ALWAYS answer questions in the context of THIS account first. "
                f"If the user asks 'show all cases' or 'all cases', show THIS account's cases first, "
                f"then mention the broader dashboard totals. Only show other accounts' data if explicitly asked."
            )
        except (IndexError, KeyError):
            ctx, ctx_label = "No account data available.", "Unknown"
    else:
        if len(f_cases) == 0:
            ctx = "No cases in the current filter selection."
            ctx_label = "Dashboard Overview"
            priority_note = "No cases match the current filters."
        else:
            avg_csat = f_cases["csat_score"].mean()
            total_esc = int(f_cases["escalated"].sum())

            status_counts = f_cases["status"].value_counts()
            status_str = ", ".join(f"{s}: {v}" for s, v in status_counts.items())

            prod_counts = f_cases["product_name"].value_counts().head(10)
            prod_str = ", ".join(f"{p}: {v}" for p, v in prod_counts.items())

            sev_str = ", ".join(
                f"Sev{sev}: {len(grp)} cases, CSAT {grp['csat_score'].mean():.1f}, {int(grp['escalated'].sum())} esc"
                for sev, grp in f_cases.groupby("severity")
            )

            reg = f_cases.merge(
                accounts_df[["account_id", "region"]], on="account_id", how="left"
            )["region"].value_counts()
            region_str = ", ".join(f"{r}: {v}" for r, v in reg.items())

            sector_counts = f_cases.merge(
                accounts_df[["account_id", "sector"]], on="account_id", how="left"
            )["sector"].value_counts().head(8)
            sector_str = ", ".join(f"{s}: {v}" for s, v in sector_counts.items())

            total_rev = f_accounts["annual_revenue"].sum()
            rev_str = f"${total_rev/1e9:.2f}B" if total_rev >= 1e9 else f"${total_rev/1e6:.1f}M"

            acct_summary = acct_stats[[
                "account_name", "sector", "region",
                "total_cases", "escalations", "avg_csat", "health"
            ]].copy()
            acct_summary = acct_summary.sort_values("total_cases", ascending=False)
            acct_summary["avg_csat"] = acct_summary["avg_csat"].round(1)
            acct_csv = acct_summary.head(10).to_csv(index=False)

            open_cases = len(f_cases[f_cases["status"].isin(["Open", "In Progress", "Waiting on Customer", "Waiting on Engineering"])])
            resolved_cases = len(f_cases[f_cases["status"].isin(["Resolved", "Closed"])])
            res_rate = resolved_cases / len(f_cases) * 100 if len(f_cases) else 0
            esc_rate = total_esc / len(f_cases) * 100 if len(f_cases) else 0
            avg_ttr = f_cases["time_to_resolve_hours"].mean()
            pending_csat = int(f_cases["csat_score"].isna().sum())

            tier_counts = f_accounts["support_tier"].value_counts()
            tier_str = ", ".join(f"{t}: {v}" for t, v in tier_counts.items())

            at_risk = acct_stats[acct_stats["health"] == "At Risk"] if "health" in acct_stats.columns else pd.DataFrame()
            risk_csv = at_risk[["account_name", "total_cases", "escalations", "avg_csat"]].head(10).to_csv(index=False) if len(at_risk) > 0 else "None"

            case_sample = f_cases[
                ["case_number", "account_name", "severity", "status",
                 "product_name", "case_owner", "escalated",
                 "csat_score", "time_to_resolve_hours"]
            ].copy()
            case_sample = case_sample.fillna({"csat_score": "Pending", "time_to_resolve_hours": "Pending"})
            case_sample = case_sample.head(20)
            case_csv = case_sample.to_csv(index=False)

            ctx = (
                f"Dashboard Overview:\n"
                f"Total Accounts: {len(f_accounts)} | Total Cases: {len(f_cases)}\n"
                f"Open Cases: {open_cases} | Resolved: {resolved_cases} ({res_rate:.0f}%)\n"
                f"Avg CSAT: {avg_csat:.1f}/5.0 ({pending_csat} pending surveys) | Escalations: {total_esc} ({esc_rate:.1f}%)\n"
                f"Avg TTR: {avg_ttr:.0f} hrs | Revenue: {rev_str}\n"
                f"Support Tiers: {tier_str}\n"
                f"Status: {status_str}\n"
                f"Products: {prod_str}\n"
                f"Severity: {sev_str}\n"
                f"Regions: {region_str}\n"
                f"Sectors: {sector_str}\n\n"
                f"At-Risk Accounts:\n{risk_csv}\n\n"
                f"Top 10 Accounts by Cases:\n{acct_csv}\n\n"
                f"Sample Case Data ({len(case_sample)} of {len(f_cases)} total):\n{case_csv}"
            )
            ctx_label = "Dashboard Overview"
            priority_note = (
                "The user is on the main accounts overview page. Answer in the context of all accounts. "
                "If asked about 'all cases', use the aggregate stats and sample case data provided."
            )

    _ref_data = ""
    if _sel_account:
        _all_sectors = f_accounts["sector"].value_counts()
        _sector_str = ", ".join(f"{s}: {c}" for s, c in _all_sectors.items())
        _all_regions = f_cases.merge(
            accounts_df[["account_id", "region"]], on="account_id", how="left"
        )["region"].value_counts()
        _region_str = ", ".join(f"{r}: {c}" for r, c in _all_regions.items())
        _all_products = f_cases["product_name"].value_counts().head(10)
        _prod_str = ", ".join(f"{p}: {c}" for p, c in _all_products.items())
        _tier_counts = f_accounts["support_tier"].value_counts()
        _tier_str = ", ".join(f"{t}: {c}" for t, c in _tier_counts.items())
        _total_esc = int(f_cases["escalated"].sum())
        _avg_csat_all = f_cases["csat_score"].mean()
        _acct_names = f_accounts["account_name"].tolist()

        _ref_data = (
            f"\n\n--- Reference Data (Full Dashboard) ---\n"
            f"Total Accounts: {len(f_accounts)} | Total Cases: {len(f_cases)}\n"
            f"Avg CSAT: {f'{_avg_csat_all:.1f}' if pd.notna(_avg_csat_all) else 'N/A'}/5 | Escalations: {_total_esc}\n"
            f"Sectors: {_sector_str}\n"
            f"Regions: {_region_str}\n"
            f"Products: {_prod_str}\n"
            f"Support Tiers: {_tier_str}\n"
            f"All Accounts ({len(_acct_names)}): {', '.join(_acct_names[:30])}"
            f"{'... and ' + str(len(_acct_names) - 30) + ' more' if len(_acct_names) > 30 else ''}"
        )

    return {
        "role": "system",
        "content": (
            "You are Insight Hub, AI analyst for a Red Hat Customer Intelligence Dashboard.\n"
            "SCOPE: ONLY answer questions about this dashboard's data — accounts, cases, CSAT, escalations, "
            "products, regions, sectors, health scores, revenue, support tiers. "
            "Refuse ALL other topics (recipes, weather, code, jokes, etc.) with: "
            "'I can only help with dashboard data. Try asking about accounts, cases, or CSAT.'\n"
            "RULES:\n"
            "- ONLY use data provided below. NEVER fabricate or hallucinate case numbers, names, or metrics.\n"
            "- CONTEXT PRIORITY: " + priority_note + "\n"
            "- When asked 'all cases' or 'show cases', show data from the CURRENT VIEW first, "
            "then mention broader totals from the Reference Data section.\n"
            "- If the question is about something NOT in the current view (e.g. asking about sectors or regions "
            "while on an account detail page), use the Reference Data section to answer.\n"
            "- If data is partial, state that clearly.\n"
            "- Lead with assessment. Use **bold** for metrics. Use markdown tables for rankings.\n"
            "- Show 'Pending' not 'NaN'. CSAT scale: 1-5 (5=best).\n"
            "- Health: Healthy(CSAT>=4,esc<10%), Needs Attention(CSAT>=3), At Risk.\n"
            "- Be concise. Never invent data.\n\n"
            f"Current View: {ctx_label}\n{ctx}"
            f"{_ref_data}"
        ),
    }


_OFFTOPIC_WORDS = {
    "recipe", "recipes", "cook", "cooking", "pizza", "burger", "food", "restaurant",
    "weather", "forecast", "movie", "movies", "song", "songs", "lyrics",
    "music", "game", "games", "sports", "football", "cricket", "basketball", "soccer",
    "joke", "jokes", "funny", "meme", "poem", "poetry", "story", "fiction", "novel",
    "travel", "vacation", "holiday", "tourism", "hotel",
    "code", "python", "javascript", "html", "css", "program", "programming", "coding",
    "homework", "essay", "assignment", "translate", "translation",
    "stock", "crypto", "bitcoin", "investment", "dating", "relationship",
    "diet", "exercise", "workout", "gym", "yoga", "meditation",
    "news", "politics", "election", "celebrity", "gossip",
}

_ONTOPIC_WORDS = {
    "case", "cases", "account", "accounts", "csat", "escalat", "escalation", "escalations",
    "health", "sector", "region", "product", "products", "support", "tier",
    "revenue", "dashboard", "severity", "resolved", "open", "status",
    "associate", "engineer", "owner", "tam", "red hat", "rhel", "openshift",
    "ansible", "satellite", "ceph", "jboss", "ttr", "resolution",
}

def _is_offtopic(text):
    lower = text.lower()
    words = set(lower.split())
    has_offtopic = len(words & _OFFTOPIC_WORDS) >= 1
    has_ontopic = any(kw in lower for kw in _ONTOPIC_WORDS)
    return has_offtopic and not has_ontopic


def _process_chat_message(user_msg):
    """Process a chat message: add to history, call AI, store reply."""
    cleaned = _sanitize_ai_input(user_msg)
    if not cleaned:
        st.session_state.global_chat.append({"role": "user", "content": user_msg})
        st.session_state.global_chat.append({"role": "assistant", "content": "Please enter a valid question about the dashboard data."})
        return
    if _is_offtopic(cleaned):
        st.session_state.global_chat.append({"role": "user", "content": cleaned})
        st.session_state.global_chat.append({"role": "assistant",
            "content": "I can only assist with questions about the customer support data in this dashboard. "
                        "Try asking about accounts, cases, CSAT, health scores, or products."})
        return
    st.session_state.global_chat.append({"role": "user", "content": cleaned})
    sys_prompt = _build_chat_context()
    recent = st.session_state.global_chat[-20:]
    chat_msgs = [sys_prompt] + [
        {"role": m["role"], "content": m["content"]}
        for m in recent
    ]
    reply = call_ai(chat_msgs, max_tokens=1024)
    if reply is None:
        reply = ("AI endpoint is not configured. Set AI_ENDPOINT_URL, "
                 "AI_API_TOKEN, AI_MODEL_ID in your .env file.")
    reply = _sanitize_ai_output(reply)
    st.session_state.global_chat.append({"role": "assistant", "content": reply})


@st.dialog("Insight Hub", width="large")
def _show_ai_chat():
    """Floating AI chat dialog."""
    pending = st.session_state.pop("_ai_pending", None)
    if pending:
        with st.spinner("Processing..."):
            _process_chat_message(pending)

    st.markdown(_html(f"""<div class="ai-chat-hdr">
        <div class="ai-chat-avatar">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 3l1.912 5.813a2 2 0 0 0 1.275 1.275L21 12l-5.813 1.912a2 2 0 0 0-1.275 1.275L12 21l-1.912-5.813a2 2 0 0 0-1.275-1.275L3 12l5.813-1.912a2 2 0 0 0 1.275-1.275L12 3Z"/>
            </svg>
        </div>
        <div class="ai-chat-hdr-text">
            <div class="ai-chat-title">Insight Hub</div>
            <div class="ai-chat-subtitle">Powered by IBM Granite</div>
        </div>
        <div class="ai-chat-status">
            <span class="ai-status-dot"></span> Online
        </div>
    </div>"""), unsafe_allow_html=True)

    if st.session_state.global_chat:
        with st.container(height=380):
            for idx, m in enumerate(st.session_state.global_chat):
                with st.chat_message(m["role"]):
                    st.markdown(m["content"])
    else:
        st.markdown(_html("""<div class="ai-welcome">
            <h4>Insight Hub</h4>
            <p>Ask anything about your customer data &mdash; accounts, cases,
            associates, escalations, CSAT scores, and more.</p>
            <div class="ai-welcome-suggestions">
                <div class="ai-suggestion">&mdash; "Which accounts have the most escalations?"</div>
                <div class="ai-suggestion">&mdash; "Show me CSAT trends across regions"</div>
                <div class="ai-suggestion">&mdash; "What are the top products by case volume?"</div>
            </div>
        </div>"""), unsafe_allow_html=True)

    with st.form("ai_dialog_form", clear_on_submit=True):
        cols = st.columns([6, 1])
        with cols[0]:
            user_input = st.text_input(
                "Message",
                placeholder="Ask anything...",
                label_visibility="collapsed",
            )
        with cols[1]:
            submitted = st.form_submit_button("Send")

    if submitted and user_input:
        st.session_state["_ai_pending"] = user_input
        st.rerun(scope="fragment")

    if st.session_state.global_chat:
        cols = st.columns([1, 1])
        with cols[0]:
            if st.button("Clear conversation", key="clear_chat_btn",
                         use_container_width=True):
                st.session_state.global_chat = []
                st.rerun(scope="fragment")
        with cols[1]:
            st.markdown(
                f'<div style="text-align:right;color:{PF_TEXT_SEC};font-size:0.7rem;'
                f'padding-top:8px;">Powered by IBM Granite</div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            f'<div style="text-align:center;color:{PF_TEXT_SEC};font-size:0.7rem;'
            f'margin-top:4px;">Powered by IBM Granite</div>',
            unsafe_allow_html=True,
        )


def render_floating_chat():
    """Floating AI button + chat trigger."""
    if st.sidebar.button("Insight Hub", use_container_width=True,
                          type="primary", key="open_ai_chat"):
        if not st.session_state.get("_dialog_open"):
            _show_ai_chat()

    st.markdown(_html(f"""<div class="ai-fab-wrap" title="Open Insight Hub">
        <div class="ai-fab">
            <span class="ai-fab-icon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 3l1.912 5.813a2 2 0 0 0 1.275 1.275L21 12l-5.813 1.912a2 2 0 0 0-1.275 1.275L12 21l-1.912-5.813a2 2 0 0 0-1.275-1.275L3 12l5.813-1.912a2 2 0 0 0 1.275-1.275L12 3Z"/>
                </svg>
            </span>
        </div>
    </div>"""), unsafe_allow_html=True)

    st_components.html("""
    <script>
    (function() {
        const pd = window.parent.document;
        const setupFab = () => {
            const fab = pd.querySelector('.ai-fab-wrap');
            if (!fab || fab._aibound) return;
            fab._aibound = true;
            fab.addEventListener('click', () => {
                const sidebar = pd.querySelector('[data-testid="stSidebar"]');
                if (!sidebar) return;
                const btns = sidebar.querySelectorAll('button');
                for (const b of btns) {
                    if (b.innerText.includes('Insight Hub')) { b.click(); break; }
                }
            });
        };
        const scrollChat = () => {
            const dlg = pd.querySelector('[role="dialog"]');
            if (!dlg) return;
            const scrollDivs = dlg.querySelectorAll('[style*="overflow"]');
            scrollDivs.forEach(c => { c.scrollTop = c.scrollHeight; });
        };
        if (!pd._aiEscBound) {
            pd._aiEscBound = true;
            pd.addEventListener('keydown', e => {
                if (e.key === 'Escape') {
                    const modal = pd.querySelector('[data-testid="stModal"]');
                    if (modal) {
                        const btns = modal.querySelectorAll('button');
                        if (btns.length) btns[0].click();
                    }
                }
            });
        }
        setupFab();
        setTimeout(setupFab, 600);
        setTimeout(scrollChat, 300);
        setTimeout(scrollChat, 1200);
        const addClearBtns = () => {
            pd.querySelectorAll('div.stTextInput input[type="text"]').forEach(inp => {
                const ph = (inp.placeholder||'').toLowerCase();
                if ((!ph.includes('search') && !ph.includes('account') && !ph.includes('name or')) || inp._clrDone) return;
                inp._clrDone = true;
                const wrap = inp.parentElement; wrap.style.position = 'relative';
                const btn = pd.createElement('button'); btn.className = 'search-clear-btn';
                btn.innerHTML = '&#10005;'; btn.type = 'button'; btn.title = 'Clear';
                wrap.appendChild(btn);
                const toggle = () => { btn.style.display = inp.value ? 'block' : 'none'; };
                inp.addEventListener('input', toggle);
                toggle();
                btn.addEventListener('click', e => {
                    e.preventDefault(); e.stopPropagation();
                    const set = Object.keys(inp).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$'));
                    if (set) { const nSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                        nSet.call(inp, ''); inp.dispatchEvent(new Event('input', {bubbles:true}));
                        inp.dispatchEvent(new Event('change', {bubbles:true}));
                    } else { inp.value = ''; }
                    inp.focus(); toggle();
                });
            });
        };
        addClearBtns(); setTimeout(addClearBtns, 1500);
        new MutationObserver(() => setTimeout(addClearBtns, 200)).observe(pd.body, {childList:true, subtree:true});
    })();
    </script>
    """, height=0)


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTING
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="page-loader"></div>', unsafe_allow_html=True)
st.session_state["_dialog_open"] = False

if st.session_state.selected_account:
    render_detail(st.session_state.selected_account)
else:
    render_dashboard()

render_floating_chat()

if st.session_state.get("authenticated"):
    _save_session()
