import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PSL_FIXTURE = Path(__file__).parent / "data" / "psl.dat"


def pytest_addoption(parser):
    parser.addoption("--offline", action="store_true", default=False,
                     help="skip the live PSL download integration test")


def pytest_configure(config):
    # PSL configuration is process-global and read when the extension is imported.
    config.crup_previous_psl = os.environ.get("CRUP_PSL_PATH")
    os.environ["CRUP_PSL_PATH"] = str(PSL_FIXTURE)


def pytest_unconfigure(config):
    previous = config.crup_previous_psl

    if previous is None:
        os.environ.pop("CRUP_PSL_PATH", None)

    else:
        os.environ["CRUP_PSL_PATH"] = previous


@pytest.fixture(params=["immutable", "mutable"])
def factory(request):
    import crup

    return crup.parse if request.param == "immutable" else crup.URL.parse


@pytest.fixture
def run_python(tmp_path):
    """Isolate process-global PSL state and contain native crashes/deadlocks."""
    def run(code=None, *, script=None, args=(), env=None, timeout=45):
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.update(env or {})
        command = [sys.executable, "-W", "error::RuntimeWarning"]

        if script is None:
            command += ["-c", textwrap.dedent(code)]

        else:
            command += [str(script), *args]

        result = subprocess.run(command, cwd=tmp_path, env=environment,
                                capture_output=True, text=True, timeout=timeout, check=False)
        assert result.returncode == 0, result.stdout + result.stderr

        return result

    return run
