"""Per-client rate limiting and basic security headers for the public, read-only API.

Sliding window, in memory, per process. Good enough to blunt scraping and accidental loops on a single
instance; it is NOT a distributed limiter (use Redis or the hosting platform's limiter for multi-instance
deployments).

Client identity:
  * default: the socket peer address (safe when the API is exposed directly).
  * WEAVIA_TRUST_PROXY=1: the X-Forwarded-For entry added by YOUR proxy, counted from the right
    (WEAVIA_PROXY_HOPS, default 1 = the last entry). Entries further left are client-supplied and ignored,
    so a caller cannot spoof their way out of the limit. Needed when a proxy sits in front of the API,
    including the Next.js rewrite, which otherwise makes every user look like the Next server.

Environment:
  WEAVIA_RATE_LIMIT      requests per minute per client for all routes (default 120, 0 disables)
  WEAVIA_LAB_RATE_LIMIT  requests per minute per client for POST /api/v1/lab/simulate (default 20, 0 disables)
  WEAVIA_TRUST_PROXY     "1" to read X-Forwarded-For (default off)
  WEAVIA_PROXY_HOPS      trusted proxies in front of the API, counted from the right (default 1)
"""
from __future__ import annotations

import math
import os
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

WINDOW_S = 60.0
EXEMPT_PATHS = {"/api/v1/health"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit: int | None = None, lab_limit: int | None = None,
                 trust_proxy: bool | None = None, proxy_hops: int | None = None, clock=time.monotonic):
        super().__init__(app)
        self.limit = _int_env("WEAVIA_RATE_LIMIT", 120) if limit is None else limit
        self.lab_limit = _int_env("WEAVIA_LAB_RATE_LIMIT", 20) if lab_limit is None else lab_limit
        self.trust_proxy = (os.environ.get("WEAVIA_TRUST_PROXY") == "1") if trust_proxy is None else trust_proxy
        self.proxy_hops = max(1, _int_env("WEAVIA_PROXY_HOPS", 1)) if proxy_hops is None else max(1, proxy_hops)
        self.clock = clock
        self.hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self._last_sweep = clock()

    def _client(self, request: Request) -> str:
        if self.trust_proxy:
            parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
            if len(parts) >= self.proxy_hops:
                return parts[-self.proxy_hops]
        return request.client.host if request.client else "unknown"

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < WINDOW_S:
            return
        self._last_sweep = now
        for k in [k for k, q in self.hits.items() if not q or now - q[-1] > WINDOW_S]:
            del self.hits[k]

    def _check(self, bucket: str, client: str, limit: int, now: float):
        """Return None if allowed, else seconds to wait."""
        if limit <= 0:
            return None
        q = self.hits[(bucket, client)]
        while q and now - q[0] >= WINDOW_S:
            q.popleft()
        if len(q) >= limit:
            return max(1, math.ceil(WINDOW_S - (now - q[0])))
        q.append(now)
        return None

    async def dispatch(self, request: Request, call_next):
        if request.method != "OPTIONS" and request.url.path not in EXEMPT_PATHS:
            now = self.clock()
            self._sweep(now)
            client = self._client(request)
            wait = self._check("all", client, self.limit, now)
            if wait is None and request.method == "POST" and request.url.path.endswith("/lab/simulate"):
                wait = self._check("lab", client, self.lab_limit, now)
            if wait is not None:
                return JSONResponse({"detail": "Too many requests. Slow down and retry shortly.", "retry_after_s": wait},
                                    status_code=429, headers={"Retry-After": str(wait), **SECURITY_HEADERS})
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response
