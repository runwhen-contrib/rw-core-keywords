# rw-core-keywords

Core Robot Framework keyword libraries for the RunWhen platform.

This package provides `RW.Core` — the standard keyword library that every
RunWhen CodeCollection uses for importing secrets, pushing metrics, raising
issues, generating reports, and interacting with platform services.

## Install

**For CodeCollection development (dev mode):**

```bash
pip install rw-core-keywords
```

Installs only lightweight dependencies (`requests`, `PyYAML`, `robotframework`).
Set `RW_MODE=dev` in your environment to activate dev mode.

**For production runtime images:**

```bash
pip install "rw-core-keywords[production]"
```

Includes all cloud provider SDKs, OpenTelemetry, Vault client, and other
production dependencies.

## Runtime Modes

The package operates in two modes, **defaulting to production**:

| Mode | Activate | Use case |
|------|----------|----------|
| `production` | Default (no env var needed) | Platform runtime containers |
| `dev` | `export RW_MODE=dev` | Local CodeCollection development |

Legacy: `ROBOT_DEV=true` also activates dev mode.

## Keyword Library: `RW.Core`

Import in your `.robot` file:

```robotframework
*** Settings ***
Library    RW.Core
```

### Secrets

```robotframework
# Import a required secret
RW.Core.Import Secret    kubeconfig

# Import an optional secret (returns None if not found)
RW.Core.Import Optional Secret    slack_webhook
```

**Dev mode**: reads from env vars. Use `RW_SECRET_REMAP` to map variable names
to different env var keys, and `RW_FROM_FILE` to read values from local files:

```bash
export RW_MODE=dev
export RW_FROM_FILE='{"kubeconfig":"/home/user/auth/kubeconfig"}'
export RW_SECRET_REMAP='{"my_token":"MY_LOCAL_TOKEN_VAR"}'
```

**Production**: resolves via `fetchsecrets` from Vault, Kubernetes secrets,
Azure, GCP, or AWS providers based on `RW_SECRETS_KEYS` configuration.

### User Variables

```robotframework
RW.Core.Import User Variable    NAMESPACE
RW.Core.Import User Variable    THRESHOLD    default=80
```

**Dev mode**: reads from env vars. Use `RW_ENV_REMAP` to map names:

```bash
export RW_ENV_REMAP='{"NAMESPACE":"MY_K8S_NAMESPACE"}'
```

### Platform Variables

```robotframework
RW.Core.Import Platform Variable    RW_WORKSPACE
RW.Core.Import Platform Variable    RW_LOOKBACK_WINDOW
```

**Dev mode**: delegates to `Import User Variable` (reads from env).

### Metrics

```robotframework
RW.Core.Push Metric    ${metric_value}
RW.Core.Push Metric    ${value}    sub_name=latency_p99    metric_type=gauge
RW.Core.Run Keyword And Push Metric    My SLI Keyword    arg1    arg2
```

**Dev mode**: logs to console.
**Production**: pushes to OpenTelemetry Collector.

### Issues

```robotframework
RW.Core.Add Issue
...    severity=2
...    title=Pod CrashLooping
...    expected=Pod should be Running
...    actual=Pod in CrashLoopBackOff
...    next_steps=Check pod logs with kubectl logs
...    details=${pod_details}
```

Severity constants: `${RW_CORE_SEV_1}` through `${RW_CORE_SEV_4}`.

**Dev mode**: logs to console.
**Production**: writes to `issues.jsonl`.

### Reports

```robotframework
RW.Core.Add To Report    ${summary_text}
RW.Core.Add Pre To Report    ${raw_output}
RW.Core.Add Json To Report    ${json_data}
RW.Core.Add Table To Report    ${title}    ${body}    ${headers}
```

**Dev mode**: logs to console.
**Production**: writes to `report.jsonl`.

### Logging

```robotframework
RW.Core.Info Log     Processing ${count} items    console=True
RW.Core.Debug Log    ${detailed_data}
RW.Core.Error Log    Failed to connect: ${error}
```

### Services and Shell

```robotframework
RW.Core.Import Service    kubectl_service
${result}=    RW.Core.Shell    kubectl get pods    service=${kubectl_service}
```

### Session Files

```robotframework
RW.Core.Upload Session File    results.json    ${json_contents}
${data}=    RW.Core.Get Session File    results.json
```

**Dev mode**: no-op (returns None).

### Memo Variables (Runbooks)

```robotframework
${memo_value}=    RW.Core.Import Memo Variable    user_input
```

**Dev mode**: reads from files via `RW_MEMO_FILE`:

```bash
export RW_MEMO_FILE='{"user_input":"/tmp/memo_input.txt"}'
```

### Utility

```robotframework
${window}=    RW.Core.Normalize Lookback Window    seconds=3600    format_type=2
# Returns "60m"
```

## Module Reference

| Module | Purpose |
|--------|---------|
| `RW.Core` | Robot keyword library (primary public API) |
| `RW.platform` | Python API: `Secret`, `Service`, auth, logging helpers |
| `RW.fetchsecrets` | Secret resolution from all providers (production) |
| `RW.fetchfiles` | Session file upload/download (production) |
| `RW.aws_utils` | AWS credential handling and EKS kubeconfig |
| `RW.azure_utils` | Azure credential handling and AKS kubeconfig |
| `RW.gcp_utils` | GCP credential handling and GKE kubeconfig |
| `RW.proxy` | SSL/TLS verification |
| `RW._mode` | Runtime mode detection (`is_dev_mode()`, `is_production_mode()`) |

## Keyword Reference

Full auto-generated keyword documentation for all libraries:
[docs/keywords.md](docs/keywords.md)

This is regenerated on every push to `main` by the `keyword-docs.yml` workflow.

## Development

```bash
git clone https://github.com/runwhen-contrib/rw-core-keywords
cd rw-core-keywords
pip install -e ".[dev]"
RW_MODE=dev pytest tests/
```

See `AGENTS.md` for AI coding guidelines and architectural decisions.
