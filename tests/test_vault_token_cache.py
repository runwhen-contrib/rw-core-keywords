#!/usr/bin/env python3
"""
Test script for Vault token cache functionality.

Tests the integration of cached Vault tokens from the worker (via VAULT_TOKEN_FILE)
and fallback behavior to AppRole authentication.

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


def test_vault_client_uses_cached_token_from_file(monkeypatch):
    """Test that cached token file is used when available and valid."""
    # Create temp token file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.token') as f:
        f.write('s.test-token-value-from-file')
        token_file = f.name
    
    try:
        monkeypatch.setenv('VAULT_TOKEN_FILE', token_file)
        monkeypatch.setenv('RW_VAULT_ADDR', 'http://localhost:8200')
        
        # Mock hvac client
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        
        with patch('hvac.Client', return_value=mock_client) as mock_hvac:
            client = fetchsecrets._try_cached_token_login('http://localhost:8200')
            
            assert client is not None
            assert client == mock_client
            # Verify the client was created with the token from file
            mock_hvac.assert_called_once_with(
                url='http://localhost:8200',
                token='s.test-token-value-from-file',
                verify=fetchsecrets.REQUEST_VERIFY
            )
    finally:
        os.unlink(token_file)


def test_vault_client_uses_token_from_environment(monkeypatch):
    """Test that VAULT_TOKEN environment variable is used when no token file."""
    monkeypatch.delenv('VAULT_TOKEN_FILE', raising=False)
    monkeypatch.setenv('VAULT_TOKEN', 's.test-token-from-env')
    
    # Mock hvac client
    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = True
    
    with patch('hvac.Client', return_value=mock_client) as mock_hvac:
        client = fetchsecrets._try_cached_token_login('http://localhost:8200')
        
        assert client is not None
        assert client == mock_client
        # Verify the client was created with the token from environment
        mock_hvac.assert_called_once_with(
            url='http://localhost:8200',
            token='s.test-token-from-env',
            verify=fetchsecrets.REQUEST_VERIFY
        )


def test_vault_client_token_file_takes_priority_over_env(monkeypatch):
    """Test that token file is preferred over environment variable."""
    # Create temp token file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.token') as f:
        f.write('s.file-token')
        token_file = f.name
    
    try:
        monkeypatch.setenv('VAULT_TOKEN_FILE', token_file)
        monkeypatch.setenv('VAULT_TOKEN', 's.env-token')
        
        # Mock hvac client
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        
        with patch('hvac.Client', return_value=mock_client) as mock_hvac:
            client = fetchsecrets._try_cached_token_login('http://localhost:8200')
            
            assert client is not None
            # Verify the file token was used (only one call, with file token)
            assert mock_hvac.call_count == 1
            mock_hvac.assert_called_with(
                url='http://localhost:8200',
                token='s.file-token',
                verify=fetchsecrets.REQUEST_VERIFY
            )
    finally:
        os.unlink(token_file)


def test_vault_client_fallback_to_approle_when_no_cached_token(monkeypatch):
    """Test fallback to AppRole when no cached token is available."""
    monkeypatch.delenv('VAULT_TOKEN_FILE', raising=False)
    monkeypatch.delenv('VAULT_TOKEN', raising=False)
    monkeypatch.setenv('RW_VAULT_APPROLE_ROLE_ID', 'test-role-id')
    monkeypatch.setenv('RW_VAULT_APPROLE_SECRET_ID', 'test-secret-id')
    
    # Mock hvac client for AppRole
    mock_client = MagicMock()
    
    with patch('hvac.Client', return_value=mock_client):
        client = fetchsecrets.authenticate_vault_client(
            vault_addr='http://localhost:8200',
            auth_mount_point='auth/approle',
            role_id='test-role-id',
            secret_id='test-secret-id'
        )
        
        assert client is not None
        # Verify AppRole login was called
        mock_client.auth.approle.login.assert_called_once_with(
            role_id='test-role-id',
            secret_id='test-secret-id',
            mount_point='auth/approle'
        )


def test_vault_client_fallback_when_cached_token_invalid(monkeypatch):
    """Test fallback to AppRole when cached token is invalid."""
    # Create temp token file with a token
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.token') as f:
        f.write('s.invalid-token')
        token_file = f.name
    
    try:
        monkeypatch.setenv('VAULT_TOKEN_FILE', token_file)
        monkeypatch.setenv('RW_VAULT_APPROLE_ROLE_ID', 'test-role-id')
        monkeypatch.setenv('RW_VAULT_APPROLE_SECRET_ID', 'test-secret-id')
        
        # Mock hvac clients - first for token check (invalid), second for AppRole
        call_count = [0]
        def create_mock_client(*args, **kwargs):
            call_count[0] += 1
            client = MagicMock()
            if 'token' in kwargs:
                # Token-based client - simulate invalid token
                client.is_authenticated.return_value = False
            return client
        
        with patch('hvac.Client', side_effect=create_mock_client):
            client = fetchsecrets.authenticate_vault_client(
                vault_addr='http://localhost:8200',
                auth_mount_point='auth/approle',
                role_id='test-role-id',
                secret_id='test-secret-id'
            )
            
            assert client is not None
            # Should have tried token first, then fell back to AppRole
            assert call_count[0] >= 2
    finally:
        os.unlink(token_file)


def test_vault_client_handles_missing_token_file(monkeypatch):
    """Test graceful handling when token file doesn't exist."""
    monkeypatch.setenv('VAULT_TOKEN_FILE', '/nonexistent/path/to/token')
    monkeypatch.delenv('VAULT_TOKEN', raising=False)
    
    client = fetchsecrets._try_cached_token_login('http://localhost:8200')
    
    # Should return None, allowing fallback to other auth methods
    assert client is None


def test_vault_client_handles_empty_token_file(monkeypatch):
    """Test handling of empty token file."""
    # Create temp token file with empty content
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.token') as f:
        f.write('')
        token_file = f.name
    
    try:
        monkeypatch.setenv('VAULT_TOKEN_FILE', token_file)
        monkeypatch.delenv('VAULT_TOKEN', raising=False)
        
        client = fetchsecrets._try_cached_token_login('http://localhost:8200')
        
        # Should return None for empty token
        assert client is None
    finally:
        os.unlink(token_file)


def test_vault_client_handles_whitespace_in_token_file(monkeypatch):
    """Test that whitespace is properly stripped from token file."""
    # Create temp token file with whitespace
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.token') as f:
        f.write('  s.token-with-whitespace  \n\n')
        token_file = f.name
    
    try:
        monkeypatch.setenv('VAULT_TOKEN_FILE', token_file)
        
        # Mock hvac client
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        
        with patch('hvac.Client', return_value=mock_client) as mock_hvac:
            client = fetchsecrets._try_cached_token_login('http://localhost:8200')
            
            assert client is not None
            # Verify whitespace was stripped
            mock_hvac.assert_called_once_with(
                url='http://localhost:8200',
                token='s.token-with-whitespace',
                verify=fetchsecrets.REQUEST_VERIFY
            )
    finally:
        os.unlink(token_file)


def test_vault_auth_logging(monkeypatch, caplog):
    """Test that authentication method is properly logged."""
    caplog.set_level(logging.INFO)
    
    # Create temp token file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.token') as f:
        f.write('s.test-token')
        token_file = f.name
    
    try:
        monkeypatch.setenv('VAULT_TOKEN_FILE', token_file)
        
        # Mock hvac client
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        
        with patch('hvac.Client', return_value=mock_client):
            fetchsecrets._try_cached_token_login('http://localhost:8200')
        
        # Check that structured logging occurred
        assert any('VAULT_AUTH' in record.message and 'cached_file' in record.message 
                   for record in caplog.records)
    finally:
        os.unlink(token_file)


def test_full_authenticate_vault_client_with_cached_token(monkeypatch):
    """Integration test: authenticate_vault_client uses cached token when available."""
    # Create temp token file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.token') as f:
        f.write('s.cached-token')
        token_file = f.name
    
    try:
        monkeypatch.setenv('VAULT_TOKEN_FILE', token_file)
        monkeypatch.setenv('RW_VAULT_APPROLE_ROLE_ID', 'test-role-id')
        monkeypatch.setenv('RW_VAULT_APPROLE_SECRET_ID', 'test-secret-id')
        
        # Mock hvac client that validates with cached token
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        
        with patch('hvac.Client', return_value=mock_client) as mock_hvac:
            client = fetchsecrets.authenticate_vault_client(
                vault_addr='http://localhost:8200',
                auth_mount_point='auth/approle',
                role_id='test-role-id',
                secret_id='test-secret-id'
            )
            
            assert client is not None
            # Verify AppRole login was NOT called (cached token was used)
            mock_client.auth.approle.login.assert_not_called()
            # Verify the cached token was used
            mock_hvac.assert_called_with(
                url='http://localhost:8200',
                token='s.cached-token',
                verify=fetchsecrets.REQUEST_VERIFY
            )
    finally:
        os.unlink(token_file)


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


def test_vault_client_strips_whitespace_from_env_token(monkeypatch):
    """Test that whitespace is properly stripped from VAULT_TOKEN environment variable."""
    monkeypatch.delenv('VAULT_TOKEN_FILE', raising=False)
    monkeypatch.setenv('VAULT_TOKEN', '  s.token-with-whitespace  \n')
    
    # Mock hvac client
    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = True
    
    with patch('hvac.Client', return_value=mock_client) as mock_hvac:
        client = fetchsecrets._try_cached_token_login('http://localhost:8200')
        
        assert client is not None
        # Verify whitespace was stripped from environment token
        mock_hvac.assert_called_once_with(
            url='http://localhost:8200',
            token='s.token-with-whitespace',
            verify=fetchsecrets.REQUEST_VERIFY
        )


def test_vault_client_handles_whitespace_only_env_token(monkeypatch):
    """Test handling of whitespace-only VAULT_TOKEN environment variable."""
    monkeypatch.delenv('VAULT_TOKEN_FILE', raising=False)
    monkeypatch.setenv('VAULT_TOKEN', '   \n\t  ')
    
    client = fetchsecrets._try_cached_token_login('http://localhost:8200')
    
    # Should return None for whitespace-only token
    assert client is None


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


def test_kubernetes_auth_failure_is_logged(monkeypatch, caplog):
    """Test that Kubernetes authentication failures are logged."""
    caplog.set_level(logging.WARNING)
    
    monkeypatch.delenv('VAULT_TOKEN_FILE', raising=False)
    monkeypatch.delenv('VAULT_TOKEN', raising=False)
    monkeypatch.setenv('RW_WORKSPACE', 'test-workspace')
    
    # Mock kubernetes vault login to raise exception
    with patch.object(fetchsecrets, '_kubernetes_vault_login', 
                      side_effect=fetchsecrets.AuthenticationError("K8s auth failed")):
        with pytest.raises(fetchsecrets.AuthenticationError):
            fetchsecrets.authenticate_vault_client(
                vault_addr='http://localhost:8200',
                auth_mount_point='auth/kubernetes',
                role_id=None,
                secret_id=None
            )
    
    # Check that failure was logged
    assert any('VAULT_AUTH' in record.message and 'kubernetes' in record.message 
               and '"success": false' in record.message
               for record in caplog.records)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
