"""PSL selection and crup's host-relative cache boundaries, using data/psl.dat."""
import gc

import crup
import pytest


@pytest.mark.parametrize("text,mode,expected", [
    ("https://www.example.test", "ICANN", ("example.test", "test", "ICANN")),
    ("https://www.example.co.test./p", "ICANN", ("example.co.test", "co.test", "ICANN")),
    ("foo://www.EXAMPLE.CO.TEST./p", "ICANN", ("example.co.test", "co.test", "ICANN")),
    ("https://a.b.wild.test", "ICANN", ("a.b.wild.test", "b.wild.test", "ICANN")),
    ("https://www.except.wild.test", "ICANN", ("except.wild.test", "wild.test", "ICANN")),
    ("https://sub.例え.test", "ICANN", ("xn--r8jz45g.test", "test", "ICANN")),
    ("https://example.unknown", "ICANN", ("example.unknown", "unknown", None)),
    ("https://a.hosted.test", "ICANN", ("hosted.test", "test", "ICANN")),
    ("https://a.hosted.test", "ALL", ("a.hosted.test", "hosted.test", "PRIVATE")),
    ("foo://A.HOSTED.TEST", "PRIVATE", ("a.hosted.test", "hosted.test", "PRIVATE")),
    ("https://example.co.test", "PRIVATE", None),
    ("https://example.unknown", "PRIVATE", None),
    ("https://co.test", "ALL", None),
    ("http://localhost", "ICANN", None),
    ("http://192.168.1.1", "ICANN", None),
    ("http://[2001:db8::1]", "ICANN", None),
    ("mailto:a@example.test", "ICANN", None),
], ids=["ordinary", "trailing-dot", "opaque-case", "wildcard", "exception", "idn",
        "unknown", "private-as-icann", "all-private", "private-case", "private-excludes-icann",
        "private-excludes-unknown", "suffix-only", "single-label", "ipv4", "ipv6", "hostless"])
def test_domain_rules(text, mode, expected):
    parsed = crup.parse(text, getattr(crup.psl, mode))
    hostname = parsed.hostname
    domain, info = parsed.domain, parsed.domain_info()

    if expected is None:
        assert domain is info is None

    else:
        expected_domain, suffix, psl_type = expected
        assert domain == info.domain == expected_domain
        assert info.suffix == suffix
        assert info.psl == (getattr(crup.psl, psl_type) if psl_type else None)

    assert parsed.hostname == hostname  # Lookup must not rewrite opaque hosts.

    if hostname is not None:
        assert crup.extract_domain(hostname, getattr(crup.psl, mode)) == info


@pytest.mark.parametrize("hostname", [
    "www.EXAMPLE.CO.TEST.", "www.example.co.test", "www.example\u3002co\uff0etest\uff61",
    "%77ww.example.co.test",
])
def test_extract_domain_normalization(hostname):
    expected = crup.parse("https://www.example.co.test").domain_info()
    assert crup.extract_domain(hostname) == expected
    assert crup.extract_domain(hostname=hostname, psl=None) == expected


def test_extract_domain_idn():
    assert crup.extract_domain("sub.例え.test") == crup.parse("https://sub.例え.test").domain_info()


@pytest.mark.parametrize("hostname", [
    "www.example.test", "a1-b2.example.test", "1.example.test", "-example.test",
    "example-.test", "ab--cd.test", "a" * 64 + ".test", "a." * 128 + "test",
    "localhost", "co.test", "example.unknown", "a.hosted.test",
    "www.EXAMPLE.TEST", "www.example.test.", "sub.例え.test", "xn--r8jz45g.test",
    "example.xn--p1ai", "xn--.test", "xn--a.test", "XN--r8jz45g.test",
    "www..example.test", ".example.test", "example_test.test", "example!x.test",
    "%65xample.test", "192.168.1.1", "127.1", "2130706433", "0x7f000001",
    "0177.0.0.1", "example.123", "example.0x10", "example.1abc", "example.-test",
    "example.a123", "[2001:db8::1]", "foo.xn--0", "example.0xg",
])
def test_extract_domain_matches_host_parser(hostname):
    for mode in (crup.psl.ICANN, crup.psl.ALL, crup.psl.PRIVATE):
        try:
            expected = crup.parse("https://" + hostname, mode).domain_info()

        except ValueError:
            with pytest.raises(ValueError):
                crup.extract_domain(hostname, mode)

        else:
            assert crup.extract_domain(hostname, mode) == expected


@pytest.mark.parametrize("hostname", [
    "", "https://example.test", "//example.test", "example.test/path",
    "example.test:443", "user@example.test", "example.test?key=value", "example.test#part",
    " example.test", "example.test ", "exam ple.test", "example.test\n", "example\x00.test",
    "example.test\\path", "[2001:db8::1", "2001:db8::1",
])
def test_extract_domain_rejects_invalid_hosts(hostname):
    with pytest.raises(ValueError):
        crup.extract_domain(hostname)


@pytest.mark.parametrize("args,kwargs", [
    ((), {}), ((None,), {}), ((b"example.test",), {}), ((123,), {}),
    (("example.test", "ALL"), {}), (("example.test",), {"psl": 1}),
    (("example.test", None, None), {}), (("example.test",), {"unknown": True}),
])
def test_extract_domain_argument_errors(args, kwargs):
    with pytest.raises(TypeError):
        crup.extract_domain(*args, **kwargs)


def test_domain_cache_and_binding(factory):
    for text, mode, expected in [
        ("https://www.example.test", crup.psl.ICANN, ("example.test", "test", crup.psl.ICANN)),
        ("foo://A.HOSTED.TEST", crup.psl.PRIVATE, ("a.hosted.test", "hosted.test", crup.psl.PRIVATE)),
        ("mailto:a@example.test", crup.psl.ICANN, (None, None, None)),
    ]:
        for info_first in (False, True):
            parsed = factory(text, mode)
            hostname = parsed.hostname

            if info_first:
                info, domain = parsed.domain_info(), parsed.domain

            else:
                domain, info = parsed.domain, parsed.domain_info()

            assert (domain, info.suffix if info else None, info.psl if info else None) == expected
            assert domain == (info.domain if info else None)
            assert parsed.hostname == hostname
            assert parsed.domain == domain
            assert parsed.domain_info() == info


@pytest.mark.parametrize("text,expected_domain,expected_suffix", [
    ("https://www.example.co.test", "example.co.test", "co.test"),
    ("foo://WWW.EXAMPLE.CO.TEST.", "example.co.test", "co.test"),
    ("https://sub.例え.test", "xn--r8jz45g.test", "test"),
])
def test_returned_values_outlive_the_url(factory, text, expected_domain, expected_suffix):
    parsed = factory(text)
    domain, info = parsed.domain, parsed.domain_info()
    del parsed
    gc.collect()
    # Exercise allocation/reuse after releasing the source object.

    for other_text in ("https://other.test/new", "http://192.168.1.1") * 20:
        temporary = factory(other_text)
        temporary.domain_info()
        del temporary

    assert domain == info.domain == expected_domain
    assert info.suffix == expected_suffix
