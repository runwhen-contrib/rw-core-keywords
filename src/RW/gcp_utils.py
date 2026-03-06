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
            
            result = subprocess.run([
                "gcloud", "auth", "application-default", "login", "--no-launch-browser"
            ], capture_output=True, text=True, check=True)
            
            # Get project ID from gcloud if not provided
            if not project_id:
                project_id = get_project_id(None)
        
        # Print the captured output and error logs
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

def generate_kubeconfig_for_gke(cluster_name, zone_or_region, project_id=None, service_account_key=None):
    """
    Generate kubeconfig for GKE cluster using gcloud get-credentials.
    
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
        
        # Use gcloud to get cluster credentials
        cmd = [
            "gcloud", "container", "clusters", "get-credentials",
            cluster_name,
            f"--project={resolved_project_id}"
        ]
        
        # Determine if it's a zone or region
        if '-' in zone_or_region and zone_or_region.count('-') >= 2:
            # Looks like a zone (e.g., us-central1-a)
            cmd.extend([f"--zone={zone_or_region}"])
        else:
            # Looks like a region (e.g., us-central1)
            cmd.extend([f"--region={zone_or_region}"])
        
        # Set KUBECONFIG for this command
        env = os.environ.copy()
        env['KUBECONFIG'] = kubeconfig_path
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        
        print("GKE kubeconfig generation output:", result.stdout)
        if result.stderr:
            print("GKE kubeconfig generation stderr:", result.stderr)
        
        logger.info(f"Successfully generated kubeconfig for GKE cluster {cluster_name} in {zone_or_region}")
        
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