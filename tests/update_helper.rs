use std::io::{Read, Seek, SeekFrom, Write};
use std::net::{TcpListener, TcpStream};
use std::process::{Command, ExitStatus, Stdio};
use std::thread::JoinHandle;
use std::time::Duration;

use stoei::update::HTTP_HELPER_COMMAND;

type Requests = Vec<Vec<u8>>;

fn response(status: &str, body: &[u8]) -> Vec<u8> {
    format!(
        "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    )
    .into_bytes()
    .into_iter()
    .chain(body.iter().copied())
    .collect()
}

fn request(socket: &mut TcpStream) -> Vec<u8> {
    socket
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    socket
        .set_write_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    let mut request = Vec::new();
    while request.len() < 8192 && !request.ends_with(b"\r\n\r\n") {
        let mut byte = [0];
        socket.read_exact(&mut byte).unwrap();
        request.push(byte[0]);
    }
    assert!(request.ends_with(b"\r\n\r\n"));
    request
}

fn server_responses(responses: Vec<Vec<u8>>) -> (String, JoinHandle<Requests>) {
    assert!(responses.len() <= 8);
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let handle = std::thread::spawn(move || {
        let mut requests = Vec::new();
        for response in responses {
            let (mut socket, _) = listener.accept().unwrap();
            let request = request(&mut socket);
            if request == b"STOP\r\n\r\n" {
                break;
            }
            socket.write_all(&response).unwrap();
            requests.push(request);
        }
        requests
    });
    (format!("http://{address}/release"), handle)
}

fn server(status: &str, body: &[u8]) -> (String, JoinHandle<Requests>) {
    server_responses(vec![response(status, body)])
}

fn finish_server(url: &str, server: JoinHandle<Requests>) -> Requests {
    let address = url
        .strip_prefix("http://")
        .unwrap()
        .split('/')
        .next()
        .unwrap();
    if let Ok(mut socket) = TcpStream::connect(address) {
        let _ = socket.write_all(b"STOP\r\n\r\n");
    }
    server.join().unwrap()
}

fn helper(url: &str, limit: u64) -> (ExitStatus, Vec<u8>, String) {
    let mut stdout = tempfile::tempfile().unwrap();
    let mut stderr = tempfile::tempfile().unwrap();
    let mut command = Command::new(env!("CARGO_BIN_EXE_stoei"));
    command
        .args([HTTP_HELPER_COMMAND, url, "5000", &limit.to_string()])
        .stdin(Stdio::null())
        .stdout(stdout.try_clone().unwrap())
        .stderr(stderr.try_clone().unwrap());
    for variable in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ] {
        command.env_remove(variable);
    }
    let status = command.status().unwrap();
    stdout.seek(SeekFrom::Start(0)).unwrap();
    stderr.seek(SeekFrom::Start(0)).unwrap();
    let mut body = Vec::new();
    let mut diagnostic = String::new();
    stdout.read_to_end(&mut body).unwrap();
    stderr.read_to_string(&mut diagnostic).unwrap();
    (status, body, diagnostic)
}

#[test]
fn helper_streams_binary_data_without_stdout_decoration() {
    let body = b"\0stoei\xff\n";
    let (url, server) = server("200 OK", body);
    let (status, actual, diagnostic) = helper(&url, body.len() as u64);
    let request = finish_server(&url, server).remove(0);
    assert!(status.success(), "{diagnostic}");
    assert_eq!(actual, body);
    assert!(diagnostic.is_empty());
    let request = String::from_utf8(request).unwrap().to_ascii_lowercase();
    assert!(request.starts_with("get /release http/1.1\r\n"));
    assert!(request.contains("user-agent: stoei\r\n"));
}

fn proxy_free_helper(directory: &std::path::Path) -> std::path::PathBuf {
    use std::os::unix::fs::PermissionsExt;

    let path = directory.join("http-helper");
    let executable = env!("CARGO_BIN_EXE_stoei").replace('\'', "'\\''");
    std::fs::write(
        &path,
        format!(
            "#!/bin/sh\nunset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy\nexec '{executable}' \"$@\"\n"
        ),
    )
    .unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
    path
}

fn archive(binary: &[u8]) -> Vec<u8> {
    let gzip = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
    let mut archive = tar::Builder::new(gzip);
    let mut header = tar::Header::new_gnu();
    header.set_size(binary.len() as u64);
    header.set_mode(0o755);
    header.set_cksum();
    archive.append_data(&mut header, "stoei", binary).unwrap();
    archive.into_inner().unwrap().finish().unwrap()
}

fn client(url: &str) -> stoei::update::ReleaseClient {
    let origin = url.trim_end_matches("/release").to_owned();
    stoei::update::ReleaseClient {
        api_base: origin.clone(),
        download_base: origin,
    }
}

#[test]
fn parent_latest_and_apply_use_the_real_helper_and_verified_atomic_replacement() {
    use sha2::{Digest, Sha256};
    use std::os::unix::fs::PermissionsExt;
    use std::sync::atomic::AtomicBool;

    let directory = tempfile::tempdir().unwrap();
    let helper = proxy_free_helper(directory.path());
    let destination = directory.path().join("stoei");
    std::fs::write(&destination, b"old binary").unwrap();
    let binary = b"new binary\0";
    let archive = archive(binary);
    let asset =
        stoei::update::asset_name("v1.2.3", std::env::consts::OS, std::env::consts::ARCH).unwrap();
    let checksum = format!("{:x}  {asset}\n", Sha256::digest(&archive));
    let (url, server) = server_responses(vec![
        response("200 OK", br#"{"tag_name":"v1.2.3"}"#),
        response("200 OK", &archive),
        response("200 OK", checksum.as_bytes()),
    ]);
    let client = client(&url);
    let cancelled = AtomicBool::new(false);
    let latest = client.latest_with_helper(&helper, &cancelled);
    let applied = latest
        .as_ref()
        .map_err(Clone::clone)
        .and_then(|tag| client.apply_with_helper(tag, &destination, &helper, &cancelled));
    let requests = finish_server(&url, server);
    assert_eq!(latest.unwrap(), "v1.2.3");
    applied.unwrap();
    assert_eq!(std::fs::read(&destination).unwrap(), binary);
    assert_eq!(
        std::fs::metadata(&destination)
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o755
    );
    assert_eq!(requests.len(), 3);
    assert!(requests[0].starts_with(b"GET /repos/pjhartout/stoei/releases/latest HTTP/1.1\r\n"));
    assert!(requests[1].starts_with(
        format!("GET /pjhartout/stoei/releases/download/v1.2.3/{asset} HTTP/1.1\r\n").as_bytes()
    ));
    assert!(
        requests[2].starts_with(
            b"GET /pjhartout/stoei/releases/download/v1.2.3/checksums.txt HTTP/1.1\r\n"
        )
    );
}

#[test]
fn parent_release_lookup_retains_http_status_errors() {
    let directory = tempfile::tempdir().unwrap();
    let helper = proxy_free_helper(directory.path());
    let (url, server) = server("404 Not Found", b"missing");
    let result =
        client(&url).latest_with_helper(&helper, &std::sync::atomic::AtomicBool::new(false));
    finish_server(&url, server);
    assert!(result.unwrap_err().contains("404"));
}

#[test]
fn parent_checksum_failure_preserves_the_existing_binary() {
    let directory = tempfile::tempdir().unwrap();
    let helper = proxy_free_helper(directory.path());
    let destination = directory.path().join("stoei");
    std::fs::write(&destination, b"old binary").unwrap();
    let archive = archive(b"new binary");
    let asset =
        stoei::update::asset_name("v1.2.3", std::env::consts::OS, std::env::consts::ARCH).unwrap();
    let checksum = format!("{}  {asset}\n", "0".repeat(64));
    let (url, server) = server_responses(vec![
        response("200 OK", &archive),
        response("200 OK", checksum.as_bytes()),
    ]);
    let result = client(&url).apply_with_helper(
        "v1.2.3",
        &destination,
        &helper,
        &std::sync::atomic::AtomicBool::new(false),
    );
    finish_server(&url, server);
    assert!(result.unwrap_err().contains("checksum mismatch"));
    assert_eq!(std::fs::read(&destination).unwrap(), b"old binary");
}

#[test]
fn helper_rejects_oversized_bodies_with_bounded_output() {
    let (url, server) = server("200 OK", b"0123456789");
    let (status, body, diagnostic) = helper(&url, 4);
    finish_server(&url, server);
    assert!(!status.success());
    assert_eq!(body, b"01234");
    assert!(diagnostic.contains("HTTP response exceeds 4 bytes"));
}

#[test]
fn helper_preserves_http_failures_and_is_omitted_from_help() {
    let (url, server) = server("404 Not Found", b"missing");
    let (status, body, diagnostic) = helper(&url, 1024);
    finish_server(&url, server);
    assert!(!status.success());
    assert!(body.is_empty());
    assert!(diagnostic.contains("404"));
    let help = Command::new(env!("CARGO_BIN_EXE_stoei"))
        .arg("--help")
        .output()
        .unwrap();
    assert!(help.status.success());
    assert!(
        !String::from_utf8(help.stdout)
            .unwrap()
            .contains(HTTP_HELPER_COMMAND)
    );
}
