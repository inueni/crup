
use pyo3::{basic::CompareOp, prelude::*};
use pyo3::types::PyString;
use once_cell::sync::OnceCell;
use url::Url;
use crate::base::BaseUrl;
use crate::psl::{DomainInfo, DomainMatch, PslType};

/// Represents a parsed URL, exposing its components to Python.
///
/// This struct wraps a `url::Url` and provides Pythonic getters for all major URL parts,
/// including scheme, host, port, username, password, path, query, fragment, and domain.
/// The domain is extracted using the Public Suffix List (PSL).
#[pyclass(name = "ParsedURL", module = "crup", frozen)]
pub struct ParsedUrl {
    /// Internal URL object.
    inner: Url,
    /// The PSL type to use for domain extraction.
    psl: PslType,
    /// Cached domain value for efficient repeated access.
    domain_info_cache: OnceCell<Option<DomainMatch>>,
}

impl BaseUrl for ParsedUrl {
    fn inner(&self) -> &Url { &self.inner }
    fn psl(&self) -> PslType { self.psl }
    fn domain_info_cache(&self) -> &OnceCell<Option<DomainMatch>> { &self.domain_info_cache }
}

#[pymethods]
impl ParsedUrl {
    #[getter]
    fn href(&self) -> &str {
        self.inner.as_str()
    }
    
    #[inline]
    #[getter]
    fn scheme(&self) -> &str {
        self.inner.scheme()
    }

    #[inline]
    #[getter]
    fn authority(&self) -> &str {
        self.inner.authority()
    }

    #[getter]
    fn netloc(&self) -> &str {
        self.authority()
    }

    #[inline]
    #[getter]
    fn hostname(&self) -> Option<&str> {
        self.inner.host_str()
    }

    #[inline]
    #[getter]
    fn port(&self) -> Option<u16> {
        self.inner.port()
    }

    #[inline]
    #[getter]
    fn path(&self) -> &str {
        self.inner.path()
    }

    #[inline]
    #[getter]
    fn query(&self) -> Option<&str> {
        self.inner.query()
    }

    #[inline]
    #[getter]
    fn fragment(&self) -> Option<&str> {
        self.inner.fragment()
    }

    #[inline]
    #[getter]
    fn username(&self) -> &str { 
        self.inner.username()
    }

    #[inline]
    #[getter]
    fn password(&self) -> Option<&str> {
        self.inner.password()
    }

    /// Returns the PSL-registered domain, if available.
    #[inline]
    #[getter]
    fn domain<'py>(&self, py: Python<'py>) -> Option<Bound<'py, PyString>> {
        BaseUrl::domain(self, py)
    }
    
    /// Returns the IP version of the host, if the host is an IP address.
    #[getter]
    fn host_ip_version(&self) -> Option<u8> {
        BaseUrl::host_ip_version(self)
    }

    fn path_parts(&self) -> PyResult<Vec<String>> {
        BaseUrl::path_parts(self)
    }

    fn query_params(&self, py: Python) -> PyResult<Py<PyAny>> {
        BaseUrl::query_params(self, py)
    }

    #[inline]
    fn domain_info(&self) ->  Option<DomainInfo> {
        BaseUrl::domain_info(self)
    }

    fn __str__(&self)  -> &str {
        self.href()
    }
    
    fn __repr__(&self) -> String {
        self.py_repr("ParsedURL")
    }

    fn __richcmp__(&self, other: Bound<'_, PyAny>, op: CompareOp) -> PyResult<Py<PyAny>> {
        self.py_compare(other, op)
    }

    fn __hash__(&self) -> u64 {
        self.py_hash()
    }
}

/// Parses a URL string and returns a ParsedUrl object.
///
/// # Arguments
/// * `url_str` - The URL string to parse.
/// * `psl` - Optional Public Suffix List type. If not provided, defaults to `PslType::Icann`.
///
/// # Returns
/// * `ParsedUrl` if parsing succeeds, or a Python ValueError if parsing fails.
#[pyfunction]
#[pyo3(signature = (url_str, psl = None))]
pub fn parse(url_str: &str, psl: Option<PslType>) -> PyResult<ParsedUrl> {
    let u: Url = url::Url::parse(url_str)
        .map_err(|e: url::ParseError| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

    Ok(ParsedUrl {
        inner: u,
        psl: psl.unwrap_or(PslType::Icann),
        domain_info_cache: OnceCell::new(),
    })
}
