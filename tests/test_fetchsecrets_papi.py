"""De-Vault (PLAT-SEC-001): fetchsecrets resolves workspace secrets from PAPI."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from RW import fetchsecrets


@pytest.fixture(autouse=True)
def _no_papi_env(monkeypatch):
    monkeypatch.delenv("RW_SECRETS_SOURCE", raising=False)
    monkeypatch.delenv("RW_PAPI_URL", raising=False)


def test_default_provider_is_vault_without_config():
    assert fetchsecrets._default_provider() == "runwhen-vault"


def test_default_provider_follows_the_deployment(monkeypatch):
    # The whole point: an un-prefixed read_secret() call resolves from PAPI with
    # no codebundle change, just because the deployment says so.
    monkeypatch.setenv("RW_SECRETS_SOURCE", "papi")
    assert fetchsecrets._default_provider() == "papi"


def test_fetch_papi_secret_resolves_and_builds_the_right_request(monkeypatch):
    monkeypatch.setenv("RW_PAPI_URL", "http://papi:8000/")  # trailing slash trimmed
    monkeypatch.setattr(fetchsecrets, "WORKSPACE_NAME", "acme")
    rsp = MagicMock(status_code=200)
    rsp.json.return_value = {"secrets": {"DB_PW": "s3cret"}}
    with patch.object(fetchsecrets.requests, "post", return_value=rsp) as post:
        assert fetchsecrets._fetch_papi_secret("DB_PW") == "s3cret"
    _, kwargs = post.call_args
    assert kwargs["url"] == "http://papi:8000/internal/api/v1/runner/secrets/resolve"
    assert kwargs["json"] == {"workspace": "acme", "keys": ["DB_PW"]}


def test_fetch_papi_secret_missing_key_raises_not_found(monkeypatch):
    monkeypatch.setenv("RW_PAPI_URL", "http://papi:8000")
    monkeypatch.setattr(fetchsecrets, "WORKSPACE_NAME", "acme")
    rsp = MagicMock(status_code=200)
    rsp.json.return_value = {"secrets": {}}
    with patch.object(fetchsecrets.requests, "post", return_value=rsp):
        with pytest.raises(fetchsecrets.SecretNotFoundError):
            fetchsecrets._fetch_papi_secret("MISSING")


def test_fetch_papi_secret_503_is_not_treated_as_absent(monkeypatch):
    # A source that cannot serve (e.g. PAPI still in a vault-read mode) must fail
    # loudly, never look like an absent secret.
    monkeypatch.setenv("RW_PAPI_URL", "http://papi:8000")
    monkeypatch.setattr(fetchsecrets, "WORKSPACE_NAME", "acme")
    rsp = MagicMock(status_code=503, text="source unavailable")
    with patch.object(fetchsecrets.requests, "post", return_value=rsp):
        with pytest.raises(fetchsecrets.SecretNotFoundError, match="unavailable"):
            fetchsecrets._fetch_papi_secret("K")


def test_fetch_papi_secret_requires_a_url(monkeypatch):
    monkeypatch.setattr(fetchsecrets, "WORKSPACE_NAME", "acme")
    with pytest.raises(fetchsecrets.AuthenticationError):
        fetchsecrets._fetch_papi_secret("K")


def test_health_check_passes_with_papi_config(monkeypatch):
    # No Vault env at all -- proving the PAPI path does not require it.
    monkeypatch.setenv("RW_SECRETS_SOURCE", "papi")
    monkeypatch.setenv("RW_PAPI_URL", "http://papi:8000")
    monkeypatch.setattr(fetchsecrets, "WORKSPACE_NAME", "acme")
    fetchsecrets.health_check()  # must not raise
