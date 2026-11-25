"""Customer Vault providers (SECRET_PROVIDER_<NAME>_TYPE=vault) after platform Vault removal.

The worker's platform Vault token (VAULT_TOKEN_FILE / VAULT_TOKEN) must never be
presented to a customer's Vault server: customer providers authenticate with
their own AppRole credentials only.
"""

import json
import os
import sys
from unittest.mock import patch

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from RW import fetchsecrets

PLATFORM_TOKEN = "platform-token"
CUSTOMER_TOKEN = "customer-approle-token"


@pytest.fixture
def customer_vault_env(monkeypatch, tmp_path):
    token_file = tmp_path / "vault-token"
    token_file.write_text(PLATFORM_TOKEN)
    monkeypatch.setenv("VAULT_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("VAULT_TOKEN", PLATFORM_TOKEN)

    monkeypatch.setenv("SECRET_PROVIDER_acme_TYPE", "vault")
    monkeypatch.setenv("SECRET_PROVIDER_acme_VAULT_ADDR", "https://vault.acme.example")
    monkeypatch.setenv("SECRET_PROVIDER_acme_VAULT_AUTH_MOUNT_PATH", "approle")
    monkeypatch.setenv("SECRET_PROVIDER_acme_VAULT_APPROLE_ROLE_ID", "acme-role")
    monkeypatch.setenv("SECRET_PROVIDER_acme_VAULT_APPROLE_SECRET_ID", "acme-secret")

    monkeypatch.setenv("RW_SECRETS_KEYS", "{}")
    monkeypatch.setattr(fetchsecrets, "_cache", {})
    with patch("robot.libraries.BuiltIn.BuiltIn"):
        yield


def _json_response(payload):
    rsp = requests.Response()
    rsp.status_code = 200
    rsp.headers["Content-Type"] = "application/json"
    rsp._content = json.dumps(payload).encode()
    return rsp


@pytest.mark.parametrize("platform_token_source", ["VAULT_TOKEN", "~/.vault-token"])
def test_customer_vault_login_never_uses_platform_token(
    customer_vault_env, monkeypatch, tmp_path, platform_token_source
):
    # The real hvac.Client runs here: hvac falls back to VAULT_TOKEN, then
    # ~/.vault-token, when no token is passed, so a stub client would hide a leak.
    # VAULT_TOKEN_FILE is set by the fixture in both cases.
    if platform_token_source == "~/.vault-token":
        monkeypatch.delenv("VAULT_TOKEN")
        (tmp_path / ".vault-token").write_text(PLATFORM_TOKEN)
        monkeypatch.setenv("HOME", str(tmp_path))

    sent = []

    def fake_request(session, method, url, **kwargs):
        headers = {**session.headers, **(kwargs.get("headers") or {})}
        sent.append((method.upper(), url, headers))
        if url.endswith("/v1/auth/approle/login"):
            return _json_response({"auth": {"client_token": CUSTOMER_TOKEN}})
        if url == "https://vault.acme.example/v1/secret/data/x":
            return _json_response({"data": {"data": {"value": "s3cr3t"}}})
        raise AssertionError(f"unexpected request {method} {url}")

    with patch.object(requests.Session, "request", autospec=True, side_effect=fake_request):
        assert fetchsecrets.read_secret("acme@secret/data/x:value") == "s3cr3t"

    assert [(m, u) for m, u, _ in sent] == [
        ("POST", "https://vault.acme.example/v1/auth/approle/login"),
        ("GET", "https://vault.acme.example/v1/secret/data/x"),
    ]
    for _, url, headers in sent:
        assert PLATFORM_TOKEN not in headers.values(), url
    assert "X-Vault-Token" not in sent[0][2]  # AppRole login carries no token
    assert sent[1][2]["X-Vault-Token"] == CUSTOMER_TOKEN


@pytest.mark.parametrize("name", ["_kubernetes_vault_login", "_try_cached_token_login", "VAULT_TOKEN_TTL"])
def test_no_platform_vault_symbols(name):
    assert not hasattr(fetchsecrets, name)
