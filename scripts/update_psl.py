"""Download and validate the checked-in PSL snapshot and its metadata."""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE_URL = "https://publicsuffix.org/list/public_suffix_list.dat"
FILENAME = "public_suffix_list.dat"
METADATA_FILENAME = "psl_snapshot.json"
ROOT = Path(__file__).resolve().parents[1]


def describe(data):
    text = data.decode("utf-8").replace("\r\n", "\n")
    version = re.search(r"^// VERSION: (\S+)$", text, re.MULTILINE)
    commit = re.search(r"^// COMMIT: ([0-9a-f]{40})$", text, re.MULTILINE)

    if not version or not commit:
        raise ValueError("PSL headers are missing or invalid")

    markers = [f"// ==={edge} {section} DOMAINS==="
               for section in ("ICANN", "PRIVATE") for edge in ("BEGIN", "END")]

    if any(text.count(marker) != 1 for marker in markers):
        raise ValueError("PSL section markers are missing or invalid")

    positions = [text.index(marker) for marker in markers]

    if positions != sorted(positions):
        raise ValueError("PSL sections are out of order")

    for begin, end in ((0, 1), (2, 3)):
        rules = [line.strip() for line in text[positions[begin]:positions[end]].splitlines()
                 if line.strip() and not line.strip().startswith("//")]

        if not rules or any(any(char.isspace() for char in rule) for rule in rules):
            raise ValueError("PSL section is empty or has malformed rules")

    return {"source": SOURCE_URL, "version": version.group(1),
            "commit": commit.group(1), "sha256": hashlib.sha256(data).hexdigest()}


def verify_snapshot(data, metadata):
    if any(metadata.get(key) != value for key, value in describe(data).items()):
        raise ValueError("PSL snapshot metadata does not match the list")


def update(project_dir):
    request = Request(SOURCE_URL, headers={"User-Agent": "crup-psl-update"})

    with urlopen(request, timeout=30) as response:
        data = response.read(2_000_001)

    if len(data) > 2_000_000:
        raise ValueError("PSL download exceeds 2 MB")

    metadata = describe(data)

    metadata["downloaded_at"] = datetime.now(timezone.utc).isoformat()
    encoded_metadata = (json.dumps(metadata, indent=2) + "\n").encode("utf-8")
    output_dir = project_dir / "python/crup"
    (output_dir / FILENAME).write_bytes(data)
    (output_dir / METADATA_FILENAME).write_bytes(encoded_metadata)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, default=ROOT)
    args = parser.parse_args()

    try:
        update(args.project_dir)

    except (OSError, ValueError) as error:
        parser.exit(1, f"PSL update failed: {error}\n")

    print("Updated PSL")
