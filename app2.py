#!/usr/bin/env python3
"""
Associates Operational Dashboard — Business Requirement #2

Run:  streamlit run app2.py --server.port 8502
"""

import os
import re
import json
import hashlib
import time
from datetime import datetime, date, timedelta, timezone

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
from my_desk import render_my_desk, _html

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

ROLE_PERMISSIONS = {
    "admin":     {"associate_view": True, "team_view": True, "skills_view": True, "data_ingest": True,  "ai_extract": True},
    "manager":   {"associate_view": True, "team_view": True, "skills_view": True, "data_ingest": False, "ai_extract": True},
    "associate": {"associate_view": True, "team_view": False, "skills_view": True, "data_ingest": False, "ai_extract": False},
}

CARDS_PER_PAGE = 12

st.set_page_config(
    page_title="Associates Dashboard",
    page_icon="RH",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════════════════════
# DESIGN TOKENS — PatternFly Dark (same as app1.py)
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

# ── Theme Detection (adapts to Streamlit light/dark toggle) ──
_THEME = "light"
try:
    _tb = st.get_option("theme.base")
    if _tb:
        _THEME = _tb
except Exception:
    pass

IS_DARK       = False
CHART_TPL     = "plotly_white"
CHART_FONT    = "#1E293B"
CHART_FONT2   = "#64748B"
CHART_GRID    = "rgba(0,0,0,0.06)"
CHART_BG      = "rgba(0,0,0,0)"
CHART_HM_FONT = "#1E293B"

SEVERITY_COLORS = {
    "Severity 1 (Urgent)": "#EF4444",
    "Severity 2 (High)": RH_GOLD,
    "Severity 3 (Normal)": RH_TEAL,
    "Severity 4 (Low)": RH_GRAY,
}

STATUS_COLORS = {
    "Open": "#EF4444", "In Progress": RH_GOLD,
    "Waiting on Customer": RH_ORANGE, "Waiting on Engineering": RH_PURPLE,
    "Resolved": RH_GREEN, "Closed": RH_GRAY,
}

SHIFT_COLORS = {"EMEA": RH_BLUE, "APAC": RH_GOLD, "NASA": RH_TEAL, "India": RH_PURPLE}

DRILL_COLS = ["case_number", "severity", "status", "product_name",
              "problem_statement", "case_owner", "creation_date", "escalated"]

SKILL_COLORS = [
    "#6366F1", "#06B6D4", "#8B5CF6", "#10B981", "#F59E0B",
    "#3B82F6", "#FB923C", "#F43F5E", "#94A3B8", "#4F46E5",
]

GRADIENT_PAIRS = [
    ("#6366F1", "#A78BFA"),
    ("#06B6D4", "#67E8F9"),
    ("#8B5CF6", "#C4B5FD"),
    ("#3B82F6", "#93C5FD"),
    ("#10B981", "#6EE7B7"),
    ("#F59E0B", "#FCD34D"),
]


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


SKILL_PRODUCT_MAP = {
    "OpenShift": "OpenShift Container Platform",
    "Ansible": "Ansible Automation Platform",
    "RHEL Administration": "Enterprise Linux",
    "Kubernetes": "OpenShift / Kubernetes",
    "Ceph Storage": "Ceph Storage",
    "JBoss EAP": "JBoss EAP",
    "JBoss Middleware": "JBoss Middleware Suite",
    "API Management": "3scale API Management",
    "Container Platform": "OpenShift Container Platform",
    "Service Mesh/Istio": "OpenShift Service Mesh",
    "Identity Management": "Identity Management (IdM)",
    "Networking": "Enterprise Linux Networking",
    "Kernel/OS": "Enterprise Linux Kernel",
    "Cloud (AWS)": "Cloud Services on AWS",
    "Cloud (Azure)": "Cloud Services on Azure",
    "Certificate Management": "Certificate System",
    "Security/Compliance": "Insights Compliance",
    "Clustering": "High Availability Add-On",
    "Virtualization": "OpenShift Virtualization",
    "Storage": "OpenShift Data Foundation",
    "Monitoring & Observability": "OpenShift Observability",
    "Advanced Cluster Management": "ACM for Kubernetes",
    "OpenShift AI": "OpenShift AI (RHOAI)",
    "OpenShift Container Storage": "OCS",
    "OpenShift Data Foundation": "ODF",
    "OpenStack": "OpenStack Platform",
    "Migration Toolkit": "Migration Toolkit",
    "Directory Services": "Directory Server",
    "CloudForms": "CloudForms",
    "Red Hat Satellite": "Satellite",
    "Red Hat Insights": "Insights",
    "Red Hat Fuse": "Fuse (Integration)",
    "Integration": "Integration / Camel",
    "Smart Management": "Smart Management",
    "AMQ Messaging": "AMQ Broker",
    "AMQ Streams/Kafka": "AMQ Streams (Kafka)",
    "Performance Tuning": "Enterprise Linux Performance",
    "Serverless/Knative": "OpenShift Serverless",
    "Upgrades & Migration": "Upgrade & Migration Tools",
}

SKILL_SUMMARY_MAP = {
    "OpenShift": "Deploy, manage, and scale containerized applications on Red Hat's Kubernetes platform.",
    "Ansible": "Automate IT provisioning, configuration management, and application deployment.",
    "RHEL Administration": "Install, configure, and maintain Red Hat Enterprise Linux systems.",
    "Kubernetes": "Orchestrate container workloads across clusters using Kubernetes.",
    "Ceph Storage": "Manage distributed object, block, and file storage with Ceph.",
    "JBoss EAP": "Build and deploy enterprise Java applications on JBoss Enterprise Application Platform.",
    "JBoss Middleware": "Integrate enterprise services using Red Hat's middleware and integration suite.",
    "API Management": "Secure, manage, and monitor APIs with 3scale API Management.",
    "Container Platform": "Administer and troubleshoot OpenShift Container Platform deployments.",
    "Service Mesh/Istio": "Configure service-to-service communication, observability, and security with Istio.",
    "Identity Management": "Manage centralized authentication, authorization, and user identity services.",
    "Networking": "Configure and troubleshoot network interfaces, routing, and firewall rules on RHEL.",
    "Kernel/OS": "Debug kernel-level issues, tune system performance, and manage OS internals.",
    "Cloud (AWS)": "Deploy and manage Red Hat workloads on Amazon Web Services.",
    "Cloud (Azure)": "Deploy and manage Red Hat workloads on Microsoft Azure.",
    "Certificate Management": "Issue, renew, and manage digital certificates and PKI infrastructure.",
    "Security/Compliance": "Assess and enforce security policies and regulatory compliance using Insights.",
    "Clustering": "Configure and maintain high-availability clusters and failover mechanisms.",
    "Virtualization": "Run and manage virtual machines using OpenShift Virtualization (KubeVirt).",
    "Storage": "Manage persistent storage with OpenShift Data Foundation for container workloads.",
    "Monitoring & Observability": "Set up metrics, logging, and tracing for OpenShift environments.",
    "Advanced Cluster Management": "Manage multi-cluster Kubernetes environments at scale with ACM.",
    "OpenShift AI": "Build and serve machine learning models on the OpenShift AI platform.",
    "OpenShift Container Storage": "Provision and manage container-native storage with OCS.",
    "OpenShift Data Foundation": "Deliver persistent, portable storage for OpenShift containers.",
    "OpenStack": "Build and operate private cloud infrastructure on Red Hat OpenStack Platform.",
    "Migration Toolkit": "Migrate workloads between platforms using Red Hat Migration Toolkit.",
    "Directory Services": "Manage LDAP directory services and replication with Red Hat Directory Server.",
    "CloudForms": "Manage hybrid cloud environments with policy-driven automation.",
    "Red Hat Satellite": "Manage content, patching, and provisioning across RHEL infrastructure at scale.",
    "Red Hat Insights": "Proactively identify and remediate risks using predictive analytics.",
    "Red Hat Fuse": "Integrate applications and data using Apache Camel-based integration.",
    "Integration": "Connect distributed applications and services with Red Hat Integration.",
    "Smart Management": "Combine Satellite and Insights for unified RHEL lifecycle management.",
    "AMQ Messaging": "Deploy and manage message brokers for reliable asynchronous communication.",
    "AMQ Streams/Kafka": "Build real-time data streaming pipelines with Apache Kafka on OpenShift.",
    "Performance Tuning": "Optimize system and application performance on Enterprise Linux.",
    "Serverless/Knative": "Deploy event-driven and serverless workloads on OpenShift with Knative.",
    "Upgrades & Migration": "Plan and execute RHEL and OpenShift version upgrades and migrations.",
}

CERT_SKILL_MAP = {
    "RHCSA": [
        ("Podman", 97, "RHCSA covers container management using Podman"),
        ("SELinux", 96, "RHCSA objectives include SELinux configuration and troubleshooting"),
        ("Systemd", 95, "RHCSA requires managing services using systemd"),
        ("LVM", 94, "RHCSA covers logical volume management"),
        ("Firewalld", 93, "RHCSA includes firewall configuration with firewalld"),
        ("NetworkManager", 91, "RHCSA requires network configuration using NetworkManager"),
        ("Bash Scripting", 90, "RHCSA includes basic shell scripting"),
        ("Storage Management", 89, "RHCSA covers disk partitioning and storage management"),
        ("User Administration", 88, "RHCSA requires local user and group administration"),
        ("Process Management", 87, "RHCSA covers process control and scheduling"),
        ("Package Management", 86, "RHCSA includes managing packages with yum/dnf"),
        ("SSH", 85, "RHCSA covers secure remote access via SSH"),
        ("Troubleshooting", 84, "RHCSA requires diagnosing and resolving system issues"),
        ("Red Hat Enterprise Linux", 98, "RHCSA is the foundational RHEL certification"),
    ],
    "RHCSA in RHEL 9": [
        ("Podman", 97, "RHCSA in RHEL 9 covers container management using Podman"),
        ("SELinux", 96, "RHCSA in RHEL 9 includes SELinux configuration"),
        ("Systemd", 95, "RHCSA in RHEL 9 requires managing services using systemd"),
        ("LVM", 94, "RHCSA in RHEL 9 covers logical volume management"),
        ("Firewalld", 93, "RHCSA in RHEL 9 includes firewall configuration with firewalld"),
        ("NetworkManager", 91, "RHCSA in RHEL 9 requires network configuration"),
        ("Bash Scripting", 90, "RHCSA in RHEL 9 includes shell scripting"),
        ("Storage Management", 89, "RHCSA in RHEL 9 covers disk and storage management"),
        ("User Administration", 88, "RHCSA in RHEL 9 requires user and group management"),
        ("Package Management", 86, "RHCSA in RHEL 9 includes managing packages with dnf"),
        ("SSH", 85, "RHCSA in RHEL 9 covers secure remote access"),
        ("Red Hat Enterprise Linux", 98, "RHCSA in RHEL 9 is the foundational RHEL 9 certification"),
        ("RHEL 9 Administration", 97, "Direct certification for RHEL 9 system administration"),
    ],
    "RHCE": [
        ("Ansible", 98, "RHCE is heavily focused on Ansible automation"),
        ("Automation", 97, "RHCE validates automation skills with Ansible"),
        ("Playbooks", 96, "RHCE requires writing and managing Ansible playbooks"),
        ("Ansible Roles", 95, "RHCE covers creating and using Ansible roles"),
        ("Inventory Management", 93, "RHCE includes Ansible inventory management"),
        ("YAML", 92, "RHCE requires proficiency in YAML for Ansible"),
        ("SSH Automation", 90, "RHCE covers SSH-based automation with Ansible"),
        ("Jinja2 Templates", 89, "RHCE includes Jinja2 templating for Ansible"),
        ("Advanced Linux Administration", 91, "RHCE builds on RHCSA with advanced admin skills"),
        ("Automation Troubleshooting", 88, "RHCE requires debugging automation workflows"),
    ],
    "CKA": [
        ("Kubernetes", 99, "CKA is the official Kubernetes administrator certification"),
        ("Pods", 97, "CKA covers creating and managing Kubernetes pods"),
        ("Deployments", 96, "CKA includes managing deployments and rolling updates"),
        ("ReplicaSets", 95, "CKA covers ReplicaSet management and scaling"),
        ("Services", 94, "CKA includes Kubernetes service types and networking"),
        ("ConfigMaps & Secrets", 93, "CKA covers configuration management with ConfigMaps and Secrets"),
        ("Persistent Volumes", 92, "CKA includes persistent storage provisioning"),
        ("Ingress", 91, "CKA covers ingress controllers and routing"),
        ("kubectl", 98, "CKA requires proficiency with kubectl CLI"),
        ("Scheduling", 90, "CKA includes pod scheduling, taints, and tolerations"),
        ("Cluster Networking", 89, "CKA covers CNI plugins and network policies"),
        ("Cluster Administration", 97, "CKA validates Kubernetes cluster administration"),
        ("etcd", 88, "CKA includes etcd backup and restore"),
        ("RBAC", 87, "CKA covers Kubernetes RBAC policies"),
    ],
    "CKAD": [
        ("Kubernetes", 98, "CKAD validates Kubernetes application development"),
        ("Pods", 97, "CKAD covers pod design and multi-container pods"),
        ("Deployments", 96, "CKAD includes deployment strategies"),
        ("Services", 94, "CKAD covers service discovery and networking"),
        ("ConfigMaps & Secrets", 93, "CKAD includes application configuration management"),
        ("Persistent Volumes", 91, "CKAD covers persistent storage for applications"),
        ("Helm", 90, "CKAD includes Helm chart usage for packaging"),
        ("Probes & Health Checks", 89, "CKAD covers liveness and readiness probes"),
        ("Resource Limits", 88, "CKAD includes resource quotas and limit ranges"),
        ("kubectl", 97, "CKAD requires kubectl proficiency"),
        ("Container Design Patterns", 87, "CKAD covers sidecar, adapter, and ambassador patterns"),
    ],
    "CKS": [
        ("Kubernetes Security", 98, "CKS is the Kubernetes security specialist certification"),
        ("Network Policies", 97, "CKS covers Kubernetes network policies and isolation"),
        ("Pod Security Standards", 96, "CKS includes pod security policies and standards"),
        ("Runtime Security", 95, "CKS covers container runtime security and Falco"),
        ("Image Scanning", 94, "CKS includes container image vulnerability scanning"),
        ("Supply Chain Security", 93, "CKS covers image signing and admission controllers"),
        ("Audit Logging", 92, "CKS includes Kubernetes audit log configuration"),
        ("Secrets Management", 91, "CKS covers secure secrets handling and encryption"),
        ("mTLS & Service Mesh", 90, "CKS includes mutual TLS and service mesh security"),
        ("Compliance & Benchmarks", 89, "CKS covers CIS benchmarks for Kubernetes"),
        ("Kubernetes", 97, "CKS builds on CKA with security focus"),
    ],
    "AWS SAA": [
        ("EC2", 97, "AWS SAA covers EC2 instance management and scaling"),
        ("IAM", 96, "AWS SAA includes identity and access management"),
        ("S3", 95, "AWS SAA covers S3 storage classes and lifecycle"),
        ("VPC", 94, "AWS SAA includes VPC design and networking"),
        ("Route53", 92, "AWS SAA covers DNS routing with Route53"),
        ("CloudWatch", 91, "AWS SAA includes monitoring with CloudWatch"),
        ("RDS", 90, "AWS SAA covers relational database services"),
        ("ELB", 89, "AWS SAA includes load balancing strategies"),
        ("Lambda", 88, "AWS SAA covers serverless with Lambda"),
        ("Cloud Architecture", 97, "AWS SAA validates cloud architecture design"),
        ("High Availability", 93, "AWS SAA covers multi-AZ and fault-tolerant design"),
        ("AWS Security", 91, "AWS SAA includes security best practices"),
    ],
    "Azure Administrator": [
        ("Azure VM", 97, "Azure Administrator covers virtual machine management"),
        ("Azure Storage", 96, "Azure Administrator includes storage accounts and Blob"),
        ("Azure Networking", 95, "Azure Administrator covers VNets, NSGs, and peering"),
        ("Azure AD", 94, "Azure Administrator includes Azure Active Directory"),
        ("ARM Templates", 93, "Azure Administrator covers Azure Resource Manager"),
        ("Resource Groups", 92, "Azure Administrator includes resource organization"),
        ("Azure Monitoring", 91, "Azure Administrator covers Azure Monitor and alerts"),
        ("Azure RBAC", 90, "Azure Administrator includes role-based access control"),
        ("Azure CLI", 89, "Azure Administrator requires Azure CLI proficiency"),
        ("Azure Backup", 88, "Azure Administrator covers backup and disaster recovery"),
    ],
    "Red Hat Certified Architect": [
        ("Enterprise Architecture", 98, "RHCA validates expert-level enterprise architecture"),
        ("OpenShift", 96, "RHCA typically requires OpenShift expertise"),
        ("Advanced Ansible", 95, "RHCA includes advanced automation architecture"),
        ("System Design", 94, "RHCA covers designing complex Red Hat solutions"),
        ("Performance Optimization", 93, "RHCA includes expert-level performance tuning"),
        ("High Availability Design", 92, "RHCA covers HA architecture patterns"),
        ("Security Architecture", 91, "RHCA includes designing secure infrastructure"),
        ("Cloud Architecture", 90, "RHCA covers hybrid cloud architecture design"),
        ("Integration Architecture", 89, "RHCA includes enterprise integration patterns"),
        ("Technical Leadership", 88, "RHCA validates technical leadership capabilities"),
    ],
    "Red Hat Certified Specialist in Ansible": [
        ("Ansible", 99, "Direct Ansible specialist certification"),
        ("Ansible Playbooks", 97, "Specialist certification covers advanced playbook development"),
        ("Ansible Roles", 96, "Specialist certification includes creating reusable roles"),
        ("Ansible Galaxy", 95, "Specialist certification covers Ansible Galaxy usage"),
        ("Ansible Vault", 94, "Specialist certification includes secrets management with Vault"),
        ("Ansible Tower/AAP", 93, "Specialist certification covers Ansible Automation Platform"),
        ("Jinja2 Templates", 92, "Specialist certification includes advanced Jinja2 templating"),
        ("Inventory Management", 91, "Specialist certification covers dynamic inventory"),
        ("YAML", 90, "Specialist certification requires advanced YAML proficiency"),
        ("CI/CD Automation", 89, "Specialist certification includes automation pipelines"),
    ],
    "Red Hat Certified Specialist in OpenShift": [
        ("OpenShift Administration", 99, "Direct OpenShift specialist certification"),
        ("Container Orchestration", 97, "Specialist certification covers container management"),
        ("OpenShift Networking", 96, "Specialist certification includes SDN and route config"),
        ("OpenShift Storage", 95, "Specialist certification covers persistent storage on OCP"),
        ("OpenShift Security", 94, "Specialist certification includes SCC and RBAC on OCP"),
        ("Operator Framework", 93, "Specialist certification covers Operators and OLM"),
        ("OpenShift CLI (oc)", 92, "Specialist certification requires oc CLI proficiency"),
        ("Image Streams & Builds", 91, "Specialist certification includes S2I and BuildConfigs"),
        ("OpenShift Monitoring", 90, "Specialist certification covers Prometheus and Grafana on OCP"),
        ("Helm on OpenShift", 89, "Specialist certification includes Helm chart deployments"),
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# CSS — mirrors app1.py patterns
# ═══════════════════════════════════════════════════════════════════════════════

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
    background: var(--secondary-background-color, {PF_SURFACE});
    border: 1px solid var(--border-color, {PF_BORDER});
    border-left: 3px solid {PF_RED};
    border-radius: {PF_RADIUS};
    padding: 14px 16px;
    box-shadow: {PF_SHADOW};
    animation: slideUp 0.5s ease both;
    transition: box-shadow 0.25s ease, border-color 0.25s ease;
}}
div[data-testid="stMetric"]:hover {{
    box-shadow: 0 20px 30px -8px rgba(99,102,241,0.12);
    border-color: {PF_RED};
    transform: translateY(-6px);
    animation: glowBorder 1.5s ease infinite;
}}
div[data-testid="stMetric"] label {{
    color: var(--text-color, {PF_TEXT_SEC}) !important;
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.04em !important;
}}
div[data-testid="stMetric"] [data-testid="stMetricValue"] {{
    color: var(--text-color, {PF_TEXT}) !important;
    font-size: 1.4rem !important;
    font-weight: 700 !important;
}}

/* ── Associate Cards ── */
.assoc-card {{
    background: var(--secondary-background-color, {PF_SURFACE});
    border: 1px solid var(--border-color, {PF_BORDER});
    border-radius: 16px;
    padding: 0;
    margin: 6px 0;
    height: 290px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02);
    transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
    animation: slideUp 0.5s ease both;
    position: relative;
    overflow: hidden;
}}
.assoc-card:hover {{
    border-color: rgba(99,102,241,0.30);
    box-shadow: 0 20px 40px -12px rgba(99,102,241,0.18), 0 4px 12px rgba(0,0,0,0.05);
    transform: translateY(-6px) scale(1.008);
    cursor: pointer;
}}
.assoc-card:hover .assoc-avatar {{
    transform: rotate(3deg);
    transition: transform 0.3s ease;
}}
.assoc-card-top {{
    display: flex; align-items: center; gap: 14px;
    padding: 18px 20px 12px;
}}
.assoc-card-top-left {{ flex: 1; min-width: 0; }}
.assoc-name {{
    color: var(--text-color, {PF_TEXT}); font-size: 1rem; font-weight: 700;
    line-height: 1.3; margin-bottom: 2px;
}}
.assoc-meta {{
    color: var(--text-color, {PF_TEXT_SEC}); font-size: 0.70rem;
    margin-bottom: 6px;
}}
.assoc-perf-line {{
    display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
}}
.assoc-avatar {{
    width: 46px; height: 46px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; font-weight: 700; color: {RH_WHITE}; flex-shrink: 0;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}}
.assoc-card-body {{ flex: 1; display: flex; flex-direction: column; }}
.assoc-metrics {{
    display: grid; grid-template-columns: repeat(4, 1fr);
    border-top: 1px solid rgba(226,232,240,0.6);
    border-bottom: 1px solid rgba(226,232,240,0.6);
}}
.assoc-metric {{
    text-align: center; padding: 12px 4px;
    border-right: 1px solid rgba(226,232,240,0.6);
}}
.assoc-metric:last-child {{ border-right: none; }}
.assoc-metric-val {{
    color: var(--text-color, {PF_TEXT}); font-size: 0.95rem; font-weight: 800;
    line-height: 1;
}}
.assoc-metric-val.warn {{ color: #EF4444; }}
.assoc-metric-lbl {{
    color: var(--text-color, {PF_TEXT_SEC}); font-size: 0.62rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.04em;
    margin-top: 4px; opacity: 0.7;
}}
.assoc-perf-bar {{
    padding: 10px 20px 6px;
    display: flex; align-items: center; gap: 8px;
}}
.assoc-perf-lbl {{
    font-size: 0.66rem; color: var(--text-color, {PF_TEXT_SEC}); font-weight: 600;
    white-space: nowrap; text-transform: uppercase; letter-spacing: 0.03em;
}}
.assoc-perf-track {{
    flex: 1; height: 5px; border-radius: 99px;
    background: rgba(226,232,240,0.6); overflow: hidden;
}}
.assoc-perf-fill {{
    height: 100%; border-radius: 99px;
    transition: width 0.8s cubic-bezier(0.4,0,0.2,1);
    position: relative; overflow: hidden;
    animation: barGrow 0.8s cubic-bezier(0.4,0,0.2,1) both;
    transform-origin: left center;
}}
.assoc-perf-fill::after {{
    content: '';
    position: absolute; top: 0; left: 0; right: 0; bottom: 0;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.35), transparent);
    background-size: 200% 100%;
    animation: progressGlow 1.8s ease 0.8s 1 both;
}}
.assoc-perf-score {{
    font-size: 0.72rem; font-weight: 800;
    min-width: 28px; text-align: right;
}}
.assoc-card-info {{
    padding: 8px 20px 4px;
    color: var(--text-color, {PF_TEXT_SEC}); font-size: 0.74rem;
}}
.assoc-card-footer {{
    display: flex; align-items: flex-end;
    padding: 4px 20px 16px; margin-top: auto;
}}
.assoc-card-footer-left {{ display: flex; gap: 5px; flex-wrap: wrap; }}

/* ── Breakdown Rows ── */
.brkdn-row {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 10px; border-radius: 8px; cursor: pointer;
    transition: background 0.2s ease;
}}
.brkdn-row:hover {{ background: rgba(99,102,241,0.06); }}

/* ── Badges ── */
.badge {{
    display: inline-block;
    padding: 3px 8px;
    border-radius: 9999px;
    font-size: 0.68rem;
    font-weight: 700;
}}
.badge-green  {{ background: {RH_GREEN};  color: {RH_WHITE}; }}
.badge-yellow {{ background: {RH_GOLD};   color: {RH_DARK_1}; }}
.badge-orange {{ background: {RH_ORANGE}; color: {RH_DARK_1}; }}
.badge-red    {{ background: {PF_RED};     color: {RH_WHITE}; }}
.badge-blue   {{ background: {RH_BLUE};   color: {RH_WHITE}; }}
.badge-purple {{ background: {RH_PURPLE}; color: {RH_WHITE}; }}
.badge-teal   {{ background: {RH_TEAL};   color: {RH_WHITE}; }}

/* ── Level / Status Badges ── */
.lvl {{
    display: inline-block; padding: 3px 8px; border-radius: 9999px;
    font-size: 0.68rem; font-weight: 600;
}}
.lvl-principal {{ background: rgba(139,92,246,0.12); color: {RH_PURPLE}; }}
.lvl-staff     {{ background: rgba(99,102,241,0.10);   color: {RH_RED}; }}
.lvl-senior    {{ background: rgba(59,130,246,0.12);  color: {RH_BLUE}; }}
.lvl-mid       {{ background: rgba(6,182,212,0.12);  color: {RH_TEAL}; }}
.lvl-assoc     {{ background: rgba(148,163,184,0.12); color: {RH_GRAY}; }}

/* ── Skill Pills ── */
.skill-pills {{ display: flex; gap: 5px; flex-wrap: wrap; margin-top: auto; padding-top: 10px; }}
.skill-pill {{
    display: inline-block; padding: 3px 8px; border-radius: 9999px;
    font-size: 11px; font-weight: 600; color: {RH_WHITE};
    animation: fadeIn 0.4s ease both;
}}
.skill-pill:nth-child(1) {{ animation-delay: 0.3s; }}
.skill-pill:nth-child(2) {{ animation-delay: 0.38s; }}
.skill-pill:nth-child(3) {{ animation-delay: 0.46s; }}
.skill-pill:nth-child(4) {{ animation-delay: 0.54s; }}

/* ── Detail Header ── */
.det-hdr {{
    background: var(--secondary-background-color, {PF_SURFACE});
    border: 1px solid var(--border-color, {PF_BORDER});
    border-top: 3px solid {PF_RED};
    border-radius: {PF_RADIUS};
    padding: 20px 24px;
    margin-bottom: 16px;
    animation: slideUp 0.4s ease both;
    box-shadow: {PF_SHADOW};
}}
.det-hdr h2 {{ color: var(--text-color, {PF_TEXT}); margin: 0 0 4px 0; font-weight: 700; }}
.det-hdr p  {{ color: var(--text-color, {PF_TEXT_SEC}); margin: 0; opacity: 0.6; }}

/* ── RBAC Lock ── */
.rbac-lock {{
    background: var(--secondary-background-color, {PF_SURFACE});
    border: 1px solid var(--border-color, {PF_BORDER});
    border-radius: {PF_RADIUS};
    padding: 48px 40px;
    text-align: center;
    max-width: 420px;
    margin: 80px auto;
    animation: slideUp 0.4s ease both;
    box-shadow: {PF_SHADOW};
}}
.rbac-lock h3 {{ color: var(--text-color, {PF_TEXT}); margin-bottom: 8px; font-weight: 700; }}
.rbac-lock p  {{ color: var(--text-color, {PF_TEXT_SEC}); font-size: 0.85rem; margin-bottom: 20px; }}

/* ── Pagination ── */
.pg-bar {{
    display: flex; align-items: center; justify-content: center;
    gap: 6px; padding: 12px 0;
}}
.pg-num {{
    display: inline-block; padding: 5px 10px; border-radius: 9999px;
    font-size: 0.82rem; color: var(--text-color, {PF_TEXT}); cursor: pointer;
    border: 1px solid var(--border-color, {PF_BORDER});
    background: var(--secondary-background-color, {PF_SURFACE});
    transition: all 0.2s ease;
}}
.pg-num:hover {{
    border-color: {PF_BORDER_H};
    background: rgba(139,92,246,0.06);
}}
.pg-num.active {{
    background: {PF_RED}; color: {RH_WHITE};
    border-color: {PF_RED}; font-weight: 700;
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
@keyframes bellShake {{
    0%,100% {{ transform: rotate(0); }}
    15% {{ transform: rotate(14deg); }}
    30% {{ transform: rotate(-12deg); }}
    45% {{ transform: rotate(8deg); }}
    60% {{ transform: rotate(-6deg); }}
    75% {{ transform: rotate(2deg); }}
}}
@keyframes badgePop {{
    0%   {{ transform: scale(0); }}
    60%  {{ transform: scale(1.2); }}
    100% {{ transform: scale(1); }}
}}
@keyframes skeletonPulse {{
    0%   {{ background-position: -200% 0; }}
    100% {{ background-position: 200% 0; }}
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
    animation: waterFlow 0.6s cubic-bezier(0.4,0,0.2,1) both;
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
[data-testid="stMetric"]:nth-child(1) {{ animation-delay: 0.05s; }}
[data-testid="stMetric"]:nth-child(2) {{ animation-delay: 0.10s; }}
[data-testid="stMetric"]:nth-child(3) {{ animation-delay: 0.15s; }}
[data-testid="stMetric"]:nth-child(4) {{ animation-delay: 0.20s; }}
[data-testid="stMetric"]:nth-child(5) {{ animation-delay: 0.25s; }}
[data-testid="stMetric"]:nth-child(6) {{ animation-delay: 0.30s; }}
[data-testid="stMetric"] [data-testid="stMetricDelta"] {{
    animation: slideRight 0.4s ease 0.8s both;
}}

/* ── Table rows stagger ── */
.stTabs [data-baseweb="tab-panel"] {{ animation: slideUp 0.4s ease-out both; }}
[data-testid="stDataFrame"] {{
    animation: waterFlow 0.6s cubic-bezier(0.4,0,0.2,1) 0.2s both;
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

/* ── Popup / Modal ── */
[data-testid="stModal"] > div:first-child {{
    animation: fadeIn 0.25s ease both;
}}
div[role="dialog"] {{
    animation: popupIn 0.35s cubic-bezier(0.34,1.56,0.64,1) both !important;
}}

/* ── Favorite Star ── */
.fav-star {{
    cursor: pointer;
    font-size: 1.2rem;
    transition: transform 0.2s ease;
    display: inline-block;
}}
.fav-star:hover {{ transform: scale(1.25); }}
.fav-star.active {{ animation: sparkle 0.5s ease both; }}

/* ── Risk Distribution Bar ── */
.risk-bar-track {{
    display: flex; height: 12px; border-radius: 99px;
    overflow: hidden; background: #E2E8F0;
}}
.risk-bar-seg {{
    height: 100%;
    transition: width 0.8s cubic-bezier(0.4,0,0.2,1);
}}
.risk-legend {{
    display: flex; gap: 20px; margin-top: 8px;
    font-size: 0.78rem; align-items: center;
}}
.risk-dot {{
    width: 10px; height: 10px; border-radius: 50%;
    display: inline-block; margin-right: 5px;
}}

/* ── Export Button ── */
.export-wrap {{
    display: flex; gap: 8px; align-items: center;
}}

/* ── AI Skeleton ── */
.ai-skeleton {{
    background: linear-gradient(90deg, #F0F4F8 25%, #E2E8F0 50%, #F0F4F8 75%);
    background-size: 200% 100%;
    animation: skeletonPulse 1.5s ease-in-out infinite;
    border-radius: 8px;
    height: 16px;
    margin: 8px 0;
}}
.ai-skeleton.short {{ width: 60%; }}
.ai-skeleton.medium {{ width: 80%; }}
.ai-skeleton.long {{ width: 95%; }}

/* ── Saved Filter Pills ── */
.saved-filter-pill {{
    display: inline-flex; align-items: center; gap: 4px;
    padding: 4px 12px; border-radius: 9999px;
    font-size: 0.72rem; font-weight: 600;
    background: rgba(99,102,241,0.08);
    border: 1px solid rgba(99,102,241,0.15);
    color: {PF_TEXT}; cursor: pointer;
    transition: all 0.2s ease;
    animation: fadeIn 0.3s ease both;
}}
.saved-filter-pill:hover {{
    background: rgba(99,102,241,0.15);
    border-color: rgba(99,102,241,0.3);
    transform: translateY(-1px);
}}

/* ── Tabs — underline style ── */
.stTabs [data-baseweb="tab-list"] {{
    gap: 0;
    border-bottom: 2px solid var(--border-color, {PF_BORDER});
}}
.stTabs [data-baseweb="tab"] {{
    padding: 10px 20px;
    font-weight: 500;
    transition: color 0.2s ease;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
}}
.stTabs [data-baseweb="tab"]:hover {{
    color: {PF_RED};
}}
.stTabs [data-baseweb="tab"][aria-selected="true"] {{
    border-bottom-color: {PF_RED} !important;
    color: {PF_RED} !important;
    font-weight: 600;
}}

/* Buttons */
.stButton > button {{
    border-radius: {PF_RADIUS};
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

/* ── Section Dividers ── */
hr {{
    border: none;
    height: 1px;
    background: var(--border-color, {PF_BORDER});
    margin: 20px 0;
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
}}
div[role="dialog"]:has(.ai-chat-hdr) {{
    position: fixed !important;
    bottom: 84px !important; right: 32px !important;
    top: auto !important; left: auto !important;
    width: 400px !important; max-width: 90vw !important;
    max-height: 540px !important;
    margin: 0 !important; transform: none !important;
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
    display: flex; align-items: center; gap: 12px;
    border-bottom: none;
    margin: -1rem -1.5rem 0.5rem -1.5rem;
}}
.ai-chat-avatar {{
    width: 36px; height: 36px; border-radius: 12px;
    background: rgba(255,255,255,0.2);
    backdrop-filter: blur(8px);
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
}}
.ai-chat-hdr-text {{ flex: 1; min-width: 0; }}
.ai-chat-title {{ color: #FFFFFF; font-weight: 700; font-size: 0.92rem; }}
.ai-chat-subtitle {{ color: rgba(255,255,255,0.75); font-size: 0.68rem; }}
.ai-chat-status {{
    display: flex; align-items: center; gap: 6px;
    font-size: 0.72rem; color: rgba(255,255,255,0.85); flex-shrink: 0;
}}
.ai-status-dot {{
    width: 8px; height: 8px; border-radius: 50%;
    background: #4ADE80; display: inline-block;
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
    border-radius: 14px; padding: 20px; text-align: center;
}}
.ai-welcome h4 {{ color: {PF_TEXT} !important; margin: 0 0 6px 0; font-size: 0.92rem; }}
.ai-welcome p {{ color: {PF_TEXT_SEC} !important; font-size: 0.78rem; margin: 0 0 14px 0; line-height: 1.5; }}
.ai-suggestion {{
    background: rgba(99,102,241,0.06); border: 1px solid rgba(99,102,241,0.12);
    border-radius: 10px; padding: 10px 14px; cursor: pointer;
    color: {PF_TEXT} !important; font-size: 0.74rem; text-align: left;
    transition: all 0.2s ease; margin-bottom: 6px;
}}
.ai-suggestion:hover {{
    background: rgba(99,102,241,0.14);
    border-color: rgba(99,102,241,0.25);
    transform: translateX(4px);
}}

[data-testid="stChatMessage"] {{
    animation: fadeIn 0.3s ease both;
    border-radius: 12px !important;
    padding: 10px 14px !important;
    margin: 4px 0 !important;
}}

/* ── AI Insight Cards ── */
.ai-card {{
    background: var(--secondary-background-color, {PF_SURFACE});
    border: 1px solid var(--border-color, {PF_BORDER});
    border-left: 3px solid {PF_RED};
    border-radius: {PF_RADIUS};
    margin: 12px 0;
    overflow: hidden;
    animation: slideUp 0.4s ease both;
    transition: box-shadow 0.25s ease, border-color 0.25s ease;
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

/* ── Profile Info Cards ── */
.profile-strip {{
    display: flex; gap: 12px; flex-wrap: wrap; margin: 10px 0 16px 0;
}}
.profile-item {{
    flex: 1; min-width: 180px;
    background: var(--secondary-background-color, {PF_SURFACE});
    border: 1px solid var(--border-color, {PF_BORDER});
    border-radius: {PF_RADIUS};
    padding: 12px 16px;
    display: flex; align-items: center; gap: 12px;
    transition: border-color 0.25s ease, box-shadow 0.25s ease;
    box-shadow: {PF_SHADOW};
}}
.profile-item:hover {{
    border-color: {PF_BORDER_H};
    box-shadow: {PF_SHADOW_H};
}}
.profile-icon {{
    width: 36px; height: 36px; border-radius: {PF_RADIUS};
    background: rgba(99,102,241,0.08);
    display: flex; align-items: center; justify-content: center;
    font-size: 16px; flex-shrink: 0;
}}
.profile-label {{
    font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--text-color, {PF_TEXT_SEC}); opacity: 0.55; font-weight: 600;
}}
.profile-value {{
    font-size: 0.85rem; font-weight: 600;
    color: var(--text-color, {PF_TEXT}); word-break: break-word;
}}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {{
    border-right: 1px solid var(--border-color, {PF_BORDER});
}}
section[data-testid="stSidebar"] .stSelectbox > div > div {{
    border-radius: {PF_RADIUS};
}}
section[data-testid="stSidebar"] .stMultiSelect > div > div {{
    border-radius: {PF_RADIUS};
}}

/* ── Responsive ── */
@media (max-width: 480px) {{
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
    div[role="dialog"]:has(.ai-chat-hdr) {{
        bottom: 0 !important; right: 0 !important;
        width: 100% !important; max-width: 100% !important;
        max-height: 90vh !important;
        border-radius: {PF_RADIUS} {PF_RADIUS} 0 0 !important;
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

/* ── Popover (drill-down tables) ── */
div[data-testid="stPopover"] > div {{
    min-width: 520px !important;
    max-width: 90vw !important;
    max-height: 70vh !important;
    border-radius: 14px !important;
    border: 1px solid #E2E8F0 !important;
    box-shadow: 0 20px 40px -8px rgba(15,23,42,0.15), 0 4px 12px rgba(0,0,0,0.06) !important;
}}
div[data-testid="stPopover"] button {{
    border-radius: 9999px !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    padding: 6px 14px !important;
    border: 1px solid #E2E8F0 !important;
    transition: all 0.2s ease !important;
}}
div[data-testid="stPopover"] button:hover {{
    border-color: #6366F1 !important;
    color: #4338CA !important;
    background: #EEF2FF !important;
}}

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

</style>
</style>
"""

st.markdown(_get_main_css(), unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600)
def load_all_data():
    engine = get_engine()
    associates = pd.read_sql("SELECT * FROM associates", engine)
    cases = pd.read_sql("SELECT * FROM support_cases", engine)
    skills = pd.read_sql("SELECT * FROM skills", engine)
    # Full account row — My Desk joins tier/TAM/contract onto each open case.
    accounts = pd.read_sql(
        "SELECT account_id, account_name, sector, support_tier, tam_assigned, region, "
        "revenue_segment, contract_end_date, hq_location, annual_revenue FROM accounts",
        engine,
    )
    accounts["contract_end_date"] = pd.to_datetime(
        accounts["contract_end_date"], errors="coerce")

    if "hire_date" in associates.columns:
        associates["hire_date"] = pd.to_datetime(associates["hire_date"], errors="coerce")
    for col in ["creation_date", "last_updated", "resolution_date"]:
        if col in cases.columns:
            cases[col] = pd.to_datetime(cases[col], errors="coerce")
    cases["csat_score"] = pd.to_numeric(cases["csat_score"], errors="coerce")
    cases["time_to_resolve_hours"] = pd.to_numeric(cases["time_to_resolve_hours"], errors="coerce")
    cases["escalated"] = pd.to_numeric(cases["escalated"], errors="coerce").fillna(0).astype(int)

    return associates, cases, skills, accounts


associates_df, cases_df, skills_df, accounts_df = load_all_data()

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION PERSISTENCE (file-backed, survives browser refresh)
# ═══════════════════════════════════════════════════════════════════════════════

_SESSIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".sessions")
os.makedirs(_SESSIONS_DIR, exist_ok=True)

_PERSIST_KEYS = [
    "f_shifts", "f_managers", "f_sbrs", "f_accounts", "f_products",
    "f_severity", "f_skills", "f_certs", "f_sort",
    "page", "det_p", "det_chart_dim", "_det_date_saved",
    "det_tab", "dash_tab", "bookmarks", "saved_filters",
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
        if k == "_det_date_saved" and isinstance(v, list):
            v = [date.fromisoformat(d) for d in v if d]
        st.session_state[k] = v


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ═══════════════════════════════════════════════════════════════════════════════

for k, v in [("selected_associate", None), ("page", 0), ("_mt_page", 0),
             ("is_manager", False), ("global_chat", []),
             ("ai_insight", None), ("team_ai", None),
             ("skill_ai", None), ("ai_regen_count", 0),
             ("authenticated", False), ("username", None),
             ("role", None), ("display_name", None),
             ("jwt_token", None), ("_workspace", None),
             ("bookmarks", []), ("saved_filters", {}),
             ("compare_ids", []), ("pinned_kpis", []),
             ("_bulk_ids", []), ("_anomaly_dismissed", []),
             ("bulk_toggle", False), ("compare_toggle", False),
             ("_mt_ai_reply", None), ("_tour_step", 0), ("_tour_seen", False)]:
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
        if _qp_role in ("admin", "manager"):
            st.session_state.is_manager = True
        _qp_view = st.query_params.get("view")
        if _qp_view:
            try:
                st.session_state.selected_associate = int(_qp_view)
            except (ValueError, TypeError):
                pass
        _load_session()
        st.rerun()

# ── Early workspace gate (skip heavy data loading if workspace not chosen) ──
if st.session_state.get("authenticated") and st.session_state.get("_workspace") != "selected":
    render_workspace_selector("associate")
    st.stop()

# ═══════════════════════════════════════════════════════════════════════════════
# AUTH HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _create_jwt(username, role, remember=False):
    from datetime import timezone, timedelta
    now = datetime.now(timezone.utc)
    exp = timedelta(days=7) if remember else timedelta(minutes=60)
    # typ marks this as a dashboard session token. The REST API refuses it,
    # so a token picked out of a URL cannot be replayed against the API.
    payload = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + exp,
        "typ": "session",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _lookup_in_data(email, role):
    """Check if email exists in admin's data for the given role. Returns display_name or None."""
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
    """Register a new manager/associate. Returns dict with success and message."""
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
    existing = conn.execute(
        f"SELECT role FROM registered_users WHERE email = {PARAM}", (email,)).fetchone()
    if existing:
        conn.close()
        if existing[0] != role:
            return {"success": False,
                    "message": f"This email is registered as {existing[0]}. Use the {existing[0]} tab to sign in."}
        return {"success": False, "message": "Already registered. Please login."}

    conn.execute(
        f"INSERT INTO registered_users (email, password_hash, role, display_name) VALUES ({PARAM}, {PARAM}, {PARAM}, {PARAM})",
        (email, _get_pwd_ctx().hash(password), role, display_name))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Account created successfully. Please sign in."}


def reset_password(email, current_password, new_password, role):
    """Reset password for a registered user. Requires current password verification."""
    email = email.strip().lower()

    if not _lookup_in_data(email, role):
        return {"success": False, "message": "Email not found in system."}

    conn = get_connection()
    existing = conn.execute(
        f"SELECT role, password_hash FROM registered_users WHERE email = {PARAM}", (email,)).fetchone()
    if not existing:
        conn.close()
        return {"success": False, "message": "No account found. Please sign up first."}
    if existing[0] != role:
        conn.close()
        return {"success": False,
                "message": f"This email is registered as {existing[0]}. Use the {existing[0]} tab."}
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
    """Validate credentials with strict role enforcement."""
    email = email.strip().lower()

    if selected_role == "admin":
        if email == ADMIN_EMAIL and _get_pwd_ctx().verify(password, _get_admin_hash()):
            return {"token": _create_jwt(email, "admin", remember), "role": "admin",
                    "display_name": "System Administrator"}
        return None

    if not _lookup_in_data(email, selected_role):
        return None

    conn = get_connection()
    row = conn.execute(
        f"SELECT password_hash, display_name, role FROM registered_users WHERE email = {PARAM}",
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


def validate_token(token):
    """Decode and validate a JWT token. Returns payload or None."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


def check_session():
    """Validate the current session token. Clears auth state if expired."""
    token = st.session_state.get("jwt_token")
    if not token:
        return False
    payload = validate_token(token)
    if payload is None:
        for k in ["authenticated", "username", "role", "display_name",
                   "is_manager", "jwt_token"]:
            if k in st.session_state:
                st.session_state[k] = None if k != "authenticated" else False
        if "token" in st.query_params:
            del st.query_params["token"]
        return False
    return True


def _validate_password_form(email, password, confirm):
    if not email or not password or not confirm:
        return "Please fill in all fields."
    if password != confirm:
        return "Passwords do not match."
    if len(password) < 6:
        return "Password must be at least 6 characters."
    return None


def has_permission(perm):
    role = st.session_state.get("role")
    if not role:
        return False
    return ROLE_PERMISSIONS.get(role, {}).get(perm, False)


def _render_data_ingest(prefix="", assoc_stats_df=None):
    ig1, ig2, ig3, ig4 = st.tabs(["CSV Upload", "Manual Entry", "Delete Case", "Export Data"])
    _REQUIRED_CSV_COLS = {"case_number", "account_name", "severity", "status", "product_name", "case_owner"}
    with ig1:
        uploaded = st.file_uploader("Upload Cases CSV", type=["csv"], key=f"{prefix}csv_up")
        if uploaded is not None:
            try:
                new = pd.read_csv(uploaded)
                missing_cols = _REQUIRED_CSV_COLS - set(new.columns)
                if missing_cols:
                    st.error(f"CSV is missing required columns: **{', '.join(sorted(missing_cols))}**")
                    st.caption(f"Required: {', '.join(sorted(_REQUIRED_CSV_COLS))}")
                else:
                    empty_rows = new[list(_REQUIRED_CSV_COLS)].isna().any(axis=1)
                    n_empty = int(empty_rows.sum())
                    if n_empty:
                        st.warning(f"{n_empty} row(s) have empty required fields and will be skipped.")
                        new = new[~empty_rows]
                    if new.empty:
                        st.error("No valid rows to import after filtering incomplete records.")
                    else:
                        if "case_number" in new.columns:
                            engine = get_engine()
                            existing_cases = set(pd.read_sql("SELECT case_number FROM support_cases", engine)["case_number"].astype(str))
                            new["case_number"] = new["case_number"].astype(str)
                            dupes = new[new["case_number"].isin(existing_cases)]
                            new = new[~new["case_number"].isin(existing_cases)]
                            if len(dupes):
                                st.warning(f"{len(dupes)} duplicate case(s) skipped (already in database).")
                        if new.empty:
                            st.info("All rows already exist in the database. Nothing to import.")
                        else:
                            st.success(f"{len(new)} new row(s) ready to import.")
                            if st.button("Import CSV", key=f"{prefix}imp_csv", type="primary"):
                                engine = get_engine()
                                new.to_sql("support_cases", engine, if_exists="append", index=False)
                                load_all_data.clear()
                                st.toast(f"{len(new)} cases imported successfully")
                                st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")
    with ig2:
        with st.form(f"{prefix}new_case", clear_on_submit=True):
            mc_acct = st.selectbox("Account *", [""] + sorted(accounts_df["account_name"].dropna().unique().tolist()), key=f"{prefix}mc_a")
            mc_owner = st.selectbox("Case Owner *", [""] + sorted(associates_df["associate_name"].dropna().unique().tolist()), key=f"{prefix}mc_o")
            mc_sev = st.selectbox("Severity *", [""] + list(SEVERITY_COLORS.keys()), key=f"{prefix}mc_s")
            mc_prod = st.selectbox("Product *", [""] + sorted(cases_df["product_name"].dropna().unique().tolist()), key=f"{prefix}mc_p")
            mc_prob = st.text_area("Problem Statement *", key=f"{prefix}mc_ps")
            st.caption("* All fields are required")
            mc_sub = st.form_submit_button("Submit Case", type="primary")
        if mc_sub:
            _missing = []
            if not mc_acct:
                _missing.append("Account")
            if not mc_owner:
                _missing.append("Case Owner")
            if not mc_sev:
                _missing.append("Severity")
            if not mc_prod:
                _missing.append("Product")
            if not mc_prob or not mc_prob.strip():
                _missing.append("Problem Statement")
            if _missing:
                st.error(f"Please fill all required fields: **{', '.join(_missing)}**")
            else:
                try:
                    engine = get_engine()
                    mx = pd.read_sql("SELECT MAX(case_number) as m FROM support_cases", engine)["m"].iloc[0]
                    cn = int(mx) + 1 if pd.notna(mx) else 4000000
                    aid_row = accounts_df[accounts_df["account_name"] == mc_acct]
                    aid = aid_row.iloc[0]["account_id"] if len(aid_row) else ""
                    conn = get_connection()
                    conn.execute(
                        f"INSERT INTO support_cases (case_number,account_id,account_name,creation_date,"
                        f"severity,status,product_name,case_owner,problem_statement,escalated) "
                        f"VALUES ({PARAM},{PARAM},{PARAM},{PARAM},{PARAM},'Open',{PARAM},{PARAM},{PARAM},0)",
                        (cn, aid, mc_acct, datetime.now().isoformat(), mc_sev, mc_prod, mc_owner, mc_prob.strip()),
                    )
                    conn.commit()
                    conn.close()
                    load_all_data.clear()
                    st.toast(f"Case #{cn} created")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")
    with ig3:
        del_options = [f"{int(r['case_number'])} — {r['account_name']} ({r['severity']})"
                       for _, r in cases_df.iterrows()]
        del_sel = st.selectbox("Select Case", [""] + del_options, key=f"{prefix}del_case_sb")
        if del_sel:
            del_cn = int(del_sel.split(" — ")[0])
            del_row = cases_df[cases_df["case_number"] == del_cn]
            if not del_row.empty:
                dr = del_row.iloc[0]
                st.markdown(f"**Account:** {dr['account_name']}")
                st.markdown(f"**Severity:** {dr['severity']} | **Status:** {dr['status']}")
                st.markdown(f"**Product:** {dr['product_name']}")
                st.markdown(f"**Owner:** {dr['case_owner']}")
                if pd.notna(dr.get("problem_statement")):
                    st.markdown(f"**Problem:** {dr['problem_statement'][:120]}")
                _del_key = f"{prefix}confirm_del_{del_cn}"
                if st.session_state.get(_del_key):
                    st.error(f"Are you sure you want to permanently delete Case #{del_cn}?")
                    _dd1, _dd2 = st.columns(2)
                    with _dd1:
                        if st.button("Yes, Delete", key=f"{prefix}del_yes_{del_cn}", type="primary", use_container_width=True):
                            try:
                                conn = get_connection()
                                conn.execute(f"DELETE FROM support_cases WHERE case_number = {PARAM}", (del_cn,))
                                conn.commit()
                                conn.close()
                                load_all_data.clear()
                                st.session_state.pop(_del_key, None)
                                st.toast(f"Case #{del_cn} deleted")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Delete failed: {e}")
                    with _dd2:
                        if st.button("Cancel", key=f"{prefix}del_no_{del_cn}", use_container_width=True):
                            st.session_state.pop(_del_key, None)
                            st.rerun()
                else:
                    st.warning("This action cannot be undone.")
                    if st.button("Delete Case", key=f"{prefix}del_case_btn", type="primary"):
                        st.session_state[_del_key] = True
                        st.rerun()
    with ig4:
        _exp_src = assoc_stats_df if assoc_stats_df is not None else associates_df
        if assoc_stats_df is not None:
            _export_df = _exp_src[["associate_id", "associate_name", "sbr", "shift",
                                   "manager_name", "skill_level", "total_cases",
                                   "resolved", "escalations", "avg_csat", "perf"]].copy()
            _export_df.columns = ["Associate ID", "Name", "SBR Team", "Shift", "Manager",
                                  "Skill Level", "Total Cases", "Resolved", "Escalations",
                                  "Avg CSAT", "Performance Score"]
        else:
            _export_df = _exp_src.copy()
        st.markdown(f"**{len(_export_df):,}** records ready for export")
        _ex1, _ex2 = st.columns(2)
        with _ex1:
            _csv = _export_df.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", _csv, "associates_export.csv",
                               "text/csv", key=f"{prefix}export_csv", use_container_width=True)
        with _ex2:
            _xls_buf = io.BytesIO()
            with pd.ExcelWriter(_xls_buf, engine="openpyxl") as writer:
                _export_df.to_excel(writer, index=False, sheet_name="Associates")
            st.download_button("Download Excel", _xls_buf.getvalue(),
                               "associates_export.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key=f"{prefix}export_xlsx", use_container_width=True)
        with st.expander("Preview Export Data"):
            st.dataframe(_export_df.head(10), use_container_width=True, hide_index=True)




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
.stButton > button[kind="secondary"]{background:#FFFFFF!important;color:#334155!important;border:1px solid #CBD5E1!important;border-radius:9999px!important;font-size:13px!important;font-weight:500!important;transition:all .25s ease!important}
.stButton > button[kind="secondary"]:hover{background:#EEF2FF!important;border-color:#6366F1!important;color:#4338CA!important;transform:translateY(-1px)!important}
.stButton > button[kind="secondary"]:active,
.stButton > button[kind="secondary"]:focus{background:#EEF2FF!important;color:#4338CA!important;outline:none!important;border-color:#6366F1!important}

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


    # ── Step 2: Login Form ──
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
                        if result["role"] in ("admin", "manager"):
                            st.session_state.is_manager = True
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

    # ── Step 3: Sign Up Form (Manager / Associate only) ──
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
                pw_err = _validate_password_form(s_email, s_pass, s_confirm)
                if pw_err:
                    st.session_state._login_error = True
                    st.session_state._login_error_msg = pw_err
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

    # ── Step 4: Forgot Password ──
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
                pw_err = _validate_password_form(f_email, f_pass, f_confirm)
                if pw_err:
                    st.session_state._login_error = True
                    st.session_state._login_error_msg = pw_err
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

def perf_score(owned, resolved, csat, esc_rate):
    """0-100 composite: 40% resolution, 30% CSAT, 20% volume, 10% no-escalation."""
    res = min(resolved / max(owned, 1), 1.0) * 40
    cs = (csat / 5.0) * 30 if pd.notna(csat) and csat > 0 else 15
    vol = min(owned / 8, 1.0) * 20
    esc = (1 - min(esc_rate, 1.0)) * 10
    return round(min(res + cs + vol + esc, 100), 1)


def perf_badge(score):
    if score >= 75:
        return f'<span class="badge badge-green">{score}</span>'
    elif score >= 55:
        return f'<span class="badge badge-yellow">{score}</span>'
    elif score >= 35:
        return f'<span class="badge badge-orange">{score}</span>'
    return f'<span class="badge badge-red">{score}</span>'


def level_html(level):
    cls = {"Principal": "lvl-principal", "Staff": "lvl-staff", "Senior": "lvl-senior",
           "Mid-Level": "lvl-mid", "Associate": "lvl-assoc"}.get(level, "lvl-assoc")
    return f'<span class="lvl {cls}">{level}</span>'


def tenure_str(hire_date):
    if pd.isna(hire_date):
        return "N/A"
    yrs = round((date.today() - hire_date.date()).days / 365.25, 1)
    return f"{yrs} yrs"


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


def build_assoc_context(name, assoc_cases, assoc_skills):
    n = len(assoc_cases)
    if n == 0:
        return f"Associate: {name}\nNo cases assigned."
    esc = int(assoc_cases["escalated"].sum())
    resolved = len(assoc_cases[assoc_cases["status"].isin(["Resolved", "Closed"])])
    prods = assoc_cases["product_name"].value_counts().head(5)
    sevs = assoc_cases["severity"].value_counts()
    stats_s = assoc_cases["status"].value_counts()
    sk = ", ".join(assoc_skills["skill_name"].tolist()) if not assoc_skills.empty else "N/A"
    avg_csat = assoc_cases["csat_score"].mean()
    avg_ttr = assoc_cases["time_to_resolve_hours"].mean()
    pending_csat = int(assoc_cases["csat_score"].isna().sum())

    prod_detail = []
    for p, cnt in prods.items():
        p_cases = assoc_cases[assoc_cases["product_name"] == p]
        p_esc = int(p_cases["escalated"].sum())
        p_csat = p_cases["csat_score"].mean()
        prod_detail.append(f"  {p}: {cnt} cases, {p_esc} escalated, CSAT {f'{p_csat:.1f}' if pd.notna(p_csat) else 'pending'}")

    return (
        f"Associate: {name}\n"
        f"Total Cases: {n} | Resolved: {resolved} ({resolved/n*100:.0f}%) | Escalations: {esc} ({esc/n*100:.1f}%)\n"
        f"Avg CSAT: {f'{avg_csat:.1f}' if pd.notna(avg_csat) else 'N/A'}/5 ({pending_csat} pending) | "
        f"Avg TTR: {f'{avg_ttr:.0f}' if pd.notna(avg_ttr) else 'N/A'} hrs\n"
        f"Severity: {', '.join(f'{s}: {v}' for s,v in sevs.items())}\n"
        f"Status: {', '.join(f'{s}: {v}' for s,v in stats_s.items())}\n"
        f"Products:\n" + "\n".join(prod_detail) + "\n"
        f"Skills: {sk}"
    )


def local_summary(name, c, skills_list=""):
    n = len(c)
    if n == 0:
        return f"No cases recorded for **{name}**."
    esc = int(c["escalated"].sum())
    avg_csat = c["csat_score"].mean()
    avg_ttr = c["time_to_resolve_hours"].mean()
    resolved = len(c[c["status"].isin(["Resolved", "Closed"])])
    open_c = n - resolved
    res_rate = resolved / n * 100 if n else 0
    esc_rate = esc / n * 100 if n else 0
    top_prod = c["product_name"].value_counts().head(3)
    sevs = c["severity"].value_counts()
    sev_lines = " | ".join(f"{s}: {v}" for s, v in sevs.items())

    csat_note = "Excellent" if avg_csat >= 4.5 else ("Good" if avg_csat >= 3.5 else ("Needs Improvement" if avg_csat >= 2.5 else "Critical"))
    esc_note = "Low risk" if esc_rate < 10 else ("Moderate" if esc_rate < 25 else "High — review needed")

    lines = [
        f"### Performance Summary — {name}\n",
        f"**Workload:** {n} total cases | {resolved} resolved ({res_rate:.0f}%) | {open_c} open\n",
        f"**Quality Metrics:**",
        f"- CSAT Score: **{avg_csat:.1f}/5** ({csat_note})",
        f"- Avg Resolution Time: **{avg_ttr:.0f} hours**",
        f"- Escalations: **{esc}** ({esc_rate:.1f}% rate — {esc_note})\n",
        f"**Severity Breakdown:** {sev_lines}\n",
        f"**Top Products:** {', '.join(f'{p} ({v} cases)' for p, v in top_prod.items())}\n",
    ]
    if skills_list:
        lines.append(f"**Skills:** {skills_list}\n")

    lines.append(f"### Recommendations\n")
    recs = []
    if esc_rate > 20:
        recs.append(f"High escalation rate ({esc_rate:.0f}%) — review top escalated product "
                     f"(**{top_prod.index[0]}**) for knowledge gaps. Pair with senior engineer for mentoring.")
    if res_rate < 50:
        recs.append(f"Resolution rate at **{res_rate:.0f}%** — audit {open_c} open cases for blockers, "
                     f"consider redistributing to balance workload.")
    if pd.notna(avg_csat) and avg_csat < 3.5:
        recs.append(f"CSAT at **{avg_csat:.1f}/5** — schedule customer follow-ups on next 5 resolved cases "
                     f"to identify improvement areas.")
    if pd.notna(avg_ttr) and avg_ttr > 200:
        recs.append(f"Avg resolution time **{avg_ttr:.0f} hours** — prioritize high-severity cases and "
                     f"consider product-specific training for {top_prod.index[0]}.")
    if not recs:
        recs.append(f"Strong performer — CSAT {avg_csat:.1f}/5, resolution rate {res_rate:.0f}%, "
                     f"escalation rate {esc_rate:.1f}%. Consider for peer mentoring or lead role.")
    for r in recs:
        lines.append(f"- {r}")

    return "\n".join(lines)


_AI_PROMPT_STYLES = [
    (
        "Generate a structured performance analysis with these sections:\n"
        "1. **Performance Overview** — workload volume, resolution rate, CSAT score\n"
        "2. **Key Strengths** — what this associate does well\n"
        "3. **Areas of Concern** — escalation patterns, slow resolution, low CSAT\n"
        "4. **Recommendations** — specific actionable steps for improvement\n"
        "Use specific numbers from the data. Use markdown formatting with bold and bullet points."
    ),
    (
        "Write a performance report as if briefing a manager. Use a simple, easy-to-understand tone.\n"
        "Structure it as:\n"
        "1. **Summary** — one paragraph overview of this associate's overall standing\n"
        "2. **What's Working** — top 3 positives with specific numbers\n"
        "3. **What Needs Attention** — top 3 risks or concerns with evidence\n"
        "4. **Action Items** — 3-4 concrete next steps with expected impact\n"
        "Use bullet points and bold key metrics. Avoid jargon."
    ),
    (
        "Create a performance scorecard analysis in a different perspective.\n"
        "Structure it as:\n"
        "1. **At a Glance** — a quick verdict (strong/average/needs improvement) with key stats\n"
        "2. **Workload & Efficiency** — cases handled, resolution rate, time to resolve\n"
        "3. **Customer Impact** — CSAT trends, escalation patterns, quality indicators\n"
        "4. **Skills & Growth** — skill coverage, product expertise, development areas\n"
        "5. **Priority Actions** — ranked list of most impactful improvements\n"
        "Use specific numbers. Write clearly for someone seeing this associate's data for the first time."
    ),
]


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
            html_lines.append("<br>")
            continue
        if stripped.startswith("# "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f'<h3 style="margin:12px 0 6px;font-size:1rem;color:var(--text-color,{PF_TEXT});">{stripped[2:]}</h3>')
        elif stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f'<h4 style="margin:10px 0 4px;font-size:0.9rem;color:var(--text-color,{PF_TEXT});">{stripped[3:]}</h4>')
        elif stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f'<h5 style="margin:8px 0 4px;font-size:0.85rem;color:var(--text-color,{PF_TEXT});">{stripped[4:]}</h5>')
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


def ai_card_empty(title):
    return (
        f'<div class="ai-card">'
        f'<div class="ai-card-hdr">'
        f'<div class="ai-card-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.912 5.813a2 2 0 0 0 1.275 1.275L21 12l-5.813 1.912a2 2 0 0 0-1.275 1.275L12 21l-1.912-5.813a2 2 0 0 0-1.275-1.275L3 12l5.813-1.912a2 2 0 0 0 1.275-1.275L12 3Z"/></svg></div>'
        f'<span class="ai-card-title">{title}</span>'
        f'<span class="ai-card-badge">Powered by IBM Granite</span>'
        f'</div>'
        f'<div class="ai-card-empty">'
        f'<div class="ai-card-empty-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#8B5CF6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.912 5.813a2 2 0 0 0 1.275 1.275L21 12l-5.813 1.912a2 2 0 0 0-1.275 1.275L12 21l-1.912-5.813a2 2 0 0 0-1.275-1.275L3 12l5.813-1.912a2 2 0 0 0 1.275-1.275L12 3Z"/></svg></div>'
        f'<p>Click Generate to get AI-powered analysis</p>'
        f'</div>'
        f'</div>'
    )


CASE_COL_RENAME = {
    "case_number": "Case Number", "severity": "Severity", "status": "Status",
    "product_name": "Product", "problem_statement": "Problem Statement",
    "case_owner": "Case Owner", "account_name": "Account",
    "creation_date": "Created Date", "escalated": "Escalated",
    "csat_score": "CSAT Score", "description": "Description",
}


def _rename_case_cols(df):
    return df.rename(columns={k: v for k, v in CASE_COL_RENAME.items() if k in df.columns})


def _build_stats(assoc_df, case_df):
    """Aggregate case stats per associate."""
    agg = case_df.groupby("case_owner").agg(
        total_cases=("case_number", "count"),
        escalations=("escalated", "sum"),
        avg_csat=("csat_score", "mean"),
        avg_ttr=("time_to_resolve_hours", "mean"),
    ).reset_index()
    res = (
        case_df[case_df["status"].isin(["Resolved", "Closed"])]
        .groupby("case_owner").size().reset_index(name="resolved")
    )
    agg = agg.merge(res, on="case_owner", how="left")
    agg["resolved"] = agg["resolved"].fillna(0).astype(int)
    agg["esc_rate"] = agg["escalations"] / agg["total_cases"].clip(lower=1)

    merged = assoc_df.merge(agg, left_on="associate_name", right_on="case_owner", how="left")
    for col in ["total_cases", "resolved", "escalations"]:
        merged[col] = merged[col].fillna(0).astype(int)
    merged["esc_rate"] = merged["esc_rate"].fillna(0)
    tc = merged["total_cases"].clip(lower=1)
    res_score = (merged["resolved"] / tc).clip(upper=1.0) * 40
    csat_vals = merged["avg_csat"]
    cs_score = pd.Series(15.0, index=merged.index)
    valid_csat = csat_vals.notna() & (csat_vals > 0)
    cs_score[valid_csat] = (csat_vals[valid_csat] / 5.0) * 30
    vol_score = (merged["total_cases"] / 8).clip(upper=1.0) * 20
    esc_score = (1 - merged["esc_rate"].clip(upper=1.0)) * 10
    merged["perf"] = (res_score + cs_score + vol_score + esc_score).clip(upper=100).round(1)
    return merged


# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR FILTERS (only rendered when authenticated)
# ═══════════════════════════════════════════════════════════════════════════════

# Default filter values (used when not authenticated to avoid NameError)
search_q = ""
selected_shifts = []
selected_managers = []
selected_sbrs = []
selected_accounts = []
selected_products = []
selected_severity = []
selected_skills = []
selected_certs = []
sort_by = "Cases Resolved (High to Low)"

if st.session_state.get("authenticated", False):
    user_role = st.session_state.get("role", "associate")
    role_cfg = {
        "admin":     {"color": "#6366F1", "icon": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/></svg>', "label": "Admin",     "title": "System Administrator"},
        "manager":   {"color": "#F59E0B", "icon": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="14" x="2" y="7" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>', "label": "Manager",   "title": "Support Lead"},
        "associate": {"color": "#3B82F6", "icon": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>', "label": "Associate", "title": "Engineer"},
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
        for k in ["authenticated", "username", "role", "display_name", "is_manager",
                  "jwt_token", "selected_associate", "ai_insight", "team_ai",
                  "skill_ai", "global_chat", "login_time", "_workspace"]:
            if k in st.session_state:
                del st.session_state[k]
        for _qk in ["token", "view"]:
            if _qk in st.query_params:
                del st.query_params[_qk]
        st.rerun()

    st.sidebar.markdown(f'<div style="height:1px;background:linear-gradient(90deg,transparent,{PF_BORDER},transparent);margin:16px 0;"></div>', unsafe_allow_html=True)

    _sidebar_role = st.session_state.get("role", "associate")
    _in_detail = st.session_state.get("selected_associate") is not None

    _active_tab = st.session_state.get("dash_tab", "Associates")

    if _in_detail:
        _det_id = st.session_state.get("selected_associate")
        _det_match = associates_df[associates_df["associate_id"] == _det_id]
        if not _det_match.empty:
            _det_row = _det_match.iloc[0]
            st.sidebar.markdown(f'<p style="color:var(--text-color,{PF_TEXT});font-size:0.9rem;font-weight:700;margin-bottom:8px;">Associate Detail</p>', unsafe_allow_html=True)
            st.sidebar.markdown(_html(f"""
            <div style="background:var(--secondary-background-color,{PF_SURFACE});border:1px solid var(--border-color,{PF_BORDER});
                border-radius:12px;padding:12px;margin-bottom:12px;">
                <div style="font-weight:700;font-size:0.85rem;color:var(--text-color,{PF_TEXT});">{_det_row['associate_name']}</div>
                <div style="font-size:0.75rem;color:{PF_TEXT_SEC};margin-top:4px;">{_det_row.get('associate_id','')}</div>
                <div style="font-size:0.75rem;color:{PF_TEXT_SEC};">SBR: {_det_row.get('sbr','')}</div>
                <div style="font-size:0.75rem;color:{PF_TEXT_SEC};">Shift: {_det_row.get('shift','')}</div>
                <div style="font-size:0.75rem;color:{PF_TEXT_SEC};">Manager: {_det_row.get('manager_name','')}</div>
            </div>
            """), unsafe_allow_html=True)
        if st.sidebar.button("Back to Associates", key="sb_back_to_list",
                             use_container_width=True, icon=":material/arrow_back:"):
            st.session_state["selected_associate"] = None
            st.rerun()

    elif _active_tab in ("Associates", None):
        _saved_f = st.session_state.get("saved_filters", {})
        if _saved_f:
            st.sidebar.markdown(f"**Saved Presets** ({len(_saved_f)})")
            for fname, fvals in _saved_f.items():
                _sb_c1, _sb_c2 = st.sidebar.columns([3, 1])
                with _sb_c1:
                    if st.button(f"📋 {fname}", key=f"sb_sf_{fname}", use_container_width=True):
                        for fk, fv in fvals.items():
                            st.session_state[fk] = fv
                        st.toast(f"Filter '{fname}' applied!")
                        st.rerun()
                with _sb_c2:
                    if st.button("", key=f"sb_sf_del_{fname}", icon=":material/delete:"):
                        del st.session_state["saved_filters"][fname]
                        st.toast(f"Preset '{fname}' removed")
                        st.rerun()
        if st.sidebar.button("Save Current Filters", key="sb_save_filter_btn",
                             use_container_width=True, icon=":material/bookmark_add:"):
            st.session_state["_show_save_filter"] = True
        st.sidebar.divider()
        st.sidebar.markdown(f'<p style="color:var(--text-color,{PF_TEXT});font-size:0.9rem;font-weight:700;margin-bottom:8px;">Filters</p>', unsafe_allow_html=True)
        selected_shifts   = st.sidebar.multiselect("Geo / Shift", sorted(associates_df["shift"].dropna().unique()), key="f_shifts")
        selected_managers = st.sidebar.multiselect("Manager", sorted(associates_df["manager_name"].dropna().unique()), key="f_managers")
        selected_sbrs     = st.sidebar.multiselect("SBR Team", sorted(associates_df["sbr"].dropna().unique()), key="f_sbrs")
        selected_accounts = st.sidebar.multiselect("Account", sorted(cases_df["account_name"].dropna().unique()), key="f_accounts")
        selected_products = st.sidebar.multiselect("Product", sorted(cases_df["product_name"].dropna().unique()), key="f_products")
        selected_severity = st.sidebar.multiselect("Severity", sorted(cases_df["severity"].dropna().unique()), key="f_severity")
        selected_skills   = st.sidebar.multiselect("Skill", sorted(skills_df["skill_name"].dropna().unique()), key="f_skills")
        all_certs = set()
        for cs in associates_df["certifications"].dropna():
            for c in str(cs).split(","):
                c = c.strip()
                if c:
                    all_certs.add(c)
        selected_certs = st.sidebar.multiselect("Certification", sorted(all_certs), key="f_certs")
        sort_by = st.sidebar.selectbox("Sort Associates By", [
            "Cases Resolved (High to Low)",
            "Performance (High to Low)",
            "Escalations (High to Low)",
            "CSAT (Low to High)",
            "Associate Name",
        ], key="f_sort")

    elif _active_tab == "My Team":
        st.sidebar.markdown(f'<p style="color:var(--text-color,{PF_TEXT});font-size:0.9rem;font-weight:700;margin-bottom:8px;">My Team Filters</p>', unsafe_allow_html=True)
        _mt_sbr_list = sorted(associates_df[associates_df["manager_name"].str.lower() == st.session_state.get("display_name", "").lower()]["sbr"].dropna().unique().tolist())
        selected_shifts = st.sidebar.multiselect("Geo / Shift", sorted(associates_df["shift"].dropna().unique()), key="f_shifts")
        selected_sbrs = st.sidebar.multiselect("SBR Team", _mt_sbr_list, key="f_sbrs")
        selected_skills = st.sidebar.multiselect("Skill", sorted(skills_df["skill_name"].dropna().unique()), key="f_skills")

    elif _active_tab == "Team / SBR View":
        st.sidebar.markdown(f'<p style="color:var(--text-color,{PF_TEXT});font-size:0.9rem;font-weight:700;margin-bottom:8px;">Team / SBR Filters</p>', unsafe_allow_html=True)
        selected_sbrs = st.sidebar.multiselect("SBR Team", sorted(associates_df["sbr"].dropna().unique()), key="f_sbrs")
        selected_shifts = st.sidebar.multiselect("Geo / Shift", sorted(associates_df["shift"].dropna().unique()), key="f_shifts")
        selected_products = st.sidebar.multiselect("Product", sorted(cases_df["product_name"].dropna().unique()), key="f_products")

    elif _active_tab == "Skills View":
        st.sidebar.markdown(f'<p style="color:var(--text-color,{PF_TEXT});font-size:0.9rem;font-weight:700;margin-bottom:8px;">Skills Filters</p>', unsafe_allow_html=True)
        selected_skills = st.sidebar.multiselect("Skill", sorted(skills_df["skill_name"].dropna().unique()), key="f_skills")
        selected_sbrs = st.sidebar.multiselect("SBR Team", sorted(associates_df["sbr"].dropna().unique()), key="f_sbrs")
        selected_shifts = st.sidebar.multiselect("Geo / Shift", sorted(associates_df["shift"].dropna().unique()), key="f_shifts")

    if has_permission("data_ingest"):
        with st.sidebar.expander("Data Management", expanded=False, icon=":material/swap_vert:"):
            _render_data_ingest(prefix="sb_")


# ═══════════════════════════════════════════════════════════════════════════════
# APPLY FILTERS
# ═══════════════════════════════════════════════════════════════════════════════

f_assoc = associates_df.copy()

_user_role = st.session_state.get("role", "associate")
_user_email = st.session_state.get("username", "")

_my_team_assoc = pd.DataFrame()
if _user_role == "manager":
    _mgr_name = st.session_state.get("display_name", "")
    _my_team_assoc = associates_df[associates_df["manager_name"].str.lower() == _mgr_name.lower()].copy()

_search_q = st.session_state.get("main_search", "")
if _search_q:
    q = _search_q.lower()
    f_assoc = f_assoc[
        f_assoc["associate_name"].str.lower().str.contains(q, na=False) |
        f_assoc["email"].str.lower().str.contains(q, na=False)
    ]
if selected_shifts:
    f_assoc = f_assoc[f_assoc["shift"].isin(selected_shifts)]
if selected_managers:
    f_assoc = f_assoc[f_assoc["manager_name"].isin(selected_managers)]
if selected_sbrs:
    f_assoc = f_assoc[f_assoc["sbr"].isin(selected_sbrs)]
if selected_certs:
    f_assoc = f_assoc[f_assoc["certifications"].apply(
        lambda x: any(c in str(x) for c in selected_certs) if pd.notna(x) else False)]
if selected_skills:
    ids = skills_df[skills_df["skill_name"].isin(selected_skills)]["associate_id"].unique()
    f_assoc = f_assoc[f_assoc["associate_id"].isin(ids)]

f_cases = cases_df[cases_df["case_owner"].isin(f_assoc["associate_name"])].copy()
if selected_accounts:
    f_cases = f_cases[f_cases["account_name"].isin(selected_accounts)]
if selected_products:
    f_cases = f_cases[f_cases["product_name"].isin(selected_products)]
if selected_severity:
    f_cases = f_cases[f_cases["severity"].isin(selected_severity)]
if selected_accounts or selected_products or selected_severity:
    f_assoc = f_assoc[f_assoc["associate_name"].isin(f_cases["case_owner"].unique())]


# ═══════════════════════════════════════════════════════════════════════════════
# BUILD STATS
# ═══════════════════════════════════════════════════════════════════════════════

assoc_stats = _build_stats(f_assoc, f_cases)

sort_config = {
    "Performance (High to Low)":    ("perf", False),
    "Cases Resolved (High to Low)": ("resolved", False),
    "Escalations (High to Low)":    ("escalations", False),
    "CSAT (Low to High)":           ("avg_csat", True),
    "Associate Name":               ("associate_name", True),
}
s_col, s_asc = sort_config[sort_by]
assoc_stats = assoc_stats.sort_values(s_col, ascending=s_asc, na_position="last")


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED HEADER
# ═══════════════════════════════════════════════════════════════════════════════

def _render_site_header():
    import datetime as _dt
    _user = st.session_state.get("display_name", "User")
    _role = st.session_state.get("role", "associate")
    _rc = {"admin": ("#6366F1", "Admin"), "manager": ("#F59E0B", "Manager"),
           "associate": ("#3B82F6", "Associate")}.get(_role, ("#3B82F6", "Associate"))
    _initials = "".join(w[0] for w in _user.split()[:2]).upper() if _user else "U"
    _now = _dt.datetime.now().strftime("%b %d, %Y  %I:%M %p")
    _role_bg = f"rgba({','.join(str(int(_rc[0].lstrip('#')[i:i+2],16)) for i in (0,2,4))},0.12)"
    _avatar_end = '#A78BFA' if _rc[0]=='#6366F1' else '#FBBF24' if _rc[0]=='#F59E0B' else '#60A5FA'
    st.markdown(_html(f"""
    <div class="site-header">
        <div class="site-header-brand">
            <div class="site-header-logo">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
            </div>
            <div>
                <div class="site-header-title">Associates Dashboard</div>
                <div class="site-header-subtitle">Workforce performance &amp; operational intelligence</div>
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
    _spacer, _hdr_ws, _help_col, _logout_col = st.columns([6, 4, 1, 1])
    with _hdr_ws:
        render_workspace_switcher("associate")
    with _help_col:
        if st.button("?", key="hdr_tour", help="Start guided tour",
                     type="secondary", use_container_width=True):
            st.session_state["_tour_step"] = 1
            st.session_state["_tour_seen"] = False
            st.session_state["selected_associate"] = None
            st.session_state["dash_tab"] = "Associates"
            st.rerun()
    with _logout_col:
        if st.button("⏻", key="hdr_logout", help="Log out",
                     type="secondary", use_container_width=True):
            try:
                os.remove(_sess_path(st.session_state.get("username", "")))
            except Exception:
                pass
            for k in ["authenticated", "username", "role", "display_name", "is_manager",
                      "jwt_token", "selected_associate", "ai_insight", "team_ai",
                      "skill_ai", "global_chat", "login_time", "manager_sbr", "_workspace"]:
                if k in st.session_state:
                    del st.session_state[k]
            for _qk in ["token", "view"]:
                if _qk in st.query_params:
                    del st.query_params[_qk]
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# ASSOCIATE DETAIL VIEW
# ═══════════════════════════════════════════════════════════════════════════════


@st.dialog("Associate Quick View")
def associate_popup(assoc_id):
    assoc = associates_df[associates_df["associate_id"] == assoc_id]
    if assoc.empty:
        st.error("Associate not found.")
        return
    assoc = assoc.iloc[0]
    a_cases = cases_df[cases_df["case_owner"] == assoc["associate_name"]]
    a_skills = skills_df[skills_df["associate_id"] == assoc_id].sort_values("skill_rank")
    total = len(a_cases)
    resolved = len(a_cases[a_cases["status"] == "Closed"]) if total else 0
    avg_c = a_cases["csat_score"].mean() if total else None
    esc = int(a_cases["escalated"].sum()) if total else 0

    csat_s = f"{avg_c:.1f}" if pd.notna(avg_c) else "N/A"
    skills_html = ""
    if not a_skills.empty:
        pills = " ".join(
            f'<span style="background:#EDE9FE;color:#6D28D9;padding:3px 10px;border-radius:12px;font-size:0.72rem;font-weight:500;">{s["skill_name"]}</span>'
            for _, s in a_skills.head(5).iterrows()
        )
        skills_html = f'<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:8px;">{pills}</div>'

    st.markdown(_html(f"""<div style="text-align:center;padding:10px 0 6px;">
        <div style="width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#8B5CF6,#A78BFA);
            display:inline-flex;align-items:center;justify-content:center;margin-bottom:8px;">
            <span style="color:#fff;font-size:1.2rem;font-weight:700;">{assoc['associate_name'][0]}</span>
        </div>
        <div style="font-size:1.05rem;font-weight:700;color:#1E293B;">{assoc['associate_name']}</div>
        <div style="font-size:0.75rem;color:#94A3B8;margin-top:2px;">{assoc_id} \u00b7 {assoc['sbr']} \u00b7 {assoc['shift']}</div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:10px 0;">
        <div style="background:#F8FAFC;border-radius:8px;padding:8px 12px;text-align:center;">
            <div style="font-size:0.68rem;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px;">Cases</div>
            <div style="font-size:1.1rem;font-weight:700;color:#1E293B;">{total}</div>
        </div>
        <div style="background:#F8FAFC;border-radius:8px;padding:8px 12px;text-align:center;">
            <div style="font-size:0.68rem;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px;">Resolved</div>
            <div style="font-size:1.1rem;font-weight:700;color:#1E293B;">{resolved}</div>
        </div>
        <div style="background:#F8FAFC;border-radius:8px;padding:8px 12px;text-align:center;">
            <div style="font-size:0.68rem;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px;">CSAT</div>
            <div style="font-size:1.1rem;font-weight:700;color:#1E293B;">{csat_s}</div>
        </div>
        <div style="background:#F8FAFC;border-radius:8px;padding:8px 12px;text-align:center;">
            <div style="font-size:0.68rem;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px;">Escalations</div>
            <div style="font-size:1.1rem;font-weight:700;color:{'#EF4444' if esc > 0 else '#1E293B'};">{esc}</div>
        </div>
    </div>
    <div style="font-size:0.78rem;color:#64748B;text-align:center;margin:4px 0;">
        <b>Manager:</b> {assoc.get('manager_name', 'N/A')} &nbsp;\u00b7&nbsp; <b>Level:</b> {assoc.get('skill_level', 'N/A')}
    </div>{skills_html}"""), unsafe_allow_html=True)

    if st.button("AI Insight", key="popup_ai_assoc", type="primary", use_container_width=True):
        csat_str = f"{avg_c:.1f}" if pd.notna(avg_c) else "N/A"
        ctx = f"Associate: {assoc['associate_name']}, SBR: {assoc['sbr']}, Cases: {total}, Resolved: {resolved}, CSAT: {csat_str}, Escalations: {esc}"
        if not a_skills.empty:
            ctx += f", Skills: {', '.join(a_skills.head(5)['skill_name'].tolist())}"
        msgs = [
            {"role": "system", "content": "You are a Red Hat support operations analyst. Give a 2-3 sentence performance summary. Include resolution rate, CSAT, top skills, and one recommendation. Use exact numbers. Missing CSAT means pending."},
            {"role": "user", "content": ctx},
        ]
        with st.spinner("Generating..."):
            result = call_ai(msgs, max_tokens=200)
        st.markdown(result if result else f"**{assoc['associate_name']}** handled {total} cases, {resolved} resolved, CSAT {csat_str}.")


@st.dialog("Cases in Period", width="large")
def _timeline_period_popup(period_label, period_start, period_end, source_cases):
    drill = source_cases[
        (source_cases["creation_date"] >= period_start)
        & (source_cases["creation_date"] < period_end)
    ]
    st.markdown(
        _html(f'<div style="font-size:1.1rem;font-weight:700;color:{PF_TEXT};margin-bottom:4px;">'
        f'{period_label}</div>'
        f'<div style="font-size:0.85rem;color:{PF_TEXT_SEC};margin-bottom:12px;">'
        f'{len(drill)} cases</div>'),
        unsafe_allow_html=True)
    if drill.empty:
        st.info("No cases in this period.")
        return
    show = [c for c in DRILL_COLS if c in drill.columns]
    st.dataframe(_rename_case_cols(drill[show].sort_values("creation_date", ascending=False)),
                 use_container_width=True, hide_index=True)


@st.dialog("Category Breakdown", width="large")
def breakdown_popup(category, col_src, color):
    if col_src == "shift":
        _merged = f_cases.merge(
            associates_df[["associate_name", "shift"]], left_on="case_owner",
            right_on="associate_name", how="left"
        )
        drill = _merged[_merged["shift"] == category]
    else:
        drill = f_cases[f_cases[col_src] == category]

    drill_show = DRILL_COLS

    st.markdown(
        _html(f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">'
        f'<span style="width:14px;height:14px;border-radius:50%;background:{color};display:inline-block;"></span>'
        f'<span style="font-size:1.1rem;font-weight:700;color:var(--text-color,{PF_TEXT});">'
        f'{category}</span>'
        f'<span style="font-size:0.85rem;color:{PF_TEXT_SEC};">{len(drill)} cases</span></div>'),
        unsafe_allow_html=True)

    st.dataframe(
        _rename_case_cols(drill[drill_show].sort_values("creation_date", ascending=False)),
        use_container_width=True, height=300, hide_index=True)

    owners = drill["case_owner"].dropna().unique().tolist()
    top = assoc_stats[assoc_stats["associate_name"].isin(owners)].nlargest(3, "resolved")

    if not top.empty:
        st.markdown(f'<div style="font-size:0.88rem;font-weight:600;color:var(--text-color,{PF_TEXT});margin:12px 0 6px;">Top Associates</div>', unsafe_allow_html=True)
        tcols = st.columns(len(top))
        for tc, (_, ta) in zip(tcols, top.iterrows()):
            with tc:
                csat_s = f"{ta['avg_csat']:.1f}" if pd.notna(ta["avg_csat"]) else "N/A"
                st.markdown(
                    _html(f'<div style="background:var(--secondary-background-color,{PF_SURFACE});'
                    f'border:1px solid var(--border-color,{PF_BORDER});border-radius:12px;padding:14px;text-align:center;">'
                    f'<div style="font-weight:700;font-size:0.85rem;color:var(--text-color,{PF_TEXT});margin-bottom:6px;">{ta["associate_name"]}</div>'
                    f'<div style="font-size:0.75rem;color:{PF_TEXT_SEC};">Resolved: {int(ta["resolved"])}</div>'
                    f'<div style="font-size:0.75rem;color:{PF_TEXT_SEC};">CSAT: {csat_s}</div></div>'),
                    unsafe_allow_html=True)


def render_detail(assoc_id):
    st.session_state["_dialog_open"] = False
    _match = associates_df[associates_df["associate_id"] == assoc_id]
    if _match.empty:
        st.error("Associate not found.")
        st.session_state.selected_associate = None
        return
    row = _match.iloc[0]
    a_cases = f_cases[f_cases["case_owner"] == row["associate_name"]].copy()
    a_skills = skills_df[skills_df["associate_id"] == assoc_id].sort_values("skill_rank")

    n = len(a_cases)
    n_res = len(a_cases[a_cases["status"].isin(["Resolved", "Closed"])])
    avg_c = a_cases["csat_score"].mean()
    avg_t = a_cases["time_to_resolve_hours"].mean()
    n_esc = int(a_cases["escalated"].sum())
    esc_rate = n_esc / max(n, 1)
    ps = perf_score(n, n_res, avg_c, esc_rate)

    _is_own_dashboard = st.session_state.get("role") == "associate"

    if _is_own_dashboard:
        _render_site_header()
        _first = row["associate_name"].split()[0] if row["associate_name"] else "there"
        _perf_clr = "#10B981" if ps >= 75 else ("#F59E0B" if ps >= 55 else ("#FB923C" if ps >= 35 else "#EF4444"))
        _csat_s = f"{avg_c:.1f}/5" if pd.notna(avg_c) else "N/A"
        _ttr_s = f"{avg_t:.0f} hrs" if pd.notna(avg_t) else "N/A"
        st.markdown(_html(f"""
        <div style="background:linear-gradient(135deg,rgba(99,102,241,0.06) 0%,rgba(59,130,246,0.04) 100%);
            border:1px solid rgba(99,102,241,0.10);border-radius:{PF_RADIUS};
            padding:24px 28px 20px;margin-bottom:16px;animation:slideUp 0.4s ease both;">
            <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;">
                <div>
                    <div style="font-size:1.4rem;font-weight:800;color:{PF_TEXT};">
                        Welcome back, {_first}
                    </div>
                    <div style="font-size:0.82rem;color:{PF_TEXT_SEC};margin-top:4px;">
                        {assoc_id} &middot; {row['sbr']} &middot; {row['shift']} &middot; {level_html(row['skill_level'])}
                    </div>
                </div>
                <div style="display:flex;align-items:center;gap:10px;">
                    {perf_badge(ps)}
                </div>
            </div>
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:18px;">
                <div style="background:{PF_SURFACE};border-radius:12px;padding:12px 16px;
                    border:1px solid {PF_BORDER};text-align:center;">
                    <div style="font-size:1.3rem;font-weight:800;color:{PF_TEXT};">{n}</div>
                    <div style="font-size:0.68rem;color:{PF_TEXT_SEC};font-weight:600;text-transform:uppercase;">
                        Total Cases</div>
                </div>
                <div style="background:{PF_SURFACE};border-radius:12px;padding:12px 16px;
                    border:1px solid {PF_BORDER};text-align:center;">
                    <div style="font-size:1.3rem;font-weight:800;color:#10B981;">{n_res}</div>
                    <div style="font-size:0.68rem;color:{PF_TEXT_SEC};font-weight:600;text-transform:uppercase;">
                        Resolved</div>
                </div>
                <div style="background:{PF_SURFACE};border-radius:12px;padding:12px 16px;
                    border:1px solid {PF_BORDER};text-align:center;">
                    <div style="font-size:1.3rem;font-weight:800;color:#F59E0B;">{_csat_s}</div>
                    <div style="font-size:0.68rem;color:{PF_TEXT_SEC};font-weight:600;text-transform:uppercase;">
                        Avg CSAT</div>
                </div>
                <div style="background:{PF_SURFACE};border-radius:12px;padding:12px 16px;
                    border:1px solid {PF_BORDER};text-align:center;">
                    <div style="font-size:1.3rem;font-weight:800;color:{_perf_clr};">{ps:.0f}<span style="font-size:0.7rem;color:{PF_TEXT_SEC};">/100</span></div>
                    <div style="font-size:0.68rem;color:{PF_TEXT_SEC};font-weight:600;text-transform:uppercase;">
                        Performance</div>
                </div>
            </div>
        </div>
        """), unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <style>
        .sticky-back {{
            position: fixed; top: 0; left: 0; right: 0; z-index: 9999;
            background: {PF_RED}; padding: 10px 32px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.4);
            display: flex; align-items: center; gap: 16px;
        }}
        .sticky-back span {{ color: {RH_WHITE}; font-weight: 600; font-size: 0.95rem; }}
        .block-container {{ padding-top: 56px !important; }}
        </style>
        <div class="sticky-back">
            <span>{row['associate_name']}</span>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Back to Dashboard", key="back_top", type="primary", use_container_width=True):
            st.session_state.selected_associate = None
            st.session_state.ai_insight = None
            st.session_state.pop("_scorecard_ai", None)
            if "view" in st.query_params:
                del st.query_params["view"]
            st.rerun()
        st.markdown(_html(f"""<div class="det-hdr">
            <h2>{row['associate_name']} &nbsp;{perf_badge(ps)} &nbsp;{level_html(row['skill_level'])}</h2>
            <p>{assoc_id} &nbsp;&middot;&nbsp; {row['sbr']} &nbsp;&middot;&nbsp; {row['shift']} &nbsp;&middot;&nbsp; {tenure_str(row.get('hire_date'))}</p>
        </div>"""), unsafe_allow_html=True)

    # ── Tour continuation inside Detail View ──
    _tour_step_d = st.session_state.get("_tour_step", 0)
    _trole_d = st.session_state.get("role", "associate")
    _d_dash_steps = 8 if _trole_d in ("manager", "admin") else 8
    _d_start = _d_dash_steps + 1
    _s_total_d = _d_dash_steps + 4
    if _tour_step_d >= _d_start and not st.session_state.get("_tour_seen"):
        _detail_steps = [
            {"icon": "🎯", "label": "RADAR", "title": "Skill Competency",
             "desc": "Radar chart shows skill proficiency across multiple dimensions for <b>%s</b>." % row["associate_name"],
             "sel": "div[data-testid='stPlotlyChart']", "nav_tab": "Skills"},
            {"icon": "🤖", "label": "AI SKILLS", "title": "Skill Extraction",
             "desc": "Extract Skills via AI reads certifications and infers new skills with confidence scores. Add them in one click.",
             "sel": ".st-key-ai_extract_skills"},
            {"icon": "📊", "label": "INSIGHTS", "title": "AI Scorecard",
             "desc": "AI-generated performance scorecard with verdict badge, key scores, data breakdown, and analysis cards.",
             "sel": "div[data-testid='stMetric']", "nav_tab": "AI Insights"},
            {"icon": "🚀", "label": "ALL SET", "title": "You're Ready!",
             "desc": "Tour complete! You know how to filter, compare, analyze skills, and use AI insights. <b>Start exploring!</b>",
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
                _dtour_js = """<script>(function(){var P=window.parent,D=P.document,SEL='%s',PCLS='.st-key-dtour_popup';var old=D.getElementById('tour-spotlight-box');if(old)old.remove();var oldS=D.getElementById('tour-pos');if(oldS)oldS.remove();var sp=D.createElement('div');sp.id='tour-spotlight-box';sp.style.cssText='position:fixed;left:0;top:0;width:0;height:0;z-index:100000;pointer-events:none;border:2px solid #6366F1;border-radius:12px;box-shadow:0 0 0 9999px rgba(15,23,42,0.65),0 0 30px rgba(99,102,241,0.25);transition:all 300ms cubic-bezier(0.4,0,0.2,1);opacity:0;';D.body.appendChild(sp);function waitEl(sel,cb){var el=D.querySelector(sel);if(el){cb(el);return}var obs=new MutationObserver(function(){el=D.querySelector(sel);if(el){obs.disconnect();cb(el)}});obs.observe(D.body,{childList:true,subtree:true});setTimeout(function(){obs.disconnect();if(!D.querySelector(sel))cb(null)},5000)}waitEl(SEL,function(el){if(!el){sp.style.cssText='position:fixed;inset:0;z-index:100000;pointer-events:none;border:none;border-radius:0;box-shadow:0 0 0 9999px rgba(15,23,42,0.65);opacity:1;';var fs=D.createElement('style');fs.id='tour-pos';fs.textContent=PCLS+'{left:50%%!important;top:50%%!important;transform:translate(-50%%,-50%%)!important;opacity:1!important;animation:_tFadeIn .4s cubic-bezier(.34,1.56,.64,1) both!important;}';D.head.appendChild(fs);return}el.scrollIntoView({behavior:'smooth',block:'center'});setTimeout(function(){var r=el.getBoundingClientRect(),pad=8;sp.style.left=(r.left-pad)+'px';sp.style.top=(r.top-pad)+'px';sp.style.width=(r.width+pad*2)+'px';sp.style.height=(r.height+pad*2)+'px';sp.style.opacity='1';posPopup(el)},600)});function posPopup(el){var popup=D.querySelector(PCLS);if(!popup){setTimeout(function(){posPopup(el)},100);return}var r=el.getBoundingClientRect(),vw=P.innerWidth,vh=P.innerHeight,pw=400,ph=popup.offsetHeight||380,gap=24,left,top;if(r.right+gap+pw<vw){left=r.right+gap;top=r.top}else if(r.left-gap-pw>0){left=r.left-gap-pw;top=r.top}else if(r.bottom+gap+ph<vh){left=Math.max(gap,r.left+(r.width-pw)/2);top=r.bottom+gap}else{left=Math.max(gap,r.left+(r.width-pw)/2);top=Math.max(gap,r.top-ph-gap)}left=Math.max(20,Math.min(left,vw-pw-20));top=Math.max(20,Math.min(top,vh-ph-20));var s=D.getElementById('tour-pos');if(s)s.remove();s=D.createElement('style');s.id='tour-pos';s.textContent=PCLS+'{left:'+left+'px!important;top:'+top+'px!important;opacity:1!important;animation:_tFadeIn .4s cubic-bezier(.34,1.56,.64,1) both!important;}';D.head.appendChild(s);function repos(){var nr=el.getBoundingClientRect(),pad=8;sp.style.left=(nr.left-pad)+'px';sp.style.top=(nr.top-pad)+'px';sp.style.width=(nr.width+pad*2)+'px';sp.style.height=(nr.height+pad*2)+'px';if(nr.right+gap+pw<vw){left=nr.right+gap;top=nr.top}else if(nr.left-gap-pw>0){left=nr.left-gap-pw;top=nr.top}else{left=Math.max(20,nr.left+(nr.width-pw)/2);top=nr.bottom+gap}left=Math.max(20,Math.min(left,vw-pw-20));top=Math.max(20,Math.min(top,vh-ph-20));s.textContent=PCLS+'{left:'+left+'px!important;top:'+top+'px!important;opacity:1!important;}'}P.addEventListener('scroll',repos,{passive:true});P.addEventListener('resize',repos,{passive:true})}})();</script>""" % _djs_sel
            st_components.html(_dtour_js, height=0)

            if _d_finish:
                _d_desc = """<div style="font-size:.85rem;color:#334155;line-height:1.65;">
                    Tour complete! You know how to filter, compare, analyze skills, and use AI insights.
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
                                <div style="font-size:1.05rem;font-weight:800;color:#fff;">%s</div>
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
                        if _prev <= _d_dash_steps:
                            st.session_state["selected_associate"] = None
                            st.session_state.pop("dash_tab", None)
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
                            st.session_state["selected_associate"] = None
                            st.session_state.pop("dash_tab", None)
                            st.rerun()
                with _dc3:
                    if st.button("Skip Tour", key="_dtour_skip", use_container_width=True):
                        st.session_state["_tour_step"] = 0
                        st.session_state["_tour_seen"] = True
                        st.session_state["selected_associate"] = None
                        st.session_state.pop("dash_tab", None)
                        st.rerun()
    else:
        st_components.html("""<script>(function(){var D=window.parent.document;var b=D.getElementById('tour-spotlight-box');if(b)b.remove();var s=D.getElementById('tour-pos');if(s)s.remove();})()</script>""", height=0)

    _det_active = st.pills("", ["Overview", "Cases & Trends", "Skills", "AI Insights"],
                           default="Overview", key="det_tab")
    if not _det_active:
        _det_active = "Overview"

    # ─── TAB 1: OVERVIEW ───
    if _det_active == "Overview":
        certs = row.get("certifications", "")
        cert_val = certs if pd.notna(certs) and str(certs).strip() else "None"
        hire_val = row['hire_date'].strftime('%Y-%m-%d') if pd.notna(row.get('hire_date')) else "N/A"
        st.markdown(_html(f"""<div class="profile-strip">
            <div class="profile-item">
                <div class="profile-icon">&#9993;</div>
                <div><div class="profile-label">Email</div><div class="profile-value">{row['email']}</div></div>
            </div>
            <div class="profile-item">
                <div class="profile-icon">&#128100;</div>
                <div><div class="profile-label">Manager</div><div class="profile-value">{row['manager_name']}</div></div>
            </div>
            <div class="profile-item">
                <div class="profile-icon">&#127942;</div>
                <div><div class="profile-label">Certifications</div><div class="profile-value">{cert_val}</div></div>
            </div>
            <div class="profile-item">
                <div class="profile-icon">&#128197;</div>
                <div><div class="profile-label">Hire Date</div><div class="profile-value">{hire_val}</div></div>
            </div>
        </div>"""), unsafe_allow_html=True)

        # Detail KPI Deltas (vs last 30 days)
        _dnow = pd.Timestamp.now()
        _d30 = _dnow - pd.Timedelta(days=30)
        _d60 = _dnow - pd.Timedelta(days=60)
        _dc = a_cases[a_cases["creation_date"] >= _d30]
        _dp = a_cases[(a_cases["creation_date"] >= _d60) & (a_cases["creation_date"] < _d30)]
        _dc_res = len(_dc[_dc["status"].isin(["Resolved", "Closed"])])
        _dp_res = len(_dp[_dp["status"].isin(["Resolved", "Closed"])])
        _dc_esc = int(_dc["escalated"].sum())
        _dp_esc = int(_dp["escalated"].sum())

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Total Cases Owned", n, delta=f"{len(_dc)} this month" if len(_dc) else None)
        k2.metric("Cases Resolved", n_res,
                  delta=f"{_dc_res - _dp_res:+d}" if _dp_res else None, delta_color="normal")
        k3.metric("Avg CSAT Score", f"{avg_c:.1f}" if pd.notna(avg_c) else "N/A")
        k4.metric("Avg Resolve Time", f"{avg_t:.0f} hrs" if pd.notna(avg_t) else "N/A")
        k5.metric("Total Escalations", n_esc,
                  delta=f"{_dc_esc - _dp_esc:+d}" if _dp_esc else None, delta_color="inverse")
        k6.metric("Performance Score", f"{ps}/100")

        if n == 0:
            st.warning("No cases found for this associate with the current filters.")
            return

        def _gen_insight():
            ctx = build_assoc_context(row["associate_name"], a_cases, a_skills)
            msgs = [
                {"role": "system", "content":
                    "You are a Red Hat support operations analyst. Give a 4-line performance card: "
                    "Line 1: Overall verdict (Strong/Solid/Needs Improvement) with resolution rate. "
                    "Line 2: Top strength (best product area or skill, with case count). "
                    "Line 3: Key risk (highest escalation area, pending cases, or low CSAT product). "
                    "Line 4: One specific action recommendation. "
                    "Use exact numbers. Cases without CSAT are still open — say 'pending' not 'N/A'."},
                {"role": "user", "content": f"Quick summary:\n\n{ctx}"},
            ]
            with st.spinner("Generating insight..."):
                result = call_ai(msgs, max_tokens=200)
            sk_str = ", ".join(a_skills["skill_name"].tolist()) if not a_skills.empty else ""
            st.session_state.ai_insight = result if result else local_summary(
                row["associate_name"], a_cases, sk_str)
            st.rerun()

        if st.session_state.ai_insight:
            st.markdown(ai_card_html("AI Quick Insight", st.session_state.ai_insight),
                        unsafe_allow_html=True)
            if st.button("Regenerate", key="regen_overview"):
                st.session_state.ai_regen_count += 1
                _gen_insight()
        else:
            st.markdown(ai_card_empty("AI Quick Insight"), unsafe_allow_html=True)
            if st.button("Generate Insight", key="gen_overview",
                         type="primary"):
                _gen_insight()

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
            _min_dt = a_cases["creation_date"].min().date() if len(a_cases) else pd.Timestamp.now().date()
            _max_dt = a_cases["creation_date"].max().date() if len(a_cases) else pd.Timestamp.now().date()
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

        _tl_cases = a_cases.copy()
        if isinstance(_date_range, (list, tuple)) and len(_date_range) == 2:
            _dr_start, _dr_end = pd.Timestamp(_date_range[0]), pd.Timestamp(_date_range[1]) + pd.Timedelta(days=1)
            _tl_cases = _tl_cases[(_tl_cases["creation_date"] >= _dr_start) & (_tl_cases["creation_date"] < _dr_end)]

        freq = {"Day": "D", "Week": "W", "Month": "MS", "Quarter": "QS"}[period]
        if len(_tl_cases) > 0:
            _rs = _tl_cases.set_index("creation_date").resample(freq)
            ts = pd.DataFrame({
                "creation_date": _rs["case_number"].count().index,
                "Cases": _rs["case_number"].count().values,
                "Escalations": _rs["escalated"].sum().values,
            })
        else:
            ts = pd.DataFrame(columns=["creation_date", "Cases", "Escalations"])

        if period == "Day":
            ts = ts[ts["Cases"] > 0].reset_index(drop=True)

        fig = go.Figure()
        if period == "Day":
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
                marker=dict(size=7, color="#EF4444", symbol="diamond",
                            line=dict(width=2, color="white")),
            ))
        else:
            fig.add_trace(go.Scatter(
                x=ts["creation_date"], y=ts["Cases"], name="Cases",
                mode="lines+markers",
                line=dict(color=GRADIENT_PAIRS[0][0], width=2.5, shape="spline"),
                marker=dict(size=7, color=GRADIENT_PAIRS[0][0], symbol="circle",
                            line=dict(width=2, color="white")),
                fill="tozeroy",
                fillcolor=f"rgba({','.join(str(int(GRADIENT_PAIRS[0][0].lstrip('#')[i:i+2],16)) for i in (0,2,4))},0.15)",
            ))
            fig.add_trace(go.Scatter(
                x=ts["creation_date"], y=ts["Escalations"], name="Escalations",
                mode="lines+markers", yaxis="y2",
                line=dict(color="#EF4444", width=2.5, shape="spline"),
                marker=dict(size=7, color="#EF4444", symbol="diamond",
                            line=dict(width=2, color="white")),
                fill="tozeroy", fillcolor="rgba(239,68,68,0.08)",
            ))

        _styled_layout(fig, height=360)
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
        elif period == "Quarter":
            _tf, _dt = "%b %Y", "M3"
        else:
            _tf, _dt = "%b %Y", "M1"
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
            hovermode="x unified",
        )
        evt = st.plotly_chart(fig, use_container_width=True, key="det_timeline",
                              on_select="rerun")
        if evt and evt.selection and not st.session_state.get("_dialog_open"):
            pts = evt.selection.get("points", getattr(evt.selection, "points", []))
            if pts:
                p = pts[0]
                px = p.get("x") if isinstance(p, dict) else getattr(p, "x", None)
                if px is not None:
                    clicked_dt = pd.Timestamp(px)
                    _offsets = {"D": {"days": 1}, "W": {"weeks": 1},
                                "MS": {"months": 1}, "QS": {"months": 3}}
                    p_end = clicked_dt + pd.DateOffset(**_offsets[freq])
                    _fmt = {"Day": "%b %d, %Y", "Week": "Week of %b %d, %Y",
                            "Month": "%b %Y", "Quarter": None}
                    if period == "Quarter":
                        _lbl = f"Q{(clicked_dt.month - 1) // 3 + 1} {clicked_dt.year}"
                    else:
                        _lbl = clicked_dt.strftime(_fmt[period])
                    st.session_state["_dialog_open"] = True
                    _timeline_period_popup(_lbl, clicked_dt, p_end, a_cases)

    # ─── TAB 2: CASES & TRENDS ───
    if _det_active == "Cases & Trends":
        if n == 0:
            st.warning("No cases to display.")
            return

        st.subheader("Case Distribution Analysis")
        st.caption("Explore how cases are distributed — click any segment for details")
        dim = st.pills("View cases by", ["Product", "Severity", "Status", "Account"],
                       default="Product", key="det_chart_dim")
        if not dim:
            dim = "Product"

        dim_map = {
            "Product":  ("product_name",  10),
            "Severity": ("severity",      None),
            "Status":   ("status",        None),
            "Account":  ("account_name",  8),
        }
        col, top_n = dim_map[dim]
        vc = a_cases[col].value_counts()
        if top_n:
            vc = vc.head(top_n)
        chart_df = vc.reset_index()
        chart_df.columns = [dim, "Cases"]

        color_map = {}
        if dim == "Severity":
            color_map = SEVERITY_COLORS
        elif dim == "Status":
            color_map = STATUS_COLORS

        dim_titles = {
            "Product": "Cases by Product",
            "Severity": "Cases by Severity Level",
            "Status": "Cases by Current Status",
            "Account": "Cases by Account",
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
            xaxis=dict(title="No. of Cases", dtick=max(1, _dim_max // 6)),
            hovermode="closest", clickmode="event+select",
        )

        dim_evt = st.plotly_chart(fig_dim, use_container_width=True,
                                  key="det_chart_unified", on_select="rerun",
                                  selection_mode=("points",))

        # ── Drill-down on click ──
        sel_val = None
        if dim_evt and dim_evt.selection:
            pts = dim_evt.selection.get("points", dim_evt.selection.points if hasattr(dim_evt.selection, "points") else [])
            if pts:
                p = pts[0]
                if isinstance(p, dict):
                    sel_val = p.get("y") or p.get("label")
                else:
                    sel_val = getattr(p, "y", None) or getattr(p, "label", None)
            if not sel_val:
                idxs = dim_evt.selection.get("point_indices", getattr(dim_evt.selection, "point_indices", []))
                if idxs and idxs[0] < len(chart_df):
                    sel_val = chart_df.iloc[idxs[0]][dim]

        drill_show = [c if c != "case_owner" else "account_name" for c in DRILL_COLS]

        if sel_val:
            drill = a_cases[a_cases[col] == sel_val]
            st.markdown(f"### {sel_val} — {len(drill)} Cases")
            st.dataframe(_rename_case_cols(drill[drill_show].sort_values("creation_date", ascending=False)),
                         use_container_width=True, height=300, hide_index=True)

        st.subheader("Complete Case History")
        st.caption(f"Showing all {n} cases for this associate")
        show_cols = ["case_number", "severity", "status", "product_name",
                     "problem_statement", "account_name", "creation_date",
                     "escalated", "csat_score"]
        st.dataframe(_rename_case_cols(a_cases[show_cols].sort_values("creation_date", ascending=False)),
                     use_container_width=True, height=400)
        st.download_button("Download Cases CSV",
                           a_cases[show_cols].to_csv(index=False),
                           f"{assoc_id}_cases.csv", "text/csv")

    # ─── TAB 3: SKILLS ───
    if _det_active == "Skills":
        sk_left, sk_right = st.columns([3, 1])
        with sk_left:
            st.subheader("Skill Profile")
        with sk_right:
            _do_extract = st.button("Extract Skills via AI", key="ai_extract_skills",
                                    type="primary", use_container_width=True)

        if _do_extract:
            _certs_raw = row.get("certifications", "")
            _certs_str = _certs_raw if pd.notna(_certs_raw) and str(_certs_raw).strip() else ""
            _cert_list = [c.strip() for c in _certs_str.split(",") if c.strip()] if _certs_str else []

            existing_skills = set(
                skills_df[skills_df["associate_id"] == assoc_id]["skill_name"]
                .str.lower().str.strip().tolist()
            )

            inferred = []
            seen_lower = set()
            for cert in _cert_list:
                mapped = CERT_SKILL_MAP.get(cert, [])
                for sk_name, confidence, reason in mapped:
                    sk_lower = sk_name.lower().strip()
                    if sk_lower not in existing_skills and sk_lower not in seen_lower:
                        inferred.append({
                            "skill": sk_name, "confidence": confidence,
                            "reason": reason, "source_cert": cert,
                        })
                        seen_lower.add(sk_lower)

            if not _cert_list:
                ai_extra = []
                products = a_cases["product_name"].value_counts().head(10).to_dict()
                prompt = (
                    f"Associate: {row['associate_name']}, SBR: {row['sbr']}, "
                    f"Level: {row['skill_level']}.\n"
                    f"Products handled: {products}\n\n"
                    "This associate has no certifications recorded. Based on their product experience, "
                    "infer 8 technical skills they likely possess.\n\n"
                    "Return EXACTLY 8 lines in this format, nothing else:\n"
                    "SKILL: Linux Administration | CONFIDENCE: 85 | REASON: Works extensively with RHEL products\n"
                )
                msgs = [
                    {"role": "system", "content":
                        "You are a technical skill inference engine. "
                        "Return ONLY lines in the exact SKILL/CONFIDENCE/REASON format. No extra text."},
                    {"role": "user", "content": prompt},
                ]
                with st.spinner("AI is analyzing case data to infer skills..."):
                    result = call_ai(msgs, max_tokens=500)
                if result:
                    for line in result.strip().split("\n"):
                        line = line.strip().lstrip("0123456789.-) ")
                        m = re.search(
                            r"SKILL:\s*(.+?)\s*\|\s*CONFIDENCE:\s*(\d+)\s*\|\s*REASON:\s*(.+)",
                            line, re.IGNORECASE)
                        if m:
                            sk_name = m.group(1).strip()
                            if sk_name.lower() not in existing_skills and sk_name.lower() not in seen_lower:
                                ai_extra.append({
                                    "skill": sk_name, "confidence": int(m.group(2)),
                                    "reason": m.group(3).strip(), "source_cert": "Case Analysis",
                                })
                                seen_lower.add(sk_name.lower())
                inferred.extend(ai_extra)

            st.session_state["_ai_inferred"] = inferred
            st.session_state["_ai_existing"] = list(existing_skills)
            st.session_state["_ai_certs"] = _cert_list

        if st.session_state.get("_ai_inferred") is not None:
            _inferred = st.session_state["_ai_inferred"]
            _existing = st.session_state.get("_ai_existing", [])
            _certs_used = st.session_state.get("_ai_certs", [])

            st.markdown(_html(f"""<div style="background:linear-gradient(135deg,#EEF2FF,#F0F9FF);
                border:1px solid #C7D2FE;border-radius:16px;padding:24px;margin:12px 0;">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
                    <span style="font-size:1.4rem;">🧠</span>
                    <span style="font-size:1.1rem;font-weight:700;color:#312E81;">AI Skill Discovery Results</span>
                </div>
                <div style="color:#64748B;font-size:0.82rem;margin-bottom:4px;">
                    Certifications analyzed: <strong>{', '.join(_certs_used) if _certs_used else 'None — used case analysis'}</strong>
                    &nbsp;|&nbsp; Existing skills: <strong>{len(_existing)}</strong>
                    &nbsp;|&nbsp; New skills discovered: <strong>{len(_inferred)}</strong>
                </div>
            </div>"""), unsafe_allow_html=True)

            if _existing:
                with st.expander(f"📋 Existing Skills in Database ({len(_existing)})", expanded=False):
                    _ex_pills = "".join(
                        f'<span style="display:inline-block;padding:5px 14px;margin:3px;'
                        f'border-radius:99px;font-size:0.78rem;font-weight:600;'
                        f'background:#F1F5F9;color:#475569;border:1px solid #E2E8F0;">{s.title()}</span>'
                        for s in sorted(_existing)
                    )
                    st.markdown(_ex_pills, unsafe_allow_html=True)

            if _inferred:
                st.markdown(f"#### 🆕 AI Inferred Skills ({len(_inferred)})")
                _sel_key = "_ai_sel_skills"
                if _sel_key not in st.session_state:
                    st.session_state[_sel_key] = [True] * len(_inferred)

                _skill_cards = []
                for i, sk in enumerate(_inferred):
                    conf = sk["confidence"]
                    conf_color = "#10B981" if conf >= 90 else "#F59E0B" if conf >= 80 else "#6366F1"
                    conf_bar_w = conf
                    _skill_cards.append(f"""<div style="background:{PF_SURFACE};border:1px solid #E2E8F0;
                        border-radius:12px;padding:16px 20px;
                        display:flex;align-items:center;gap:16px;
                        transition:all 0.2s ease;">
                        <div style="flex:1;">
                            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap;">
                                <span style="font-weight:700;font-size:0.95rem;color:#1E293B;">
                                    ✓ {sk['skill']}</span>
                                <span style="background:#DCFCE7;color:#166534;font-size:0.65rem;
                                    font-weight:700;padding:2px 8px;border-radius:99px;">NEW</span>
                                <span style="color:#94A3B8;font-size:0.72rem;">from {sk['source_cert']}</span>
                            </div>
                            <div style="color:#64748B;font-size:0.78rem;margin-bottom:6px;">
                                {sk['reason']}</div>
                            <div style="display:flex;align-items:center;gap:8px;">
                                <span style="font-size:0.72rem;font-weight:600;color:{conf_color};">
                                    Confidence: {conf}%</span>
                                <div style="flex:1;max-width:120px;height:4px;background:#F1F5F9;border-radius:99px;overflow:hidden;">
                                    <div style="width:{conf_bar_w}%;height:100%;background:{conf_color};border-radius:99px;"></div>
                                </div>
                            </div>
                        </div>
                    </div>""")
                st.markdown(_html('<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">'
                            + ''.join(_skill_cards) + '</div>'), unsafe_allow_html=True)

                st.markdown("")
                _add_col, _cancel_col = st.columns(2)
                with _add_col:
                    if st.button("✓ Add All Inferred Skills to Profile", key="ai_add_skills",
                                 type="primary", use_container_width=True):
                        conn = get_connection()
                        cur_max = conn.execute(
                            f"SELECT COALESCE(MAX(skill_rank), 0) FROM skills WHERE associate_id = {PARAM}",
                            (assoc_id,)).fetchone()[0]
                        added = 0
                        for idx, sk in enumerate(_inferred):
                            conn.execute(
                                f"INSERT INTO skills (associate_id, associate_name, skill_name, skill_rank, relevance_score) "
                                f"VALUES ({PARAM}, {PARAM}, {PARAM}, {PARAM}, {PARAM})",
                                (assoc_id, row["associate_name"], sk["skill"],
                                 cur_max + idx + 1, min(10, sk["confidence"] // 10)),
                            )
                            added += 1
                        conn.commit()
                        conn.close()
                        load_all_data.clear()
                        st.session_state.pop("_ai_inferred", None)
                        st.session_state.pop("_ai_existing", None)
                        st.session_state.pop("_ai_certs", None)
                        st.session_state.pop("_ai_sel_skills", None)
                        st.toast(f"Added {added} new skills to profile!")
                        st.rerun()
                with _cancel_col:
                    if st.button("✕ Cancel", key="ai_cancel_skills", use_container_width=True):
                        st.session_state.pop("_ai_inferred", None)
                        st.session_state.pop("_ai_existing", None)
                        st.session_state.pop("_ai_certs", None)
                        st.session_state.pop("_ai_sel_skills", None)
                        st.rerun()
            elif st.session_state.get("_ai_inferred") is not None and len(_inferred) == 0:
                st.success("All certification-derived skills are already in this associate's profile!")
                if st.button("OK", key="ai_dismiss_ok"):
                    st.session_state.pop("_ai_inferred", None)
                    st.rerun()

        a_skills = skills_df[skills_df["associate_id"] == assoc_id].sort_values("skill_rank")

        if a_skills.empty:
            st.info("No skills recorded. Click **Extract Skills via AI** to analyze cases and generate skills.")
        else:
            pills_html = "".join(
                f'<span class="skill-pill" style="background:{SKILL_COLORS[i % len(SKILL_COLORS)]};">'
                f'{r["skill_name"]}</span>'
                for i, (_, r) in enumerate(a_skills.iterrows())
            )
            st.markdown(f'<div class="skill-pills">{pills_html}</div>', unsafe_allow_html=True)
            st.markdown("")

            st.dataframe(
                a_skills[["skill_name", "skill_rank", "relevance_score"]].rename(
                    columns={"skill_name": "Skill Name", "skill_rank": "Skill Rank", "relevance_score": "Relevance Score"}),
                use_container_width=True, hide_index=True,
            )

            st.subheader("Skill Competency Radar")
            st.caption("Relevance score (1-5) for top skills")
            radar = a_skills.head(6)
            fig = go.Figure()
            fig.add_trace(go.Scatterpolar(
                r=radar["relevance_score"].tolist(),
                theta=radar["skill_name"].tolist(),
                fill="toself", fillcolor="rgba(99,102,241,0.18)",
                line=dict(color=GRADIENT_PAIRS[0][0], width=2.5, shape="spline"),
                marker=dict(size=6, color=GRADIENT_PAIRS[0][0]),
                name="Relevance",
            ))
            fig.update_layout(
                template=CHART_TPL, paper_bgcolor=CHART_BG,
                font=dict(family="Red Hat Display, sans-serif"),
                polar=dict(
                    bgcolor="rgba(0,0,0,0)",
                    radialaxis=dict(visible=True, range=[0, 5],
                                    tickfont=dict(size=9, color=CHART_FONT2),
                                    gridcolor=CHART_GRID,
                                    tickvals=[1, 2, 3, 4, 5]),
                    angularaxis=dict(tickfont=dict(size=10, color=CHART_FONT),
                                     gridcolor=CHART_GRID),
                ),
                showlegend=False,
                height=320, margin=dict(l=50, r=50, t=20, b=30),
                transition=dict(duration=700, easing="cubic-in-out"),
            )
            st.plotly_chart(fig, use_container_width=True, key=f"radar_{assoc_id}")

    # ─── TAB 4: AI INSIGHTS ───
    if _det_active == "AI Insights":
        # ── Compute all metrics locally ──
        _res_rate = (n_res / n * 100) if n else 0
        _esc_rate_pct = (n_esc / n * 100) if n else 0
        _csat_display = f"{avg_c:.1f}" if pd.notna(avg_c) else "N/A"
        _ttr_display = f"{avg_t:.0f}" if pd.notna(avg_t) else "N/A"

        # Verdict
        if ps >= 75:
            _verdict, _v_color, _v_bg = "Strong", "#059669", "rgba(5,150,105,0.08)"
        elif ps >= 55:
            _verdict, _v_color, _v_bg = "Steady", "#D97706", "rgba(217,119,6,0.08)"
        elif ps >= 35:
            _verdict, _v_color, _v_bg = "At Risk", "#EA580C", "rgba(234,88,12,0.08)"
        else:
            _verdict, _v_color, _v_bg = "Critical", "#DC2626", "rgba(220,38,38,0.08)"

        # Product breakdown
        _prod_counts = a_cases["product_name"].value_counts().head(5)
        _sev_counts = a_cases["severity"].value_counts()
        _status_counts = a_cases["status"].value_counts()

        # 30-day trends
        _now = pd.Timestamp.now()
        _30d = _now - pd.Timedelta(days=30)
        _60d = _now - pd.Timedelta(days=60)
        _cur_cases = a_cases[a_cases["creation_date"] >= _30d]
        _prev_cases = a_cases[(a_cases["creation_date"] >= _60d) & (a_cases["creation_date"] < _30d)]
        _cur_res = len(_cur_cases[_cur_cases["status"].isin(["Resolved", "Closed"])])
        _prev_res = len(_prev_cases[_prev_cases["status"].isin(["Resolved", "Closed"])])
        _cur_csat = _cur_cases["csat_score"].mean()
        _prev_csat = _prev_cases["csat_score"].mean()
        _cur_esc = int(_cur_cases["escalated"].sum())
        _prev_esc = int(_prev_cases["escalated"].sum())
        _csat_trend = f"{_cur_csat - _prev_csat:+.1f}" if pd.notna(_cur_csat) and pd.notna(_prev_csat) else "—"
        _res_trend = f"{_cur_res - _prev_res:+d}"
        _esc_trend = f"{_cur_esc - _prev_esc:+d}"

        # Certs & Skills
        _certs_raw = row.get("certifications", "")
        _certs_val = _certs_raw if pd.notna(_certs_raw) and str(_certs_raw).strip() else "None"
        _skill_names = a_skills["skill_name"].tolist() if not a_skills.empty else []
        _top_skill = _skill_names[0] if _skill_names else "—"

        # Top product by cases
        _top_product = _prod_counts.index[0] if len(_prod_counts) > 0 else "—"
        _top_product_n = int(_prod_counts.iloc[0]) if len(_prod_counts) > 0 else 0

        # ── Written Performance Summary ──
        _rc = "#10B981" if _res_rate >= 80 else ("#F59E0B" if _res_rate >= 60 else "#EF4444")
        _ec = "#10B981" if _esc_rate_pct <= 10 else ("#F59E0B" if _esc_rate_pct <= 20 else "#EF4444")
        _tc = "#10B981" if pd.notna(avg_t) and avg_t <= 24 else ("#F59E0B" if pd.notna(avg_t) and avg_t <= 48 else "#EF4444")

        _perf_bullets = []
        _perf_bullets.append(f"Overall verdict: <b style='color:{_v_color};'>{_verdict}</b> — "
                             f"performance score <b>{ps:.0f}/100</b> ({row['skill_level']}, {row['sbr']}, {row['shift']})")
        _perf_bullets.append(f"Resolution rate: <b style='color:{_rc};'>{_res_rate:.0f}%</b> "
                             f"({n_res} resolved out of {n} total cases)"
                             + (f" — 30d trend: <b>{_res_trend}</b>" if _res_trend != "—" else ""))
        _perf_bullets.append(f"Average CSAT: <b style='color:{'#10B981' if pd.notna(avg_c) and avg_c >= 4 else '#F59E0B'};'>"
                             f"{_csat_display}/5</b>"
                             + (f" — 30d trend: <b>{_csat_trend}</b>" if _csat_trend != "—" else ""))
        _perf_bullets.append(f"Escalation rate: <b style='color:{_ec};'>{_esc_rate_pct:.0f}%</b> "
                             f"({n_esc} escalations)"
                             + (f" — 30d trend: <b>{_esc_trend}</b>" if _esc_trend != "—" else ""))
        _perf_bullets.append(f"Average time to resolve: <b style='color:{_tc};'>{_ttr_display} hours</b>")

        _perf_rec = None
        if _esc_rate_pct > 20:
            _perf_rec = (f"&#9889; <b>Recommendation:</b> Escalation rate at {_esc_rate_pct:.0f}% — "
                         f"pair with senior engineer on <b>{_top_product}</b> cases for mentoring")
        elif _res_rate < 50:
            _perf_rec = (f"&#9889; <b>Recommendation:</b> {n - n_res} open cases — "
                         f"audit for blockers and consider workload redistribution across the {row['sbr']} team")
        elif pd.notna(avg_c) and avg_c < 3.5:
            _perf_rec = (f"&#9889; <b>Recommendation:</b> CSAT at {_csat_display}/5 — "
                         f"schedule follow-ups on next 5 resolved cases to identify improvement areas")
        elif pd.notna(avg_t) and avg_t > 200:
            _perf_rec = (f"&#9889; <b>Recommendation:</b> Avg TTR {_ttr_display} hrs — "
                         f"focus training on <b>{_top_product}</b> to speed up resolution")
        else:
            _perf_rec = (f"&#11088; <b>Recommendation:</b> Strong performance — "
                         f"consider for peer mentoring role or cross-SBR knowledge sharing")
        if _perf_rec:
            _perf_bullets.append(_perf_rec)

        _perf_html = "".join(
            f'<div style="padding:7px 0;border-bottom:1px dashed #E2E8F0;font-size:0.82rem;'
            f'color:#334155;line-height:1.6;">{b}</div>'
            for b in _perf_bullets
        )

        st.markdown(_html(f"""<div style="background:#fff;border:1px solid #E2E8F0;border-radius:16px;
            padding:22px 26px;margin-bottom:16px;box-shadow:0 4px 16px rgba(0,0,0,0.04);">
            <div style="font-size:0.88rem;font-weight:800;color:#1E293B;margin-bottom:12px;">
                Performance Summary</div>
            <div style="height:1px;background:#E2E8F0;margin-bottom:14px;"></div>
            {_perf_html}
        </div>"""), unsafe_allow_html=True)

        # ── Written Case & Profile Summary ──
        _status_lines = ", ".join(f"<b>{v}</b> {s}" for s, v in _status_counts.items())
        _sev_lines = ", ".join(f"<b>{v}</b> {s}" for s, v in _sev_counts.items())
        _prod_lines = ", ".join(f"{p} (<b>{v}</b>)" for p, v in _prod_counts.items())

        _case_bullets = [
            f"Case status breakdown: {_status_lines}",
            f"Severity distribution: {_sev_lines}",
            f"Top products handled: {_prod_lines}" if _prod_lines else "No product data available",
        ]

        _certs_raw = row.get("certifications", "")
        _certs_val = _certs_raw if pd.notna(_certs_raw) and str(_certs_raw).strip() else "None"
        _skill_names_display = ", ".join(_skill_names[:8]) if _skill_names else "No skills recorded"

        _profile_bullets = [
            f"Certifications: <b>{_certs_val}</b>",
            f"Primary skill: <b>{_top_skill}</b> | Top product: <b>{_top_product}</b> ({_top_product_n} cases)",
            f"Manager: <b>{row['manager_name']}</b>",
            f"Skills: {_skill_names_display}",
        ]

        _case_html = "".join(
            f'<div style="padding:7px 0;border-bottom:1px dashed #E2E8F0;font-size:0.82rem;'
            f'color:#334155;line-height:1.6;">{b}</div>'
            for b in _case_bullets
        )
        _prof_html = "".join(
            f'<div style="padding:7px 0;border-bottom:1px dashed #E2E8F0;font-size:0.82rem;'
            f'color:#334155;line-height:1.6;">{b}</div>'
            for b in _profile_bullets
        )

        _cl, _cr = st.columns(2)
        with _cl:
            st.markdown(_html(f"""<div style="background:#fff;border:1px solid #E2E8F0;border-radius:16px;
                padding:22px 26px;box-shadow:0 4px 16px rgba(0,0,0,0.04);margin-bottom:16px;">
                <div style="font-size:0.88rem;font-weight:800;color:#1E293B;margin-bottom:12px;">
                    Case Breakdown</div>
                <div style="height:1px;background:#E2E8F0;margin-bottom:14px;"></div>
                {_case_html}
            </div>"""), unsafe_allow_html=True)
        with _cr:
            st.markdown(_html(f"""<div style="background:#fff;border:1px solid #E2E8F0;border-radius:16px;
                padding:22px 26px;box-shadow:0 4px 16px rgba(0,0,0,0.04);margin-bottom:16px;">
                <div style="font-size:0.88rem;font-weight:800;color:#1E293B;margin-bottom:12px;">
                    Associate Profile</div>
                <div style="height:1px;background:#E2E8F0;margin-bottom:14px;"></div>
                {_prof_html}
            </div>"""), unsafe_allow_html=True)

        # ── Section 5: AI Strengths / Risks / Actions ──
        def _gen_scorecard_insight():
            ctx = build_assoc_context(row["associate_name"], a_cases, a_skills)
            res_rate = f"{n_res/n*100:.0f}" if n > 0 else "0"
            esc_rate = f"{n_esc/n*100:.0f}" if n > 0 else "0"
            msgs = [
                {"role": "system", "content":
                    "You are a senior Red Hat support operations analyst writing a performance review. "
                    "Return EXACTLY 5 sections separated by the markers below. No markdown headers — just the markers.\n\n"
                    "SUMMARY:\nOne concise paragraph (3-4 sentences) assessing overall performance. "
                    "Include the verdict: Outstanding (res>85%, esc<10%), Strong (res>70%, esc<15%), "
                    "Developing (res>50%), or Needs Improvement. Reference specific numbers.\n\n"
                    "STRENGTHS:\n3-4 bullet points. Each must reference a specific product, case count, or metric. "
                    "Example: '- Resolved 8/9 Red Hat OpenShift cases with 4.2 avg CSAT — top performer in this product area'\n\n"
                    "RISKS:\n2-3 bullet points about specific problem areas. Name the exact product/severity/account. "
                    "Example: '- 3 of 4 escalations came from Red Hat Satellite cases — CSAT dropped to 2.0 in this product'\n\n"
                    "ACTIONS:\n3-4 bullet points. Each must be a specific, executable action — not vague advice. "
                    "Example: '- Pair with a Satellite specialist to co-handle the 2 open Sev1 cases before they escalate'\n"
                    "Example: '- Request Satellite troubleshooting lab access to build hands-on debugging skills'\n"
                    "BAD example (too vague): '- Improve resolution rate' or '- Enhance problem-solving skills'\n\n"
                    "GAPS:\n2-3 bullet points naming specific Red Hat products/technologies where upskilling is needed, with reasoning.\n\n"
                    "Rules: Use ONLY exact numbers from the data. Never invent metrics. "
                    "Missing CSAT = case still open = say 'pending'. Keep each bullet under 25 words."},
                {"role": "user", "content":
                    f"Analyze (resolution rate: {res_rate}%, escalation rate: {esc_rate}%):\n\n{ctx}"},
            ]
            with st.spinner("Generating AI analysis..."):
                result = call_ai(msgs, max_tokens=600)
            st.session_state["_scorecard_ai"] = result if result else None
            st.rerun()

        _ai_btn_col1, _ai_btn_col2, _ = st.columns([1, 1, 4])
        with _ai_btn_col1:
            if st.button("Generate AI Analysis", key="gen_ai_tab4_sc",
                         type="primary", use_container_width=True):
                _gen_scorecard_insight()
        with _ai_btn_col2:
            if st.session_state.get("_scorecard_ai"):
                if st.button("Regenerate", key="regen_ai_tab4_sc", use_container_width=True):
                    _gen_scorecard_insight()

        if st.session_state.get("_scorecard_ai"):
            st.markdown(ai_card_html("AI Performance Analysis", st.session_state["_scorecard_ai"]),
                        unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

def render_dashboard():
    _render_site_header()

    # ── Enterprise Guided Tour ──────────────────────────────────────────────────
    if not st.session_state.get("_tour_seen") and st.session_state.get("_tour_step", 0) == 0:
        st.session_state["_tour_step"] = 1

    _tour_step = st.session_state.get("_tour_step", 0)
    if _tour_step > 0:
        _trole = st.session_state.get("role", "associate")
        # Every step below declares nav_tab explicitly. The old `_tour_step <= 4`
        # fallback assumed the first four steps lived on Associates; with My Desk
        # in front of them that assumption no longer holds.
        _tour_steps = [
            {"icon": "👋", "label": "WELCOME", "title": "Associates Dashboard",
             "desc": "", "sel": "", "welcome": True, "nav_tab": "My Desk"},

            # ── My Desk: the operational workspace ──
            {"icon": "🗂️", "label": "MY DESK", "title": "Your Operational Workspace",
             "desc": "This is where a shift starts. My Desk answers one question — what do I work on right now — and every panel below exists to justify that answer. The rest of the dashboard is retrospective; this tab is not.",
             "sel": ".st-key-desk_header", "nav_tab": "My Desk"},
            {"icon": "🕐", "label": "DATA AS OF", "title": "Static Extract, Honest Clock",
             "desc": "Case ages and SLA state are measured from the newest timestamp in the data, not from your wall clock. A stale extract therefore cannot age every open case into a false breach. Nothing here is a live feed, and the tab says so.",
             "sel": ".st-key-desk_freshness", "nav_tab": "My Desk"},
            {"icon": "🔎", "label": "SEARCH", "title": "Jump To Anything",
             "desc": "One box for case numbers, accounts, associates and symptom text. Useful when a customer calls with a case number and you have ten seconds before you have to say something intelligent.",
             "sel": ".st-key-desk_search_box", "nav_tab": "My Desk"},
            {"icon": "📌", "label": "PRESSURE", "title": "Where The Pressure Is",
             "desc": "Six counts, not six charts — open, needs your move, SLA breached, at risk, untouched for a week, escalated. 'Needs my move' excludes cases parked on the customer, because those are not yours to progress.",
             "sel": ".st-key-desk_kpis", "nav_tab": "My Desk"},
            {"icon": "🔁", "label": "WHAT CHANGED", "title": "Since Your Last Visit",
             "desc": "Diffed against a snapshot recorded the last time you opened this queue — new cases, departures, fresh escalations, newly breached targets. With a static extract this stays empty, and it tells you that rather than inventing movement.",
             "sel": ".st-key-desk_changed", "nav_tab": "My Desk"},
            {"icon": "📝", "label": "HANDOFF", "title": "Shift Handoff Brief",
             "desc": "One button writes the over-to-you note: Critical, SLA Risk, Waiting on Customer, Escalations, Recommended Follow-ups. It uses the AI endpoint when reachable and a deterministic local brief when it is not — either way, only facts already in the case data.",
             "sel": ".st-key-desk_handoff", "nav_tab": "My Desk"},
            {"icon": "⚡", "label": "QUICK FILTERS", "title": "One-Tap Slices",
             "desc": "Critical, SLA risk, escalated, aging, waiting on customer, high tier, your products. Counts are on the chips, they stack, and every filter is a plain predicate over the queue.",
             "sel": ".st-key-desk_filters", "nav_tab": "My Desk"},
            {"icon": "🎯", "label": "QUEUE", "title": "Ranked By Priority Score",
             "desc": "0-100 from severity, SLA pressure, time since last update, support tier and the escalation flag. SLA pressure and staleness are log-scaled, so a case 200x over target still outranks one 2x over instead of both pinning at 100.",
             "sel": ".st-key-desk_queue", "nav_tab": "My Desk"},
            {"icon": "➡️", "label": "NEXT ACTION", "title": "Recommended Next Action",
             "desc": "Every card names one action and the rule that produced it. These are deterministic rules over fields in the case row — not a prediction, not a model — so you can argue with the recommendation instead of trusting it.",
             "sel": ".st-key-desk_card_top", "nav_tab": "My Desk"},
            {"icon": "🧭", "label": "CASE WORKSPACE", "title": "Everything On One Case",
             "desc": "Open a case for customer context, then five tabs: Timeline, Similar cases, Potential SMEs, Escalation readiness, Private notes — plus an AI case brief with a local fallback. Milestones the dataset does not record are labelled as missing, never filled in.",
             "sel": ".st-key-desk_detail_top", "nav_tab": "My Desk"},
            {"icon": "🛠️", "label": "ACTION CENTER", "title": "What You Can Actually Do",
             "desc": "Follow, export a summary, find an SME, view similar cases. Actions needing write access to the case system are shown disabled with the reason stated — a green button that does nothing is worse than no button.",
             "sel": ".st-key-desk_actions_top", "nav_tab": "My Desk"},
            {"icon": "🧪", "label": "SLA TARGETS", "title": "Targets Are Yours To Set",
             "desc": "The defaults are standard enterprise targets. Change them and every badge, bucket and chart recalculates — useful when your own commitments differ from the defaults.",
             "sel": ".st-key-desk_slatargets", "nav_tab": "My Desk"},
            {"icon": "📚", "label": "MORE TABS", "title": "The Rest Of The Desk",
             "desc": "SLA & Aging, Escalation Risk (naive-Bayes with its own held-out AUC published), Similar & Patterns (TF-IDF search plus observed historical repeats), Trends & Anomalies, My Follow-ups and My Performance. Managers also get Team Queue and Team Workload.",
             "sel": ".st-key-desk_tabs", "nav_tab": "My Desk"},

            # ── The retrospective half of the dashboard ──
            {"icon": "🎛️", "label": "FILTERS", "title": "Global Filter Panel",
             "desc": "Filter the entire dashboard by Geo/Shift, Manager, SBR, Account, Product, and Severity. Every visualization updates automatically.",
             "sel": "section[data-testid='stSidebar']", "nav_tab": "Associates"},
            {"icon": "📊", "label": "KPI METRICS", "title": "Executive Overview",
             "desc": "6 key performance indicators — Active Associates, Cases Resolved, CSAT, Resolve Time, Escalations, Performance.",
             "sel": "div[data-testid='stMetric']", "nav_tab": "Associates"},
            {"icon": "🃏", "label": "CARDS", "title": "Associate Cards",
             "desc": "Each card shows cases, CSAT, performance bar, and skills. Click View Details for full profile, or use Compare Mode and Bulk Select.",
             "sel": ".assoc-card", "nav_tab": "Associates"},
        ]
        if _trole in ("manager", "admin"):
            _tour_steps.extend([
                {"icon": "👥", "label": "TEAM", "title": "Team Dashboard",
                 "desc": "Overview of all SBR teams — stacked bar shows cases vs resolved with CSAT trend line overlay.",
                 "sel": ".st-key-team_perf_overview", "nav_tab": "Team / SBR View"},
                {"icon": "📈", "label": "PERFORMANCE", "title": "Team Analytics",
                 "desc": "Deep-dive into individual SBR team performance. Analyze by product, severity, status, or SBR team.",
                 "sel": ".st-key-team_chart_unified", "nav_tab": "Team / SBR View"},
            ])
        else:
            _tour_steps.extend([
                {"icon": "🔔", "label": "ALERTS", "title": "Anomaly Detection",
                 "desc": "Auto-detects CSAT drops, escalation spikes, and underperformers. Dismissible alert banners appear below the KPI row.",
                 "sel": "div[data-testid='stAlert']", "nav_tab": "Associates"},
                {"icon": "📈", "label": "ANALYTICS", "title": "Charts & Insights",
                 "desc": "Shift workload distribution, case trend timeline, and AI-generated insights.",
                 "sel": "div[data-testid='stPlotlyChart']", "nav_tab": "Associates"},
            ])
        _tour_steps.extend([
            {"icon": "🧠", "label": "SKILLS", "title": "Skill Analytics",
             "desc": "Workforce skill prevalence, certification distribution, and skill catalog across your organization.",
             "sel": ".st-key-sk_chart_unified", "nav_tab": "Skills View"},
            {"icon": "🔥", "label": "HEATMAP", "title": "Skill Coverage",
             "desc": "Skill coverage heatmap shows which associates have which skills. Identify skill gaps across your workforce.",
             "sel": ".st-key-sk_heatmap", "nav_tab": "Skills View"},
        ])
        _s_total = len(_tour_steps) + 4
        _step_idx = _tour_step - 1
        if _step_idx < len(_tour_steps):
            _ts = _tour_steps[_step_idx]
            _sel = _ts.get("sel", "")
            _is_welcome = _ts.get("welcome", False)

            # Every step declares its own tab, so there is no positional
            # fallback left to misfire when the step list changes.
            if _ts.get("nav_tab"):
                st.session_state["dash_tab"] = _ts["nav_tab"]

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
            if _is_welcome:
                _tour_js = """<script>(function(){var P=window.parent,D=P.document;var old=D.getElementById('tour-spotlight-box');if(old)old.remove();var oldS=D.getElementById('tour-pos');if(oldS)oldS.remove();var sp=D.createElement('div');sp.id='tour-spotlight-box';sp.style.cssText='position:fixed;inset:0;z-index:100000;pointer-events:none;border:none;border-radius:0;box-shadow:0 0 0 9999px rgba(15,23,42,0.65);';D.body.appendChild(sp);P.scrollTo({top:0,behavior:'smooth'});function s(){var p=D.querySelector('.st-key-tour_popup');if(!p){setTimeout(s,100);return}var st=D.createElement('style');st.id='tour-pos';st.textContent='.st-key-tour_popup{left:50%!important;top:50%!important;transform:translate(-50%,-50%)!important;opacity:1!important;animation:_tFadeIn .4s cubic-bezier(.34,1.56,.64,1) both!important;}';D.head.appendChild(st)}setTimeout(s,200)})();</script>"""
            elif _js_sel:
                _tour_js = """<script>(function(){var P=window.parent,D=P.document,SEL='%s',PCLS='.st-key-tour_popup';var old=D.getElementById('tour-spotlight-box');if(old)old.remove();var oldS=D.getElementById('tour-pos');if(oldS)oldS.remove();var sp=D.createElement('div');sp.id='tour-spotlight-box';sp.style.cssText='position:fixed;left:0;top:0;width:0;height:0;z-index:100000;pointer-events:none;border:2px solid #6366F1;border-radius:12px;box-shadow:0 0 0 9999px rgba(15,23,42,0.65),0 0 30px rgba(99,102,241,0.25);transition:all 300ms cubic-bezier(0.4,0,0.2,1);opacity:0;';D.body.appendChild(sp);function waitEl(sel,cb){var el=D.querySelector(sel);if(el){cb(el);return}var obs=new MutationObserver(function(){el=D.querySelector(sel);if(el){obs.disconnect();cb(el)}});obs.observe(D.body,{childList:true,subtree:true});setTimeout(function(){obs.disconnect();if(!D.querySelector(sel))cb(null)},5000)}waitEl(SEL,function(el){if(!el){sp.style.cssText='position:fixed;inset:0;z-index:100000;pointer-events:none;border:none;border-radius:0;box-shadow:0 0 0 9999px rgba(15,23,42,0.65);opacity:1;';var fs=D.createElement('style');fs.id='tour-pos';fs.textContent=PCLS+'{left:50%%!important;top:50%%!important;transform:translate(-50%%,-50%%)!important;opacity:1!important;animation:_tFadeIn .4s cubic-bezier(.34,1.56,.64,1) both!important;}';D.head.appendChild(fs);return}var det=el.closest('details');if(det&&!det.open)det.open=true;el.scrollIntoView({behavior:'smooth',block:'center'});setTimeout(function(){var r=el.getBoundingClientRect(),pad=8;sp.style.left=(r.left-pad)+'px';sp.style.top=(r.top-pad)+'px';sp.style.width=(r.width+pad*2)+'px';sp.style.height=(r.height+pad*2)+'px';sp.style.opacity='1';posPopup(el)},600)});function posPopup(el){var popup=D.querySelector(PCLS);if(!popup){setTimeout(function(){posPopup(el)},100);return}var r=el.getBoundingClientRect(),vw=P.innerWidth,vh=P.innerHeight,pw=400,ph=popup.offsetHeight||380,gap=24,left,top;if(r.right+gap+pw<vw){left=r.right+gap;top=r.top}else if(r.left-gap-pw>0){left=r.left-gap-pw;top=r.top}else if(r.bottom+gap+ph<vh){left=Math.max(gap,r.left+(r.width-pw)/2);top=r.bottom+gap}else{left=Math.max(gap,r.left+(r.width-pw)/2);top=Math.max(gap,r.top-ph-gap)}left=Math.max(20,Math.min(left,vw-pw-20));top=Math.max(20,Math.min(top,vh-ph-20));var s=D.getElementById('tour-pos');if(s)s.remove();s=D.createElement('style');s.id='tour-pos';s.textContent=PCLS+'{left:'+left+'px!important;top:'+top+'px!important;opacity:1!important;animation:_tFadeIn .4s cubic-bezier(.34,1.56,.64,1) both!important;}';D.head.appendChild(s);function repos(){var nr=el.getBoundingClientRect(),pad=8;sp.style.left=(nr.left-pad)+'px';sp.style.top=(nr.top-pad)+'px';sp.style.width=(nr.width+pad*2)+'px';sp.style.height=(nr.height+pad*2)+'px';if(nr.right+gap+pw<vw){left=nr.right+gap;top=nr.top}else if(nr.left-gap-pw>0){left=nr.left-gap-pw;top=nr.top}else{left=Math.max(20,nr.left+(nr.width-pw)/2);top=nr.bottom+gap}left=Math.max(20,Math.min(left,vw-pw-20));top=Math.max(20,Math.min(top,vh-ph-20));s.textContent=PCLS+'{left:'+left+'px!important;top:'+top+'px!important;opacity:1!important;}'}P.addEventListener('scroll',repos,{passive:true});P.addEventListener('resize',repos,{passive:true})}})();</script>""" % _js_sel
            else:
                _tour_js = ""
            if _tour_js:
                st_components.html(_tour_js, height=0)

            if _is_welcome:
                _desc_html = """<div style="font-size:.85rem;color:#334155;line-height:1.65;">
                    Two halves: <b>My Desk</b> is the operational front door — what you
                    work on next and why. Everything after it is retrospective analytics
                    on workforce, team and skill performance.
                    <div style="margin-top:12px;font-size:.78rem;color:#64748B;">
                        <div style="margin-bottom:4px;">&#9201; Estimated time: ~2 minutes</div>
                        <div style="font-weight:600;margin-bottom:4px;">You will learn:</div>
                        <div>&#10003; My Desk — queue, next action, case workspace</div>
                        <div>&#10003; Shift handoff, SLA targets &amp; what changed</div>
                        <div>&#10003; Dashboard filters &amp; key indicators</div>
                        <div>&#10003; Team &amp; skill analytics, AI insights</div>
                    </div></div>"""
            else:
                _desc_html = '<div style="font-size:.85rem;color:#334155;line-height:1.65;">%s</div>' % _ts["desc"]

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
                                <div style="font-size:1.05rem;font-weight:800;color:#fff;margin-top:1px;">
                                    %s</div>
                            </div>
                        </div>
                        <div style="display:flex;align-items:center;gap:3px;">%s</div>
                    </div>
                    <div style="padding:18px 24px 8px;">%s</div>
                    <div style="padding:2px 24px 10px;">
                        <span style="font-size:.7rem;color:#94A3B8;font-weight:600;">Step %d of %d</span>
                    </div>
                </div>
                """ % (_ts["icon"], _ts["label"], _ts["title"], _dots, _desc_html, _tour_step, _s_total)), unsafe_allow_html=True)
                _tc1, _tc2, _tc3 = st.columns(3)
                with _tc1:
                    if _tour_step > 1:
                        if st.button("← Back", key="_tour_prev", use_container_width=True):
                            _prv = _tour_steps[_tour_step - 2]
                            st.session_state["dash_tab"] = _prv.get("nav_tab", "Associates")
                            st.session_state["selected_associate"] = None
                            st.session_state["_tour_step"] = _tour_step - 1
                            st.rerun()
                with _tc2:
                    _next_label = "Start Tour →" if _is_welcome else "Next →"
                    if st.button(_next_label, key="_tour_next", type="primary", use_container_width=True):
                        _nxt = _tour_step + 1
                        if _nxt > len(_tour_steps):
                            if not associates_df.empty:
                                st.session_state["selected_associate"] = associates_df.iloc[0]["associate_id"]
                            else:
                                st.session_state["_tour_step"] = 0
                                st.session_state["_tour_seen"] = True
                                st.rerun()
                        elif _tour_steps[_nxt - 1].get("nav_tab"):
                            st.session_state["dash_tab"] = _tour_steps[_nxt - 1]["nav_tab"]
                        st.session_state["_tour_step"] = _nxt
                        st.rerun()
                with _tc3:
                    if st.button("Skip Tour", key="_tour_skip", use_container_width=True):
                        st.session_state["_tour_step"] = 0
                        st.session_state["_tour_seen"] = True
                        st.session_state["selected_associate"] = None
                        st.session_state["dash_tab"] = "Associates"
                        st.rerun()
        elif _tour_step > len(_tour_steps):
            pass
    else:
        st_components.html("""<script>(function(){var D=window.parent.document;var b=D.getElementById('tour-spotlight-box');if(b)b.remove();var s=D.getElementById('tour-pos');if(s)s.remove();})()</script>""", height=0)

    # ── TAB LAYOUT (role-based) ──
    _dash_role = st.session_state.get("role", "associate")
    if _dash_role == "associate":
        _tab_labels = ["My Desk", "Associates", "Skills View"]
    elif _dash_role == "manager":
        _tab_labels = ["My Desk", "Associates", "My Team", "Team / SBR View", "Skills View"]
    else:
        _tab_labels = ["My Desk", "Associates", "Team / SBR View", "Skills View"]
    if st.session_state.get("dash_tab") not in _tab_labels:
        st.session_state.pop("dash_tab", None)
    _dash_active = st.segmented_control("", _tab_labels, default=_tab_labels[0], key="dash_tab")
    if not _dash_active:
        _dash_active = _tab_labels[0]

    # ═══════════════════════════ TAB 0: MY DESK ═══════════════════════════
    # Operational view — what this engineer should work on right now, as opposed
    # to the retrospective analytics in every other tab.
    if _dash_active == "My Desk":
        render_my_desk(
            cases_df, associates_df, skills_df, accounts_df,
            role=_dash_role,
            user_email=st.session_state.get("username", ""),
            display_name=st.session_state.get("display_name", ""),
            ai_fn=call_ai,
        )

    # ═══════════════════════════ TAB 1: ASSOCIATES ═══════════════════════════
    if _dash_active == "Associates":

        # ── Your Profile (associate role highlight) ──
        if _dash_role == "associate":
            _my_email = st.session_state.get("username", "")
            _my_row = assoc_stats[assoc_stats["email"].str.lower() == _my_email.lower()]
            if not _my_row.empty:
                _me = _my_row.iloc[0]
                _my_csat = f"{_me['avg_csat']:.1f}/5" if pd.notna(_me.get("avg_csat")) else "N/A"
                _my_perf = _me.get("perf", 0)
                _my_pclr = "#10B981" if _my_perf >= 75 else ("#F59E0B" if _my_perf >= 55 else "#EF4444")
                _my_skills = skills_df[skills_df["associate_id"] == _me["associate_id"]].sort_values("skill_rank")
                if not _my_skills.empty:
                    _my_pills = "".join(
                        f'<span style="background:{SKILL_COLORS[i % len(SKILL_COLORS)]};color:#fff;'
                        f'padding:3px 10px;border-radius:9999px;font-size:0.68rem;font-weight:600;">'
                        f'{r["skill_name"]}</span> '
                        for i, (_, r) in enumerate(_my_skills.head(5).iterrows())
                    )
                else:
                    _my_pills = '<span style="color:#94A3B8;font-size:0.78rem;">No skills extracted yet</span>'
                _my_certs = _me.get("certifications", "")
                _my_cert_val = _my_certs if pd.notna(_my_certs) and str(_my_certs).strip() else "None"
                st.markdown(_html(f"""<div style="background:linear-gradient(135deg,rgba(99,102,241,0.06),rgba(139,92,246,0.04));
                    border:1.5px solid rgba(99,102,241,0.18);border-radius:16px;padding:20px 24px;margin-bottom:16px;
                    animation:slideUp 0.4s ease both;">
                    <div style="display:flex;align-items:center;gap:14px;margin-bottom:14px;">
                        <div style="width:48px;height:48px;border-radius:14px;
                            background:linear-gradient(135deg,#6366F1,#A78BFA);
                            display:flex;align-items:center;justify-content:center;
                            color:#fff;font-weight:800;font-size:1.1rem;flex-shrink:0;">
                            {"".join(w[0] for w in _me["associate_name"].split()[:2]).upper()}</div>
                        <div>
                            <div style="font-weight:800;font-size:1.05rem;color:var(--text-color,{PF_TEXT});">
                                {_me['associate_name']} <span style="font-size:0.72rem;font-weight:600;color:#6366F1;">— Your Profile</span></div>
                            <div style="font-size:0.78rem;color:{PF_TEXT_SEC};">
                                {_me['associate_id']} · {_me['sbr']} · {_me['shift']} · Manager: {_me['manager_name']}</div>
                        </div>
                    </div>
                    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px;">
                        <div style="background:var(--secondary-background-color,{PF_SURFACE});border-radius:10px;padding:10px 18px;text-align:center;min-width:100px;">
                            <div style="font-size:1.15rem;font-weight:800;color:var(--text-color,{PF_TEXT});">{_me['total_cases']}</div>
                            <div style="font-size:0.68rem;color:{PF_TEXT_SEC};text-transform:uppercase;font-weight:600;">Cases</div></div>
                        <div style="background:var(--secondary-background-color,{PF_SURFACE});border-radius:10px;padding:10px 18px;text-align:center;min-width:100px;">
                            <div style="font-size:1.15rem;font-weight:800;color:var(--text-color,{PF_TEXT});">{_me['resolved']}</div>
                            <div style="font-size:0.68rem;color:{PF_TEXT_SEC};text-transform:uppercase;font-weight:600;">Resolved</div></div>
                        <div style="background:var(--secondary-background-color,{PF_SURFACE});border-radius:10px;padding:10px 18px;text-align:center;min-width:100px;">
                            <div style="font-size:1.15rem;font-weight:800;color:var(--text-color,{PF_TEXT});">{_my_csat}</div>
                            <div style="font-size:0.68rem;color:{PF_TEXT_SEC};text-transform:uppercase;font-weight:600;">CSAT</div></div>
                        <div style="background:var(--secondary-background-color,{PF_SURFACE});border-radius:10px;padding:10px 18px;text-align:center;min-width:100px;">
                            <div style="font-size:1.15rem;font-weight:800;color:{_my_pclr};">{_my_perf:.0f}/100</div>
                            <div style="font-size:0.68rem;color:{PF_TEXT_SEC};text-transform:uppercase;font-weight:600;">Performance</div></div>
                    </div>
                    <div style="font-size:0.72rem;color:{PF_TEXT_SEC};margin-bottom:4px;font-weight:600;">CERTIFICATIONS</div>
                    <div style="font-size:0.82rem;color:var(--text-color,{PF_TEXT});margin-bottom:10px;">{_my_cert_val}</div>
                    <div style="font-size:0.72rem;color:{PF_TEXT_SEC};margin-bottom:4px;font-weight:600;">TOP SKILLS</div>
                    <div style="display:flex;gap:6px;flex-wrap:wrap;">{_my_pills}</div>
                </div>"""), unsafe_allow_html=True)

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

        _n_res_cur = len(_cur[_cur["status"].isin(["Resolved", "Closed"])])
        _n_res_prev = len(_prev[_prev["status"].isin(["Resolved", "Closed"])])
        _esc_cur = int(_cur["escalated"].sum())
        _esc_prev = int(_prev["escalated"].sum())
        _csat_cur = _cur["csat_score"].mean()
        _csat_prev = _prev["csat_score"].mean()
        _ttr_cur = _cur["time_to_resolve_hours"].mean()
        _ttr_prev = _prev["time_to_resolve_hours"].mean()

        n_resolved = len(f_cases[f_cases["status"].isin(["Resolved", "Closed"])])
        avg_csat = f_cases["csat_score"].mean()
        avg_ttr = f_cases["time_to_resolve_hours"].mean()
        avg_perf = assoc_stats["perf"].mean() if len(assoc_stats) else 0
        _csat_d = f"{_csat_cur - _csat_prev:+.2f}" if pd.notna(_csat_cur) and pd.notna(_csat_prev) and _csat_cur != _csat_prev else None
        _ttr_d = f"{_ttr_cur - _ttr_prev:+.0f} hrs" if pd.notna(_ttr_cur) and pd.notna(_ttr_prev) and abs(_ttr_cur - _ttr_prev) > 0.5 else None

        _kpi_data = [
            ("Active Associates", f"{len(f_assoc):,}", None, "normal"),
            ("Cases Resolved", f"{n_resolved:,}", _delta_pct(_n_res_cur, _n_res_prev), "normal"),
            ("Avg CSAT Score", f"{avg_csat:.1f}/5" if pd.notna(avg_csat) else "N/A", _csat_d, "normal"),
            ("Avg Resolve Time", f"{avg_ttr:.0f} hrs" if pd.notna(avg_ttr) else "N/A", _ttr_d, "inverse"),
            ("Total Escalations", f"{int(f_cases['escalated'].sum()):,}", _delta_abs(_esc_cur, _esc_prev), "inverse"),
            ("Avg Performance", f"{avg_perf:.0f}/100", None, "normal"),
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
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        for col, (label, val, delta, dcolor) in zip([m1, m2, m3, m4, m5, m6], _kpi_data):
            with col:
                st.metric(label, val, delta=delta, delta_color=dcolor)
        _pin_cols = st.columns(6)
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
        _at_risk_assocs = assoc_stats[assoc_stats["perf"] < 40]
        if len(_at_risk_assocs) > 0:
            _anomalies.append(("at_risk", f"{len(_at_risk_assocs)} associate(s) have performance score below 40"))
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
                if _aid == "at_risk":
                    st.dataframe(
                        _at_risk_assocs[["associate_name", "sbr", "shift", "total_cases", "avg_csat", "perf"]].rename(
                            columns={"associate_name": "Name", "total_cases": "Cases", "avg_csat": "CSAT", "perf": "Perf"}
                        ).sort_values("Perf"),
                        use_container_width=True, hide_index=True, height=200)

        # ── Data Management (admin-only) ──
        if has_permission("data_ingest"):
            with st.expander("Data Management", expanded=False, icon=":material/swap_vert:"):
                _render_data_ingest(prefix="main_", assoc_stats_df=assoc_stats)

        # ── Top 3 Performers ──
        _top3 = assoc_stats.sort_values(["resolved", "total_cases"], ascending=False).head(3)
        if not _top3.empty:
            _medal_cfg = [
                {"icon": "🥇", "label": "1st", "grad": "linear-gradient(135deg, #FEF3C7 0%, #FDE68A 50%, #F59E0B 100%)",
                 "border": "#F59E0B", "glow": "rgba(245,158,11,0.25)", "badge_bg": "#FEF3C7", "badge_fg": "#92400E"},
                {"icon": "🥈", "label": "2nd", "grad": "linear-gradient(135deg, #F1F5F9 0%, #CBD5E1 50%, #94A3B8 100%)",
                 "border": "#94A3B8", "glow": "rgba(148,163,184,0.20)", "badge_bg": "#F1F5F9", "badge_fg": "#475569"},
                {"icon": "🥉", "label": "3rd", "grad": "linear-gradient(135deg, #FEF2E8 0%, #FDBA74 50%, #EA580C 100%)",
                 "border": "#EA580C", "glow": "rgba(234,88,12,0.18)", "badge_bg": "#FFF7ED", "badge_fg": "#9A3412"},
            ]
            st.markdown(_html(f'<div style="font-weight:700;font-size:0.85rem;color:var(--text-color,{PF_TEXT});'
                        f'margin:12px 0 6px;letter-spacing:0.03em;">Top Performers</div>'),
                        unsafe_allow_html=True)
            _t3_cols = st.columns(3)
            for ci, (_, tp) in enumerate(_top3.iterrows()):
                mc = _medal_cfg[ci]
                _csat_v = f"{tp['avg_csat']:.1f}" if pd.notna(tp.get("avg_csat")) else "N/A"
                _perf_v = int(tp["perf"])
                _res_v = int(tp["resolved"])
                _esc_v = int(tp["escalations"])
                _cases_v = int(tp["total_cases"])
                _initials = "".join(w[0] for w in str(tp["associate_name"]).split()[:2]).upper()
                _resolve_pct = int(_res_v / _cases_v * 100) if _cases_v > 0 else 0
                with _t3_cols[ci]:
                    st.markdown(_html(f"""<div style="
                        background:var(--secondary-background-color,{PF_SURFACE});
                        border:1.5px solid {mc['border']};border-radius:16px;
                        padding:20px 18px 16px;position:relative;overflow:hidden;
                        box-shadow:0 4px 20px {mc['glow']}, 0 1px 3px rgba(0,0,0,0.04);
                        animation:slideUp 0.5s ease both;animation-delay:{ci*0.1}s;
                        transition:transform 0.3s ease,box-shadow 0.3s ease;">
                        <div style="position:absolute;top:0;right:0;width:80px;height:80px;
                            background:{mc['grad']};opacity:0.12;border-radius:0 0 0 80px;"></div>
                        <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
                            <div style="width:44px;height:44px;border-radius:50%;
                                background:{mc['grad']};display:flex;align-items:center;
                                justify-content:center;font-size:1.3rem;flex-shrink:0;
                                box-shadow:0 2px 8px {mc['glow']};">
                                {mc['icon']}</div>
                            <div style="flex:1;min-width:0;">
                                <div style="font-weight:800;font-size:0.92rem;color:var(--text-color,{PF_TEXT});
                                    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                                    {tp['associate_name']}</div>
                                <div style="font-size:0.70rem;color:{PF_TEXT_SEC};margin-top:1px;">
                                    {tp['sbr']} · {tp['shift']}</div>
                            </div>
                            <div style="background:{mc['badge_bg']};color:{mc['badge_fg']};
                                font-size:0.62rem;font-weight:800;padding:3px 8px;
                                border-radius:20px;text-transform:uppercase;letter-spacing:0.05em;">
                                {mc['label']}</div>
                        </div>
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;">
                            <div style="background:var(--background-color,{PF_BG});border-radius:10px;padding:8px 10px;text-align:center;">
                                <div style="font-size:1.2rem;font-weight:800;color:var(--text-color,{PF_TEXT});">
                                    {_perf_v}<span style="font-size:0.6rem;color:{PF_TEXT_SEC};font-weight:500;">/100</span></div>
                                <div style="font-size:0.58rem;color:{PF_TEXT_SEC};text-transform:uppercase;letter-spacing:0.06em;margin-top:2px;">Performance</div>
                            </div>
                            <div style="background:var(--background-color,{PF_BG});border-radius:10px;padding:8px 10px;text-align:center;">
                                <div style="font-size:1.2rem;font-weight:800;color:var(--text-color,{PF_TEXT});">{_res_v}</div>
                                <div style="font-size:0.58rem;color:{PF_TEXT_SEC};text-transform:uppercase;letter-spacing:0.06em;margin-top:2px;">Resolved</div>
                            </div>
                            <div style="background:var(--background-color,{PF_BG});border-radius:10px;padding:8px 10px;text-align:center;">
                                <div style="font-size:1.2rem;font-weight:800;color:var(--text-color,{PF_TEXT});">{_csat_v}</div>
                                <div style="font-size:0.58rem;color:{PF_TEXT_SEC};text-transform:uppercase;letter-spacing:0.06em;margin-top:2px;">Avg CSAT</div>
                            </div>
                            <div style="background:var(--background-color,{PF_BG});border-radius:10px;padding:8px 10px;text-align:center;">
                                <div style="font-size:1.2rem;font-weight:800;color:var(--text-color,{PF_TEXT});">{_esc_v}</div>
                                <div style="font-size:0.58rem;color:{PF_TEXT_SEC};text-transform:uppercase;letter-spacing:0.06em;margin-top:2px;">Escalations</div>
                            </div>
                        </div>
                        <div style="margin-top:4px;">
                            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                                <span style="font-size:0.6rem;color:{PF_TEXT_SEC};font-weight:600;">Resolve Rate</span>
                                <span style="font-size:0.6rem;font-weight:700;color:var(--text-color,{PF_TEXT});">{_resolve_pct}%</span>
                            </div>
                            <div style="height:6px;background:var(--background-color,{PF_BG});border-radius:3px;overflow:hidden;">
                                <div style="height:100%;width:{_resolve_pct}%;background:{mc['grad']};
                                    border-radius:3px;transition:width 0.8s ease;"></div>
                            </div>
                        </div>
                    </div>"""), unsafe_allow_html=True)

        st.markdown('<div style="margin:20px 0;"></div>', unsafe_allow_html=True)

        # ── Save Filter Dialog (triggered from sidebar) ──
        if st.session_state.get("_show_save_filter"):
            _sf_name = st.text_input("Filter preset name:", key="_sf_name_input")
            _sf_c1, _sf_c2 = st.columns(2)
            with _sf_c1:
                if st.button("Save", key="_sf_save") and _sf_name:
                    _current_filters = {}
                    for fk in ["f_shifts", "f_managers", "f_sbrs", "f_accounts",
                               "f_products", "f_severity", "f_skills", "f_certs", "f_sort"]:
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

        # ── Risk Distribution Bar (interactive — click to filter) ──
        _healthy = len(assoc_stats[assoc_stats["perf"] >= 75])
        _attention = len(assoc_stats[(assoc_stats["perf"] >= 45) & (assoc_stats["perf"] < 75)])
        _at_risk = len(assoc_stats[assoc_stats["perf"] < 45])
        _risk_total = max(_healthy + _attention + _at_risk, 1)
        _h_pct = _healthy / _risk_total * 100
        _a_pct = _attention / _risk_total * 100
        _r_pct = _at_risk / _risk_total * 100

        _active_risk = st.session_state.get("_risk_filter")
        st.markdown(_html(f"""<div style="background:var(--secondary-background-color,{PF_SURFACE});
            border:1px solid var(--border-color,{PF_BORDER});border-radius:{PF_RADIUS};
            padding:16px 20px;margin:4px 0 8px;animation:slideUp 0.5s ease both;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                <span style="font-weight:700;font-size:0.88rem;color:var(--text-color,{PF_TEXT});">
                    Associate Risk Distribution</span>
                <span style="font-size:0.72rem;color:{PF_TEXT_SEC};">
                    Performance score: Healthy ≥75 · Attention 45-74 · At Risk &lt;45</span>
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
            _popup_labels = {"healthy": ("🟢 Healthy Associates", "perf ≥ 75"),
                             "attention": ("🟡 Needs Attention", "perf 45–74"),
                             "at_risk": ("🔴 At Risk Associates", "perf < 45")}
            _pl, _pd = _popup_labels[_risk_popup]
            if _risk_popup == "healthy":
                _popup_df = assoc_stats[assoc_stats["perf"] >= 75]
            elif _risk_popup == "attention":
                _popup_df = assoc_stats[(assoc_stats["perf"] >= 45) & (assoc_stats["perf"] < 75)]
            else:
                _popup_df = assoc_stats[assoc_stats["perf"] < 45]
            _popup_df = _popup_df.sort_values("perf", ascending=(_risk_popup == "at_risk"))

            with st.expander(f"{_pl} — {len(_popup_df)} associates ({_pd})", expanded=True):
                if _popup_df.empty:
                    st.info("No associates in this category.")
                else:
                    _show_df = _popup_df[["associate_name", "sbr", "shift", "total_cases",
                                          "resolved", "escalations", "avg_csat", "perf"]].copy()
                    _show_df.columns = ["Name", "SBR Team", "Shift", "Cases",
                                        "Resolved", "Escalations", "Avg CSAT", "Performance"]
                    _show_df["Avg CSAT"] = _show_df["Avg CSAT"].round(1)
                    _show_df["Performance"] = _show_df["Performance"].round(0).astype(int)
                    st.dataframe(_show_df, use_container_width=True, hide_index=True, height=320)
                if st.button("Close", key="_risk_popup_close"):
                    del st.session_state["_risk_popup"]
                    st.rerun()

        _view = assoc_stats

        # ── Bookmarks Section ──
        _bookmarks = st.session_state.get("bookmarks", [])
        if _bookmarks and not st.session_state.get("compare_toggle"):
            _bk_assocs = _view[_view["associate_id"].isin(_bookmarks)]
            if not _bk_assocs.empty:
                st.markdown(_html(f'<div style="font-weight:700;font-size:0.92rem;color:var(--text-color,{PF_TEXT});'
                            f'margin:8px 0 6px;animation:fadeIn 0.3s ease both;">'
                            f'⭐ Favorites ({len(_bk_assocs)})</div>'), unsafe_allow_html=True)
                _bk_cols = st.columns(min(len(_bk_assocs), 4))
                for bi, (_, ba) in enumerate(_bk_assocs.iterrows()):
                    with _bk_cols[bi % len(_bk_cols)]:
                        _bc = f"{ba['avg_csat']:.1f}" if pd.notna(ba.get("avg_csat")) else "N/A"
                        st.markdown(_html(f"""<div style="background:var(--secondary-background-color,{PF_SURFACE});
                            border:1px solid rgba(251,191,36,0.3);border-radius:{PF_RADIUS};
                            padding:10px 14px;animation:slideUp 0.4s ease both;cursor:pointer;">
                            <div style="display:flex;align-items:center;gap:8px;">
                                <span style="font-size:1rem;">⭐</span>
                                <div style="flex:1;min-width:0;">
                                    <div style="font-weight:700;font-size:0.82rem;color:var(--text-color,{PF_TEXT});
                                        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{ba['associate_name']}</div>
                                    <div style="font-size:0.66rem;color:{PF_TEXT_SEC};">{ba['sbr']} · CSAT {_bc}</div>
                                </div>
                            </div>
                        </div>"""), unsafe_allow_html=True)
                        _fv_left, _fv_right = st.columns(2)
                        with _fv_left:
                            if st.button("View", key=f"bk_v_{ba['associate_id']}", use_container_width=True):
                                st.session_state.selected_associate = ba["associate_id"]
                                st.session_state.ai_insight = None
                                st.session_state.pop("_scorecard_ai", None)
                                st.session_state.pop("det_tab", None)
                                st.query_params["view"] = str(ba["associate_id"])
                                st.rerun()
                        with _fv_right:
                            if st.button("Remove", key=f"bk_rm_{ba['associate_id']}", use_container_width=True):
                                st.session_state["bookmarks"] = [b for b in _bookmarks if b != ba["associate_id"]]
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
                if len(f_cases) > 0:
                    cases_with_shift = f_cases.merge(
                        associates_df[["associate_name", "shift"]], left_on="case_owner",
                        right_on="associate_name", how="left"
                    )
                    cases_with_sbr = f_cases.merge(
                        associates_df[["associate_name", "sbr"]].rename(columns={"sbr": "assoc_sbr"}),
                        left_on="case_owner", right_on="associate_name", how="left"
                    )
    
                    col_left, col_right = st.columns(2)
    
                    # ── LEFT: Breakdown card (toggle Geo/Shift ↔ Severity) ──
                    with col_left:
                        is_sev = st.session_state.get("ov_left_toggle", False)
                        toggle_label = "Switch to Geo / Shift" if is_sev else "Switch to Severity"
                        show_sev = st.toggle(toggle_label, value=False, key="ov_left_toggle")
                        if show_sev:
                            left_title = "Cases by Severity Level"
                            left_df = f_cases["severity"].value_counts().reset_index()
                            left_df.columns = ["Category", "Cases"]
                            left_cmap = SEVERITY_COLORS
                            left_col_src = "severity"
                        else:
                            left_title = "Cases by Geo / Shift"
                            left_df = cases_with_shift["shift"].value_counts().reset_index()
                            left_df.columns = ["Category", "Cases"]
                            left_cmap = SHIFT_COLORS
                            left_col_src = "shift"
    
                        left_total = int(left_df["Cases"].sum()) if len(left_df) else 0
    
                        bar_segs = ""
                        for _, r in left_df.iterrows():
                            pct = r["Cases"] / left_total * 100 if left_total else 0
                            clr = left_cmap.get(r["Category"], "#94A3B8")
                            bar_segs += f'<div style="width:{pct}%;height:100%;background:{clr};transition:width 0.6s ease;" title="{r["Category"]}: {r["Cases"]}"></div>'
    
                        rows_html = ""
                        for _, r in left_df.iterrows():
                            pct = r["Cases"] / left_total * 100 if left_total else 0
                            clr = left_cmap.get(r["Category"], "#94A3B8")
                            cat_name = r["Category"]
                            rows_html += f'''<div class="brkdn-row">
                                <div style="display:flex;align-items:center;gap:8px;flex:1;min-width:0;">
                                    <span style="width:10px;height:10px;border-radius:50%;background:{clr};flex-shrink:0;"></span>
                                    <span style="font-size:0.82rem;color:var(--text-color,{PF_TEXT});white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{cat_name}</span>
                                </div>
                                <div style="display:flex;align-items:center;gap:12px;">
                                    <span style="font-size:0.82rem;font-weight:600;color:var(--text-color,{PF_TEXT});">{int(r["Cases"])}</span>
                                    <span style="font-size:0.72rem;color:{PF_TEXT_SEC};min-width:38px;text-align:right;">{pct:.1f}%</span>
                                </div>
                            </div>'''
    
                        st.markdown(_html(f'''<div style="background:var(--secondary-background-color,{PF_SURFACE});border:1px solid var(--border-color,{PF_BORDER});border-radius:16px;padding:20px 22px;animation:slideUp 0.5s ease both;">
                            <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:16px;">
                                <span style="font-size:0.92rem;font-weight:700;color:var(--text-color,{PF_TEXT});">{left_title}</span>
                                <span style="font-size:1.4rem;font-weight:800;color:var(--text-color,{PF_TEXT});">{left_total:,}</span>
                            </div>
                            <div style="display:flex;height:10px;border-radius:99px;overflow:hidden;background:#E2E8F0;margin-bottom:20px;">{bar_segs}</div>
                            <div style="display:flex;flex-direction:column;gap:2px;">{rows_html}</div>
                        </div>'''), unsafe_allow_html=True)
    
                        drill_show = DRILL_COLS
    
                        btn_cols = st.columns(len(left_df))
                        for i, (_, r) in enumerate(left_df.iterrows()):
                            clr = left_cmap.get(r["Category"], "#94A3B8")
                            with btn_cols[i]:
                                if st.button(f"{r['Category']}", key=f"brkdn_{left_col_src}_{r['Category']}",
                                             use_container_width=True):
                                    breakdown_popup(r["Category"], left_col_src, clr)
    
                    # ── RIGHT: Bar chart (segmented SBR Team ↔ Product) ──
                    with col_right:
                        right_dim = st.segmented_control("Ranked by", ["SBR Team", "Product"],
                                                          default="SBR Team", key="ov_right_seg")
                        if not right_dim:
                            right_dim = "SBR Team"
    
                        if right_dim == "SBR Team":
                            right_title = "Top SBR Teams by Case Volume"
                            right_df = cases_with_sbr["assoc_sbr"].value_counts().head(8).reset_index()
                            right_df.columns = ["Category", "Cases"]
                            right_col_src = "assoc_sbr"
                            right_colors = [GRADIENT_PAIRS[i % len(GRADIENT_PAIRS)][0] for i in range(len(right_df))]
                        else:
                            right_title = "Top Products by Case Volume"
                            right_df = f_cases["product_name"].value_counts().head(10).reset_index()
                            right_df.columns = ["Category", "Cases"]
                            right_col_src = "product_name"
                            right_colors = [GRADIENT_PAIRS[i % len(GRADIENT_PAIRS)][0] for i in range(len(right_df))]
    
                        fig_right = go.Figure(go.Bar(
                            x=right_df["Cases"], y=right_df["Category"], orientation="h",
                            marker=dict(color=right_colors, line=dict(width=0)),
                            text=right_df["Cases"], textposition="outside",
                            textfont=dict(color=CHART_FONT, size=12),
                        ))
                        _right_max = int(right_df["Cases"].max()) if len(right_df) else 1
                        _styled_layout(fig_right, height=max(320, len(right_df) * 40), yint=False, xint=True)
                        fig_right.update_layout(
                            title=dict(text=right_title, font=dict(color=CHART_FONT, size=14), x=0.5),
                            yaxis=dict(autorange="reversed", title=right_dim),
                            xaxis=dict(title="No. of Cases", dtick=max(1, _right_max // 6)),
                            hovermode="closest", clickmode="event+select",
                        )
                        right_evt = st.plotly_chart(fig_right, use_container_width=True,
                                                    key="ov_bar", on_select="rerun",
                                                    selection_mode=("points",))
    
                    sel_right = None
                    if right_evt and right_evt.selection:
                        pts = right_evt.selection.get("points", getattr(right_evt.selection, "points", []))
                        if pts:
                            p = pts[0]
                            if isinstance(p, dict):
                                sel_right = p.get("y") or p.get("label")
                            else:
                                sel_right = getattr(p, "y", None) or getattr(p, "label", None)
                        if not sel_right:
                            idxs = right_evt.selection.get("point_indices", getattr(right_evt.selection, "point_indices", []))
                            if idxs and idxs[0] < len(right_df):
                                sel_right = right_df.iloc[idxs[0]]["Category"]
                    if sel_right:
                        if right_dim == "SBR Team":
                            drill = cases_with_sbr[cases_with_sbr["assoc_sbr"] == sel_right]
                        else:
                            drill = f_cases[f_cases[right_col_src] == sel_right]
                        st.markdown(f"### {sel_right} — {len(drill)} Cases")
                        st.dataframe(_rename_case_cols(drill[drill_show].sort_values("creation_date", ascending=False)),
                                     use_container_width=True, height=300, hide_index=True)
    
                # ── Shift Insights ──
                st.subheader("Shift Insights")
                shift_stats = f_assoc.groupby("shift").agg(
                    associates=("associate_id", "count"),
                ).reset_index()
                if "cases_with_shift" not in locals():
                    cases_with_shift = f_cases.merge(
                        associates_df[["associate_name", "shift"]], left_on="case_owner",
                        right_on="associate_name", how="left"
                    )
                for _, sr in shift_stats.iterrows():
                    s_cases = cases_with_shift[cases_with_shift["shift"] == sr["shift"]]
                    shift_stats.loc[shift_stats["shift"] == sr["shift"], "cases"] = len(s_cases)
                    shift_stats.loc[shift_stats["shift"] == sr["shift"], "resolved"] = len(
                        s_cases[s_cases["status"].isin(["Resolved", "Closed"])])
                    shift_stats.loc[shift_stats["shift"] == sr["shift"], "avg_csat"] = round(
                        s_cases["csat_score"].mean(), 2) if len(s_cases) else 0
                    shift_stats.loc[shift_stats["shift"] == sr["shift"], "escalations"] = int(
                        s_cases["escalated"].sum())
                for c in ["cases", "resolved", "escalations"]:
                    shift_stats[c] = shift_stats[c].astype(int)
    
                _si_cols = st.columns(len(shift_stats))
                for i, (_, sr) in enumerate(shift_stats.iterrows()):
                    clr = SHIFT_COLORS.get(sr["shift"], "#94A3B8")
                    res_pct = sr["resolved"] / sr["cases"] * 100 if sr["cases"] else 0
                    with _si_cols[i]:
                        st.markdown(_html(f"""<div style="background:var(--secondary-background-color,{PF_SURFACE});border:1px solid var(--border-color,{PF_BORDER});
                            border-radius:{PF_RADIUS};padding:16px;border-top:3px solid {clr};
                            animation:waterFlow 0.6s ease both;">
                            <div style="font-weight:700;color:var(--text-color,{PF_TEXT});font-size:0.95rem;margin-bottom:8px;">
                                {sr['shift']}</div>
                            <div style="font-size:0.78rem;color:{PF_TEXT_SEC};line-height:1.8;">
                                Associates: <b>{sr['associates']}</b><br>
                                Cases: <b>{int(sr['cases'])}</b><br>
                                Resolved: <b>{int(sr['resolved'])} ({res_pct:.0f}%)</b><br>
                                Escalations: <b>{int(sr['escalations'])}</b><br>
                                Avg CSAT: <b>{sr['avg_csat']:.2f}/5</b>
                            </div>
                        </div>"""), unsafe_allow_html=True)
    
                _si_btn_col, _si_close_col = st.columns([1, 5])
                with _si_btn_col:
                    if st.button("Generate Shift Insights", key="gen_shift_insights", type="primary"):
                        shift_ctx = "\n".join(
                            f"  {r['shift']}: {r['associates']} associates, {int(r['cases'])} cases, "
                            f"{int(r['resolved'])} resolved ({r['resolved']/r['cases']*100 if r['cases'] else 0:.0f}%), "
                            f"{int(r['escalations'])} escalations, avg CSAT {r['avg_csat']:.2f}"
                            for _, r in shift_stats.iterrows()
                        )
                        msgs = [
                            {"role": "system", "content":
                                "You are a Red Hat support operations analyst. Analyze the shift/geo distribution "
                                "(APAC, EMEA, NASA = Americas). For each shift, assess: workload per associate, "
                                "resolution rate, CSAT quality, and escalation rate. Identify which shift is "
                                "over/under-loaded, which has best/worst CSAT, and give 2-3 specific recommendations "
                                "(e.g., 'Move 2 associates from EMEA to APAC to balance the 15 cases/person gap'). "
                                "Use **bold** for key numbers. 3-5 bullet points max."},
                            {"role": "user", "content":
                                f"Analyze shift performance:\n{shift_ctx}\n\n"
                                f"Total associates: {len(f_assoc)}, Total cases: {len(f_cases)}"},
                        ]
                        with st.spinner("Analyzing shifts..."):
                            reply = call_ai(msgs, max_tokens=400)
                        if reply is None:
                            best = shift_stats.loc[shift_stats["avg_csat"].idxmax()]
                            busiest = shift_stats.loc[shift_stats["cases"].astype(int).idxmax()]
                            worst = shift_stats.loc[shift_stats["avg_csat"].idxmin()]
                            reply = (
                                f"**Shift Performance Summary**\n\n"
                                f"- **{busiest['shift']}** handles the most cases ({int(busiest['cases'])}), "
                                f"indicating highest workload.\n"
                                f"- **{best['shift']}** has the best CSAT ({best['avg_csat']:.2f}/5).\n"
                                f"- Across all shifts, {len(f_assoc)} associates handle {len(f_cases)} total cases.\n\n"
                                f"**Recommendations:**\n"
                                f"- Consider rebalancing workload from **{busiest['shift']}** if per-associate case "
                                f"count exceeds team average.\n"
                                f"- Review **{worst['shift']}** practices (CSAT {worst['avg_csat']:.2f}/5) — "
                                f"adopt best practices from **{best['shift']}** team."
                            )
                        st.session_state["_shift_insight_reply"] = reply
    
                if st.session_state.get("_shift_insight_reply"):
                    st.info(st.session_state["_shift_insight_reply"])
                    if st.button("✕ Close", key="close_shift_insights"):
                        del st.session_state["_shift_insight_reply"]
                        st.rerun()
    
                if st.button("✕ Close Analytics", key="_close_analytics", use_container_width=True):
                    st.session_state["_analytics_closed"] = True
                    st.rerun()

        st.markdown("---")

        if st.session_state.pop("_pending_compare", False):
            st.session_state["compare_toggle"] = True
            st.session_state["bulk_toggle"] = False
            st.session_state["_bulk_ids"] = []

        ov_left, ov_mid, ov_bulk, ov_right = st.columns([2, 1, 1, 1])
        with ov_left:
            st.subheader("Associates Overview")
        with ov_mid:
            _cmp_on = st.toggle("Compare Mode", key="compare_toggle",
                      help="Select 2-5 associates below, then compare side-by-side")
            if _cmp_on and st.session_state.get("bulk_toggle"):
                st.session_state["bulk_toggle"] = False
                st.session_state["_bulk_ids"] = []
                st.rerun()
        with ov_bulk:
            _blk_on = st.toggle("Bulk Select", key="bulk_toggle",
                      help="Select multiple associates for batch export or compare")
            if _blk_on and st.session_state.get("compare_toggle"):
                st.session_state["compare_toggle"] = False
                st.session_state["compare_ids"] = []
                st.rerun()
        with ov_right:
            st.text_input("Search", placeholder="Search by name or email…",
                          key="main_search", label_visibility="collapsed")

        # ── Compare Mode View ──
        if st.session_state.get("compare_toggle"):
            _cmp_ids = st.session_state.get("compare_ids", [])
            if len(_cmp_ids) < 2:
                st.info("Select 2-5 associates using the checkboxes on cards below to compare them side-by-side.")
            else:
                _cmp_ids = _cmp_ids[:5]
                _cmp_data = _view[_view["associate_id"].isin(_cmp_ids)]
                if len(_cmp_data) >= 2:
                    st.markdown(_html(f'<div style="font-weight:700;font-size:0.95rem;color:var(--text-color,{PF_TEXT});'
                                f'margin:8px 0 6px;">Compare Associates ({len(_cmp_data)})</div>'),
                                unsafe_allow_html=True)
                    _cmp_cols = st.columns(len(_cmp_data))
                    for ci, (_, cr) in enumerate(_cmp_data.iterrows()):
                        with _cmp_cols[ci]:
                            _cc = f"{cr['avg_csat']:.1f}" if pd.notna(cr.get("avg_csat")) else "N/A"
                            _clr = GRADIENT_PAIRS[ci % len(GRADIENT_PAIRS)][0]
                            st.markdown(_html(f"""<div style="background:var(--secondary-background-color,{PF_SURFACE});
                                border:2px solid {_clr};border-radius:{PF_RADIUS};padding:14px;
                                text-align:center;animation:slideUp 0.4s ease both;">
                                <div style="font-weight:700;color:var(--text-color,{PF_TEXT});font-size:0.92rem;">{cr['associate_name']}</div>
                                <div style="font-size:0.70rem;color:{PF_TEXT_SEC};margin:4px 0 10px;">{cr['sbr']} · {cr['shift']}</div>
                                <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                                    <div style="background:{PF_BG};border-radius:8px;padding:6px;">
                                        <div style="font-size:0.62rem;color:{PF_TEXT_SEC};text-transform:uppercase;">Cases</div>
                                        <div style="font-size:1rem;font-weight:800;color:var(--text-color,{PF_TEXT});">{cr['total_cases']}</div>
                                    </div>
                                    <div style="background:{PF_BG};border-radius:8px;padding:6px;">
                                        <div style="font-size:0.62rem;color:{PF_TEXT_SEC};text-transform:uppercase;">Resolved</div>
                                        <div style="font-size:1rem;font-weight:800;color:var(--text-color,{PF_TEXT});">{cr['resolved']}</div>
                                    </div>
                                    <div style="background:{PF_BG};border-radius:8px;padding:6px;">
                                        <div style="font-size:0.62rem;color:{PF_TEXT_SEC};text-transform:uppercase;">CSAT</div>
                                        <div style="font-size:1rem;font-weight:800;color:var(--text-color,{PF_TEXT});">{_cc}</div>
                                    </div>
                                    <div style="background:{PF_BG};border-radius:8px;padding:6px;">
                                        <div style="font-size:0.62rem;color:{PF_TEXT_SEC};text-transform:uppercase;">Perf</div>
                                        <div style="font-size:1rem;font-weight:800;color:var(--text-color,{PF_TEXT});">{cr['perf']:.0f}</div>
                                    </div>
                                </div>
                            </div>"""), unsafe_allow_html=True)

                    _cmp_fig = go.Figure()
                    for ci, (_, cr) in enumerate(_cmp_data.iterrows()):
                        _clr = GRADIENT_PAIRS[ci % len(GRADIENT_PAIRS)][0]
                        _cmp_fig.add_trace(go.Bar(
                            x=["Cases", "Resolved", "Escalations", "Performance"],
                            y=[cr["total_cases"], cr["resolved"], cr["escalations"], cr["perf"]],
                            name=cr["associate_name"], marker=dict(color=_clr),
                            text=[cr["total_cases"], cr["resolved"], cr["escalations"], f"{cr['perf']:.0f}"],
                            textposition="outside",
                        ))
                    _styled_layout(_cmp_fig, height=320)
                    _cmp_fig.update_layout(barmode="group", xaxis_title="", yaxis_title="Count",
                                           legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center"))
                    st.plotly_chart(_cmp_fig, use_container_width=True, key="compare_chart")

                    # ── Comparison Analysis ──
                    _cmp_sorted_perf = _cmp_data.sort_values("perf", ascending=False)
                    _analysis_items = []

                    _best_p = _cmp_sorted_perf.iloc[0]
                    _worst_p = _cmp_sorted_perf.iloc[-1]
                    _perf_gap = (_best_p.get("perf", 0) or 0) - (_worst_p.get("perf", 0) or 0)
                    if _perf_gap > 0:
                        _analysis_items.append(
                            f"<b>{_best_p['associate_name']}</b> leads with performance score "
                            f"<b>{_perf_gap:.0f} points higher</b> than <b>{_worst_p['associate_name']}</b>"
                        )

                    _res_rates = []
                    for _, _rr in _cmp_data.iterrows():
                        _rr_rate = _rr["resolved"] / max(_rr["total_cases"], 1) * 100
                        _res_rates.append((_rr["associate_name"], _rr_rate))
                    _res_rates.sort(key=lambda x: x[1], reverse=True)
                    if len(_res_rates) >= 2 and abs(_res_rates[0][1] - _res_rates[-1][1]) > 10:
                        _analysis_items.append(
                            f"Resolution rate gap — <b>{_res_rates[0][0]}</b>: {_res_rates[0][1]:.0f}% "
                            f"vs <b>{_res_rates[-1][0]}</b>: {_res_rates[-1][1]:.0f}%"
                        )

                    for _, _rr in _cmp_data.iterrows():
                        _rr_esc = _rr["escalations"] / max(_rr["total_cases"], 1) * 100
                        if _rr_esc > 15:
                            _analysis_items.append(
                                f"<b>{_rr['associate_name']}</b> has <b>{_rr_esc:.0f}% escalation rate</b> — needs review"
                            )

                    _csat_parts = []
                    for _, _rr in _cmp_data.iterrows():
                        if pd.notna(_rr.get("avg_csat")) and _rr["avg_csat"] > 0:
                            _csat_parts.append((_rr["associate_name"], _rr["avg_csat"]))
                    if len(_csat_parts) >= 2:
                        _csat_parts.sort(key=lambda x: x[1], reverse=True)
                        _analysis_items.append(
                            f"CSAT — <b>{_csat_parts[0][0]}</b>: {_csat_parts[0][1]:.1f}/5 "
                            f"vs <b>{_csat_parts[-1][0]}</b>: {_csat_parts[-1][1]:.1f}/5"
                        )

                    _skill_overlap = {}
                    for _, _rr in _cmp_data.iterrows():
                        _a_sk = skills_df[skills_df["associate_id"] == _rr["associate_id"]]["skill_name"].tolist()
                        _skill_overlap[_rr["associate_name"]] = set(_a_sk)
                    _all_sk_names = list(_skill_overlap.keys())
                    if len(_all_sk_names) >= 2:
                        _common_sk = set.intersection(*_skill_overlap.values())
                        if _common_sk:
                            _analysis_items.append(
                                f"Shared skills: <b>{', '.join(sorted(_common_sk)[:4])}</b>"
                                + (f" (+{len(_common_sk)-4} more)" if len(_common_sk) > 4 else "")
                            )

                    _rec_items = []
                    if _perf_gap > 15:
                        _rec_items.append(
                            f"<b>Recommendation:</b> Pair <b>{_worst_p['associate_name']}</b> with "
                            f"<b>{_best_p['associate_name']}</b> for peer mentoring to close the {_perf_gap:.0f}-point gap"
                        )
                    if _res_rates and _res_rates[-1][1] < 60:
                        _rec_items.append(
                            f"<b>Action:</b> <b>{_res_rates[-1][0]}</b> has {_res_rates[-1][1]:.0f}% resolution rate — "
                            f"audit open cases for blockers or reassignment"
                        )
                    _analysis_items.extend(_rec_items)

                    if not _analysis_items:
                        _analysis_items.append("Associates are performing similarly across all metrics")

                    _analysis_html = "".join(
                        f'<div style="display:flex;align-items:flex-start;gap:8px;padding:6px 0;'
                        f'border-bottom:1px dashed {PF_BORDER};">'
                        f'<span style="color:#6366F1;font-size:0.85rem;margin-top:1px;">&#9679;</span>'
                        f'<span style="font-size:0.82rem;color:var(--text-color,{PF_TEXT});line-height:1.5;">{item}</span></div>'
                        for item in _analysis_items
                    )
                    st.markdown(_html(f"""<div style="background:var(--secondary-background-color,{PF_SURFACE});
                        border:1px solid var(--border-color,{PF_BORDER});border-radius:{PF_RADIUS};
                        padding:16px 18px;margin:12px 0;">
                        <div style="font-weight:700;font-size:0.85rem;color:var(--text-color,{PF_TEXT});margin-bottom:10px;
                            display:flex;align-items:center;gap:8px;">
                            <span style="font-size:1rem;">&#128202;</span> Comparison Analysis
                        </div>
                        {_analysis_html}
                    </div>"""), unsafe_allow_html=True)

                    if st.button("Clear Comparison", key="_cmp_clear", use_container_width=True):
                        st.session_state["compare_ids"] = []
                        st.rerun()

        total = len(_view)
        total_pages = max(1, -(-total // CARDS_PER_PAGE))
        if st.session_state.page >= total_pages:
            st.session_state.page = 0

        pg = st.session_state.page
        start = pg * CARDS_PER_PAGE
        end = min(start + CARDS_PER_PAGE, total)
        page_data = _view.iloc[start:end]

        st.caption(f"Showing {start+1}–{end} of {total} associates  ·  Page {pg+1} of {total_pages}")

        if st.session_state.get("bulk_toggle"):
            _bk_sel, _bk_all, _bk_clr = st.columns([4, 1, 1])
            with _bk_sel:
                _n_sel = len(st.session_state.get("_bulk_ids", []))
                st.markdown(_html(f'<div style="font-size:0.85rem;color:{PF_TEXT_SEC};padding:6px 0;">'
                            f'<b>{_n_sel}</b> associate{"s" if _n_sel != 1 else ""} selected</div>'),
                            unsafe_allow_html=True)
            with _bk_all:
                if st.button("Select All", key="_bulk_all", use_container_width=True):
                    st.session_state["_bulk_ids"] = _view["associate_id"].tolist()
                    st.rerun()
            with _bk_clr:
                if st.button("Clear All", key="_bulk_clr", use_container_width=True):
                    st.session_state["_bulk_ids"] = []
                    st.rerun()

            # ── Bulk Action Bar (under selection controls) ──
            _blk_ids = st.session_state.get("_bulk_ids", [])
            if _blk_ids:
                st.markdown(_html(f"""<div style="background:linear-gradient(135deg,#6366F1,#818CF8);
                    border-radius:12px;padding:12px 20px;margin:12px 0;
                    display:flex;align-items:center;justify-content:space-between;
                    box-shadow:0 8px 24px rgba(99,102,241,0.25);">
                    <span style="color:#fff;font-weight:700;font-size:0.9rem;">
                        {len(_blk_ids)} associate{"s" if len(_blk_ids) != 1 else ""} selected
                    </span>
                </div>"""), unsafe_allow_html=True)
                _ba1, _ba2, _ba3 = st.columns(3)
                with _ba1:
                    _bulk_export = assoc_stats[assoc_stats["associate_id"].isin(_blk_ids)]
                    st.download_button("Export CSV", _bulk_export.to_csv(index=False),
                                       "bulk_associates.csv", "text/csv",
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

        # Card gallery — 3 columns
        _page_ids = page_data["associate_id"].tolist()
        _page_skills = skills_df[skills_df["associate_id"].isin(_page_ids)].sort_values("skill_rank")
        _skills_lookup = {aid: grp.head(5) for aid, grp in _page_skills.groupby("associate_id")}
        for i in range(0, len(page_data), 3):
            chunk = page_data.iloc[i:i+3]
            cols = st.columns(3)
            for idx, (_, row) in enumerate(chunk.iterrows()):
                with cols[idx]:
                    csat_s = f"{row['avg_csat']:.1f}" if pd.notna(row.get("avg_csat")) else "N/A"
                    a_skills = _skills_lookup.get(row["associate_id"], pd.DataFrame())
                    pills = "".join(
                        f'<span class="skill-pill" style="background:{SKILL_COLORS[si % len(SKILL_COLORS)]};">'
                        f'{sr["skill_name"]}</span>'
                        for si, (_, sr) in enumerate(a_skills.head(5).iterrows())
                    )
                    initials = row['associate_name'].split()[0][0] if row['associate_name'] else "?"
                    _perf = row['perf']
                    _avclr = "#6366F1" if _perf >= 75 else ("#F59E0B" if _perf >= 55 else ("#FB923C" if _perf >= 35 else "#EF4444"))
                    _bar_clr = "#10B981" if _perf >= 75 else ("#F59E0B" if _perf >= 55 else ("#FB923C" if _perf >= 35 else "#EF4444"))
                    esc_n = row['escalations']
                    esc_cls = "assoc-metric-val warn" if esc_n > 0 else "assoc-metric-val"
                    st.markdown(_html(f"""<div class="assoc-card" style="border-top:3px solid {_bar_clr};">
                        <div class="assoc-card-top">
                            <div class="assoc-avatar" style="background:linear-gradient(135deg,{_avclr},{_avclr}bb);">{initials}</div>
                            <div class="assoc-card-top-left">
                                <div class="assoc-name">{row['associate_name']}</div>
                                <div class="assoc-meta">{row['associate_id']} &middot; {row['sbr']} &middot; {row['shift']}</div>
                                <div class="assoc-perf-line">{perf_badge(row['perf'])} {level_html(row['skill_level'])}</div>
                            </div>
                        </div>
                        <div class="assoc-card-body">
                            <div class="assoc-metrics">
                                <div class="assoc-metric"><div class="assoc-metric-val">{row['total_cases']}</div><div class="assoc-metric-lbl">Cases</div></div>
                                <div class="assoc-metric"><div class="assoc-metric-val">{row['resolved']}</div><div class="assoc-metric-lbl">Resolved</div></div>
                                <div class="assoc-metric"><div class="{esc_cls}">{esc_n}</div><div class="assoc-metric-lbl">Escalated</div></div>
                                <div class="assoc-metric"><div class="assoc-metric-val">{csat_s}</div><div class="assoc-metric-lbl">CSAT</div></div>
                            </div>
                            <div class="assoc-perf-bar">
                                <span class="assoc-perf-lbl">Performance</span>
                                <div class="assoc-perf-track"><div class="assoc-perf-fill" style="width:{min(_perf,100):.0f}%;background:{_bar_clr};"></div></div>
                                <span class="assoc-perf-score" style="color:{_bar_clr};">{_perf:.0f}</span>
                            </div>
                            <div class="assoc-card-info">Manager: <strong>{row['manager_name']}</strong></div>
                            <div class="assoc-card-footer">
                                <div class="assoc-card-footer-left">{pills}</div>
                            </div>
                        </div>
                    </div>"""), unsafe_allow_html=True)
                    _btn_c1, _btn_c2 = st.columns([3, 1])
                    with _btn_c1:
                        if st.button("View Details", key=f"v_{row['associate_id']}", use_container_width=True):
                            st.session_state.selected_associate = row["associate_id"]
                            st.session_state.ai_insight = None
                            st.session_state.pop("_scorecard_ai", None)
                            st.session_state.pop("det_tab", None)
                            st.query_params["view"] = str(row["associate_id"])
                            st.rerun()
                    with _btn_c2:
                        _is_bk = row["associate_id"] in st.session_state.get("bookmarks", [])
                        _bk_label = "⭐" if _is_bk else "☆"
                        if st.button(_bk_label, key=f"bk_{row['associate_id']}",
                                     use_container_width=True,
                                     help="Add to favorites" if not _is_bk else "Remove from favorites"):
                            bks = list(st.session_state.get("bookmarks", []))
                            if _is_bk:
                                bks.remove(row["associate_id"])
                            else:
                                bks.append(row["associate_id"])
                            st.session_state["bookmarks"] = bks
                            st.rerun()
                    if st.session_state.get("compare_toggle"):
                        _in_cmp = row["associate_id"] in st.session_state.get("compare_ids", [])
                        if st.checkbox("Compare", value=_in_cmp,
                                       key=f"cmp_{row['associate_id']}"):
                            if not _in_cmp:
                                cids = list(st.session_state.get("compare_ids", []))
                                if len(cids) < 5:
                                    cids.append(row["associate_id"])
                                    st.session_state["compare_ids"] = cids
                                    st.rerun()
                        elif _in_cmp:
                            cids = list(st.session_state.get("compare_ids", []))
                            cids.remove(row["associate_id"])
                            st.session_state["compare_ids"] = cids
                            st.rerun()
                    if st.session_state.get("bulk_toggle"):
                        _in_blk = row["associate_id"] in st.session_state.get("_bulk_ids", [])
                        if st.checkbox("Select", value=_in_blk,
                                       key=f"blk_{row['associate_id']}"):
                            if not _in_blk:
                                bids = list(st.session_state.get("_bulk_ids", []))
                                bids.append(row["associate_id"])
                                st.session_state["_bulk_ids"] = bids
                                st.rerun()
                        elif _in_blk:
                            bids = list(st.session_state.get("_bulk_ids", []))
                            bids.remove(row["associate_id"])
                            st.session_state["_bulk_ids"] = bids
                            st.rerun()

        # Pagination controls
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
            st.markdown(f'<div class="pg-bar">{"&nbsp;".join(labels)}</div>', unsafe_allow_html=True)

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

    # ═══════════════════════════ TAB: MY TEAM ═══════════════════════════
    if _dash_active == "My Team":
        if _my_team_assoc.empty:
            st.info("No team members found. Use the **Your Team (SBR)** selector in the sidebar to pick your teams.")
        else:
            _mt_cases = cases_df[cases_df["case_owner"].isin(_my_team_assoc["associate_name"])].copy()
            _mt_stats = _build_stats(_my_team_assoc, _mt_cases)
            _mt_sbrs = sorted(_my_team_assoc["sbr"].dropna().unique().tolist())

            _mgr_display = st.session_state.get("display_name", "Manager")
            st.markdown(_html(f"""<div style="background:linear-gradient(135deg,rgba(99,102,241,0.06),rgba(139,92,246,0.04));
                border:1.5px solid rgba(99,102,241,0.18);border-radius:16px;padding:18px 24px;margin-bottom:16px;">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
                    <span style="font-size:1.1rem;">👥</span>
                    <span style="font-weight:800;font-size:1rem;color:var(--text-color,{PF_TEXT});">{_mgr_display}'s Team</span>
                    <span style="background:rgba(99,102,241,0.1);color:#6366F1;font-size:0.7rem;font-weight:700;
                          padding:2px 10px;border-radius:9999px;">{len(_my_team_assoc)} members</span>
                    <span style="background:rgba(16,185,129,0.1);color:#10B981;font-size:0.7rem;font-weight:700;
                          padding:2px 10px;border-radius:9999px;">SBR: {', '.join(_mt_sbrs)}</span>
                </div>
            </div>"""), unsafe_allow_html=True)

            _mt_resolved = len(_mt_cases[_mt_cases["status"].isin(["Resolved", "Closed"])])
            _mt_csat = _mt_cases["csat_score"].mean()
            _mt_esc = int(_mt_cases["escalated"].sum())
            _mt_perf = _mt_stats["perf"].mean() if len(_mt_stats) else 0
            _mt_perf = _mt_perf if pd.notna(_mt_perf) else 0
            _mt1, _mt2, _mt3, _mt4, _mt5 = st.columns(5)
            _mt1.metric("Team Members", f"{len(_my_team_assoc):,}")
            _mt2.metric("Cases Resolved", f"{_mt_resolved:,}")
            _mt3.metric("Avg CSAT", f"{_mt_csat:.1f}/5" if pd.notna(_mt_csat) else "N/A")
            _mt4.metric("Escalations", f"{_mt_esc:,}")
            _mt5.metric("Avg Performance", f"{_mt_perf:.0f}/100")

            st.markdown("")

            _mt_hdr1, _mt_hdr2, _mt_hdr3 = st.columns([3, 2, 2])
            with _mt_hdr1:
                st.subheader("Team Members")
            with _mt_hdr2:
                _mt_search = st.text_input("Search", placeholder="Name or ID…",
                                           key="_mt_search", label_visibility="collapsed")
            with _mt_hdr3:
                _mt_sort = st.selectbox("Sort by", ["Performance (High)", "Cases Resolved (High)",
                                                     "CSAT (High)", "Escalations (Low)"],
                                        key="_mt_sort", label_visibility="collapsed")

            if _mt_search:
                _sq = _mt_search.lower()
                _mt_stats = _mt_stats[
                    _mt_stats["associate_name"].str.lower().str.contains(_sq, na=False) |
                    _mt_stats["associate_id"].astype(str).str.contains(_sq, na=False)
                ]
            if _mt_sort == "Performance (High)":
                _mt_stats = _mt_stats.sort_values("perf", ascending=False)
            elif _mt_sort == "Cases Resolved (High)":
                _mt_stats = _mt_stats.sort_values("resolved", ascending=False)
            elif _mt_sort == "CSAT (High)":
                _mt_stats = _mt_stats.sort_values("avg_csat", ascending=False)
            else:
                _mt_stats = _mt_stats.sort_values("escalations", ascending=True)

            _mt_total = len(_mt_stats)
            _mt_total_pages = max(1, -(-_mt_total // CARDS_PER_PAGE))
            if st.session_state.get("_mt_page", 0) >= _mt_total_pages:
                st.session_state["_mt_page"] = 0
            _mt_pg = st.session_state.get("_mt_page", 0)
            _mt_start = _mt_pg * CARDS_PER_PAGE
            _mt_end = min(_mt_start + CARDS_PER_PAGE, _mt_total)
            _mt_page_data = _mt_stats.iloc[_mt_start:_mt_end]

            st.caption(f"Showing {_mt_start+1}–{_mt_end} of {_mt_total} members  ·  Page {_mt_pg+1} of {_mt_total_pages}")

            _mt_ids = _mt_page_data["associate_id"].tolist()
            _mt_sk = skills_df[skills_df["associate_id"].isin(_mt_ids)].sort_values("skill_rank")
            _mt_sk_lookup = {aid: grp.head(3) for aid, grp in _mt_sk.groupby("associate_id")}
            for i in range(0, len(_mt_page_data), 3):
                chunk = _mt_page_data.iloc[i:i+3]
                cols = st.columns(3)
                for idx, (_, row) in enumerate(chunk.iterrows()):
                    with cols[idx]:
                        csat_s = f"{row['avg_csat']:.1f}" if pd.notna(row.get("avg_csat")) else "N/A"
                        _perf = row['perf']
                        _bar_clr = "#10B981" if _perf >= 75 else ("#F59E0B" if _perf >= 55 else ("#FB923C" if _perf >= 35 else "#EF4444"))
                        _avclr = _bar_clr
                        initials = row['associate_name'].split()[0][0] if row['associate_name'] else "?"
                        esc_n = row['escalations']
                        a_skills = _mt_sk_lookup.get(row["associate_id"], pd.DataFrame())
                        pills = "".join(
                            f'<span class="skill-pill" style="background:{SKILL_COLORS[si % len(SKILL_COLORS)]};">'
                            f'{sr["skill_name"]}</span>'
                            for si, (_, sr) in enumerate(a_skills.head(3).iterrows())
                        )
                        st.markdown(_html(f"""<div class="assoc-card" style="border-top:3px solid {_bar_clr};">
                            <div class="assoc-card-top">
                                <div class="assoc-avatar" style="background:linear-gradient(135deg,{_avclr},{_avclr}bb);">{initials}</div>
                                <div class="assoc-card-top-left">
                                    <div class="assoc-name">{row['associate_name']}</div>
                                    <div class="assoc-meta">{row['associate_id']} · {row['sbr']} · {row['shift']}</div>
                                    <div class="assoc-perf-line">{perf_badge(row['perf'])} {level_html(row['skill_level'])}</div>
                                </div>
                            </div>
                            <div class="assoc-card-body">
                                <div class="assoc-metrics">
                                    <div class="assoc-metric"><div class="assoc-metric-val">{row['total_cases']}</div><div class="assoc-metric-lbl">Cases</div></div>
                                    <div class="assoc-metric"><div class="assoc-metric-val">{row['resolved']}</div><div class="assoc-metric-lbl">Resolved</div></div>
                                    <div class="assoc-metric"><div class="assoc-metric-val">{esc_n}</div><div class="assoc-metric-lbl">Escalated</div></div>
                                    <div class="assoc-metric"><div class="assoc-metric-val">{csat_s}</div><div class="assoc-metric-lbl">CSAT</div></div>
                                </div>
                                <div class="assoc-perf-bar">
                                    <span class="assoc-perf-lbl">Performance</span>
                                    <div class="assoc-perf-track"><div class="assoc-perf-fill" style="width:{min(_perf,100):.0f}%;background:{_bar_clr};"></div></div>
                                    <span class="assoc-perf-score" style="color:{_bar_clr};">{_perf:.0f}</span>
                                </div>
                                <div class="assoc-card-footer">
                                    <div class="assoc-card-footer-left">{pills}</div>
                                </div>
                            </div>
                        </div>"""), unsafe_allow_html=True)
                        if st.button("View Details", key=f"mt_v_{row['associate_id']}", use_container_width=True):
                            st.session_state.selected_associate = row["associate_id"]
                            st.session_state.ai_insight = None
                            st.session_state.pop("_scorecard_ai", None)
                            st.session_state.pop("det_tab", None)
                            st.query_params["view"] = str(row["associate_id"])
                            st.rerun()

            if _mt_total_pages > 1:
                _mtp1, _mtp2, _mtp3 = st.columns([1, 4, 1])
                with _mtp1:
                    if st.button("← Previous", disabled=(_mt_pg <= 0), key="mt_pg_prev", use_container_width=True):
                        st.session_state["_mt_page"] = _mt_pg - 1
                        st.rerun()
                with _mtp2:
                    st.markdown(_html(f'<div style="text-align:center;padding:8px 0;font-size:0.82rem;color:{PF_TEXT_SEC};">'
                                f'Page {_mt_pg+1} of {_mt_total_pages}</div>'), unsafe_allow_html=True)
                with _mtp3:
                    if st.button("Next →", disabled=(_mt_pg >= _mt_total_pages - 1), key="mt_pg_next", use_container_width=True):
                        st.session_state["_mt_page"] = _mt_pg + 1
                        st.rerun()

            if st.button("Generate Team AI Summary", key="_mt_ai_btn", type="primary"):
                _mt_ctx = "\n".join(
                    f"  {r['associate_name']} ({r['sbr']}, {r['shift']}): "
                    f"{r['total_cases']} cases, {r['resolved']} resolved, "
                    f"CSAT {r['avg_csat']:.1f}, perf {r['perf']:.0f}"
                    for _, r in _mt_stats.iterrows()
                )
                msgs = [
                    {"role": "system", "content":
                        "You are a Red Hat support team analyst. Analyze this manager's team: "
                        "1) Team strength (best performers, resolution rate, top CSAT). "
                        "2) Concerns (low performers, high escalation rates, skill gaps). "
                        "3) 2-3 specific recommendations (e.g., 'Pair junior associate X with senior Y "
                        "on OpenShift cases'). Use **bold** for key numbers. Keep it under 120 words."},
                    {"role": "user", "content":
                        f"Team: {_mgr_display}'s team ({len(_mt_stats)} members)\n"
                        f"SBRs: {', '.join(_mt_sbrs)}\n\n{_mt_ctx}"},
                ]
                with st.spinner("Analyzing team..."):
                    reply = call_ai(msgs, max_tokens=300)
                if reply:
                    st.session_state["_mt_ai_reply"] = reply
                else:
                    st.session_state["_mt_ai_reply"] = (
                        f"**Team Summary:** {len(_mt_stats)} members across {', '.join(_mt_sbrs)}. "
                        f"Avg performance: **{_mt_perf:.0f}/100**. "
                        f"Total resolved: **{_mt_resolved}** cases."
                    )
                st.rerun()
            if st.session_state.get("_mt_ai_reply"):
                st.markdown(ai_card_html("Team Summary", st.session_state["_mt_ai_reply"]),
                            unsafe_allow_html=True)
                if st.button("✕ Close", key="_mt_ai_close"):
                    del st.session_state["_mt_ai_reply"]
                    st.rerun()

    # ═══════════════════════════ TAB 2: TEAM / SBR ═══════════════════════════
    if _dash_active == "Team / SBR View":
        if not has_permission("team_view"):
            st.markdown(_html(f"""<div class="rbac-lock">
                <h3><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:4px"><rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> Access Restricted</h3>
                <p>This view contains team workload and capacity statistics restricted to <strong>Managers</strong> and <strong>Administrators</strong>.</p>
                <p style="margin-top:12px;font-size:0.8rem;">You are logged in as <strong>{st.session_state.get('display_name','User')}</strong>
                with <strong>{st.session_state.get('role','associate')}</strong> role.</p>
            </div>"""), unsafe_allow_html=True)
        else:
            role_label = st.session_state.get("role", "manager").title()
            st.success(f"Authenticated as {role_label}")

            # ── Team Performance Overview (all SBRs) ──
            st.subheader("Team Performance Overview")
            all_sbrs = sorted(associates_df["sbr"].dropna().unique().tolist())
            sbr_perf = []
            for sbr_name in all_sbrs:
                sbr_team = associates_df[associates_df["sbr"] == sbr_name]
                sbr_cases = cases_df[cases_df["case_owner"].isin(sbr_team["associate_name"])]
                n_total = len(sbr_cases)
                n_resolved = len(sbr_cases[sbr_cases["status"].isin(["Resolved", "Closed"])])
                n_open = len(sbr_cases[sbr_cases["status"].isin(
                    ["Open", "In Progress", "Waiting on Customer", "Waiting on Engineering"])])
                n_esc = int(sbr_cases["escalated"].sum())
                avg_csat = sbr_cases["csat_score"].mean() if n_total > 0 else 0
                sbr_perf.append({
                    "SBR": sbr_name, "Members": len(sbr_team),
                    "Resolved": n_resolved, "Open": n_open, "Escalated": n_esc,
                    "Avg CSAT": round(avg_csat, 1) if pd.notna(avg_csat) else 0,
                    "Total": n_total,
                })
            sbr_df = pd.DataFrame(sbr_perf).sort_values("Total", ascending=False)

            fig_overview = go.Figure()
            fig_overview.add_trace(go.Bar(
                x=sbr_df["SBR"], y=sbr_df["Resolved"], name="Resolved",
                marker=dict(color="#10B981"), text=sbr_df["Resolved"],
                textposition="inside", textfont=dict(size=11, color="white"),
            ))
            fig_overview.add_trace(go.Bar(
                x=sbr_df["SBR"], y=sbr_df["Open"], name="Open",
                marker=dict(color="#F59E0B"), text=sbr_df["Open"],
                textposition="inside", textfont=dict(size=11, color="white"),
            ))
            fig_overview.add_trace(go.Bar(
                x=sbr_df["SBR"], y=sbr_df["Escalated"], name="Escalated",
                marker=dict(color="#EF4444"), text=sbr_df["Escalated"],
                textposition="inside", textfont=dict(size=11, color="white"),
            ))
            fig_overview.add_trace(go.Scatter(
                x=sbr_df["SBR"], y=sbr_df["Avg CSAT"], name="Avg CSAT",
                mode="lines+markers", yaxis="y2",
                line=dict(color="#8B5CF6", width=2.5),
                marker=dict(size=8, color="#8B5CF6",
                            line=dict(width=2, color="white")),
                hovertemplate="%{y:.1f}<extra>Avg CSAT</extra>",
            ))
            max_cases = int(sbr_df[["Resolved", "Open", "Escalated"]].sum(axis=1).max()) if len(sbr_df) else 10
            _styled_layout(fig_overview, height=420, xint=False)
            fig_overview.update_layout(
                barmode="stack",
                xaxis=dict(title="", tickangle=-30,
                           tickfont=dict(size=12, color=CHART_FONT)),
                yaxis=dict(title="Cases", dtick=max(1, max_cases // 6), tickformat="d",
                           range=[0, max_cases * 1.25]),
                yaxis2=dict(title="Avg CSAT", overlaying="y", side="right",
                            dtick=1, tickformat=".1f", showgrid=False,
                            range=[0, 5.5],
                            tickfont=dict(color="#8B5CF6", size=11),
                            title_font=dict(color="#8B5CF6", size=12)),
                legend=dict(orientation="h", y=-0.22, x=0.5, xanchor="center",
                            font=dict(size=11), bgcolor="rgba(0,0,0,0)"),
                margin=dict(l=40, r=50, t=20, b=80),
                hovermode="x unified",
            )
            st.plotly_chart(fig_overview, use_container_width=True, key="team_perf_overview")

            # ── SBR Team Cards ──
            st.subheader("SBR Teams")
            _sbr_cols = st.columns(min(len(sbr_df), 3))
            for i, (_, sr) in enumerate(sbr_df.iterrows()):
                with _sbr_cols[i % len(_sbr_cols)]:
                    st.markdown(_html(f"""<div style="background:{PF_SURFACE};border:1px solid {PF_BORDER};
                        border-radius:{PF_RADIUS};padding:14px 16px;margin-bottom:8px;">
                        <div style="font-weight:700;font-size:0.95rem;color:{PF_TEXT};">{sr['SBR']}</div>
                        <div style="font-size:0.75rem;color:{PF_TEXT_SEC};margin-bottom:8px;">{sr['Members']} members</div>
                        <div style="display:flex;gap:12px;flex-wrap:wrap;">
                            <div><span style="font-weight:700;color:{PF_TEXT};">{sr['Total']}</span>
                                 <span style="font-size:0.7rem;color:{PF_TEXT_SEC};">Cases</span></div>
                            <div><span style="font-weight:700;color:#10B981;">{sr['Resolved']}</span>
                                 <span style="font-size:0.7rem;color:{PF_TEXT_SEC};">Resolved</span></div>
                            <div><span style="font-weight:700;color:#F59E0B;">{sr['Open']}</span>
                                 <span style="font-size:0.7rem;color:{PF_TEXT_SEC};">Open</span></div>
                            <div><span style="font-weight:700;color:#EF4444;">{sr['Escalated']}</span>
                                 <span style="font-size:0.7rem;color:{PF_TEXT_SEC};">Escalated</span></div>
                            <div><span style="font-weight:700;color:#8B5CF6;">{sr['Avg CSAT']}</span>
                                 <span style="font-size:0.7rem;color:{PF_TEXT_SEC};">CSAT</span></div>
                        </div>
                    </div>"""), unsafe_allow_html=True)

            st.markdown("---")

            sel_sbr_team = st.selectbox("Select SBR Team", all_sbrs, key="team_sbr")

            team = associates_df[associates_df["sbr"] == sel_sbr_team]
            team_cases = cases_df[cases_df["case_owner"].isin(team["associate_name"])]
            team_stats = _build_stats(team, team_cases)

            tk1, tk2, tk3, tk4, tk5 = st.columns(5)
            n_tr = len(team_cases[team_cases["status"].isin(["Resolved", "Closed"])])
            tc_csat = team_cases["csat_score"].mean()
            tc_esc = int(team_cases["escalated"].sum())
            tk1.metric("Team Size", len(team))
            tk2.metric("Total Cases", len(team_cases))
            tk3.metric("Cases Resolved", n_tr)
            tk4.metric("Avg CSAT Score", f"{tc_csat:.1f}" if pd.notna(tc_csat) else "N/A")
            tk5.metric("Escalations", tc_esc)

            st.subheader(f"{sel_sbr_team} — Team Roster")
            roster = team_stats[["associate_id", "associate_name", "skill_level", "shift",
                                 "total_cases", "resolved", "escalations", "perf",
                                 "manager_name"]].copy()
            roster.columns = ["Associate ID", "Associate Name", "Skill Level", "Geo / Shift",
                              "Total Cases", "Cases Resolved", "Escalations",
                              "Performance Score", "Manager"]
            st.dataframe(roster.sort_values("Performance Score", ascending=False),
                         use_container_width=True, hide_index=True, height=350)

            st.subheader("Team Performance Breakdown")
            st.caption("Analyze team workload, severity distribution, and case status")
            tm_dim = st.segmented_control("Analyze by", ["Workload", "Severity", "Status"],
                                          default="Workload", key="tm_chart_dim")

            if not tm_dim:
                tm_dim = "Workload"
            tm_chart_type = "bar"
            tm_titles = {
                "Workload": "Associate Workload Distribution",
                "Severity": "Case Severity Breakdown",
                "Status": "Case Status Overview",
            }
            if tm_dim == "Workload" and not team_stats.empty:
                top_n = team_stats.nlargest(10, "total_cases")
                tm_df = top_n[["associate_name", "total_cases"]].copy()
                tm_df.columns = ["Category", "Cases"]
                tm_cmap = None
            elif tm_dim == "Severity" and len(team_cases) > 0:
                tm_df = team_cases["severity"].value_counts().reset_index()
                tm_df.columns = ["Category", "Cases"]
                tm_cmap = SEVERITY_COLORS
            elif tm_dim == "Status" and len(team_cases) > 0:
                tm_df = team_cases["status"].value_counts().reset_index()
                tm_df.columns = ["Category", "Cases"]
                tm_cmap = STATUS_COLORS
            else:
                tm_df = pd.DataFrame(columns=["Category", "Cases"])
                tm_cmap = None

            if not tm_df.empty:
                if tm_cmap:
                    tm_colors = [tm_cmap.get(v, GRADIENT_PAIRS[i % len(GRADIENT_PAIRS)][0])
                                 for i, v in enumerate(tm_df["Category"])]
                else:
                    tm_colors = [GRADIENT_PAIRS[i % len(GRADIENT_PAIRS)][0] for i in range(len(tm_df))]
                fig_tm = go.Figure(go.Bar(
                    x=tm_df["Cases"], y=tm_df["Category"], orientation="h",
                    marker=dict(color=tm_colors, line=dict(width=0)),
                    text=tm_df["Cases"], textposition="outside",
                    textfont=dict(color=CHART_FONT, size=12),
                ))
                _tm_max = int(tm_df["Cases"].max()) if len(tm_df) else 1
                _styled_layout(fig_tm, height=max(300, len(tm_df) * 42), yint=False, xint=True)
                fig_tm.update_layout(
                    title=dict(text=tm_titles[tm_dim], font=dict(color=CHART_FONT, size=14), x=0.5),
                    yaxis=dict(autorange="reversed", title=""),
                    xaxis=dict(title="No. of Cases", dtick=max(1, _tm_max // 6)),
                    hovermode="closest", clickmode="event+select",
                )
                tm_evt = st.plotly_chart(fig_tm, use_container_width=True, key="team_chart_unified",
                                         on_select="rerun", selection_mode=("points",))

                sel_tm = None
                if tm_evt and tm_evt.selection:
                    tm_pts = tm_evt.selection.get("points", getattr(tm_evt.selection, "points", []))
                    if tm_pts:
                        tp = tm_pts[0]
                        if isinstance(tp, dict):
                            sel_tm = tp.get("y") or tp.get("label")
                        else:
                            sel_tm = getattr(tp, "y", None) or getattr(tp, "label", None)
                if sel_tm:
                    if tm_dim == "Workload":
                        drill_tm = team_cases[team_cases["case_owner"] == sel_tm]
                    elif tm_dim == "Severity":
                        drill_tm = team_cases[team_cases["severity"] == sel_tm]
                    else:
                        drill_tm = team_cases[team_cases["status"] == sel_tm]
                    if not drill_tm.empty:
                        st.markdown(f"### {sel_tm} — {len(drill_tm)} Cases")
                        _tm_cols = ["case_number", "severity", "status", "product_name",
                                    "problem_statement", "case_owner", "creation_date", "escalated"]
                        st.dataframe(_rename_case_cols(drill_tm[_tm_cols].sort_values("creation_date", ascending=False)),
                                     use_container_width=True, height=300, hide_index=True)

            def _gen_team_summary():
                sk_counts = skills_df[skills_df["associate_id"].isin(team["associate_id"])]["skill_name"].value_counts().head(10)
                s_dist = team["shift"].value_counts()
                l_dist = team["skill_level"].value_counts()
                ctx = (
                    f"SBR: {sel_sbr_team}, Size: {len(team)}, Cases: {len(team_cases)}, "
                    f"Resolved: {n_tr}, CSAT: {f'{tc_csat:.1f}' if pd.notna(tc_csat) else 'N/A'}, "
                    f"Shifts: {', '.join(f'{s}:{c}' for s,c in s_dist.items())}, "
                    f"Levels: {', '.join(f'{s}:{c}' for s,c in l_dist.items())}, "
                    f"Top Skills: {', '.join(f'{s}({c})' for s,c in sk_counts.items())}"
                )
                msgs = [
                    {"role": "system", "content": "You are a Red Hat SBR team analyst. "
                        "Analyze this team's operational health: resolution capacity (cases per person), "
                        "CSAT quality, escalation hotspots, shift coverage balance, and skill depth. "
                        "Identify the top performer and the biggest gap. Give 2 specific recommendations. "
                        "2 short paragraphs max. Use **bold** for key numbers."},
                    {"role": "user", "content": f"Team analysis:\n{ctx}"},
                ]
                with st.spinner("Generating summary..."):
                    result = call_ai(msgs)
                if result is None:
                    _t_res_rate = n_tr / max(len(team_cases), 1) * 100
                    _t_csat_str = f"{tc_csat:.1f}" if pd.notna(tc_csat) else "N/A"
                    _t_rec = ""
                    if _t_res_rate < 60:
                        _t_rec = f"\n\n**Recommendation:** Resolution rate at {_t_res_rate:.0f}% — audit open cases for blockers and consider cross-team support."
                    elif pd.notna(tc_csat) and tc_csat < 3.5:
                        _t_rec = f"\n\n**Recommendation:** CSAT at {_t_csat_str}/5 needs attention — review customer feedback on recent cases for improvement areas."
                    else:
                        _t_rec = f"\n\n**Recommendation:** Team performing well — consider cross-SBR knowledge sharing sessions to spread best practices."
                    result = (
                        f"The **{sel_sbr_team}** team ({len(team)} members) handles "
                        f"**{len(team_cases)} cases** with **{n_tr} resolved** "
                        f"({_t_res_rate:.0f}%). "
                        f"CSAT: **{_t_csat_str}/5**.{_t_rec}"
                    )
                st.session_state.team_ai = result
                st.rerun()

            if st.session_state.team_ai:
                st.markdown(ai_card_html("Team Summary", st.session_state.team_ai),
                            unsafe_allow_html=True)
                if st.button("Regenerate Summary", key="regen_team_ai"):
                    _gen_team_summary()
            else:
                st.markdown(ai_card_empty("Team Summary"), unsafe_allow_html=True)
                if st.button("Generate Team Summary", key="team_ai_btn",
                             type="primary", use_container_width=True):
                    _gen_team_summary()

    # ═══════════════════════════ TAB 3: SKILLS ═══════════════════════════
    if _dash_active == "Skills View":
        skill_prev = (
            skills_df.groupby("skill_name")
            .agg(associates=("associate_id", "nunique"),
                 avg_relevance=("relevance_score", "mean"))
            .reset_index().sort_values("associates", ascending=False)
        )
        skill_prev["avg_relevance"] = skill_prev["avg_relevance"].round(1)
        skill_prev["product"] = skill_prev["skill_name"].map(SKILL_PRODUCT_MAP).fillna("General Portfolio")

        sk1, sk2, sk3, sk4 = st.columns(4)
        sk1.metric("Unique Skills", len(skill_prev))
        sk2.metric("Total Skill Records", f"{len(skills_df):,}")
        sk3.metric("Avg Skills / Associate", f"{len(skills_df)/max(len(associates_df),1):.0f}")
        top_sk = skill_prev.iloc[0]["skill_name"] if len(skill_prev) else "N/A"
        sk4.metric("Most Common", top_sk)

        cert_counts = {}
        for cs in associates_df["certifications"].dropna():
            for c in str(cs).split(","):
                c = c.strip()
                if c:
                    cert_counts[c] = cert_counts.get(c, 0) + 1
        cert_df = (pd.DataFrame(list(cert_counts.items()),
                                columns=["Certification", "Associates"])
                   .sort_values("Associates", ascending=False) if cert_counts
                   else pd.DataFrame(columns=["Certification", "Associates"]))

        st.subheader("Workforce Skill & Certification Analysis")
        show_certs = st.toggle("Switch to Certifications", value=False, key="sk_chart_dim")
        sk_dim = "Certifications" if show_certs else "Skill Prevalence"

        if sk_dim == "Skill Prevalence":
            sk_title = "Top Skills by Associate Count"
            sk_y_label = "Skill"
            sk_x_label = "No. of Associates"
            top15 = skill_prev.head(15)
            sk_chart_df = top15[["skill_name", "associates"]].copy()
            sk_chart_df.columns = ["Category", "Count"]
            sk_chart_colors = [SKILL_COLORS[i % len(SKILL_COLORS)] for i in range(len(sk_chart_df))]
        else:
            sk_title = "Certification Distribution Across Associates"
            sk_y_label = "Certification"
            sk_x_label = "No. of Associates"
            sk_chart_df = cert_df.head(15).copy()
            sk_chart_df.columns = ["Category", "Count"]
            sk_chart_colors = RH_BLUE

        if not sk_chart_df.empty:
            sk_sorted = sk_chart_df.sort_values("Count", ascending=True).reset_index(drop=True)
            max_val = sk_sorted["Count"].max()
            n = len(sk_sorted)
            lollipop_colors = [SKILL_COLORS[i % len(SKILL_COLORS)] for i in range(n)]

            fig_sk = go.Figure()
            fig_sk.add_trace(go.Bar(
                y=sk_sorted["Category"].tolist(), x=sk_sorted["Count"].tolist(),
                orientation="h", marker=dict(
                    color=lollipop_colors, opacity=0.4,
                    line=dict(width=0),
                ),
                showlegend=False, hoverinfo="skip",
                width=0.6,
            ))
            fig_sk.add_trace(go.Scatter(
                x=sk_sorted["Count"].tolist(), y=sk_sorted["Category"].tolist(),
                mode="markers+text",
                marker=dict(size=14, color=lollipop_colors,
                            line=dict(width=2.5, color="#FFFFFF"),
                            symbol="circle"),
                text=[str(v) for v in sk_sorted["Count"]], textposition="middle right",
                textfont=dict(color=CHART_FONT, size=12, family="Red Hat Display"),
                showlegend=False,
                hovertemplate="%{y}<br><b>%{x}</b> associates<extra></extra>",
            ))

            fig_sk.update_layout(
                template=CHART_TPL, paper_bgcolor=CHART_BG, plot_bgcolor=CHART_BG,
                height=max(380, n * 38),
                margin=dict(l=10, r=60, t=50, b=20),
                font=dict(family="Red Hat Display, sans-serif"),
                title=dict(text=sk_title, font=dict(color=CHART_FONT, size=14), x=0.5),
                barmode="overlay",
                xaxis=dict(
                    title=dict(text=sk_x_label, font=dict(color=CHART_FONT2, size=11)),
                    tickfont=dict(color=CHART_FONT2, size=11),
                    gridcolor="rgba(0,0,0,0.04)", zeroline=False,
                    dtick=max(1, max_val // 6), tickformat="d", range=[0, max_val * 1.25],
                ),
                yaxis=dict(
                    title="", tickfont=dict(color=CHART_FONT, size=11),
                    gridcolor="rgba(0,0,0,0.02)", zeroline=False,
                    autorange="reversed",
                ),
                hoverlabel=dict(bgcolor="#1E293B", font_size=13, font_color="#F8FAFC",
                                bordercolor="#6366F1", font_family="Red Hat Text"),
                hovermode="closest",
                showlegend=False,
                transition=dict(duration=600, easing="cubic-in-out"),
            )
            sk_event = st.plotly_chart(fig_sk, use_container_width=True, key="sk_chart_unified", on_select="rerun", selection_mode="points")
            sel_skill = None
            if sk_event and sk_event.selection:
                sk_pts = sk_event.selection.get("points", getattr(sk_event.selection, "points", []))
                if sk_pts:
                    sel_point = sk_pts[0]
                    if isinstance(sel_point, dict):
                        sel_skill = sel_point.get("y") or sel_point.get("label")
                    else:
                        sel_skill = getattr(sel_point, "y", None) or getattr(sel_point, "label", None)
            if sel_skill:
                if sk_dim == "Certifications":
                    with st.expander(f"Associates with \"{sel_skill}\"", expanded=True):
                        matched = associates_df[associates_df["certifications"].fillna("").str.contains(sel_skill, case=False, regex=False)]
                        if not matched.empty:
                            st.dataframe(
                                matched[["associate_id", "associate_name", "sbr", "shift", "skill_level"]].rename(columns={
                                    "associate_id": "ID", "associate_name": "Associate", "sbr": "SBR",
                                    "shift": "Shift", "skill_level": "Level"
                                }),
                                use_container_width=True, hide_index=True,
                            )
                        else:
                            st.info("No associates found with this certification.")
                elif sel_skill in skills_df["skill_name"].values:
                    with st.expander(f"Associates with \"{sel_skill}\"", expanded=True):
                        matched = skills_df[skills_df["skill_name"] == sel_skill].merge(
                            associates_df[["associate_id", "sbr", "shift", "skill_level"]],
                            on="associate_id", how="left"
                        )
                        if not matched.empty:
                            st.dataframe(
                                matched[["associate_name", "sbr", "shift", "skill_level", "relevance_score"]].rename(columns={
                                    "associate_name": "Associate", "sbr": "SBR", "shift": "Shift",
                                    "skill_level": "Level", "relevance_score": "Relevance"
                                }),
                                use_container_width=True, hide_index=True,
                            )
                        else:
                            st.info("No associates found for this skill.")

        st.subheader("Skill Catalog")
        skill_prev["summary"] = skill_prev["skill_name"].map(SKILL_SUMMARY_MAP).fillna("")
        disp = skill_prev.rename(columns={
            "skill_name": "Skill Name", "associates": "No. of Associates",
            "avg_relevance": "Avg Relevance Score", "product": "Product",
            "summary": "Description",
        })
        st.dataframe(disp, use_container_width=True, hide_index=True, height=420)

        st.subheader("All Associates & Skills")
        _sk_assoc = skills_df.merge(
            associates_df[["associate_id", "sbr", "shift", "skill_level", "certifications"]],
            on="associate_id", how="left"
        ).sort_values(["skill_name", "skill_rank"])
        _sk_search = st.text_input("Search associate or skill…", key="_sk_assoc_search",
                                    label_visibility="collapsed", placeholder="Search associate or skill…")
        if _sk_search:
            _sq = _sk_search.lower()
            _sk_assoc = _sk_assoc[
                _sk_assoc["associate_name"].str.lower().str.contains(_sq, na=False)
                | _sk_assoc["skill_name"].str.lower().str.contains(_sq, na=False)
            ]
        st.dataframe(
            _sk_assoc[["associate_name", "sbr", "shift", "skill_level", "skill_name",
                        "skill_rank", "relevance_score", "certifications"]].rename(columns={
                "associate_name": "Associate", "sbr": "SBR", "shift": "Shift",
                "skill_level": "Level", "skill_name": "Skill",
                "skill_rank": "Rank", "relevance_score": "Relevance",
                "certifications": "Certifications",
            }),
            use_container_width=True, hide_index=True, height=500,
        )

        st.subheader("Skill Coverage Heatmap")
        st.caption("Shows how skills are distributed across associate experience levels")
        slm = (
            skills_df.merge(associates_df[["associate_id", "skill_level"]], on="associate_id", how="left")
            .groupby(["skill_name", "skill_level"]).size()
            .reset_index(name="count")
            .pivot_table(index="skill_name", columns="skill_level", values="count", fill_value=0)
        )
        lvl_order = ["Associate", "Mid-Level", "Senior", "Staff", "Principal"]
        for c in lvl_order:
            if c not in slm.columns:
                slm[c] = 0
        slm = slm[lvl_order]
        slm = slm.loc[slm.sum(axis=1).sort_values(ascending=False).head(20).index]

        fig3 = go.Figure(go.Heatmap(
            z=slm.values, x=slm.columns.tolist(), y=slm.index.tolist(),
            colorscale=[[0, "#EEF2FF"], [0.35, "#A78BFA"], [0.7, "#6366F1"], [1, "#4F46E5"]],
            text=slm.values, texttemplate="%{text}",
            textfont=dict(size=11, color=CHART_HM_FONT), showscale=False,
        ))
        fig3.update_layout(template=CHART_TPL, paper_bgcolor=CHART_BG,
                           plot_bgcolor=CHART_BG,
                           font=dict(family="Red Hat Display, sans-serif"),
                           height=max(400, len(slm) * 24),
                           margin=dict(l=10, r=10, t=10, b=40),
                           xaxis_title="Experience Level",
                           yaxis_title="Skill",
                           xaxis=dict(tickfont=dict(color=CHART_FONT)),
                           yaxis=dict(autorange="reversed",
                                      tickfont=dict(color=CHART_FONT)),
                           transition=dict(duration=700, easing="cubic-in-out"))
        st.plotly_chart(fig3, use_container_width=True, key="sk_heatmap")

        def _gen_skill_summary():
            top10 = skill_prev.head(10)
            bot5 = skill_prev.tail(5)
            total_assoc = len(associates_df)
            ctx = (
                f"Total: {total_assoc} associates, {len(skill_prev)} unique skills tracked.\n"
                f"Top skills (name — # associates — % coverage):\n"
                + "\n".join(f"  {r.skill_name}: {r.associates} associates ({r.associates*100//total_assoc}%)"
                            for _, r in top10.iterrows())
                + f"\n\nLowest coverage skills:\n"
                + "\n".join(f"  {r.skill_name}: {r.associates} associates ({r.associates*100//total_assoc}%)"
                            for _, r in bot5.iterrows())
            )
            msgs = [
                {"role": "system", "content":
                    "You are a workforce planning expert at Red Hat. "
                    "Provide a DETAILED, well-structured skill analysis using this exact format:\n\n"
                    "## Key Strengths\n"
                    "- List 3-4 strongest skills with exact numbers and what this means for the team\n\n"
                    "## Critical Gaps\n"
                    "- List 3-4 weakest skills, why they matter, and the risk of not addressing them\n\n"
                    "## Training Recommendations\n"
                    "- Prioritized list of 3-4 specific training actions with expected impact\n\n"
                    "## Coverage Summary\n"
                    "- One paragraph overview with key percentages\n\n"
                    "Use **bold** for key numbers. Be specific — use exact associate counts and percentages. "
                    "Keep language clear and actionable for managers."},
                {"role": "user", "content": f"Analyze this skill data:\n{ctx}"},
            ]
            with st.spinner("Generating..."):
                result = call_ai(msgs)
            if result is None:
                top5_str = "\n".join(f"- **{r.skill_name}** — {r.associates} associates ({r.associates*100//total_assoc}%)" for _, r in top10.head(5).iterrows())
                bot3_str = "\n".join(f"- **{r.skill_name}** — {r.associates} associates ({r.associates*100//total_assoc}%)" for _, r in bot5.head(3).iterrows())
                result = (
                    f"## Key Strengths\n{top5_str}\n\n"
                    f"## Critical Gaps\n{bot3_str}\n\n"
                    f"## Coverage Summary\n"
                    f"The workforce covers **{len(skill_prev)} skills** across **{total_assoc} associates**."
                )
            st.session_state.skill_ai = result
            st.rerun()

        if st.session_state.skill_ai:
            st.markdown(ai_card_html("Skill Analysis", st.session_state.skill_ai),
                        unsafe_allow_html=True)
            _sk_c1, _sk_c2 = st.columns(2)
            with _sk_c1:
                if st.button("Regenerate Analysis", key="regen_sk_ai", use_container_width=True):
                    _gen_skill_summary()
            with _sk_c2:
                if st.button("Close", key="close_sk_ai", use_container_width=True):
                    st.session_state.skill_ai = None
                    st.rerun()
        else:
            st.markdown(ai_card_empty("Skill Analysis"), unsafe_allow_html=True)
            if st.button("Generate Skill Summary", key="sk_ai_btn",
                         type="primary", use_container_width=True):
                _gen_skill_summary()


# ═══════════════════════════════════════════════════════════════════════════════
# FLOATING AI CHATBOT
# ═══════════════════════════════════════════════════════════════════════════════

def _build_chat_context():
    _active_tab = st.session_state.get("dash_tab", "Associates")
    _sel_assoc = st.session_state.get("selected_associate")

    if _sel_assoc:
        try:
            row = associates_df[associates_df["associate_id"] == _sel_assoc].iloc[0]
            a_cases = f_cases[f_cases["case_owner"] == row["associate_name"]]
            a_skills = skills_df[skills_df["associate_id"] == _sel_assoc]
            ctx = build_assoc_context(row["associate_name"], a_cases, a_skills)
            case_csv = a_cases[
                ["case_number", "account_name", "severity", "status", "product_name",
                 "escalated", "csat_score", "time_to_resolve_hours"]
            ].fillna({"csat_score": "Pending", "time_to_resolve_hours": "Pending"}).to_csv(index=False)
            ctx += f"\n\nAll {len(a_cases)} cases for this associate:\n{case_csv}"
            other_cases = f_cases[f_cases["case_owner"] != row["associate_name"]]
            ctx += f"\n\nDashboard also has {len(other_cases)} cases from {other_cases['case_owner'].nunique()} other associates."
            ctx_label = f"Associate Detail: {row['associate_name']}"
            priority_note = (
                f"The user is currently viewing associate **{row['associate_name']}**'s detail page. "
                f"ALWAYS answer questions in the context of THIS associate first. "
                f"If the user asks 'show all cases' or 'all cases', show THIS associate's cases first, "
                f"then mention the broader dashboard totals. Only show other associates' data if explicitly asked."
            )
        except (IndexError, KeyError):
            ctx, ctx_label, priority_note = "No data available.", "Unknown", ""

    elif _active_tab == "My Team":
        _mgr = st.session_state.get("display_name", "")
        _team = f_assoc[f_assoc["manager_name"] == _mgr] if _mgr else f_assoc
        _team_names = _team["associate_name"].tolist()
        _team_cases = f_cases[f_cases["case_owner"].isin(_team_names)]
        _team_summary = _team[["associate_name", "sbr", "shift"]].copy()
        _team_summary = _team_summary.merge(
            assoc_stats[["associate_name", "total_cases", "resolved", "escalations", "avg_csat", "perf"]],
            on="associate_name", how="left"
        )
        _team_csv = _team_summary.to_csv(index=False) if len(_team_summary) > 0 else "No team data"
        ctx = (
            f"My Team ({_mgr}):\n"
            f"Team Size: {len(_team)} | Total Cases: {len(_team_cases)}\n"
            f"Team Members:\n{_team_csv}"
        )
        ctx_label = f"My Team: {_mgr}"
        priority_note = (
            f"The user is on the 'My Team' tab viewing {_mgr}'s team of {len(_team)} associates. "
            f"Answer questions in the context of THIS team first. If asked about 'all cases', show this team's cases. "
            f"Mention dashboard-wide data only for comparison."
        )

    elif _active_tab == "Team / SBR View":
        _sel_sbr = st.session_state.get("_selected_sbr_team", "")
        if _sel_sbr:
            _sbr_team = f_assoc[f_assoc["sbr"] == _sel_sbr]
            _sbr_names = _sbr_team["associate_name"].tolist()
            _sbr_cases = f_cases[f_cases["case_owner"].isin(_sbr_names)]
            _sbr_summary = _sbr_team[["associate_name", "shift", "skill_level"]].copy()
            _sbr_summary = _sbr_summary.merge(
                assoc_stats[["associate_name", "total_cases", "resolved", "escalations", "avg_csat", "perf"]],
                on="associate_name", how="left"
            )
            _sbr_csv = _sbr_summary.to_csv(index=False)
            _sbr_skills = skills_df[skills_df["associate_id"].isin(_sbr_team["associate_id"])]["skill_name"].value_counts().head(10)
            _sk_str = ", ".join(f"{s}({c})" for s, c in _sbr_skills.items())
            ctx = (
                f"SBR Team: {_sel_sbr}\n"
                f"Team Size: {len(_sbr_team)} | Total Cases: {len(_sbr_cases)}\n"
                f"Top Skills: {_sk_str}\n"
                f"Members:\n{_sbr_csv}"
            )
            ctx_label = f"SBR Team: {_sel_sbr}"
            priority_note = (
                f"The user is viewing the '{_sel_sbr}' SBR team ({len(_sbr_team)} members). "
                f"Answer questions about THIS team first. 'All cases' means this team's cases."
            )
        else:
            ctx = f"No SBR team selected. {len(f_assoc)} associates across {f_assoc['sbr'].nunique()} SBR teams."
            ctx_label = "Team / SBR View"
            priority_note = "The user is on the Team/SBR tab but hasn't selected a team yet."

    elif _active_tab == "Skills View":
        top_skills = skills_df.groupby("skill_name").agg(
            associates=("associate_id", "nunique"),
            avg_rank=("skill_rank", "mean")
        ).reset_index().sort_values("associates", ascending=False).head(20)
        skill_csv = top_skills.to_csv(index=False)
        ctx = (
            f"Skills View:\n"
            f"Total unique skills: {skills_df['skill_name'].nunique()} across {len(f_assoc)} associates\n"
            f"Top 20 skills by prevalence:\n{skill_csv}"
        )
        ctx_label = "Skills View"
        priority_note = (
            "The user is on the 'Skills View' tab. Prioritize skill-related data. "
            "If asked about 'top skills' or 'best skills', use the skill prevalence data."
        )

    else:
        avg_csat = f_cases["csat_score"].mean() if len(f_cases) > 0 else 0
        total_esc = int(f_cases["escalated"].sum()) if len(f_cases) > 0 else 0

        summary = assoc_stats[["associate_name", "sbr", "shift",
                         "total_cases", "resolved", "escalations", "avg_csat", "perf"]].copy()
        summary = summary.sort_values("resolved", ascending=False)
        summary["avg_csat"] = summary["avg_csat"].round(1)
        summary_str = summary.head(20).to_csv(index=False) if len(summary) > 0 else "No data"
        _remaining = max(0, len(summary) - 20)
        if _remaining:
            summary_str += f"\n... and {_remaining} more associates"

        status_counts = f_cases["status"].value_counts()
        status_str = ", ".join(f"{s}: {v}" for s, v in status_counts.items())

        prod_counts = f_cases["product_name"].value_counts().head(10)
        prod_str = ", ".join(f"{p}: {v}" for p, v in prod_counts.items())

        sev_stats = f_cases.groupby("severity").agg(
            count=("case_number", "count"),
            avg_csat=("csat_score", "mean"),
            escalated=("escalated", "sum")
        ).reset_index()
        sev_stats["avg_csat"] = sev_stats["avg_csat"].round(1)
        sev_str = ", ".join(f"Sev{row['severity']}: {row['count']} cases, CSAT {row['avg_csat']}, {int(row['escalated'])} esc" for _, row in sev_stats.iterrows())

        shift_counts = f_cases.merge(
            associates_df[["associate_name", "shift"]], left_on="case_owner",
            right_on="associate_name", how="left"
        )["shift"].value_counts()
        shift_str = ", ".join(f"{s}: {v}" for s, v in shift_counts.items())

        top_skills = skills_df.groupby("skill_name").agg(
            associates=("associate_id", "nunique")).reset_index().sort_values(
            "associates", ascending=False).head(15)
        skill_str = ", ".join(f"{row['skill_name']}({row['associates']})" for _, row in top_skills.iterrows())

        open_cases = len(f_cases[f_cases["status"].isin(["Open", "In Progress", "Waiting on Customer", "Waiting on Engineering"])])
        resolved_cases = len(f_cases[f_cases["status"].isin(["Resolved", "Closed"])])
        res_rate = resolved_cases / len(f_cases) * 100 if len(f_cases) else 0
        esc_rate = total_esc / len(f_cases) * 100 if len(f_cases) else 0
        avg_ttr = f_cases["time_to_resolve_hours"].mean() if len(f_cases) > 0 else 0
        pending_csat = int(f_cases["csat_score"].isna().sum()) if len(f_cases) > 0 else 0

        sbr_counts = f_assoc["sbr"].value_counts()
        sbr_str = ", ".join(f"{s}: {v}" for s, v in sbr_counts.items())

        level_counts = f_assoc["skill_level"].value_counts()
        level_str = ", ".join(f"{l}: {v}" for l, v in level_counts.items())

        cases_per_assoc = len(f_cases) / len(f_assoc) if len(f_assoc) > 0 else 0

        case_sample = f_cases[
            ["case_number", "case_owner", "severity", "status", "product_name",
             "escalated", "csat_score"]
        ].fillna({"csat_score": "Pending"}).head(20).to_csv(index=False)

        ctx = (
            f"Dashboard Overview:\n"
            f"Active Associates: {len(f_assoc)} | Total Cases: {len(f_cases)}\n"
            f"Open Cases: {open_cases} | Resolved: {resolved_cases} ({res_rate:.0f}%)\n"
            f"Avg CSAT: {avg_csat:.1f}/5 ({pending_csat} pending) | Escalations: {total_esc} ({esc_rate:.1f}%)\n"
            f"Avg TTR: {avg_ttr:.0f} hrs | Avg Cases/Associate: {cases_per_assoc:.1f}\n"
            f"Skill Levels: {level_str}\n"
            f"SBR Teams: {sbr_str}\n"
            f"Status: {status_str}\n"
            f"Products: {prod_str}\n"
            f"Severity: {sev_str}\n"
            f"Shifts: {shift_str}\n"
            f"Top Skills(associates): {skill_str}\n\n"
            f"Associates (top 20 by resolved):\n{summary_str}\n\n"
            f"Sample Cases (20 of {len(f_cases)}):\n{case_sample}"
        )
        ctx_label = "Dashboard Overview (Associates Tab)"
        priority_note = (
            "The user is on the main Associates list view. Answer in the context of all associates. "
            "If asked about a specific associate, use the data provided."
        )

    _mgr_list = associates_df["manager_name"].dropna().unique().tolist()
    _mgr_with_count = associates_df.groupby("manager_name").size().sort_values(ascending=False)
    _mgr_str = ", ".join(f"{m} ({c})" for m, c in _mgr_with_count.items())

    _sbr_list = associates_df["sbr"].dropna().unique().tolist()
    _sbr_with_count = associates_df.groupby("sbr").size().sort_values(ascending=False)
    _sbr_str = ", ".join(f"{s} ({c})" for s, c in _sbr_with_count.items())

    _shift_dist = associates_df["shift"].value_counts()
    _shift_str = ", ".join(f"{s}: {c}" for s, c in _shift_dist.items())

    _level_dist = associates_df["skill_level"].value_counts()
    _level_str = ", ".join(f"{l}: {c}" for l, c in _level_dist.items())

    _total_cases = len(f_cases)
    _total_assoc = len(associates_df)
    _total_resolved = len(f_cases[f_cases["status"].isin(["Resolved", "Closed"])])
    _total_esc = int(f_cases["escalated"].sum())
    _avg_csat_all = f_cases["csat_score"].mean()

    _ref_data = (
        f"\n\n--- Reference Data (Full Application) ---\n"
        f"Total Associates: {_total_assoc} | Total Cases: {_total_cases}\n"
        f"Resolved: {_total_resolved} | Escalations: {_total_esc}\n"
        f"Avg CSAT: {f'{_avg_csat_all:.1f}' if pd.notna(_avg_csat_all) else 'N/A'}/5\n"
        f"Managers ({len(_mgr_list)}): {_mgr_str}\n"
        f"SBR Teams ({len(_sbr_list)}): {_sbr_str}\n"
        f"Shifts: {_shift_str}\n"
        f"Skill Levels: {_level_str}"
    )

    return {
        "role": "system",
        "content": (
            "You are Insight Hub, AI analyst for a Red Hat Associates Operations Dashboard.\n"
            "SCOPE: ONLY answer questions about this dashboard's data — associates, cases, performance, "
            "SBR teams, shifts, skills, CSAT, escalations, products, workload. "
            "Refuse ALL other topics (recipes, weather, code, jokes, etc.) with: "
            "'I can only help with dashboard data. Try asking about associates, performance, or cases.'\n"
            "RULES:\n"
            "- ONLY use data provided below. NEVER fabricate case numbers, names, or metrics.\n"
            "- CONTEXT PRIORITY: " + priority_note + "\n"
            "- When asked 'all cases' or 'show cases', show data from the CURRENT VIEW first, "
            "then mention broader totals from the Reference Data section.\n"
            "- If the question is about something NOT in the current view (e.g. asking about managers while "
            "on a detail page), use the Reference Data section to answer.\n"
            "- Lead with assessment. Use **bold** for metrics. Use markdown tables for listings.\n"
            "- Show 'Pending' not 'NaN'. CSAT 1-5 (5=best). Shifts: EMEA/APAC/NASA/India.\n"
            "- Levels: Associate→Mid-Level→Senior→Staff→Principal. Be concise. Never invent data.\n\n"
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
    "case", "cases", "associate", "associates", "csat", "escalat", "escalation", "escalations",
    "team", "sbr", "shift", "manager", "product", "products", "skill", "skills",
    "performance", "resolved", "dashboard", "severity", "open", "status",
    "workload", "engineer", "certification", "ttr", "resolution",
    "red hat", "rhel", "openshift", "ansible", "satellite", "ceph", "jboss",
}

def _is_offtopic(text):
    lower = text.lower()
    words = set(lower.split())
    has_offtopic = len(words & _OFFTOPIC_WORDS) >= 1
    has_ontopic = any(kw in lower for kw in _ONTOPIC_WORDS)
    return has_offtopic and not has_ontopic


def _process_chat(user_msg):
    cleaned = _sanitize_ai_input(user_msg)
    if not cleaned:
        st.session_state.global_chat.append({"role": "user", "content": user_msg})
        st.session_state.global_chat.append({"role": "assistant", "content": "Please enter a valid question about the dashboard data."})
        return
    if _is_offtopic(cleaned):
        st.session_state.global_chat.append({"role": "user", "content": cleaned})
        st.session_state.global_chat.append({"role": "assistant",
            "content": "I can only assist with questions about the associate operations data in this dashboard. "
                        "Try asking about performance, cases, CSAT, teams, or skills."})
        return
    st.session_state.global_chat.append({"role": "user", "content": cleaned})
    sys_prompt = _build_chat_context()
    recent = st.session_state.global_chat[-20:]
    msgs = [sys_prompt] + [{"role": m["role"], "content": m["content"]} for m in recent]
    reply = call_ai(msgs, max_tokens=512)
    if reply is None:
        reply = "AI endpoint is not configured. Set AI_ENDPOINT_URL, AI_API_TOKEN, AI_MODEL_ID in .env."
    reply = _sanitize_ai_output(reply)
    st.session_state.global_chat.append({"role": "assistant", "content": reply})


@st.dialog("Insight Hub", width="large")
def _show_ai_chat():
    pending = st.session_state.pop("_ai_pending", None)
    if pending:
        with st.spinner("Processing..."):
            _process_chat(pending)

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
            for m in st.session_state.global_chat:
                with st.chat_message(m["role"]):
                    st.markdown(m["content"])
    else:
        st.markdown(_html("""<div class="ai-welcome">
            <h4>Insight Hub</h4>
            <p>Ask about associate performance, team workload, skill gaps,
            escalation patterns, and operational metrics.</p>
            <div class="ai-suggestion">&mdash; "Who has the most escalations?"</div>
            <div class="ai-suggestion">&mdash; "Compare EMEA vs APAC team performance"</div>
            <div class="ai-suggestion">&mdash; "Which skills have the lowest coverage?"</div>
        </div>"""), unsafe_allow_html=True)

    with st.form("ai_form", clear_on_submit=True):
        cols = st.columns([6, 1])
        with cols[0]:
            user_input = st.text_input("Message", placeholder="Ask anything...",
                                        label_visibility="collapsed")
        with cols[1]:
            submitted = st.form_submit_button("Send")

    if submitted and user_input:
        st.session_state["_ai_pending"] = user_input
        st.rerun(scope="fragment")

    if st.session_state.global_chat:
        cols = st.columns([1, 1])
        with cols[0]:
            if st.button("Clear conversation", key="clear_chat", use_container_width=True):
                st.session_state.global_chat = []
                st.rerun(scope="fragment")
        with cols[1]:
            st.markdown(
                _html(f'<div style="text-align:right;color:{PF_TEXT_SEC};font-size:0.7rem;'
                f'padding-top:8px;">Powered by IBM Granite</div>'),
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            _html(f'<div style="text-align:center;color:{PF_TEXT_SEC};font-size:0.7rem;'
            f'margin-top:4px;">Powered by IBM Granite</div>'),
            unsafe_allow_html=True,
        )


def render_floating_chat():
    if st.sidebar.button("Insight Hub", use_container_width=True,
                          type="primary", key="open_ai"):
        _show_ai_chat()

    st.markdown(_html(f"""<div class="ai-fab-wrap" title="Insight Hub">
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
                if (sidebar) {
                    const aiBtn = sidebar.querySelector('button[kind="primary"]');
                    if (aiBtn) aiBtn.click();
                }
            });
        };
        setupFab();
        setTimeout(setupFab, 300);
        setTimeout(setupFab, 2000);
        const addClearBtns = () => {
            pd.querySelectorAll('div.stTextInput input[type="text"]').forEach(inp => {
                const ph = (inp.placeholder||'').toLowerCase();
                if ((!ph.includes('search') && !ph.includes('name or') && !ph.includes('name…') && !ph.includes('skill')) || inp._clrDone) return;
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
                    const nSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                    nSet.call(inp, ''); inp.dispatchEvent(new Event('input', {bubbles:true}));
                    inp.dispatchEvent(new Event('change', {bubbles:true}));
                    inp.focus(); toggle();
                });
            });
        };
        addClearBtns(); setTimeout(addClearBtns, 1500);
        new MutationObserver(() => setTimeout(addClearBtns, 300)).observe(pd.body, {childList:true, subtree:true});
    })();
    </script>
    """, height=0)


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTING
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="page-loader"></div>', unsafe_allow_html=True)

if st.session_state.get("authenticated", False) and not check_session():
    st.toast("Session expired. Please sign in again.")

if not st.session_state.get("authenticated", False):
    render_login_page()
else:
    if st.session_state.selected_associate:
        render_detail(st.session_state.selected_associate)
    else:
        render_dashboard()

if st.session_state.get("authenticated", False):
    render_floating_chat()
    _save_session()
