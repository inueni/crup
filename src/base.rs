use pyo3::{
    basic::CompareOp,
    prelude::*,
    types::{PyAny, PyDict, PyString}
};
use std::{
    collections::hash_map::DefaultHasher,
    hash::{Hash, Hasher},
};
use once_cell::sync::OnceCell;
use url::{Host, Url};
use crate::mutable_url::MutableUrl;
use crate::parsed_url::ParsedUrl;
use crate::psl::{DomainInfo, DomainMatch, PslType, registered_domain};

pub trait BaseUrl {
    fn inner(&self) -> &Url;
    fn psl(&self) -> PslType;
    fn domain_info_cache(&self) -> &OnceCell<Option<DomainMatch>>;

    fn domain_match(&self) -> Option<&DomainMatch> {
        self.domain_info_cache().get_or_init(|| {
            self.inner().domain().and_then(|d: &str| registered_domain(d, self.psl()))
        }).as_ref()
    }

    fn domain_info(&self) -> Option<DomainInfo> {
        let host = self.inner().domain()?;
        self.domain_match().map(|domain| domain.info(host))
    }

    fn domain<'py>(&self, py: Python<'py>) -> Option<Bound<'py, PyString>> {
        let host = self.inner().domain()?;
        self.domain_match().map(|domain| domain.python_domain(py, host))
    }

    fn host_ip_version(&self) -> Option<u8> {
        match self.inner().host() {
            Some(Host::Ipv4(_)) => Some(4),
            Some(Host::Ipv6(_)) => Some(6),
            _ => None,
        }
    }

    fn path_parts(&self) -> PyResult<Vec<String>> {
        let segments: Vec<String> = self.inner().path_segments()
            .ok_or_else(|| PyErr::new::<pyo3::exceptions::PyValueError, _>("Invalid path segments"))?
            .filter_map(|s: &str| if !s.is_empty() { Some(s.to_string()) } else { None })
            .collect();
        Ok(segments)
    }

    fn query_params(&self, py: Python) -> PyResult<Py<PyAny>> {
        let dict: Bound<'_, PyDict> = PyDict::new(py);
        for (k, v) in self.inner().query_pairs() {
            dict.set_item(k.as_ref(), v.as_ref())?;
        }
        Ok(dict.into())
    }

    // python dunder methods
    fn py_repr(&self, class_name: &str) -> String {
        format!(
            "<crup.{}(scheme='{}', netloc='{}', path='{}', query='{}', fragment='{}')>",
            class_name,
            self.inner().scheme(),
            self.inner().authority(),
            self.inner().path(),
            self.inner().query().unwrap_or(""),
            self.inner().fragment().unwrap_or(""),
        )
    }

    fn py_compare(&self, other: Bound<'_, PyAny>, op: CompareOp) -> PyResult<Py<PyAny>> {
        let py = other.py();
        if !matches!(op, CompareOp::Eq | CompareOp::Ne) {
            return Ok(py.NotImplemented());
        }

        let equal = if let Ok(other_url) = other.cast::<ParsedUrl>() {
            self.inner() == other_url.try_borrow()?.inner()
        } else if let Ok(other_url) = other.cast::<MutableUrl>() {
            self.inner() == other_url.try_borrow()?.inner()
        } else {
            return Ok(py.NotImplemented());
        };
        let result = if matches!(op, CompareOp::Eq) { equal } else { !equal };
        Ok(result.into_pyobject(py)?.to_owned().into_any().unbind())
    }

    fn py_hash(&self) -> u64 {
        let mut hasher: DefaultHasher = DefaultHasher::new();
        self.inner().hash(&mut hasher);
        hasher.finish()
    }

}
