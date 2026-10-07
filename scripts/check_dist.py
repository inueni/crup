"""Check release archive contents before installation or upload."""
import argparse
import json
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

from update_psl import verify_snapshot

PACKAGE_FILES = {
    "__init__.py", "__init__.pyi", "psl.pyi", "py.typed",
    "public_suffix_list.dat", "psl_snapshot.json",
}


def check(path, expected_version, expected_psl=None):
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            metadata_name, = [n for n in names if n.endswith(".dist-info/METADATA")]
            metadata = BytesParser().parsebytes(archive.read(metadata_name))
            psl = archive.read("crup/public_suffix_list.dat")
            snapshot = json.loads(archive.read("crup/psl_snapshot.json"))

        required = {f"crup/{name}" for name in PACKAGE_FILES}
        required.add(metadata_name.replace("METADATA", "licenses/LICENSE"))
        extensions = [n for n in names if n.startswith("crup/_crup.")
                      and n.endswith((".so", ".pyd"))]

        if len(extensions) != 1:
            raise ValueError(f"expected one native extension, found {extensions}")

    else:
        with tarfile.open(path) as archive:
            members = [m for m in archive.getmembers() if m.isfile()]
            roots = {m.name.split("/", 1)[0] for m in members}

            if len(roots) != 1:
                raise ValueError(f"expected one sdist root, found {roots}")

            root, = roots
            names = {m.name.removeprefix(root + "/") for m in members}
            metadata = BytesParser().parsebytes(archive.extractfile(f"{root}/PKG-INFO").read())
            psl = archive.extractfile(f"{root}/python/crup/public_suffix_list.dat").read()
            snapshot = json.loads(archive.extractfile(f"{root}/python/crup/psl_snapshot.json").read())

        required = {f"python/crup/{name}" for name in PACKAGE_FILES}
        required.update({"Cargo.toml", "Cargo.lock", "pyproject.toml", "build.rs",
                         ".cargo/config.toml", "rust-toolchain.toml", "LICENSE"})

    missing = required - names
    unwanted = {n for n in names if n.startswith(("benchmark/", "assets/", ".github/"))
                or n in {"SPEC.md", "uv.lock"}
                or "__pycache__" in Path(n).parts}

    if missing or unwanted:
        raise ValueError(f"missing files: {sorted(missing)}; unwanted files: {sorted(unwanted)}")

    if metadata["Name"] != "crup" or metadata["Requires-Python"] != ">=3.10":
        raise ValueError("unexpected package name or Python requirement")

    if expected_version is not None and metadata["Version"] != expected_version:
        raise ValueError(f"version {metadata['Version']} does not match tag v{expected_version}")

    verify_snapshot(psl, snapshot)

    if expected_psl is not None and snapshot != expected_psl:
        raise ValueError("bundled PSL differs from the repository snapshot")

    print(f"OK: {path.name} ({len(names)} files, crup {metadata['Version']})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--tag", help="release tag, e.g. v0.1.0")
    parser.add_argument("--psl-metadata", type=Path, help="expected repository PSL snapshot metadata")
    args = parser.parse_args()
    expected_psl = json.loads(args.psl_metadata.read_text()) if args.psl_metadata else None

    for path in args.archives:
        check(path, args.tag.removeprefix("v") if args.tag else None, expected_psl)
