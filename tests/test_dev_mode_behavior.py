import importlib
import sys

import pytest


def _reload_dev_modules(monkeypatch):
    monkeypatch.setenv("RW_MODE", "dev")

    for module_name in ["RW.Core", "RW.platform", "RW._mode"]:
        sys.modules.pop(module_name, None)

    mode_mod = importlib.import_module("RW._mode")
    importlib.reload(mode_mod)
    platform_mod = importlib.import_module("RW.platform")
    importlib.reload(platform_mod)
    core_mod = importlib.import_module("RW.Core")
    importlib.reload(core_mod)

    return core_mod, platform_mod


class _DummyBuiltIn:
    def __init__(self):
        self.variables = {}

    def set_suite_variable(self, name, value):
        self.variables[name] = value


def test_core_init_does_not_crash_in_dev_mode(monkeypatch):
    core_mod, _ = _reload_dev_modules(monkeypatch)
    monkeypatch.setattr(core_mod, "BuiltIn", _DummyBuiltIn)

    core = core_mod.Core()

    assert core.otel_enabled is False


def test_import_secret_dev_required_missing_raises_importerror(monkeypatch):
    core_mod, _ = _reload_dev_modules(monkeypatch)
    monkeypatch.setattr(core_mod, "BuiltIn", _DummyBuiltIn)
    monkeypatch.delenv("MISSING_REQUIRED_SECRET", raising=False)
    monkeypatch.setenv("RW_SECRET_REMAP", "{}")
    monkeypatch.setenv("RW_FROM_FILE", "{}")

    core = core_mod.Core()

    with pytest.raises(ImportError):
        core.import_secret("MISSING_REQUIRED_SECRET", optional=False)


def test_import_memo_variable_missing_key_returns_none_in_dev(monkeypatch):
    _, platform_mod = _reload_dev_modules(monkeypatch)
    monkeypatch.setenv("RW_MEMO_FILE", "{}")

    assert platform_mod.import_memo_variable("missing_key") is None
