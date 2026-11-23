"""Import-surface guards for RW.Core."""

import os
import subprocess
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def test_core_has_no_prometheus_client():
    # Metrics are exported over OTLP; the Prometheus client was dead weight.
    # Run in a fresh interpreter (production mode) so modules imported by
    # other tests cannot leak into sys.modules.
    env = {k: v for k, v in os.environ.items() if k not in ("RW_MODE", "ROBOT_DEV")}
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "import sys, RW.Core\n"
        "from RW._mode import is_dev_mode\n"
        "assert not is_dev_mode(), 'expected production mode'\n"
        "print('prometheus_client' in sys.modules)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False", out.stdout + out.stderr
