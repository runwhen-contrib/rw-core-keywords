import subprocess
import time
import hashlib
import logging
import json
from azure.identity import DefaultAzureCredential, ClientSecretCredential
from azure.mgmt.containerservice import ContainerServiceClient
from azure.core.exceptions import AzureError
from azure.mgmt.subscription import SubscriptionClient
from robot.libraries.BuiltIn import BuiltIn
import os
import sys
import yaml

logger = logging.getLogger(__name__)

# Azure credential cache
_azure_credential_cache = {}
_azure_credential_cache_ttl = {}

# Cache TTL for Azure credentials (1 hour by default)
AZURE_CREDENTIAL_TTL = int(os.getenv("RW_AZURE_CREDENTIAL_CACHE_TTL", "3600"))

def _generate_azure_cache_key(tenant_id=None, client_id=None, client_secret=None):
    """Generate cache key for Azure credentials."""
    if tenant_id and client_id and client_secret:
        # Hash the client_secret for security
        secret_hash = hashlib.sha256(client_secret.encode()).hexdigest()[:8]
        return f"azure_sp_{tenant_id}_{client_id}_{secret_hash}"
    else:
        return "azure_msi_default"

def _is_azure_cache_valid(cache_key: str) -> bool:
    """Check if cached Azure credential is still valid."""
    if cache_key not in _azure_credential_cache_ttl:
        return False
    return time.time() < _azure_credential_cache_ttl[cache_key]

def _cache_azure_credential(cache_key: str, credential, ttl_seconds: int):
    """Cache Azure credential with TTL."""
    _azure_credential_cache[cache_key] = credential
    _azure_credential_cache_ttl[cache_key] = time.time() + ttl_seconds

def _get_cached_azure_credential(cache_key: str):
    """Retrieve cached Azure credential if valid."""
    if _is_azure_cache_valid(cache_key):
        return _azure_credential_cache[cache_key]
    else:
        # Clean up expired cache entry
        if cache_key in _azure_credential_cache:
            del _azure_credential_cache[cache_key]
        if cache_key in _azure_credential_cache_ttl:
            del _azure_credential_cache_ttl[cache_key]
        return None

def _is_azure_cli_authenticated(azure_dir, expected_tenant_id=None, expected_client_id=None, expected_subscription_id=None):
    """
    Check if Azure CLI is authenticated with the correct credentials.
    
    This validates:
    1. Token files exist and are readable
    2. Current authentication matches expected tenant/client
    3. Tokens are not expired
    4. Correct subscription is selected (if specified)
    """
    if not azure_dir:
        logger.debug("CREDENTIAL_CACHE: No Azure config directory set")
        return False
        
    token_file = os.path.join(azure_dir, "accessTokens.json")
    config_file = os.path.join(azure_dir, "config")
    
    # Check if token files exist
    if not (os.path.exists(token_file) and os.path.exists(config_file)):
        logger.debug("CREDENTIAL_CACHE: Azure token files do not exist")
        return False
    
    try:
        # Check current authentication status
        result = subprocess.run(["az", "account", "show"], 
                              capture_output=True, text=True, check=True)
        account_info = json.loads(result.stdout)
        
        current_tenant_id = account_info.get("tenantId")
        current_user_name = account_info.get("user", {}).get("name")  # Service principal client ID
        current_subscription_id = account_info.get("id")
        
        logger.debug(f"CREDENTIAL_CACHE: Current Azure session - tenant: {current_tenant_id}, user: {current_user_name}, subscription: {current_subscription_id}")
        
        # Validate tenant matches (if specified)
        if expected_tenant_id and current_tenant_id != expected_tenant_id:
            logger.debug(f"CREDENTIAL_CACHE: Tenant mismatch - expected: {expected_tenant_id}, current: {current_tenant_id}")
            return False
            
        # Validate client/user matches (if specified)
        if expected_client_id and current_user_name != expected_client_id:
            logger.debug(f"CREDENTIAL_CACHE: Client ID mismatch - expected: {expected_client_id}, current: {current_user_name}")
            return False
            
        # Validate subscription matches (if specified)  
        if expected_subscription_id and current_subscription_id != expected_subscription_id:
            logger.debug(f"CREDENTIAL_CACHE: Subscription mismatch - expected: {expected_subscription_id}, current: {current_subscription_id}")
            return False
            
        logger.debug(f"CREDENTIAL_CACHE: Azure CLI authentication validated successfully")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.debug(f"CREDENTIAL_CACHE: Azure CLI authentication check failed: {e}")
        return False
    except json.JSONDecodeError as e:
        logger.debug(f"CREDENTIAL_CACHE: Failed to parse Azure account info: {e}")
        return False
    except Exception as e:
        logger.debug(f"CREDENTIAL_CACHE: Unexpected error checking Azure authentication: {e}")
        return False

def az_login(client_id=None, tenant_id=None, client_secret=None, subscription_id=None):
    """
    Perform az login using service principal credentials and set the subscription if provided.
    If no subscription ID is provided, attempt to retrieve it using the Azure SDK.
    """
    # Set Azure config dir back in robot (if running in Robot Framework context)
    azure_dir = os.environ.get("AZURE_CONFIG_DIR", "")
    try:
        BuiltIn().set_suite_variable("${AZURE_CONFIG_DIR}", azure_dir)
    except Exception:
        # Not running in Robot Framework context, skip setting suite variable
        pass
    
    # Check if already authenticated with the correct credentials
    if _is_azure_cli_authenticated(azure_dir, tenant_id, client_id, subscription_id):
        logger.info(f"CREDENTIAL_CACHE: Azure CLI already authenticated for correct tenant/client, reusing session")
        return  # Already authenticated with correct credentials

    credential, subscription_id = get_azure_credential(
        tenant_id=tenant_id, client_id=client_id, client_secret=client_secret
    )
    try:
        # Capture the output and error for more detailed logs
        if tenant_id and client_id and client_secret:
            logger.info(f"CREDENTIAL_CACHE: Performing Azure Service Principal login (tenant: {tenant_id[:8]}...)")
            print("Logging into Azure with Service Principal credentials...")
            result = subprocess.run([
                "az", "login",
                "--service-principal",
                "--username", client_id,
                "--password", client_secret,
                "--tenant", tenant_id
            ], capture_output=True, text=True, check=True)
            credential = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)

        else: 
            logger.info(f"CREDENTIAL_CACHE: Performing Azure Managed Identity login")
            print("Using managed service identity for authentication")
            result = subprocess.run([
                "az", "login",
                "--identity"
            ], capture_output=True, text=True, check=True)
            credential = DefaultAzureCredential()
              
        # Print the captured output and error logs
        print("Login output:", result.stdout)
        print("Login error output:", result.stderr)
        
        logger.info(f"CREDENTIAL_CACHE: Azure authentication successful, credentials stored in {azure_dir}")
        print("Login successful.")
        
        # If subscription_id is not provided, use get_subscription_id to determine it
        if not subscription_id:
            print("No subscription ID provided, attempting to retrieve it...")
            subscription_id = get_subscription_id(credential)
        
        # If subscription_id is determined (either passed or retrieved), set it in the Azure CLI
        if subscription_id:
            print(f"Setting subscription to: {subscription_id}")
            subprocess.run([
                "az", "account", "set", "--subscription", subscription_id
            ], check=True)
            logger.info(f"CREDENTIAL_CACHE: Azure subscription set to {subscription_id}")
            print(f"Subscription set to: {subscription_id}")
        else:
            logger.warning(f"CREDENTIAL_CACHE: Failed to determine Azure subscription ID")
            print("Failed to determine subscription ID. Proceeding without setting a specific subscription.")
        
    except subprocess.CalledProcessError as e:
        logger.error(f"CREDENTIAL_CACHE: Azure login failed: {e}")
        print(f"Azure login failed: {e}", file=sys.stderr)
        print("Standard output:", e.stdout)
        print("Standard error:", e.stderr)



def get_subscription_id(credential):
    try:
        print(f"Attempting to retrieve subscription ID with credential type: {type(credential)}")
        from azure.mgmt.subscription import SubscriptionClient
        subscription_client = SubscriptionClient(credential)
        subscription = next(subscription_client.subscriptions.list(), None)
        if not subscription:
            print("No subscriptions found for the provided credentials.", file=sys.stderr)
            return None
        print(f"Successfully retrieved subscription ID: {subscription.subscription_id[:4]}...")
        return subscription.subscription_id
    except AzureError as e:
        print(f"Azure error occurred while retrieving subscription ID: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Unexpected error occurred while retrieving subscription ID: {e}", file=sys.stderr)
        return None

def get_azure_credential(tenant_id=None, client_id=None, client_secret=None):
    """Obtain Azure credentials either through managed identity or service principal with caching."""
    
    # Generate cache key
    cache_key = _generate_azure_cache_key(tenant_id, client_id, client_secret)
    
    # Try to get cached credential
    cached_result = _get_cached_azure_credential(cache_key)
    if cached_result:
        print(f"Using cached Azure credential")
        return cached_result
    
    if tenant_id and client_id and client_secret:
        print("Creating new Azure Service Principal credential (cache miss)")
        credential = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
    else:
        print("Creating new Azure Managed Identity credential (cache miss)")
        try:
            credential = DefaultAzureCredential()
            print(f"DefaultAzureCredential obtained. Credential type: {type(credential)}")
        except Exception as e:
            print(f"Failed to authenticate using managed identity: {e}", file=sys.stderr)
            return None, None
    
    subscription_id = get_subscription_id(credential)
    result = (credential, subscription_id)
    
    # Cache the result
    _cache_azure_credential(cache_key, result, AZURE_CREDENTIAL_TTL)
    
    return result

def enumerate_subscriptions(credential):
    """
    Enumerate all subscriptions that the service principal has access to.
    """
    from azure.mgmt.subscription import SubscriptionClient
    subscription_client = SubscriptionClient(credential)
    accessible_subscriptions = []
    try:
        for subscription in subscription_client.subscriptions.list():
            accessible_subscriptions.append(subscription.subscription_id)
            print(f"Discovered accessible subscription ID: {subscription.subscription_id}")

    except AzureError as e:
        print(f"Failed to enumerate subscriptions: {e}", file=sys.stderr)

    return accessible_subscriptions


def generate_kubeconfig_for_aks(resource_group, cluster_name, tenant_id=None, client_id=None, client_secret=None):
    # Obtain the credential
    credential, _ = get_azure_credential(
        tenant_id=tenant_id, client_id=client_id, client_secret=client_secret
    )
    
    if not credential:
        print("Failed to obtain Azure credentials.", file=sys.stderr)
        return

    # Set Kubeconfig Path
    kubeconfig_path = os.environ.get("KUBECONFIG", "")
    BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
    
    # Get all accessible subscriptions
    accessible_subscriptions = enumerate_subscriptions(credential)
    
    # Search for the AKS cluster across accessible subscriptions
    subscription_id = None
    for sub_id in accessible_subscriptions:
        try:
            aks_client = ContainerServiceClient(credential, subscription_id=sub_id)
            print(f"Checking subscription {sub_id} for cluster {cluster_name} in resource group {resource_group}")
            
            # Try to retrieve the AKS cluster
            aks_client.managed_clusters.get(resource_group, cluster_name)
            print(f"Cluster {cluster_name} found in subscription {sub_id}")
            subscription_id = sub_id
            break  # Exit loop once the cluster is found
        except AzureError:
            print(f"Cluster {cluster_name} not found in subscription {sub_id}. Continuing search...")

    if subscription_id:
        try:
            aks_client = ContainerServiceClient(credential, subscription_id=subscription_id)
            print(f"Processing cluster: {cluster_name} in resource group: {resource_group} under subscription: {subscription_id}")
            kubeconfig = aks_client.managed_clusters.list_cluster_user_credentials(resource_group, cluster_name)
            kubeconfig_content = kubeconfig.kubeconfigs[0].value.decode('utf-8')
            convert_and_save_kubeconfig(kubeconfig_content, client_id, client_secret)
        except AzureError as e:
            print(f"Azure error occurred while processing cluster {cluster_name}: {e}", file=sys.stderr)
    else:
        print(f"Failed to locate the AKS cluster {cluster_name} in any accessible subscriptions. Attempting CLI login", file=sys.stderr)
        generate_kubeconfig_with_az_cli(resource_group, cluster_name)

def generate_kubeconfig_with_az_cli(resource_group, cluster_name):

    # Set Kubeconfig Path
    kubeconfig_path = os.environ.get("KUBECONFIG", "")
    BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
    
    try:
        print("Logging in to Azure using managed identity...")
        subprocess.run(["az", "login", "--identity"], check=True)
        
        print(f"Generating kubeconfig for AKS cluster: {cluster_name} in resource group: {resource_group}")
        subprocess.run([
            "az", "aks", "get-credentials",
            "--resource-group", resource_group,
            "--name", cluster_name,
            "--overwrite-existing",
            "--file", kubeconfig_path
        ], check=True)
        print("Successfully generated kubeconfig using Azure CLI.")

        # Convert kubeconfig using kubelogin
        convert_and_save_kubeconfig()

    except subprocess.CalledProcessError as e:
        print(f"Failed to generate kubeconfig using Azure CLI: {e}", file=sys.stderr)

def convert_and_save_kubeconfig(kubeconfig_content=None, client_id=None, client_secret=None):

    # Set Kubeconfig Path
    kubeconfig_path = os.environ.get("KUBECONFIG", "")
    BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
    

    if kubeconfig_content:
        print(f"Saving kubeconfig to: {kubeconfig_path}")

        # Write the kubeconfig content to file
        with open(kubeconfig_path, "w") as kubeconfig_file:
            kubeconfig_file.write(kubeconfig_content)
    else:
        print(f"No kubeconfig content provided; skipping save.")

    # Convert the kubeconfig using kubelogin for MSI or SPN
    if client_id and client_secret:
        convert_kubeconfig_using_kubelogin("spn", client_id, client_secret)
    else:
        convert_kubeconfig_using_kubelogin("msi")

    # Load the converted kubeconfig and update the kubelogin path
    with open(kubeconfig_path, "r") as kubeconfig_file:
        kubeconfig_yaml = yaml.safe_load(kubeconfig_file)

    # Ensure the kubelogin path is correctly set
    for user in kubeconfig_yaml.get('users', []):
        exec_config = user.get('user', {}).get('exec')
        if exec_config and exec_config.get('command') == 'kubelogin':
            print(f"Found exec command")
            exec_config['command'] = '/usr/local/bin/kubelogin'

    # Save the modified kubeconfig back to file
    with open(kubeconfig_path, "w") as kubeconfig_file:
        yaml.dump(kubeconfig_yaml, kubeconfig_file)

    print(f"Successfully saved kubeconfig with updated kubelogin path at {kubeconfig_path}")

def convert_kubeconfig_using_kubelogin(login_type="msi", client_id=None, client_secret=None):
    try:
        if login_type == "spn":
            print(f"Converting kubeconfig using kubelogin for client ID: {client_id}")
            subprocess.run(["/usr/local/bin/kubelogin", "convert-kubeconfig", "-l", "spn", "--client-id", client_id, "--client-secret", client_secret], check=True)
            print("Successfully converted kubeconfig with kubelogin for service principal.")
        else:
            print("Converting kubeconfig using kubelogin with Managed Service Identity (MSI)...")
            subprocess.run(["/usr/local/bin/kubelogin", "convert-kubeconfig", "-l", "msi"], check=True)
            print("Successfully converted kubeconfig with kubelogin for MSI.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to convert kubeconfig using kubelogin: {e}", file=sys.stderr)
    except FileNotFoundError:
        print("kubelogin binary not found. Please ensure it is installed and accessible in PATH.", file=sys.stderr)
