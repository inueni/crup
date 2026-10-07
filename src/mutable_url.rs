use pyo3::{basic::CompareOp, prelude::*, types::PyString};
use once_cell::sync::OnceCell;
use url::Url;
use crate::base::BaseUrl;
use crate::psl::{DomainInfo, DomainMatch, PslType};

/// Represents a mutable URL, exposing its components to Python.
///
/// This struct wraps a `url::Url` and provides Pythonic getters and setters for all major URL parts,
/// including scheme, host, port, username, password, path, query, fragment, and domain.
/// The domain is extracted using the Public Suffix List (PSL).
#[pyclass(name = "URL", module = "crup", subclass)]
pub struct MutableUrl {
    /// Internal URL object.
    inner: Url,
    /// The PSL type to use for domain extraction.
    psl: PslType,
    /// Cached domain value for efficient repeated access.
    domain_info_cache: OnceCell<Option<DomainMatch>>,
}

impl BaseUrl for MutableUrl {
    fn inner(&self) -> &Url { &self.inner }
    fn psl(&self) -> PslType { self.psl }
    fn domain_info_cache(&self) -> &OnceCell<Option<DomainMatch>> { &self.domain_info_cache }
}

#[pymethods]
impl MutableUrl {
    /// href
    #[getter]
    fn href(&self) -> &str {
        self.inner.as_str()
    }

    /// scheme
    #[inline]
    #[getter]
    fn scheme(&self) -> &str {
        self.inner.scheme()
    }

    #[inline]
    #[setter]
    fn set_scheme(&mut self, scheme: &str) -> PyResult<()> {
        self.inner.set_scheme(scheme)
            .map_err(|_| pyo3::exceptions::PyValueError::new_err("Invalid scheme"))?;
        Ok(())
    }
    
    /// authority
    #[inline]
    #[getter]
    fn authority(&self) -> &str {
        self.inner.authority()
    }
    
    /// netloc
    #[getter]
    fn netloc(&self) -> &str {
        self.authority()
    }
    
    /// hostname
    #[inline]
    #[getter]
    fn hostname(&self) -> Option<&str> {
        self.inner.host_str()
    }

    #[inline]
    #[setter]
    fn set_hostname(&mut self, hostname: Option<&str>) -> PyResult<()> {
        self.inner.set_host(hostname)
            .map_err(|e: url::ParseError| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        self.domain_info_cache.take();
        Ok(())
    }
    
    /// port
    #[inline]
    #[getter]
    fn port(&self) -> Option<u16> {
        self.inner.port()
    }

    #[inline]
    #[setter]
    fn set_port(&mut self, port: Option<u16>) -> PyResult<()> {
        self.inner.set_port(port)
            .map_err(|_| pyo3::exceptions::PyValueError::new_err("Invalid port"))?;
        Ok(())
    }
    
    /// path
    #[inline]
    #[getter]
    fn path(&self) -> &str {
        self.inner.path()
    }

    #[inline]
    #[setter]
    fn set_path(&mut self, path: Option<&str>) -> PyResult<()> {
        self.inner.set_path(path.unwrap_or(""));
        Ok(())
    }
    
    /// query
    #[inline]
    #[getter]
    fn query(&self) -> Option<&str> {
        self.inner.query()
    }

    #[inline]
    #[setter]
    fn set_query(&mut self, query: Option<&str>) -> PyResult<()> {
        self.inner.set_query(query);
        Ok(())
    }
    
    /// fragment
    #[inline]
    #[getter]
    fn fragment(&self) -> Option<&str> {
        self.inner.fragment()
    }

    #[inline]
    #[setter]
    fn set_fragment(&mut self, fragment: Option<&str>) -> PyResult<()> {
        self.inner.set_fragment(fragment);
        Ok(())
    }
    
    /// username
    #[inline]
    #[getter]
    fn username(&self) -> &str { 
        self.inner.username()
    }

    #[inline]
    #[setter]
    fn set_username(&mut self, username: Option<&str>) -> PyResult<()> {
        self.inner.set_username(username.unwrap_or(""))
            .map_err(|_| pyo3::exceptions::PyValueError::new_err("Can not set username for this URL."))?;
        Ok(())
    }
    
    /// password
    #[inline]
    #[getter]
    fn password(&self) -> Option<&str> {
        self.inner.password()
    }

    #[inline]
    #[setter]
    fn set_password(&mut self, password: Option<&str>) -> PyResult<()> {
        self.inner.set_password(password)
            .map_err(|_| pyo3::exceptions::PyValueError::new_err("Can not set password for this URL."))?;
        Ok(())
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
        self.py_repr("URL")
    }

    fn __richcmp__(&self, other: Bound<'_, PyAny>, op: CompareOp) -> PyResult<Py<PyAny>> {
        self.py_compare(other, op)
    }

    /// Parses a URL string and returns a MutableUrl object.
    ///
    /// # Arguments
    /// * `url_str` - The URL string to parse.
    /// * `psl` - Optional Public Suffix List type. If not provided, defaults to `PslType::Icann`.
    ///
    /// # Returns
    /// * `MutableUrl` if parsing succeeds, or a Python ValueError if parsing fails.
    // The factory does not use a class argument. A static method avoids
    // allocating a bound built-in method on every URL.parse lookup.
    #[staticmethod]
    #[pyo3(signature = (url_str, psl = None))]
    fn parse(url_str: &str, psl: Option<PslType>) -> PyResult<MutableUrl> {
        let u: Url = url::Url::parse(url_str)
            .map_err(|e: url::ParseError| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

        Ok(MutableUrl {
            inner:  u,
            psl: psl.unwrap_or(PslType::Icann),
            domain_info_cache: OnceCell::new(),
        })
    }
}
