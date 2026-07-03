// STTLive desktop launcher.
//
// A thin native wrapper around the two EXISTING local servers:
//   * STT  — WhisperLiveKit `whisperlivekit-server` on http://localhost:8000
//   * TTS  — VieNeu-TTS sidecar               on http://localhost:8011
//
// It does NOT reimplement either engine. It only:
//   1. checks whether each server is already up (health endpoint),
//   2. starts a server (via the repo's platform launch scripts) if — and only if
//      — it is not already running,
//   3. shows the existing STT web UI inside a desktop window (see ui/index.html,
//      which embeds :8000 in an iframe),
//   4. exposes health/status + a "start TTS" command to the frontend,
//   5. on exit, stops ONLY the child processes it started itself — never a
//      server that was already running before the app launched.
//
// HOW it starts a server is NOT hard-coded per platform here. It is read from an
// OS-aware command map (scripts/launch.config.json) so backend commands can be
// changed without recompiling. macOS/Windows/Linux each map to their own script.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{Manager, RunEvent, State};

const STT_HEALTH_URL: &str = "http://localhost:8000/health";
const STT_UI_URL: &str = "http://localhost:8000";
const TTS_HEALTH_URL: &str = "http://localhost:8011/tts/health";
const TTS_UI_URL: &str = "http://localhost:8011";

/// Which server a launch command starts.
#[derive(Clone, Copy)]
enum Service {
    Stt,
    Tts,
}

/// One launch command: a program plus its args. Relative paths resolve against
/// the repo root (we spawn with `current_dir(repo)`).
#[derive(Deserialize, Clone)]
struct LaunchCmd {
    program: String,
    #[serde(default)]
    args: Vec<String>,
}

/// The STT + TTS launch commands for a single platform.
#[derive(Deserialize, Clone)]
struct PlatformCmds {
    stt: LaunchCmd,
    tts: LaunchCmd,
}

impl PlatformCmds {
    fn get(&self, svc: Service) -> &LaunchCmd {
        match svc {
            Service::Stt => &self.stt,
            Service::Tts => &self.tts,
        }
    }
}

/// Shared runtime state. A `Some(Child)` in a slot means "this app started that
/// server and still owns it" — the ONLY processes we are allowed to kill.
#[derive(Default)]
struct AppState {
    stt: Mutex<Option<Child>>,
    tts: Mutex<Option<Child>>,
    repo_root: Mutex<Option<PathBuf>>,
    /// OS-aware launch commands resolved once at startup.
    cmds: Mutex<Option<PlatformCmds>>,
}

#[derive(Serialize, Clone)]
struct ServiceStatus {
    /// Health endpoint reachable right now (regardless of who started it).
    running: bool,
    /// We spawned it and still track the child handle (so we may stop it).
    started_by_app: bool,
    ui_url: String,
}

/// Returns true if an HTTP server answers at `url` (any status = the port is
/// serving; only a transport error counts as "down"). Short timeout so the UI
/// stays responsive while a server is still booting.
fn http_up(url: &str) -> bool {
    let agent = ureq::AgentBuilder::new()
        .timeout(Duration::from_millis(800))
        .build();
    match agent.get(url).call() {
        Ok(_) => true,
        Err(ureq::Error::Status(_, _)) => true, // responded (e.g. 503 while loading)
        Err(ureq::Error::Transport(_)) => false, // nobody listening
    }
}

/// Find the Speech2Text repo root so we can locate `scripts/`.
/// Priority: `$STTLIVE_REPO` → walk up from CWD → walk up from the executable.
/// A directory qualifies when it contains the launch config or the macOS scripts
/// (both are checked so detection works regardless of host OS).
fn find_repo_root() -> Option<PathBuf> {
    let is_repo = |d: &Path| {
        d.join("scripts/launch.config.json").is_file()
            || (d.join("scripts/run_stt_server.sh").is_file()
                && d.join("scripts/run_tts_server.sh").is_file())
    };

    if let Ok(env) = std::env::var("STTLIVE_REPO") {
        let p = PathBuf::from(env);
        if is_repo(&p) {
            return Some(p);
        }
    }

    let mut starts: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        starts.push(cwd);
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            starts.push(dir.to_path_buf());
        }
    }
    for start in starts {
        let mut cur: Option<&Path> = Some(start.as_path());
        while let Some(d) = cur {
            if is_repo(d) {
                return Some(d.to_path_buf());
            }
            cur = d.parent();
        }
    }
    None
}

/// The key used to look up commands in launch.config.json for the current OS.
fn platform_key() -> &'static str {
    if cfg!(target_os = "macos") {
        "macos"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else {
        "linux"
    }
}

/// Built-in fallback commands (identical to scripts/launch.config.json) used if
/// the config file is missing or unparsable, so the app still works out of the box.
/// Exactly one cfg block below is compiled, and it is the function's tail
/// expression — no `return`, no unreachable code on any platform.
fn default_cmds() -> PlatformCmds {
    #[cfg(target_os = "windows")]
    {
        let ps = |script: &str| LaunchCmd {
            program: "powershell".into(),
            args: vec![
                "-NoProfile".into(),
                "-ExecutionPolicy".into(),
                "Bypass".into(),
                "-File".into(),
                format!("scripts/{script}"),
            ],
        };
        PlatformCmds {
            stt: ps("run_stt_windows.ps1"),
            tts: ps("run_tts_windows.ps1"),
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        let sh = |script: &str| LaunchCmd {
            program: "bash".into(),
            args: vec![format!("scripts/{script}")],
        };
        #[cfg(target_os = "macos")]
        {
            PlatformCmds {
                stt: sh("run_stt_server.sh"),
                tts: sh("run_tts_server.sh"),
            }
        }
        #[cfg(not(target_os = "macos"))]
        {
            PlatformCmds {
                stt: sh("run_stt_linux.sh"),
                tts: sh("run_tts_linux.sh"),
            }
        }
    }
}

/// Load the OS-aware launch commands: `$STTLIVE_LAUNCH_CONFIG` or
/// `<repo>/scripts/launch.config.json`, keyed by the current platform. Any
/// problem (missing file, bad JSON, missing platform key) falls back to defaults.
fn load_launch_config(repo: &Path) -> PlatformCmds {
    let path = std::env::var("STTLIVE_LAUNCH_CONFIG")
        .map(PathBuf::from)
        .unwrap_or_else(|_| repo.join("scripts").join("launch.config.json"));

    let parsed = std::fs::read_to_string(&path)
        .ok()
        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
        .and_then(|v| v.get(platform_key()).cloned())
        .and_then(|pv| serde_json::from_value::<PlatformCmds>(pv).ok());

    parsed.unwrap_or_else(|| {
        eprintln!(
            "STTLive: using built-in launch commands (config not found/invalid at {}).",
            path.display()
        );
        default_cmds()
    })
}

/// Spawn the launch command for a service. The macOS/Linux scripts `exec` their
/// server, so the child's PID *is* the server — killing it stops the server
/// cleanly. (On Windows, PowerShell cannot exec-replace; see the Windows notes
/// in docs/DESKTOP_APP.md about process-tree cleanup.)
fn spawn_service(repo: &Path, cmds: &PlatformCmds, svc: Service) -> std::io::Result<Child> {
    let cmd = cmds.get(svc);
    Command::new(&cmd.program)
        .args(&cmd.args)
        .current_dir(repo)
        .spawn()
}

/// Kill a child ONLY if we own it (slot is `Some`). Never touches a server that
/// was already running when the app started (that slot stays `None`).
fn stop_owned(slot: &Mutex<Option<Child>>) {
    if let Ok(mut guard) = slot.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn status_of(url: &str, ui_url: &str, slot: &Mutex<Option<Child>>) -> ServiceStatus {
    let started_by_app = slot.lock().map(|g| g.is_some()).unwrap_or(false);
    ServiceStatus {
        running: http_up(url),
        started_by_app,
        ui_url: ui_url.to_string(),
    }
}

#[tauri::command]
fn stt_status(state: State<AppState>) -> ServiceStatus {
    status_of(STT_HEALTH_URL, STT_UI_URL, &state.stt)
}

#[tauri::command]
fn tts_status(state: State<AppState>) -> ServiceStatus {
    status_of(TTS_HEALTH_URL, TTS_UI_URL, &state.tts)
}

/// Start STT if nothing is already serving :8000. Safe to call repeatedly.
#[tauri::command]
fn start_stt(state: State<AppState>) -> Result<ServiceStatus, String> {
    ensure_started(&state, STT_HEALTH_URL, &state.stt, Service::Stt)?;
    Ok(status_of(STT_HEALTH_URL, STT_UI_URL, &state.stt))
}

/// Start TTS only when needed (e.g. the user opens the Text-to-Speech tab).
/// No-ops if a TTS server is already up — including an external one, which we
/// will never adopt or kill.
#[tauri::command]
fn start_tts(state: State<AppState>) -> Result<ServiceStatus, String> {
    ensure_started(&state, TTS_HEALTH_URL, &state.tts, Service::Tts)?;
    Ok(status_of(TTS_HEALTH_URL, TTS_UI_URL, &state.tts))
}

/// Stop a server the app started. Refuses (harmlessly) if we don't own it.
#[tauri::command]
fn stop_tts(state: State<AppState>) -> ServiceStatus {
    stop_owned(&state.tts);
    status_of(TTS_HEALTH_URL, TTS_UI_URL, &state.tts)
}

/// Core "start only if needed, don't double-start, don't adopt external" logic.
fn ensure_started(
    state: &State<AppState>,
    health_url: &str,
    slot: &Mutex<Option<Child>>,
    svc: Service,
) -> Result<(), String> {
    // Already serving (ours or external) → nothing to do.
    if http_up(health_url) {
        return Ok(());
    }
    // We already spawned one that's still booting → don't spawn a second.
    if slot.lock().map(|g| g.is_some()).unwrap_or(false) {
        return Ok(());
    }
    let repo = state
        .repo_root
        .lock()
        .ok()
        .and_then(|g| g.clone())
        .ok_or_else(|| {
            "Could not locate the Speech2Text repo. Launch the app from the repo \
             or set the STTLIVE_REPO environment variable."
                .to_string()
        })?;
    let cmds = state
        .cmds
        .lock()
        .ok()
        .and_then(|g| g.clone())
        .unwrap_or_else(default_cmds);
    let child = spawn_service(&repo, &cmds, svc)
        .map_err(|e| format!("Failed to launch {}: {e}", cmds.get(svc).program))?;
    if let Ok(mut guard) = slot.lock() {
        *guard = Some(child);
    }
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            stt_status,
            tts_status,
            start_stt,
            start_tts,
            stop_tts
        ])
        .setup(|app| {
            let state = app.state::<AppState>();
            let repo = find_repo_root();
            if let Some(r) = &repo {
                if let Ok(mut guard) = state.repo_root.lock() {
                    *guard = Some(r.clone());
                }
                // Resolve the OS-aware launch commands once, up front.
                let cmds = load_launch_config(r);
                if let Ok(mut guard) = state.cmds.lock() {
                    *guard = Some(cmds);
                }
            } else {
                eprintln!(
                    "STTLive: repo root not found. STT will NOT be auto-started. \
                     Set STTLIVE_REPO to the Speech2Text checkout."
                );
            }

            // Auto-start STT — but only if :8000 isn't already served by an
            // external process (which we must leave untouched).
            if !http_up(STT_HEALTH_URL) {
                if let Some(r) = &repo {
                    let cmds = state
                        .cmds
                        .lock()
                        .ok()
                        .and_then(|g| g.clone())
                        .unwrap_or_else(default_cmds);
                    match spawn_service(r, &cmds, Service::Stt) {
                        Ok(child) => {
                            if let Ok(mut guard) = state.stt.lock() {
                                *guard = Some(child);
                            }
                        }
                        Err(e) => eprintln!("STTLive: failed to start STT: {e}"),
                    }
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the STTLive desktop app")
        .run(|app_handle, event| {
            // Clean up ONLY app-started children on exit.
            if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
                let state = app_handle.state::<AppState>();
                stop_owned(&state.stt);
                stop_owned(&state.tts);
            }
        });
}
