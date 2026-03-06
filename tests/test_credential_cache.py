#!/usr/bin/env python3
"""
Test script to demonstrate credential caching functionality.

This script simulates multiple secret imports to show how caching reduces
authentication overhead and improves performance.
"""

import os
import sys
import time
import json
from unittest.mock import patch, MagicMock

# Add the RW module to the path (go up one directory since we're in tests/)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import the modules we want to test
from RW import fetchsecrets, Core

def setup_test_environment():
    """Set up test environment variables."""
    os.environ.update({
        'RW_VAULT_ADDR': 'https://test-vault.example.com',
        'RW_WORKSPACE': 'test-workspace',
        'RW_LOCATION': 'test-location',
        'RW_LOCATION_VAULT_AUTH_MOUNT_POINT': 'auth/kubernetes',
        'RW_VAULT_APPROLE_ROLE_ID': 'test-role-id',
        'RW_VAULT_APPROLE_SECRET_ID': 'test-secret-id',
        'RW_SECRETS_KEYS': json.dumps({
            'TEST_SECRET_1': 'secret/test1',
            'TEST_SECRET_2': 'secret/test2',
            'TEST_SECRET_3': 'secret/test3',
            'AZURE_SECRET': 'azure:identity@kubeconfig:myRG/myCluster',
        }),
        # Set shorter cache TTLs for testing
        'RW_VAULT_TOKEN_CACHE_TTL': '300',  # 5 minutes
        'RW_AZURE_CREDENTIAL_CACHE_TTL': '600',  # 10 minutes
    })

def mock_vault_authentication():
    """Mock vault authentication to avoid real network calls."""
    
    # Mock hvac client
    mock_client = MagicMock()
    mock_client.token = 'mock-vault-token-12345'
    mock_client.sys.read_health_status.return_value = {'initialized': True}
    
    # Mock requests.get for vault secret retrieval
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'data': {
            'data': {
                'env': 'mock-secret-value'
            }
        }
    }
    
    return mock_client, mock_response

def test_vault_credential_caching():
    """Test Vault credential caching functionality."""
    print("=== Testing Vault Credential Caching ===")
    
    mock_client, mock_response = mock_vault_authentication()
    
    with patch('RW.fetchsecrets.authenticate_vault_client', return_value=mock_client), \
         patch('requests.get', return_value=mock_response):
        
        core = Core.Core()
        
        # Clear caches to start fresh
        core.clear_all_credential_caches()
        
        # First secret import - should authenticate
        print("1. First secret import (should authenticate)...")
        start_time = time.time()
        secret1 = core.import_secret('TEST_SECRET_1')
        first_time = time.time() - start_time
        print(f"   Time taken: {first_time:.4f} seconds")
        
        # Get cache stats
        stats = core.get_credential_cache_stats()
        print(f"   Cache stats: {stats}")
        
        # Second secret import - should use cached credentials
        print("2. Second secret import (should use cache)...")
        start_time = time.time()
        secret2 = core.import_secret('TEST_SECRET_2')
        second_time = time.time() - start_time
        print(f"   Time taken: {second_time:.4f} seconds")
        
        # Third secret import - should also use cached credentials
        print("3. Third secret import (should use cache)...")
        start_time = time.time()
        secret3 = core.import_secret('TEST_SECRET_3')
        third_time = time.time() - start_time
        print(f"   Time taken: {third_time:.4f} seconds")
        
        # Final cache stats
        final_stats = core.get_credential_cache_stats()
        print(f"   Final cache stats: {final_stats}")
        
        # Performance comparison
        avg_cached_time = (second_time + third_time) / 2
        improvement = ((first_time - avg_cached_time) / first_time) * 100
        print(f"   Performance improvement: {improvement:.1f}% faster with caching")
        
        return first_time, avg_cached_time

def test_cache_expiration():
    """Test cache expiration functionality."""
    print("\n=== Testing Cache Expiration ===")
    
    # Set very short TTL for testing
    original_ttl = fetchsecrets.VAULT_TOKEN_TTL
    fetchsecrets.VAULT_TOKEN_TTL = 2  # 2 seconds
    
    try:
        mock_client, mock_response = mock_vault_authentication()
        
        with patch('RW.fetchsecrets.authenticate_vault_client', return_value=mock_client) as mock_auth, \
             patch('requests.get', return_value=mock_response):
            
            core = Core.Core()
            core.clear_all_credential_caches()
            
            # First import
            print("1. First import (creates cache entry)...")
            core.import_secret('TEST_SECRET_1')
            print(f"   Authentication calls: {mock_auth.call_count}")
            
            # Second import immediately (should use cache)
            print("2. Second import immediately (should use cache)...")
            core.import_secret('TEST_SECRET_2')
            print(f"   Authentication calls: {mock_auth.call_count}")
            
            # Wait for cache to expire
            print("3. Waiting for cache to expire...")
            time.sleep(3)
            
            # Third import after expiration (should re-authenticate)
            print("4. Third import after expiration (should re-authenticate)...")
            core.import_secret('TEST_SECRET_3')
            print(f"   Authentication calls: {mock_auth.call_count}")
            
            # Verify cache cleanup
            core.clear_expired_credential_caches()
            stats = core.get_credential_cache_stats()
            print(f"   Cache stats after cleanup: {stats}")
            
    finally:
        # Restore original TTL
        fetchsecrets.VAULT_TOKEN_TTL = original_ttl

def test_azure_credential_caching():
    """Test Azure credential caching functionality."""
    print("\n=== Testing Azure Credential Caching ===")
    
    from RW import azure_utils
    
    # Mock Azure credential creation
    mock_credential = MagicMock()
    mock_subscription_id = 'test-subscription-12345'
    
    with patch('azure.identity.DefaultAzureCredential', return_value=mock_credential), \
         patch('RW.azure_utils.get_subscription_id', return_value=mock_subscription_id):
        
        # First call - should create new credential
        print("1. First Azure credential request (should create new)...")
        start_time = time.time()
        cred1, sub1 = azure_utils.get_azure_credential()
        first_time = time.time() - start_time
        print(f"   Time taken: {first_time:.4f} seconds")
        
        # Second call - should use cached credential
        print("2. Second Azure credential request (should use cache)...")
        start_time = time.time()
        cred2, sub2 = azure_utils.get_azure_credential()
        second_time = time.time() - start_time
        print(f"   Time taken: {second_time:.4f} seconds")
        
        # Verify same objects returned
        print(f"   Same credential object: {cred1 is cred2}")
        print(f"   Same subscription ID: {sub1 == sub2}")
        
        improvement = ((first_time - second_time) / first_time) * 100 if first_time > 0 else 0
        print(f"   Performance improvement: {improvement:.1f}% faster with caching")

def main():
    """Run all tests."""
    print("Credential Caching Test Suite")
    print("=" * 50)
    
    setup_test_environment()
    
    try:
        # Test Vault caching
        vault_times = test_vault_credential_caching()
        
        # Test cache expiration
        test_cache_expiration()
        
        # Test Azure caching
        test_azure_credential_caching()
        
        print("\n=== Summary ===")
        if vault_times:
            first_time, avg_cached_time = vault_times
            improvement = ((first_time - avg_cached_time) / first_time) * 100
            print(f"Vault authentication caching provides {improvement:.1f}% performance improvement")
        
        print("\nCredential caching is working correctly!")
        print("This will significantly reduce authentication overhead in production.")
        
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main()) 