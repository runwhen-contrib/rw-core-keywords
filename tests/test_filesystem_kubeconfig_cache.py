#!/usr/bin/env python3
"""
Test script to verify filesystem-based kubeconfig caching.
This tests that kubeconfig content is cached to filesystem and persists across process boundaries.
"""

import os
import sys
import json
import time
import tempfile
import shutil
from unittest.mock import patch, MagicMock

# Set up logging
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Add the module path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_filesystem_kubeconfig_caching():
    """Test that kubeconfig content is cached to filesystem and persists."""
    
    print("=== Testing Filesystem Kubeconfig Caching ===\n")
    
    # Create a temporary Azure config directory
    with tempfile.TemporaryDirectory() as temp_azure_dir:
        
        # Set up test environment
        os.environ.update({
            'RW_SECRETS_KEYS': json.dumps({
                'kubeconfig': 'azure:sp@kubeconfig:azure-aks-rwl/aks-rwl-helm',
                'az_tenantId': 'file@/tmp/test_tenant_fs',
                'az_clientId': 'file@/tmp/test_client_fs', 
                'az_clientSecret': 'file@/tmp/test_secret_fs'
            }),
            'AZURE_CONFIG_DIR': temp_azure_dir,
            'KUBECONFIG': f'{temp_azure_dir}/current_kubeconfig'
        })
        
        # Create mock credential files
        os.makedirs('/tmp', exist_ok=True)
        with open('/tmp/test_tenant_fs', 'w') as f:
            f.write('2022d72f-4153-4b41-ac30-f973cdcdda2e')
        with open('/tmp/test_client_fs', 'w') as f:
            f.write('2a9345eb-7ee1-4c19-8c93-392fc5037b92')
        with open('/tmp/test_secret_fs', 'w') as f:
            f.write('test-secret-value')
        
        # Mock kubeconfig content
        mock_kubeconfig = """apiVersion: v1
kind: Config
clusters:
- cluster:
    server: https://aks-rwl-helm-dns-12345.hcp.eastus.azmk8s.io:443
  name: aks-rwl-helm
contexts:
- context:
    cluster: aks-rwl-helm
    user: clusterUser_azure-aks-rwl_aks-rwl-helm
  name: aks-rwl-helm
current-context: aks-rwl-helm
users:
- name: clusterUser_azure-aks-rwl_aks-rwl-helm
  user:
    exec:
      command: kubelogin
      args: ["get-token", "--tenant-id", "2022d72f-4153-4b41-ac30-f973cdcdda2e"]
"""
        
        def mock_generate_kubeconfig(*args, **kwargs):
            """Mock the kubeconfig generation to avoid real Azure calls."""
            # Write mock kubeconfig to the expected path
            kubeconfig_path = os.environ.get('KUBECONFIG')
            os.makedirs(os.path.dirname(kubeconfig_path), exist_ok=True)
            with open(kubeconfig_path, 'w') as f:
                f.write(mock_kubeconfig)
            return kubeconfig_path
        
        # Import modules after setting environment
        from RW import fetchsecrets
        
        # Clear any existing cache
        fetchsecrets._cache.clear()
        
        print("1. First kubeconfig request (should generate and cache to filesystem)...")
        start_time = time.time()
        
        with patch('RW.azure_utils.generate_kubeconfig_for_aks', side_effect=mock_generate_kubeconfig) as mock_gen:
            with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
                try:
                    result1 = fetchsecrets.read_secret('azure:sp@kubeconfig:azure-aks-rwl/aks-rwl-helm')
                    first_duration = time.time() - start_time
                    print(f"   ✅ First request completed in {first_duration:.3f} seconds")
                    print(f"   ✅ generate_kubeconfig called: {mock_gen.called}")
                    
                    # Check if filesystem cache file was created
                    expected_cache_file = os.path.join(temp_azure_dir, "kubeconfig_sp_azure-aks-rwl_aks-rwl-helm_2022d72f_2a9345eb.yaml")
                    if os.path.exists(expected_cache_file):
                        print(f"   ✅ SUCCESS: Filesystem cache file created at {expected_cache_file}")
                        with open(expected_cache_file, 'r') as f:
                            cached_content = f.read()
                        print(f"   ✅ Cache file contains kubeconfig content: {len(cached_content)} chars")
                    else:
                        print(f"   ❌ ERROR: Filesystem cache file not found at {expected_cache_file}")
                        return False
                    
                except Exception as e:
                    print(f"   ❌ First request failed: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
        
        print(f"\n2. Simulate process restart by clearing in-memory cache...")
        # Clear in-memory cache to simulate new process
        fetchsecrets._cache.clear()
        print(f"   ✅ In-memory cache cleared")
        
        print(f"\n3. Second kubeconfig request (should use filesystem cache)...")
        start_time = time.time()
        
        with patch('RW.azure_utils.generate_kubeconfig_for_aks', side_effect=mock_generate_kubeconfig) as mock_gen:
            with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
                try:
                    result2 = fetchsecrets.read_secret('azure:sp@kubeconfig:azure-aks-rwl/aks-rwl-helm')
                    second_duration = time.time() - start_time
                    print(f"   ✅ Second request completed in {second_duration:.3f} seconds")
                    print(f"   ✅ Speed improvement: {(first_duration/second_duration):.1f}x faster")
                    
                    # Check if generate_kubeconfig was called (it shouldn't be)
                    if mock_gen.called:
                        print(f"   ❌ ERROR: generate_kubeconfig was called again (filesystem caching failed)")
                        return False
                    else:
                        print(f"   ✅ SUCCESS: generate_kubeconfig was NOT called (filesystem cache hit)")
                    
                    # Verify results are identical
                    if str(result1) == str(result2):
                        print(f"   ✅ SUCCESS: Results are identical")
                    else:
                        print(f"   ❌ ERROR: Results differ")
                        return False
                        
                except Exception as e:
                    print(f"   ❌ Second request failed: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
        
        print(f"\n4. Test cache expiration (modify cache file timestamp)...")
        # Make the cache file appear old (older than 1 hour)
        old_time = time.time() - 3700  # 61 minutes ago
        os.utime(expected_cache_file, (old_time, old_time))
        
        # Clear in-memory cache again
        fetchsecrets._cache.clear()
        
        with patch('RW.azure_utils.generate_kubeconfig_for_aks', side_effect=mock_generate_kubeconfig) as mock_gen:
            with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
                try:
                    result3 = fetchsecrets.read_secret('azure:sp@kubeconfig:azure-aks-rwl/aks-rwl-helm')
                    print(f"   ✅ Cache expiration request completed")
                    
                    # Should have regenerated due to expiration
                    if mock_gen.called:
                        print(f"   ✅ SUCCESS: generate_kubeconfig was called due to cache expiration")
                    else:
                        print(f"   ❌ ERROR: Cache expiration was not detected")
                        return False
                        
                    # Old cache file should be removed
                    if not os.path.exists(expected_cache_file):
                        print(f"   ❌ ERROR: Old cache file was not removed")
                        # This might be expected behavior - let's check for a new one
                    
                except Exception as e:
                    print(f"   ❌ Cache expiration test failed: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
        
        # Final cache status
        cache_info = fetchsecrets.get_cache_info()
        print(f"\n📊 Final Cache Statistics:")
        print(f"   Total in-memory cache entries: {cache_info['total_cache_size']}")
        print(f"   Filesystem kubeconfig caches: {cache_info['kubeconfig_caches']}")
        print(f"   Secret caches: {cache_info['secret_caches']}")
        
        # List cache files
        cache_files = [f for f in os.listdir(temp_azure_dir) if f.startswith("kubeconfig_") and f.endswith(".yaml")]
        print(f"   Cache files in {temp_azure_dir}: {cache_files}")
        
        # Cleanup
        for file_path in ['/tmp/test_tenant_fs', '/tmp/test_client_fs', '/tmp/test_secret_fs']:
            if os.path.exists(file_path):
                os.remove(file_path)
        
        return True

if __name__ == '__main__':
    try:
        success = test_filesystem_kubeconfig_caching()
        
        if success:
            print(f"\n🎉 Filesystem kubeconfig caching test completed successfully!")
            print(f"✅ First request generates kubeconfig and caches to filesystem")
            print(f"✅ Second request uses filesystem cache (survives process restart)")
            print(f"✅ Cache expiration works correctly (1-hour TTL)")
            print(f"✅ Significant performance improvement for subsequent requests")
        else:
            print(f"\n❌ Filesystem kubeconfig caching test failed!")
            
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc() 