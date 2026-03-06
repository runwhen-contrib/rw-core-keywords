#!/usr/bin/env python3
"""Simple test for credential caching"""

import os
import sys
import time
import json

# Test environment setup
os.environ.update({
    'RW_VAULT_ADDR': 'https://test.vault.com',
    'RW_WORKSPACE': 'test',
    'RW_LOCATION': 'test',
    'RW_LOCATION_VAULT_AUTH_MOUNT_POINT': 'auth/k8s',
    'RW_VAULT_APPROLE_ROLE_ID': 'test-role',
    'RW_VAULT_APPROLE_SECRET_ID': 'test-secret',
    'RW_SECRETS_KEYS': json.dumps({
        'TEST_SECRET': 'runwhen-vault@secret/test:field',
        'AZURE_KUBECONFIG': 'azure:identity@kubeconfig:myRG/myCluster'
    }),
    'AZURE_CONFIG_DIR': '/tmp/test_cache/shared_config/abc123/.azure',
    'CLOUDSDK_CONFIG': '/tmp/test_cache/shared_config/abc123/.gcloud'
})

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from RW import fetchsecrets

print("Testing credential caching...")

# Test cache info
print("\n1. Testing cache info...")
try:
    info = fetchsecrets.get_cache_info()
    print('Cache info:')
    for key, value in info.items():
        if isinstance(value, dict):
            print(f'  {key}:')
            for subkey, subvalue in value.items():
                print(f'    {subkey}: {subvalue}')
        else:
            print(f'  {key}: {value}')
except Exception as e:
    print(f"Error getting cache info: {e}")

# Test comprehensive cache status logging
print("\n2. Testing comprehensive cache status logging...")
try:
    fetchsecrets.log_credential_cache_status()
    print("Cache status logged successfully!")
except Exception as e:
    print(f"Error logging cache status: {e}")

# Test secret cache operations
print("\n3. Testing secret cache operations...")
fetchsecrets._cache['test_secret'] = 'test_value'
print(f"Added test secret to cache. Cache size: {len(fetchsecrets._cache)}")

# Test cache clearing
print("\n4. Testing cache clearing...")
fetchsecrets.clear_all_caches()
print(f"Cache cleared. Cache size: {len(fetchsecrets._cache)}")

print("\nCredential caching system test completed!") 