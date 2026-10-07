"""Shared crup workloads for the full benchmark and native CI comparisons."""
# Attribute reads are part of the measured workload.
# ruff: noqa: B018

from pathlib import Path

import crup


def load_urls():
    with open(Path(__file__).parent / 'data.txt', newline='') as f:
        return f.readlines()


def bench_crup(urls):
    for url in urls:
        try:
            p = crup.parse(url)
            p.scheme
            p.hostname
            p.path
            p.query

        except ValueError:
            continue


def bench_crup_mutable(urls):
    for url in urls:
        try:
            p = crup.URL.parse(url)
            p.scheme
            p.hostname
            p.path
            p.query

        except ValueError:
            continue


def bench_domain_crup(urls):
    for url in urls:
        try:
            p = crup.parse(url)
            p.scheme
            p.path
            p.query
            p.domain

        except ValueError:
            continue


def bench_crup_parse(urls):
    for url in urls:
        try:
            p = crup.parse(url)  # noqa: F841

        except ValueError:
            continue
