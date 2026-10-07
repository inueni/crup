"""Manual PSL refreshes save validated downloads and matching metadata."""
import io
import json

import pytest

from scripts import update_psl


def list_bytes(version="2026-10-06_00-00-00_UTC"):
    return f"""// VERSION: {version}
// COMMIT: {'a' * 40}
// ===BEGIN ICANN DOMAINS===
com
co.uk
// ===END ICANN DOMAINS===
// ===BEGIN PRIVATE DOMAINS===
github.io
// ===END PRIVATE DOMAINS===
""".encode()


@pytest.fixture
def project(tmp_path):
    output = tmp_path / "python/crup"
    output.mkdir(parents=True)
    data = list_bytes()
    (output / update_psl.FILENAME).write_bytes(data)
    (output / update_psl.METADATA_FILENAME).write_text(json.dumps(update_psl.describe(data)))

    return tmp_path


def test_manual_refresh_writes_download_and_matching_metadata(project, monkeypatch):
    # An explicit refresh also saves header-only changes and original line endings.
    response = list_bytes("new-date").replace(b"\n", b"\r\n")
    monkeypatch.setattr(update_psl, "urlopen", lambda *a, **kw: io.BytesIO(response))
    update_psl.update(project)
    output = project / "python/crup"
    assert (output / update_psl.FILENAME).read_bytes() == response
    metadata = json.loads((output / update_psl.METADATA_FILENAME).read_text())
    update_psl.verify_snapshot(response, metadata)
    assert metadata["version"] == "new-date"
    assert metadata["downloaded_at"]


@pytest.mark.parametrize("response", [
    b"<html>unavailable</html>",
    list_bytes().split(b"// ===END PRIVATE")[0],
    None,
    list_bytes().replace(b"com\nco.uk\n", b"// no ICANN rules\n"),
    list_bytes().replace(b"github.io\n", b"// no PRIVATE rules\n"),
    list_bytes().replace(b"co.uk", b"co uk"),
    list_bytes().replace(b"// ===BEGIN ICANN DOMAINS===", b"// ===BEGIN ICANN DOMAINS===\n" * 2),
    list_bytes().replace(b"ICANN", b"TEMP").replace(b"PRIVATE", b"ICANN").replace(b"TEMP", b"PRIVATE"),
], ids=["html", "truncated", "timeout", "empty-icann", "empty-private", "malformed-rule",
        "duplicate-marker", "reordered-sections"])
def test_failed_download_preserves_snapshot(project, monkeypatch, response):
    before = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}

    def download(*args, **kwargs):
        if response is None:
            raise TimeoutError("download timed out")

        return io.BytesIO(response)

    monkeypatch.setattr(update_psl, "urlopen", download)

    with pytest.raises((OSError, ValueError)):
        update_psl.update(project)

    assert all(p.read_bytes() == original for p, original in before.items())

