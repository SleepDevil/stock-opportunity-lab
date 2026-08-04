from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import mask_database_url
from app.services.learning_store import resolve_aidap_database_url


AIDAP_DATABASE_URL = (
    "postgresql://[fdbd:dc03:17:918:3300::2d]:4432/aidb?"
    "options=bytepg_compute_id%3Dcompute-123%20bytepg_auth_token%3D%24%7BToken%7D"
)


def test_resolve_aidap_database_url_injects_runtime_token(monkeypatch) -> None:
    monkeypatch.setenv("SEC_TOKEN_STRING", "header.payload.signature")

    resolved = resolve_aidap_database_url(AIDAP_DATABASE_URL)
    options = parse_qs(urlsplit(resolved).query)["options"][0]

    assert "${Token}" not in resolved
    assert options == "bytepg_compute_id=compute-123 bytepg_auth_token=header.payload.signature"


def test_resolve_aidap_database_url_reads_rotating_token_file(tmp_path, monkeypatch) -> None:
    token_path = tmp_path / "zti-token"
    token_path.write_text("rotating.jwt.token\n", encoding="utf-8")
    monkeypatch.delenv("SEC_TOKEN_STRING", raising=False)
    monkeypatch.delenv("Token", raising=False)
    monkeypatch.delenv("STOCK_LAB_AIDAP_TOKEN", raising=False)
    monkeypatch.setenv("SEC_TOKEN_PATH", str(token_path))

    resolved = resolve_aidap_database_url(AIDAP_DATABASE_URL)

    assert "rotating.jwt.token" in resolved


def test_resolve_aidap_database_url_requires_workload_identity(monkeypatch) -> None:
    for env_name in ("SEC_TOKEN_STRING", "Token", "STOCK_LAB_AIDAP_TOKEN", "SEC_TOKEN_PATH"):
        monkeypatch.delenv(env_name, raising=False)

    with pytest.raises(RuntimeError, match="SEC_TOKEN_PATH"):
        resolve_aidap_database_url(AIDAP_DATABASE_URL)


def test_non_aidap_database_url_is_unchanged(monkeypatch) -> None:
    monkeypatch.delenv("SEC_TOKEN_STRING", raising=False)

    url = "postgresql://user:password@example.com/stock_lab"

    assert resolve_aidap_database_url(url) == url


def test_mask_database_url_removes_credentials_and_aidap_options() -> None:
    assert mask_database_url(AIDAP_DATABASE_URL) == (
        "postgresql://***@[fdbd:dc03:17:918:3300::2d]:4432/aidb"
    )
    assert mask_database_url("postgresql://user:password@example.com/stock_lab?sslmode=require") == (
        "postgresql://***@example.com/stock_lab"
    )
