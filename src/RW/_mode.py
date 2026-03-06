"""
Runtime mode detection for rw-core-keywords.

Supports two modes:
  - "dev"        — local development; secrets from env/files, reports to console
  - "production" — platform runtime; fetchsecrets, OTEL metrics, report.jsonl

Detection order:
  1. RW_MODE env var (explicit: "dev" or "production")
  2. ROBOT_DEV=true legacy flag → dev mode
  3. Default → production
"""

import os

_DEV = "dev"
_PRODUCTION = "production"


def _detect_mode() -> str:
    explicit = os.getenv("RW_MODE", "").strip().lower()
    if explicit in (_DEV, _PRODUCTION):
        return explicit
    if os.getenv("ROBOT_DEV", "").strip().lower() == "true":
        return _DEV
    return _PRODUCTION


_MODE = _detect_mode()


def is_dev_mode() -> bool:
    return _MODE == _DEV


def is_production_mode() -> bool:
    return _MODE == _PRODUCTION


def get_mode() -> str:
    """Returns 'dev' or 'production'."""
    return _MODE
