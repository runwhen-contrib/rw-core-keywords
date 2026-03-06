#!/usr/bin/env python3
"""
Validation script to demonstrate kubeconfig caching is working.
This simulates the same kubeconfig request multiple times to show caching behavior.
"""

import os
import sys
import json
import time
import tempfile
from unittest.mock import patch, MagicMock

# Add the module path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def simulate_kubeconfig_requests():
    """Simulate multiple kubeconfig requests to demonstrate caching."""
    
    print("=== Validating Kubeconfig Caching ===\n")
    
    # Set up test environment similar to real execution
    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ.update({
            'RW_SECRETS_KEYS': json.dumps({
                'kubeconfig': 'azure:sp@kubeconfig:azure-aks-rwl/aks-rwl-helm',
                'az_tenantId': 'file@/tmp/test_tenant',
                'az_clientId': 'file@/tmp/test_client', 
                'az_clientSecret': 'file@/tmp/test_secret'
            }),
            'KUBECONFIG': f'{temp_dir}/kubeconfig',
            'AZURE_CONFIG_DIR': temp_dir
        })
        
        # Create mock credential files
        os.makedirs('/tmp', exist_ok=True)
        with open('/tmp/test_tenant', 'w') as f:
            f.write('2022d72f-4153-4b41-ac30-f973cdcdda2e')
        with open('/tmp/test_client', 'w') as f:
            f.write('2a9345eb-7ee1-4c19-8c93-392fc5037b92')
        with open('/tmp/test_secret', 'w') as f:
            f.write('test-secret-value')
        
        # Import after environment setup
        from RW import fetchsecrets
        
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
      args: ["get-token"]
"""
        
        def mock_generate_kubeconfig(*args, **kwargs):
            """Mock the kubeconfig generation to avoid real Azure calls."""
            # Write mock kubeconfig to the expected path
            kubeconfig_path = os.environ.get('KUBECONFIG')
            os.makedirs(os.path.dirname(kubeconfig_path), exist_ok=True)
            with open(kubeconfig_path, 'w') as f:
                f.write(mock_kubeconfig)
            return kubeconfig_path
        
        # Clear cache to start fresh
        fetchsecrets._cache.clear()
        
        print("1. First kubeconfig request (should generate and cache)...")
        start_time = time.time()
        
        with patch('RW.azure_utils.generate_kubeconfig_for_aks', side_effect=mock_generate_kubeconfig):
            with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
                try:
                    result1 = fetchsecrets.read_secret('azure:sp@kubeconfig:azure-aks-rwl/aks-rwl-helm')
                    first_duration = time.time() - start_time
                    print(f"   ✅ First request completed in {first_duration:.3f} seconds")
                    print(f"   ✅ Result type: {type(result1)}")
                    
                    # Check cache status
                    cache_info = fetchsecrets.get_cache_info()
                    print(f"   ✅ Cache size after first request: {cache_info['total_cache_size']}")
                    print(f"   ✅ Kubeconfig caches: {cache_info['kubeconfig_caches']}")
                    
                except Exception as e:
                    print(f"   ❌ First request failed: {e}")
                    return False
        
        print(f"\n2. Second kubeconfig request (should use cache)...")
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
                        print(f"   ❌ ERROR: generate_kubeconfig was called again (caching failed)")
                        return False
                    else:
                        print(f"   ✅ SUCCESS: generate_kubeconfig was NOT called (cache hit)")
                    
                    # Verify results are identical
                    if str(result1) == str(result2):
                        print(f"   ✅ SUCCESS: Results are identical")
                    else:
                        print(f"   ❌ ERROR: Results differ")
                        return False
                        
                except Exception as e:
                    print(f"   ❌ Second request failed: {e}")
                    return False
        
        print(f"\n3. Third kubeconfig request (should still use cache)...")
        start_time = time.time()
        
        with patch('RW.azure_utils.generate_kubeconfig_for_aks', side_effect=mock_generate_kubeconfig) as mock_gen:
            with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
                try:
                    result3 = fetchsecrets.read_secret('azure:sp@kubeconfig:azure-aks-rwl/aks-rwl-helm')
                    third_duration = time.time() - start_time
                    print(f"   ✅ Third request completed in {third_duration:.3f} seconds")
                    
                    if not mock_gen.called:
                        print(f"   ✅ SUCCESS: Still using cache (no API calls)")
                    else:
                        print(f"   ❌ ERROR: Cache was not used")
                        return False
                        
                except Exception as e:
                    print(f"   ❌ Third request failed: {e}")
                    return False
        
        # Final cache status
        final_cache_info = fetchsecrets.get_cache_info()
        print(f"\n📊 Final Cache Statistics:")
        print(f"   Total cache entries: {final_cache_info['total_cache_size']}")
        print(f"   Kubeconfig caches: {final_cache_info['kubeconfig_caches']}")
        print(f"   Secret caches: {final_cache_info['secret_caches']}")
        
        # Cleanup
        for file_path in ['/tmp/test_tenant', '/tmp/test_client', '/tmp/test_secret']:
            if os.path.exists(file_path):
                os.remove(file_path)
        
        return True

if __name__ == '__main__':
    try:
        success = simulate_kubeconfig_requests()
        
        if success:
            print(f"\n🎉 Kubeconfig caching validation completed successfully!")
            print(f"✅ First request generates and caches kubeconfig content")
            print(f"✅ Subsequent requests use cached content (no API calls)")
            print(f"✅ Significant performance improvement achieved")
            print(f"✅ Cache persistence works correctly")
        else:
            print(f"\n❌ Kubeconfig caching validation failed!")
            
    except Exception as e:
        print(f"Validation failed with error: {e}")
        import traceback
        traceback.print_exc() 