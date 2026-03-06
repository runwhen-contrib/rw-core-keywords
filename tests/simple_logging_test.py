#!/usr/bin/env python3
"""
Simple test to demonstrate credential caching logging without heavy dependencies.
"""

import os
import sys
import json
import logging

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Add module path (go up one directory since we're in tests/)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_basic_logging():
    """Test basic credential cache logging functionality."""
    
    print("=== Basic Credential Cache Logging Test ===\n")
    
    # Set up test environment
    os.environ.update({
        'RW_SECRETS_KEYS': json.dumps({
            'az_tenantId': 'test-tenant-12345',
            'az_clientId': 'test-client-67890', 
            'az_clientSecret': 'test-secret-abcdef',
            'azure_kubeconfig': 'azure:sp@kubeconfig:testRG/testCluster'
        }),
        'RW_WORKSPACE': 'test-workspace',
        'RW_LOCATION': 'test-location',
        'RW_VAULT_ADDR': 'https://test.vault.com',
        'TMPDIR': '/tmp/test_logging',
        'AZURE_CONFIG_DIR': '/tmp/test_logging/shared_config/abc123def456/.azure',
        'CLOUDSDK_CONFIG': '/tmp/test_logging/shared_config/abc123def456/.gcloud'
    })
    
    # Import just fetchsecrets
    from RW import fetchsecrets
    
    print("1. Testing cache info gathering...")
    cache_info = fetchsecrets.get_cache_info()
    print("Cache Info:")
    for key, value in cache_info.items():
        if isinstance(value, dict):
            print(f"  {key}:")
            for subkey, subvalue in value.items():
                print(f"    {subkey}: {subvalue}")
        else:
            print(f"  {key}: {value}")
    
    print("\n2. Testing comprehensive cache status logging...")
    detailed_info = fetchsecrets.log_credential_cache_status()
    
    print(f"\n3. Testing secret cache operations...")
    # Simulate secret cache operations
    fetchsecrets._cache['test_secret_1'] = 'cached_value_1'
    fetchsecrets._cache['test_secret_2'] = 'cached_value_2'
    
    print("Secret cache now contains:")
    for key, value in fetchsecrets._cache.items():
        print(f"  {key}: {value}")
    
    print(f"\n4. Testing cache clearing...")
    fetchsecrets.clear_all_caches()
    print(f"Cache size after clearing: {len(fetchsecrets._cache)}")
    
    return cache_info

def show_logging_summary():
    """Show a summary of the logging capabilities."""
    
    print(f"\n=== Credential Caching Logging Summary ===")
    print(f"")
    print(f"The credential caching system provides comprehensive logging for troubleshooting:")
    print(f"")
    print(f"1. CONTEXT GENERATION:")
    print(f"   - Context hash generation with input details")
    print(f"   - Directory creation and path logging")
    print(f"   - Environment variable analysis")
    print(f"")
    print(f"2. AUTHENTICATION OPERATIONS:")
    print(f"   - Cache hit/miss detection for Azure CLI")
    print(f"   - Authentication success/failure logging")
    print(f"   - Credential storage location logging")
    print(f"")
    print(f"3. SECRET OPERATIONS:")
    print(f"   - Secret cache hit/miss logging")
    print(f"   - Provider selection logging")
    print(f"   - Error handling with detailed messages")
    print(f"")
    print(f"4. CACHE STATISTICS:")
    print(f"   - Directory sizes and file counts")
    print(f"   - Cache effectiveness metrics")
    print(f"   - Environment variable visibility")
    print(f"")
    print(f"5. TROUBLESHOOTING KEYWORDS:")
    print(f"   - Log Credential Cache Status (Robot Framework)")
    print(f"   - Get Credential Cache Info (Robot Framework)")
    print(f"   - Clear Secret Cache (Robot Framework)")

if __name__ == '__main__':
    try:
        cache_info = test_basic_logging()
        show_logging_summary()
        
        print(f"\n🎉 Basic credential cache logging test completed successfully!")
        print(f"The system provides comprehensive logging for troubleshooting credential caching.")
        
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc() 