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
    monkeypatch.setenv("RW_ACCESS_TOKEN", "run-token")


def _papi_response(secrets):
    rsp = MagicMock(status_code=200)
    rsp.json.return_value = {"secrets": secrets}
    return rsp


@pytest.fixture
def papi_read_env(monkeypatch):
    """Env for an end-to-end read_secret() against a mocked PAPI resolver."""
    monkeypatch.setenv("RW_PAPI_URL", "http://papi:8000")
    monkeypatch.setenv("RW_SECRETS_KEYS", "{}")
    monkeypatch.setattr(fetchsecrets, "WORKSPACE_NAME", "acme")
    monkeypatch.setattr(fetchsecrets, "_cache", {})
    with patch("robot.libraries.BuiltIn.BuiltIn"):
        yield


def test_default_provider_is_papi_without_config(papi_read_env):
    # RW_SECRETS_SOURCE unset: an un-prefixed key resolves via PAPI.
    with patch.object(fetchsecrets.requests, "post", return_value=_papi_response({"my-key": "v1"})) as post:
        assert fetchsecrets.read_secret("my-key") == "v1"
    assert post.call_count == 1
    assert post.call_args.kwargs["json"] == {"workspace": "acme", "keys": ["my-key"]}


def test_runwhen_vault_prefix_resolves_via_papi(papi_read_env):
    # Existing codebundles that say runwhen-vault@ keep working, but via PAPI:
    # no Vault client may be constructed.
    with patch.object(fetchsecrets.hvac, "Client", side_effect=AssertionError("hvac.Client constructed")), \
         patch.object(fetchsecrets.requests, "get", side_effect=AssertionError("Vault HTTP read")), \
         patch.object(fetchsecrets.requests, "post", return_value=_papi_response({"my-key": "v2"})) as post:
        assert fetchsecrets.read_secret("runwhen-vault@my-key") == "v2"
    assert post.call_count == 1
    assert post.call_args.kwargs["json"]["keys"] == ["my-key"]


def test_rw_secrets_source_vault_is_deprecated_and_ignored(monkeypatch, caplog):
    monkeypatch.setenv("RW_SECRETS_SOURCE", "vault")
    monkeypatch.setattr(fetchsecrets, "_vault_source_deprecation_logged", False)
    with caplog.at_level("WARNING", logger=fetchsecrets.logger.name):
        assert fetchsecrets._secrets_source() == "papi"
        assert fetchsecrets._default_provider() == "papi"
    msgs = [r.getMessage() for r in caplog.records]
    assert msgs.count("RW_SECRETS_SOURCE=vault is deprecated; using papi") == 1


def test_service_account_keys_via_papi(papi_read_env, monkeypatch):
    # platform.form_access_token() falls back to the SA credentials when the
    # runner provides no RW_ACCESS_TOKEN; both keys must be read from PAPI.
    import importlib

    # Production path. Other test modules may leave RW.platform loaded in dev
    # mode (no fetchsecrets/backoff), so load it fresh in production mode.
    monkeypatch.delenv("RW_MODE", raising=False)
    monkeypatch.delenv("ROBOT_DEV", raising=False)
    importlib.reload(importlib.import_module("RW._mode"))
    platform = importlib.reload(importlib.import_module("RW.platform"))
    assert platform.fetchsecrets is fetchsecrets

    monkeypatch.delenv("RW_ACCESS_TOKEN")
    monkeypatch.setenv("RW_API_BASE_URL", "http://papi:8000")
    asked = []

    def fake_papi(key):
        asked.append(key)
        return {"rw-service-account-username": "sa", "rw-service-account-pw": "pw"}[key]

    token_rsp = MagicMock(status_code=200)
    token_rsp.json.return_value = {"access": "tok"}
    with patch.object(fetchsecrets, "_fetch_papi_secret", side_effect=fake_papi), \
         patch.object(fetchsecrets, "authenticate_vault_client", side_effect=AssertionError("Vault used")), \
         patch.object(platform.requests, "post", return_value=token_rsp) as post:
        assert platform.form_access_token() == "tok"
    assert asked == ["rw-service-account-username", "rw-service-account-pw"]
    assert post.call_args.kwargs["json"] == {"username": "sa", "password": "pw"}


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
    assert kwargs["url"] == "http://papi:8000/api/v1/runner/secrets/resolve"
    assert kwargs["json"] == {"workspace": "acme", "keys": ["DB_PW"]}
    # The run's token is the credential: PAPI binds the read to the workspace
    # its service account belongs to, and refuses the call without it.
    assert kwargs["headers"] == {"Authorization": "Bearer run-token"}


def test_fetch_papi_secret_fails_closed_without_a_token(monkeypatch):
    # A task that cannot prove who it is must not read secrets.
    monkeypatch.setenv("RW_PAPI_URL", "http://papi:8000")
    monkeypatch.delenv("RW_ACCESS_TOKEN")
    monkeypatch.setattr(fetchsecrets, "WORKSPACE_NAME", "acme")
    with patch.object(fetchsecrets.requests, "post") as post:
        with pytest.raises(fetchsecrets.AuthenticationError):
            fetchsecrets._fetch_papi_secret("DB_PW")
    post.assert_not_called()


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
