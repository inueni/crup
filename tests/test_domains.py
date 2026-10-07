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


def test_returned_values_outlive_the_url(factory):
    parsed = factory("https://www.example.co.test")
    domain, info = parsed.domain, parsed.domain_info()
    del parsed
    gc.collect()
    # Exercise allocation/reuse after releasing the source object.

    for text in ("https://other.test/new", "http://192.168.1.1") * 20:
        temporary = factory(text)
        temporary.domain_info()
        del temporary

    assert domain == info.domain == "example.co.test"
    assert info.suffix == "co.test"
