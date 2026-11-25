"""Customer Vault providers (SECRET_PROVIDER_<NAME>_TYPE=vault) after platform Vault removal.

The worker's platform Vault token (VAULT_TOKEN_FILE / VAULT_TOKEN) must never be
presented to a customer's Vault server: customer providers authenticate with
their own AppRole credentials only.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

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


def test_customer_vault_login_never_uses_platform_token(customer_vault_env):
    tokens_seen = []
    approle_logins = []

    class RecordingClient:
        def __init__(self, url=None, token=None, verify=None, **kwargs):
            self.url = url
            self._token = None
            self.token = token
            self.auth = MagicMock()
            self.auth.approle.login.side_effect = self._approle_login

        @property
        def token(self):
            return self._token

        @token.setter
        def token(self, value):
            tokens_seen.append(value)
            self._token = value

        def is_authenticated(self):
            return self._token is not None

        def _approle_login(self, role_id=None, secret_id=None, mount_point=None):
            approle_logins.append((role_id, secret_id, mount_point))
            self.token = CUSTOMER_TOKEN

    vault_rsp = MagicMock(status_code=200)
    vault_rsp.json.return_value = {"data": {"data": {"value": "s3cr3t"}}}

    with patch.object(fetchsecrets.hvac, "Client", RecordingClient), \
         patch.object(fetchsecrets.requests, "get", return_value=vault_rsp) as get:
        assert fetchsecrets.read_secret("acme@secret/data/x:value") == "s3cr3t"

    assert PLATFORM_TOKEN not in tokens_seen
    assert approle_logins == [("acme-role", "acme-secret", "approle")]
    assert get.call_args.kwargs["headers"] == {"X-Vault-Token": CUSTOMER_TOKEN}
    assert get.call_args.kwargs["url"] == "https://vault.acme.example/v1/secret/data/x"


@pytest.mark.parametrize("name", ["_kubernetes_vault_login", "_try_cached_token_login", "VAULT_TOKEN_TTL"])
def test_no_platform_vault_symbols(name):
    assert not hasattr(fetchsecrets, name)
