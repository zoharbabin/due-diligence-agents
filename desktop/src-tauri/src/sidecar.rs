//! The local Python API process: start it, read its port, stop it.
//!
//! The server exits when its stdin closes, so it ends if this app dies. `stop` also kills the
//! process group after a grace period, in case a run is still winding down.

use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

const READY_PREFIX: &str = "DD_AGENTS_LISTENING ";
const START_TIMEOUT: Duration = Duration::from_secs(60);
const STOP_GRACE: Duration = Duration::from_secs(8);

/// Read the port from the server's one-line ready message.
pub fn parse_ready_line(line: &str) -> Option<u16> {
    let json = line.trim().strip_prefix(READY_PREFIX)?;
    let value: serde_json::Value = serde_json::from_str(json).ok()?;
    u16::try_from(value.get("port")?.as_u64()?)
        .ok()
        .filter(|p| *p != 0)
}

/// Open the service log for this launch. Replaces the last launch's log, so it never grows.
pub fn open_log(path: &Path) -> std::io::Result<File> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    File::create(path)
}

/// 32 random bytes as hex. A new one for every launch.
pub fn new_token() -> String {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("system random source");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

pub struct Sidecar {
    child: Child,
    stdin: Option<ChildStdin>,
    pub port: u16,
    pub token: String,
}

impl Sidecar {
    pub fn start(
        python: &Path,
        ui_dir: &Path,
        extra_env: &HashMap<String, String>,
        log: Option<&Path>,
    ) -> Result<Sidecar, String> {
        let token = new_token();
        // Server errors go to a file, so a failed start can be diagnosed. No log means no output.
        let stderr = log
            .and_then(|path| open_log(path).ok())
            .map_or_else(Stdio::null, Stdio::from);
        let mut cmd = Command::new(python);
        cmd.args([
            "-m",
            "dd_agents",
            "serve",
            "--port",
            "0",
            "--exit-on-stdin-close",
            "--ui-dir",
        ])
        .arg(ui_dir)
        .envs(extra_env)
        .env("DD_API_TOKEN", &token)
        .env("PYTHONUNBUFFERED", "1")
        // The bundle is signed. Python must not write .pyc files into it.
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(stderr);
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            cmd.process_group(0);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
            cmd.creation_flags(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP);
        }
        let mut child = cmd
            .spawn()
            .map_err(|e| format!("Cannot start the local service ({}): {e}", python.display()))?;
        let stdin = child.stdin.take();
        let stdout = child
            .stdout
            .take()
            .ok_or("no stdout from the local service")?;

        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if let Some(port) = parse_ready_line(&line) {
                    let _ = tx.send(port);
                    break;
                }
            }
            // Keep draining so the server never blocks on a full pipe.
        });

        let mut sidecar = Sidecar {
            child,
            stdin,
            port: 0,
            token,
        };
        match rx.recv_timeout(START_TIMEOUT) {
            Ok(port) => {
                sidecar.port = port;
                Ok(sidecar)
            }
            Err(_) => {
                sidecar.stop();
                Err("The local service did not start in time.".into())
            }
        }
    }

    pub fn url(&self) -> String {
        format!("http://127.0.0.1:{}/", self.port)
    }

    /// Close stdin so the server shuts down cleanly. Kill the group if it is slow.
    pub fn stop(&mut self) {
        self.stdin.take();
        let deadline = Instant::now() + STOP_GRACE;
        while Instant::now() < deadline {
            if matches!(self.child.try_wait(), Ok(Some(_))) {
                return;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        kill_tree(&mut self.child);
        let _ = self.child.wait();
    }
}

#[cfg(unix)]
fn kill_tree(child: &mut Child) {
    // The child leads its own process group (see `process_group(0)`), so -pid reaches all of it.
    unsafe {
        libc::kill(-(child.id() as i32), libc::SIGKILL);
    }
}

#[cfg(windows)]
fn kill_tree(child: &mut Child) {
    let _ = Command::new("taskkill")
        .args(["/F", "/T", "/PID", &child.id().to_string()])
        .output();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_the_ready_line() {
        assert_eq!(
            parse_ready_line("DD_AGENTS_LISTENING {\"port\": 51234, \"host\": \"127.0.0.1\"}\n"),
            Some(51234)
        );
    }

    #[test]
    fn ignores_other_lines_and_bad_ports() {
        assert_eq!(parse_ready_line("INFO started"), None);
        assert_eq!(parse_ready_line("DD_AGENTS_LISTENING not-json"), None);
        assert_eq!(parse_ready_line("DD_AGENTS_LISTENING {\"port\": 0}"), None);
        assert_eq!(
            parse_ready_line("DD_AGENTS_LISTENING {\"port\": 70000}"),
            None
        );
    }

    #[test]
    fn tokens_are_long_and_unique() {
        let (a, b) = (new_token(), new_token());
        assert_eq!(a.len(), 64);
        assert_ne!(a, b);
    }

    #[test]
    fn the_log_is_replaced_on_each_launch() {
        use std::io::Write;
        let dir = std::env::temp_dir().join(format!("dd-log-test-{}", new_token()));
        let path = dir.join("logs").join("service.log");
        writeln!(open_log(&path).unwrap(), "first launch").unwrap();
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "first launch\n");
        drop(open_log(&path).unwrap());
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn missing_python_is_a_clear_error() {
        let err = Sidecar::start(
            Path::new("/definitely/not/python"),
            Path::new("."),
            &HashMap::new(),
            None,
        )
        .err()
        .unwrap();
        assert!(err.contains("Cannot start the local service"));
    }

    /// Needs a Python with dd-agents[app] installed: set DD_DESKTOP_PYTHON. CI sets it.
    #[test]
    fn real_server_starts_answers_and_stops() {
        use std::io::{Read, Write};
        use std::net::TcpStream;

        let Ok(python) = std::env::var("DD_DESKTOP_PYTHON") else {
            eprintln!("skipped: DD_DESKTOP_PYTHON is not set");
            return;
        };
        let mut sidecar = Sidecar::start(Path::new(&python), Path::new("."), &HashMap::new(), None)
            .expect("start");
        let get = |auth: &str| {
            let mut s = TcpStream::connect(("127.0.0.1", sidecar.port)).unwrap();
            let req = format!(
                "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{}\r\n{auth}Connection: close\r\n\r\n",
                sidecar.port
            );
            s.write_all(req.as_bytes()).unwrap();
            let mut out = String::new();
            s.read_to_string(&mut out).unwrap();
            out
        };
        assert!(get("").starts_with("HTTP/1.1 401"));
        let ok = get(&format!("Authorization: Bearer {}\r\n", sidecar.token));
        assert!(
            ok.starts_with("HTTP/1.1 200") && ok.contains("\"status\":\"ok\""),
            "{ok}"
        );

        let port = sidecar.port;
        sidecar.stop();
        assert!(
            TcpStream::connect(("127.0.0.1", port)).is_err(),
            "server still listening after stop"
        );
    }
}
