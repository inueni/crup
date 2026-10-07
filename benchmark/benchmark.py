# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "ada_url",
#     "can_ada",
#     "chardet",
#     "crup",
#     "pydomainextractor",
#     "pyfaup",
#     "rich",
#     "tldextract",
#     "yarl",
# ]
# ///
# type: ignore
# The corpus includes invalid inputs; ValueError is an expected rejection.
# Attribute reads are part of the measured workload; keep them unassigned.
# ruff: noqa: B018

import statistics
import timeit
from urllib.parse import urlparse

import ada_url
import can_ada
import pydomainextractor
import tldextract
import yarl
from pyfaup.faup import Faup
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text
from workloads import bench_crup, bench_crup_mutable, bench_domain_crup, load_urls


def bench_urlparse(urls):
    for url in urls:
        try:
            p = urlparse(url)
            p.scheme
            p.hostname
            p.path
            p.query

        except ValueError:
            continue


def bench_pyfaup(urls):
    p = Faup()

    for url in urls:
        p.decode(url)
        p.get_scheme()
        p.get_host()
        p.get_resource_path()
        p.get_query_string()


def bench_ada_url(urls):
    for url in urls:
        try:
            p = ada_url.URL(url)
            p.protocol
            p.hostname
            p.pathname
            p.search

        except ValueError:
            continue


def bench_can_ada(urls):
    for url in urls:
        try:
            p = can_ada.parse(url)
            p.protocol
            p.hostname
            p.pathname
            p.search

        except ValueError:
            continue


def bench_yarl(urls):
    for url in urls:
        try:
            p = yarl.URL(url)
            p.scheme
            p.host
            p.path
            p.query_string

        except ValueError:
            continue


def bench_domain_urllib_tldextract(urls):
    for url in urls:
        try:
            p = urlparse(url)
            p.scheme
            p.path
            p.query
            d = tldextract.extract(p.hostname or '')
            d.domain

        except ValueError:
            continue


def bench_domain_ada_url_pydomainextractor(urls):
    extract = pydomainextractor.DomainExtractor().extract

    for url in urls:
        try:
            p = ada_url.URL(url)
            p.protocol
            p.pathname
            p.search
            d = extract(p.hostname)
            f"{d['domain']}.{d['suffix']}"

        except ValueError:
            continue


def bench_domain_can_ada_pydomainextractor(urls):
    extract = pydomainextractor.DomainExtractor().extract

    for url in urls:
        try:
            p = can_ada.parse(url)
            p.protocol
            p.pathname
            p.search
            d = extract(p.hostname)
            f"{d['domain']}.{d['suffix']}"

        except ValueError:
            continue


def bench_domain_pyfaup(urls):
    p = Faup()

    for url in urls:
        p.decode(url)
        p.get_scheme()
        p.get_resource_path()
        p.get_query_string()
        p.get_domain()


def bench(func, urls, name, runs=10):
    """Benchmark a function with pytest-benchmark style statistics."""

    try:
        # Create timer
        timer = timeit.Timer(lambda: func(urls))

        # Run benchmark multiple times
        times = timer.repeat(repeat=runs, number=1)

        # Calculate statistics
        min_time = min(times)
        max_time = max(times)
        mean_time = statistics.mean(times)

        # Calculate attempted inputs/second, including rejected URLs, using best time
        rate = len(urls) / min_time

        return {
            'name': name,
            'min': min_time,
            'max': max_time,
            'mean': mean_time,
            'rate': rate
        }

    # Report a failed case and let the other parsers run.
    except Exception as e:  # noqa: BLE001
        print(f"ERROR benchmarking {name}: {e}")

        return None


def run_benchmarks(console, benchmarks, urls, runs=10):
    """Run a list of benchmarks and return results."""
    results = []
    num_benchmarks = len(benchmarks)

    for i, (name, func) in enumerate(benchmarks, 1):
        with console.status(f"[bold]Benchmarking [blue]{name}[/blue][/bold] ({i}/{num_benchmarks})"):
            result = bench(func, urls, name, runs)

            if result:
                results.append(result)

    return results


def format_results_table(results, title, console):
    """Format results in pytest-benchmark style with factors using Rich."""

    if not results:
        return

    # Find the fastest result (baseline)
    fastest = min(results, key=lambda x: x['min'])
    baseline_min = fastest['min']
    baseline_max = fastest['max']
    baseline_mean = fastest['mean']

    table = Table(
        title=Text(title, style="bold blue", justify="left"),
        box=box.ROUNDED,
        header_style="bold magenta"
    )

    table.add_column("Name", no_wrap=True)
    table.add_column("Min", justify="right")
    table.add_column("Max", justify="right")
    table.add_column("Mean", justify="right")
    table.add_column("Throughput", justify="right")

    # Sort results by min time (fastest first)
    sorted_results = sorted(results, key=lambda x: x['min'])

    for result in sorted_results:
        min_factor = result['min'] / baseline_min
        max_factor = result['max'] / baseline_max
        mean_factor = result['mean'] / baseline_mean
        name_style = "bold green" if result == fastest else "bright_white"

        table.add_row(
            f"[{name_style}]{result['name']}[/{name_style}]",
            f"{result['min']*1000:.1f} ms ([cyan]{min_factor:.2f}[/cyan])",
            f"{result['max']*1000:.1f} ms ([cyan]{max_factor:.2f}[/cyan])",
            f"{result['mean']*1000:.1f} ms ([cyan]{mean_factor:.2f}[/cyan])",
            f"{result['rate']:,.0f} URLs/s"
        )

    console.print(table)
    console.print()


def main():
    console = Console()

    # Load URLs once into memory for consistent benchmarking
    urls = list(load_urls())
    n = len(urls)
    runs = 10

    console.print("[bold blue]crup URL Parsing Benchmark[/bold blue]")
    console.print(f"Input URLs: {n:,}")
    console.print("Throughput counts attempted inputs, including rejected URLs.")
    console.print(f"Runs per test: {runs}")
    console.print()

    # Run parsing benchmarks
    benchmarks = [
        ("urlparse", bench_urlparse),
        ("pyfaup", bench_pyfaup),
        ("ada_url", bench_ada_url),
        ("can_ada", bench_can_ada),
        ("yarl", bench_yarl),
        ("crup", bench_crup),
        ("crup mutable", bench_crup_mutable),
    ]

    results = run_benchmarks(console, benchmarks, urls, runs)

    if results:
        format_results_table(results, "URL Parsing + Component Access Results", console)

    # Run domain extraction benchmarks
    domain_benchmarks = [
        ("urlparse + tldextract", bench_domain_urllib_tldextract),
        ("ada_url + pydomainextractor", bench_domain_ada_url_pydomainextractor),
        ("can_ada + pydomainextractor", bench_domain_can_ada_pydomainextractor),
        ("pyfaup", bench_domain_pyfaup),
        ("crup", bench_domain_crup),
    ]

    domain_results = run_benchmarks(console, domain_benchmarks, urls, runs)

    if domain_results:
        format_results_table(domain_results, "URL Parsing + Domain Extraction Results", console)


if __name__ == "__main__":
    main()
