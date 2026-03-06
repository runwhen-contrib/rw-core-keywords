# rw-core-keywords — AI Coding Guidelines

## Package Overview

This is the single pip-installable package for all RunWhen core Robot Framework
keyword libraries. It provides `RW.Core` and supporting modules used by every
CodeCollection. It supports two runtime modes: **production** (default) and
**dev** (for local CodeCollection development).

## Architecture

### Namespace Package

`RW` is a **namespace package** (`pkgutil.extend_path`). This allows
CodeCollection keyword libraries (`RW.HTTP`, `RW.Report`, `RW.K8s`, `RW.CLI`,
etc.) to coexist alongside this package on `PYTHONPATH`. Never convert `RW` to a
regular package — the `__init__.py` must contain only the `extend_path` line.

### Runtime Modes

Mode is detected once at import time in `_mode.py`:

1. `RW_MODE=dev` or `RW_MODE=production` — explicit
2. `ROBOT_DEV=true` — legacy, implies dev
3. Default → **production**

**Production** is always the default. Dev mode must be explicitly opted into by
the CodeCollection developer. Never change this default.

In dev mode, heavy modules (`fetchsecrets`, `fetchfiles`, `aws_utils`,
`azure_utils`, `gcp_utils`, OTEL, prometheus) are **not imported**. This keeps
the dev install lightweight — only `requests`, `PyYAML`, and `robotframework` are
required.

### Module Responsibilities

| Module | Purpose | Dev mode |
|--------|---------|----------|
| `Core.py` | Robot keyword library — the public API for codebundles | Mode-branched |
| `platform.py` | Shared Python APIs (Secret, Service, auth, logging) | Mode-branched |
| `_mode.py` | Runtime mode detection | Always loaded |
| `proxy.py` | SSL/TLS verification for requests | Always loaded |
| `fetchsecrets.py` | Secret resolution (vault, k8s, cloud providers) | Production only |
| `fetchfiles.py` | Session file upload/download via SLX API | Production only |
| `aws_utils.py` | AWS credential handling and EKS kubeconfig | Production only |
| `azure_utils.py` | Azure credential handling and AKS kubeconfig | Production only |
| `gcp_utils.py` | GCP credential handling and GKE kubeconfig | Production only |
| `Platypus.py` | Legacy/experimental keywords (likely to be removed) | Production only |

### Dependencies

Base dependencies (all modes): `PyYAML`, `requests`, `robotframework`.

All dependencies are installed by default (`pip install rw-core-keywords`): azure, k8s,
opentelemetry, hvac, prometheus-client, backoff, PyGithub.

When adding a new dependency, decide whether it's needed in dev mode. If not,
add it to `[project.optional-dependencies] production` only.

## Key Conventions

### Adding Robot Keywords

All public Robot keywords live in `Core.py` inside the `Core` class. When adding
a keyword that behaves differently in dev vs production:

1. Add `if is_dev_mode():` early return with the dev behavior
2. Keep the production path as the fall-through (no else needed)
3. Dev behavior should use env vars, local files, or console logging
4. Production behavior uses platform APIs, fetchsecrets, OTEL, jsonl files

### Secret Handling (fetchsecrets.py)

See `src/RW/AGENTS.md` for detailed fetchsecrets guidelines. Key points:

- Provider key format: `<provider>@<resource-path>` (keys without `@` → vault)
- All resolution happens in `fetchsecrets.py` — the Go worker is a passthrough
- K8s secrets use direct API calls, not volume mounts
- Kubeconfig values are written to execution-specific paths
- Per-execution in-memory cache + shared filesystem cache with TTL

### Dev Mode Environment Variables

These env vars only apply in dev mode:

| Variable | Purpose |
|----------|---------|
| `RW_MODE=dev` | Enable dev mode |
| `RW_SECRET_REMAP` | JSON mapping variable names → env var keys |
| `RW_FROM_FILE` | JSON mapping keys → file paths for secret values |
| `RW_ENV_REMAP` | JSON mapping variable names → env var keys for user vars |
| `RW_MEMO_FILE` | JSON mapping memo keys → file paths |
| `RW_ACCESS_TOKEN` | Bearer token for platform API auth |
| `RW_SVC_URLS` | JSON mapping service names → URLs |

### Versioning

Date-based versioning (`YYYY.MM.DD.N`) via CI. The `VERSION` file is a local
fallback for editable installs; CI always overwrites it at build time.

## Testing

Tests are in the `tests/` directory. Run with:

```
pip install -e ".[dev]"
pytest tests/
```

Many tests require mocked platform services or specific env vars. Check each
test file's docstring or setup for prerequisites.

## What NOT to Do

- Do not add an `__init__.py` to `RW/` that does anything other than
  `extend_path` — it will break namespace package merging
- Do not import `fetchsecrets` or `fetchfiles` at module level in files that
  are loaded in dev mode — guard with `if not is_dev_mode()`
- Do not make production the non-default mode
- Do not add secrets handling logic to any repo other than this one
  (see `platform-robot-runtime/AGENTS.md`)
