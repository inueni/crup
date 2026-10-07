# crup

<div align="center">
<img src="https://raw.githubusercontent.com/inueni/crup/main/assets/images/crusty.png" alt="crusty" />

`crup` - **CR**usty **U**rl **P**arser - a fast **Rust**-powered URL parser for **Python**.

</div>

## TL;DR

### Features

- **[Blazing fast performance](#performance)**
- **[Simple and familiar API](#usage)**
- **[PSL based domain extraction](#domain-extraction)**
- **[WHATWG URL Standard compliance](#whatwg-url-standard-compliance)**
- **[Optional mutable interface](#mutable-urls)**
- **[API reference](#api-reference)**
- **[Tests](#running-tests)**

### Installation

Add `crup` from [PyPI](https://pypi.org/project/crup/) to your [uv](https://astral.sh/uv) project:

```bash
uv add crup
```

To install into an existing virtual environment, use `uv pip install crup` or `pip install crup`.

### Quick start

```python
import crup

url = crup.parse("https://www.example.com/path?query=1")

print(url.scheme)   # 'https'
print(url.hostname) # 'www.example.com'
print(url.path)     # '/path'
print(url.query)    # 'query=1'
print(url.domain)   # 'example.com'
print(url)          # 'https://www.example.com/path?query=1'
```

Mutable URL example:

```python
from crup import URL

url = URL.parse("https://www.example.com/path?query=1")

print(url.hostname) # 'www.example.com'
print(url.path)     # '/path'

url.hostname = "newhost.com"
url.path = "/newpath"

print(url)  # 'https://newhost.com/newpath?query=1'
```

## Why another Python URL parser? Aren't there enough?

`crup` grew out of a need to parse tens of millions of URLs and extract their registered domains. At that scale, the cost of parsing, reading components and looking up domains starts to add up.

[Ada](https://github.com/ada-url/ada) based Python parsers are fast at parsing URLs, but the cost of reading attributes such as hostname, path and query can reduce that advantage. Since crup was originally written, [can_ada](https://github.com/TkTech/can_ada) has substantially reduced this overhead by moving to [nanobind](https://github.com/wjakob/nanobind). In our [benchmarks](#performance), crup stays close to can_ada for parsing and component access, while providing domain extraction in the same API.

We also tried [pyFaup](https://pypi.org/project/pyfaup/), based on [Faup](https://github.com/stricaud/faup), which already offered domain extraction. It was slower in our workload, and we encountered stability issues.

`crup` combines Rust's [url](https://crates.io/crates/url) and [publicsuffix](https://crates.io/crates/publicsuffix) crates. You parse a URL once and request its domain information when you need it. Domain lookups are lazy and cached, and the parsed object is immutable by default, with a mutable interface available when needed.

## Usage

### Basic URL parsing

`crup.parse()` returns an immutable `ParsedURL` object with all the components you'd expect.

```python
import crup

url = crup.parse("https://user:password@example.com:8080/path/to/resource?key=value&foo=bar#section")

# Access URL components
print(url.scheme)   # 'https'
print(url.hostname) # 'example.com'
print(url.port)     # 8080
print(url.username) # 'user'
print(url.password) # 'password'
print(url.netloc)   # 'user:password@example.com:8080'
print(url.path)     # '/path/to/resource'
print(url.query)    # 'key=value&foo=bar'
print(url.fragment) # 'section'
```

### Domain extraction

Use `domain` to get the registrable domain according to the Public Suffix List (PSL). For `blog.example.co.uk`, the public suffix is `co.uk` and the registrable domain is `example.co.uk`. `domain_info()` also reports the suffix and its PSL type.

```python
import crup

url = crup.parse("https://blog.example.co.uk/posts/latest")
print(url.domain)  # 'example.co.uk'

info = url.domain_info()
print(info.domain)  # 'example.co.uk'
print(info.suffix)  # 'co.uk'
print(info.psl)     # ICANN
```

Both `domain` and `domain_info()` return `None` when there is no registrable domain, such as for IP addresses, `localhost`, or a hostname that is itself a public suffix. Domain and suffix values use lowercase ASCII; internationalized domains use their punycode form.

Domain information is calculated on first access and cached per URL. Changing a mutable URL's hostname clears its cached result.

#### Choosing a PSL type

By default, crup uses ICANN suffixes. Pass `psl` to either `crup.parse()` or `crup.URL.parse()` to include private suffixes, such as `github.io`, which distinguish individual sites on a shared hosting service.

| PSL type | Suffixes used | Domain for `user.github.io` |
| --- | --- | --- |
| `crup.psl.ICANN` (default) | ICANN | `github.io` |
| `crup.psl.ALL` | ICANN and private | `user.github.io` |
| `crup.psl.PRIVATE` | Private only | `user.github.io` |

```python
import crup

url = crup.parse("https://user.github.io/repo", psl=crup.psl.ALL)
print(url.domain)               # 'user.github.io'
print(url.domain_info().suffix) # 'github.io'
print(url.domain_info().psl)    # PRIVATE

url = crup.parse("https://example.com", psl=crup.psl.PRIVATE)
print(url.domain)  # None
```

`PRIVATE` returns a domain only when a private suffix matches. The `psl` field in `DomainInfo` identifies the matched suffix's type, or is `None` for an unknown suffix.

#### Updating the Public Suffix List

crup bundles a PSL snapshot prepared for the release, so domain extraction works without a download. `crup.psl.update()` downloads the latest list, saves it to the user cache and reloads it for the current process. The default timeout is 30 seconds and covers the complete download, including the response body.

```python
import crup

crup.psl.update(timeout=10.0)
print(crup.psl.get_psl_path())  # Cache path for this system
```

Set `CRUP_PSL_PATH` before importing crup to use a custom PSL file and update location. A missing file falls back to the bundled list; an invalid file also raises a `UserWarning` before falling back.

Updates release the GIL during downloading, parsing and saving. A failed update raises `OSError` and leaves the previous file and active list in place. Invalid timeout values raise `ValueError`.

Cached domain results stay unchanged after an update. A URL's first domain lookup uses the list active at that time; reparse a URL if you need to recalculate a result that is already cached.

### Mutable URLs

`crup` offers an optional mutable `URL` object, for cases when modifying the URL components is required.

```python
from crup import URL

# Create a mutable URL
url = URL.parse("https://api.example.com/v1/users")

print(url.hostname) # 'api.example.com'
print(url.path)     # '/v1/users'

# Modify components
url.scheme = "http"
url.hostname = "localhost"
url.port = 8000
url.path = "/api/v2/customers"
url.query = "active=true"

print(url)  # 'http://localhost:8000/api/v2/customers?active=true'
```

### Query parameters and path components

#### Query parameters

The `query` property contains the query string without the leading `?`. Use `query_params()` to get its decoded names and values as a dictionary.

```python
import crup

url = crup.parse("https://example.com/users?name=Ada+Lovelace&tag=one&tag=two&empty=")
print(url.query_params())  # {'name': 'Ada Lovelace', 'tag': 'two', 'empty': ''}
```

Percent escapes are decoded, and `+` becomes a space. Empty values and parameters without `=` map to `''`; repeated keys keep the last value. A URL with no query returns an empty dictionary.

#### Path components

`path_parts()` returns the nonempty path segments. Unlike `query_params()`, it preserves percent encoding.

```python
import crup

url = crup.parse("https://example.com/api//users/Ada%20Lovelace/")
print(url.path_parts())  # ['api', 'users', 'Ada%20Lovelace']
```

URLs with opaque paths, such as `mailto:person@example.com`, have no path segments; calling `path_parts()` on them raises `ValueError`.

### IP addresses

`host_ip_version` returns `4` or `6` for an IP address, and `None` for a domain name or a URL without a host.

```python
import crup

print(crup.parse("http://192.168.1.1/api").host_ip_version)         # 4
print(crup.parse("https://[2001:db8::1]:8080/path").host_ip_version) # 6
print(crup.parse("https://example.com").host_ip_version)           # None
```

## Compatibility

### Python support

crup requires CPython 3.10 or newer, or PyPy 3.11 or newer. Free-threaded CPython 3.14 is supported; free-threaded CPython 3.13 is not. A Rust toolchain is needed only when building from source.

### WHATWG URL Standard compliance

crup uses Rust's [url](https://crates.io/crates/url) crate to follow the WHATWG [URL Standard](https://url.spec.whatwg.org/). Internationalized hostnames are converted to punycode, and path segments such as `.` and `..` are resolved during parsing.

```python
import crup

url = crup.parse("https://example.测试/./path/../path2/")
print(url.hostname)  # 'example.xn--0zwm56d'
print(url.path)      # '/path2/'
```

### Threading

Immutable `ParsedURL` objects can be shared between threads, including their cached domain information. Mutable `URL` objects support concurrent reads. When sharing a mutable URL, use the same `threading.Lock` in every thread around mutations and any reads that must stay consistent with them. Overlapping reads and writes can raise `RuntimeError` instead of waiting for another call to finish.

```python
import threading
import crup

url = crup.URL.parse("https://www.example.com/")
lock = threading.Lock()

with lock:
    url.hostname = "www.example.co.uk"
    domain = url.domain

print(domain)  # 'example.co.uk'
```

Importing crup leaves the GIL disabled in a free-threaded interpreter. The same object-sharing rules apply on regular CPython.

## Performance

The [benchmark](https://github.com/inueni/crup/blob/main/benchmark/benchmark.py) measures parsing followed by component access, as well as parsing combined with domain extraction. It uses a real-world URL dataset from Ada's benchmark. Run it with current dependencies to compare performance on your system.

### Benchmark results

Sample run on an AMD Ryzen 7 7700 server (8C/16T) with 64 GB of RAM, using Linux and CPython 3.12. The benchmark covered 100,031 URLs in five passes of 10 runs per workload, pinned to one CPU. The tables summarize all 50 timings for a local release build of crup. Times cover the full dataset; throughput counts attempted inputs, including rejected URLs, and uses the minimum time.

#### URL parsing and component access

| Library | Min | Max | Mean | Throughput |
| --- | ---: | ---: | ---: | ---: |
| `can_ada` | 42.3 ms | 43.7 ms | 42.9 ms | 2,364,484 URLs/s |
| `crup` | 48.7 ms | 50.8 ms | 49.4 ms | 2,054,113 URLs/s |
| `crup mutable` | 52.1 ms | 53.5 ms | 52.9 ms | 1,919,645 URLs/s |
| `urlparse` | 294.9 ms | 304.0 ms | 299.2 ms | 339,200 URLs/s |
| `pyfaup` | 296.5 ms | 314.2 ms | 300.3 ms | 337,385 URLs/s |
| `ada_url` | 362.3 ms | 382.6 ms | 369.5 ms | 276,133 URLs/s |
| `yarl` | 369.9 ms | 395.9 ms | 382.6 ms | 270,460 URLs/s |

#### URL parsing and domain extraction

| Library | Min | Max | Mean | Throughput |
| --- | ---: | ---: | ---: | ---: |
| `crup` | 58.4 ms | 66.9 ms | 59.6 ms | 1,712,864 URLs/s |
| `can_ada + pydomainextractor` | 72.8 ms | 75.1 ms | 73.8 ms | 1,373,668 URLs/s |
| `pyfaup` | 296.9 ms | 305.1 ms | 302.8 ms | 336,974 URLs/s |
| `ada_url + pydomainextractor` | 395.0 ms | 412.9 ms | 404.9 ms | 253,273 URLs/s |
| `urlparse + tldextract` | 517.6 ms | 538.8 ms | 528.8 ms | 193,256 URLs/s |

### Running the benchmark

Clone the repository, then choose the published PyPI package or a release build of this checkout:

```bash
git clone https://github.com/inueni/crup.git
cd crup

# Published crup from PyPI
uv run benchmark/benchmark.py

# Build and benchmark this checkout
uv run benchmark/local.py

# Rebuild after source changes
uv run --reinstall-package crup benchmark/local.py
```

Both runners use the same workloads with current comparison dependencies, each in a separate uv environment. Python 3.10+ is required; a local build also requires a current stable Rust toolchain.

With pip, create and activate a virtual environment, then install `benchmark/requirements.txt` and run `python benchmark/benchmark.py`. Add `.` to the install command to build local crup: `pip install -r benchmark/requirements.txt .`.

## API Reference

### Parsing

| Factory | Returns |
| --- | --- |
| `crup.parse(url_str, psl=None)` | Immutable `crup.ParsedURL` |
| `crup.URL.parse(url_str, psl=None)` | Mutable `crup.URL` |

Both factories accept an absolute URL as a `str`. Invalid URLs and relative references raise `ValueError`; incorrect argument types raise `TypeError`. Omitting `psl` or passing `None` selects `crup.psl.ICANN`. See [Domain extraction](#domain-extraction) for the other PSL modes.

### URL objects

`ParsedURL` and `URL` expose the same getters and methods. Only `URL` allows component assignment. Equality compares normalized URLs across both classes, regardless of PSL selection. `ParsedURL` is hashable; `URL` is unhashable. Use `crup.parse(url.href)` to create an immutable dictionary key or set member.

#### Properties

The assignment column applies to `crup.URL`; every property is read-only on `ParsedURL`.

| Property | Getter type | Assignment type | Description |
| --- | --- | --- | --- |
| `href` | `str` | Read-only | Complete normalized URL; also returned by `str(url)` |
| `scheme` | `str` | `str` | Scheme without `:` |
| `hostname` | `str \| None` | `str \| None` | Host without a port; IPv6 addresses include brackets |
| `port` | `int \| None` | `int \| None` | Explicit non-default port |
| `username` | `str` | `str \| None` | Username, or `''` when absent |
| `password` | `str \| None` | `str \| None` | Password, or `None` when absent |
| `path` | `str` | `str \| None` | URL path, preserving percent encoding |
| `query` | `str \| None` | `str \| None` | Query without `?`; `None` when absent, `''` when empty |
| `fragment` | `str \| None` | `str \| None` | Fragment without `#`; `None` when absent, `''` when empty |
| `authority` | `str` | Read-only | `[userinfo@]host[:port]` |
| `netloc` | `str` | Read-only | Alias for `authority` |
| `domain` | `str \| None` | Read-only | Cached registrable domain according to the selected PSL mode |
| `host_ip_version` | `int \| None` | Read-only | `4` or `6` for an IP address, otherwise `None` |

A port equal to the scheme's default is omitted: parsing `https://example.com:443/` gives `port=None`. Assigning a port or changing the scheme can normalize it the same way.

Assigning `None` removes a query, fragment, password or port. For username and path, it assigns an empty string; the path is then normalized for the scheme. Clearing a hostname is allowed only for schemes that permit an empty host. Successful hostname assignments clear cached domain information.

Invalid schemes or hosts, and assignments unsupported by the URL's scheme, raise `ValueError`. Ports outside `0..65535` raise `OverflowError`; incorrect assignment types raise `TypeError`. Failed assignments leave the URL unchanged. See [Mutable URLs](#mutable-urls) for an example and [Threading](#threading) for sharing rules.

#### Methods

| Method | Returns | Behavior |
| --- | --- | --- |
| `path_parts()` | `list[str]` | Nonempty path segments, preserving percent encoding; raises `ValueError` for opaque paths |
| `query_params()` | `dict[str, str]` | Decoded query parameters; repeated keys keep the last value |
| `domain_info()` | `DomainInfo \| None` | Cached domain, suffix and PSL type, or `None` when no registrable domain exists |

See [Query parameters and path components](#query-parameters-and-path-components) and [Domain extraction](#domain-extraction) for examples.

### Domain information

`crup.DomainInfo` has three read-only fields:

| Field | Type | Description |
| --- | --- | --- |
| `domain` | `str` | Registrable domain, such as `example.co.uk` |
| `suffix` | `str` | Matched public suffix, such as `co.uk` |
| `psl` | `PslType \| None` | Matched suffix's type; `None` for an unknown suffix |

### Public Suffix List

`crup.psl` is available through both `import crup.psl` and `from crup import psl`. The enum type is exported as `crup.PslType` and `crup.psl.PslType`; the submodule constants are aliases for its values.

| Constant | Enum value | Suffixes used |
| --- | --- | --- |
| `crup.psl.ICANN` | `PslType.ICANN` | ICANN suffixes (default) |
| `crup.psl.ALL` | `PslType.ALL` | ICANN and private suffixes |
| `crup.psl.PRIVATE` | `PslType.PRIVATE` | Private suffixes only |

| Function | Returns | Behavior |
| --- | --- | --- |
| `crup.psl.update(*, timeout=30.0)` | `None` | Download, save and reload the PSL; raises `OSError` on failure or `ValueError` for an invalid timeout |
| `crup.psl.get_psl_path()` | `pathlib.Path \| None` | Writable cache path, or `None` when no cache location is available |

See [Updating the Public Suffix List](#updating-the-public-suffix-list) for the bundled snapshot, custom paths, timeout and cache behavior.

## Development

> `crup` is developed using [uv](https://astral.sh/uv). It's highly recommended when working on the project.

### Building from source

Requirements:

- Python 3.10+
- Current stable Rust (only needed when building from source)
- maturin

```bash
# Clone the repository
git clone https://github.com/inueni/crup.git
cd crup

# (optional) create a venv
uv venv --prompt=crup

# Install development dependencies
uv sync --group dev

# Build the extension
uv run maturin develop
```

The PSL snapshot is stored in the repository and bundled in wheels and source archives. Builds use it without downloading anything from [publicsuffix.org](https://publicsuffix.org/list/). `psl_snapshot.json` records the list's version, upstream commit and SHA256. To update the snapshot manually, run `uv run --no-project scripts/update_psl.py`.

### Running tests

Build the extension first, then run the Python and Rust tests:

```bash
uv run pytest
cargo test --locked --test psl_data
```

The default suite includes a live PSL download and reload test. To skip external network access, run:

```bash
uv run pytest --offline
```

Local proxy and HTTP server tests still run with `--offline`.

### Cross-platform benchmarks

Contributors with write access can run benchmarks on Linux, Windows and macOS through **Actions → Benchmark → Run workflow**. Select a candidate branch and optionally set **baseline-ref** to compare another revision. Each run includes `can_ada` and `urlparse` reference timings for parsing and component access. Results appear in job summaries, with raw samples available as artifacts. Repeat runs before interpreting small timing differences.

## Credits

`crup` is built on top of the excellent [url](https://crates.io/crates/url) and [publicsuffix](https://crates.io/crates/publicsuffix) Rust crates, powered by [PyO3](https://pyo3.rs/) for Python bindings.

The logo was created with the help of AI and represents the friendly crab that powers the fast URL parsing under the hood.

## License

`crup` is licensed under the [MIT License](https://github.com/inueni/crup/blob/main/LICENSE).
