"""Tests for data integrity in the database."""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import get_connection, PARAM, IS_PG


@pytest.fixture
def conn():
    c = get_connection()
    yield c
    c.close()


def _col_names(cursor):
    return [desc[0] for desc in cursor.description]


class TestTablesExist:
    @pytest.mark.parametrize("table", ["accounts", "support_cases", "associates", "skills", "registered_users"])
    def test_table_exists(self, conn, table):
        if IS_PG:
            cur = conn.execute(
                f"SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name={PARAM}",
                (table,))
        else:
            cur = conn.execute(
                f"SELECT name FROM sqlite_master WHERE type='table' AND name={PARAM}", (table,))
        assert cur.fetchone() is not None, f"Table '{table}' does not exist"


class TestAccountsData:
    def test_accounts_not_empty(self, conn):
        count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        assert count > 0

    def test_accounts_required_columns(self, conn):
        cur = conn.execute("SELECT * FROM accounts LIMIT 1")
        keys = _col_names(cur)
        for col in ["account_id", "account_name", "sector", "region"]:
            assert col in keys, f"Column '{col}' missing from accounts"

    def test_account_ids_unique(self, conn):
        total = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        distinct = conn.execute("SELECT COUNT(DISTINCT account_id) FROM accounts").fetchone()[0]
        assert total == distinct

    def test_account_names_not_null(self, conn):
        nulls = conn.execute("SELECT COUNT(*) FROM accounts WHERE account_name IS NULL OR account_name = ''").fetchone()[0]
        assert nulls == 0


class TestSupportCasesData:
    def test_cases_not_empty(self, conn):
        count = conn.execute("SELECT COUNT(*) FROM support_cases").fetchone()[0]
        assert count > 0

    def test_cases_required_columns(self, conn):
        cur = conn.execute("SELECT * FROM support_cases LIMIT 1")
        keys = _col_names(cur)
        for col in ["case_number", "severity", "status", "case_owner", "product_name"]:
            assert col in keys

    def test_case_numbers_unique(self, conn):
        total = conn.execute("SELECT COUNT(*) FROM support_cases").fetchone()[0]
        distinct = conn.execute("SELECT COUNT(DISTINCT case_number) FROM support_cases").fetchone()[0]
        assert total == distinct

    def test_csat_scores_valid_range(self, conn):
        invalid = conn.execute(
            "SELECT COUNT(*) FROM support_cases WHERE csat_score IS NOT NULL AND (csat_score < 0 OR csat_score > 5)"
        ).fetchone()[0]
        assert invalid == 0, f"{invalid} cases have CSAT outside 0-5 range"

    def test_escalated_is_binary(self, conn):
        invalid = conn.execute(
            "SELECT COUNT(*) FROM support_cases WHERE escalated NOT IN (0, 1)"
        ).fetchone()[0]
        assert invalid == 0


class TestAssociatesData:
    def test_associates_not_empty(self, conn):
        count = conn.execute("SELECT COUNT(*) FROM associates").fetchone()[0]
        assert count > 0

    def test_associates_required_columns(self, conn):
        cur = conn.execute("SELECT * FROM associates LIMIT 1")
        keys = _col_names(cur)
        for col in ["associate_id", "associate_name", "sbr", "shift"]:
            assert col in keys

    def test_associate_ids_unique(self, conn):
        total = conn.execute("SELECT COUNT(*) FROM associates").fetchone()[0]
        distinct = conn.execute("SELECT COUNT(DISTINCT associate_id) FROM associates").fetchone()[0]
        assert total == distinct

    def test_case_owners_exist_as_associates(self, conn):
        orphaned = conn.execute(
            "SELECT COUNT(DISTINCT case_owner) FROM support_cases "
            "WHERE case_owner NOT IN (SELECT associate_name FROM associates)"
        ).fetchone()[0]
        assert orphaned == 0, f"{orphaned} case owners are not in the associates table"


class TestSkillsData:
    def test_skills_not_empty(self, conn):
        count = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        assert count > 0

    def test_skills_required_columns(self, conn):
        cur = conn.execute("SELECT * FROM skills LIMIT 1")
        keys = _col_names(cur)
        for col in ["associate_id", "skill_name", "skill_rank", "relevance_score"]:
            assert col in keys

    def test_skill_ranks_valid(self, conn):
        invalid = conn.execute(
            "SELECT COUNT(*) FROM skills WHERE skill_rank < 1 OR skill_rank > 5"
        ).fetchone()[0]
        assert invalid == 0

    def test_skill_associate_ids_exist(self, conn):
        orphaned = conn.execute(
            "SELECT COUNT(DISTINCT associate_id) FROM skills "
            "WHERE associate_id NOT IN (SELECT associate_id FROM associates)"
        ).fetchone()[0]
        assert orphaned == 0, f"{orphaned} skill entries reference non-existent associates"


class TestRegisteredUsers:
    def test_table_exists_and_has_columns(self, conn):
        cur = conn.execute("SELECT * FROM registered_users LIMIT 1")
        keys = _col_names(cur)
        assert "email" in keys
        assert "role" in keys
