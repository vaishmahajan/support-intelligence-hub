"""Tests for JWT authentication and role-based access control.

Fixtures (client, auth_token, headers) are provided by conftest.py.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api import create_access_token


def get_token(client, username, password):
    resp = client.post("/auth/login", json={"username": username, "password": password})
    if resp.status_code == 200:
        return resp.json()["access_token"]
    return None


class TestJWT:
    def test_token_structure(self, client):
        token = get_token(client, "admin", "admin2026")
        assert token is not None
        parts = token.split(".")
        assert len(parts) == 3, "JWT should have 3 parts"

    def test_expired_token_rejected(self, client):
        from datetime import timedelta
        token = create_access_token({"sub": "admin", "role": "admin"}, expires_delta=timedelta(seconds=-1))
        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_invalid_token_rejected(self, client):
        resp = client.get("/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
        assert resp.status_code == 401

    def test_missing_auth_header(self, client):
        from fastapi.testclient import TestClient
        from api import app
        raw = TestClient(app)
        raw.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) TestSuite/1.0",
        })
        resp = raw.get("/api/v1/associates")
        assert resp.status_code in (403,)


class TestRBAC:
    def test_admin_can_access_all(self, client, headers):
        for endpoint in ["/api/v1/associates", "/api/v1/cases", "/api/v1/teams", "/api/v1/stats/overview"]:
            resp = client.get(endpoint, headers=headers)
            assert resp.status_code == 200, f"Admin denied from {endpoint}"

    def test_manager_can_access_all(self, client):
        token = get_token(client, "manager", "manager2026")
        assert token is not None
        h = {"Authorization": f"Bearer {token}"}
        for endpoint in ["/api/v1/associates", "/api/v1/cases", "/api/v1/teams"]:
            resp = client.get(endpoint, headers=h)
            assert resp.status_code == 200, f"Manager denied from {endpoint}"

    def test_associate_can_read(self, client):
        token = get_token(client, "associate", "associate2026")
        assert token is not None
        resp = client.get("/api/v1/associates", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_each_role_returns_correct_role_claim(self, client):
        for username, expected_role in [("admin", "admin"), ("manager", "manager"), ("associate", "associate")]:
            token = get_token(client, username, f"{username}2026")
            assert token is not None
            resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200
            assert resp.json()["role"] == expected_role
