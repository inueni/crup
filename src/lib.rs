mod base;
mod psl;
mod psl_data;
mod mutable_url;
mod parsed_url;

use pyo3::prelude::*;
use pyo3::{Bound, types::PyModule};

use crate::mutable_url::MutableUrl;
use crate::parsed_url::{parse, ParsedUrl};
use crate::psl::{DomainInfo, PslType};

#[pymodule(gil_used = false)]
#[pyo3(name="_crup")]
fn crup<'py>(py: Python<'py>, m: &Bound<'py, PyModule>) -> PyResult<()> {
    psl::init(py)?;

    m.add_class::<ParsedUrl>()?;
    m.add_function(wrap_pyfunction!(parse, m)?)?;

    m.add_class::<MutableUrl>()?;
    m.add_class::<DomainInfo>()?;
    m.add_class::<PslType>()?;

    let psl_mod: Bound<'_, PyModule> = PyModule::new(py, "crup.psl")?;
    psl_mod.add_class::<PslType>()?;
    for name in ["ALL", "ICANN", "PRIVATE"] {
        psl_mod.add(name, py.get_type::<PslType>().getattr(name)?)?;
    }
    psl_mod.add_function(wrap_pyfunction!(psl::update, &psl_mod)?)?;
    psl_mod.add_function(wrap_pyfunction!(psl::get_psl_path, &psl_mod)?)?;
    m.add("psl", &psl_mod)?;

    // Adding a module attribute alone does not make dotted imports work.
    py.import("sys")?.getattr("modules")?.set_item("crup.psl", &psl_mod)?;

    Ok(())
}
