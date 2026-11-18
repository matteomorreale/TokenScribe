"""Startup and safety guards: CSRF origin check, reset refusal, secret key, reloader, crypto."""

import pytest
from cryptography.fernet import Fernet

import config
from app import create_app
from app.services.crypto_service import CryptoService


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.TestingConfig, "DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKENSCRIBE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("TOKENSCRIBE_DEBUG", raising=False)
    return create_app("testing")


def _add_item(app, status):
    conn = app.config["DB"].get_connection()
    conn.execute("PRAGMA foreign_keys = OFF")  # no experiment_runs row needed here
    conn.execute(
        "INSERT INTO run_queue (run_id, operation_type, item_key, status) VALUES (1, 'llm_call', 'k', ?)",
        (status,),
    )
    conn.commit()
    conn.close()


def _queue_rows(app):
    conn = app.config["DB"].get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM run_queue").fetchone()[0]
    finally:
        conn.close()


def test_cross_site_post_is_rejected(app):
    c = app.test_client()
    form = {"magi_judge_balthasar_id": "1"}
    assert c.post("/settings/magi-judges", data=form, headers={"Origin": "http://evil.example"}).status_code == 403
    assert c.post("/settings/magi-judges", data=form, headers={"Origin": "http://localhost"}).status_code == 302
    assert c.post("/settings/magi-judges", data=form).status_code == 302  # no Origin: not a browser


def test_reset_is_refused_while_items_run(app):
    _add_item(app, "running")
    r = app.test_client().post("/settings/reset-db", data={"confirm_reset": "RESET"})
    assert r.status_code == 302
    assert _queue_rows(app) == 1  # tables were not dropped


def test_reset_wipes_when_idle(app):
    _add_item(app, "done")
    app.test_client().post("/settings/reset-db", data={"confirm_reset": "RESET"})
    assert _queue_rows(app) == 0


def test_production_refuses_to_start_without_secret_key(monkeypatch):
    monkeypatch.setattr(config.ProductionConfig, "SECRET_KEY", None)
    with pytest.raises(RuntimeError):
        create_app("production")


def test_reloader_parent_does_not_start_the_queue(app, tmp_path, monkeypatch):
    monkeypatch.setenv("TOKENSCRIBE_DEBUG", "1")
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    monkeypatch.setattr(config.TestingConfig, "DATABASE_PATH", str(tmp_path / "parent.db"))
    assert "QUEUE_SERVICE" not in create_app("testing").config
    monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")
    monkeypatch.setattr(config.TestingConfig, "DATABASE_PATH", str(tmp_path / "child.db"))
    assert "QUEUE_SERVICE" in create_app("testing").config


def test_crypto_roundtrip_wrong_key_and_legacy_plaintext(monkeypatch):
    monkeypatch.setenv("TOKENSCRIBE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token = CryptoService().encrypt("sk-secret")
    assert token != "sk-secret" and CryptoService().decrypt(token) == "sk-secret"
    assert CryptoService().decrypt("old-plain-key") == "old-plain-key"
    monkeypatch.setenv("TOKENSCRIBE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert CryptoService().decrypt(token) == ""  # key changed: "not configured", never the raw token
