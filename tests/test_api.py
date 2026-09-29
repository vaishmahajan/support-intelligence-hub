"""Tests for the FastAPI REST API endpoints.

Fixtures (client, auth_token, headers) are provided by conftest.py.
"""
import pytest


class TestHealth:
    def test_health_check(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "timestamp" in data


class TestAuth:
    def test_login_valid(self, client):
        resp = client.post("/auth/login", json={"username": "admin", "password": "admin2026"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["role"] == "admin"

    def test_login_invalid_password(self, client):
        resp = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401

    def test_login_invalid_user(self, client):
        resp = client.post("/auth/login", json={"username": "nobody", "password": "x"})
        assert resp.status_code == 401

    def test_me_authenticated(self, client, headers):
        resp = client.get("/auth/me", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"

    def test_me_unauthenticated(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code in (401, 403)

    def test_login_all_roles(self, client):
        for username, role in [("admin", "admin"), ("manager", "manager"), ("associate", "associate")]:
            pwd = f"{username}2026"
            resp = client.post("/auth/login", json={"username": username, "password": pwd})
            assert resp.status_code == 200
            assert resp.json()["role"] == role


class TestAssociates:
    def test_list_associates(self, client, headers):
        resp = client.get("/api/v1/associates", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert "data" in data
        assert data["count"] > 0

    def test_list_associates_unauthenticated(self, client):
        resp = client.get("/api/v1/associates")
        assert resp.status_code in (401, 403)

    def test_list_associates_filter_sbr(self, client, headers):
        all_resp = client.get("/api/v1/associates?limit=1", headers=headers)
        if all_resp.json()["count"] > 0:
            sbr = all_resp.json()["data"][0].get("sbr")
            if sbr:
                resp = client.get(f"/api/v1/associates?sbr={sbr}", headers=headers)
                assert resp.status_code == 200
                for a in resp.json()["data"]:
                    assert a["sbr"] == sbr

    def test_get_associate_detail(self, client, headers):
        list_resp = client.get("/api/v1/associates?limit=1", headers=headers)
        if list_resp.json()["count"] > 0:
            aid = list_resp.json()["data"][0]["associate_id"]
            resp = client.get(f"/api/v1/associates/{aid}", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert "associate" in data
            assert "skills" in data
            assert "cases_summary" in data

    def test_get_associate_not_found(self, client, headers):
        resp = client.get("/api/v1/associates/NONEXISTENT_999", headers=headers)
        assert resp.status_code == 404

    def test_list_associates_pagination(self, client, headers):
        resp = client.get("/api/v1/associates?limit=5&offset=0", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["count"] <= 5


class TestCases:
    def test_list_cases(self, client, headers):
        resp = client.get("/api/v1/cases", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert data["count"] > 0

    def test_list_cases_filter_severity(self, client, headers):
        resp = client.get("/api/v1/cases?severity=1&limit=5", headers=headers)
        assert resp.status_code == 200

    def test_list_cases_filter_escalated(self, client, headers):
        resp = client.get("/api/v1/cases?escalated=1&limit=5", headers=headers)
        assert resp.status_code == 200


class TestSkills:
    def test_list_skills(self, client, headers):
        resp = client.get("/api/v1/skills", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["count"] > 0

    def test_skill_prevalence(self, client, headers):
        resp = client.get("/api/v1/skills/prevalence", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) > 0
        assert "skill_name" in data[0]
        assert "associate_count" in data[0]


class TestTeams:
    def test_list_teams(self, client, headers):
        resp = client.get("/api/v1/teams", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) > 0

    def test_get_team_detail(self, client, headers):
        teams = client.get("/api/v1/teams", headers=headers).json()["data"]
        if teams:
            sbr = teams[0]["sbr"]
            resp = client.get(f"/api/v1/teams/{sbr}", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert "members" in data
            assert "stats" in data
            assert data["stats"]["member_count"] > 0

    def test_get_team_not_found(self, client, headers):
        resp = client.get("/api/v1/teams/NONEXISTENT_TEAM", headers=headers)
        assert resp.status_code == 404


class TestStats:
    def test_overview_stats(self, client, headers):
        resp = client.get("/api/v1/stats/overview", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_associates"] > 0
        assert data["total_cases"] > 0
        assert "avg_csat" in data

    def test_stats_by_shift(self, client, headers):
        resp = client.get("/api/v1/stats/by-shift", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["data"]) > 0

    def test_stats_by_severity(self, client, headers):
        resp = client.get("/api/v1/stats/by-severity", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["data"]) > 0


class TestAccounts:
    def test_list_accounts(self, client, headers):
        resp = client.get("/api/v1/accounts", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["count"] > 0

    def test_list_accounts_filter_sector(self, client, headers):
        all_resp = client.get("/api/v1/accounts?limit=1", headers=headers)
        if all_resp.json()["count"] > 0:
            sector = all_resp.json()["data"][0].get("sector")
            if sector:
                resp = client.get(f"/api/v1/accounts?sector={sector}", headers=headers)
                assert resp.status_code == 200
