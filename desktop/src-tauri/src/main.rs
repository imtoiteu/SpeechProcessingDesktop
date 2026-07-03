// STTLive desktop launcher.
//
// A thin native wrapper around the STT + TTS servers:
//   * STT  — WhisperLiveKit `whisperlivekit-server`  (default http://localhost:8000)
//   * TTS  — VieNeu-TTS sidecar                       (default http://localhost:8011)
//
// It does NOT reimplement either engine. It supervises them according to a small
// user-editable desktop config (see DesktopConfig) with two runtime modes:
//
//   * Local Managed Mode — start/stop the local servers via the repo's OS-aware
//     launch scripts (scripts/launch.config.json), health-check them, and stop
//     ONLY processes this app started.
//   * Remote Server Mode — connect to STT/TTS URLs on another machine. Never start
//     or kill any local process; only health-check and embed the remote UIs.
//
// The config is edited from the desktop Settings UI and persisted to the OS app
// config dir (<config_dir>/STTLive/config.json). scripts/launch.config.json remains
// the built-in START-COMMAND map for Local mode; the desktop config governs URLs,
// mode, and auto-start.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{Manager, RunEvent, State};

// =====================================================================
// Desktop connection config (edited in the Settings UI, persisted to disk)
// =====================================================================

fn def_mode() -> String {
    "local".into()
}
fn def_stt_url() -> String {
    "http://localhost:8000".into()
}
fn def_tts_url() -> String {
    "http://localhost:8011".into()
}
fn def_true() -> bool {
    true
}
fn def_timeout() -> u64 {
    30
}

#[derive(Serialize, Deserialize, Clone)]
struct DesktopConfig {
    /// "local" (Local Managed) or "remote" (Remote Server).
    #[serde(default = "def_mode")]
    mode: String,
    #[serde(default = "def_stt_url")]
    stt_url: String,
    #[serde(default = "def_tts_url")]
    tts_url: String,
    #[serde(default = "def_true")]
    auto_start_stt: bool,
    #[serde(default)]
    auto_start_tts: bool,
    #[serde(default = "def_timeout")]
    timeout_seconds: u64,
}

fn default_config_local() -> DesktopConfig {
    DesktopConfig {
        mode: def_mode(),
        stt_url: def_stt_url(),
        tts_url: def_tts_url(),
        auto_start_stt: true,
        auto_start_tts: false,
        timeout_seconds: def_timeout(),
    }
}

impl DesktopConfig {
    fn is_remote(&self) -> bool {
        self.mode.eq_ignore_ascii_case("remote")
    }
    fn stt_base(&self) -> String {
        self.stt_url.trim_end_matches('/').to_string()
    }
    fn tts_base(&self) -> String {
        self.tts_url.trim_end_matches('/').to_string()
    }
    fn stt_health(&self) -> String {
        format!("{}/health", self.stt_base())
    }
    fn tts_health(&self) -> String {
        format!("{}/tts/health", self.tts_base())
    }
}

// =====================================================================
// OS-aware launch commands (Local mode only) — from scripts/launch.config.json
// =====================================================================

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
    /// Current desktop connection config (None until loaded/saved).
    config: Mutex<Option<DesktopConfig>>,
}

impl AppState {
    fn config_or_default(&self) -> DesktopConfig {
        self.config
            .lock()
            .ok()
            .and_then(|g| g.clone())
            .unwrap_or_else(default_config_local)
    }
}

#[derive(Serialize, Clone)]
struct ServiceStatus {
    /// Health endpoint reachable right now (regardless of who started it).
    running: bool,
    /// We spawned it and still track the child handle (so we may stop it).
    started_by_app: bool,
    ui_url: String,
}

#[derive(Serialize, Clone)]
struct TestResult {
    reachable: bool,
    status: u16,
    message: String,
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

// =====================================================================
// Config persistence (<OS config dir>/STTLive/config.json)
// =====================================================================

fn resolve_config_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    app.path()
        .config_dir()
        .ok()
        .map(|d| d.join("STTLive").join("config.json"))
}

fn read_config_file(app: &tauri::AppHandle) -> Option<DesktopConfig> {
    let p = resolve_config_path(app)?;
    let s = std::fs::read_to_string(&p).ok()?;
    serde_json::from_str::<DesktopConfig>(&s).ok()
}

fn write_config_file(app: &tauri::AppHandle, cfg: &DesktopConfig) -> Result<(), String> {
    let p = resolve_config_path(app).ok_or("Could not resolve the OS config directory.")?;
    if let Some(dir) = p.parent() {
        std::fs::create_dir_all(dir).map_err(|e| format!("Create config dir failed: {e}"))?;
    }
    let json = serde_json::to_string_pretty(cfg).map_err(|e| e.to_string())?;
    std::fs::write(&p, json).map_err(|e| format!("Write config failed: {e}"))
}

// =====================================================================
// Repo + launch-command discovery (Local mode)
// =====================================================================

/// Find the Speech2Text repo root so we can locate `scripts/`.
/// Priority: `$STTLIVE_REPO` → walk up from CWD → walk up from the executable.
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

/// Load the OS-aware launch commands, keyed by the current platform, with a
/// built-in fallback on any problem.
fn load_launch_config(repo: &Path) -> PlatformCmds {
    let path = std::env::var("STTLIVE_LAUNCH_CONFIG")
        .map(PathBuf::from)
        .unwrap_or_else(|_| repo.join("scripts").join("launch.config.json"));

    std::fs::read_to_string(&path)
        .ok()
        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
        .and_then(|v| v.get(platform_key()).cloned())
        .and_then(|pv| serde_json::from_value::<PlatformCmds>(pv).ok())
        .unwrap_or_else(default_cmds)
}

/// Spawn the launch command for a service (Local mode only). The macOS/Linux
/// scripts `exec` their server, so the child's PID *is* the server.
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

fn status_of(health_url: &str, ui_url: &str, slot: &Mutex<Option<Child>>) -> ServiceStatus {
    let started_by_app = slot.lock().map(|g| g.is_some()).unwrap_or(false);
    ServiceStatus {
        running: http_up(health_url),
        started_by_app,
        ui_url: ui_url.to_string(),
    }
}

// =====================================================================
// Tauri commands
// =====================================================================

/// Return the saved desktop config, or null on first launch (no file yet).
#[tauri::command]
fn get_config(app: tauri::AppHandle, state: State<AppState>) -> Option<DesktopConfig> {
    if let Some(c) = state.config.lock().ok().and_then(|g| g.clone()) {
        return Some(c);
    }
    let cfg = read_config_file(&app);
    if let Some(c) = &cfg {
        if let Ok(mut g) = state.config.lock() {
            *g = Some(c.clone());
        }
    }
    cfg
}

/// The built-in defaults for a mode (used by the Settings UI to prefill).
#[tauri::command]
fn default_config(mode: String) -> DesktopConfig {
    let mut c = default_config_local();
    if mode.eq_ignore_ascii_case("remote") {
        c.mode = "remote".into();
        c.stt_url = String::new();
        c.tts_url = String::new();
        c.auto_start_stt = false;
        c.auto_start_tts = false;
    }
    c
}

/// Persist the config and update in-memory state.
#[tauri::command]
fn save_config(
    app: tauri::AppHandle,
    state: State<AppState>,
    config: DesktopConfig,
) -> Result<(), String> {
    write_config_file(&app, &config)?;
    if let Ok(mut g) = state.config.lock() {
        *g = Some(config);
    }
    Ok(())
}

/// Health-check an arbitrary STT/TTS URL from the native side (no browser CORS).
/// `kind` is "stt" or "tts".
#[tauri::command]
fn test_connection(url: String, kind: String, timeout_seconds: Option<u64>) -> TestResult {
    let base = url.trim().trim_end_matches('/');
    if base.is_empty() {
        return TestResult {
            reachable: false,
            status: 0,
            message: "No URL set.".into(),
        };
    }
    let health = if kind.eq_ignore_ascii_case("tts") {
        format!("{base}/tts/health")
    } else {
        format!("{base}/health")
    };
    let secs = timeout_seconds.unwrap_or(5).clamp(1, 60);
    let agent = ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(secs))
        .build();
    match agent.get(&health).call() {
        Ok(r) => TestResult {
            reachable: true,
            status: r.status(),
            message: format!("Reachable (HTTP {}).", r.status()),
        },
        Err(ureq::Error::Status(code, _)) => TestResult {
            reachable: true,
            status: code,
            message: format!("Reachable (HTTP {code})."),
        },
        Err(ureq::Error::Transport(e)) => TestResult {
            reachable: false,
            status: 0,
            message: format!("Not reachable: {e}"),
        },
    }
}

#[tauri::command]
fn stt_status(state: State<AppState>) -> ServiceStatus {
    let cfg = state.config_or_default();
    status_of(&cfg.stt_health(), &cfg.stt_base(), &state.stt)
}

#[tauri::command]
fn tts_status(state: State<AppState>) -> ServiceStatus {
    let cfg = state.config_or_default();
    status_of(&cfg.tts_health(), &cfg.tts_base(), &state.tts)
}

/// Start STT if nothing is already serving it (Local mode only).
#[tauri::command]
fn start_stt(state: State<AppState>) -> Result<ServiceStatus, String> {
    let cfg = state.config_or_default();
    if cfg.is_remote() {
        return Err("Remote Server Mode: STT is not managed by this app.".into());
    }
    ensure_started(&state, &cfg.stt_health(), &state.stt, Service::Stt)?;
    Ok(status_of(&cfg.stt_health(), &cfg.stt_base(), &state.stt))
}

/// Start TTS on demand (Local mode only). No-ops if TTS is already up.
#[tauri::command]
fn start_tts(state: State<AppState>) -> Result<ServiceStatus, String> {
    let cfg = state.config_or_default();
    if cfg.is_remote() {
        return Err("Remote Server Mode: TTS is not managed by this app.".into());
    }
    ensure_started(&state, &cfg.tts_health(), &state.tts, Service::Tts)?;
    Ok(status_of(&cfg.tts_health(), &cfg.tts_base(), &state.tts))
}

/// Stop a server the app started. Refuses (harmlessly) if we don't own it.
#[tauri::command]
fn stop_tts(state: State<AppState>) -> ServiceStatus {
    stop_owned(&state.tts);
    let cfg = state.config_or_default();
    status_of(&cfg.tts_health(), &cfg.tts_base(), &state.tts)
}

/// Core "start only if needed, don't double-start, don't adopt external" logic.
fn ensure_started(
    state: &State<AppState>,
    health_url: &str,
    slot: &Mutex<Option<Child>>,
    svc: Service,
) -> Result<(), String> {
    if http_up(health_url) {
        return Ok(()); // already serving (ours or external)
    }
    if slot.lock().map(|g| g.is_some()).unwrap_or(false) {
        return Ok(()); // we already spawned one that's still booting
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
            get_config,
            default_config,
            save_config,
            test_connection,
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
                let cmds = load_launch_config(r);
                if let Ok(mut guard) = state.cmds.lock() {
                    *guard = Some(cmds);
                }
            } else {
                eprintln!(
                    "STTLive: repo root not found. Local Managed Mode cannot auto-start \
                     servers. Set STTLIVE_REPO to the Speech2Text checkout."
                );
            }

            // Load the saved desktop config (if any). On FIRST LAUNCH there is no
            // file: do NOT auto-start anything — the frontend shows the setup UI and
            // the user confirms the config before we start/connect.
            let handle = app.handle().clone();
            let cfg = read_config_file(&handle);
            if let Some(c) = &cfg {
                if let Ok(mut guard) = state.config.lock() {
                    *guard = Some(c.clone());
                }
                // Local Managed Mode: honor auto-start. Remote Mode: never start.
                if !c.is_remote() {
                    if c.auto_start_stt && !http_up(&c.stt_health()) {
                        if let Some(r) = &repo {
                            let cmds = state
                                .cmds
                                .lock()
                                .ok()
                                .and_then(|g| g.clone())
                                .unwrap_or_else(default_cmds);
                            match spawn_service(r, &cmds, Service::Stt) {
                                Ok(child) => {
                                    if let Ok(mut g) = state.stt.lock() {
                                        *g = Some(child);
                                    }
                                }
                                Err(e) => eprintln!("STTLive: failed to start STT: {e}"),
                            }
                        }
                    }
                    if c.auto_start_tts && !http_up(&c.tts_health()) {
                        if let Some(r) = &repo {
                            let cmds = state
                                .cmds
                                .lock()
                                .ok()
                                .and_then(|g| g.clone())
                                .unwrap_or_else(default_cmds);
                            match spawn_service(r, &cmds, Service::Tts) {
                                Ok(child) => {
                                    if let Ok(mut g) = state.tts.lock() {
                                        *g = Some(child);
                                    }
                                }
                                Err(e) => eprintln!("STTLive: failed to start TTS: {e}"),
                            }
                        }
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
