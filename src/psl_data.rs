//! PSL loading and updates without any Python objects or interpreter calls.

use publicsuffix::{IcannList, List, PrivateList};
use std::{
    fs::{create_dir_all, read_to_string},
    io::Write,
    path::Path,
    str::FromStr,
    time::Duration,
};
use tempfile::NamedTempFile;

#[derive(Debug)]
pub(crate) struct PslLists {
    pub(crate) all: List,
    pub(crate) icann: IcannList,
    pub(crate) private: PrivateList,
}

pub(crate) fn parse_lists(text: &str) -> Result<PslLists, String> {
    let list = List::from_str(text).map_err(|e| format!("PSL data is invalid: {e}"))?;
    let icann = IcannList::from(list.clone());
    let private = PrivateList::from(list.clone());
    Ok(PslLists {
        all: list,
        icann,
        private,
    })
}

pub(crate) fn read_lists(path: &Path) -> Result<PslLists, String> {
    let text = read_to_string(path)
        .map_err(|e| format!("Failed to read PSL file at '{}': {e}", path.display()))?;
    parse_lists(&text).map_err(|e| format!("PSL file at '{}' is invalid: {e}", path.display()))
}

#[cold]
pub(crate) fn write_atomically(path: &Path, text: &str) -> Result<(), String> {
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    create_dir_all(parent)
        .map_err(|e| format!("Failed to create PSL directory '{}': {e}", parent.display()))?;

    // Use the destination directory so replacement stays on the same filesystem.
    // NamedTempFile removes an unfinished file on every error path.
    let mut file = NamedTempFile::new_in(parent)
        .map_err(|e| format!("Failed to create temporary PSL file: {e}"))?;
    file.write_all(text.as_bytes())
        .map_err(|e| format!("Failed to write PSL: {e}"))?;
    file.as_file()
        .sync_all()
        .map_err(|e| format!("Failed to flush PSL: {e}"))?;
    file.persist(path)
        .map_err(|e| format!("Failed to replace PSL file at '{}': {e}", path.display()))?;
    Ok(())
}

#[cold]
pub(crate) fn update_cache(
    path: &Path,
    agent: &ureq::Agent,
    source_url: &str,
    timeout: Duration,
) -> Result<PslLists, String> {
    let text = agent
        .get(source_url)
        .config()
        .timeout_global(Some(timeout))
        .build()
        .call()
        .map_err(|e| format!("Failed to fetch PSL: {e}"))?
        .body_mut()
        .read_to_string()
        .map_err(|e| format!("Failed to read PSL response: {e}"))?;
    let lists = parse_lists(&text).map_err(|e| format!("Downloaded PSL is invalid: {e}"))?;
    write_atomically(path, &text)?;
    Ok(lists)
}
