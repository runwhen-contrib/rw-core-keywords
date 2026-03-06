#!/usr/bin/env python3
"""
Simple test for credential context isolation logic.
"""

import os
import json
import hashlib

def generate_credential_context_hash():
    """Generate a hash representing the current credential context."""
    context_data = []
    
    # Get secrets configuration to determine credential context
    secrets_keys_str = os.getenv('RW_SECRETS_KEYS', '{}')
    try:
        secrets_config = json.loads(secrets_keys_str)
    except json.JSONDecodeError:
        secrets_config = {}
    
    # Add relevant environment variables that affect credential context
    context_vars = [
        'RW_WORKSPACE',
        'RW_LOCATION', 
        'RW_VAULT_ADDR',
        'RW_VAULT_APPROLE_ROLE_ID',
        'RW_LOCATION_VAULT_AUTH_MOUNT_POINT'
    ]
    
    for var in context_vars:
        value = os.getenv(var, '')
        if value:
            context_data.append(f"{var}={value}")
    
    # Analyze secrets to identify credential-affecting patterns
    azure_contexts = []
    custom_vault_contexts = []
    
    for secret_name, secret_key in secrets_config.items():
        if isinstance(secret_key, str):
            # Check for Azure contexts
            if 'azure:sp' in secret_key:
                # Azure Service Principal - extract resource info for context
                azure_contexts.append(f"azure_sp_{secret_key}")
            elif 'azure:identity' in secret_key:
                # Azure Managed Identity - extract resource info for context  
                azure_contexts.append(f"azure_identity_{secret_key}")
            elif 'az_clientId' in secret_name or 'az_tenantId' in secret_name:
                # Different Azure service principals should have different contexts
                if 'az_tenantId' in secret_name:
                    # This is a tenant ID - it defines a unique Azure context
                    azure_contexts.append(f"azure_tenant_{secret_key}")
                elif 'az_clientId' in secret_name:
                    # This is a client ID - it defines a unique Azure context
                    azure_contexts.append(f"azure_client_{secret_key}")
            
            # Check for custom vault contexts
            if '@' in secret_key and secret_key.split('@')[0] not in ['azure:identity', 'azure:sp', 'file', 'env']:
                # This is a custom provider
                provider = secret_key.split('@')[0]
                custom_vault_contexts.append(f"custom_vault_{provider}")
    
    # Add Azure contexts (deduplicated)
    for azure_context in set(azure_contexts):
        context_data.append(azure_context)
    
    # Add custom vault contexts (deduplicated)  
    for vault_context in set(custom_vault_contexts):
        context_data.append(vault_context)
    
    # Sort for deterministic hashing
    context_data.sort()
    context_string = '|'.join(context_data)
    
    # Generate hash
    if context_string:
        context_hash = hashlib.sha256(context_string.encode()).hexdigest()[:12]  # 12 chars for readability
    else:
        context_hash = "default"
    
    return context_hash, context_string

def test_context_isolation():
    """Test that different credential contexts get different cache directories."""
    
    print("=== Testing Credential Context Isolation ===\n")
    
    test_cases = [
        ("Default context (no secrets)", '{}'),
        ("Azure Service Principal - Tenant A", json.dumps({
            'az_tenantId': 'tenant-aaaa-1111',
            'az_clientId': 'client-aaaa-1111', 
            'az_clientSecret': 'secret-aaaa-1111',
            'azure_kubeconfig': 'azure:sp@kubeconfig:myRG/cluster1'
        })),
        ("Azure Service Principal - Tenant B", json.dumps({
            'az_tenantId': 'tenant-bbbb-2222',
            'az_clientId': 'client-bbbb-2222',
            'az_clientSecret': 'secret-bbbb-2222', 
            'azure_kubeconfig': 'azure:sp@kubeconfig:myRG/cluster2'
        })),
        ("Azure Managed Identity", json.dumps({
            'azure_kubeconfig': 'azure:identity@kubeconfig:myRG/cluster3'
        })),
        ("Custom Vault Provider A", json.dumps({
            'custom_secret': 'my-vault@secret/path:field',
            'another_secret': 'my-vault@secret/other:value'
        })),
        ("Custom Vault Provider B", json.dumps({
            'custom_secret': 'other-vault@secret/path:field'
        }))
    ]
    
    contexts = []
    
    for i, (description, secrets_config) in enumerate(test_cases, 1):
        print(f"{i}. {description}:")
        os.environ['RW_SECRETS_KEYS'] = secrets_config
        context_hash, context_string = generate_credential_context_hash()
        print(f"   Context hash: {context_hash}")
        print(f"   Context data: {context_string[:80]}{'...' if len(context_string) > 80 else ''}")
        contexts.append(context_hash)
    
    # Verify contexts are different
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
    
    return len(contexts) == len(unique_contexts)

def demonstrate_directory_structure():
    """Show what the directory structure would look like."""
    print(f"\n=== Directory Structure Example ===")
    print(f"/tmp/runwhen/")
    print(f"├── shared_config/                    # Context-isolated credential caching")
    print(f"│   ├── default/                      # Default context")
    print(f"│   │   ├── .azure/")
    print(f"│   │   └── .gcloud/")
    print(f"│   ├── a1b2c3d4e5f6/                 # Azure SP Tenant A")
    print(f"│   │   ├── .azure/                   # Isolated Azure credentials")
    print(f"│   │   └── .gcloud/")
    print(f"│   ├── f6e5d4c3b2a1/                 # Azure SP Tenant B")
    print(f"│   │   ├── .azure/                   # Different tenant credentials")
    print(f"│   │   └── .gcloud/")
    print(f"│   └── 9z8y7x6w5v4u/                 # Custom vault context")
    print(f"│       ├── .azure/")
    print(f"│       └── .gcloud/")
    print(f"└── executions/                       # Execution-specific (temporary)")
    print(f"    ├── session1/req1/")
    print(f"    │   ├── codebundle/               # Codebundle working directory")
    print(f"    │   ├── robot_logs/               # Robot execution logs")
    print(f"    │   └── workdir/")
    print(f"    │       └── .kube/config          # Execution-specific kubeconfig")
    print(f"    └── session1/req2/")
    print(f"        ├── codebundle/")
    print(f"        └── robot_logs/")
    
    print(f"\n=== How It Works ===")
    print(f"1. Each codebundle execution analyzes its RW_SECRETS_KEYS configuration")
    print(f"2. A context hash is generated based on credential-affecting secrets")
    print(f"3. Authentication state directories use the context hash for isolation")
    print(f"4. Codebundles with same credentials share cache directories")
    print(f"5. Codebundles with different credentials get separate directories")

if __name__ == '__main__':
    try:
        success = test_context_isolation()
        demonstrate_directory_structure()
        
        if success:
            print(f"\n🎉 Context isolation is working correctly!")
            print(f"Different credential configurations will use different cache directories.")
        else:
            print(f"\n❌ Context isolation test failed!")
            
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc() 