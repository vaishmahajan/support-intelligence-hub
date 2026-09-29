"""
Anti-Scraping & Security Middleware for Capstone2 API

Blocks requests from curl, wget, scrapy, and other automation tools.
Validates a frontend-injected signature header (X-Frontend-Token)
to ensure requests originate from the Streamlit dashboards.
"""

import hashlib
import hmac
import os
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config import FRONTEND_SECRET  # validated at startup, no silent fallback

BLOCKED_AGENTS = [
    "curl", "wget", "httpie", "scrapy", "python-requests",
    "python-urllib", "go-http-client", "java/", "okhttp",
    "postman", "insomnia", "bot", "spider", "crawl",
]

OPEN_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


def generate_frontend_token(timestamp: str) -> str:
    msg = f"capstone2:{timestamp}".encode()
    return hmac.new(FRONTEND_SECRET.encode(), msg, hashlib.sha256).hexdigest()[:32]


class AntiScrapingMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in OPEN_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        ua = (request.headers.get("user-agent") or "").lower()
        for blocked in BLOCKED_AGENTS:
            if blocked in ua:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Forbidden: automated access is not permitted.",
                        "code": "BLOCKED_CLIENT",
                    },
                )

        if not ua or len(ua) < 20:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Forbidden: missing or invalid client identifier.",
                    "code": "INVALID_UA",
                },
            )

        fe_token = request.headers.get("x-frontend-token")
        fe_ts = request.headers.get("x-frontend-ts")

        if path.startswith("/api/") and path not in OPEN_PATHS:
            if not fe_token or not fe_ts:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Forbidden: missing frontend authentication.",
                        "code": "NO_FRONTEND_TOKEN",
                    },
                )

            try:
                ts_int = int(fe_ts)
                now = int(time.time())
                if abs(now - ts_int) > 300:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": "Forbidden: request token expired.",
                            "code": "TOKEN_EXPIRED",
                        },
                    )
            except ValueError:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Forbidden: invalid timestamp.",
                        "code": "INVALID_TS",
                    },
                )

            expected = generate_frontend_token(fe_ts)
            if not hmac.compare_digest(fe_token, expected):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Forbidden: invalid frontend token.",
                        "code": "BAD_TOKEN",
                    },
                )

        return await call_next(request)
