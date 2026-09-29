"""Guards on the things that make this safe to host rather than just to demo.

Three properties are worth locking down, because all three fail silently:

1. A production deployment must refuse to start on a weak or missing secret,
   rather than quietly signing tokens with a key published in this repository.
2. Cross-app links must not carry a long-lived session credential in the URL.
3. Login lockout must not live in one process's memory.

The configuration tests run in a subprocess. `config` validates at import time,
which is the point — you cannot import it twice with different environments in
one interpreter.
"""
import json
import os
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
import login_guard  # noqa: E402
import workspace_utils as wu  # noqa: E402
from jose import jwt  # noqa: E402

STRONG = "u7Kd-9QpL2xR4vN8bT6yW3zA5cE1gH0jM-sF2dY4kP6q"

GOOD_ENV = {
    "APP_ENV": "production",
    "JWT_SECRET_KEY": STRONG,
    "FRONTEND_TOKEN_SECRET": STRONG,
    "ADMIN_PASSWORD": "Str0ng-Admin-Passphrase",
    "MANAGER_PASSWORD": "Str0ng-Mgr-Passphrase",
    "ASSOCIATE_PASSWORD": "Str0ng-Assoc-Passphrase",
    "PUBLIC_CUSTOMER_URL": "https://cust.example.com",
    "PUBLIC_ASSOCIATES_URL": "https://assoc.example.com",
    "PUBLIC_API_URL": "https://api.example.com",
}

_PROBE = (
    "import config, json;"
    "print('__OK__' + json.dumps({'cors': config.cors_origins(),"
    " 'customer': config.CUSTOMER_URL, 'prod': config.IS_PRODUCTION}))"
)


def _boot(**overrides):
    """Import config in a clean interpreter. Returns (ok, payload_or_stderr)."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("APP_ENV", "JWT_", "PUBLIC_", "CORS_", "ALLOW_"))}
    for k in ("ADMIN_PASSWORD", "MANAGER_PASSWORD", "ASSOCIATE_PASSWORD",
              "FRONTEND_TOKEN_SECRET"):
        env.pop(k, None)
    env.update({k: v for k, v in overrides.items() if v is not None})
    # A local .env would otherwise fill in the very values under test.
    env["DOTENV_DISABLE"] = "1"
    proc = subprocess.run([sys.executable, "-c", _PROBE], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    if proc.returncode == 0 and "__OK__" in proc.stdout:
        return True, json.loads(proc.stdout.split("__OK__", 1)[1].splitlines()[0])
    return False, proc.stderr


class TestProductionRefusesWeakConfig:
    def test_a_good_production_config_starts(self):
        ok, payload = _boot(**GOOD_ENV)
        assert ok, payload
        assert payload["prod"] is True

    def test_missing_jwt_secret_is_fatal(self):
        env = dict(GOOD_ENV)
        env.pop("JWT_SECRET_KEY")
        ok, err = _boot(**env)
        assert not ok
        assert "JWT_SECRET_KEY is not set" in err

    @pytest.mark.parametrize("var,value", [
        ("JWT_SECRET_KEY", "capstone2-jwt-secret-change-in-prod"),
        ("FRONTEND_TOKEN_SECRET", "capstone2-frontend-secret"),
        ("ADMIN_PASSWORD", "admin2026"),
    ])
    def test_values_published_in_this_repo_are_rejected(self, var, value):
        ok, err = _boot(**dict(GOOD_ENV, **{var: value}))
        assert not ok
        assert var in err and "published in this repository" in err

    def test_a_short_secret_is_rejected(self):
        ok, err = _boot(**dict(GOOD_ENV, JWT_SECRET_KEY="short-but-unique-xy"))
        assert not ok
        assert "at least 32" in err

    def test_every_problem_is_reported_at_once(self):
        """One restart per mistake is a bad way to configure a deployment."""
        env = dict(GOOD_ENV)
        for k in ("JWT_SECRET_KEY", "ADMIN_PASSWORD", "PUBLIC_CUSTOMER_URL"):
            env.pop(k)
        ok, err = _boot(**env)
        assert not ok
        for k in ("JWT_SECRET_KEY", "ADMIN_PASSWORD", "PUBLIC_CUSTOMER_URL"):
            assert k in err

    def test_plain_http_is_rejected_in_production(self):
        ok, err = _boot(**dict(GOOD_ENV, PUBLIC_CUSTOMER_URL="http://cust.internal"))
        assert not ok
        assert "plain http://" in err

    def test_plain_http_allowed_with_explicit_opt_in(self):
        ok, payload = _boot(**dict(GOOD_ENV, PUBLIC_CUSTOMER_URL="http://cust.internal",
                                   ALLOW_INSECURE_HTTP="true"))
        assert ok, payload

    def test_development_still_works_with_nothing_set(self):
        ok, payload = _boot(APP_ENV="development")
        assert ok, payload
        assert payload["customer"] == "http://localhost:8501"


class TestCorsFollowsThePublicUrls:
    def test_derived_from_public_urls(self):
        ok, payload = _boot(**GOOD_ENV)
        assert ok, payload
        assert payload["cors"] == sorted(
            {GOOD_ENV["PUBLIC_CUSTOMER_URL"], GOOD_ENV["PUBLIC_ASSOCIATES_URL"],
             GOOD_ENV["PUBLIC_API_URL"]})

    def test_no_localhost_leaks_into_production_cors(self):
        ok, payload = _boot(**GOOD_ENV)
        assert ok, payload
        assert not [o for o in payload["cors"] if "localhost" in o or "127.0.0.1" in o]

    def test_explicit_override_wins(self):
        ok, payload = _boot(**dict(GOOD_ENV, CORS_ORIGINS="https://a.example.com, https://b.example.com/"))
        assert ok, payload
        assert payload["cors"] == ["https://a.example.com", "https://b.example.com"]


class TestHandoffToken:
    def _session(self, minutes=60):
        now = int(time.time())
        return jwt.encode({"sub": "theo.krishnan@redhat.com", "role": "associate",
                           "typ": "session", "iat": now,
                           "exp": now + minutes * 60},
                          config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)

    def test_link_does_not_carry_the_session_token(self):
        sess = self._session()
        url = wu.build_switch_url("customer", sess)
        assert sess not in url, "the session credential is still in the URL"

    def test_handoff_is_short_lived(self):
        claims = jwt.decode(wu.mint_handoff(self._session()), config.JWT_SECRET,
                            algorithms=[config.JWT_ALGORITHM])
        assert claims["typ"] == "handoff"
        assert claims["exp"] - claims["iat"] <= config.HANDOFF_TTL_SECONDS

    def test_identity_is_preserved(self):
        claims = jwt.decode(wu.mint_handoff(self._session()), config.JWT_SECRET,
                            algorithms=[config.JWT_ALGORITHM])
        assert claims["sub"] == "theo.krishnan@redhat.com"
        assert claims["role"] == "associate"

    def test_handoff_does_not_inherit_a_remember_me_week(self):
        claims = jwt.decode(wu.mint_handoff(self._session(minutes=60 * 24 * 7)),
                            config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
        assert claims["exp"] - claims["iat"] <= config.HANDOFF_TTL_SECONDS

    def test_garbage_in_is_not_silently_signed(self):
        assert wu.mint_handoff("not-a-token") == "not-a-token"
        assert wu.mint_handoff("") == ""

    def test_switch_url_uses_the_configured_base(self):
        assert wu.build_switch_url("customer", "").startswith(config.CUSTOMER_URL)
        assert wu.build_switch_url("associate", "").startswith(config.ASSOCIATES_URL)


class TestApiRejectsDashboardTokens:
    def _token(self, typ):
        now = int(time.time())
        return jwt.encode({"sub": "admin", "role": "admin", "typ": typ,
                           "iat": now, "exp": now + 600},
                          config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)

    @pytest.mark.parametrize("typ", ["session", "handoff"])
    def test_dashboard_token_cannot_call_the_api(self, client, typ):
        h = dict(client.headers)
        h["Authorization"] = f"Bearer {self._token(typ)}"
        r = client.get("/api/v1/accounts", headers=h)
        assert r.status_code == 401, r.text

    def test_a_real_api_token_still_works(self, client, headers):
        assert client.get("/api/v1/accounts", headers=headers).status_code == 200


class TestLoginLockout:
    def setup_method(self):
        self.email = f"lockout-probe-{int(time.time() * 1000)}@redhat.com"

    def teardown_method(self):
        login_guard.clear(self.email)

    def test_clean_address_is_not_locked(self):
        assert login_guard.check(self.email) is None

    def test_locks_after_the_configured_number_of_failures(self):
        for _ in range(config.MAX_LOGIN_ATTEMPTS - 1):
            login_guard.record_failure(self.email)
        assert login_guard.check(self.email) is None, "locked too early"
        login_guard.record_failure(self.email)
        assert "Too many failed attempts" in login_guard.check(self.email)

    def test_a_successful_login_clears_the_count(self):
        for _ in range(config.MAX_LOGIN_ATTEMPTS):
            login_guard.record_failure(self.email)
        login_guard.clear(self.email)
        assert login_guard.check(self.email) is None

    def test_state_is_shared_not_process_local(self):
        """The whole point: a second process must see the same lockout."""
        if login_guard.backend() != "db":
            pytest.skip("no database available; lockout is memory-only here")
        for _ in range(config.MAX_LOGIN_ATTEMPTS):
            login_guard.record_failure(self.email)
        probe = (f"import login_guard;"
                 f"print('LOCKED' if login_guard.check({self.email!r}) else 'OPEN')")
        out = subprocess.run([sys.executable, "-c", probe], cwd=ROOT,
                             capture_output=True, text=True, timeout=120)
        assert "LOCKED" in out.stdout, out.stderr


def test_no_module_falls_back_to_a_hardcoded_secret():
    """config.py is the only place allowed to name a default secret."""
    import ast
    guarded = {"JWT_SECRET_KEY", "ADMIN_PASSWORD", "MANAGER_PASSWORD",
               "ASSOCIATE_PASSWORD", "ASSOCIATE_PASSWORD", "FRONTEND_TOKEN_SECRET",
               "POSTGRES_PASSWORD"}
    bad = []
    for name in os.listdir(ROOT):
        if not name.endswith(".py") or name == "config.py":
            continue
        tree = ast.parse(open(os.path.join(ROOT, name), encoding="utf-8").read())
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call)
                    and getattr(n.func, "attr", None) == "getenv"
                    and len(n.args) == 2
                    and isinstance(n.args[0], ast.Constant)
                    and n.args[0].value in guarded):
                bad.append(f"{name}:{n.lineno} ({n.args[0].value})")
    assert not bad, "secret read with a hardcoded fallback: " + ", ".join(bad)
