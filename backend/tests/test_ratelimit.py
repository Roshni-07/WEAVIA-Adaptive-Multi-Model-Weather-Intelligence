"""Rate limiter and security headers. Self-contained: needs no pipeline artifacts."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from weavia.api.ratelimit import RateLimitMiddleware


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def make(limit=3, lab_limit=2, trust_proxy=False, proxy_hops=1):
    clock = Clock()
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limit=limit, lab_limit=lab_limit, trust_proxy=trust_proxy, proxy_hops=proxy_hops, clock=clock)

    @app.get("/api/v1/health")
    def health():
        return {"ok": True}

    @app.get("/api/v1/thing")
    def thing():
        return {"ok": True}

    @app.post("/api/v1/lab/simulate")
    def lab():
        return {"ok": True}

    return TestClient(app), clock


def test_blocks_after_limit_with_retry_after():
    c, _ = make(limit=3)
    assert [c.get("/api/v1/thing").status_code for _ in range(3)] == [200, 200, 200]
    r = c.get("/api/v1/thing")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert r.json()["retry_after_s"] >= 1


def test_window_slides_and_recovers():
    c, clock = make(limit=2)
    c.get("/api/v1/thing"); c.get("/api/v1/thing")
    assert c.get("/api/v1/thing").status_code == 429
    clock.t += 61
    assert c.get("/api/v1/thing").status_code == 200


def test_health_is_exempt():
    c, _ = make(limit=1)
    assert all(c.get("/api/v1/health").status_code == 200 for _ in range(10))


def test_lab_has_its_own_lower_limit():
    c, _ = make(limit=100, lab_limit=2)
    assert [c.post("/api/v1/lab/simulate").status_code for _ in range(3)] == [200, 200, 429]
    assert c.get("/api/v1/thing").status_code == 200


def test_limit_zero_disables():
    c, _ = make(limit=0, lab_limit=0)
    assert all(c.get("/api/v1/thing").status_code == 200 for _ in range(50))


def test_forwarded_header_ignored_unless_proxy_trusted():
    c, _ = make(limit=1, trust_proxy=False)
    assert c.get("/api/v1/thing", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert c.get("/api/v1/thing", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429   # spoofing does not help


def test_forwarded_header_separates_clients_when_trusted():
    c, _ = make(limit=1, trust_proxy=True)
    assert c.get("/api/v1/thing", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert c.get("/api/v1/thing", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 200
    assert c.get("/api/v1/thing", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 429


def test_client_supplied_prefix_cannot_spoof_when_proxy_trusted():
    """The proxy appends the real client to the right. Anything the client put on the left is ignored."""
    c, _ = make(limit=1, trust_proxy=True, proxy_hops=1)
    assert c.get("/api/v1/thing", headers={"X-Forwarded-For": "6.6.6.6, 1.1.1.1"}).status_code == 200
    assert c.get("/api/v1/thing", headers={"X-Forwarded-For": "7.7.7.7, 1.1.1.1"}).status_code == 429


def test_two_trusted_hops_use_second_from_right():
    c, _ = make(limit=1, trust_proxy=True, proxy_hops=2)
    assert c.get("/api/v1/thing", headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.1"}).status_code == 200
    assert c.get("/api/v1/thing", headers={"X-Forwarded-For": "8.8.8.8, 1.1.1.1, 10.0.0.9"}).status_code == 429


def test_missing_forwarded_header_falls_back_to_peer():
    c, _ = make(limit=1, trust_proxy=True)
    assert c.get("/api/v1/thing").status_code == 200
    assert c.get("/api/v1/thing").status_code == 429


def test_security_headers_on_ok_and_blocked_responses():
    c, _ = make(limit=1)
    for r in (c.get("/api/v1/thing"), c.get("/api/v1/thing")):
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "no-referrer"
