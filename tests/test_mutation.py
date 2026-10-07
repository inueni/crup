"""Setter conversion, normalization, rollback and cache invalidation."""
import crup
import pytest

ORIGINAL = "https://user:pass@example.test:8080/old?q=1#f"
COMPONENTS = ("scheme", "username", "password", "hostname", "port", "path",
              "query", "fragment", "host_ip_version")


@pytest.mark.parametrize("name,value,expected", [
    ("scheme", "http", "http://user:pass@example.test:8080/old?q=1#f"),
    ("hostname", "例え.test", "https://user:pass@xn--r8jz45g.test:8080/old?q=1#f"),
    ("port", 9000, "https://user:pass@example.test:9000/old?q=1#f"),
    ("path", "/é", "https://user:pass@example.test:8080/%C3%A9?q=1#f"),
    ("query", "new=2", "https://user:pass@example.test:8080/old?new=2#f"),
    ("fragment", "new", "https://user:pass@example.test:8080/old?q=1#new"),
    ("username", "new", "https://new:pass@example.test:8080/old?q=1#f"),
    ("password", "new", "https://user:new@example.test:8080/old?q=1#f"),
], ids=["scheme", "hostname", "port", "path", "query", "fragment", "username", "password"])
def test_setter(name, value, expected):
    parsed = crup.URL.parse(ORIGINAL)
    before = {field: getattr(parsed, field) for field in COMPONENTS}
    setattr(parsed, name, value)
    normalized = crup.parse(expected)
    assert parsed.href == str(parsed) == expected
    assert getattr(parsed, name) == getattr(normalized, name)

    for field, old in before.items():
        if field != name:
            assert getattr(parsed, field) == old, field


def test_clearing_and_default_ports():
    for name, expected in [("port", "https://user:pass@example.test/old?q=1#f"),
                           ("path", "https://user:pass@example.test:8080/?q=1#f"),
                           ("query", "https://user:pass@example.test:8080/old#f"),
                           ("fragment", "https://user:pass@example.test:8080/old?q=1"),
                           ("username", "https://:pass@example.test:8080/old?q=1#f"),
                           ("password", "https://user@example.test:8080/old?q=1#f")]:
        parsed = crup.URL.parse(ORIGINAL)
        setattr(parsed, name, None)
        assert parsed.href == expected, name

    parsed = crup.URL.parse("foo://example.test/a")
    parsed.hostname = None
    assert parsed.hostname == ""
    assert parsed.href == "foo:/a"
    parsed = crup.URL.parse("https://example.test:8080/a")
    parsed.port = 443
    assert parsed.port is None
    assert parsed.href == "https://example.test/a"
    parsed.port = 80
    parsed.scheme = "http"
    assert parsed.port is None
    assert parsed.href == "http://example.test/a"

    for field in ("query", "fragment"):
        setattr(parsed, field, "")
        assert getattr(parsed, field) == ""

    assert parsed.href == "http://example.test/a?#"


def test_invalid_setters_leave_url_and_cache_unchanged():
    parsed = crup.URL.parse(ORIGINAL)
    domain, info = parsed.domain, parsed.domain_info()

    for name, value, error in [
        ("scheme", "", ValueError), ("scheme", "ht!tp", ValueError), ("scheme", "2http", ValueError),
        ("hostname", "[invalid", ValueError), ("hostname", None, ValueError),
        ("port", "abc", TypeError), ("port", -1, OverflowError), ("port", 65536, OverflowError),
        *((name, 123, TypeError) for name in ("scheme", "hostname", "path", "query", "fragment", "username", "password")),
    ]:
        with pytest.raises(error):
            setattr(parsed, name, value)

        assert parsed.href == ORIGINAL, (name, value)
        assert parsed.domain == domain
        assert parsed.domain_info() == info

    opaque = crup.URL.parse("mailto:a@example.test")

    for name, value in [("port", 80), ("username", "user"), ("password", "pass")]:
        with pytest.raises(ValueError):
            setattr(opaque, name, value)

        assert opaque.href == "mailto:a@example.test"


def test_hostname_cache_invalidation_and_retained_values():
    parsed = crup.URL.parse("https://www.example.co.test/path")
    original_domain, original_info = parsed.domain, parsed.domain_info()

    for host, domain, suffix in [("www.example.test", "example.test", "test"),
                                 ("192.168.1.1", None, None),
                                 ("sub.other.co.test.", "other.co.test", "co.test")]:
        parsed.hostname = host
        info = parsed.domain_info()  # Exercise the reverse first-access order too.
        assert parsed.domain == domain
        assert (info.suffix if info else None) == suffix

    for field, value in [("username", "long-name"), ("password", "long-password"),
                         ("port", 8080), ("scheme", "http"), ("path", "/new/path"),
                         ("query", "new=1"), ("fragment", "new-fragment")]:
        setattr(parsed, field, value)
        assert parsed.domain == "other.co.test"
        assert parsed.domain_info().suffix == "co.test"

    del parsed
    assert original_domain == original_info.domain == "example.co.test"
    assert original_info.suffix == "co.test"
