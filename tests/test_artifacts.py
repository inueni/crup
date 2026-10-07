"""Run against installed artifacts in CI, and the editable package locally."""

def test_package_outside_checkout(tmp_path, run_python):
    run_python("""
        import hashlib, json, os, sys
        from importlib.resources import files
        from pathlib import Path
        gil_enabled = getattr(sys, "_is_gil_enabled", lambda: True)
        before = gil_enabled()
        import crup
        from crup.psl import PslType
        assert gil_enabled() == before
        assert PslType is crup.PslType

        if os.environ.get("CRUP_REQUIRE_INSTALLED") == "1":
            assert Path(sys.prefix).resolve() in Path(crup.__file__).resolve().parents

        package = files("crup")

        for filename in ("public_suffix_list.dat", "psl_snapshot.json", "__init__.pyi", "psl.pyi", "py.typed"):
            assert package.joinpath(filename).is_file(), filename

        snapshot = json.loads(package.joinpath("psl_snapshot.json").read_text())
        assert snapshot["sha256"] == hashlib.sha256(package.joinpath("public_suffix_list.dat").read_bytes()).hexdigest()
        # No user cache: prove that the package's bundled PSL is usable.
        assert not crup.psl.get_psl_path().exists()

        for factory in (crup.parse, crup.URL.parse):
            parsed = factory("https://www.example.co.uk/path?a=1")
            assert parsed.domain == "example.co.uk"
            assert parsed.domain_info().suffix == "co.uk"
            assert parsed.query_params() == {"a": "1"}
    """, env={"CRUP_PSL_PATH": str(tmp_path / "missing" / "psl.dat")})
