"""Central configuration and startup validation.

Every secret in this project used to be read with a literal fallback:

    JWT_SECRET = os.getenv("JWT_SECRET_KEY", "capstone2-jwt-secret-change-in-prod")

That is convenient on a laptop and dangerous anywhere else — deploy without the
variable set and the signing key is a string published in the README, so anyone
can mint an admin token. This module keeps the convenience in development and
removes the danger in production by refusing to start.

Set ``APP_ENV=production`` when hosting. Every problem is collected and raised
in one message, so you fix the whole list in one pass rather than discovering
the next missing variable on the next restart.
"""

import os
import secrets as _secrets

from dotenv import load_dotenv

# override=False so a real environment variable always beats a .env file that
# happens to be baked into an image. The orchestrator must have the last word.
# DOTENV_DISABLE ignores the file entirely — for a container that should be
# configured only by its environment, and for tests that need a bare slate.
if os.getenv("DOTENV_DISABLE", "").strip().lower() not in ("1", "true", "yes"):
    load_dotenv(override=False)

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"

# Plain HTTP for public URLs is a mistake in production, but an internal-only
# deployment behind someone else's TLS may legitimately want it. Opt in loudly.
ALLOW_INSECURE_HTTP = os.getenv("ALLOW_INSECURE_HTTP", "").strip().lower() in (
    "1", "true", "yes")

_MIN_SECRET_LEN = 32

# Values shipped in .env.sample and this repo's history. Treat them as public.
_PUBLISHED = {
    "capstone2-jwt-secret-change-in-prod",
    "capstone2-frontend-secret",
    "change-this-to-a-random-secret-for-frontend-signing",
    "change_me_in_production",
    "admin2026", "manager2026", "associate2026",
    "manager123", "associate123",
    "changeme", "change-me", "secret", "password",
}

_problems = []


def _fail(msg):
    _problems.append(msg)


def secret(name, dev_default, min_len=_MIN_SECRET_LEN):
    """Resolve a secret. Strict in production, forgiving on a laptop.

    In production the value must be present, must not be one of the strings
    published in this repo, and must be long enough to be worth brute-forcing.
    """
    value = (os.getenv(name) or "").strip()
    if not IS_PRODUCTION:
        return value or dev_default
    if not value:
        _fail(f"{name} is not set. Generate one with: python -c "
              f"\"import secrets;print(secrets.token_urlsafe(48))\"")
        return value
    if value.lower() in _PUBLISHED:
        _fail(f"{name} is set to a value published in this repository. "
              f"It is public — choose a new one.")
    elif len(value) < min_len:
        _fail(f"{name} is {len(value)} characters; at least {min_len} are "
              f"required in production.")
    return value


def password(name, dev_default):
    """Same as secret() but for human-typed passwords, which are shorter."""
    return secret(name, dev_default, min_len=12)


def public_url(name, default_port):
    """The URL a *browser* uses to reach a service.

    Cross-app links and CORS are built from these. Hardcoding localhost meant
    every link broke the moment the app was not running on the viewer's own
    machine, so in production these must be stated explicitly.
    """
    value = (os.getenv(name) or "").strip().rstrip("/")
    if not value:
        if IS_PRODUCTION:
            _fail(f"{name} is not set. Cross-app links would point at "
                  f"localhost:{default_port} and break for every user. "
                  f"Set it to the URL browsers actually use.")
        return f"http://localhost:{default_port}"
    if (IS_PRODUCTION and value.startswith("http://")
            and not ALLOW_INSECURE_HTTP):
        _fail(f"{name} uses plain http://. Session tokens would travel "
              f"unencrypted. Use https://, or set ALLOW_INSECURE_HTTP=true if "
              f"this is an internal network you have already secured.")
    return value


# ── secrets ───────────────────────────────────────────────────────────────────

JWT_SECRET = secret("JWT_SECRET_KEY", "capstone2-jwt-secret-change-in-prod")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

FRONTEND_SECRET = secret("FRONTEND_TOKEN_SECRET", "capstone2-frontend-secret")

ADMIN_PASSWORD = password("ADMIN_PASSWORD", "admin2026")
MANAGER_PASSWORD = password("MANAGER_PASSWORD", "manager2026")
ASSOCIATE_PASSWORD = password("ASSOCIATE_PASSWORD", "associate2026")

# ── public addresses ──────────────────────────────────────────────────────────

CUSTOMER_URL = public_url("PUBLIC_CUSTOMER_URL", 8501)
ASSOCIATES_URL = public_url("PUBLIC_ASSOCIATES_URL", 8502)
API_URL = public_url("PUBLIC_API_URL", 8503)


def cors_origins():
    """Origins allowed to call the API.

    Explicit CORS_ORIGINS wins; otherwise derive from the public URLs so the
    two stay in step instead of drifting apart.
    """
    raw = (os.getenv("CORS_ORIGINS") or "").strip()
    if raw:
        return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    origins = [CUSTOMER_URL, ASSOCIATES_URL, API_URL]
    if not IS_PRODUCTION:
        origins += [f"http://127.0.0.1:{p}" for p in (8501, 8502, 8503)]
    return sorted(set(origins))


# ── lockout policy ────────────────────────────────────────────────────────────

MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
LOCKOUT_SECONDS = int(os.getenv("LOCKOUT_SECONDS", "300"))

# Seconds a cross-app handoff link stays valid. Deliberately tiny: the token
# rides in a URL, so it should be useless by the time it reaches a log file.
HANDOFF_TTL_SECONDS = int(os.getenv("HANDOFF_TTL_SECONDS", "60"))


def generate_secret():
    return _secrets.token_urlsafe(48)


def validate():
    """Raise if anything is misconfigured. Called at import; safe to re-call."""
    if _problems:
        raise RuntimeError(
            "Refusing to start: APP_ENV=production but the configuration is "
            "not production-safe.\n\n  - "
            + "\n  - ".join(_problems)
            + "\n\nSee .env.sample and the Hosting section of README.md."
        )


validate()
