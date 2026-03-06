"""
Fetch and load secrets for this workspace container.

Intended to pair with the writevaultutils here - https://github.com/project-468/468-platform/tree/main/utils and
see wiki page on this design here - https://project-468.atlassian.net/wiki/spaces/ENG/pages/10518536/SLI+Troubleshooting.
"""
import os
import requests
import hvac
import logging
import json
import time
import hashlib
from enum import Enum
from . import proxy
from . import azure_utils
from . import gcp_utils
from . import aws_utils


REQUEST_VERIFY=proxy.get_request_verify()

# Updated to support RW_VAULT_ADDR with fallback to RW_VAULT_URL for legacy support
VAULT_ADDR = os.getenv("RW_VAULT_ADDR") or os.getenv("RW_VAULT_URL")
WORKSPACE_NAME = os.getenv("RW_WORKSPACE")
LOCATION_NAME = os.getenv("RW_LOCATION")
LOCATION_VAULT_AUTH_MOUNT_POINT = os.getenv("RW_LOCATION_VAULT_AUTH_MOUNT_POINT")
VAULT_APPROLE_ROLE_ID = os.getenv("RW_VAULT_APPROLE_ROLE_ID")
VAULT_APPROLE_SECRET_ID = os.getenv("RW_VAULT_APPROLE_SECRET_ID")

# K8s by default mounts a token for the container's default service account at the following
# path in the filesystem --
KUBERNETES_SERVICE_ACCOUNT_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"

# Secret value cache (existing functionality)
_cache = {}

# Cache TTL settings (in seconds) - now primarily for documentation
VAULT_TOKEN_TTL = int(os.getenv("RW_VAULT_TOKEN_CACHE_TTL", "1800"))  # 30 minutes
AZURE_CREDENTIAL_TTL = int(os.getenv("RW_AZURE_CREDENTIAL_CACHE_TTL", "3600"))  # 1 hour
GCP_CREDENTIAL_TTL = int(os.getenv("RW_GCP_CREDENTIAL_CACHE_TTL", "3600"))  # 1 hour
AWS_CREDENTIAL_TTL = int(os.getenv("RW_AWS_CREDENTIAL_CACHE_TTL", "3600"))  # 1 hour
CUSTOM_VAULT_TOKEN_TTL = int(os.getenv("RW_CUSTOM_VAULT_TOKEN_CACHE_TTL", "1800"))  # 30 minutes
K8S_SECRET_CACHE_TTL = int(os.getenv("RW_K8S_SECRET_CACHE_TTL", "3600"))  # 1 hour

logger = logging.getLogger(__name__)

class SecretProvider(Enum):
    RUNWHEN_VAULT = "runwhen-vault"
    CUSTOM = "custom"
    FILE = "file"
    ENV = "env"
    AZURE_IDENTITY = "azure-identity"
    AZURE_SP = "azure-sp"
    GCP_ADC = "gcp-adc"
    GCP_SA = "gcp-sa"
    # AWS providers
    AWS_IRSA = "aws-irsa"  # IRSA (IAM Roles for Service Accounts)
    AWS_ACCESS_KEY = "aws-access-key"  # Explicit access key credentials
    AWS_ASSUME_ROLE = "aws-assume-role"  # Assume role authentication
    AWS_DEFAULT = "aws-default"  # Default credential chain
    AWS_WORKLOAD_IDENTITY = "aws-workload-identity"  # Alias for IRSA (EKS kubeconfig)
    AWS_CLI = "aws-cli"  # AWS CLI with explicit credentials (EKS kubeconfig)
    K8S_FILE = "k8s-file"  # Read secret data from a Kubernetes Secret or ConfigMap (file mount)
    K8S_ENV = "k8s-env"  # Read secret data from a Kubernetes Secret or ConfigMap (env var)
    
_current_secret_provider: SecretProvider = SecretProvider.RUNWHEN_VAULT
SECRET_PROVIDER_SYMBOL: str = "@"


class AuthenticationError(Exception):
    pass

class SecretNotFoundError(Exception):
    pass


def get_cache_info():
    """Get information about filesystem-based credential caching."""
    azure_config_dir = os.environ.get("AZURE_CONFIG_DIR", "Not set")
    gcloud_config_dir = os.environ.get("CLOUDSDK_CONFIG", "Not set")
    aws_config_dir = os.environ.get("AWS_CONFIG_DIR", os.path.expanduser("~/.aws"))
    
    # Extract context hash from directory path for display
    context_hash = "unknown"
    if azure_config_dir != "Not set":
        try:
            # Extract context from path like /tmp/runwhen/shared_config/abc123def456/.azure
            path_parts = azure_config_dir.split('/')
            if 'shared_config' in path_parts:
                idx = path_parts.index('shared_config')
                if idx + 1 < len(path_parts):
                    context_hash = path_parts[idx + 1]
        except:
            pass
    
    # Collect cache directory statistics
    cache_stats = _get_cache_directory_stats(azure_config_dir, gcloud_config_dir, aws_config_dir)
    
    # Analyze secret cache contents (in-memory)
    secret_caches = len(_cache)
    
    # Count filesystem kubeconfig caches (from all providers)
    kubeconfig_caches = 0
    for config_dir in [azure_config_dir, aws_config_dir]:
        if config_dir and config_dir != "Not set" and os.path.exists(config_dir):
            try:
                for filename in os.listdir(config_dir):
                    if filename.startswith("kubeconfig_") and filename.endswith(".yaml"):
                        kubeconfig_caches += 1
            except Exception as e:
                logger.debug(f"CREDENTIAL_CACHE: Error counting kubeconfig cache files in {config_dir}: {e}")
    
    # Get AWS cache info
    aws_cache_info = aws_utils.get_cache_info() if hasattr(aws_utils, 'get_cache_info') else {}
    
    return {
        "caching_method": "context_isolated_filesystem_with_credential_validation",
        "credential_context_hash": context_hash,
        "azure_config_dir": azure_config_dir,
        "gcloud_config_dir": gcloud_config_dir,
        "aws_config_dir": aws_config_dir,
        "total_cache_size": len(_cache),
        "kubeconfig_caches": kubeconfig_caches,
        "secret_caches": secret_caches,
        "cache_directory_stats": cache_stats,
        "aws_credential_cache": aws_cache_info,
        "description": "Azure/AWS/GCP credential authentication cached at filesystem level with validation, kubeconfig content cached in filesystem with 1-hour TTL"
    }


def _get_cache_directory_stats(azure_dir, gcloud_dir, aws_dir=None):
    """Get statistics about cache directories."""
    stats = {}
    
    directories = [("azure", azure_dir), ("gcloud", gcloud_dir)]
    if aws_dir:
        directories.append(("aws", aws_dir))
    
    for name, directory in directories:
        if directory == "Not set" or not directory or not os.path.exists(directory):
            stats[name] = {"exists": False, "files": 0, "size_mb": 0}
            continue
            
        try:
            file_count = 0
            total_size = 0
            
            for root, dirs, files in os.walk(directory):
                file_count += len(files)
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        total_size += os.path.getsize(file_path)
                    except OSError:
                        pass
            
            stats[name] = {
                "exists": True,
                "files": file_count,
                "size_mb": round(total_size / (1024 * 1024), 2)
            }
            
        except Exception as e:
            logger.debug(f"Error collecting stats for {directory}: {e}")
            stats[name] = {"exists": True, "files": "unknown", "size_mb": "unknown"}
    
    return stats


def health_check():
    """ Checks that any required vars for this secrets engine to work are, indeed, set.
        Raise AssertionError if this check fails.
    """
    # Make sure that the env vars we need exist
    if not VAULT_ADDR or not WORKSPACE_NAME or not LOCATION_NAME or not LOCATION_VAULT_AUTH_MOUNT_POINT or not VAULT_APPROLE_ROLE_ID:
        raise AssertionError(
            f"Trying to fetch RW_VAULT_URL, RW_WORKSPACE and RW_LOCATION from env vars, but got"
            + f" {VAULT_ADDR}, {WORKSPACE_NAME}, {LOCATION_NAME}, {LOCATION_VAULT_AUTH_MOUNT_POINT}, {VAULT_APPROLE_ROLE_ID}"
        )

def about():
    """Returns a dict of info identifying this particular fetchsecrets plugin"""
    return {
        "author": "kyle",
        "version": "0.4",  # Version updated to reflect shared filesystem caching
        "description": "Updated fetchsecrets implementation with shared filesystem-based credential caching",
        "home_url": "https://runwhen.com/about/fetchsecrets",
    }

def _kubernetes_vault_login(role: str, vault_url: str, auth_mount_point: str = LOCATION_VAULT_AUTH_MOUNT_POINT):
    """Return an authenticated vault client for the role using K8s auth bootstrapping
    
    Args:
    role (str): The role to use (see module vars above)
    vault_url (str): Begins with https://, expected from settings
    auth_mount_point (str): For corestate and backend, leave as default.  This changes only in the locations case where it should be
    
    Returns:
    Authenticated hvac client, or throws FileNotFoundError (needs K8s sa token) or AuthenticationError
    """
    try:
        with open(KUBERNETES_SERVICE_ACCOUNT_TOKEN_PATH, "r") as f:
            token = f.read()
            f.close()

        client = hvac.Client(url=vault_url, verify=REQUEST_VERIFY)
        client.auth.kubernetes.login(role, token, mount_point=auth_mount_point)
        return client
    except FileNotFoundError as e:
        raise FileNotFoundError(
            (
                f"The K8s service account token was not found at path {KUBERNETES_SERVICE_ACCOUNT_TOKEN_PATH}.",
                f"  This token bootstraps the vault auth process.  Is this being run from inside a K8s container?",
            )
        )
    except Exception as e:
        pod_service_account_name = os.getenv("MY_POD_SERVICE_ACCOUNT")
        raise AuthenticationError(
            f"Failed vault-k8s authentication using role {role}, auth mount point {auth_mount_point} and the k8s service account token found at {KUBERNETES_SERVICE_ACCOUNT_TOKEN_PATH} with MY_POD_SERVICE_ACCOUNT set to {pod_service_account_name}: {type(e)}: {str(e)}"
        )

def _approle_vault_login(vault_addr: str, role_id: str, secret_id: str, auth_mount_point: str):
    """Authenticate to Vault using AppRole auth method.
    See https://hvac.readthedo  cs.io/en/stable/usage/auth_methods/approle.html
    """
    try:
        client = hvac.Client(url=vault_addr, verify=REQUEST_VERIFY)
        client.auth.approle.login(role_id=role_id, secret_id=secret_id, mount_point=auth_mount_point)
        return client
    except Exception as e:
        raise AuthenticationError(f"Failed AppRole authentication: {e}")


def _try_cached_token_login(vault_addr: str):
    """Try to authenticate using a cached token from file or environment.
    
    Priority:
    1. VAULT_TOKEN_FILE - Read token from file (cached by worker)
    2. VAULT_TOKEN - Direct token from environment
    
    Returns:
        Authenticated hvac client if token is valid, None otherwise
    """
    def _authenticate_with_token(token: str, method: str, details: dict = None):
        """Helper function to authenticate with a token and log the result."""
        if not token or not token.strip():
            return None
        
        token = token.strip()
        try:
            client = hvac.Client(url=vault_addr, token=token, verify=REQUEST_VERIFY)
            if client.is_authenticated():
                _log_vault_auth_method(method, True, details)
                return client
            else:
                log_details = details.copy() if details else {}
                log_details['reason'] = 'token_invalid'
                _log_vault_auth_method(method, False, log_details)
        except Exception as e:
            log_details = details.copy() if details else {}
            log_details['reason'] = str(e)
            _log_vault_auth_method(method, False, log_details)
        return None
    
    # Try to get token from file first
    token_file = os.getenv('VAULT_TOKEN_FILE')
    if token_file and os.path.exists(token_file):
        try:
            with open(token_file, 'r') as f:
                token = f.read()
            result = _authenticate_with_token(token, 'cached_file', {'token_file': token_file})
            if result:
                return result
        except Exception as e:
            _log_vault_auth_method('cached_file', False, {'reason': str(e), 'token_file': token_file})
    
    # Fall back to environment token
    return _authenticate_with_token(os.getenv('VAULT_TOKEN'), 'environment')


def _log_vault_auth_method(method: str, success: bool, details: dict = None):
    """Log Vault authentication method for debugging.
    
    Args:
        method: The authentication method used ('cached_file', 'environment', 'approle', 'kubernetes')
        success: Whether authentication was successful
        details: Additional details to log
    """
    log_data = {
        "event": "vault_auth",
        "method": method,
        "success": success,
    }
    if details:
        log_data.update(details)
    
    log_message = f"VAULT_AUTH: {json.dumps(log_data)}"
    if success:
        logger.info(log_message)
    else:
        logger.warning(log_message)


def authenticate_vault_client(vault_addr: str, auth_mount_point: str, role_id: str=None, secret_id: str=None):
    """Dynamically choose the authentication method based on available credentials.
    
    Priority:
    1. VAULT_TOKEN_FILE - Read token from file (cached by worker)
    2. VAULT_TOKEN - Direct token from environment
    3. AppRole authentication (if role_id and secret_id provided)
    4. Kubernetes authentication (fallback)
    
    Note: Vault tokens are naturally cached by the hvac library and shared filesystem
    configuration, reducing the need for explicit credential caching.
    """
    # First, try cached token authentication (from file or environment)
    cached_client = _try_cached_token_login(vault_addr)
    if cached_client:
        return cached_client
    
    # Fall back to traditional authentication methods
    if role_id and secret_id:
        logger.debug(f"Authenticating to Vault using AppRole method")
        try:
            client = _approle_vault_login(vault_addr, role_id, secret_id, auth_mount_point=auth_mount_point)
            _log_vault_auth_method('approle', True)
            return client
        except Exception as e:
            _log_vault_auth_method('approle', False, {'reason': str(e)})
            raise
    else:
        logger.debug(f"Authenticating to Vault using Kubernetes auth method")
        try:
            client = _kubernetes_vault_login(role=WORKSPACE_NAME, vault_url=vault_addr, auth_mount_point=auth_mount_point)
            _log_vault_auth_method('kubernetes', True)
            return client
        except Exception as e:
            _log_vault_auth_method('kubernetes', False, {'reason': str(e)})
            raise

def _get_k8s_pod_namespace():
    """Return the namespace this pod is running in."""
    ns_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
    try:
        with open(ns_path, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Cannot determine Kubernetes namespace: {ns_path} not found. "
            "Is this running inside a Kubernetes pod?"
        )


def _k8s_api_get(resource_path: str, namespace: str):
    """Make an authenticated GET to the in-cluster Kubernetes API.

    Args:
        resource_path: e.g. ``secrets/my-secret`` or ``configmaps/my-cm``
        namespace: Kubernetes namespace.

    Returns:
        Parsed JSON response body.
    """
    with open(KUBERNETES_SERVICE_ACCOUNT_TOKEN_PATH, "r") as f:
        sa_token = f.read().strip()

    k8s_host = os.getenv("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    k8s_port = os.getenv("KUBERNETES_SERVICE_PORT", "443")
    url = f"https://{k8s_host}:{k8s_port}/api/v1/namespaces/{namespace}/{resource_path}"

    ca_cert = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    verify = ca_cert if os.path.exists(ca_cert) else False

    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {sa_token}"},
        verify=verify,
        timeout=10,
    )
    if resp.status_code != 200:
        raise SecretNotFoundError(
            f"Kubernetes API request failed for '{resource_path}' in namespace "
            f"'{namespace}': HTTP {resp.status_code} - {resp.text}"
        )
    return resp.json()


def _read_k8s_resource(kind: str, name: str, data_key: str, namespace: str = None):
    """Read a data key from a Kubernetes Secret or ConfigMap.

    Args:
        kind: ``"secret"`` or ``"configmap"``.
        name: Resource name.
        data_key: The data key to read.
        namespace: Kubernetes namespace (defaults to the pod's own namespace).

    Returns:
        The value as a string (base64-decoded for Secrets, raw for ConfigMaps).
    """
    import base64

    if namespace is None:
        namespace = _get_k8s_pod_namespace()

    if kind == "secret":
        body = _k8s_api_get(f"secrets/{name}", namespace)
        data = body.get("data", {})
        if data_key not in data:
            raise SecretNotFoundError(
                f"Key '{data_key}' not found in Kubernetes secret '{name}'. "
                f"Available keys: {list(data.keys())}"
            )
        return base64.b64decode(data[data_key]).decode("utf-8")

    elif kind == "configmap":
        body = _k8s_api_get(f"configmaps/{name}", namespace)
        data = body.get("data", {})
        if data_key not in data:
            raise SecretNotFoundError(
                f"Key '{data_key}' not found in Kubernetes configmap '{name}'. "
                f"Available keys: {list(data.keys())}"
            )
        return data[data_key]

    else:
        raise ValueError(f"Unsupported Kubernetes resource kind: '{kind}'. Expected 'secret' or 'configmap'.")


def _read_k8s_secret(secret_name: str, secret_key: str, namespace: str = None):
    """Convenience wrapper — reads from a Kubernetes Secret."""
    return _read_k8s_resource("secret", secret_name, secret_key, namespace)


def _get_k8s_cache_dir():
    """Return the shared cache directory for K8s secret/configmap data."""
    tmpdir_base = os.environ.get("TMPDIR", "/tmp/runwhen")
    cache_dir = os.path.join(tmpdir_base, "shared_config", ".k8s_secrets")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _k8s_cache_key(namespace: str, kind: str, name: str, data_key: str) -> str:
    """Build a filesystem-safe cache key."""
    safe = lambda s: s.replace("/", "_").replace(":", "_")
    return f"{safe(namespace)}_{safe(kind)}_{safe(name)}_{safe(data_key)}"


def _read_k8s_resource_cached(kind: str, name: str, data_key: str, namespace: str = None):
    """Read a K8s Secret/ConfigMap value with filesystem caching.

    Returns:
        Tuple of (value: str, from_cache: bool).
    """
    if namespace is None:
        namespace = _get_k8s_pod_namespace()

    cache_dir = _get_k8s_cache_dir()
    key = _k8s_cache_key(namespace, kind, name, data_key)
    cache_file = os.path.join(cache_dir, f"{key}.cache")

    if os.path.exists(cache_file):
        try:
            cache_age = time.time() - os.path.getmtime(cache_file)
            if cache_age < K8S_SECRET_CACHE_TTL:
                with open(cache_file, "r") as f:
                    return f.read(), True
            else:
                os.remove(cache_file)
        except Exception:
            pass

    value = _read_k8s_resource(kind, name, data_key, namespace)

    try:
        with open(cache_file, "w") as f:
            f.write(value)
    except Exception as e:
        logger.warning(f"K8S_CACHE: Failed to write cache for {kind}/{name}:{data_key}: {e}")

    return value, False


def _parse_k8s_resource_path(remaining_key: str):
    """Parse a k8s:file or k8s:env resource path into components.

    Accepted formats::

        secret/<name>:<data-key>
        configmap/<name>:<data-key>
        <namespace>/secret/<name>:<data-key>
        <namespace>/configmap/<name>:<data-key>

    Returns:
        Tuple of (kind, name, data_key, namespace_or_None).
    """
    if ":" not in remaining_key:
        raise ValueError(
            f"Invalid k8s resource key format '{remaining_key}'. "
            "Expected '<kind>/<name>:<key>' or '<namespace>/<kind>/<name>:<key>'"
        )

    resource_path, data_key = remaining_key.rsplit(":", 1)
    parts = resource_path.split("/")

    if len(parts) == 2 and parts[0] in ("secret", "configmap"):
        return parts[0], parts[1], data_key, None
    elif len(parts) == 3 and parts[1] in ("secret", "configmap"):
        return parts[1], parts[2], data_key, parts[0]
    else:
        raise ValueError(
            f"Invalid k8s resource path '{resource_path}'. "
            "Expected 'secret/<name>', 'configmap/<name>', "
            "'<namespace>/secret/<name>', or '<namespace>/configmap/<name>'"
        )


def _handle_k8s_kubeconfig(secret_data: str, key: str, log_fn):
    """If the key looks like a kubeconfig, write to the execution-specific
    KUBECONFIG path and set the Robot Framework suite variable.

    Returns True if kubeconfig handling was performed.
    """
    if "kubeconfig" not in key.lower():
        return False

    kubeconfig_path = os.environ.get("KUBECONFIG", "")
    if not kubeconfig_path:
        return False

    from robot.libraries.BuiltIn import BuiltIn

    kubeconfig_dir = os.path.dirname(kubeconfig_path)
    if kubeconfig_dir:
        os.makedirs(kubeconfig_dir, exist_ok=True)
    with open(kubeconfig_path, "w") as f:
        f.write(secret_data)

    BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
    log_fn(
        f"K8S_KUBECONFIG: Wrote kubeconfig to execution-specific path {kubeconfig_path}",
        "DEBUG",
    )
    return True


def read_secret(key: str, _recursion_stack=None):
    """Reads a secret. Note that in order to read, this call must be made from a container that is
    running in a workspace (namespace) in a location. (See design notes above.)

    This requires the RW_VAULT_URL, RW_WORKSPACE and RW_LOCATION env vars to be set.

    key (str): Secret to read
    _recursion_stack (set): Internal parameter to track recursive calls and prevent circular dependencies
    """
    from robot.libraries.BuiltIn import BuiltIn

    logger = BuiltIn().log
    
    # Initialize recursion stack for the top-level call
    if _recursion_stack is None:
        _recursion_stack = set()
    
    # Check for circular dependency
    if key in _recursion_stack:
        raise ValueError(f"Circular dependency detected in secret configuration: {' -> '.join(list(_recursion_stack) + [key])}")
    
    # Add current key to recursion stack
    _recursion_stack.add(key)

    # Load the secrets configuration from the environment variable
    secrets_provided_env = os.getenv('RW_SECRETS_KEYS')
    if not secrets_provided_env:
        raise ValueError("Environment variable RW_SECRETS_KEYS is not set.")
    try:
        secrets_provided = json.loads(secrets_provided_env)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse RW_SECRETS_KEYS: {e}")

    provider = None
    remaining_key = None
    # Check the cache first
    cached_val = _cache.get(key)
    if cached_val:
        logger(f"SECRET_CACHE: Cache HIT for secret '{key}'", "DEBUG")
        _recursion_stack.discard(key)
        return cached_val

    logger(f"SECRET_CACHE: Cache MISS for secret '{key}', fetching from provider", "DEBUG")

    # Determine the provider from the key
    if SECRET_PROVIDER_SYMBOL in key:
        provider, remaining_key = key.split(SECRET_PROVIDER_SYMBOL, 1)
        logger(f"Extracted provider: {provider}, remaining key: {remaining_key}", "DEBUG")
    else:
        provider = "runwhen-vault"
        remaining_key = key
        logger(f"No explicit provider in key, using default: {provider}", "DEBUG")

    # Check for Azure Identity specifically
    if provider == "azure:identity":
        _current_secret_provider = SecretProvider.AZURE_IDENTITY
        logger("Provider matched as Azure Identity.", "DEBUG")
    elif provider == "azure:sp":
        _current_secret_provider = SecretProvider.AZURE_SP
        logger("Provider matched as Azure Service Principal.", "DEBUG")
    # AWS providers
    elif provider == "aws:irsa":
        _current_secret_provider = SecretProvider.AWS_IRSA
        logger("Provider matched as AWS IRSA.", "DEBUG")
    elif provider == "aws:access_key":
        _current_secret_provider = SecretProvider.AWS_ACCESS_KEY
        logger("Provider matched as AWS Access Key.", "DEBUG")
    elif provider == "aws:assume_role":
        _current_secret_provider = SecretProvider.AWS_ASSUME_ROLE
        logger("Provider matched as AWS Assume Role.", "DEBUG")
    elif provider == "aws:default":
        _current_secret_provider = SecretProvider.AWS_DEFAULT
        logger("Provider matched as AWS Default Chain.", "DEBUG")
    elif provider == "aws:workload_identity":
        _current_secret_provider = SecretProvider.AWS_WORKLOAD_IDENTITY
        logger("Provider matched as AWS Workload Identity (IRSA for EKS).", "DEBUG")
    elif provider == "aws:cli":
        _current_secret_provider = SecretProvider.AWS_CLI
        logger("Provider matched as AWS CLI (explicit credentials for EKS).", "DEBUG")
    elif provider == "k8s:file":
        _current_secret_provider = SecretProvider.K8S_FILE
        logger("Provider matched as Kubernetes resource (file).", "DEBUG")
    elif provider == "k8s:env":
        _current_secret_provider = SecretProvider.K8S_ENV
        logger("Provider matched as Kubernetes resource (env).", "DEBUG")
    elif provider == "file":
        _current_secret_provider = SecretProvider.FILE
    elif provider == "runwhen-vault":
        _current_secret_provider = SecretProvider.RUNWHEN_VAULT
        logger("Provider matched as RunWhen Vault.", "DEBUG")
    else:
        _current_secret_provider = SecretProvider.CUSTOM
        logger(f"Provider did not match any known types, defaulting to Custom provider.", "DEBUG")

    logger(f"Determined provider as: {_current_secret_provider}", "DEBUG")

    # Fetch the secret based on the provider
    secret_data = None
    try:
        if _current_secret_provider == SecretProvider.ENV:
            logger(f"Fetching secret from environment variable: {remaining_key}", "DEBUG")
            secret_data = os.getenv(remaining_key)
            if not secret_data:
                raise SecretNotFoundError(f"Secret at key '{remaining_key}' not found in environment variables")

        elif _current_secret_provider == SecretProvider.FILE:
            logger(f"Fetching secret from file: {remaining_key}", "DEBUG")
            with open(remaining_key, "r") as f:
                secret_data = f.read().strip()

        elif _current_secret_provider in (SecretProvider.K8S_FILE, SecretProvider.K8S_ENV):
            provider_label = "k8s:file" if _current_secret_provider == SecretProvider.K8S_FILE else "k8s:env"
            logger(f"Fetching secret via {provider_label} from Kubernetes resource: {remaining_key}", "DEBUG")

            kind, res_name, data_key, k8s_namespace = _parse_k8s_resource_path(remaining_key)

            logger(
                f"Reading Kubernetes {kind} '{res_name}' key '{data_key}'"
                + (f" in namespace '{k8s_namespace}'" if k8s_namespace else " in pod namespace"),
                "DEBUG",
            )

            secret_data, from_cache = _read_k8s_resource_cached(
                kind, res_name, data_key, namespace=k8s_namespace,
            )

            cache_status = "HIT" if from_cache else "MISS"
            logger(f"K8S_CACHE: Cache {cache_status} for {kind}/{res_name}:{data_key}", "DEBUG")

            _handle_k8s_kubeconfig(secret_data, key, logger)

        elif _current_secret_provider == SecretProvider.RUNWHEN_VAULT:
            logger(f"Fetching secret from Vault for key: {remaining_key}", "DEBUG")
            vault_lookup = "env"
            client = authenticate_vault_client(
                vault_addr=VAULT_ADDR,
                auth_mount_point=LOCATION_VAULT_AUTH_MOUNT_POINT,
                role_id=VAULT_APPROLE_ROLE_ID,
                secret_id=VAULT_APPROLE_SECRET_ID,
            )
            url = f"{VAULT_ADDR}/v1/workspaces/data/{WORKSPACE_NAME}/{remaining_key}"
            headers = {"X-Vault-Token": client.token}
            rsp = requests.get(url=url, headers=headers, verify=REQUEST_VERIFY)
            if rsp.status_code != 200:
                raise SecretNotFoundError(f"Secret at key '{remaining_key}' not found: {rsp.text} {rsp.status_code} with provider {_current_secret_provider}")
            secret_data = rsp.json()["data"]["data"][vault_lookup]

        elif _current_secret_provider == SecretProvider.CUSTOM:
            SECRET_PROVIDER_TYPE = os.getenv(f"SECRET_PROVIDER_{provider}_TYPE") #TODO: handle other vault types
            key,field = key.split(":")
            if SECRET_PROVIDER_TYPE == "vault":
                SECRET_PROVIDER_VAULT_ADDR = os.getenv(f"SECRET_PROVIDER_{provider}_VAULT_ADDR")
                SECRET_PROVIDER_VAULT_AUTH_MOUNT_PATH = os.getenv(f"SECRET_PROVIDER_{provider}_VAULT_AUTH_MOUNT_PATH")
                SECRET_PROVIDER_VAULT_APPROLE_ROLE_ID = os.getenv(f"SECRET_PROVIDER_{provider}_VAULT_APPROLE_ROLE_ID")
                SECRET_PROVIDER_VAULT_APPROLE_SECRET_ID = os.getenv(f"SECRET_PROVIDER_{provider}_VAULT_APPROLE_SECRET_ID")
                if (
                    not SECRET_PROVIDER_TYPE
                    or not SECRET_PROVIDER_VAULT_ADDR
                    or not SECRET_PROVIDER_VAULT_AUTH_MOUNT_PATH
                    or not SECRET_PROVIDER_VAULT_APPROLE_ROLE_ID
                    or not SECRET_PROVIDER_VAULT_APPROLE_SECRET_ID
                ):
                    raise AssertionError(f"Custom vault provider used but missing necessary environment variables: {SECRET_PROVIDER_TYPE} {SECRET_PROVIDER_VAULT_ADDR} {SECRET_PROVIDER_VAULT_AUTH_MOUNT_PATH} {SECRET_PROVIDER_VAULT_APPROLE_ROLE_ID} {SECRET_PROVIDER_VAULT_APPROLE_SECRET_ID}")
                
                logger.debug(f"Authenticating to custom vault provider {provider}")
                client = authenticate_vault_client(
                    vault_addr=SECRET_PROVIDER_VAULT_ADDR,
                    auth_mount_point=SECRET_PROVIDER_VAULT_AUTH_MOUNT_PATH,
                    role_id=SECRET_PROVIDER_VAULT_APPROLE_ROLE_ID,
                    secret_id=SECRET_PROVIDER_VAULT_APPROLE_SECRET_ID,
                )
                
                url = f"{SECRET_PROVIDER_VAULT_ADDR}/v1{key}" if key.startswith("/") else f"{SECRET_PROVIDER_VAULT_ADDR}/v1/{key}"
                headers = {"X-Vault-Token": client.token}
                rsp = requests.get(url=url, headers=headers, verify=REQUEST_VERIFY)
                if rsp.status_code != 200:
                    raise SecretNotFoundError(f"Secret at key {key} not found: {rsp.text} {rsp.status_code} with provider {_current_secret_provider}")
                secret_data = rsp.json()["data"]["data"][field]

        elif _current_secret_provider == SecretProvider.AZURE_IDENTITY:
            if "kubeconfig" in key:
                logger(f"Handling Azure Identity provider for key: {remaining_key}", "DEBUG")
                try:
                    # Split correctly for resource group and cluster name
                    resource_info = remaining_key.split(":", 1)[-1]  # Remove 'kubeconfig:' prefix
                    resource_group, cluster_name = resource_info.split("/", 1)
                    logger(f"Parsed resource group: {resource_group}, cluster name: {cluster_name}", "DEBUG")
                except ValueError:
                    raise ValueError(f"Expected format 'azure:identity@kubeconfig:resource_group/cluster_name', got {remaining_key}")

                # Check for cached kubeconfig content in filesystem first
                azure_config_dir = os.environ.get('AZURE_CONFIG_DIR', '')
                kubeconfig_cache_file = None
                cached_kubeconfig = None
                
                if azure_config_dir:
                    # Create a safe filename for the cache (Identity doesn't need tenant/client isolation)
                    cache_filename = f"kubeconfig_identity_{resource_group.replace('/', '_')}_{cluster_name.replace('/', '_')}.yaml"
                    kubeconfig_cache_file = os.path.join(azure_config_dir, cache_filename)
                    
                    if os.path.exists(kubeconfig_cache_file):
                        try:
                            # Check if cached file is recent (within 1 hour)
                            import time
                            cache_age = time.time() - os.path.getmtime(kubeconfig_cache_file)
                            if cache_age < 3600:  # 1 hour TTL
                                logger(f"KUBECONFIG_CACHE: Cache HIT for Identity kubeconfig {resource_group}/{cluster_name}, using filesystem cache", "DEBUG")
                                
                                with open(kubeconfig_cache_file, 'r') as f:
                                    cached_kubeconfig = f.read()
                            else:
                                logger(f"KUBECONFIG_CACHE: Cache EXPIRED for Identity kubeconfig {resource_group}/{cluster_name}, regenerating", "DEBUG")
                                os.remove(kubeconfig_cache_file)  # Remove expired cache
                        except Exception as e:
                            logger(f"KUBECONFIG_CACHE: Error reading cache file {kubeconfig_cache_file}: {e}", "DEBUG")
                
                if cached_kubeconfig:
                    secret_data = cached_kubeconfig
                    
                    # Still need to write to execution-specific location and set KUBECONFIG
                    kubeconfig_path = os.environ.get("KUBECONFIG", "")
                    if kubeconfig_path:
                        kubeconfig_dir = os.path.dirname(kubeconfig_path)
                        if kubeconfig_dir:
                            os.makedirs(kubeconfig_dir, exist_ok=True)
                        with open(kubeconfig_path, "w") as f:
                            f.write(secret_data)
                        logger(f"KUBECONFIG_CACHE: Restored cached Identity kubeconfig to {kubeconfig_path}", "DEBUG")
                        BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
                else:
                    logger(f"KUBECONFIG_CACHE: Cache MISS for Identity kubeconfig {resource_group}/{cluster_name}, generating new", "DEBUG")
                    
                    # Generate the kubeconfig using the existing function
                    azure_utils.generate_kubeconfig_for_aks(resource_group, cluster_name)

                    # Set Kubeconfig Path
                    kubeconfig_path = os.environ.get("KUBECONFIG", "")
                    BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
                    
                    try:
                        with open(kubeconfig_path, "r") as f:
                            secret_data = f.read()
                        
                        # Cache the kubeconfig content to filesystem for future use
                        if azure_config_dir and kubeconfig_cache_file:
                            try:
                                with open(kubeconfig_cache_file, 'w') as f:
                                    f.write(secret_data)
                                logger(f"KUBECONFIG_CACHE: Cached Identity kubeconfig content to filesystem for {resource_group}/{cluster_name}", "DEBUG")
                            except Exception as e:
                                logger(f"KUBECONFIG_CACHE: Failed to cache kubeconfig to filesystem: {e}", "DEBUG")
                        
                    except FileNotFoundError:
                        raise SecretNotFoundError(f"Kubeconfig file not found after generation at path {kubeconfig_path}")
            elif "cli" in key: 
                logger(f"Handling Azure Identity provider for key: {remaining_key}", "DEBUG")
                # Perform az login (which stores credentials in ~/.azure/accessTokens.json)
                # The caching is now handled at the credential level in azure_utils.az_login()
                azure_utils.az_login()
                
                # Return a simple success indicator
                secret_data = f"Azure CLI authenticated with Managed Identity at {os.environ.get('AZURE_CONFIG_DIR', 'unknown')}"
            else:
                raise SecretNotFoundError(f"Key does not refer to a kubeconfig or cli: {remaining_key}")

        elif _current_secret_provider == SecretProvider.AZURE_SP:
            # Prepare to fetch all necessary pieces of information from the secrets
            required_keys = ["az_clientId", "az_tenantId", "az_clientSecret"]
            credentials = {}

            for required_key in required_keys:
                print(f"Required key: {required_key}")
                secret_key = secrets_provided.get(required_key)
                if not secret_key:
                    raise SecretNotFoundError(f"Required secret '{required_key}' not found in provided configuration.")
                credentials[required_key] = read_secret(secret_key, _recursion_stack)

            tenant_id = credentials.get("az_tenantId")
            client_id = credentials.get("az_clientId")
            client_secret = credentials.get("az_clientSecret")

            if not tenant_id or not client_id or not client_secret:
                raise ValueError(f"Required fields (tenantId, clientId, clientSecret) missing in associated secrets.")

            if "kubeconfig" in key:
                # Extract resource group and cluster name from the remaining key
                resource_info = remaining_key.split(":", 1)[-1]
                resource_group, cluster_name = resource_info.split("/", 1)

                # Check for cached kubeconfig content in filesystem first
                azure_config_dir = os.environ.get('AZURE_CONFIG_DIR', '')
                kubeconfig_cache_file = None
                cached_kubeconfig = None
                
                if azure_config_dir:
                    # Create a safe filename for the cache (include tenant/client for SP isolation)
                    cache_filename = f"kubeconfig_sp_{resource_group.replace('/', '_')}_{cluster_name.replace('/', '_')}_{tenant_id[:8]}_{client_id[:8]}.yaml"
                    kubeconfig_cache_file = os.path.join(azure_config_dir, cache_filename)
                    
                    if os.path.exists(kubeconfig_cache_file):
                        try:
                            # Check if cached file is recent (within 1 hour)
                            import time
                            cache_age = time.time() - os.path.getmtime(kubeconfig_cache_file)
                            if cache_age < 3600:  # 1 hour TTL
                                logger(f"KUBECONFIG_CACHE: Cache HIT for SP kubeconfig {resource_group}/{cluster_name}, using filesystem cache", "DEBUG")
                                
                                with open(kubeconfig_cache_file, 'r') as f:
                                    cached_kubeconfig = f.read()
                            else:
                                logger(f"KUBECONFIG_CACHE: Cache EXPIRED for SP kubeconfig {resource_group}/{cluster_name}, regenerating", "DEBUG")
                                os.remove(kubeconfig_cache_file)  # Remove expired cache
                        except Exception as e:
                            logger(f"KUBECONFIG_CACHE: Error reading cache file {kubeconfig_cache_file}: {e}", "DEBUG")
                
                if cached_kubeconfig:
                    secret_data = cached_kubeconfig
                    
                    # Still need to write to execution-specific location and set KUBECONFIG
                    kubeconfig_path = os.environ.get("KUBECONFIG", "")
                    if kubeconfig_path:
                        kubeconfig_dir = os.path.dirname(kubeconfig_path)
                        if kubeconfig_dir:
                            os.makedirs(kubeconfig_dir, exist_ok=True)
                        with open(kubeconfig_path, "w") as f:
                            f.write(secret_data)
                        logger(f"KUBECONFIG_CACHE: Restored cached SP kubeconfig to {kubeconfig_path}", "DEBUG")
                        BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
                else:
                    logger(f"KUBECONFIG_CACHE: Cache MISS for SP kubeconfig {resource_group}/{cluster_name}, generating new", "DEBUG")
                    
                    azure_utils.generate_kubeconfig_for_aks(
                        resource_group=resource_group, 
                        cluster_name=cluster_name, 
                        tenant_id=tenant_id, 
                        client_id=client_id, 
                        client_secret=client_secret
                    )

                    # Set Kubeconfig Path
                    kubeconfig_path = os.environ.get("KUBECONFIG", "")
                    BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
                    
                    with open(kubeconfig_path, "r") as f:
                        secret_data = f.read()
                    
                    # Cache the kubeconfig content to filesystem for future use
                    if azure_config_dir and kubeconfig_cache_file:
                        try:
                            with open(kubeconfig_cache_file, 'w') as f:
                                f.write(secret_data)
                            logger(f"KUBECONFIG_CACHE: Cached SP kubeconfig content to filesystem for {resource_group}/{cluster_name}", "DEBUG")
                        except Exception as e:
                            logger(f"KUBECONFIG_CACHE: Failed to cache kubeconfig to filesystem: {e}", "DEBUG")
            elif "cli" in key: 
                logger(f"Handling Azure SP provider for key: {remaining_key}", "DEBUG")
                # Perform az login (which stores credentials in ~/.azure/accessTokens.json)
                # The caching is now handled at the credential level in azure_utils.az_login()
                azure_utils.az_login(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
                
                # Return a simple success indicator  
                secret_data = f"Azure CLI authenticated for tenant {tenant_id[:8]}... at {os.environ.get('AZURE_CONFIG_DIR', 'unknown')}"
            else:
                raise SecretNotFoundError(f"Key does not refer to a kubeconfig: {remaining_key}")

        elif _current_secret_provider == SecretProvider.GCP_SA:
            # Prepare to fetch all necessary pieces of information from the secrets
            required_keys = ["gcp_projectId", "gcp_serviceAccountKey"]
            credentials = {}

            for required_key in required_keys:
                print(f"Required key: {required_key}")
                secret_key = secrets_provided.get(required_key)
                if not secret_key:
                    raise SecretNotFoundError(f"Required secret '{required_key}' not found in provided configuration.")
                credentials[required_key] = read_secret(secret_key, _recursion_stack)

            project_id = credentials.get("gcp_projectId")
            service_account_key = credentials.get("gcp_serviceAccountKey")

            if not project_id or not service_account_key:
                raise ValueError(f"Required fields (projectId, serviceAccountKey) missing in associated secrets.")

            if "kubeconfig" in key:
                # Extract cluster info from the remaining key
                cluster_info = remaining_key.split(":", 1)[-1]
                cluster_parts = cluster_info.split("/")
                if len(cluster_parts) != 2:
                    raise ValueError(f"GKE cluster info should be in format 'cluster_name/zone_or_region', got: {cluster_info}")
                
                cluster_name, zone_or_region = cluster_parts

                # Check for cached kubeconfig content in filesystem first
                gcp_config_dir = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_DIR', '')
                kubeconfig_cache_file = None
                cached_kubeconfig = None
                
                if gcp_config_dir:
                    # Create a safe filename for the cache (include project for SA isolation)
                    cache_filename = f"kubeconfig_sa_{cluster_name.replace('/', '_')}_{zone_or_region.replace('/', '_')}_{project_id}_{hashlib.sha256(service_account_key.encode()).hexdigest()[:8]}.yaml"
                    kubeconfig_cache_file = os.path.join(gcp_config_dir, cache_filename)
                    
                    if os.path.exists(kubeconfig_cache_file):
                        try:
                            # Check if cached file is recent (within 1 hour)
                            import time
                            cache_age = time.time() - os.path.getmtime(kubeconfig_cache_file)
                            if cache_age < 3600:  # 1 hour TTL
                                logger(f"KUBECONFIG_CACHE: Cache HIT for GCP SA kubeconfig {cluster_name}/{zone_or_region}, using filesystem cache", "DEBUG")
                                
                                with open(kubeconfig_cache_file, 'r') as f:
                                    cached_kubeconfig = f.read()
                            else:
                                logger(f"KUBECONFIG_CACHE: Cache EXPIRED for GCP SA kubeconfig {cluster_name}/{zone_or_region}, regenerating", "DEBUG")
                                os.remove(kubeconfig_cache_file)  # Remove expired cache
                        except Exception as e:
                            logger(f"KUBECONFIG_CACHE: Error reading cache file {kubeconfig_cache_file}: {e}", "DEBUG")
                
                if cached_kubeconfig:
                    secret_data = cached_kubeconfig
                    
                    # Still need to write to execution-specific location and set KUBECONFIG
                    kubeconfig_path = os.environ.get("KUBECONFIG", "")
                    if kubeconfig_path:
                        kubeconfig_dir = os.path.dirname(kubeconfig_path)
                        if kubeconfig_dir:
                            os.makedirs(kubeconfig_dir, exist_ok=True)
                        with open(kubeconfig_path, "w") as f:
                            f.write(secret_data)
                        logger(f"KUBECONFIG_CACHE: Restored cached GCP SA kubeconfig to {kubeconfig_path}", "DEBUG")
                        BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
                else:
                    logger(f"KUBECONFIG_CACHE: Cache MISS for GCP SA kubeconfig {cluster_name}/{zone_or_region}, generating new", "DEBUG")
                    
                    gcp_utils.generate_kubeconfig_for_gke(
                        cluster_name=cluster_name, 
                        zone_or_region=zone_or_region, 
                        project_id=project_id, 
                        service_account_key=service_account_key
                    )

                    # Set Kubeconfig Path
                    kubeconfig_path = os.environ.get("KUBECONFIG", "")
                    BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
                    
                    with open(kubeconfig_path, "r") as f:
                        secret_data = f.read()
                    
                    # Cache the kubeconfig content to filesystem for future use
                    if gcp_config_dir and kubeconfig_cache_file:
                        try:
                            with open(kubeconfig_cache_file, 'w') as f:
                                f.write(secret_data)
                            logger(f"KUBECONFIG_CACHE: Cached GCP SA kubeconfig content to filesystem for {cluster_name}/{zone_or_region}", "DEBUG")
                        except Exception as e:
                            logger(f"KUBECONFIG_CACHE: Failed to cache kubeconfig to filesystem: {e}", "DEBUG")
            elif "cli" in key: 
                logger(f"Handling GCP Service Account provider for key: {remaining_key}", "DEBUG")
                # Perform gcloud auth (which stores credentials in ~/.config/gcloud)
                # The caching is now handled at the credential level in gcp_utils.gcloud_login()
                gcp_utils.gcloud_login(project_id=project_id, service_account_key=service_account_key)
                
                # Return a simple success indicator  
                secret_data = f"GCP CLI authenticated for project {project_id} at {os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_DIR', 'unknown')}"
            else:
                raise SecretNotFoundError(f"Key does not refer to a kubeconfig or cli: {remaining_key}")

        elif _current_secret_provider == SecretProvider.GCP_ADC:
            # Application Default Credentials
            project_id = None
            
            # Try to get project_id from secrets if provided
            if "gcp_projectId" in secrets_provided:
                project_id_key = secrets_provided.get("gcp_projectId")
                if project_id_key:
                    project_id = read_secret(project_id_key, _recursion_stack)

            if "kubeconfig" in key:
                # Extract cluster info from the remaining key
                cluster_info = remaining_key.split(":", 1)[-1]
                cluster_parts = cluster_info.split("/")
                if len(cluster_parts) != 2:
                    raise ValueError(f"GKE cluster info should be in format 'cluster_name/zone_or_region', got: {cluster_info}")
                
                cluster_name, zone_or_region = cluster_parts

                # Check for cached kubeconfig content in filesystem first
                gcp_config_dir = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_DIR', '')
                kubeconfig_cache_file = None
                cached_kubeconfig = None
                
                if gcp_config_dir:
                    # Create a safe filename for the cache (ADC doesn't have service account key)
                    cache_filename = f"kubeconfig_adc_{cluster_name.replace('/', '_')}_{zone_or_region.replace('/', '_')}_{project_id or 'default'}.yaml"
                    kubeconfig_cache_file = os.path.join(gcp_config_dir, cache_filename)
                    
                    if os.path.exists(kubeconfig_cache_file):
                        try:
                            # Check if cached file is recent (within 1 hour)
                            import time
                            cache_age = time.time() - os.path.getmtime(kubeconfig_cache_file)
                            if cache_age < 3600:  # 1 hour TTL
                                logger(f"KUBECONFIG_CACHE: Cache HIT for GCP ADC kubeconfig {cluster_name}/{zone_or_region}, using filesystem cache", "DEBUG")
                                
                                with open(kubeconfig_cache_file, 'r') as f:
                                    cached_kubeconfig = f.read()
                            else:
                                logger(f"KUBECONFIG_CACHE: Cache EXPIRED for GCP ADC kubeconfig {cluster_name}/{zone_or_region}, regenerating", "DEBUG")
                                os.remove(kubeconfig_cache_file)  # Remove expired cache
                        except Exception as e:
                            logger(f"KUBECONFIG_CACHE: Error reading cache file {kubeconfig_cache_file}: {e}", "DEBUG")
                
                if cached_kubeconfig:
                    secret_data = cached_kubeconfig
                    
                    # Still need to write to execution-specific location and set KUBECONFIG
                    kubeconfig_path = os.environ.get("KUBECONFIG", "")
                    if kubeconfig_path:
                        kubeconfig_dir = os.path.dirname(kubeconfig_path)
                        if kubeconfig_dir:
                            os.makedirs(kubeconfig_dir, exist_ok=True)
                        with open(kubeconfig_path, "w") as f:
                            f.write(secret_data)
                        logger(f"KUBECONFIG_CACHE: Restored cached GCP ADC kubeconfig to {kubeconfig_path}", "DEBUG")
                        BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
                else:
                    logger(f"KUBECONFIG_CACHE: Cache MISS for GCP ADC kubeconfig {cluster_name}/{zone_or_region}, generating new", "DEBUG")
                    
                    gcp_utils.generate_kubeconfig_for_gke(
                        cluster_name=cluster_name, 
                        zone_or_region=zone_or_region, 
                        project_id=project_id
                    )

                    # Set Kubeconfig Path
                    kubeconfig_path = os.environ.get("KUBECONFIG", "")
                    BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
                    
                    with open(kubeconfig_path, "r") as f:
                        secret_data = f.read()
                        
                    # Cache the kubeconfig content to filesystem for future use
                    if gcp_config_dir and kubeconfig_cache_file:
                        try:
                            with open(kubeconfig_cache_file, 'w') as f:
                                f.write(secret_data)
                            logger(f"KUBECONFIG_CACHE: Cached GCP ADC kubeconfig content to filesystem for {cluster_name}/{zone_or_region}", "DEBUG")
                        except Exception as e:
                            logger(f"KUBECONFIG_CACHE: Failed to cache kubeconfig to filesystem: {e}", "DEBUG")
            elif "cli" in key: 
                logger(f"Handling GCP Application Default Credentials provider for key: {remaining_key}", "DEBUG")
                # Perform gcloud auth (which stores credentials in ~/.config/gcloud)
                # The caching is now handled at the credential level in gcp_utils.gcloud_login()
                gcp_utils.gcloud_login(project_id=project_id)
                
                # Return a simple success indicator
                secret_data = f"GCP CLI authenticated with Application Default Credentials at {os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_DIR', 'unknown')}"
            else:
                raise SecretNotFoundError(f"Key does not refer to a kubeconfig or cli: {remaining_key}")

        # ========================================
        # AWS IRSA (IAM Roles for Service Accounts)
        # Pattern: aws:irsa@cli or aws:irsa@kubeconfig (use aws:workload_identity for kubeconfig)
        # ========================================
        elif _current_secret_provider == SecretProvider.AWS_IRSA:
            if "cli" in key:
                logger(f"Handling AWS IRSA provider for key: {remaining_key}", "DEBUG")
                # Perform AWS authentication using IRSA
                aws_utils.aws_login_irsa()
                
                # Check if there's a role to assume (cross-account access)
                if "AWS_ROLE_ARN" in secrets_provided:
                    role_arn_key = secrets_provided.get("AWS_ROLE_ARN")
                    if role_arn_key:
                        role_arn = read_secret(role_arn_key, _recursion_stack) if "@" in role_arn_key else role_arn_key
                        logger(f"Assuming cross-account role: {role_arn}", "DEBUG")
                        aws_utils.aws_login_assume_role(role_arn)
                
                # Return a simple success indicator
                secret_data = f"AWS CLI authenticated with IRSA"
            else:
                raise SecretNotFoundError(f"Key does not refer to cli: {remaining_key}. For EKS kubeconfig, use aws:workload_identity@kubeconfig")

        # ========================================
        # AWS Access Key (Explicit credentials)
        # Pattern: aws:access_key@cli
        # ========================================
        elif _current_secret_provider == SecretProvider.AWS_ACCESS_KEY:
            # Fetch required AWS credentials from secrets
            required_keys = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
            credentials = {}

            for required_key in required_keys:
                logger(f"Looking for required key: {required_key}", "DEBUG")
                secret_key = secrets_provided.get(required_key)
                if not secret_key:
                    raise SecretNotFoundError(f"Required secret '{required_key}' not found in provided configuration.")
                credentials[required_key] = read_secret(secret_key, _recursion_stack)

            access_key_id = credentials.get("AWS_ACCESS_KEY_ID")
            secret_access_key = credentials.get("AWS_SECRET_ACCESS_KEY")
            
            # Optional session token
            session_token = None
            if "AWS_SESSION_TOKEN" in secrets_provided:
                session_token_key = secrets_provided.get("AWS_SESSION_TOKEN")
                if session_token_key:
                    session_token = read_secret(session_token_key, _recursion_stack)

            if not access_key_id or not secret_access_key:
                raise ValueError(f"Required fields (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY) missing in associated secrets.")

            if "cli" in key:
                logger(f"Handling AWS Access Key provider for key: {remaining_key}", "DEBUG")
                aws_utils.aws_login_access_key(access_key_id, secret_access_key, session_token)
                
                # Return a simple success indicator
                secret_data = f"AWS CLI authenticated with access key {access_key_id[:8]}..."
            else:
                raise SecretNotFoundError(f"Key does not refer to cli: {remaining_key}")

        # ========================================
        # AWS Assume Role
        # Pattern: aws:assume_role@cli
        # ========================================
        elif _current_secret_provider == SecretProvider.AWS_ASSUME_ROLE:
            # Get the role ARN - this is required
            role_arn = None
            if "AWS_ROLE_ARN" in secrets_provided:
                role_arn_key = secrets_provided.get("AWS_ROLE_ARN")
                if role_arn_key:
                    # Check if it's a direct value or a secret reference
                    role_arn = read_secret(role_arn_key, _recursion_stack) if "@" in role_arn_key else role_arn_key
            
            # Also check for aws_role_arn (lowercase variant)
            if not role_arn and "aws_role_arn" in secrets_provided:
                role_arn_key = secrets_provided.get("aws_role_arn")
                if role_arn_key:
                    role_arn = read_secret(role_arn_key, _recursion_stack) if "@" in role_arn_key else role_arn_key
            
            if not role_arn:
                raise SecretNotFoundError("AWS_ROLE_ARN or aws_role_arn is required for assume_role authentication")

            # Check for optional base credentials
            access_key_id = None
            secret_access_key = None
            session_token = None
            
            if "AWS_ACCESS_KEY_ID" in secrets_provided:
                access_key_id_key = secrets_provided.get("AWS_ACCESS_KEY_ID")
                if access_key_id_key:
                    access_key_id = read_secret(access_key_id_key, _recursion_stack)
            
            if "AWS_SECRET_ACCESS_KEY" in secrets_provided:
                secret_access_key_key = secrets_provided.get("AWS_SECRET_ACCESS_KEY")
                if secret_access_key_key:
                    secret_access_key = read_secret(secret_access_key_key, _recursion_stack)
            
            if "AWS_SESSION_TOKEN" in secrets_provided:
                session_token_key = secrets_provided.get("AWS_SESSION_TOKEN")
                if session_token_key:
                    session_token = read_secret(session_token_key, _recursion_stack)

            if "cli" in key:
                logger(f"Handling AWS Assume Role provider for key: {remaining_key}", "DEBUG")
                aws_utils.aws_login_assume_role(
                    role_arn=role_arn,
                    access_key_id=access_key_id,
                    secret_access_key=secret_access_key,
                    session_token=session_token
                )
                
                # Return a simple success indicator
                secret_data = f"AWS CLI authenticated by assuming role {role_arn}"
            else:
                raise SecretNotFoundError(f"Key does not refer to cli: {remaining_key}")

        # ========================================
        # AWS Default Chain
        # Pattern: aws:default@cli
        # ========================================
        elif _current_secret_provider == SecretProvider.AWS_DEFAULT:
            if "cli" in key:
                logger(f"Handling AWS Default Chain provider for key: {remaining_key}", "DEBUG")
                aws_utils.aws_login_default()
                
                # Return a simple success indicator
                secret_data = f"AWS CLI authenticated with default credential chain"
            else:
                raise SecretNotFoundError(f"Key does not refer to cli: {remaining_key}")

        # ========================================
        # AWS Workload Identity (IRSA for EKS kubeconfig)
        # Pattern: aws:workload_identity@kubeconfig:{region}/{cluster_name}
        # ========================================
        elif _current_secret_provider == SecretProvider.AWS_WORKLOAD_IDENTITY:
            if "kubeconfig" in key:
                logger(f"Handling AWS Workload Identity provider for key: {remaining_key}", "DEBUG")
                try:
                    # Split correctly for region and cluster name
                    # Format: kubeconfig:{region}/{cluster_name}
                    resource_info = remaining_key.split(":", 1)[-1]  # Remove 'kubeconfig:' prefix
                    region, cluster_name = resource_info.split("/", 1)
                    logger(f"Parsed region: {region}, cluster name: {cluster_name}", "DEBUG")
                except ValueError:
                    raise ValueError(f"Expected format 'aws:workload_identity@kubeconfig:region/cluster_name', got {remaining_key}")

                # Check if there's a role to assume for cluster access (needed for cache key isolation)
                role_arn = None
                if "AWS_ROLE_ARN" in secrets_provided:
                    role_arn_key = secrets_provided.get("AWS_ROLE_ARN")
                    if role_arn_key:
                        role_arn = read_secret(role_arn_key, _recursion_stack) if "@" in role_arn_key else role_arn_key

                # Check for cached kubeconfig content in filesystem first
                aws_config_dir = os.environ.get('AWS_CONFIG_DIR', os.path.expanduser('~/.aws'))
                kubeconfig_cache_file = None
                cached_kubeconfig = None
                
                if aws_config_dir:
                    os.makedirs(aws_config_dir, exist_ok=True)
                    # Create a safe filename for the cache, including role_arn for isolation
                    role_suffix = f"_{role_arn.split('/')[-1]}" if role_arn else ""
                    cache_filename = f"kubeconfig_irsa_{region.replace('/', '_')}_{cluster_name.replace('/', '_')}{role_suffix}.yaml"
                    kubeconfig_cache_file = os.path.join(aws_config_dir, cache_filename)
                    
                    if os.path.exists(kubeconfig_cache_file):
                        try:
                            # Check if cached file is recent (within 1 hour)
                            import time
                            cache_age = time.time() - os.path.getmtime(kubeconfig_cache_file)
                            if cache_age < 3600:  # 1 hour TTL
                                logger(f"KUBECONFIG_CACHE: Cache HIT for AWS IRSA kubeconfig {region}/{cluster_name}, using filesystem cache", "DEBUG")
                                
                                with open(kubeconfig_cache_file, 'r') as f:
                                    cached_kubeconfig = f.read()
                            else:
                                logger(f"KUBECONFIG_CACHE: Cache EXPIRED for AWS IRSA kubeconfig {region}/{cluster_name}, regenerating", "DEBUG")
                                os.remove(kubeconfig_cache_file)  # Remove expired cache
                        except Exception as e:
                            logger(f"KUBECONFIG_CACHE: Error reading cache file {kubeconfig_cache_file}: {e}", "DEBUG")
                
                if cached_kubeconfig:
                    secret_data = cached_kubeconfig
                    
                    # Still need to write to execution-specific location and set KUBECONFIG
                    kubeconfig_path = os.environ.get("KUBECONFIG", "")
                    if kubeconfig_path:
                        kubeconfig_dir = os.path.dirname(kubeconfig_path)
                        if kubeconfig_dir:
                            os.makedirs(kubeconfig_dir, exist_ok=True)
                        with open(kubeconfig_path, "w") as f:
                            f.write(secret_data)
                        logger(f"KUBECONFIG_CACHE: Restored cached AWS IRSA kubeconfig to {kubeconfig_path}", "DEBUG")
                        BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
                else:
                    logger(f"KUBECONFIG_CACHE: Cache MISS for AWS IRSA kubeconfig {region}/{cluster_name}, generating new", "DEBUG")
                    
                    # Generate the kubeconfig using IRSA
                    aws_utils.generate_kubeconfig_for_eks(
                        cluster_name=cluster_name,
                        region=region,
                        role_arn=role_arn,
                        auth_method="irsa"
                    )

                    # Set Kubeconfig Path
                    kubeconfig_path = os.environ.get("KUBECONFIG", "")
                    BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
                    
                    try:
                        with open(kubeconfig_path, "r") as f:
                            secret_data = f.read()
                        
                        # Cache the kubeconfig content to filesystem for future use
                        if aws_config_dir and kubeconfig_cache_file:
                            try:
                                with open(kubeconfig_cache_file, 'w') as f:
                                    f.write(secret_data)
                                logger(f"KUBECONFIG_CACHE: Cached AWS IRSA kubeconfig content to filesystem for {region}/{cluster_name}", "DEBUG")
                            except Exception as e:
                                logger(f"KUBECONFIG_CACHE: Failed to cache kubeconfig to filesystem: {e}", "DEBUG")
                        
                    except FileNotFoundError:
                        raise SecretNotFoundError(f"Kubeconfig file not found after generation at path {kubeconfig_path}")
            else:
                raise SecretNotFoundError(f"Key does not refer to a kubeconfig: {remaining_key}")

        # ========================================
        # AWS CLI (Explicit credentials for EKS kubeconfig)
        # Pattern: aws:cli@kubeconfig:{region}/{cluster_name}
        # ========================================
        elif _current_secret_provider == SecretProvider.AWS_CLI:
            # Fetch required AWS credentials from secrets
            required_keys = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
            credentials = {}

            for required_key in required_keys:
                logger(f"Looking for required key: {required_key}", "DEBUG")
                secret_key = secrets_provided.get(required_key)
                if not secret_key:
                    raise SecretNotFoundError(f"Required secret '{required_key}' not found in provided configuration.")
                credentials[required_key] = read_secret(secret_key, _recursion_stack)

            access_key_id = credentials.get("AWS_ACCESS_KEY_ID")
            secret_access_key = credentials.get("AWS_SECRET_ACCESS_KEY")
            
            # Optional session token
            session_token = None
            if "AWS_SESSION_TOKEN" in secrets_provided:
                session_token_key = secrets_provided.get("AWS_SESSION_TOKEN")
                if session_token_key:
                    session_token = read_secret(session_token_key, _recursion_stack)

            if not access_key_id or not secret_access_key:
                raise ValueError(f"Required fields (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY) missing in associated secrets.")

            if "kubeconfig" in key:
                logger(f"Handling AWS CLI provider for key: {remaining_key}", "DEBUG")
                try:
                    # Split correctly for region and cluster name
                    # Format: kubeconfig:{region}/{cluster_name}
                    resource_info = remaining_key.split(":", 1)[-1]  # Remove 'kubeconfig:' prefix
                    region, cluster_name = resource_info.split("/", 1)
                    logger(f"Parsed region: {region}, cluster name: {cluster_name}", "DEBUG")
                except ValueError:
                    raise ValueError(f"Expected format 'aws:cli@kubeconfig:region/cluster_name', got {remaining_key}")

                # Check for cached kubeconfig content in filesystem first
                aws_config_dir = os.environ.get('AWS_CONFIG_DIR', os.path.expanduser('~/.aws'))
                kubeconfig_cache_file = None
                cached_kubeconfig = None
                
                if aws_config_dir:
                    os.makedirs(aws_config_dir, exist_ok=True)
                    # Create a safe filename for the cache (include access key for isolation)
                    cache_filename = f"kubeconfig_cli_{region.replace('/', '_')}_{cluster_name.replace('/', '_')}_{access_key_id[:8]}.yaml"
                    kubeconfig_cache_file = os.path.join(aws_config_dir, cache_filename)
                    
                    if os.path.exists(kubeconfig_cache_file):
                        try:
                            # Check if cached file is recent (within 1 hour)
                            import time
                            cache_age = time.time() - os.path.getmtime(kubeconfig_cache_file)
                            if cache_age < 3600:  # 1 hour TTL
                                logger(f"KUBECONFIG_CACHE: Cache HIT for AWS CLI kubeconfig {region}/{cluster_name}, using filesystem cache", "DEBUG")
                                
                                with open(kubeconfig_cache_file, 'r') as f:
                                    cached_kubeconfig = f.read()
                            else:
                                logger(f"KUBECONFIG_CACHE: Cache EXPIRED for AWS CLI kubeconfig {region}/{cluster_name}, regenerating", "DEBUG")
                                os.remove(kubeconfig_cache_file)  # Remove expired cache
                        except Exception as e:
                            logger(f"KUBECONFIG_CACHE: Error reading cache file {kubeconfig_cache_file}: {e}", "DEBUG")
                
                if cached_kubeconfig:
                    secret_data = cached_kubeconfig
                    
                    # Still need to set credentials and write to execution-specific location
                    aws_utils.aws_login_access_key(access_key_id, secret_access_key, session_token)
                    
                    kubeconfig_path = os.environ.get("KUBECONFIG", "")
                    if kubeconfig_path:
                        kubeconfig_dir = os.path.dirname(kubeconfig_path)
                        if kubeconfig_dir:
                            os.makedirs(kubeconfig_dir, exist_ok=True)
                        with open(kubeconfig_path, "w") as f:
                            f.write(secret_data)
                        logger(f"KUBECONFIG_CACHE: Restored cached AWS CLI kubeconfig to {kubeconfig_path}", "DEBUG")
                        BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
                else:
                    logger(f"KUBECONFIG_CACHE: Cache MISS for AWS CLI kubeconfig {region}/{cluster_name}, generating new", "DEBUG")
                    
                    # Generate the kubeconfig using explicit credentials
                    aws_utils.generate_kubeconfig_for_eks(
                        cluster_name=cluster_name,
                        region=region,
                        access_key_id=access_key_id,
                        secret_access_key=secret_access_key,
                        session_token=session_token,
                        auth_method="access_key"
                    )

                    # Set Kubeconfig Path
                    kubeconfig_path = os.environ.get("KUBECONFIG", "")
                    BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
                    
                    try:
                        with open(kubeconfig_path, "r") as f:
                            secret_data = f.read()
                        
                        # Cache the kubeconfig content to filesystem for future use
                        if aws_config_dir and kubeconfig_cache_file:
                            try:
                                with open(kubeconfig_cache_file, 'w') as f:
                                    f.write(secret_data)
                                logger(f"KUBECONFIG_CACHE: Cached AWS CLI kubeconfig content to filesystem for {region}/{cluster_name}", "DEBUG")
                            except Exception as e:
                                logger(f"KUBECONFIG_CACHE: Failed to cache kubeconfig to filesystem: {e}", "DEBUG")
                        
                    except FileNotFoundError:
                        raise SecretNotFoundError(f"Kubeconfig file not found after generation at path {kubeconfig_path}")
            elif "cli" in key:
                logger(f"Handling AWS CLI provider for CLI authentication: {remaining_key}", "DEBUG")
                aws_utils.aws_login_access_key(access_key_id, secret_access_key, session_token)
                secret_data = f"AWS CLI authenticated with access key {access_key_id[:8]}..."
            else:
                raise SecretNotFoundError(f"Key does not refer to a kubeconfig or cli: {remaining_key}")

        if not secret_data:
            raise SecretNotFoundError(f"Secret at key '{remaining_key}' not found, got null value with provider {_current_secret_provider}")
        
        # Cache the secret value (existing functionality)
        _cache[key] = secret_data
        logger(f"SECRET_CACHE: Successfully fetched and cached secret for key: {remaining_key}", "DEBUG")
        _recursion_stack.discard(key)
        return secret_data

    except Exception as e:
        logger(f"Error reading secret for key '{key}': {str(e)}", "ERROR")
        _recursion_stack.discard(key)
        raise


def get_cache_stats():
    """Get statistics about caches and shared filesystem configuration."""
    return get_cache_info()


def clear_expired_caches():
    """Clear expired secret cache entries.
    
    Note: Credential caching is now handled via shared filesystem directories.
    This function only clears the in-memory secret value cache.
    """
    # Only clear in-memory secret cache - credential caching is filesystem-based
    logger.debug("Credential caching via shared filesystem - no manual cleanup needed")


def clear_all_caches():
    """Clear in-memory secret cache.
    
    Note: Credential caching is now handled via shared filesystem directories.
    To clear authentication state, remove files from AZURE_CONFIG_DIR and CLOUDSDK_CONFIG.
    """
    global _cache
    _cache.clear()
    logger.info("Cleared in-memory secret cache. Credential caching persists via shared filesystem.")


def log_credential_cache_status():
    """Log comprehensive credential cache status for troubleshooting."""
    cache_info = get_cache_info()
    
    logger.info("=== CREDENTIAL CACHE STATUS ===")
    logger.info(f"CREDENTIAL_CACHE: Method: {cache_info['caching_method']}")
    logger.info(f"CREDENTIAL_CACHE: Context Hash: {cache_info['credential_context_hash']}")
    logger.info(f"CREDENTIAL_CACHE: Azure Config Dir: {cache_info['azure_config_dir']}")
    logger.info(f"CREDENTIAL_CACHE: GCloud Config Dir: {cache_info['gcloud_config_dir']}")
    logger.info(f"CREDENTIAL_CACHE: AWS Config Dir: {cache_info.get('aws_config_dir', 'Not set')}")
    logger.info(f"CREDENTIAL_CACHE: Total Cache Size: {cache_info['total_cache_size']}")
    logger.info(f"CREDENTIAL_CACHE: Kubeconfig Caches: {cache_info['kubeconfig_caches']}")
    logger.info(f"CREDENTIAL_CACHE: Secret Caches: {cache_info['secret_caches']}")
    
    # Log cache directory statistics
    stats = cache_info.get('cache_directory_stats', {})
    for provider, provider_stats in stats.items():
        if provider_stats['exists']:
            logger.info(f"CREDENTIAL_CACHE: {provider.upper()} - Files: {provider_stats['files']}, Size: {provider_stats['size_mb']}MB")
        else:
            logger.info(f"CREDENTIAL_CACHE: {provider.upper()} - Directory does not exist")
    
    # Log AWS credential cache info
    aws_cache = cache_info.get('aws_credential_cache', {})
    if aws_cache:
        logger.info(f"CREDENTIAL_CACHE: AWS In-Memory Cache Size: {aws_cache.get('cache_size', 0)}")
    
    # Log environment variables that affect credential context
    context_vars = [
        'RW_WORKSPACE', 'RW_LOCATION', 'RW_VAULT_ADDR', 
        'RW_VAULT_APPROLE_ROLE_ID', 'RW_LOCATION_VAULT_AUTH_MOUNT_POINT',
        'AWS_DEFAULT_REGION', 'AWS_REGION'
    ]
    
    logger.info("CREDENTIAL_CACHE: Context Environment Variables:")
    for var in context_vars:
        value = os.getenv(var, 'Not set')
        # Mask sensitive values
        if 'SECRET' in var or 'PASSWORD' in var or 'KEY' in var:
            value = value[:8] + '...' if value != 'Not set' and len(value) > 8 else value
        logger.info(f"CREDENTIAL_CACHE:   {var}={value}")
    
    logger.info("=== END CREDENTIAL CACHE STATUS ===")
    
    return cache_info
