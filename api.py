#!/usr/bin/env python3
"""
Capstone2 — Secure REST API for Associates Dashboard

Endpoints expose read-only access to associates, cases, skills, teams,
and aggregate statistics.  All routes require JWT Bearer token auth.

Run:
  uvicorn api:app --port 8503 --reload

Auth:
  POST /auth/login with {"username": "...", "password": "..."}
  Two built-in accounts:
    viewer  / viewer123                       → role=viewer  (read-only)
    manager / <MANAGER_PASSWORD from .env>    → role=manager (full access)
  Use the returned access_token as:  Authorization: Bearer <token>
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel
from db import get_dict_connection, PARAM

load_dotenv(override=False)  # real environment wins; .env only fills gaps

import config

JWT_SECRET = config.JWT_SECRET
JWT_ALGORITHM = config.JWT_ALGORITHM
JWT_EXPIRE_MINUTES = config.JWT_EXPIRE_MINUTES

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

MANAGER_PASSWORD = config.MANAGER_PASSWORD
ADMIN_PASSWORD = config.ADMIN_PASSWORD
ASSOCIATE_PASSWORD = config.ASSOCIATE_PASSWORD

USERS_DB = {
    "admin": {
        "username": "admin",
        "hashed_password": pwd_ctx.hash(ADMIN_PASSWORD),
        "role": "admin",
    },
    "manager": {
        "username": "manager",
        "hashed_password": pwd_ctx.hash(MANAGER_PASSWORD),
        "role": "manager",
    },
    "associate": {
        "username": "associate",
        "hashed_password": pwd_ctx.hash(ASSOCIATE_PASSWORD),
        "role": "associate",
    },
}

app = FastAPI(
    title="Associates Dashboard API",
    description="Secure REST API for the Associates Operational Dashboard (Business Requirement #2)",
    version="2.0.0",
)

from middleware import AntiScrapingMiddleware
app.add_middleware(AntiScrapingMiddleware)

# Derived from the public dashboard URLs so CORS cannot drift away from
# where the dashboards are actually served. Override with CORS_ORIGINS.
_ALLOWED_ORIGINS = config.cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

security = HTTPBearer()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    username = payload.get("sub")
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    # Dashboard session tokens ride in the browser URL and handoff tokens are
    # emailable links; neither is an API credential, even though all three are
    # signed with the same key.
    if payload.get("typ") in ("session", "handoff"):
        raise HTTPException(
            status_code=401,
            detail="This is a dashboard token, not an API token. "
                   "Obtain one from POST /auth/login.")
    return payload


def require_manager(payload: dict = Depends(verify_token)) -> dict:
    if payload.get("role") not in ("manager", "admin"):
        raise HTTPException(status_code=403, detail="Manager or Admin role required")
    return payload


def get_db():
    conn = get_dict_connection()
    try:
        yield conn
    finally:
        conn.close()


# ── Auth ─────────────────────────────────────────────────────────────────────

@app.post("/auth/login", tags=["Auth"], response_model=TokenResponse)
def login(req: LoginRequest):
    user = USERS_DB.get(req.username)
    if not user or not pwd_ctx.verify(req.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    return TokenResponse(
        access_token=token,
        expires_in=JWT_EXPIRE_MINUTES * 60,
        role=user["role"],
    )


@app.get("/auth/me", tags=["Auth"], dependencies=[Depends(verify_token)])
def current_user(payload: dict = Depends(verify_token)):
    return {"username": payload["sub"], "role": payload["role"]}


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ── Associates ────────────────────────────────────────────────────────────────

@app.get("/api/v1/associates", tags=["Associates"],
         dependencies=[Depends(verify_token)])
def list_associates(
    sbr: Optional[str] = Query(None, description="Filter by SBR team"),
    shift: Optional[str] = Query(None, description="Filter by geo/shift"),
    skill_level: Optional[str] = Query(None, description="Filter by skill level"),
    manager: Optional[str] = Query(None, description="Filter by manager name"),
    active: Optional[int] = Query(None, description="Filter by active status (0 or 1)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn = Depends(get_db),
):
    query = "SELECT * FROM associates WHERE 1=1"
    params = []
    if sbr:
        query += f" AND sbr = {PARAM}"
        params.append(sbr)
    if shift:
        query += f" AND shift = {PARAM}"
        params.append(shift)
    if skill_level:
        query += f" AND skill_level = {PARAM}"
        params.append(skill_level)
    if manager:
        query += f" AND manager_name = {PARAM}"
        params.append(manager)
    if active is not None:
        query += f" AND active = {PARAM}"
        params.append(active)
    query += f" ORDER BY associate_name LIMIT {PARAM} OFFSET {PARAM}"
    params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()
    return {"count": len(rows), "data": [dict(r) for r in rows]}


@app.get("/api/v1/associates/{associate_id}", tags=["Associates"],
         dependencies=[Depends(verify_token)])
def get_associate(associate_id: str, conn=Depends(get_db)):
    row = conn.execute(
        f"SELECT * FROM associates WHERE associate_id = {PARAM}", (associate_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Associate not found")
    skills = conn.execute(
        f"SELECT skill_name, skill_rank, relevance_score FROM skills WHERE associate_id = {PARAM} ORDER BY skill_rank",
        (associate_id,),
    ).fetchall()
    cases = conn.execute(
        f"SELECT case_number, severity, status, csat_score, product_name, creation_date, escalated, time_to_resolve_hours "
        f"FROM support_cases WHERE case_owner = (SELECT associate_name FROM associates WHERE associate_id = {PARAM})",
        (associate_id,),
    ).fetchall()
    return {
        "associate": dict(row),
        "skills": [dict(s) for s in skills],
        "cases_summary": {
            "total": len(cases),
            "resolved": sum(1 for c in cases if c["status"] in ("Resolved", "Closed")),
            "escalated": sum(1 for c in cases if c["escalated"]),
            "avg_csat": round(
                sum(c["csat_score"] for c in cases if c["csat_score"]) /
                max(sum(1 for c in cases if c["csat_score"]), 1), 2
            ),
        },
        "cases": [dict(c) for c in cases],
    }


# ── Cases ─────────────────────────────────────────────────────────────────────

@app.get("/api/v1/cases", tags=["Cases"],
         dependencies=[Depends(verify_token)])
def list_cases(
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    product: Optional[str] = Query(None, description="Filter by product_name"),
    account: Optional[str] = Query(None, description="Filter by account_name"),
    owner: Optional[str] = Query(None, description="Filter by case_owner"),
    escalated: Optional[int] = Query(None, description="0 or 1"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn = Depends(get_db),
):
    query = "SELECT * FROM support_cases WHERE 1=1"
    params = []
    if severity:
        query += f" AND severity = {PARAM}"
        params.append(severity)
    if status:
        query += f" AND status = {PARAM}"
        params.append(status)
    if product:
        query += f" AND product_name = {PARAM}"
        params.append(product)
    if account:
        query += f" AND account_name = {PARAM}"
        params.append(account)
    if owner:
        query += f" AND case_owner = {PARAM}"
        params.append(owner)
    if escalated is not None:
        query += f" AND escalated = {PARAM}"
        params.append(escalated)
    query += f" ORDER BY creation_date DESC LIMIT {PARAM} OFFSET {PARAM}"
    params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()
    return {"count": len(rows), "data": [dict(r) for r in rows]}


# ── Skills ────────────────────────────────────────────────────────────────────

@app.get("/api/v1/skills", tags=["Skills"],
         dependencies=[Depends(verify_token)])
def list_skills(
    skill_name: Optional[str] = Query(None),
    min_rank: Optional[int] = Query(None, ge=1, le=5),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn = Depends(get_db),
):
    query = "SELECT * FROM skills WHERE 1=1"
    params = []
    if skill_name:
        query += f" AND skill_name = {PARAM}"
        params.append(skill_name)
    if min_rank is not None:
        query += f" AND skill_rank >= {PARAM}"
        params.append(min_rank)
    query += f" ORDER BY skill_name, skill_rank LIMIT {PARAM} OFFSET {PARAM}"
    params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()
    return {"count": len(rows), "data": [dict(r) for r in rows]}


@app.get("/api/v1/skills/prevalence", tags=["Skills"],
         dependencies=[Depends(verify_token)])
def skill_prevalence(conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT skill_name, COUNT(DISTINCT associate_id) as associate_count, "
        "ROUND(AVG(relevance_score), 2) as avg_relevance "
        "FROM skills GROUP BY skill_name ORDER BY associate_count DESC"
    ).fetchall()
    return {"data": [dict(r) for r in rows]}


# ── Teams ─────────────────────────────────────────────────────────────────────

@app.get("/api/v1/teams", tags=["Teams"],
         dependencies=[Depends(verify_token)])
def list_teams(conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT sbr, COUNT(*) as member_count FROM associates "
        "WHERE active = 1 GROUP BY sbr ORDER BY member_count DESC"
    ).fetchall()
    return {"data": [dict(r) for r in rows]}


@app.get("/api/v1/teams/{sbr}", tags=["Teams"],
         dependencies=[Depends(verify_token)])
def get_team(sbr: str, conn=Depends(get_db)):
    members = conn.execute(
        f"SELECT * FROM associates WHERE sbr = {PARAM} ORDER BY associate_name", (sbr,)
    ).fetchall()
    if not members:
        raise HTTPException(status_code=404, detail="SBR team not found")
    names = [m["associate_name"] for m in members]
    placeholders = ",".join([PARAM] * len(names))
    cases = conn.execute(
        f"SELECT severity, status, escalated, csat_score, time_to_resolve_hours "
        f"FROM support_cases WHERE case_owner IN ({placeholders})", names
    ).fetchall()
    total = len(cases)
    resolved = sum(1 for c in cases if c["status"] in ("Resolved", "Closed"))
    escalated = sum(1 for c in cases if c["escalated"])
    csats = [c["csat_score"] for c in cases if c["csat_score"]]
    return {
        "sbr": sbr,
        "members": [dict(m) for m in members],
        "stats": {
            "member_count": len(members),
            "total_cases": total,
            "resolved": resolved,
            "escalated": escalated,
            "avg_csat": round(sum(csats) / max(len(csats), 1), 2),
            "resolution_rate": round(resolved / max(total, 1) * 100, 1),
        },
    }


# ── Statistics ────────────────────────────────────────────────────────────────

@app.get("/api/v1/stats/overview", tags=["Statistics"],
         dependencies=[Depends(verify_token)])
def overview_stats(conn=Depends(get_db)):
    assoc = conn.execute("SELECT COUNT(*) as c FROM associates WHERE active = 1").fetchone()
    cases_total = conn.execute("SELECT COUNT(*) as c FROM support_cases").fetchone()
    resolved = conn.execute(
        "SELECT COUNT(*) as c FROM support_cases WHERE status IN ('Resolved','Closed')"
    ).fetchone()
    escalated = conn.execute(
        "SELECT COUNT(*) as c FROM support_cases WHERE escalated = 1"
    ).fetchone()
    csat = conn.execute(
        "SELECT ROUND(AVG(csat_score), 2) as avg FROM support_cases WHERE csat_score IS NOT NULL"
    ).fetchone()
    ttr = conn.execute(
        "SELECT ROUND(AVG(time_to_resolve_hours), 1) as avg FROM support_cases "
        "WHERE time_to_resolve_hours IS NOT NULL"
    ).fetchone()
    skills_count = conn.execute("SELECT COUNT(DISTINCT skill_name) as c FROM skills").fetchone()
    return {
        "active_associates": assoc["c"],
        "total_cases": cases_total["c"],
        "cases_resolved": resolved["c"],
        "total_escalations": escalated["c"],
        "avg_csat": csat["avg"],
        "avg_resolve_time_hours": ttr["avg"],
        "unique_skills": skills_count["c"],
    }


@app.get("/api/v1/stats/by-shift", tags=["Statistics"],
         dependencies=[Depends(verify_token)])
def stats_by_shift(conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT a.shift, COUNT(DISTINCT a.associate_id) as associates, "
        "COUNT(c.case_number) as cases, "
        "ROUND(AVG(c.csat_score), 2) as avg_csat, "
        "SUM(c.escalated) as escalations "
        "FROM associates a LEFT JOIN support_cases c ON c.case_owner = a.associate_name "
        "GROUP BY a.shift ORDER BY cases DESC"
    ).fetchall()
    return {"data": [dict(r) for r in rows]}


@app.get("/api/v1/stats/by-severity", tags=["Statistics"],
         dependencies=[Depends(verify_token)])
def stats_by_severity(conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT severity, COUNT(*) as count, "
        "ROUND(AVG(csat_score), 2) as avg_csat, "
        "SUM(escalated) as escalations, "
        "ROUND(AVG(time_to_resolve_hours), 1) as avg_ttr_hours "
        "FROM support_cases GROUP BY severity ORDER BY count DESC"
    ).fetchall()
    return {"data": [dict(r) for r in rows]}


# ── Accounts ──────────────────────────────────────────────────────────────────

@app.get("/api/v1/accounts", tags=["Accounts"],
         dependencies=[Depends(verify_token)])
def list_accounts(
    sector: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn = Depends(get_db),
):
    query = "SELECT * FROM accounts WHERE 1=1"
    params = []
    if sector:
        query += f" AND sector = {PARAM}"
        params.append(sector)
    if region:
        query += f" AND region = {PARAM}"
        params.append(region)
    query += f" ORDER BY account_name LIMIT {PARAM} OFFSET {PARAM}"
    params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()
    return {"count": len(rows), "data": [dict(r) for r in rows]}
