"""PSL configuration is isolated in subprocesses; updates use a local proxy."""
import os
import socket
import threading
from pathlib import Path

import crup
import pytest

PSL_FIXTURE = Path(__file__).parent / "data" / "psl.dat"


@pytest.mark.parametrize("source", ["override", "missing", "invalid"])
def test_psl_loading_and_writable_path(source, tmp_path, run_python):
    # Test undecodable paths without creating them: macOS rejects those filenames.
    filename = os.fsdecode(b"psl-\xff.dat") if os.name == "posix" and source == "missing" else "psl-é.dat"
    path = tmp_path / filename

    if source == "override":
        path.write_bytes(PSL_FIXTURE.read_bytes())

    elif source == "invalid":
        path.write_text("not a valid list")

    result = run_python("""
        import os, warnings
        from pathlib import Path

        with warnings.catch_warnings(record=True) as warnings_seen:
            warnings.simplefilter("always")
            import crup

        source = os.environ["CRUP_TEST_SOURCE"]
        assert crup.psl.get_psl_path() == Path(os.environ["CRUP_PSL_PATH"])

        if source == "override":
            assert crup.parse("https://www.example.co.test").domain == "example.co.test"

        else:
            assert crup.parse("https://www.example.co.uk").domain == "example.co.uk"

        if source == "invalid":
            assert len(warnings_seen) == 1
            assert issubclass(warnings_seen[0].category, UserWarning)
            assert "PSL" in str(warnings_seen[0].message)

        else:
            assert not warnings_seen
    """, env={"CRUP_PSL_PATH": str(path), "CRUP_TEST_SOURCE": source})
    assert not result.stderr


def test_update_argument_validation():
    for timeout in (0, -1, float("nan"), float("inf"), 1e100, 1e-100):
        with pytest.raises(ValueError, match="timeout"):
            crup.psl.update(timeout=timeout)

    with pytest.raises(TypeError):
        crup.psl.update(1)

    with pytest.raises(TypeError):
        crup.psl.update(timeout="invalid")


def test_update_timeout_releases_gil_and_preserves_cache(tmp_path, run_python):
    psl_file = tmp_path / "psl.dat"
    original = "// ===BEGIN ICANN DOMAINS===\ninvalid\nco.invalid\n"
    psl_file.write_text(original)
    requests = []

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)

        def stall_proxy():
            with listener.accept()[0] as connection:
                connection.settimeout(5)
                request = b""

                while b"\r\n\r\n" not in request:
                    chunk = connection.recv(4096)

                    if not chunk:
                        break

                    request += chunk

                requests.append(request)
                # No CONNECT response: the download must stop at its deadline.
                threading.Event().wait(1)

        server = threading.Thread(target=stall_proxy)
        server.start()
        proxy = "http://127.0.0.1:" + str(listener.getsockname()[1])
        env = {
            name: proxy for name in (
                "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"
            )
        }
        env.update(CRUP_PSL_PATH=str(psl_file), NO_PROXY="", no_proxy="")

        try:
            run_python("""
                import crup, threading, time
                ticks = []
                stop = threading.Event()
                def worker():
                    while not stop.wait(0.01):
                        ticks.append(time.monotonic())

                thread = threading.Thread(target=worker)
                thread.start()
                start = time.monotonic()

                try:
                    crup.psl.update(timeout=0.4)

                except OSError as error:
                    assert "timeout" in str(error).lower(), str(error)

                else:
                    raise AssertionError("stalled download should time out")

                finally:
                    end = time.monotonic()
                    stop.set()
                    thread.join()

                assert end - start < 3
                assert any(start + 0.05 < tick < end - 0.05 for tick in ticks)
                assert crup.parse("https://www.example.co.invalid").domain == "example.co.invalid"
            """, env=env)

        finally:
            server.join(timeout=6)

    assert requests and requests[0].startswith(b"CONNECT publicsuffix.org:443")
    assert psl_file.read_text() == original


def test_live_update_with_concurrent_readers(tmp_path, run_python, request):
    if request.config.getoption("--offline"):
        pytest.skip("live PSL download disabled by --offline")

    path = tmp_path / "psl.dat"
    path.write_text("// ===BEGIN ICANN DOMAINS===\ninvalid\nco.invalid\n")
    before = path.read_bytes()
    run_python(script=Path(__file__).with_name("threading_cases.py"),
               args=["update"], env={"CRUP_PSL_PATH": str(path)})
    assert path.read_bytes() != before
    assert not list(tmp_path.glob(".tmp*"))
