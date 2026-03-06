#!/usr/bin/env python3
"""
Test script to verify credential-level caching for Azure authentication.
This tests that Azure CLI authentication is cached at the credential level,
not at the secret level.
"""

import os
import sys
import json
import logging
import tempfile
from unittest.mock import patch, MagicMock

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Add the module path (go up one directory since we're in tests/)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_credential_level_caching():
    """Test that Azure authentication is cached at the credential level."""
    
    print("=== Testing Credential-Level Caching ===\n")
    
    # Create a temporary Azure config directory
    with tempfile.TemporaryDirectory() as temp_azure_dir:
        
        # Set up test environment
        os.environ.update({
            'RW_SECRETS_KEYS': json.dumps({
                'azure_credentials': 'azure:sp@cli',
                'az_tenantId': 'file@/tmp/test_tenant_cred',
                'az_clientId': 'file@/tmp/test_client_cred', 
                'az_clientSecret': 'file@/tmp/test_secret_cred'
            }),
            'AZURE_CONFIG_DIR': temp_azure_dir
        })
        
        # Create mock credential files
        os.makedirs('/tmp', exist_ok=True)
        with open('/tmp/test_tenant_cred', 'w') as f:
            f.write('test-tenant-id')
        with open('/tmp/test_client_cred', 'w') as f:
            f.write('test-client-id')
        with open('/tmp/test_secret_cred', 'w') as f:
            f.write('test-client-secret')
        
        # Import modules after setting environment
        from RW import fetchsecrets
        
        # Mock the subprocess calls for Azure CLI
        mock_account_info = {
            "id": "test-subscription-id",
            "tenantId": "test-tenant-id", 
            "user": {"name": "test-client-id", "type": "servicePrincipal"},
            "state": "Enabled"
        }
        
        def mock_subprocess_run(cmd, **kwargs):
            """Mock subprocess.run for Azure CLI commands."""
            if cmd == ["az", "account", "show"]:
                # First call should fail (not authenticated)
                if not hasattr(mock_subprocess_run, 'call_count'):
                    mock_subprocess_run.call_count = 0
                mock_subprocess_run.call_count += 1
                
                if mock_subprocess_run.call_count == 1:
                    # First call - not authenticated
                    raise subprocess.CalledProcessError(1, cmd, "Not logged in")
                else:
                    # Subsequent calls - authenticated
                    result = MagicMock()
                    result.stdout = json.dumps(mock_account_info)
                    result.returncode = 0
                    return result
                    
            elif cmd[0] == "az" and cmd[1] == "login":
                # Mock successful login
                result = MagicMock()
                result.stdout = json.dumps([mock_account_info])
                result.stderr = ""
                result.returncode = 0
                return result
                
            elif cmd[0] == "az" and cmd[1] == "account" and cmd[2] == "set":
                # Mock successful subscription set
                result = MagicMock()
                result.returncode = 0
                return result
                
            else:
                # Default mock
                result = MagicMock()
                result.returncode = 0
                return result
        
        # Clear any existing cache
        fetchsecrets._cache.clear()
        
        print("1. Testing first Azure authentication (should perform az login)...")
        import subprocess
        with patch('subprocess.run', side_effect=mock_subprocess_run):
            with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
                try:
                    auth_result1 = fetchsecrets.read_secret('azure:sp@cli')
                    print(f"   First auth successful: {auth_result1}")
                    print(f"   subprocess.run call count: {getattr(mock_subprocess_run, 'call_count', 0)}")
                    
                    # Should have called az login (call count > 1)
                    if getattr(mock_subprocess_run, 'call_count', 0) > 1:
                        print(f"   ✅ SUCCESS: az login was performed on first access")
                    else:
                        print(f"   ❌ ERROR: az login was NOT performed on first access")
                        return False
                        
                except Exception as e:
                    print(f"   First auth failed: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
        
        print("\n2. Testing second Azure authentication (should reuse credentials)...")
        # Reset call counter but keep the "authenticated" state
        mock_subprocess_run.call_count = 0
        
        with patch('subprocess.run', side_effect=mock_subprocess_run):
            with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
                try:
                    auth_result2 = fetchsecrets.read_secret('azure:sp@cli')
                    print(f"   Second auth successful: {auth_result2}")
                    print(f"   subprocess.run call count: {getattr(mock_subprocess_run, 'call_count', 0)}")
                    
                    # Should NOT have called az login (only az account show)
                    if getattr(mock_subprocess_run, 'call_count', 0) == 1:
                        print(f"   ✅ SUCCESS: Only validation call made, no re-authentication")
                    else:
                        print(f"   ❌ ERROR: Multiple calls made, authentication was not cached")
                        return False
                        
                    # Results should be identical
                    if auth_result1 == auth_result2:
                        print(f"   ✅ SUCCESS: Authentication results are identical")
                    else:
                        print(f"   ❌ ERROR: Authentication results differ")
                        return False
                        
                except Exception as e:
                    print(f"   Second auth failed: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
        
        print("\n3. Testing different tenant (should re-authenticate)...")
        # Change tenant to test credential isolation
        with open('/tmp/test_tenant_cred', 'w') as f:
            f.write('different-tenant-id')
        
        # Update mock to return different tenant
        mock_account_info["tenantId"] = "different-tenant-id"
        mock_subprocess_run.call_count = 0
        
        # Clear secret-level cache to force re-evaluation
        if 'azure:sp@cli' in fetchsecrets._cache:
            del fetchsecrets._cache['azure:sp@cli']
        
        with patch('subprocess.run', side_effect=mock_subprocess_run):
            with patch('robot.libraries.BuiltIn.BuiltIn.set_suite_variable'):
                try:
                    auth_result3 = fetchsecrets.read_secret('azure:sp@cli')
                    print(f"   Different tenant auth successful: {auth_result3}")
                    print(f"   subprocess.run call count: {getattr(mock_subprocess_run, 'call_count', 0)}")
                    
                    # Should have re-authenticated due to tenant mismatch
                    if getattr(mock_subprocess_run, 'call_count', 0) > 1:
                        print(f"   ✅ SUCCESS: Re-authentication performed for different tenant")
                    else:
                        print(f"   ❌ ERROR: Re-authentication was NOT performed for different tenant")
                        return False
                        
                except Exception as e:
                    print(f"   Different tenant auth failed: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
        
        # Cleanup
        for file_path in ['/tmp/test_tenant_cred', '/tmp/test_client_cred', '/tmp/test_secret_cred']:
            if os.path.exists(file_path):
                os.remove(file_path)
        
        return True

if __name__ == '__main__':
    try:
        success = test_credential_level_caching()
        
        if success:
            print(f"\n🎉 Credential-level caching test completed successfully!")
            print(f"✅ First access performs Azure CLI authentication")
            print(f"✅ Second access validates existing authentication (no re-login)")
            print(f"✅ Different credentials trigger re-authentication")
            print(f"✅ Caching happens at the credential level, not secret level")
        else:
            print(f"\n❌ Credential-level caching test failed!")
            
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc() 