# fetchsecrets.py — AI Coding Guidelines

## Provider key format

All secret keys in `RW_SECRETS_KEYS` follow the pattern `<provider>@<resource-path>`.
The `@` symbol (`SECRET_PROVIDER_SYMBOL`) splits provider from path. Keys without `@`
default to RunWhen vault.

## K8s secret providers (`k8s:file`, `k8s:env`)

Both providers resolve secrets via direct Kubernetes API calls (not volume mounts or
`EnvVarSource`). The path format supports four variants:

- `secret/<name>:<key>`
- `configmap/<name>:<key>`
- `<namespace>/secret/<name>:<key>`
- `<namespace>/configmap/<name>:<key>`

Secrets are base64-decoded; ConfigMaps are returned raw.

## Caching

K8s resources are cached on the filesystem at `$TMPDIR/shared_config/.k8s_secrets/`
with a TTL of 1 hour (configurable via `RW_K8S_SECRET_CACHE_TTL`). Cache keys are
filesystem-safe hashes of `namespace/kind/name/key`.

The cache is shared across executions in the same worker pod. This is separate from
the per-secret cache in `read_secret()` which caches resolved values in memory for a
single robot execution.

## Kubeconfig handling

When a K8s secret key contains "kubeconfig", the resolved data is written to the
execution-specific `KUBECONFIG` path (set by `runrobot.py`) and the Robot Framework
suite variable `${KUBECONFIG}` is updated. This supports multiple kubeconfigs per
worker since each execution gets its own file path.

## Adding new providers

When adding a new secret provider:

1. Add an enum value to `SecretProvider`.
2. Add provider prefix detection in the `if/elif` chain in `read_secret()`.
3. Add the handler logic in the corresponding `elif _current_secret_provider == ...` block.
4. Add the provider prefix to the known-provider list in `runrobot.py`'s
   `_generate_credential_context_hash()` to prevent misclassification as custom vault.
