from fastapi.testclient import TestClient

from autoresearch.api.main import create_app
from autoresearch.cli import run_key_revoke
from autoresearch.security import hash_api_key


def test_database_api_key_auth_and_project_scope(test_settings, db):
    allowed = db.insert(
        f"INSERT INTO projects (name, question) VALUES ({db.ph}, {db.ph})", ["allowed", "q"]
    )
    blocked = db.insert(
        f"INSERT INTO projects (name, question) VALUES ({db.ph}, {db.ph})", ["blocked", "q"]
    )
    secret = "ar_live_test_secret"
    prefix = secret[:16]
    db.insert(
        f"INSERT INTO api_keys (key_prefix, key_hash, label, project_id) "
        f"VALUES ({db.ph}, {db.ph}, {db.ph}, {db.ph})",
        [prefix, hash_api_key(secret), "test", allowed],
    )
    with TestClient(create_app(test_settings)) as client:
        assert client.get("/projects").status_code == 401
        headers = {"X-API-Key": secret}
        assert client.get("/projects", headers=headers).json()[0]["id"] == allowed
        assert client.get(f"/projects/{blocked}", headers=headers).status_code == 403
        assert client.get(f"/projects/{allowed}", headers=headers).status_code == 200


def test_database_api_key_revoke_blocks_future_requests(test_settings, db):
    secret = "ar_live_revoke_test"
    prefix = secret[:16]
    db.insert(
        f"INSERT INTO api_keys (key_prefix, key_hash, label) VALUES ({db.ph}, {db.ph}, {db.ph})",
        [prefix, hash_api_key(secret), "revoke"],
    )
    assert run_key_revoke(prefix, settings=test_settings) == 0
    settings = test_settings.model_copy(update={"api_key": "bootstrap-secret"})
    with TestClient(create_app(settings)) as client:
        assert client.get("/projects", headers={"X-API-Key": secret}).status_code == 401


def test_database_api_key_uses_own_rate_limit(test_settings, db):
    secret = "ar_live_rate_limit_test"
    db.insert(
        f"INSERT INTO api_keys (key_prefix, key_hash, label, rate_limit_per_minute) "
        f"VALUES ({db.ph}, {db.ph}, {db.ph}, {db.ph})",
        [secret[:16], hash_api_key(secret), "rate", 1],
    )
    with TestClient(create_app(test_settings)) as client:
        headers = {"X-API-Key": secret}
        assert client.get("/projects", headers=headers).status_code == 200
        assert client.get("/projects", headers=headers).status_code == 429
