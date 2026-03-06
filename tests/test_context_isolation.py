#!/usr/bin/env python3
"""
Test script to demonstrate credential context isolation.

This script shows how different credential configurations get different
filesystem cache directories to prevent credential conflicts.
"""

import os
import sys
import json
import tempfile

# Add the module path (go up one directory since we're in tests/)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_context_isolation():
    """Test that different credential contexts get different cache directories."""
    
    # Import the function we need
    from runrobot import _generate_credential_context_hash
    from RW import fetchsecrets
    
    print("=== Testing Credential Context Isolation ===\n")
    
    # Test Case 1: Default context (no secrets)
    print("1. Default context (no secrets configured):")
    os.environ['RW_SECRETS_KEYS'] = '{}'
    context1 = _generate_credential_context_hash()
    print(f"   Context hash: {context1}")
    
    # Test Case 2: Azure Service Principal Tenant A
    print("\n2. Azure Service Principal - Tenant A:")
    os.environ['RW_SECRETS_KEYS'] = json.dumps({
        'az_tenantId': 'tenant-aaaa-1111',
        'az_clientId': 'client-aaaa-1111', 
        'az_clientSecret': 'secret-aaaa-1111',
        'azure_kubeconfig': 'azure:sp@kubeconfig:myRG/cluster1'
    })
    context2 = _generate_credential_context_hash()
    print(f"   Context hash: {context2}")
    
    # Test Case 3: Azure Service Principal Tenant B
    print("\n3. Azure Service Principal - Tenant B:")
    os.environ['RW_SECRETS_KEYS'] = json.dumps({
        'az_tenantId': 'tenant-bbbb-2222',
        'az_clientId': 'client-bbbb-2222',
        'az_clientSecret': 'secret-bbbb-2222', 
        'azure_kubeconfig': 'azure:sp@kubeconfig:myRG/cluster2'
    })
    context3 = _generate_credential_context_hash()
    print(f"   Context hash: {context3}")
    
    # Test Case 4: Azure Managed Identity
    print("\n4. Azure Managed Identity:")
    os.environ['RW_SECRETS_KEYS'] = json.dumps({
        'azure_kubeconfig': 'azure:identity@kubeconfig:myRG/cluster3'
    })
    context4 = _generate_credential_context_hash()
    print(f"   Context hash: {context4}")
    
    # Test Case 5: Custom Vault Provider
    print("\n5. Custom Vault Provider:")
    os.environ['RW_SECRETS_KEYS'] = json.dumps({
        'custom_secret': 'my-vault@secret/path:field',
        'another_secret': 'my-vault@secret/other:value'
    })
    context5 = _generate_credential_context_hash()
    print(f"   Context hash: {context5}")
    
    # Test Case 6: Different Custom Vault Provider
    print("\n6. Different Custom Vault Provider:")
    os.environ['RW_SECRETS_KEYS'] = json.dumps({
        'custom_secret': 'other-vault@secret/path:field'
    })
    context6 = _generate_credential_context_hash()
    print(f"   Context hash: {context6}")
    
    # Verify contexts are different
    contexts = [context1, context2, context3, context4, context5, context6]
    unique_contexts = set(contexts)
    
    print(f"\n=== Results ===")
    print(f"Total contexts tested: {len(contexts)}")
    print(f"Unique contexts generated: {len(unique_contexts)}")
    print(f"Isolation working correctly: {len(contexts) == len(unique_contexts)}")
    
    if len(contexts) != len(unique_contexts):
        print("WARNING: Some contexts generated identical hashes!")
        for i, ctx in enumerate(contexts, 1):
            print(f"  Test case {i}: {ctx}")
    else:
        print("✅ All credential contexts are properly isolated!")
    
    # Test cache info with a specific context
    print(f"\n=== Cache Info Example ===")
    # Set up environment to simulate context 2
    os.environ['RW_SECRETS_KEYS'] = json.dumps({
        'az_tenantId': 'tenant-aaaa-1111',
        'az_clientId': 'client-aaaa-1111', 
        'az_clientSecret': 'secret-aaaa-1111'
    })
    # Simulate the directory being set (normally done by runrobot.py)
    os.environ['AZURE_CONFIG_DIR'] = f'/tmp/runwhen/shared_config/{context2}/.azure'
    os.environ['CLOUDSDK_CONFIG'] = f'/tmp/runwhen/shared_config/{context2}/.gcloud'
    
    cache_info = fetchsecrets.get_cache_info()
    print("Cache configuration:")
    for key, value in cache_info.items():
        print(f"  {key}: {value}")
    
    return len(contexts) == len(unique_contexts)

def demonstrate_directory_structure():
    """Show what the directory structure would look like."""
    print(f"\n=== Directory Structure Example ===")
    print(f"/tmp/runwhen/")
    print(f"├── shared_config/")
    print(f"│   ├── default/              # Default context (no specific credentials)")
    print(f"│   │   ├── .azure/")
    print(f"│   │   └── .gcloud/")
    print(f"│   ├── a1b2c3d4e5f6/         # Azure SP Tenant A context")
    print(f"│   │   ├── .azure/           # Tenant A credentials isolated here")
    print(f"│   │   └── .gcloud/")
    print(f"│   ├── f6e5d4c3b2a1/         # Azure SP Tenant B context")
    print(f"│   │   ├── .azure/           # Tenant B credentials isolated here") 
    print(f"│   │   └── .gcloud/")
    print(f"│   └── 9z8y7x6w5v4u/         # Custom vault context")
    print(f"│       ├── .azure/")
    print(f"│       └── .gcloud/")
    print(f"└── executions/               # Execution-specific (temporary)")
    print(f"    └── session1/req1/")
    print(f"        ├── codebundle/")
    print(f"        ├── robot_logs/")
    print(f"        └── workdir/")
    print(f"            └── .kube/        # Execution-specific kubeconfig")

if __name__ == '__main__':
    try:
        success = test_context_isolation()
        demonstrate_directory_structure()
        
        if success:
            print(f"\n🎉 Context isolation is working correctly!")
            print(f"Different credential configurations will use different cache directories.")
            sys.exit(0)
        else:
            print(f"\n❌ Context isolation test failed!")
            sys.exit(1)
            
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1) 