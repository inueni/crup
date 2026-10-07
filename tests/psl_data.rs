// Exercise the Rust-only update code without linking a Python interpreter.
#[path = "../src/psl_data.rs"]
mod psl_data;

use publicsuffix::Psl;
use std::{
    fs,
    io::{Read, Write},
    net::TcpListener,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Barrier,
    },
    thread,
    time::Duration,
};

const ORIGINAL: &str = "// ===BEGIN ICANN DOMAINS===\ninvalid\nco.invalid\n// ===END ICANN DOMAINS===\n// ===BEGIN PRIVATE DOMAINS===\nhosted.invalid\n// ===END PRIVATE DOMAINS===\n";
const REPLACEMENT: &str = "// ===BEGIN ICANN DOMAINS===\ninvalid\n// ===END ICANN DOMAINS===\n// ===BEGIN PRIVATE DOMAINS===\nhosted.invalid\n// ===END PRIVATE DOMAINS===\n";

fn serve_response(
    status: u16,
    text: &str,
    extra_length: usize,
) -> (String, thread::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}/psl", listener.local_addr().unwrap());
    let text = text.to_owned();
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        let mut request = Vec::new();
        let mut buffer = [0; 1024];
        while !request.windows(4).any(|w| w == b"\r\n\r\n") {
            let count = stream.read(&mut buffer).unwrap();
            assert!(count > 0);
            request.extend_from_slice(&buffer[..count]);
        }
        write!(
            stream,
            "HTTP/1.1 {status} Test\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{text}",
            text.len() + extra_length
        )
        .unwrap();
    });
    (url, server)
}

fn agent() -> ureq::Agent {
    ureq::Agent::config_builder().proxy(None).build().into()
}

#[test]
fn valid_download_creates_or_replaces_cache_and_returns_new_lists() {
    for existing in [false, true] {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("nested/psl.dat");
        if existing {
            fs::create_dir(path.parent().unwrap()).unwrap();
            fs::write(&path, ORIGINAL).unwrap();
        }
        let (url, server) = serve_response(200, REPLACEMENT, 0);
        let lists = psl_data::update_cache(&path, &agent(), &url, Duration::from_secs(5)).unwrap();
        server.join().unwrap();
        assert_eq!(fs::read_to_string(&path).unwrap(), REPLACEMENT);
        let host = b"www.example.co.invalid";
        assert_eq!(lists.all.domain(host).unwrap().as_bytes(), b"co.invalid");
        assert_eq!(lists.icann.domain(host).unwrap().as_bytes(), b"co.invalid");
        assert_eq!(
            lists
                .private
                .domain(b"x.hosted.invalid")
                .unwrap()
                .as_bytes(),
            b"x.hosted.invalid"
        );
        assert_eq!(
            psl_data::read_lists(&path)
                .unwrap()
                .all
                .domain(host)
                .unwrap()
                .as_bytes(),
            b"co.invalid"
        );
    }
}

#[test]
fn failed_or_invalid_download_keeps_existing_cache() {
    for (status, text, extra_length) in [
        (500, REPLACEMENT, 0),
        (200, "com\n", 0),
        (200, REPLACEMENT, 5),
    ] {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("psl.dat");
        fs::write(&path, ORIGINAL).unwrap();
        let (url, server) = serve_response(status, text, extra_length);
        let result = psl_data::update_cache(&path, &agent(), &url, Duration::from_secs(5));
        server.join().unwrap();
        assert!(
            result.is_err(),
            "accepted invalid download: {status}, {extra_length}"
        );
        assert_eq!(fs::read_to_string(&path).unwrap(), ORIGINAL);
        assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
    }
}

#[test]
fn readers_see_complete_old_or_new_files_during_replacement() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("psl.dat");
    let old = format!("{}{}", "// old comment\n".repeat(5000), ORIGINAL);
    let new = format!("{}{}", "// new comment\n".repeat(5000), REPLACEMENT);
    fs::write(&path, &old).unwrap();
    let done = Arc::new(AtomicBool::new(false));
    let reads = Arc::new(AtomicUsize::new(0));
    let start = Arc::new(Barrier::new(2));
    let reader = {
        let (path, old, new) = (path.clone(), old.clone(), new.clone());
        let (done, reads, start) = (done.clone(), reads.clone(), start.clone());
        thread::spawn(move || {
            while !done.load(Ordering::Acquire) {
                let text = fs::read_to_string(&path).unwrap();
                assert!(text == old || text == new, "observed a partial cache file");

                if reads.fetch_add(1, Ordering::Relaxed) == 0 {
                    start.wait();
                }
            }
        })
    };
    start.wait();
    for index in 0..40 {
        psl_data::write_atomically(&path, if index % 2 == 0 { &new } else { &old }).unwrap();
    }
    done.store(true, Ordering::Release);
    reader.join().unwrap();
    assert!(reads.load(Ordering::Relaxed) > 0);
    assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
}

#[test]
fn failed_replacement_cleans_up_temporary_file() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("psl.dat");
    fs::create_dir(&path).unwrap();
    fs::write(path.join("keep"), ORIGINAL).unwrap();
    assert!(psl_data::write_atomically(&path, REPLACEMENT).is_err());
    assert_eq!(fs::read_to_string(path.join("keep")).unwrap(), ORIGINAL);
    assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
}

#[test]
fn timeout_also_covers_the_response_body() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("psl.dat");
    fs::write(&path, ORIGINAL).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}/psl", listener.local_addr().unwrap());
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        assert!(stream.read(&mut [0; 4096]).unwrap() > 0);
        write!(
            stream,
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            REPLACEMENT.len()
        )
        .unwrap();
        stream.flush().unwrap();
        thread::sleep(Duration::from_millis(500));
    });
    let error =
        psl_data::update_cache(&path, &agent(), &url, Duration::from_millis(100)).unwrap_err();
    server.join().unwrap();
    assert!(error.to_lowercase().contains("timeout"), "{error}");
    assert_eq!(fs::read_to_string(path).unwrap(), ORIGINAL);
}

#[cfg(unix)]
#[test]
fn unwritable_directory_does_not_truncate_existing_writable_cache() {
    use std::os::unix::fs::PermissionsExt;

    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("psl.dat");
    fs::write(&path, ORIGINAL).unwrap();
    let permissions = fs::metadata(dir.path()).unwrap().permissions();
    fs::set_permissions(dir.path(), fs::Permissions::from_mode(0o500)).unwrap();
    // Privileged users can bypass permission bits; this case needs normal access.
    let privileged = fs::write(dir.path().join("probe"), "").is_ok();
    let result = if privileged {
        None
    } else {
        Some(psl_data::write_atomically(&path, REPLACEMENT))
    };
    fs::set_permissions(dir.path(), permissions).unwrap();
    if let Some(result) = result {
        assert!(result.is_err());
        assert_eq!(fs::read_to_string(&path).unwrap(), ORIGINAL);
        assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
    }
}
