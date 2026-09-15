from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.base import ProviderPost
from app.providers.mock import MockFacebookProvider
from tests.conftest import TEST_API_KEY

AUTH = {"Authorization": f"Bearer {TEST_API_KEY}"}


@pytest.fixture
def provider_holder(clock):
    return {"provider": MockFacebookProvider(clock=clock)}


@pytest.fixture
def client(settings, session_factory, provider_holder, clock):
    app = create_app(
        settings,
        session_factory=session_factory,
        provider_factory=lambda _s: provider_holder["provider"],
        clock=clock,
        setup_logging=False,
    )
    with TestClient(app) as test_client:
        yield test_client


def _create_source(client, **overrides):
    payload = {
        "source_type": "page",
        "source_name": "Example Page",
        "source_identifier": "examplepage",
        "source_url": "https://www.facebook.com/examplepage",
    } | overrides
    response = client.post("/api/v1/sources", json=payload, headers=AUTH)
    assert response.status_code == 201, response.text
    return response.json()


# --- health / auth -------------------------------------------------------------
def test_health_is_public(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    assert response.json()["data_provider"] == "mock"


@pytest.mark.parametrize(
    "path", ["/api/v1/sources", "/api/v1/posts", "/api/v1/collection/runs", "/api/v1/export/csv"]
)
def test_protected_endpoints_require_api_key(client, path):
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Bearer"


def test_wrong_api_key_is_rejected(client):
    response = client.post("/api/v1/collection/run", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_non_bearer_scheme_is_rejected(client):
    response = client.get("/api/v1/sources", headers={"Authorization": f"Basic {TEST_API_KEY}"})
    assert response.status_code == 401


def test_endpoints_disabled_when_api_key_not_configured(settings, session_factory):
    settings.internal_api_key = None
    app = create_app(settings, session_factory=session_factory, setup_logging=False)
    with TestClient(app) as c:
        response = c.get("/api/v1/sources", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CONFIGURATION_ERROR"


def test_api_key_never_appears_in_responses(client):
    for path in ("/health", "/api/v1/sources", "/api/v1/provider/health"):
        assert TEST_API_KEY not in client.get(path, headers=AUTH).text


# --- sources -------------------------------------------------------------------
def test_source_crud(client):
    created = _create_source(client)
    assert created["active"] is True
    assert created["last_collected_at"] is None

    listed = client.get("/api/v1/sources", headers=AUTH).json()
    assert [s["id"] for s in listed] == [created["id"]]

    patched = client.patch(
        f"/api/v1/sources/{created['id']}",
        json={"active": False, "source_name": "Renamed"},
        headers=AUTH,
    )
    assert patched.status_code == 200
    assert patched.json()["active"] is False
    assert patched.json()["source_name"] == "Renamed"

    assert client.get("/api/v1/sources?active=true", headers=AUTH).json() == []

    assert client.delete(f"/api/v1/sources/{created['id']}", headers=AUTH).status_code == 204
    assert client.get(f"/api/v1/sources/{created['id']}", headers=AUTH).status_code == 404


def test_duplicate_source_returns_409(client):
    _create_source(client)
    response = client.post(
        "/api/v1/sources",
        json={"source_type": "page", "source_name": "Again", "source_identifier": "examplepage"},
        headers=AUTH,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


@pytest.mark.parametrize(
    "payload",
    [
        {"source_type": "profile", "source_name": "x", "source_identifier": "x"},
        {"source_type": "page", "source_name": "", "source_identifier": "x"},
        {"source_type": "page", "source_name": "x", "source_identifier": "has spaces"},
        {"source_type": "page", "source_name": "x", "source_identifier": "../etc"},
        {
            "source_type": "page",
            "source_name": "x",
            "source_identifier": "x",
            "source_url": "ftp://x",
        },
        {"source_type": "page", "source_name": "x", "source_identifier": "x", "unexpected": 1},
    ],
)
def test_invalid_source_payloads_return_422(client, payload):
    response = client.post("/api/v1/sources", json=payload, headers=AUTH)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_validate_source_endpoint(client):
    ok = _create_source(client)
    bad = _create_source(client, source_identifier="mock-permission-denied")
    assert client.post(f"/api/v1/sources/{ok['id']}/validate", headers=AUTH).json()["ok"] is True
    body = client.post(f"/api/v1/sources/{bad['id']}/validate", headers=AUTH).json()
    assert body["ok"] is False
    assert body["error_code"] == "PERMISSION_DENIED"


# --- collection ----------------------------------------------------------------
def test_trigger_collection_and_no_duplicates_on_rerun(client, clock):
    _create_source(client, source_type="group", source_identifier="ai-jobs")

    first = client.post("/api/v1/collection/run", headers=AUTH)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "success"
    assert body["posts_saved"] > 0
    assert body["sources"][0]["status"] == "success"

    clock.advance(minutes=1)
    second = client.post("/api/v1/collection/run", headers=AUTH).json()
    assert second["posts_saved"] == 0

    total = client.get("/api/v1/posts", headers=AUTH).json()["total"]
    assert total == body["posts_saved"]


def test_trigger_collection_with_json_body(client):
    a = _create_source(client, source_identifier="page-a")
    _create_source(client, source_identifier="page-b")
    body = client.post(
        "/api/v1/collection/run", json={"source_ids": [a["id"]]}, headers=AUTH
    ).json()
    assert [s["source_id"] for s in body["sources"]] == [a["id"]]


def test_partial_success_returns_200_and_failed_returns_502(client):
    _create_source(client, source_identifier="good")
    bad = _create_source(client, source_identifier="mock-token-expired")
    partial = client.post("/api/v1/collection/run", headers=AUTH)
    assert partial.status_code == 200
    assert partial.json()["status"] == "partial_success"

    failed = client.post("/api/v1/collection/run", json={"source_ids": [bad["id"]]}, headers=AUTH)
    assert failed.status_code == 502
    assert failed.json()["status"] == "failed"
    assert failed.json()["sources"][0]["error_code"] == "TOKEN_EXPIRED"


def test_runs_listing_and_detail(client):
    _create_source(client, source_identifier="good")
    _create_source(client, source_identifier="mock-invalid")
    run_id = client.post("/api/v1/collection/run", headers=AUTH).json()["id"]

    runs = client.get("/api/v1/collection/runs", headers=AUTH).json()
    assert runs["total"] == 1
    assert runs["items"][0]["status"] == "partial_success"

    detail = client.get(f"/api/v1/collection/runs/{run_id}", headers=AUTH).json()
    assert detail["errors"][0]["error_code"] == "INVALID_SOURCE"
    assert client.get("/api/v1/collection/runs/999", headers=AUTH).status_code == 404


def test_provider_health_endpoint(client):
    body = client.get("/api/v1/provider/health", headers=AUTH).json()
    assert body == {
        "ok": True,
        "provider": "mock",
        "message": "Mock provider is always healthy.",
        "details": {},
    }


# --- posts -----------------------------------------------------------------------
@pytest.fixture
def seeded(client, provider_holder, clock):
    now = clock.now
    posts = {
        "page-a": [
            ProviderPost("a1", now - timedelta(hours=1), "Hiring a data scientist"),
            ProviderPost("a2", now - timedelta(hours=20), "Need a Python developer"),
        ],
        "group-b": [ProviderPost("b1", now - timedelta(hours=5), "Looking for an AI engineer")],
    }
    provider_holder["provider"] = MockFacebookProvider(clock=clock, posts_by_source=posts)
    a = _create_source(client, source_identifier="page-a", source_name="Page A")
    b = _create_source(
        client, source_type="group", source_identifier="group-b", source_name="Group B"
    )
    assert client.post("/api/v1/collection/run", headers=AUTH).json()["posts_saved"] == 3
    return {"a": a, "b": b, "now": now}


def test_posts_list_pagination(client, seeded):
    page1 = client.get("/api/v1/posts?page=1&page_size=2", headers=AUTH).json()
    page2 = client.get("/api/v1/posts?page=2&page_size=2", headers=AUTH).json()
    assert page1["total"] == 3 and page1["pages"] == 2
    assert len(page1["items"]) == 2 and len(page2["items"]) == 1
    assert page1["items"][0]["text"] == "Hiring a data scientist"  # newest first
    assert page1["items"][0]["posted_at"].endswith("Z")


def test_posts_filters(client, seeded):
    def texts(query):
        return {
            p["text"] for p in client.get(f"/api/v1/posts?{query}", headers=AUTH).json()["items"]
        }

    assert texts(f"source_id={seeded['a']['id']}") == {
        "Hiring a data scientist",
        "Need a Python developer",
    }
    assert texts("source_type=group") == {"Looking for an AI engineer"}
    start = (seeded["now"] - timedelta(hours=6)).isoformat().replace("+00:00", "Z")
    assert texts(f"start_date={start}") == {"Hiring a data scientist", "Looking for an AI engineer"}
    assert texts("end_date=2026-09-13") == {"Need a Python developer"}  # whole day included
    assert texts("end_date=2026-09-12") == set()
    assert len(texts("start_date=2026-09-14&end_date=2026-09-14")) == 2  # whole-day end bound


def test_posts_invalid_filters(client, seeded):
    assert client.get("/api/v1/posts?start_date=yesterday", headers=AUTH).status_code == 422
    assert (
        client.get(
            "/api/v1/posts?start_date=2026-09-15&end_date=2026-09-14", headers=AUTH
        ).status_code
        == 422
    )
    assert client.get("/api/v1/posts?page_size=1000", headers=AUTH).status_code == 422


def test_get_single_post(client, seeded):
    post = client.get("/api/v1/posts", headers=AUTH).json()["items"][0]
    assert client.get(f"/api/v1/posts/{post['id']}", headers=AUTH).json() == post
    assert client.get("/api/v1/posts/9999", headers=AUTH).status_code == 404


# --- export ----------------------------------------------------------------------
def test_export_csv_endpoint(client, seeded):
    response = client.get("/api/v1/export/csv?source_type=page", headers=AUTH)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    lines = response.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0] == "source_name,source_type,posted_at,text"
    assert len(lines) == 3


def test_export_json_endpoint(client, seeded):
    rows = client.get("/api/v1/export/json", headers=AUTH).json()
    assert len(rows) == 3
    assert set(rows[0]) == {"source_name", "source_type", "posted_at", "text"}


# --- security --------------------------------------------------------------------
def test_request_body_size_limit(client, settings):
    big = "x" * (settings.max_request_body_bytes + 10)
    response = client.post(
        "/api/v1/sources", content=big, headers={**AUTH, "Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_cors_only_for_configured_origins(settings, session_factory):
    settings.cors_allowed_origins = "http://localhost:5678"
    app = create_app(settings, session_factory=session_factory, setup_logging=False)
    with TestClient(app) as c:
        allowed = c.options(
            "/api/v1/sources",
            headers={"Origin": "http://localhost:5678", "Access-Control-Request-Method": "GET"},
        )
        denied = c.options(
            "/api/v1/sources",
            headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
        )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5678"
    assert "access-control-allow-origin" not in denied.headers


def test_unknown_route_uses_error_envelope(client):
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"
