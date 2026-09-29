"""Shared test fixtures — handles anti-scraping middleware bypass."""
import hashlib
import hmac
import os
import time

import pytest
from fastapi.testclient import TestClient
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api import app

from config import FRONTEND_SECRET  # single source of truth, validated at startup

def _frontend_headers():
    ts = str(int(time.time()))
    msg = f"capstone2:{ts}".encode()
    token = hmac.new(FRONTEND_SECRET.encode(), msg, hashlib.sha256).hexdigest()[:32]
    return {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) TestSuite/1.0",
        "x-frontend-token": token,
        "x-frontend-ts": ts,
    }


@pytest.fixture
def client():
    c = TestClient(app)
    c.headers.update(_frontend_headers())
    return c


@pytest.fixture
def auth_token(client):
    resp = client.post("/auth/login", json={"username": "admin", "password": "admin2026"})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


@pytest.fixture
def headers(auth_token):
    h = _frontend_headers()
    h["Authorization"] = f"Bearer {auth_token}"
    return h
