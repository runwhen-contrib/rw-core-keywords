"""
AWS utilities for credential management and EKS kubeconfig generation.

Supports the following workspaceKey patterns:
- aws:irsa@cli - IRSA (IAM Roles for Service Accounts) authentication
- aws:access_key@cli - Explicit access key authentication  
- aws:assume_role@cli - Assume role authentication
- aws:default@cli - Default credential chain
- aws:workload_identity@kubeconfig:{region}/{cluster_name} - EKS with IRSA
- aws:cli@kubeconfig:{region}/{cluster_name} - EKS with explicit credentials
"""

import subprocess
import time
import hashlib
import logging
import json
import os
import sys
import yaml
from robot.libraries.BuiltIn import BuiltIn

logger = logging.getLogger(__name__)


def _set_aws_suite_variables():
    """Set AWS configuration as Robot Framework suite variables if in RF context.
    
    This mirrors what azure_utils.az_login() does with AZURE_CONFIG_DIR -
    ensuring the context-isolated AWS config directory and region are available
    as Robot Framework variables for codebundles to reference.
    """
    try:
        aws_config_dir = os.environ.get("AWS_CONFIG_DIR", "")
        if aws_config_dir:
            BuiltIn().set_suite_variable("${AWS_CONFIG_DIR}", aws_config_dir)
        
        aws_region = os.environ.get("AWS_DEFAULT_REGION", "") or os.environ.get("AWS_REGION", "")
        if aws_region:
            BuiltIn().set_suite_variable("${AWS_DEFAULT_REGION}", aws_region)
    except Exception:
        # Not running in Robot Framework context, skip setting suite variables
        pass


# AWS credential cache
_aws_credential_cache = {}
_aws_credential_cache_ttl = {}

# Cache TTL for AWS credentials (1 hour by default)
AWS_CREDENTIAL_TTL = int(os.getenv("RW_AWS_CREDENTIAL_CACHE_TTL", "3600"))


def _generate_aws_cache_key(access_key_id=None, secret_access_key=None, role_arn=None, auth_method="default"):
    """Generate cache key for AWS credentials.
    
    Args:
        access_key_id: AWS access key ID (for explicit credentials)
        secret_access_key: AWS secret access key (for explicit credentials)
        role_arn: Role ARN to assume
        auth_method: Authentication method - one of: 'irsa', 'pod_identity', 'irsa_partial', 
                     'explicit', 'default', 'access_key', 'assume_role', 'workload_identity'
    
    Returns:
        str: Unique cache key for this credential combination
    """
    if access_key_id and secret_access_key:
        # Hash the secret for security
        secret_hash = hashlib.sha256(secret_access_key.encode()).hexdigest()[:8]
        if role_arn:
            role_hash = hashlib.sha256(role_arn.encode()).hexdigest()[:8]
            return f"aws_assume_role_{access_key_id}_{secret_hash}_{role_hash}"
        return f"aws_access_key_{access_key_id}_{secret_hash}"
    elif role_arn:
        role_hash = hashlib.sha256(role_arn.encode()).hexdigest()[:8]
        return f"aws_assume_role_irsa_{role_hash}"
    elif auth_method in ("irsa", "workload_identity"):
        return "aws_irsa_default"
    elif auth_method == "pod_identity":
        return "aws_pod_identity_default"
    elif auth_method == "irsa_partial":
        return "aws_irsa_partial"
    elif auth_method == "explicit":
        return "aws_explicit_env"
    else:
        return f"aws_{auth_method}_chain"


def _is_aws_cache_valid(cache_key: str) -> bool:
    """Check if cached AWS credential is still valid."""
    if cache_key not in _aws_credential_cache_ttl:
        return False
    return time.time() < _aws_credential_cache_ttl[cache_key]


def _cache_aws_credential(cache_key: str, credential_data, ttl_seconds: int):
    """Cache AWS credential with TTL."""
    _aws_credential_cache[cache_key] = credential_data
    _aws_credential_cache_ttl[cache_key] = time.time() + ttl_seconds
    logger.info(f"CREDENTIAL_CACHE: Cached AWS credential {cache_key} for {ttl_seconds} seconds")


def _get_cached_aws_credential(cache_key: str):
    """Get cached AWS credential if valid."""
    if cache_key in _aws_credential_cache and _is_aws_cache_valid(cache_key):
        logger.info(f"CREDENTIAL_CACHE: Cache HIT for AWS credential {cache_key}")
        return _aws_credential_cache[cache_key]
    return None


def _is_aws_cli_authenticated(expected_role_arn=None):
    """
    Check if AWS CLI is authenticated with the correct credentials.
    
    This validates:
    1. AWS CLI can make authenticated calls
    2. Current assumed role matches expected role ARN (if specified)
    
    Args:
        expected_role_arn: Optional role ARN to verify we're using the expected assumed role
        
    Returns:
        bool: True if authenticated (and role matches if specified)
    """
    try:
        # Check current identity
        result = subprocess.run(
            ["aws", "sts", "get-caller-identity", "--output", "json"],
            capture_output=True, text=True, check=True
        )
        identity_info = json.loads(result.stdout)
        
        current_arn = identity_info.get("Arn", "")
        current_account = identity_info.get("Account", "")
        current_user_id = identity_info.get("UserId", "")
        
        logger.debug(f"CREDENTIAL_CACHE: Current AWS session - arn: {current_arn}, account: {current_account}")
        
        # If we have an expected role ARN, verify we're using that role
        if expected_role_arn:
            # Check if the current ARN indicates we've assumed the expected role
            # Role ARNs look like: arn:aws:iam::123456789012:role/MyRole
            # Assumed role ARNs look like: arn:aws:sts::123456789012:assumed-role/MyRole/session-name
            if "assumed-role" in current_arn:
                # Extract role name from assumed-role ARN
                current_role_name = current_arn.split("/")[1] if "/" in current_arn else ""
                expected_role_name = expected_role_arn.split("/")[-1] if "/" in expected_role_arn else ""
                
                if current_role_name != expected_role_name:
                    logger.debug(f"CREDENTIAL_CACHE: Role mismatch - expected: {expected_role_name}, current: {current_role_name}")
                    return False
            else:
                # Not using assumed role, but we expected one
                logger.debug(f"CREDENTIAL_CACHE: Expected assumed role but not in assumed-role state")
                return False
        
        logger.debug(f"CREDENTIAL_CACHE: AWS CLI authentication validated successfully")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.debug(f"CREDENTIAL_CACHE: AWS CLI authentication check failed: {e}")
        return False
    except json.JSONDecodeError as e:
        logger.debug(f"CREDENTIAL_CACHE: Failed to parse AWS identity info: {e}")
        return False
    except Exception as e:
        logger.debug(f"CREDENTIAL_CACHE: Unexpected error checking AWS authentication: {e}")
        return False


def aws_login_irsa():
    """
    Authenticate using IRSA (IAM Roles for Service Accounts) or EKS Pod Identity.
    
    Supports both authentication mechanisms:
    - IRSA: Uses projected service account token and web identity federation
    - Pod Identity: Uses EKS Pod Identity Agent (newer, simpler approach)
    
    No explicit credential setup needed - boto3/AWS CLI automatically use these
    when running in an EKS pod with proper configuration.
    
    Returns:
        bool: True if authentication check passes
    """
    # Set AWS config dir as Robot Framework suite variable
    _set_aws_suite_variables()
    
    # Detect which identity mechanism is available
    identity_type, identity_env_vars = _detect_aws_identity_type()
    
    cache_key = _generate_aws_cache_key(auth_method=identity_type)
    
    # Check cache first
    cached = _get_cached_aws_credential(cache_key)
    if cached:
        logger.info(f"CREDENTIAL_CACHE: Using cached {identity_type} credentials")
        return True
    
    logger.info(f"CREDENTIAL_CACHE: Performing AWS authentication using {identity_type}")
    
    if identity_type == 'pod_identity':
        print("Using EKS Pod Identity for AWS authentication...")
    elif identity_type == 'irsa':
        print("Using IRSA (IAM Roles for Service Accounts) for AWS authentication...")
    else:
        print(f"Using AWS {identity_type} credential chain for authentication...")
    
    # Log the identity configuration for debugging
    _log_aws_identity_debug_info()
    
    # Verify authentication works
    if _is_aws_cli_authenticated():
        logger.info(f"CREDENTIAL_CACHE: AWS {identity_type} authentication successful")
        _cache_aws_credential(cache_key, {"method": identity_type}, AWS_CREDENTIAL_TTL)
        print(f"{identity_type.upper()} authentication successful.")
        return True
    else:
        error_msg = f"AWS {identity_type} authentication failed"
        if identity_type == 'irsa':
            error_msg += " - ensure the pod has a service account with IAM role annotation (eks.amazonaws.com/role-arn)"
        elif identity_type == 'pod_identity':
            error_msg += " - ensure EKS Pod Identity is configured for this service account"
        raise RuntimeError(error_msg)


def _log_aws_identity_debug_info():
    """Log debug information about AWS identity configuration."""
    debug_info = []
    
    # IRSA
    web_identity_token = os.environ.get('AWS_WEB_IDENTITY_TOKEN_FILE')
    role_arn = os.environ.get('AWS_ROLE_ARN')
    if web_identity_token:
        token_exists = os.path.exists(web_identity_token)
        debug_info.append(f"IRSA: AWS_WEB_IDENTITY_TOKEN_FILE={web_identity_token} (exists: {token_exists})")
    if role_arn:
        debug_info.append(f"IRSA: AWS_ROLE_ARN={role_arn}")
    
    # Pod Identity
    container_creds_uri = os.environ.get('AWS_CONTAINER_CREDENTIALS_FULL_URI')
    container_auth_token = os.environ.get('AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE')
    if container_creds_uri:
        debug_info.append(f"Pod Identity: AWS_CONTAINER_CREDENTIALS_FULL_URI={container_creds_uri}")
    if container_auth_token:
        debug_info.append(f"Pod Identity: AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE={container_auth_token}")
    
    # Region
    region = os.environ.get('AWS_DEFAULT_REGION') or os.environ.get('AWS_REGION')
    if region:
        debug_info.append(f"Region: {region}")
    
    # Log all debug info
    for info in debug_info:
        logger.info(f"AWS_IDENTITY_DEBUG: {info}")
        print(f"  {info}")


def aws_login_access_key(access_key_id: str, secret_access_key: str, session_token: str = None, region: str = None):
    """
    Authenticate using explicit AWS access keys.
    
    Args:
        access_key_id: AWS Access Key ID
        secret_access_key: AWS Secret Access Key
        session_token: Optional session token for temporary credentials
        region: Optional AWS region
        
    Returns:
        bool: True if authentication succeeds
    """
    cache_key = _generate_aws_cache_key(access_key_id=access_key_id, secret_access_key=secret_access_key)
    
    # Check cache first
    cached = _get_cached_aws_credential(cache_key)
    if cached:
        logger.info("CREDENTIAL_CACHE: Using cached AWS access key credentials")
        # Re-export environment variables
        os.environ['AWS_ACCESS_KEY_ID'] = access_key_id
        os.environ['AWS_SECRET_ACCESS_KEY'] = secret_access_key
        if session_token:
            os.environ['AWS_SESSION_TOKEN'] = session_token
        elif 'AWS_SESSION_TOKEN' in os.environ:
            # Clear stale session token from previous assume_role calls
            del os.environ['AWS_SESSION_TOKEN']
        if region:
            os.environ['AWS_DEFAULT_REGION'] = region
        _set_aws_suite_variables()
        return True
    
    logger.info(f"CREDENTIAL_CACHE: Performing AWS access key authentication (key: {access_key_id[:8]}...)")
    print("Configuring AWS access key credentials...")
    
    # Set environment variables for AWS CLI/SDK
    os.environ['AWS_ACCESS_KEY_ID'] = access_key_id
    os.environ['AWS_SECRET_ACCESS_KEY'] = secret_access_key
    if session_token:
        os.environ['AWS_SESSION_TOKEN'] = session_token
    elif 'AWS_SESSION_TOKEN' in os.environ:
        # Clear stale session token from previous assume_role calls
        del os.environ['AWS_SESSION_TOKEN']
    if region:
        os.environ['AWS_DEFAULT_REGION'] = region
    
    # Verify authentication works
    if _is_aws_cli_authenticated():
        logger.info("CREDENTIAL_CACHE: AWS access key authentication successful")
        _cache_aws_credential(cache_key, {
            "method": "access_key",
            "access_key_id": access_key_id
        }, AWS_CREDENTIAL_TTL)
        print("AWS access key authentication successful.")
        _set_aws_suite_variables()
        return True
    else:
        raise RuntimeError("AWS access key authentication failed - verify your credentials")


def aws_login_assume_role(role_arn: str, access_key_id: str = None, secret_access_key: str = None, 
                          session_token: str = None, session_name: str = "runwhen-session",
                          external_id: str = None, region: str = None):
    """
    Authenticate by assuming an IAM role.
    
    Can use either:
    - Base credentials (access keys) to assume the role
    - IRSA/default credentials to assume the role (cross-account)
    
    Args:
        role_arn: ARN of the IAM role to assume
        access_key_id: Optional base AWS Access Key ID
        secret_access_key: Optional base AWS Secret Access Key
        session_token: Optional base session token
        session_name: Session name for the assumed role
        external_id: Optional external ID for cross-account access
        region: Optional AWS region
        
    Returns:
        dict: Assumed role credentials
    """
    cache_key = _generate_aws_cache_key(
        access_key_id=access_key_id, 
        secret_access_key=secret_access_key,
        role_arn=role_arn
    )
    
    # Check cache first
    cached = _get_cached_aws_credential(cache_key)
    if cached and cached.get("credentials"):
        logger.info("CREDENTIAL_CACHE: Using cached assumed role credentials")
        creds = cached["credentials"]
        os.environ['AWS_ACCESS_KEY_ID'] = creds['AccessKeyId']
        os.environ['AWS_SECRET_ACCESS_KEY'] = creds['SecretAccessKey']
        os.environ['AWS_SESSION_TOKEN'] = creds['SessionToken']
        if region:
            os.environ['AWS_DEFAULT_REGION'] = region
        _set_aws_suite_variables()
        return creds
    
    logger.info(f"CREDENTIAL_CACHE: Performing AWS assume role (role: {role_arn})")
    print(f"Assuming IAM role: {role_arn}...")
    
    # If base credentials provided, set them first
    if access_key_id and secret_access_key:
        os.environ['AWS_ACCESS_KEY_ID'] = access_key_id
        os.environ['AWS_SECRET_ACCESS_KEY'] = secret_access_key
        if session_token:
            os.environ['AWS_SESSION_TOKEN'] = session_token
        elif 'AWS_SESSION_TOKEN' in os.environ:
            # Clear stale session token from previous operations
            del os.environ['AWS_SESSION_TOKEN']
    
    try:
        # Build assume-role command
        cmd = [
            "aws", "sts", "assume-role",
            "--role-arn", role_arn,
            "--role-session-name", session_name,
            "--output", "json"
        ]
        
        if external_id:
            cmd.extend(["--external-id", external_id])
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        response = json.loads(result.stdout)
        credentials = response.get("Credentials", {})
        
        # Validate that required credential keys are present
        required_keys = ['AccessKeyId', 'SecretAccessKey', 'SessionToken']
        missing_keys = [key for key in required_keys if key not in credentials]
        if missing_keys:
            raise RuntimeError(f"AWS STS response missing required credential keys: {missing_keys}")
        
        # Set the assumed role credentials
        os.environ['AWS_ACCESS_KEY_ID'] = credentials['AccessKeyId']
        os.environ['AWS_SECRET_ACCESS_KEY'] = credentials['SecretAccessKey']
        os.environ['AWS_SESSION_TOKEN'] = credentials['SessionToken']
        if region:
            os.environ['AWS_DEFAULT_REGION'] = region
        
        # Verify the assumed role
        if _is_aws_cli_authenticated(expected_role_arn=role_arn):
            logger.info(f"CREDENTIAL_CACHE: AWS assume role successful for {role_arn}")
            _cache_aws_credential(cache_key, {
                "method": "assume_role",
                "role_arn": role_arn,
                "credentials": credentials
            }, min(AWS_CREDENTIAL_TTL, 3600))  # Cap at 1 hour for assumed role
            print(f"Successfully assumed role: {role_arn}")
            _set_aws_suite_variables()
            return credentials
        else:
            raise RuntimeError(f"Assumed role but verification failed for {role_arn}")
            
    except subprocess.CalledProcessError as e:
        logger.error(f"CREDENTIAL_CACHE: AWS assume role failed: {e.stderr}")
        print(f"Failed to assume role: {e.stderr}", file=sys.stderr)
        raise RuntimeError(f"Failed to assume role {role_arn}: {e.stderr}")


def aws_login_default():
    """
    Authenticate using AWS default credential chain.
    
    boto3's default credential chain checks (in order):
    1. Environment variables (AWS_ACCESS_KEY_ID, etc.)
    2. Shared credential file (~/.aws/credentials)
    3. AWS config file (~/.aws/config)
    4. Assume role provider
    5. Boto2 config file
    6. Instance metadata service (IMDS) on EC2
    7. Container credentials (ECS/EKS)
    
    Returns:
        bool: True if authentication check passes
    """
    # Set AWS config dir as Robot Framework suite variable
    _set_aws_suite_variables()
    
    cache_key = _generate_aws_cache_key(auth_method="default")
    
    # Check cache first
    cached = _get_cached_aws_credential(cache_key)
    if cached:
        logger.info("CREDENTIAL_CACHE: Using cached AWS default chain credentials")
        return True
    
    logger.info("CREDENTIAL_CACHE: Performing AWS default credential chain authentication")
    print("Using AWS default credential chain for authentication...")
    
    if _is_aws_cli_authenticated():
        logger.info("CREDENTIAL_CACHE: AWS default chain authentication successful")
        _cache_aws_credential(cache_key, {"method": "default"}, AWS_CREDENTIAL_TTL)
        print("AWS default chain authentication successful.")
        return True
    else:
        raise RuntimeError("AWS default credential chain authentication failed - no valid credentials found")


def get_aws_account_id():
    """Get the current AWS account ID."""
    try:
        result = subprocess.run(
            ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except Exception as e:
        logger.error(f"Failed to get AWS account ID: {e}")
        return None


def _detect_aws_identity_type():
    """
    Detect which AWS identity mechanism is available.
    
    Returns:
        tuple: (identity_type, env_vars_dict)
        identity_type is one of: 'pod_identity', 'irsa', 'default', None
    """
    # Check for EKS Pod Identity (newer, preferred)
    # Pod Identity uses AWS_CONTAINER_CREDENTIALS_FULL_URI
    container_creds_uri = os.environ.get('AWS_CONTAINER_CREDENTIALS_FULL_URI')
    container_auth_token = os.environ.get('AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE')
    
    if container_creds_uri:
        logger.info(f"Detected EKS Pod Identity: AWS_CONTAINER_CREDENTIALS_FULL_URI={container_creds_uri}")
        env_vars = {'AWS_CONTAINER_CREDENTIALS_FULL_URI': container_creds_uri}
        if container_auth_token:
            env_vars['AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE'] = container_auth_token
        return 'pod_identity', env_vars
    
    # Check for IRSA (IAM Roles for Service Accounts)
    web_identity_token_file = os.environ.get('AWS_WEB_IDENTITY_TOKEN_FILE')
    role_arn = os.environ.get('AWS_ROLE_ARN')
    
    if web_identity_token_file and role_arn:
        logger.info(f"Detected IRSA: AWS_WEB_IDENTITY_TOKEN_FILE={web_identity_token_file}, AWS_ROLE_ARN={role_arn}")
        env_vars = {
            'AWS_WEB_IDENTITY_TOKEN_FILE': web_identity_token_file,
            'AWS_ROLE_ARN': role_arn
        }
        return 'irsa', env_vars
    
    # Check for just web identity token (partial IRSA setup)
    if web_identity_token_file:
        logger.warning(f"Found AWS_WEB_IDENTITY_TOKEN_FILE but missing AWS_ROLE_ARN - IRSA may not work correctly")
        return 'irsa_partial', {'AWS_WEB_IDENTITY_TOKEN_FILE': web_identity_token_file}
    
    # Default credential chain (EC2 instance profile, env vars, etc.)
    access_key = os.environ.get('AWS_ACCESS_KEY_ID')
    if access_key:
        logger.info("Detected explicit AWS credentials (AWS_ACCESS_KEY_ID)")
        return 'explicit', {}
    
    logger.info("No specific AWS identity mechanism detected, will use default credential chain")
    return 'default', {}


def _fix_kubeconfig_aws_path(kubeconfig_path: str):
    """
    Fix the AWS CLI path and identity environment in the kubeconfig.
    
    The kubeconfig generated by `aws eks update-kubeconfig` uses just 'aws' as the
    command, which may not be found when kubectl runs in a subprocess with a different
    PATH. This function updates the kubeconfig to use the full path to the AWS CLI.
    
    Additionally, for IRSA (IAM Roles for Service Accounts) and EKS Pod Identity,
    the relevant environment variables need to be embedded in the kubeconfig's exec
    section, because subprocesses may not inherit these environment variables.
    
    Supports:
    - EKS Pod Identity (AWS_CONTAINER_CREDENTIALS_FULL_URI)
    - IRSA (AWS_WEB_IDENTITY_TOKEN_FILE, AWS_ROLE_ARN)
    
    This is similar to what AKS does with kubelogin.
    
    Args:
        kubeconfig_path: Path to the kubeconfig file to fix
    """
    try:
        # Find the AWS CLI path
        aws_path = "/usr/local/bin/aws"
        
        # Try to find aws in common locations
        aws_locations = [
            "/usr/local/bin/aws",
            "/usr/bin/aws",
            "/opt/homebrew/bin/aws",
            "/home/linuxbrew/.linuxbrew/bin/aws"
        ]
        
        for path in aws_locations:
            if os.path.exists(path):
                aws_path = path
                break
        else:
            # Try to find it using 'which'
            try:
                result = subprocess.run(["which", "aws"], capture_output=True, text=True, check=True)
                aws_path = result.stdout.strip()
            except subprocess.CalledProcessError:
                logger.warning(f"Could not find AWS CLI path, using default: {aws_path}")
        
        logger.info(f"Using AWS CLI path: {aws_path}")
        
        # Detect identity type and collect environment variables
        identity_type, identity_env_vars = _detect_aws_identity_type()
        
        # Build the list of environment variables to embed in kubeconfig
        exec_env_vars = []
        
        # Add identity-specific env vars
        for name, value in identity_env_vars.items():
            exec_env_vars.append({'name': name, 'value': value})
            logger.info(f"Adding {name} to kubeconfig exec env")
        
        # Add common AWS env vars
        aws_region = os.environ.get('AWS_DEFAULT_REGION') or os.environ.get('AWS_REGION')
        if aws_region:
            exec_env_vars.append({'name': 'AWS_DEFAULT_REGION', 'value': aws_region})
            logger.info(f"Adding AWS_DEFAULT_REGION to kubeconfig exec env: {aws_region}")
        
        # Also add AWS_STS_REGIONAL_ENDPOINTS if set
        sts_endpoints = os.environ.get('AWS_STS_REGIONAL_ENDPOINTS')
        if sts_endpoints:
            exec_env_vars.append({'name': 'AWS_STS_REGIONAL_ENDPOINTS', 'value': sts_endpoints})
        
        # Load the kubeconfig
        with open(kubeconfig_path, "r") as f:
            kubeconfig = yaml.safe_load(f)
        
        # Update the exec command path and environment for all users
        modified = False
        for user in kubeconfig.get('users', []):
            exec_config = user.get('user', {}).get('exec')
            if exec_config and exec_config.get('command') in ('aws', '/usr/local/bin/aws', '/usr/bin/aws'):
                logger.info(f"Updating AWS CLI config in kubeconfig for user: {user.get('name', 'unknown')}")
                
                # Fix the command path
                exec_config['command'] = aws_path
                
                # Add identity environment variables to exec config
                if exec_env_vars:
                    # Get existing env or create new list
                    existing_env = exec_config.get('env', []) or []
                    existing_env_names = {e.get('name') for e in existing_env if e.get('name')}
                    
                    # Add new env vars that don't already exist
                    for env_var in exec_env_vars:
                        if env_var['name'] not in existing_env_names:
                            existing_env.append(env_var)
                    
                    exec_config['env'] = existing_env
                    logger.info(f"Added {len(exec_env_vars)} AWS identity environment variables to kubeconfig exec config (type: {identity_type})")
                
                modified = True
        
        # Save the modified kubeconfig
        if modified:
            with open(kubeconfig_path, "w") as f:
                yaml.dump(kubeconfig, f, default_flow_style=False)
            logger.info(f"Successfully updated kubeconfig with AWS CLI path ({aws_path}) and {identity_type} env vars")
        else:
            logger.debug("No AWS exec commands found in kubeconfig to update")
            
    except Exception as e:
        logger.error(f"Failed to fix AWS CLI path in kubeconfig: {e}")
        # Don't raise - this is a best-effort fix
        print(f"Warning: Could not fix AWS CLI path in kubeconfig: {e}", file=sys.stderr)


def generate_kubeconfig_for_eks(cluster_name: str, region: str, 
                                 access_key_id: str = None, secret_access_key: str = None,
                                 session_token: str = None, role_arn: str = None,
                                 auth_method: str = "default", context_alias: str = None):
    """
    Generate kubeconfig for EKS cluster using aws eks update-kubeconfig.
    
    Args:
        cluster_name: Name of the EKS cluster
        region: AWS region where the cluster is located
        access_key_id: Optional AWS Access Key ID for explicit credentials
        secret_access_key: Optional AWS Secret Access Key
        session_token: Optional session token
        role_arn: Optional role ARN to assume for cluster access
        auth_method: Authentication method ('irsa', 'access_key', 'assume_role', 'default')
        context_alias: Optional alias for the context name (defaults to cluster_name if not specified)
        
    Returns:
        str: Path to the generated kubeconfig file
    """
    logger.info(f"Generating kubeconfig for EKS cluster {cluster_name} in {region}")
    
    # Set up credentials based on auth method
    if auth_method in ("irsa", "workload_identity", "pod_identity"):
        aws_login_irsa()
    elif auth_method == "access_key":
        if not access_key_id or not secret_access_key:
            raise ValueError(f"auth_method='access_key' requires access_key_id and secret_access_key parameters")
        aws_login_access_key(access_key_id, secret_access_key, session_token, region)
    elif auth_method == "assume_role":
        if not role_arn:
            raise ValueError(f"auth_method='assume_role' requires role_arn parameter")
        aws_login_assume_role(role_arn, access_key_id, secret_access_key, session_token, region=region)
    elif auth_method == "default":
        aws_login_default()
    else:
        raise ValueError(f"Unknown auth_method: {auth_method}. Valid options: irsa, workload_identity, pod_identity, access_key, assume_role, default")
    
    # Get kubeconfig path
    kubeconfig_path = os.environ.get("KUBECONFIG", "")
    if not kubeconfig_path:
        raise ValueError("KUBECONFIG environment variable not set")
    
    # Ensure directory exists (only if path has a directory component)
    kubeconfig_dir = os.path.dirname(kubeconfig_path)
    if kubeconfig_dir:
        os.makedirs(kubeconfig_dir, exist_ok=True)
    
    # Use cluster_name as the default alias if not specified
    # This ensures the context name matches what codebundles expect
    if context_alias is None:
        context_alias = cluster_name
    
    try:
        # Build update-kubeconfig command
        cmd = [
            "aws", "eks", "update-kubeconfig",
            "--name", cluster_name,
            "--region", region,
            "--kubeconfig", kubeconfig_path,
            "--alias", context_alias  # Use alias to get a simple context name
        ]
        
        # If a role ARN is specified for cluster access (different from auth role)
        if role_arn and auth_method != "assume_role":
            cmd.extend(["--role-arn", role_arn])
        
        logger.info(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        print("EKS kubeconfig generation output:", result.stdout)
        if result.stderr:
            print("EKS kubeconfig generation stderr:", result.stderr)
        
        # Fix the AWS CLI path in the kubeconfig to use absolute path
        # This is similar to what AKS does with kubelogin
        _fix_kubeconfig_aws_path(kubeconfig_path)
        
        logger.info(f"Successfully generated kubeconfig for EKS cluster {cluster_name} in {region}")
        
        # Set Robot Framework variable if in RF context
        try:
            BuiltIn().set_suite_variable("${KUBECONFIG}", kubeconfig_path)
        except Exception:
            pass
        
        return kubeconfig_path
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to generate kubeconfig for EKS cluster: {e}")
        print(f"Failed to generate kubeconfig for EKS cluster: {e.stderr}", file=sys.stderr)
        raise


def list_eks_clusters(region: str = None):
    """
    List all EKS clusters in the specified region (or all regions if not specified).
    
    Args:
        region: AWS region to list clusters from (optional)
        
    Returns:
        list: List of cluster names
    """
    try:
        cmd = ["aws", "eks", "list-clusters", "--output", "json"]
        if region:
            cmd.extend(["--region", region])
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        response = json.loads(result.stdout)
        return response.get("clusters", [])
        
    except Exception as e:
        logger.error(f"Failed to list EKS clusters: {e}")
        print(f"Failed to list EKS clusters: {e}", file=sys.stderr)
        return []


def describe_eks_cluster(cluster_name: str, region: str):
    """
    Get details about an EKS cluster.
    
    Args:
        cluster_name: Name of the EKS cluster
        region: AWS region
        
    Returns:
        dict: Cluster details
    """
    try:
        result = subprocess.run([
            "aws", "eks", "describe-cluster",
            "--name", cluster_name,
            "--region", region,
            "--output", "json"
        ], capture_output=True, text=True, check=True)
        
        response = json.loads(result.stdout)
        return response.get("cluster", {})
        
    except Exception as e:
        logger.error(f"Failed to describe EKS cluster {cluster_name}: {e}")
        return {}


def get_cache_info():
    """Get information about AWS credential caching."""
    return {
        "cache_size": len(_aws_credential_cache),
        "cached_keys": list(_aws_credential_cache.keys()),
        "ttl_info": {k: v - time.time() for k, v in _aws_credential_cache_ttl.items() if v > time.time()},
        "description": "AWS credential caching with configurable TTL"
    }


def clear_aws_cache():
    """Clear all AWS credential caches."""
    global _aws_credential_cache, _aws_credential_cache_ttl
    _aws_credential_cache.clear()
    _aws_credential_cache_ttl.clear()
    logger.info("CREDENTIAL_CACHE: Cleared AWS credential cache")
