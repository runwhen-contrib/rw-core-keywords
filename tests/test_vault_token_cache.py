#!/usr/bin/env python3
"""
Tests for customer Vault authentication helpers (AppRole login and auth logging).

Platform Vault token caching was removed; customer Vault providers authenticate
with their own AppRole credentials only (see tests/test_customer_vault.py).

This test mocks the external dependencies to allow standalone testing.
"""

import os
import sys
import tempfile
import types
import json
import logging
import pytest
from unittest.mock import patch, MagicMock, PropertyMock


def create_mock_module(name):
    """Create a mock module that can be used as a parent for submodules."""
    module = types.ModuleType(name)
    module.__path__ = []
    return module


# Create mock modules hierarchy for Azure
azure_mock = create_mock_module('azure')
azure_mock.identity = create_mock_module('azure.identity')
azure_mock.core = create_mock_module('azure.core')
azure_mock.core.exceptions = create_mock_module('azure.core.exceptions')
azure_mock.mgmt = create_mock_module('azure.mgmt')
azure_mock.mgmt.containerservice = create_mock_module('azure.mgmt.containerservice')
azure_mock.mgmt.subscription = create_mock_module('azure.mgmt.subscription')
azure_mock.mgmt.resource = create_mock_module('azure.mgmt.resource')

# Add mock classes
azure_mock.identity.DefaultAzureCredential = MagicMock()
azure_mock.identity.ClientSecretCredential = MagicMock()
azure_mock.core.exceptions.AzureError = Exception
azure_mock.mgmt.containerservice.ContainerServiceClient = MagicMock()
azure_mock.mgmt.subscription = create_mock_module('azure.mgmt.subscription')
azure_mock.mgmt.subscription.SubscriptionClient = MagicMock()

# Create mock modules hierarchy for Google
google_mock = create_mock_module('google')
google_mock.auth = create_mock_module('google.auth')
google_mock.auth.transport = create_mock_module('google.auth.transport')
google_mock.auth.transport.requests = create_mock_module('google.auth.transport.requests')
google_mock.oauth2 = create_mock_module('google.oauth2')
google_mock.oauth2.service_account = create_mock_module('google.oauth2.service_account')
google_mock.cloud = create_mock_module('google.cloud')
google_mock.cloud.container_v1 = create_mock_module('google.cloud.container_v1')

# Create mock modules for robot framework
robot_mock = create_mock_module('robot')
robot_mock.libraries = create_mock_module('robot.libraries')
robot_mock.libraries.BuiltIn = create_mock_module('robot.libraries.BuiltIn')
robot_mock.libraries.BuiltIn.BuiltIn = MagicMock()

# Install mock modules
sys.modules['azure'] = azure_mock
sys.modules['azure.core'] = azure_mock.core
sys.modules['azure.core.exceptions'] = azure_mock.core.exceptions
sys.modules['azure.identity'] = azure_mock.identity
sys.modules['azure.mgmt'] = azure_mock.mgmt
sys.modules['azure.mgmt.containerservice'] = azure_mock.mgmt.containerservice
sys.modules['azure.mgmt.subscription'] = azure_mock.mgmt.subscription
sys.modules['azure.mgmt.resource'] = azure_mock.mgmt.resource
sys.modules['google'] = google_mock
sys.modules['google.auth'] = google_mock.auth
sys.modules['google.auth.transport'] = google_mock.auth.transport
sys.modules['google.auth.transport.requests'] = google_mock.auth.transport.requests
sys.modules['google.oauth2'] = google_mock.oauth2
sys.modules['google.oauth2.service_account'] = google_mock.oauth2.service_account
sys.modules['google.cloud'] = google_mock.cloud
sys.modules['google.cloud.container_v1'] = google_mock.cloud.container_v1
sys.modules['robot'] = robot_mock
sys.modules['robot.libraries'] = robot_mock.libraries
sys.modules['robot.libraries.BuiltIn'] = robot_mock.libraries.BuiltIn

# Add the RW module to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from RW import fetchsecrets



def test_log_vault_auth_method_success():
    """Test _log_vault_auth_method with successful authentication."""
    # Just verify it doesn't raise
    fetchsecrets._log_vault_auth_method('approle', True)
    fetchsecrets._log_vault_auth_method('cached_file', True, {'token_file': '/path/to/token'})


def test_log_vault_auth_method_failure():
    """Test _log_vault_auth_method with failed authentication."""
    # Just verify it doesn't raise
    fetchsecrets._log_vault_auth_method('cached_file', False, {'reason': 'token_invalid'})
    fetchsecrets._log_vault_auth_method('environment', False, {'reason': 'error'})


def test_approle_auth_failure_is_logged(monkeypatch, caplog):
    """Test that AppRole authentication failures are logged."""
    caplog.set_level(logging.WARNING)
    
    monkeypatch.delenv('VAULT_TOKEN_FILE', raising=False)
    monkeypatch.delenv('VAULT_TOKEN', raising=False)
    
    # Mock hvac client to raise exception on AppRole login
    mock_client = MagicMock()
    mock_client.auth.approle.login.side_effect = Exception("Connection refused")
    
    with patch('hvac.Client', return_value=mock_client):
        with pytest.raises(fetchsecrets.AuthenticationError):
            fetchsecrets.authenticate_vault_client(
                vault_addr='http://localhost:8200',
                auth_mount_point='auth/approle',
                role_id='test-role-id',
                secret_id='test-secret-id'
            )
    
    # Check that failure was logged
    assert any('VAULT_AUTH' in record.message and 'approle' in record.message 
               and '"success": false' in record.message
               for record in caplog.records)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
