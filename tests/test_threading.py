"""Native concurrency runs in children so crashes and hangs have a timeout."""
from pathlib import Path

import pytest


@pytest.mark.parametrize("case", ["independent", "shared", "handoff", "locked", "unlocked"])
def test_native_threading(case, run_python):
    result = run_python(script=Path(__file__).with_name("threading_cases.py"), args=[case])
    assert f'"case": "{case}"' in result.stdout
