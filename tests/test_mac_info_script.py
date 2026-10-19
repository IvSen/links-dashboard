import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "mac" / "links-dashboard-mac-info"
REQUIRED_KEYS = {"hosts", "sync", "forward", "branches", "errors", "generated_at"}


@pytest.mark.skipif(sys.platform != "darwin", reason="Mac-only script")
def test_script_outputs_valid_json():
    result = subprocess.run(
        ["/usr/bin/python3", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert REQUIRED_KEYS <= payload.keys()
    assert "/Users/i.senishin/project/carbox/rosfines-dev" in payload["branches"]
