"""Shared workspace utilities for cross-app navigation."""

import re
from datetime import datetime, timedelta, timezone

import streamlit as st
from jose import jwt, JWTError

import config

_HTML_WS = re.compile(r"\n\s*")


def _html(markup):
    """Collapse a multi-line HTML template onto one line.

    An interpolated value that comes back empty leaves a whitespace-only line
    behind. Markdown reads that as a blank line, closes the HTML block early,
    and renders everything after it as an indented code block. Lives here
    rather than in either dashboard because both of them need it.
    """
    return _HTML_WS.sub(" ", markup).strip()

WORKSPACE_PORTS = {
    "associate": 8502,
    "customer": 8501,
}

WORKSPACE_LABELS = {
    "associate": "Associates Dashboard",
    "customer": "Customer Dashboard",
}

WORKSPACE_DESCS = {
    "associate": "Manage associates, skills, teams and performance",
    "customer": "Monitor customer health, cases and insights",
}

WORKSPACE_ICONS_SVG = {
    "associate": '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    "customer": '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>',
}


def mint_handoff(jwt_token):
    """Trade a session token for a short-lived one safe to put in a URL.

    The link used to carry the full session JWT — a 60-minute credential
    landing in browser history, bookmarks, referrer headers and proxy logs.
    A handoff token names the same user but expires in
    ``HANDOFF_TTL_SECONDS`` and is marked ``typ="handoff"``, which the REST
    API refuses outright. Copy the link to a colleague and it is already dead.

    Returns the original token unchanged if it cannot be decoded, so a
    misconfigured secret degrades to the previous behaviour rather than
    silently producing links that do not log anyone in.
    """
    if not jwt_token:
        return ""
    try:
        claims = jwt.decode(jwt_token, config.JWT_SECRET,
                            algorithms=[config.JWT_ALGORITHM])
    except JWTError:
        return jwt_token
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": claims.get("sub"), "role": claims.get("role"), "iat": now,
         "exp": now + timedelta(seconds=config.HANDOFF_TTL_SECONDS),
         "typ": "handoff"},
        config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def workspace_base_url(target_app):
    """Where a browser reaches the other dashboard. Configured, not assumed."""
    return (config.CUSTOMER_URL if target_app == "customer"
            else config.ASSOCIATES_URL)


def build_switch_url(target_app, jwt_token):
    return f"{workspace_base_url(target_app)}/?token={mint_handoff(jwt_token)}"


def nav_link(label, url, primary=True):
    """Render an <a> tag styled as a button — navigates same window, no iframe."""
    if primary:
        style = (
            "display:block;width:100%;text-align:center;padding:11px 16px;"
            "border-radius:10px;background:linear-gradient(135deg,#8B5CF6,#6366F1);"
            "color:#fff;font-size:0.85rem;font-weight:600;text-decoration:none;"
            "box-sizing:border-box;"
        )
    else:
        style = (
            "display:block;width:100%;text-align:center;padding:11px 16px;"
            "border-radius:10px;background:#F8FAFC;border:1px solid #E2E8F0;"
            "color:#1E293B;font-size:0.85rem;font-weight:600;text-decoration:none;"
            "box-sizing:border-box;"
        )
    # target="_self" is the browser default, but state it: a stray target="_blank"
    # anywhere in this chain would hand the other dashboard a fresh tab and a
    # handoff token that expires before anyone finishes reading the first one.
    st.markdown(f'<a href="{url}" target="_self" style="{style}">{label}</a>',
                unsafe_allow_html=True)
