#!/usr/bin/env python3
"""
Test script to verify kubeconfig caching functionality.
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

def test_kubeconfig_caching():
    """Test that kubeconfig content is properly cached."""
    
    print("=== Testing Kubeconfig Caching ===\n")
    
    # Set up test environment
    os.environ.update({
        'RW_SECRETS_KEYS': json.dumps({
            'kubeconfig': 'azure:sp@kubeconfig:testRG/testCluster',
            'az_tenantId': 'file@/tmp/test_tenant',
            'az_clientId': 'file@/tmp/test_client', 
            'az_clientSecret': 'file@/tmp/test_secret'
        }),
        'KUBECONFIG': '/tmp/test_kubeconfig/config'
    })
    
    # Create mock credential files
    os.makedirs('/tmp', exist_ok=True)
    with open('/tmp/test_tenant', 'w') as f:
        f.write('test-tenant-id')
    with open('/tmp/test_client', 'w') as f:
        f.write('test-client-id')
    with open('/tmp/test_secret', 'w') as f:
        f.write('test-client-secret')
    
    # Import modules after setting environment
    from RW import fetchsecrets
    
    # Mock the Azure utils function to avoid real API calls
    mock_kubeconfig_content = """
apiVersion: v1
kind: Config
clusters:
- cluster:
    server: https://test-cluster.hcp.eastus.azmk8s.io:443
  name: test-cluster
contexts:
- context:
    cluster: test-cluster
    user: clusterUser_testRG_testCluster
  name: test-cluster
current-context: test-cluster
users:
- name: clusterUser_testRG_testCluster
  user:
    exec:
      command: kubelogin
      args:
      - get-token
      - --login
      - spn
      - --server-id
      - 6dae42f8-4368-4678-94ff-3960e28e3630
      - --client-id
      - test-client-id
      - --tenant-id
      - test-tenant-id
"""
    
    def mock_generate_kubeconfig(*args, **kwargs):
        """Mock kubeconfig generation."""
        kubeconfig_path = os.environ.get("KUBECONFIG", "")
        os.makedirs(os.path.dirname(kubeconfig_path), exist_ok=True)
        with open(kubeconfig_path, 'w') as f:
            f.write(mock_kubeconfig_content)
        print("Mock: Generated kubeconfig file")
    
    # Clear any existing cache
    fetchsecrets._cache.clear()
    
    print("1. Testing first kubeconfig access (should be cache MISS)...")
    with patch('RW.azure_utils.generate_kubeconfig_for_aks', side_effect=mock_generate_kubeconfig):
        with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
            try:
                kubeconfig1 = fetchsecrets.read_secret('azure:sp@kubeconfig:testRG/testCluster')
                print(f"   First access successful, content length: {len(kubeconfig1)}")
                print(f"   Cache size after first access: {len(fetchsecrets._cache)}")
                
                # Check cache contents
                kubeconfig_keys = [k for k in fetchsecrets._cache.keys() if k.startswith('kubeconfig_')]
                print(f"   Kubeconfig cache keys: {kubeconfig_keys}")
                
            except Exception as e:
                print(f"   First access failed: {e}")
                return False
    
    print("\n2. Testing second kubeconfig access (should be cache HIT)...")
    # Clear the physical file to ensure we're getting from cache
    if os.path.exists('/tmp/test_kubeconfig/config'):
        os.remove('/tmp/test_kubeconfig/config')
    
    with patch('RW.azure_utils.generate_kubeconfig_for_aks', side_effect=mock_generate_kubeconfig) as mock_gen:
        with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
            try:
                kubeconfig2 = fetchsecrets.read_secret('azure:sp@kubeconfig:testRG/testCluster')
                print(f"   Second access successful, content length: {len(kubeconfig2)}")
                print(f"   Cache size after second access: {len(fetchsecrets._cache)}")
                
                # Verify generate_kubeconfig was NOT called (cache hit)
                if mock_gen.called:
                    print(f"   ❌ ERROR: generate_kubeconfig was called on second access (should be cached)")
                    return False
                else:
                    print(f"   ✅ SUCCESS: generate_kubeconfig was NOT called (cache hit)")
                
                # Verify content is identical
                if kubeconfig1 == kubeconfig2:
                    print(f"   ✅ SUCCESS: Kubeconfig content is identical")
                else:
                    print(f"   ❌ ERROR: Kubeconfig content differs")
                    return False
                    
            except Exception as e:
                print(f"   Second access failed: {e}")
                return False
    
    print("\n3. Testing cache info...")
    cache_info = fetchsecrets.get_cache_info()
    print(f"   Total cache size: {cache_info['total_cache_size']}")
    print(f"   Kubeconfig caches: {cache_info['kubeconfig_caches']}")
    print(f"   Secret caches: {cache_info['secret_caches']}")
    
    if cache_info['kubeconfig_caches'] > 0:
        print(f"   ✅ SUCCESS: Kubeconfig cache detected")
    else:
        print(f"   ❌ ERROR: No kubeconfig cache found")
        return False
    
    print("\n4. Testing different cluster (should be separate cache)...")
    os.environ['RW_SECRETS_KEYS'] = json.dumps({
        'kubeconfig': 'azure:sp@kubeconfig:otherRG/otherCluster',
        'az_tenantId': 'file@/tmp/test_tenant',
        'az_clientId': 'file@/tmp/test_client', 
        'az_clientSecret': 'file@/tmp/test_secret'
    })
    
    with patch('RW.azure_utils.generate_kubeconfig_for_aks', side_effect=mock_generate_kubeconfig) as mock_gen:
        with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
            try:
                kubeconfig3 = fetchsecrets.read_secret('azure:sp@kubeconfig:otherRG/otherCluster')
                print(f"   Different cluster access successful, content length: {len(kubeconfig3)}")
                
                # Verify generate_kubeconfig WAS called (different cluster, cache miss)
                if mock_gen.called:
                    print(f"   ✅ SUCCESS: generate_kubeconfig was called for different cluster")
                else:
                    print(f"   ❌ ERROR: generate_kubeconfig was NOT called for different cluster")
                    return False
                    
            except Exception as e:
                print(f"   Different cluster access failed: {e}")
                return False
    
    final_cache_info = fetchsecrets.get_cache_info()
    print(f"   Final kubeconfig caches: {final_cache_info['kubeconfig_caches']}")
    
    if final_cache_info['kubeconfig_caches'] >= 2:
        print(f"   ✅ SUCCESS: Multiple kubeconfig caches detected")
    else:
        print(f"   ❌ ERROR: Expected multiple kubeconfig caches")
        return False
    
    # Cleanup
    for file_path in ['/tmp/test_tenant', '/tmp/test_client', '/tmp/test_secret']:
        if os.path.exists(file_path):
            os.remove(file_path)
    
    return True

if __name__ == '__main__':
    try:
        success = test_kubeconfig_caching()
        
        if success:
            print(f"\n🎉 Kubeconfig caching test completed successfully!")
            print(f"✅ First access generates kubeconfig via Azure API")
            print(f"✅ Second access uses cached kubeconfig content")
            print(f"✅ Different clusters get separate cache entries")
            print(f"✅ Cache statistics properly track kubeconfig caches")
        else:
            print(f"\n❌ Kubeconfig caching test failed!")
            
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc() 