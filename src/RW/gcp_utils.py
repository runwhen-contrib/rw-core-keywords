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

# GCP credential cache
_gcp_credential_cache = {}
_gcp_credential_cache_ttl = {}

# Cache TTL for GCP credentials (1 hour by default)
GCP_CREDENTIAL_TTL = int(os.getenv("RW_GCP_CREDENTIAL_CACHE_TTL", "3600"))

def _generate_gcp_cache_key(project_id=None, service_account_key=None):
    """Generate cache key for GCP credentials."""
    if project_id and service_account_key:
        # Hash the service account key for security
        key_hash = hashlib.sha256(service_account_key.encode()).hexdigest()[:8]
        return f"gcp_sa_{project_id}_{key_hash}"
    else:
        return "gcp_adc_default"

def _is_gcp_cache_valid(cache_key: str) -> bool:
    """Check if cached GCP credential is still valid."""
    if cache_key not in _gcp_credential_cache_ttl:
        return False
    return time.time() < _gcp_credential_cache_ttl[cache_key]

def _get_cached_gcp_credential(cache_key: str):
    """Get cached GCP credential if valid."""
    if cache_key in _gcp_credential_cache and _is_gcp_cache_valid(cache_key):
        logger.info(f"CREDENTIAL_CACHE: Cache HIT for GCP credential {cache_key}")
        return _gcp_credential_cache[cache_key]
    return None

def _cache_gcp_credential(cache_key: str, credential_data, ttl_seconds: int):
    """Cache GCP credential with TTL."""
    _gcp_credential_cache[cache_key] = credential_data
    _gcp_credential_cache_ttl[cache_key] = time.time() + ttl_seconds
    logger.info(f"CREDENTIAL_CACHE: Cached GCP credential {cache_key} for {ttl_seconds} seconds")

def gcloud_login(project_id=None, service_account_key=None):
    """
    Perform gcloud auth login using service account key or application default credentials.
    
    Args:
        project_id: GCP project ID
        service_account_key: Service account JSON key as string
    """
    
    # Set up GCP config directory for credential caching
    gcp_dir = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_DIR', os.path.expanduser('~/.config/gcloud'))
    os.makedirs(gcp_dir, exist_ok=True)
    
    # Generate cache key for this credential combination
    cache_key = _generate_gcp_cache_key(
        project_id=project_id,
        service_account_key=service_account_key
    )
    
    try:
        # Capture the output and error for more detailed logs
        adc_available = False  # set True in the ADC branch below
        if service_account_key and project_id:
            logger.info(f"CREDENTIAL_CACHE: Performing GCP Service Account login (project: {project_id})")
            print("Logging into GCP with Service Account credentials...")
            
            # Write service account key to temporary file
            sa_key_file = os.path.join(gcp_dir, f"sa_key_{cache_key}.json")
            with open(sa_key_file, 'w') as f:
                f.write(service_account_key)
            
            # Activate service account
            result = subprocess.run([
                "gcloud", "auth", "activate-service-account",
                "--key-file", sa_key_file
            ], capture_output=True, text=True, check=True)
            
            # Set project
            if project_id:
                subprocess.run([
                    "gcloud", "config", "set", "project", project_id
                ], capture_output=True, text=True, check=True)
            
            # For service accounts, we don't need to create a credentials object
            # The gcloud CLI handles authentication
            
        else:
            logger.info(f"CREDENTIAL_CACHE: Performing GCP Application Default Credentials login")
            print("Using application default credentials for authentication")
            
            # Check whether ADC is already available from the environment
            # (GCE/GKE metadata server, or a credentials file pointed to by
            # GOOGLE_APPLICATION_CREDENTIALS). This mirrors how Azure Identity
            # checks `_is_azure_cli_authenticated()` before calling `az login`,
            # and how AWS IRSA detects `AWS_WEB_IDENTITY_TOKEN_FILE` /
            # `AWS_CONTAINER_CREDENTIALS_FULL_URI` without running a login
            # command — federated credentials come from the environment.
            adc_available = False
            try:
                import google.auth
                google.auth.default()
                adc_available = True
                logger.info("CREDENTIAL_CACHE: Application Default Credentials already available from environment")
                print("Application Default Credentials already available from environment, skipping login")
            except Exception:
                pass
            
            if not adc_available:
                # ADC not in the environment — local workstation or a pod
                # without a metadata server. Use the gcloud CLI to bootstrap
                # credentials. --quiet avoids the interactive prompt that
                # fails on GCE VMs ("not in an interactive session").
                result = subprocess.run([
                    "gcloud", "auth", "application-default", "login",
                    "--no-launch-browser", "--quiet"
                ], capture_output=True, text=True, check=True)
            
            # Get project ID from gcloud if not provided
            if not project_id:
                project_id = get_project_id(None)
        
        # Print the captured output and error logs
        if not adc_available:
            print("Login output:", result.stdout)
            print("Login error output:", result.stderr)
        
        logger.info(f"CREDENTIAL_CACHE: GCP authentication successful, credentials stored in {gcp_dir}")
        print("Login successful.")
        
        return True, project_id
        
    except subprocess.CalledProcessError as e:
        logger.error(f"GCP authentication failed: {e}")
        print(f"GCP authentication failed: {e.stderr}", file=sys.stderr)
        raise
    except Exception as e:
        logger.error(f"Unexpected error during GCP authentication: {e}")
        print(f"Unexpected error during GCP authentication: {e}", file=sys.stderr)
        raise

def get_project_id(credentials=None):
    """Get the project ID from gcloud config or environment."""
    try:
        # Try to get from gcloud config
        result = subprocess.run([
            "gcloud", "config", "get-value", "project"
        ], capture_output=True, text=True, check=True)
        
        project_id = result.stdout.strip()
        if project_id and project_id != "(unset)":
            return project_id
            
        # Try environment variable
        project_id = os.environ.get('GOOGLE_CLOUD_PROJECT') or os.environ.get('GCP_PROJECT')
        if project_id:
            return project_id
            
        print("Warning: Unable to determine project ID", file=sys.stderr)
        return None
        
    except Exception as e:
        print(f"Error getting project ID: {e}", file=sys.stderr)
        return None

def get_gcp_credential(project_id=None, service_account_key=None):
    """Obtain GCP credentials either through ADC or service account with caching."""
    
    # Generate cache key
    cache_key = _generate_gcp_cache_key(project_id, service_account_key)
    
    # Try to get cached credential
    cached_result = _get_cached_gcp_credential(cache_key)
    if cached_result:
        print(f"Using cached GCP credential")
        return cached_result
    
    if service_account_key and project_id:
        print("Creating new GCP Service Account credential (cache miss)")
        try:
            # Parse service account key to validate and extract project if needed
            sa_info = json.loads(service_account_key)
            if not project_id:
                project_id = sa_info.get('project_id')
        except json.JSONDecodeError as e:
            print(f"Failed to parse service account key: {e}", file=sys.stderr)
            return None, None
    else:
        print("Creating new GCP Application Default credential (cache miss)")
        if not project_id:
            project_id = get_project_id()
        print(f"Using Application Default Credentials")
    
    if not project_id:
        project_id = get_project_id()
    
    result = (True, project_id)  # Return success flag instead of credentials object
    
    # Cache the result
    _cache_gcp_credential(cache_key, result, GCP_CREDENTIAL_TTL)
    
    return result

GKE_OAUTH_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def generate_kubeconfig_for_gke(cluster_name, zone_or_region, project_id=None, service_account_key=None):
    """
    Generate kubeconfig for a GKE cluster with an embedded OAuth token.

    Builds the kubeconfig directly (server URL + CA cert + bearer token)
    instead of using ``gcloud container clusters get-credentials``, which
    generates a kubeconfig that depends on the ``gke-gcloud-auth-plugin``
    exec credential provider — a binary not installed in the runner image.

    This mirrors runwhen-local's ``generate_kubeconfig_for_gke`` which
    deliberately avoids the gcloud exec plugin: cluster endpoint + CA come
    from ``gcloud container clusters describe``, and the OAuth bearer token
    comes from ``google.auth.default()`` (ADC) or a service-account key.
    
    Args:
        cluster_name: Name of the GKE cluster
        zone_or_region: Zone or region where the cluster is located
        project_id: GCP project ID (optional, will be determined from credentials)
        service_account_key: Service account JSON key as string (optional)
    """
    
    try:
        # Authenticate first
        auth_success, resolved_project_id = gcloud_login(project_id, service_account_key)
        
        if not resolved_project_id:
            raise ValueError("Unable to determine project ID for GKE cluster access")
        
        # Get GKE credentials
        kubeconfig_path = os.environ.get("KUBECONFIG", "")
        if not kubeconfig_path:
            raise ValueError("KUBECONFIG environment variable not set")
        
        # Ensure directory exists (only if path has a directory component)
        kubeconfig_dir = os.path.dirname(kubeconfig_path)
        if kubeconfig_dir:
            os.makedirs(kubeconfig_dir, exist_ok=True)
        
        # Fetch cluster endpoint + CA cert via gcloud describe (avoids needing
        # google-cloud-container pip package; gcloud CLI is available).
        describe_cmd = [
            "gcloud", "container", "clusters", "describe",
            cluster_name,
            f"--project={resolved_project_id}",
            "--format=json",
        ]
        if '-' in zone_or_region and zone_or_region.count('-') >= 2:
            describe_cmd.append(f"--zone={zone_or_region}")
        else:
            describe_cmd.append(f"--region={zone_or_region}")

        describe_result = subprocess.run(
            describe_cmd, capture_output=True, text=True, check=True,
        )
        cluster_info = json.loads(describe_result.stdout)
        endpoint = cluster_info.get("endpoint")
        ca_cert = cluster_info.get("masterAuth", {}).get("clusterCaCertificate")

        if not endpoint or not ca_cert:
            raise ValueError(
                f"Cluster describe missing endpoint ({endpoint}) or CA cert ({ca_cert is not None})"
            )

        # Prepend https:// if not present (gcloud describe returns bare IP)
        server_url = endpoint if endpoint.startswith("https://") else f"https://{endpoint}"

        # Mint a short-lived OAuth bearer token to embed in the kubeconfig.
        # This is the same token gke-gcloud-auth-plugin would fetch at runtime
        # — we embed it directly so no exec plugin is needed.
        import google.auth
        import google.auth.transport.requests

        if service_account_key:
            from google.oauth2 import service_account
            info = json.loads(service_account_key)
            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=GKE_OAUTH_SCOPES
            )
        else:
            credentials, _ = google.auth.default(scopes=GKE_OAUTH_SCOPES)

        credentials.refresh(google.auth.transport.requests.Request())
        oauth_token = credentials.token

        if not oauth_token:
            raise ValueError("Failed to obtain OAuth token for GKE kubeconfig")

        # Build the kubeconfig directly — context name = cluster_name so it
        # matches what workspace-builder generates as the CONTEXT variable.
        kubeconfig = {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [{
                "name": cluster_name,
                "cluster": {
                    "server": server_url,
                    "certificate-authority-data": ca_cert,
                },
            }],
            "users": [{
                "name": f"{cluster_name}-user",
                "user": {"token": oauth_token},
            }],
            "contexts": [{
                "name": cluster_name,
                "context": {
                    "cluster": cluster_name,
                    "user": f"{cluster_name}-user",
                },
            }],
            "current-context": cluster_name,
        }

        with open(kubeconfig_path, "w") as f:
            yaml.dump(kubeconfig, f, default_flow_style=False)

        logger.info(f"Successfully generated kubeconfig for GKE cluster {cluster_name} in {zone_or_region}")
        print(f"Generated token-based kubeconfig for GKE cluster {cluster_name} (no gke-gcloud-auth-plugin required)")
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to generate kubeconfig for GKE cluster: {e}")
        print(f"Failed to generate kubeconfig for GKE cluster: {e.stderr}", file=sys.stderr)
        raise
    except Exception as e:
        logger.error(f"Unexpected error generating kubeconfig: {e}")
        print(f"Unexpected error generating kubeconfig: {e}", file=sys.stderr)
        raise

def list_gke_clusters(project_id=None, service_account_key=None):
    """List all GKE clusters in the project."""
    try:
        auth_success, resolved_project_id = get_gcp_credential(project_id, service_account_key)
        
        if not resolved_project_id:
            raise ValueError("Unable to determine project ID for listing clusters")
        
        # Use gcloud to list clusters
        result = subprocess.run([
            "gcloud", "container", "clusters", "list",
            f"--project={resolved_project_id}",
            "--format=json"
        ], capture_output=True, text=True, check=True)
        
        clusters = json.loads(result.stdout)
        return clusters
        
    except Exception as e:
        logger.error(f"Failed to list GKE clusters: {e}")
        print(f"Failed to list GKE clusters: {e}", file=sys.stderr)
        return [] 