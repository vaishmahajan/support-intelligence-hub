"""Header workspace switcher — popover dropdown near logout button."""

import streamlit as st
from workspace_utils import (
    WORKSPACE_LABELS, WORKSPACE_DESCS, WORKSPACE_ICONS_SVG,
    build_switch_url, nav_link,
)

WORKSPACE_SHORT = {
    "associate": "Associates",
    "customer": "Customer",
}

_CARD_COLORS = {
    "associate": ("#3B82F6", "#6366F1", "rgba(59,130,246,0.08)", "rgba(59,130,246,0.2)"),
    "customer": ("#8B5CF6", "#EC4899", "rgba(139,92,246,0.08)", "rgba(139,92,246,0.2)"),
}

_SWITCH_ICONS = {
    "associate": '''<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#3B82F6"
         stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
        <circle cx="9" cy="7" r="4"/>
        <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
        <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
    </svg>''',
    "customer": '''<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#8B5CF6"
         stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
        <line x1="8" y1="21" x2="16" y2="21"/>
        <line x1="12" y1="17" x2="12" y2="21"/>
    </svg>''',
}


def render_workspace_switcher(current_app):
    other_app = "customer" if current_app == "associate" else "associate"
    current_short = WORKSPACE_SHORT[current_app]
    other_label = WORKSPACE_LABELS[other_app]
    other_desc = WORKSPACE_DESCS[other_app]
    token = st.session_state.get("jwt_token", "")
    switch_url = build_switch_url(other_app, token)

    c1, c2, bg, border = _CARD_COLORS[other_app]

    with st.popover(f"⇄  {current_short} Dashboard", use_container_width=True):
        st.markdown(
            f'<div style="background:{bg};border:1.5px solid {border};'
            f'border-radius:14px;padding:16px 14px 12px;text-align:center;">'
            f'<div style="width:44px;height:44px;border-radius:12px;display:inline-flex;align-items:center;'
            f'justify-content:center;background:white;border:1.5px solid {border};margin-bottom:10px;">'
            f'{_SWITCH_ICONS[other_app]}</div>'
            f'<div style="font-size:0.88rem;font-weight:700;color:#1E293B;margin-bottom:3px;">{other_label}</div>'
            f'<div style="font-size:0.72rem;color:#64748B;margin-bottom:14px;">{other_desc}</div>'
            f'<a href="{switch_url}" target="_self" style="display:block;width:100%;text-align:center;padding:9px 14px;'
            f'border-radius:10px;background:linear-gradient(135deg,{c1},{c2});color:#fff;font-size:0.82rem;'
            f'font-weight:600;text-decoration:none;box-sizing:border-box;">Switch to {WORKSPACE_SHORT[other_app]}  →</a>'
            f'</div>',
            unsafe_allow_html=True,
        )
