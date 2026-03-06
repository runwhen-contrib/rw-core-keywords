#!/usr/bin/env python3
"""
Test script to demonstrate comprehensive logging for credential caching troubleshooting.
"""

import os
import sys
import json
import logging

# Set up logging to see all levels
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Add the module path
sys.path.insert(0, os.path.dirname(__file__))

def test_credential_cache_logging():
    """Test comprehensive credential cache logging."""
    
    print("=== Credential Cache Logging Test ===\n")
    
    # Set up test environment
    os.environ.update({
        'RW_SECRETS_KEYS': json.dumps({
            'az_tenantId': 'test-tenant-12345',
            'az_clientId': 'test-client-67890', 
            'az_clientSecret': 'test-secret-abcdef',
            'azure_kubeconfig': 'azure:sp@kubeconfig:testRG/testCluster',
            'vault_secret': 'runwhen-vault@secret/path:field'
        }),
        'RW_WORKSPACE': 'test-workspace',
        'RW_LOCATION': 'test-location',
        'RW_VAULT_ADDR': 'https://test.vault.com',
        'TMPDIR': '/tmp/test_logging'
    })
    
    # Import modules after setting environment
    from RW import fetchsecrets, Core
    
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
    core = Core.Core()
    detailed_info = core.log_credential_cache_status()
    
    print(f"\n3. Testing secret cache operations...")
    # Simulate secret cache operations
    fetchsecrets._cache['test_secret_1'] = 'cached_value_1'
    fetchsecrets._cache['test_secret_2'] = 'cached_value_2'
    
    print("Secret cache now contains:")
    for key, value in fetchsecrets._cache.items():
        print(f"  {key}: {value[:20]}...")
    
    # Test cache clearing
    print(f"\n4. Testing cache clearing...")
    core.clear_secret_cache()
    print(f"Cache size after clearing: {len(fetchsecrets._cache)}")
    
    return cache_info

def demonstrate_log_patterns():
    """Demonstrate different log patterns used in the system."""
    
    print(f"\n=== Log Pattern Examples ===")
    print(f"The credential caching system uses structured logging with prefixes:")
    print(f"")
    print(f"CREDENTIAL_CACHE: - General credential caching operations")
    print(f"SECRET_CACHE:     - Secret value caching (hit/miss)")  
    print(f"CONTEXT_HASH:     - Context generation and isolation")
    print(f"AZURE_AUTH:       - Azure authentication operations")
    print(f"VAULT_AUTH:       - Vault authentication operations")
    print(f"")
    print(f"Example log entries you might see:")
    print(f"")
    print(f"INFO - CREDENTIAL_CACHE: Generated context hash: a1b2c3d4e5f6")
    print(f"INFO - CREDENTIAL_CACHE: Azure CLI already authenticated, reusing existing session")
    print(f"DEBUG - SECRET_CACHE: Cache HIT for secret 'azure_kubeconfig'")
    print(f"DEBUG - SECRET_CACHE: Cache MISS for secret 'vault_token', fetching from provider")
    print(f"INFO - CREDENTIAL_CACHE: Azure authentication successful, credentials stored in /tmp/runwhen/shared_config/a1b2c3d4e5f6/.azure")
    print(f"DEBUG - Authenticating to Vault using AppRole method")

def show_troubleshooting_commands():
    """Show useful commands for troubleshooting credential caching."""
    
    print(f"\n=== Troubleshooting Commands ===")
    print(f"")
    print(f"# Check credential cache directories")
    print(f"ls -la /tmp/runwhen/shared_config/*/")
    print(f"")
    print(f"# Check Azure CLI authentication status")
    print(f"az account show")
    print(f"")
    print(f"# Check Azure CLI token files")
    print(f"ls -la $AZURE_CONFIG_DIR/")
    print(f"")
    print(f"# Check Google Cloud authentication")
    print(f"gcloud auth list")
    print(f"")
    print(f"# View credential cache statistics in Robot Framework")
    print(f"Log Credential Cache Status    # Robot Framework keyword")
    print(f"")
    print(f"# Enable debug logging")
    print(f"export RW_LOG_LEVEL=DEBUG")
    print(f"")
    print(f"# Clear credential caches manually")
    print(f"rm -rf /tmp/runwhen/shared_config/*/")

def show_common_issues():
    """Show common credential caching issues and solutions."""
    
    print(f"\n=== Common Issues & Solutions ===")
    print(f"")
    print(f"Issue: Different codebundles interfering with each other's credentials")
    print(f"Solution: Check context hash generation - different credentials should have different hashes")
    print(f"Debug: Look for 'Generated credential context hash' in logs")
    print(f"")
    print(f"Issue: Azure authentication not being reused")
    print(f"Solution: Check AZURE_CONFIG_DIR and verify accessTokens.json exists")
    print(f"Debug: Look for 'Azure CLI already authenticated' vs 'Performing Azure Service Principal login'")
    print(f"")
    print(f"Issue: Vault tokens expiring too quickly")
    print(f"Solution: Check vault token TTL settings and renewal policies")
    print(f"Debug: Look for 'Authenticating to Vault' frequency in logs")
    print(f"")
    print(f"Issue: Cache directories not being created")
    print(f"Solution: Check TMPDIR permissions and disk space")
    print(f"Debug: Look for 'CONTEXT-SPECIFIC directory' in logs")
    print(f"")
    print(f"Issue: Context hash not changing for different credentials")
    print(f"Solution: Verify RW_SECRETS_KEYS configuration includes credential-affecting secrets")
    print(f"Debug: Check context hash generation logic and environment variables")

if __name__ == '__main__':
    try:
        cache_info = test_credential_cache_logging()
        demonstrate_log_patterns()
        show_troubleshooting_commands()
        show_common_issues()
        
        print(f"\n🎉 Credential cache logging test completed successfully!")
        print(f"The system provides comprehensive logging for troubleshooting credential caching issues.")
        
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc() 