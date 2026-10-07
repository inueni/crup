"""Measure installed crup wheels on a native runner, optionally against a baseline."""
import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import timeit
from pathlib import Path


def worker(check_only):
    gil_enabled = getattr(sys, "_is_gil_enabled", lambda: True)
    before = gil_enabled()
    import crup
    from workloads import (
        bench_crup,
        bench_crup_mutable,
        bench_crup_parse,
        bench_domain_crup,
        load_urls,
    )
    assert gil_enabled() == before
    assert Path(sys.prefix).resolve() in Path(crup.__file__).resolve().parents
    assert Path(crup.psl.get_psl_path()).resolve() == Path(os.environ["CRUP_PSL_PATH"]).resolve()
    urls = load_urls()

    if check_only:
        checks = {}

        for name, factory in (("immutable", crup.parse), ("mutable", crup.URL.parse)):
            digest = hashlib.sha256()
            rejected = 0

            for text in urls:
                try:
                    parsed = factory(text)

                except ValueError:
                    value = "rejected"
                    rejected += 1

                else:
                    info = parsed.domain_info()
                    assert parsed.domain == (info.domain if info else None)
                    value = (parsed.href, parsed.scheme, parsed.hostname, parsed.port,
                             parsed.username, parsed.password, parsed.path, parsed.query,
                             parsed.fragment, parsed.domain,
                             (info.domain, info.suffix, str(info.psl)) if info else None)

                digest.update(json.dumps(value, separators=(",", ":")).encode())

            checks[name] = {"sha256": digest.hexdigest(), "rejected": rejected}

        return {"checks": checks, "inputs": len(urls), "python": sys.version,
                "version": importlib.metadata.version("crup"), "module": crup.__file__,
                "gil_enabled": gil_enabled()}

    times = {}

    for name, function in (("Parse only", bench_crup_parse),
                           ("Parse + components", bench_crup),
                           ("Mutable parse + components", bench_crup_mutable),
                           ("Parse + domain", bench_domain_crup)):
        function(urls)
        gc.collect()
        times[name] = timeit.timeit(lambda function=function: function(urls), number=1)

    return times


def run(args):
    report = {
        "platform": platform.platform(), "architecture": platform.machine(),
        "processor": platform.processor(), "cpu_count": os.cpu_count(),
        "runner": os.environ.get("RUNNER_NAME"),
        "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
        "maturin": importlib.metadata.version("maturin"),
        "corpus_sha256": hashlib.sha256(Path(__file__).with_name("data.txt").read_bytes()).hexdigest(),
        "psl_sha256": hashlib.sha256(args.psl.read_bytes()).hexdigest(),
        "samples_per_pass": args.samples, "passes": args.passes, "variants": {},
        "measurement_order": [],
    }
    wheels = {"candidate": (args.candidate, args.candidate_sha)}

    if args.baseline:
        wheels["baseline"] = (args.baseline, args.baseline_sha)

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONUTF8"] = "1"
    environment["CRUP_PSL_PATH"] = str(args.psl.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="crup-benchmark-") as directory:
        interpreters = {}

        for name, (wheel, revision) in wheels.items():
            target = Path(directory) / name
            subprocess.run([sys.executable, "-m", "venv", str(target)], check=True)
            python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            subprocess.run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", "--no-cache-dir",
                            str(wheel.resolve())], check=True, env=environment)
            command = [str(python), "-W", "error::RuntimeWarning", str(Path(__file__).resolve()), "--worker"]
            interpreters[name] = command
            result = subprocess.check_output(command + ["--check-only"], env=environment,
                                             cwd=directory, text=True, timeout=120)
            report["variants"][name] = {
                **json.loads(result), "revision": revision,
                "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "wheel": wheel.name, "samples": [],
            }

        if args.baseline:
            candidate = report["variants"]["candidate"]
            baseline = report["variants"]["baseline"]

            if candidate["checks"] != baseline["checks"] or candidate["inputs"] != baseline["inputs"]:
                args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                raise ValueError("baseline/candidate URL or domain results differ; see the JSON checks")

        for pass_index in range(args.passes):
            orders = []

            for name in wheels:
                report["variants"][name]["samples"].append([])

            for sample in range(args.samples):
                order = list(wheels)

                if (pass_index * args.samples + sample) % 2:
                    order.reverse()

                orders.append(order)

                for name in order:
                    result = subprocess.check_output(interpreters[name], env=environment,
                                                     cwd=directory, text=True, timeout=120)
                    report["variants"][name]["samples"][pass_index].append(json.loads(result))

            report["measurement_order"].append(orders)
            print(f"Pass {pass_index + 1}/{args.passes} complete", flush=True)

    write_report(report, args.output)


def write_report(report, output_path):
    summary = {}
    variants = report["variants"]
    lines = ["## crup native benchmark", "",
             f"{report['platform']} ({report['architecture']}); {report['passes']} passes × {report['samples_per_pass']} samples.", ""]

    for name, variant in variants.items():
        lines.append(f"- {name}: `{variant['revision']}`; crup {variant['version']}; {variant['python'].splitlines()[0]}")

    lines += ["", "Median times cover the complete corpus. Negative changes mean less time.", "",
              "| Workload | Candidate | Baseline | Change |", "| --- | ---: | ---: | ---: |"]

    for case in variants["candidate"]["samples"][0][0]:
        row = {}

        for name, variant in variants.items():
            passes = [[sample[case] for sample in samples] for samples in variant["samples"]]
            values = [value for samples in passes for value in samples]
            row[name] = {"min": min(values), "max": max(values), "mean": statistics.mean(values),
                         "median": statistics.median(values),
                         "pass_medians": [statistics.median(samples) for samples in passes]}

        baseline_time, change = "—", "—"

        if "baseline" in variants:
            row["change_pct"] = (row["candidate"]["median"] / row["baseline"]["median"] - 1) * 100
            row["pass_changes_pct"] = [(candidate / baseline - 1) * 100 for candidate, baseline in
                                       zip(row["candidate"]["pass_medians"], row["baseline"]["pass_medians"])]
            baseline_time = f"{row['baseline']['median'] * 1000:.3f} ms"
            change = f"{row['change_pct']:+.2f}%"

        summary[case] = row
        lines.append(f"| {case} | {row['candidate']['median'] * 1000:.3f} ms | {baseline_time} | {change} |")

    report["summary"] = summary
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines += ["", "Hosted runner timings vary. Repeat comparisons before interpreting small changes.", ""]
    markdown = "\n".join(lines)
    output_path.with_suffix(".md").write_text(markdown, encoding="utf-8")

    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
            output.write(markdown)

    print(markdown)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--candidate-sha")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-sha")
    parser.add_argument("--psl", type=Path)
    parser.add_argument("--output", type=Path, default=Path("benchmark-results.json"))
    parser.add_argument("--samples", type=int, default=31)
    parser.add_argument("--passes", type=int, default=2)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--check-only", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker:
        print(json.dumps(worker(args.check_only)))

    else:
        if args.candidate is None or args.psl is None or args.samples < 1 or args.passes < 1:
            parser.error("--candidate and --psl are required; --samples and --passes must be positive")

        run(args)
