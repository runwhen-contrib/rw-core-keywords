#!/usr/bin/env python3
"""
Test script to verify Azure CLI authentication caching functionality.
"""

import os
import sys
import json
import logging
from unittest.mock import patch, MagicMock

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Add the module path (go up one directory since we're in tests/)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_azure_cli_caching():
    """Test that Azure CLI authentication is properly cached."""
    
    print("=== Testing Azure CLI Authentication Caching ===\n")
    
    # Set up test environment
    os.environ.update({
        'RW_SECRETS_KEYS': json.dumps({
            'azure_credentials': 'azure:sp@cli',
            'az_tenantId': 'file@/tmp/test_tenant_cli',
            'az_clientId': 'file@/tmp/test_client_cli', 
            'az_clientSecret': 'file@/tmp/test_secret_cli'
        }),
        'AZURE_CONFIG_DIR': '/tmp/test_azure_cli/shared_config/abc123/.azure'
    })
    
    # Create mock credential files
    os.makedirs('/tmp', exist_ok=True)
    with open('/tmp/test_tenant_cli', 'w') as f:
        f.write('test-tenant-id-cli')
    with open('/tmp/test_client_cli', 'w') as f:
        f.write('test-client-id-cli')
    with open('/tmp/test_secret_cli', 'w') as f:
        f.write('test-client-secret-cli')
    
    # Import modules after setting environment
    from RW import fetchsecrets
    
    # Mock the Azure utils az_login function to avoid real Azure calls
    def mock_az_login(*args, **kwargs):
        """Mock az login."""
        print(f"Mock: az login called with args={args}, kwargs={kwargs}")
    
    # Clear any existing cache
    fetchsecrets._cache.clear()
    
    print("1. Testing first Azure CLI authentication (should be cache MISS)...")
    with patch('RW.azure_utils.az_login', side_effect=mock_az_login) as mock_login:
        with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
            try:
                auth_result1 = fetchsecrets.read_secret('azure:sp@cli')
                print(f"   First auth successful: {auth_result1}")
                print(f"   Cache size after first auth: {len(fetchsecrets._cache)}")
                
                # Verify az_login was called
                if mock_login.called:
                    print(f"   ✅ SUCCESS: az_login was called on first access")
                    print(f"   Call args: {mock_login.call_args}")
                else:
                    print(f"   ❌ ERROR: az_login was NOT called on first access")
                    return False
                
                # Check cache contents
                cli_keys = [k for k in fetchsecrets._cache.keys() if k.startswith('azure_cli_')]
                print(f"   Azure CLI cache keys: {cli_keys}")
                
            except Exception as e:
                print(f"   First auth failed: {e}")
                return False
    
    print("\n2. Testing second Azure CLI authentication (should be cache HIT)...")
    with patch('RW.azure_utils.az_login', side_effect=mock_az_login) as mock_login:
        with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
            try:
                auth_result2 = fetchsecrets.read_secret('azure:sp@cli')
                print(f"   Second auth successful: {auth_result2}")
                print(f"   Cache size after second auth: {len(fetchsecrets._cache)}")
                
                # Verify az_login was NOT called (cache hit)
                if mock_login.called:
                    print(f"   ❌ ERROR: az_login was called on second access (should be cached)")
                    return False
                else:
                    print(f"   ✅ SUCCESS: az_login was NOT called (cache hit)")
                
                # Verify content is identical
                if auth_result1 == auth_result2:
                    print(f"   ✅ SUCCESS: Authentication results are identical")
                else:
                    print(f"   ❌ ERROR: Authentication results differ")
                    return False
                    
            except Exception as e:
                print(f"   Second auth failed: {e}")
                return False
    
    print("\n3. Testing cache info...")
    cache_info = fetchsecrets.get_cache_info()
    print(f"   Total cache size: {cache_info['total_cache_size']}")
    print(f"   Kubeconfig caches: {cache_info['kubeconfig_caches']}")
    print(f"   Azure CLI caches: {cache_info['azure_cli_caches']}")
    print(f"   Secret caches: {cache_info['secret_caches']}")
    
    if cache_info['azure_cli_caches'] > 0:
        print(f"   ✅ SUCCESS: Azure CLI cache detected")
    else:
        print(f"   ❌ ERROR: No Azure CLI cache found")
        return False
    
    print("\n4. Testing different tenant (should be separate cache)...")
    # Change tenant ID to create different cache context
    with open('/tmp/test_tenant_cli', 'w') as f:
        f.write('different-tenant-id')
    
    # Clear the secret-level cache for azure:sp@cli to force re-evaluation
    # but keep the CLI-specific cache to test isolation
    if 'azure:sp@cli' in fetchsecrets._cache:
        del fetchsecrets._cache['azure:sp@cli']
    
    # Clear the file-based secret cache to force re-reading credentials
    file_keys_to_remove = [k for k in fetchsecrets._cache.keys() if k.startswith('file@')]
    for key in file_keys_to_remove:
        del fetchsecrets._cache[key]
    
    with patch('RW.azure_utils.az_login', side_effect=mock_az_login) as mock_login:
        with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
            try:
                auth_result3 = fetchsecrets.read_secret('azure:sp@cli')
                print(f"   Different tenant auth successful: {auth_result3}")
                
                # Verify az_login WAS called (different tenant, cache miss)
                if mock_login.called:
                    print(f"   ✅ SUCCESS: az_login was called for different tenant")
                else:
                    print(f"   ❌ ERROR: az_login was NOT called for different tenant")
                    return False
                    
            except Exception as e:
                print(f"   Different tenant auth failed: {e}")
                return False
    
    final_cache_info = fetchsecrets.get_cache_info()
    print(f"   Final Azure CLI caches: {final_cache_info['azure_cli_caches']}")
    
    if final_cache_info['azure_cli_caches'] >= 2:
        print(f"   ✅ SUCCESS: Multiple Azure CLI caches detected")
    else:
        print(f"   ❌ ERROR: Expected multiple Azure CLI caches")
        return False
    
    # Cleanup
    for file_path in ['/tmp/test_tenant_cli', '/tmp/test_client_cli', '/tmp/test_secret_cli']:
        if os.path.exists(file_path):
            os.remove(file_path)
    
    return True

def test_azure_identity_cli_caching():
    """Test Azure Managed Identity CLI caching."""
    
    print("\n=== Testing Azure Identity CLI Caching ===\n")
    
    # Set up test environment for Managed Identity
    os.environ.update({
        'RW_SECRETS_KEYS': json.dumps({
            'azure_credentials': 'azure:identity@cli'
        }),
        'AZURE_CONFIG_DIR': '/tmp/test_azure_identity/shared_config/def456/.azure'
    })
    
    from RW import fetchsecrets
    
    # Mock the Azure utils az_login function
    def mock_az_login_identity(*args, **kwargs):
        """Mock az login for identity."""
        print(f"Mock: az login (identity) called with args={args}, kwargs={kwargs}")
    
    # Clear cache
    fetchsecrets._cache.clear()
    
    print("1. Testing first Azure Identity CLI authentication...")
    with patch('RW.azure_utils.az_login', side_effect=mock_az_login_identity) as mock_login:
        with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
            try:
                auth_result1 = fetchsecrets.read_secret('azure:identity@cli')
                print(f"   First identity auth successful: {auth_result1}")
                
                if mock_login.called:
                    print(f"   ✅ SUCCESS: az_login was called on first access")
                else:
                    print(f"   ❌ ERROR: az_login was NOT called on first access")
                    return False
                    
            except Exception as e:
                print(f"   First identity auth failed: {e}")
                return False
    
    print("\n2. Testing second Azure Identity CLI authentication...")
    with patch('RW.azure_utils.az_login', side_effect=mock_az_login_identity) as mock_login:
        with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
            try:
                auth_result2 = fetchsecrets.read_secret('azure:identity@cli')
                print(f"   Second identity auth successful: {auth_result2}")
                
                if mock_login.called:
                    print(f"   ❌ ERROR: az_login was called on second access (should be cached)")
                    return False
                else:
                    print(f"   ✅ SUCCESS: az_login was NOT called (cache hit)")
                    
            except Exception as e:
                print(f"   Second identity auth failed: {e}")
                return False
    
    return True

if __name__ == '__main__':
    try:
        success1 = test_azure_cli_caching()
        success2 = test_azure_identity_cli_caching()
        
        if success1 and success2:
            print(f"\n🎉 Azure CLI caching tests completed successfully!")
            print(f"✅ First access performs az login")
            print(f"✅ Second access uses cached authentication")
            print(f"✅ Different tenants get separate cache entries")
            print(f"✅ Both Service Principal and Managed Identity caching work")
            print(f"✅ Cache statistics properly track CLI authentications")
        else:
            print(f"\n❌ Azure CLI caching tests failed!")
            
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc() 