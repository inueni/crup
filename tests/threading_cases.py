"""Exercise native concurrency in child processes so hangs and aborts fail tests."""

import faulthandler
import gc
import json
import os
import queue
import sys
import sysconfig
import threading
import time
import traceback

WORKERS = 8
CASES = [
    ("https://www.example.co.test./p?key=v&x=2#part", "example.co.test", "co.test", "ICANN"),
    ("foo://www.EXAMPLE.CO.TEST./p?key=v&x=2#part", "example.co.test", "co.test", "ICANN"),
    ("https://USER.HOSTED.TEST/p?key=v&x=2#part", "user.hosted.test", "hosted.test", "PRIVATE"),
    ("http://localhost/p?key=v&x=2#part", None, None, "ICANN"),
    ("http://[2001:db8::1]/p?key=v&x=2#part", None, None, "ICANN"),
    ("foo://" + "a" * 4096 + ".test/p?key=v&x=2#part", "a" * 4096 + ".test", "test", "ICANN"),
]


def gil_enabled():
    return getattr(sys, "_is_gil_enabled", lambda: True)()


def run_threads(functions):
    failures = queue.SimpleQueue()

    def checked(function):
        try:
            function()

        # Forward even SystemExit from a worker so the parent cannot report success.
        except BaseException:  # noqa: BLE001
            failures.put(traceback.format_exc())

    threads = [threading.Thread(target=checked, args=(function,), daemon=True)
               for function in functions]

    for thread in threads:
        thread.start()

    deadline = time.monotonic() + 25

    for thread in threads:
        thread.join(max(0, deadline - time.monotonic()))

    if not failures.empty():
        raise AssertionError(failures.get())

    assert not any(thread.is_alive() for thread in threads), "native worker did not finish"


def check_url(parsed, domain, suffix):
    assert parsed.domain == domain, parsed.href
    info = parsed.domain_info()

    if domain is None:
        assert info is None

    else:
        assert info.domain == domain
        assert info.suffix == suffix


def independent(crup, factories, rounds):
    start = threading.Barrier(WORKERS)

    def worker():
        start.wait()

        for index in range(rounds * 10):
            text, domain, suffix, mode = CASES[index % len(CASES)]

            for factory in factories:
                parsed = factory(text, getattr(crup.psl, mode))
                check_url(parsed, domain, suffix)
                del parsed

    run_threads([worker] * WORKERS)


def shared(crup, factories, rounds, mutable):
    factory = factories[mutable]
    barrier = threading.Barrier(WORKERS + 1, timeout=15)
    shared = [None]

    def reader():
        for index in range(rounds):
            barrier.wait()
            _, domain, suffix, _ = CASES[index % len(CASES)]
            parsed = shared[0]
            check_url(parsed, domain, suffix)
            barrier.wait()

    def coordinator():
        for index in range(rounds):
            text, _, _, mode = CASES[index % len(CASES)]
            # Every round races the first reads of both lazy cache levels.
            shared[0] = factory(text, getattr(crup.psl, mode))
            barrier.wait()
            gc.collect()
            barrier.wait()

        shared[0] = None

    run_threads([reader] * WORKERS + [coordinator])


def handoff(crup, factories, rounds):
    values = queue.Queue(maxsize=32)
    retained = []

    def producer():
        for index in range(rounds * 10):
            text, domain, suffix, mode = CASES[index % len(CASES)]
            parsed = factories[index % 2](text, getattr(crup.psl, mode))
            check_url(parsed, domain, suffix)
            values.put((parsed, domain, suffix))
            del parsed

        values.put(None)

    def consumer():
        while (item := values.get()) is not None:
            parsed, domain, suffix = item
            check_url(parsed, domain, suffix)
            retained.append((parsed.domain, parsed.domain_info(), domain, suffix))
            del parsed, item

            if len(retained) % 50 == 0:
                gc.collect()

        for value, info, domain, suffix in retained:
            assert value == domain

            if info is not None:
                assert (info.domain, info.suffix) == (domain, suffix)

    run_threads([producer, consumer])


def mutation(crup, rounds, locked):
    parsed = crup.URL.parse("https://www.example.test/p?key=v&x=2#part")
    lock = threading.Lock()
    start = threading.Barrier(WORKERS)
    successes = queue.SimpleQueue()
    conflicts = queue.SimpleQueue()

    def operation(index):
        expected_domain = "example.co.test" if index % 2 else "example.test"
        parsed.hostname = "www." + expected_domain

        if locked:
            assert parsed.domain == expected_domain
            assert parsed.domain_info().domain == expected_domain

        else:
            # Unlocked calls can observe different intervening writes.
            assert parsed.domain in ("example.test", "example.co.test")
            assert parsed.domain_info().domain in ("example.test", "example.co.test")

        parsed.query = "key=v&x=2"
        assert parsed.query_params() == {"key": "v", "x": "2"}

    def writer():
        start.wait()

        for index in range(rounds * 10):
            try:
                if locked:
                    with lock:
                        operation(index)

                else:
                    operation(index)

                successes.put(1)

            except RuntimeError as error:
                assert not locked, str(error)
                assert "borrowed" in str(error).lower(), str(error)
                conflicts.put(1)

    run_threads([writer] * WORKERS)
    assert not successes.empty(), "no writer completed"
    print(json.dumps({"borrow_conflicts": conflicts.qsize()}), flush=True)

    with lock:
        parsed.hostname = "www.example.test"
        assert parsed.domain == "example.test"


def update(crup, factories):
    done = threading.Event()
    start = threading.Barrier(4, timeout=15)
    observed = [threading.Event(), threading.Event()]
    # Warm each lazy access order and retain cold objects across the reload.
    cached, cold = [], []

    for factory in factories:
        for info_first in (False, True):
            parsed = factory("https://www.example.co.invalid")

            if info_first:
                parsed.domain_info()

            assert parsed.domain == "example.co.invalid"
            cached.append((parsed, parsed.domain, parsed.domain_info()))

        cold.append(factory(cached[0][0].href))

    def updater():
        start.wait()

        try:
            assert all(event.wait(10) for event in observed), "readers did not start"
            crup.psl.update(timeout=10)

        finally:
            done.set()

    def reader(index):
        start.wait()

        while not done.is_set():
            parsed = factories[index](cached[0][0].href)
            domain = parsed.domain
            assert domain in ("example.co.invalid", "co.invalid")
            assert parsed.domain_info().domain == domain

            for old, value, info in cached:
                assert old.domain == value
                assert old.domain_info() == info

            observed[index].set()

    def collector():
        start.wait()

        while not done.wait(0.002):
            gc.collect()

    run_threads([updater, lambda: reader(0), lambda: reader(1), collector])

    for parsed in cold + [factory(cached[0][0].href) for factory in factories]:
        assert parsed.domain == parsed.domain_info().domain == "co.invalid"

    for parsed, value, info in cached:
        assert parsed.domain == value == "example.co.invalid"
        assert parsed.domain_info() == info

        if isinstance(parsed, crup.URL):
            parsed.hostname = "www.other.co.invalid"
            assert parsed.domain == "co.invalid"

        assert value == info.domain == "example.co.invalid"

    assert crup.psl.get_psl_path().is_file()
    assert crup.parse("https://example.com").domain == "example.com"


def main(case):
    before = gil_enabled()
    import crup
    assert gil_enabled() == before, "import changed the GIL state"

    if sysconfig.get_config_var("Py_GIL_DISABLED") and os.environ.get("PYTHON_GIL") != "1":
        assert not before, "free-threaded verification requires the GIL disabled"

    rounds = int(os.environ.get("CRUP_THREAD_TEST_ROUNDS", "100"))
    factories = [crup.parse, crup.URL.parse]

    if case == "independent":
        independent(crup, factories, rounds)

    elif case == "shared":
        for mutable in (False, True):
            shared(crup, factories, rounds, mutable)

    elif case == "handoff":
        handoff(crup, factories, rounds)

    elif case in ("locked", "unlocked"):
        mutation(crup, rounds, locked=case == "locked")

    elif case == "update":
        update(crup, factories)

    else:
        raise AssertionError(case)

    gc.collect()
    assert gil_enabled() == before
    print(json.dumps({"case": case, "gil_enabled": gil_enabled(), "rounds": rounds}), flush=True)


if __name__ == "__main__":
    faulthandler.enable()
    faulthandler.dump_traceback_later(30)

    try:
        main(sys.argv[1])

    finally:
        faulthandler.cancel_dump_traceback_later()
