"""The Python URL contract shared by immutable and mutable objects."""
import importlib
import operator

import crup
import pytest

COMPONENTS = ("scheme", "username", "password", "hostname", "port", "path",
              "query", "fragment", "host_ip_version")


def test_public_exports():
    from crup.psl import ICANN, PslType
    assert importlib.import_module("crup.psl") is crup.psl
    assert PslType is crup.PslType

    for name in ("ALL", "ICANN", "PRIVATE"):
        assert getattr(crup.psl, name) is getattr(PslType, name)

    info = crup.parse("https://example.test", ICANN).domain_info()
    assert isinstance(info, crup.DomainInfo)
    assert info.psl == ICANN


def test_factory_arguments(factory):
    expected_type = crup.ParsedURL if factory is crup.parse else crup.URL

    for parsed in (factory("https://a.hosted.test"),
                   factory(url_str="https://a.hosted.test", psl=None),
                   factory("https://a.hosted.test", crup.psl.ICANN)):
        assert type(parsed) is expected_type
        assert parsed.domain == "hosted.test"

    assert factory(url_str="https://a.hosted.test", psl=crup.psl.ALL).domain == "a.hosted.test"

    for args, kwargs, error in [
        ((), {}, TypeError), ((None,), {}, TypeError), ((b"https://example.test",), {}, TypeError),
        (("",), {}, ValueError), (("not a URL",), {}, ValueError),
        (("https://example.test",), {"psl": "ALL"}, TypeError),
        (("https://example.test",), {"unknown": True}, TypeError),
    ]:
        with pytest.raises(error):
            factory(*args, **kwargs)


@pytest.mark.parametrize("text,href,authority,components", [
    ("HTTPS://user:pass@EXAMPLE.TEST:8080/a?x=1#f",
     "https://user:pass@example.test:8080/a?x=1#f", "user:pass@example.test:8080",
     ("https", "user", "pass", "example.test", 8080, "/a", "x=1", "f", None)),
    ("https://example.test:443", "https://example.test/", "example.test",
     ("https", "", None, "example.test", None, "/", None, None, None)),
    ("https://example.test/?#", "https://example.test/?#", "example.test",
     ("https", "", None, "example.test", None, "/", "", "", None)),
    ("https://例え.test/é", "https://xn--r8jz45g.test/%C3%A9", "xn--r8jz45g.test",
     ("https", "", None, "xn--r8jz45g.test", None, "/%C3%A9", None, None, None)),
    ("http://192.168.1.1:8080/a", "http://192.168.1.1:8080/a", "192.168.1.1:8080",
     ("http", "", None, "192.168.1.1", 8080, "/a", None, None, 4)),
    ("http://[2001:db8::1]/", "http://[2001:db8::1]/", "[2001:db8::1]",
     ("http", "", None, "[2001:db8::1]", None, "/", None, None, 6)),
    ("file:///tmp/a", "file:///tmp/a", "",
     ("file", "", None, None, None, "/tmp/a", None, None, None)),
    ("mailto:a@example.test", "mailto:a@example.test", "",
     ("mailto", "", None, None, None, "a@example.test", None, None, None)),
], ids=["complete", "absent", "empty-delimiters", "unicode", "ipv4", "ipv6", "file", "opaque"])
def test_components(factory, text, href, authority, components):
    parsed = factory(text)
    assert tuple(getattr(parsed, name) for name in COMPONENTS) == components
    assert parsed.href == str(parsed) == href
    assert parsed.authority == parsed.netloc == authority


def test_helpers(factory):
    for path, parts in [("/", []), ("//a///b/", ["a", "b"]),
                        ("/a%2Fb/%C3%A9", ["a%2Fb", "%C3%A9"])]:
        assert factory("https://example.test" + path).path_parts() == parts

    with pytest.raises(ValueError):
        factory("mailto:a@example.test").path_parts()

    for query, params in [("", {}), ("?", {}), ("?a=1&a=2&empty=&bare", {"a": "2", "empty": "", "bare": ""}),
                          ("?a+b=c%2Bd&%C3%A9=%E2%9C%93", {"a b": "c+d", "é": "✓"})]:
        assert factory("https://example.test/" + query).query_params() == params


def test_equality_and_python_comparisons(factory):
    parsed = factory("https://EXAMPLE.TEST:443/path", crup.psl.ICANN)

    for other_factory in (crup.parse, crup.URL.parse):
        for path, equal in [("/path", True), ("/different", False)]:
            other = other_factory("https://example.test" + path, crup.psl.PRIVATE)
            assert (parsed == other) is equal
            assert (other == parsed) is equal
            assert (parsed != other) is (not equal)
            assert (other != parsed) is (not equal)

    other = object()
    assert parsed.__eq__(other) is parsed.__ne__(other) is NotImplemented
    assert (parsed == other) is False
    assert parsed != other

    for comparison in (operator.lt, operator.le, operator.gt, operator.ge):
        with pytest.raises(TypeError):
            comparison(parsed, factory(parsed.href))

    calls = []
    class Peer:
        def __eq__(self, other):
            calls.append(("eq", other))

            return True
        def __ne__(self, other):
            calls.append(("ne", other))

            return False
    assert parsed == Peer()
    assert (parsed != Peer()) is False
    assert calls == [("eq", parsed), ("ne", parsed)]


def test_hash_contract():
    parsed = crup.parse("https://EXAMPLE.TEST:443/path")
    equivalent = crup.parse("https://example.test/path", crup.psl.ALL)
    assert hash(parsed) == hash(equivalent)
    mapping, members = {parsed: "value"}, {parsed}
    parsed.domain_info()
    _ = equivalent.domain
    assert mapping[equivalent] == "value"
    assert equivalent in members
    mutable = crup.URL.parse(parsed.href)

    with pytest.raises(TypeError, match="unhashable"):
        hash(mutable)


def test_readonly_properties(factory):
    parsed = factory("https://user:pass@example.test:8080/a?q=1#f")
    names = ("href", "authority", "netloc", "domain")

    if isinstance(parsed, crup.ParsedURL):
        names += COMPONENTS

    else:
        names += ("host_ip_version",)

    for name in names:
        with pytest.raises(AttributeError):
            setattr(parsed, name, getattr(parsed, name))

    info = parsed.domain_info()

    for name in ("domain", "suffix", "psl"):
        with pytest.raises(AttributeError):
            setattr(info, name, getattr(info, name))
