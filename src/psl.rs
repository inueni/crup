use publicsuffix::{Psl, Domain, LIST_URL};
use pyo3::prelude::*;
#[cfg(Py_GIL_DISABLED)]
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyModule, PyString};
use once_cell::sync::OnceCell;
use directories::ProjectDirs;
use crate::psl_data::{PslLists, read_lists, update_cache};
use std::{
    borrow::Cow,
    env,
    fmt,
    path::{Path, PathBuf}, 
    sync::{Mutex, RwLock, RwLockReadGuard},
    time::Duration,
};

static PSL_LISTS: OnceCell<RwLock<Option<PslLists>>> = OnceCell::new();
static WRITABLE_PSL_PATH: OnceCell<Option<PathBuf>> = OnceCell::new();
static PSL_UPDATE_LOCK: Mutex<()> = Mutex::new(());
const PSL_ENV_VAR: &str = "CRUP_PSL_PATH";
const PSL_FILENAME: &str = "public_suffix_list.dat";

#[cfg(Py_GIL_DISABLED)]
type PythonDomainCache = PyOnceLock<Py<PyString>>;
#[cfg(not(Py_GIL_DISABLED))]
type PythonDomainCache = OnceCell<Py<PyString>>;

#[pyclass(module = "crup.psl", frozen, eq, eq_int, from_py_object)]
#[derive(Clone, Debug, Copy, PartialEq)]
pub enum PslType {
    #[pyo3(name = "ALL")]
    All,
    #[pyo3(name = "ICANN")]
    Icann,
    #[pyo3(name = "PRIVATE")]
    Private,
}

#[pymethods]
impl PslType {
    fn __str__(&self) -> String {
        self.to_string()
    }

    fn __repr__(&self) -> String {
        format!("<crup.psl.{}>", self)
    }
}

impl fmt::Display for PslType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            PslType::All => write!(f, "ALL"),
            PslType::Icann => write!(f, "ICANN"),
            PslType::Private => write!(f, "PRIVATE"),
        }
    }
}

impl From<publicsuffix::Type> for PslType {
    fn from(t: publicsuffix::Type) -> Self {
        match t {
            publicsuffix::Type::Icann => PslType::Icann,
            publicsuffix::Type::Private => PslType::Private,
        }
    }
}

#[pyclass(module = "crup", frozen, eq, skip_from_py_object)]
#[derive(Clone, Debug, PartialEq)]
pub struct DomainInfo {
    #[pyo3(get)]
    pub domain: String,
    #[pyo3(get)]
    pub suffix: String,
    #[pyo3(get)]
    pub psl: Option<PslType>,
}

#[pymethods]
impl DomainInfo {
    fn __repr__(&self) -> String {
        let psl: String = match self.psl {
            Some(ref psl) => format!("'{}'", psl),
            None => "None".to_string(),
        };
        format!("<crup.DomainInfo(domain='{}', suffix='{}', psl={})>",
            self.domain,
            self.suffix,
            psl,
        )
    }
}

/// Host-relative offsets keep cached PSL results independent of URL serialization
/// changes and avoid allocating Rust strings until Python requests domain_info().
pub struct DomainMatch {
    domain_start: usize,
    suffix_start: usize,
    end: usize,
    psl: Option<PslType>,
    normalize_case: bool,
    python_domain: PythonDomainCache,
}

impl DomainMatch {
    fn new(host: &str, domain: Domain<'_>, normalize_case: bool) -> Self {
        let suffix = domain.suffix();
        Self {
            domain_start: host.len() - domain.as_bytes().len(),
            suffix_start: host.len() - suffix.as_bytes().len(),
            end: host.len() - usize::from(suffix.is_fqdn()),
            psl: suffix.typ().map(PslType::from),
            normalize_case,
            python_domain: PythonDomainCache::new(),
        }
    }

    pub fn domain<'a>(&self, host: &'a str) -> &'a str {
        &host[self.domain_start..self.end]
    }

    #[cfg(not(Py_GIL_DISABLED))]
    pub fn python_domain<'py>(&self, py: Python<'py>, host: &str) -> Bound<'py, PyString> {
        // Unicode allocation stays attached and holds the GIL in this build.
        self.python_domain
            .get_or_init(|| {
                let domain = self.domain(host);
                if self.normalize_case {
                    PyString::new(py, &domain.to_ascii_lowercase()).unbind()
                } else {
                    PyString::new(py, domain).unbind()
                }
            })
            .bind(py)
            .clone()
    }

    #[cfg(Py_GIL_DISABLED)]
    pub fn python_domain<'py>(&self, py: Python<'py>, host: &str) -> Bound<'py, PyString> {
        self.python_domain
            .get(py)
            .unwrap_or_else(|| {
                // Allocate before publishing: the cell's initializer must not call
                // Python while another attached thread could be waiting on it.
                let domain = self.domain(host);
                let value = if self.normalize_case {
                    PyString::new(py, &domain.to_ascii_lowercase()).unbind()
                } else {
                    PyString::new(py, domain).unbind()
                };
                // Concurrent first readers may allocate duplicates. Keep the winner
                // and drop any unused Python reference while still attached.
                let _ = self.python_domain.set(py, value);
                self.python_domain
                    .get(py)
                    .expect("domain cache was initialized")
            })
            .bind(py)
            .clone()
    }

    pub fn info(&self, host: &str) -> DomainInfo {
        DomainInfo {
            domain: self.normalized(self.domain(host)),
            suffix: self.normalized(&host[self.suffix_start..self.end]),
            psl: self.psl,
        }
    }

    fn normalized(&self, value: &str) -> String {
        if self.normalize_case { value.to_ascii_lowercase() } else { value.to_owned() }
    }
}

fn env_psl_path() -> Option<PathBuf> {
    env::var_os(PSL_ENV_VAR).map(PathBuf::from)
}

fn default_cache_path() -> Option<PathBuf> {
    ProjectDirs::from("com", "inueni", "crup")
        .map(|dirs: ProjectDirs| dirs.cache_dir().join(PSL_FILENAME))
}

fn resolve_writable_psl_path() -> Option<PathBuf> {
    env_psl_path().or_else(default_cache_path)
}

fn writable_psl_path() -> Option<&'static PathBuf> {
    WRITABLE_PSL_PATH.get_or_init(resolve_writable_psl_path).as_ref()
}

fn bundled_psl_path(py: Python<'_>) -> PyResult<PathBuf> {
    let files: Bound<'_, PyAny> = py.import("importlib.resources")?
        .getattr("files")?
        .call1(("crup",))?;

    files
        .call_method1("joinpath", (PSL_FILENAME,))?
        .extract()
}

fn py_warn(py: Python, message: &str) -> PyResult<()> {
    let warnings: Bound<'_, PyModule> = PyModule::import(py, "warnings")?;
    let userwarn: Bound<'_, PyAny> = py.import("builtins")?.getattr("UserWarning")?;
    warnings.call_method("warn_explicit",(message, userwarn, "crup.psl", 0),None)?;
    Ok(())
}

fn load_with_warn(path: &Path, py: Python<'_>) -> Option<PslLists> {
    match read_lists(path) {
        Ok(lists) => Some(lists),
        Err(msg) => {
            let _ = py_warn(py, &format!(
                "{}. Run `crup.psl.update()` to download a valid list.",
                msg
            ));
            None
        }
    }
}

pub fn init(py: Python<'_>) -> PyResult<()> {
    let bundled_path: PathBuf = bundled_psl_path(py)?;
    let lists_opt: Option<PslLists> = writable_psl_path()
        .and_then(|p: &PathBuf| if p.exists() { load_with_warn(p, py) } else { None })
        .or_else(|| load_with_warn(&bundled_path, py));
    if PSL_LISTS.set(RwLock::new(lists_opt)).is_err() {};
    Ok(())
}

fn runtime_lists() -> Option<RwLockReadGuard<'static, Option<PslLists>>> {
    PSL_LISTS.get()?.read().ok()
}

pub fn registered_domain(host: &str, psl_type: PslType) -> Option<DomainMatch> {
    let guard: RwLockReadGuard<'static, Option<PslLists>> = runtime_lists()?;
    let lists: &PslLists = guard.as_ref()?;
    // Non-special URL schemes can retain uppercase opaque hosts. ASCII case
    // folding preserves byte lengths, so offsets still refer to the original host.
    let normalize_case = host.bytes().any(|byte| byte.is_ascii_uppercase());
    let lookup_host = if normalize_case {
        Cow::Owned(host.to_ascii_lowercase())
    } else {
        Cow::Borrowed(host)
    };
    let domain: Option<Domain<'_>> = match psl_type {
        PslType::All => lists.all.domain(lookup_host.as_bytes()),
        PslType::Icann => lists.icann.domain(lookup_host.as_bytes()),
        // PrivateList retains the implicit wildcard and can report an ICANN
        // top-level suffix. Only actual private matches belong in PRIVATE mode.
        PslType::Private => lists.private.domain(lookup_host.as_bytes())
            .filter(|domain| domain.suffix().typ() == Some(publicsuffix::Type::Private)),
    };
    domain.map(|domain| DomainMatch::new(host, domain, normalize_case))
}

#[pyfunction]
pub fn get_psl_path(py: Python<'_>) -> PyResult<Option<Py<PyAny>>> {
    if let Some(path) = writable_psl_path() {
        Ok(Some(path.into_pyobject(py)?.unbind()))

    } else {
        Ok(None)
    }
}

#[pyfunction]
#[pyo3(signature = (*, timeout = 30.0))]
#[cold]
pub fn update(py: Python<'_>, timeout: f64) -> PyResult<()> {
    let timeout = Duration::try_from_secs_f64(timeout)
        .ok().filter(|duration| !duration.is_zero())
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
            "timeout must be a finite positive duration in seconds"
        ))?;
    let path: PathBuf = writable_psl_path().cloned().ok_or_else(|| {
        pyo3::exceptions::PyIOError::new_err(
            format!(
                "No writable PSL path available. Set {} or ensure a user cache directory is accessible.",
                PSL_ENV_VAR
            )
        )
    })?;

    // Keep Python objects (including PyErr) out of detached work: the build
    // disables PyO3's reference pool. Convert plain Rust errors after reattaching.
    py.detach(move || -> Result<(), String> {
        let lock = PSL_LISTS.get().ok_or("PSL storage is not initialized")?;
        // Serialize updates so the file and runtime list cannot be committed
        // in different orders by concurrent callers in this process.
        let _updating = PSL_UPDATE_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        let lists = update_cache(&path, &ureq::agent(), LIST_URL, timeout)?;
        *lock.write().unwrap_or_else(|p| p.into_inner()) = Some(lists);
        Ok(())
    }).map_err(pyo3::exceptions::PyIOError::new_err)
}
