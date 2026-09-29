"""Workspace Selection page — shown after login before dashboard loads."""

import streamlit as st
from workspace_utils import build_switch_url, nav_link

_WS_CSS = """<style>
[data-testid="stSidebar"]{display:none!important}
header[data-testid="stHeader"]{display:none!important}
#MainMenu{visibility:hidden}footer{visibility:hidden}
.stApp{background:linear-gradient(135deg,#F5F3FF 0%,#F8F7F4 30%,#FDF2F8 60%,#F0FDF4 100%)!important}
.block-container{max-width:880px!important;padding:60px 24px 40px!important}
@keyframes wsFadeUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
@keyframes wsFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}
.ws-hero{text-align:center;padding:20px 0 8px;animation:wsFadeUp 0.5s ease-out}
.ws-hero h1{color:#1E293B;font-size:1.5rem;font-weight:800;margin:0 0 4px;letter-spacing:-0.02em}
.ws-hero p{color:#64748B;font-size:0.88rem;margin:0}
.ws-card{
    background:rgba(255,255,255,0.55);backdrop-filter:blur(24px) saturate(180%);
    -webkit-backdrop-filter:blur(24px) saturate(180%);
    border:1px solid rgba(255,255,255,0.6);border-radius:20px;
    padding:32px 24px;text-align:center;
    transition:all 0.4s cubic-bezier(0.34,1.56,0.64,1);
    box-shadow:0 8px 32px rgba(0,0,0,0.04),0 2px 8px rgba(0,0,0,0.03);
    animation:wsFadeUp 0.6s ease-out both;position:relative;overflow:hidden;
}
.ws-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;border-radius:20px 20px 0 0}
.ws-card:hover{
    background:rgba(255,255,255,0.75);transform:translateY(-6px);
    box-shadow:0 20px 48px rgba(0,0,0,0.08),0 8px 20px rgba(0,0,0,0.06);
}
.ws-card-assoc::before{background:linear-gradient(90deg,#3B82F6,#6366F1)}
.ws-card-assoc:hover{border-color:rgba(59,130,246,0.3)}
.ws-card-cust::before{background:linear-gradient(90deg,#8B5CF6,#EC4899)}
.ws-card-cust:hover{border-color:rgba(139,92,246,0.3)}
.ws-icon{width:56px;height:56px;border-radius:16px;display:inline-flex;align-items:center;
    justify-content:center;margin-bottom:14px;animation:wsFloat 4s ease-in-out infinite}
.ws-icon-assoc{background:rgba(59,130,246,0.08);border:1.5px solid rgba(59,130,246,0.2)}
.ws-icon-cust{background:rgba(139,92,246,0.08);border:1.5px solid rgba(139,92,246,0.2)}
.ws-title{color:#1E293B;font-size:1.05rem;font-weight:700;margin-bottom:6px}
.ws-desc{color:#64748B;font-size:0.78rem;line-height:1.6;margin-bottom:14px}
.ws-features{text-align:left;margin:0 auto 16px;display:inline-block}
.ws-feat{display:flex;align-items:center;gap:6px;padding:3px 0;font-size:0.72rem;color:#475569}
.ws-feat svg{flex-shrink:0}
.ws-hint{text-align:center;margin-top:16px;font-size:0.72rem;color:#94A3B8}
</style>"""

_CHK_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10B981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'

_ASSOC_ICON = '''<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#3B82F6"
     stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
    <circle cx="9" cy="7" r="4"/>
    <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
    <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
</svg>'''

_CUST_ICON = '''<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#8B5CF6"
     stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
    <line x1="8" y1="21" x2="16" y2="21"/>
    <line x1="12" y1="17" x2="12" y2="21"/>
</svg>'''


def render_workspace_selector(current_app):
    _display = st.session_state.get("display_name", "User")
    _token = st.session_state.get("jwt_token", "")

    st.markdown(_WS_CSS, unsafe_allow_html=True)

    st.markdown(f'''<div class="ws-hero">
        <p style="color:#6366F1;font-size:0.68rem;font-weight:700;text-transform:uppercase;
            letter-spacing:0.18em;margin-bottom:6px">Welcome back, {_display} \U0001f44b</p>
        <h1>Choose Your Workspace</h1>
        <p>Select a dashboard to get started</p>
    </div>''', unsafe_allow_html=True)

    st.markdown("")

    c1, c2 = st.columns(2, gap="large")

    with c1:
        st.markdown(f'''<div class="ws-card ws-card-assoc" style="animation-delay:0.1s">
            <div class="ws-icon ws-icon-assoc">{_ASSOC_ICON}</div>
            <div class="ws-title">\U0001f465 Associates Dashboard</div>
            <div class="ws-desc">Manage associates, skills, teams,<br>certifications and performance</div>
            <div class="ws-features">
                <div class="ws-feat">{_CHK_SVG} Team / SBR Management</div>
                <div class="ws-feat">{_CHK_SVG} Skills &amp; Certifications</div>
                <div class="ws-feat">{_CHK_SVG} Workload &amp; Performance</div>
                <div class="ws-feat">{_CHK_SVG} AI Skill Extraction</div>
            </div>
        </div>''', unsafe_allow_html=True)
        if current_app == "associate":
            if st.button("Open Workspace  →", key="ws_goto_assoc",
                         use_container_width=True, type="primary"):
                st.session_state._workspace = "selected"
                st.rerun()
        else:
            nav_link("Open Workspace  →", build_switch_url("associate", _token))

    with c2:
        st.markdown(f'''<div class="ws-card ws-card-cust" style="animation-delay:0.2s">
            <div class="ws-icon ws-icon-cust">{_CUST_ICON}</div>
            <div class="ws-title">\U0001f3e2 Customer Dashboard</div>
            <div class="ws-desc">Monitor customer health, cases,<br>escalations and insights</div>
            <div class="ws-features">
                <div class="ws-feat">{_CHK_SVG} Customer Overview</div>
                <div class="ws-feat">{_CHK_SVG} Cases &amp; Trends</div>
                <div class="ws-feat">{_CHK_SVG} Customer Health</div>
                <div class="ws-feat">{_CHK_SVG} AI Insights</div>
            </div>
        </div>''', unsafe_allow_html=True)
        if current_app == "customer":
            if st.button("Open Workspace  →", key="ws_goto_cust",
                         use_container_width=True, type="primary"):
                st.session_state._workspace = "selected"
                st.rerun()
        else:
            nav_link("Open Workspace  →", build_switch_url("customer", _token))

    st.markdown('<p class="ws-hint">\U0001f504 You can switch between workspaces anytime from the header</p>',
                unsafe_allow_html=True)
