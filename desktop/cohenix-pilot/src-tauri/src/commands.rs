//! Typed Tauri commands — allowlisted operations only.

use crate::secrets::ensure_install_secrets;
use crate::state::{AppState, InstallStage};
use crate::validation::{redact_line, validate_profile, validate_site};
use crate::wsl::{lifecycle_command, provision_command, run_powershell, wsl_exec_as};
use serde::Serialize;
use serde_json::Value;
use std::fs;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, State};

pub struct SharedState(pub Mutex<AppState>);

#[derive(Clone, Serialize)]
struct ProgressPayload {
    stage: String,
    message: String,
    level: String,
}

fn emit(app: &AppHandle, stage: &str, message: &str, level: &str) {
    let _ = app.emit(
        "cohenix-progress",
        ProgressPayload {
            stage: stage.into(),
            message: redact_line(message),
            level: level.into(),
        },
    );
}

fn with_state<F, T>(state: &SharedState, f: F) -> Result<T, String>
where
    F: FnOnce(&mut AppState) -> Result<T, String>,
{
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    f(&mut guard)
}

#[tauri::command]
pub fn get_state(state: State<'_, SharedState>) -> Result<AppState, String> {
    let guard = state.0.lock().map_err(|e| e.to_string())?;
    Ok(guard.clone())
}

#[tauri::command]
pub fn save_settings(state: State<'_, SharedState>, patch: Value) -> Result<AppState, String> {
    with_state(&state, |s| {
        if let Some(v) = patch.get("distro_name").and_then(|x| x.as_str()) {
            s.distro_name = v.to_string();
        }
        if let Some(v) = patch.get("profile").and_then(|x| x.as_str()) {
            validate_profile(v).map_err(|e| e.to_string())?;
            s.profile = v.to_string();
        }
        if let Some(v) = patch.get("preferred_editor").and_then(|x| x.as_str()) {
            s.preferred_editor = v.to_string();
        }
        if let Some(v) = patch.get("http_port").and_then(|x| x.as_u64()) {
            s.http_port = v as u16;
        }
        if let Some(v) = patch.get("socketio_port").and_then(|x| x.as_u64()) {
            s.socketio_port = v as u16;
        }
        if let Some(v) = patch.get("admin_port").and_then(|x| x.as_u64()) {
            s.admin_port = v as u16;
        }
        if let Some(v) = patch.get("update_channel").and_then(|x| x.as_str()) {
            s.update_channel = v.to_string();
        }
        s.save()?;
        Ok(s.clone())
    })
}

#[derive(Serialize)]
pub struct PreflightReport {
    pub ok: bool,
    pub os_caption: String,
    pub arch: String,
    pub admin: bool,
    pub ram_gb: f64,
    pub disk_free_gb: f64,
    pub webview2: bool,
    pub wsl_installed: bool,
    pub wsl_version: Option<String>,
    pub distros: Vec<String>,
    pub ports_free: serde_json::Map<String, Value>,
    pub remediation: Vec<String>,
    pub mock: Option<bool>,
}

#[tauri::command]
pub fn run_preflight(app: AppHandle) -> Result<PreflightReport, String> {
    emit(&app, "preflight", "Running Windows preflight…", "info");
    match run_powershell("Preflight.ps1", &[]) {
        Ok(res) => {
            emit(&app, "preflight", &res.stdout, "info");
            if let Ok(v) = serde_json::from_str::<Value>(&res.stdout) {
                let mut ports = serde_json::Map::new();
                if let Some(obj) = v.get("ports").and_then(|p| p.as_object()) {
                    for (k, val) in obj {
                        ports.insert(k.clone(), val.clone());
                    }
                }
                let distros = v
                    .pointer("/wsl/distros")
                    .and_then(|d| d.as_array())
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|x| x.get("name").and_then(|n| n.as_str()).map(|s| s.to_string()))
                            .collect()
                    })
                    .unwrap_or_default();
                let remediation = v
                    .get("remediation")
                    .and_then(|r| r.as_array())
                    .map(|a| {
                        a.iter()
                            .filter_map(|x| x.as_str().map(|s| s.to_string()))
                            .collect()
                    })
                    .unwrap_or_default();
                return Ok(PreflightReport {
                    ok: v.get("ok").and_then(|x| x.as_bool()).unwrap_or(false),
                    os_caption: v
                        .pointer("/os/caption")
                        .and_then(|x| x.as_str())
                        .unwrap_or("Windows")
                        .to_string(),
                    arch: v
                        .pointer("/os/arch")
                        .and_then(|x| x.as_str())
                        .unwrap_or("unknown")
                        .to_string(),
                    admin: v.get("admin").and_then(|x| x.as_bool()).unwrap_or(false),
                    ram_gb: v.get("ramGb").and_then(|x| x.as_f64()).unwrap_or(0.0),
                    disk_free_gb: v.get("diskFreeGb").and_then(|x| x.as_f64()).unwrap_or(0.0),
                    webview2: v.get("webView2").and_then(|x| x.as_bool()).unwrap_or(false),
                    wsl_installed: v
                        .pointer("/wsl/installed")
                        .and_then(|x| x.as_bool())
                        .unwrap_or(false),
                    wsl_version: v
                        .pointer("/wsl/version")
                        .and_then(|x| x.as_str())
                        .map(|s| s.to_string()),
                    distros,
                    ports_free: ports,
                    remediation,
                    mock: None,
                });
            }
            Err(format!("Could not parse preflight JSON: {}", res.stderr))
        }
        Err(crate::wsl::WslError::NotWindows) => Ok(PreflightReport {
            ok: true,
            os_caption: "Non-Windows development host".into(),
            arch: std::env::consts::ARCH.into(),
            admin: false,
            ram_gb: 16.0,
            disk_free_gb: 64.0,
            webview2: true,
            wsl_installed: false,
            wsl_version: None,
            distros: vec![],
            ports_free: serde_json::Map::from_iter([
                ("8000".into(), Value::Bool(true)),
                ("8002".into(), Value::Bool(true)),
                ("9000".into(), Value::Bool(true)),
            ]),
            remediation: vec![
                "This is a mock preflight on a non-Windows host. Real WSL checks require Windows 11.".into(),
            ],
            mock: Some(true),
        }),
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command]
pub fn enable_wsl(app: AppHandle, state: State<'_, SharedState>) -> Result<Value, String> {
    emit(&app, "wsl_enable", "Requesting WSL enablement…", "info");
    match run_powershell("Enable-Wsl.ps1", &[]) {
        Ok(res) => {
            emit(&app, "wsl_enable", &res.stdout, if res.ok { "info" } else { "warn" });
            let restart = res.code == 3
                || res.stdout.to_lowercase().contains("restart")
                || res.stdout.contains("\"restartRequired\":true");
            if res.ok && !restart {
                with_state(&state, |s| {
                    s.stage = InstallStage::Distro;
                    s.save()?;
                    Ok(())
                })?;
            }
            Ok(serde_json::json!({
                "ok": res.ok || restart,
                "restart_required": restart,
                "message": redact_line(&format!("{} {}", res.stdout, res.stderr)),
            }))
        }
        Err(crate::wsl::WslError::NotWindows) => {
            with_state(&state, |s| {
                s.stage = InstallStage::Distro;
                s.save()
            })?;
            Ok(serde_json::json!({
                "ok": true,
                "restart_required": false,
                "message": "Mock: WSL enable skipped on non-Windows host.",
            }))
        }
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command]
pub fn create_distro(app: AppHandle, state: State<'_, SharedState>) -> Result<Value, String> {
    let distro = with_state(&state, |s| Ok(s.distro_name.clone()))?;
    emit(&app, "distro", &format!("Creating distro {distro}…"), "info");
    match run_powershell("Import-CohenixDistro.ps1", &["-DistroName", &distro]) {
        Ok(res) => {
            if !res.ok {
                return Err(redact_line(&format!("{}{}", res.stdout, res.stderr)));
            }
            // First-boot as root: write wsl.conf + cohenix user, then terminate so default user applies.
            let _ = wsl_exec_as(
                &distro,
                Some("root"),
                "apt-get update -y && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends git ca-certificates curl \
                 && git clone --depth 1 --branch version-16_cohenix https://github.com/EPIUSECX/frappe_cohenix_development.git /tmp/cohenix-src \
                 && bash /tmp/cohenix-src/scripts/native-wsl/configure-distro.sh all \
                 && mkdir -p /home/cohenix/cohenix \
                 && cp -a /tmp/cohenix-src /home/cohenix/cohenix/frappe_cohenix_development \
                 && chown -R cohenix:cohenix /home/cohenix/cohenix",
            );
            let _ = run_powershell(
                "Terminate-Distro.ps1",
                &["-DistroName", &distro],
            );
            with_state(&state, |s| {
                s.stage = InstallStage::LinuxDeps;
                s.save()?;
                Ok(())
            })?;
            Ok(serde_json::json!({"ok": true, "message": redact_line(&res.stdout)}))
        }
        Err(crate::wsl::WslError::NotWindows) => {
            with_state(&state, |s| {
                s.stage = InstallStage::LinuxDeps;
                s.save()
            })?;
            Ok(serde_json::json!({
                "ok": true,
                "message": "Mock: distro create skipped on non-Windows host.",
            }))
        }
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command]
pub fn run_provision_stage(
    app: AppHandle,
    state: State<'_, SharedState>,
    stage: String,
    profile: Option<String>,
) -> Result<Value, String> {
    if stage == "advance_preflight" {
        return with_state(&state, |s| {
            s.stage = InstallStage::WslEnable;
            s.save()?;
            Ok(serde_json::json!({"ok": true, "message": "Advanced to WSL enablement."}))
        });
    }
    if stage == "advance_wsl" {
        return with_state(&state, |s| {
            s.stage = InstallStage::Distro;
            s.save()?;
            Ok(serde_json::json!({"ok": true, "message": "Advanced to distro creation."}))
        });
    }

    let (cmd, distro, next_stage) = with_state(&state, |s| {
        if let Some(ref p) = profile {
            validate_profile(p).map_err(|e| e.to_string())?;
            s.profile = p.clone();
        }
        let mapped = match stage.as_str() {
            "linux_deps" => ("system_deps", InstallStage::PilotInstall),
            "pilot_install" => ("pilot_install", InstallStage::CohenixProvision),
            "cohenix_provision" => ("cohenix_provision", InstallStage::Verify),
            "verify" => ("verify", InstallStage::Ready),
            other => return Err(format!("unsupported stage {other}")),
        };
        let command = provision_command(s, mapped.0, profile.as_deref()).map_err(|e| e.to_string())?;
        Ok((command, s.distro_name.clone(), mapped.1))
    })?;

    // Ensure secrets exist before provision; export into WSL env via a wrapper.
    let (admin_ui, site_admin, db_root) = ensure_install_secrets().unwrap_or_else(|_| {
        // Non-Windows / keyring-less: ephemeral for mock only.
        (
            "mock-admin-ui-not-for-prod".into(),
            "mock-site-admin-not-for-prod".into(),
            "mock-db-root-not-for-prod".into(),
        )
    });

    let wrapped = format!(
        "export COHENIX_ADMIN_UI_PASSWORD='{admin_ui}' COHENIX_SITE_ADMIN_PASSWORD='{site_admin}' COHENIX_DB_ROOT_PASSWORD='{db_root}' COHENIX_REPO_URL='https://github.com/EPIUSECX/frappe_cohenix_development.git' COHENIX_REPO_BRANCH='version-16_cohenix'; {cmd}",
        admin_ui = admin_ui.replace('\'', ""),
        site_admin = site_admin.replace('\'', ""),
        db_root = db_root.replace('\'', ""),
        cmd = cmd,
    );

    emit(&app, &stage, "Starting provision stage…", "info");
    match wsl_exec_as(&distro, Some("cohenix"), &wrapped) {
        Ok(res) => {
            for line in res.stdout.lines().chain(res.stderr.lines()) {
                emit(&app, &stage, line, if res.ok { "info" } else { "error" });
            }
            if !res.ok {
                with_state(&state, |s| {
                    s.last_error = Some(redact_line(&res.stderr));
                    s.save()
                })?;
                return Err(redact_line(&format!("Stage failed: {}", res.stderr)));
            }
            with_state(&state, |s| {
                s.stage = next_stage;
                s.last_error = None;
                s.save()?;
                Ok(())
            })?;
            Ok(serde_json::json!({"ok": true, "message": "Stage completed."}))
        }
        Err(crate::wsl::WslError::NotWindows) => {
            emit(
                &app,
                &stage,
                "Mock provision on non-Windows host — advancing stage for UI development.",
                "warn",
            );
            with_state(&state, |s| {
                s.stage = next_stage;
                s.save()
            })?;
            Ok(serde_json::json!({
                "ok": true,
                "message": "Mock stage advanced (Windows required for real WSL provisioning).",
            }))
        }
        Err(e) => Err(e.to_string()),
    }
}

#[derive(Serialize)]
pub struct StackStatus {
    pub stage: InstallStage,
    pub wsl_running: bool,
    pub process: bool,
    pub frappe_http: bool,
    pub admin_health: bool,
    pub site_url: String,
    pub admin_url: String,
    pub profile: String,
    pub bench_name: String,
    pub site_name: String,
    pub installed_apps: Vec<String>,
}

#[tauri::command]
pub fn get_stack_status(state: State<'_, SharedState>) -> Result<StackStatus, String> {
    let snapshot = with_state(&state, |s| Ok(s.clone()))?;
    let mut status = StackStatus {
        stage: snapshot.stage.clone(),
        wsl_running: false,
        process: false,
        frappe_http: false,
        admin_health: false,
        site_url: format!("http://{}:{}/app", snapshot.site_name, snapshot.http_port),
        admin_url: format!("http://127.0.0.1:{}", snapshot.admin_port),
        profile: snapshot.profile.clone(),
        bench_name: snapshot.bench_name.clone(),
        site_name: snapshot.site_name.clone(),
        installed_apps: vec![],
    };

    let cmd = lifecycle_command(&snapshot, "status").map_err(|e| e.to_string())?;
    match wsl_exec_as(&snapshot.distro_name, Some("cohenix"), &cmd) {
        Ok(res) => {
            status.wsl_running = true;
            if let Ok(v) = serde_json::from_str::<Value>(res.stdout.trim()) {
                status.process = v.get("process").and_then(|x| x.as_bool()).unwrap_or(false);
                status.frappe_http = v.get("frappe_http").and_then(|x| x.as_bool()).unwrap_or(false);
                status.admin_health = v.get("admin_health").and_then(|x| x.as_bool()).unwrap_or(false);
            }
        }
        Err(crate::wsl::WslError::NotWindows) => {
            status.wsl_running = false;
        }
        Err(_) => {}
    }
    Ok(status)
}

#[tauri::command]
pub fn lifecycle_action(
    app: AppHandle,
    state: State<'_, SharedState>,
    action: String,
) -> Result<StackStatus, String> {
    let snapshot = with_state(&state, |s| Ok(s.clone()))?;
    let cmd = lifecycle_command(&snapshot, &action).map_err(|e| e.to_string())?;
    emit(&app, "lifecycle", &format!("Running {action}…"), "info");
    match wsl_exec_as(&snapshot.distro_name, Some("cohenix"), &cmd) {
        Ok(res) => {
            emit(&app, "lifecycle", &res.stdout, if res.ok { "info" } else { "error" });
            if !res.ok {
                return Err(redact_line(&res.stderr));
            }
        }
        Err(crate::wsl::WslError::NotWindows) => {
            emit(&app, "lifecycle", "Mock lifecycle on non-Windows host", "warn");
        }
        Err(e) => return Err(e.to_string()),
    }
    get_stack_status(state)
}

#[tauri::command]
pub fn open_url(state: State<'_, SharedState>, kind: String) -> Result<(), String> {
    let snapshot = with_state(&state, |s| Ok(s.clone()))?;
    let url = match kind.as_str() {
        "admin" => format!("http://127.0.0.1:{}", snapshot.admin_port),
        "desk" => format!("http://{}:{}/app", snapshot.site_name, snapshot.http_port),
        "editor" => {
            // Open WSL remote folder via editor URI when possible.
            let path = format!(
                "vscode-remote://wsl+{}/home/cohenix/cohenix/frappe_cohenix_development",
                snapshot.distro_name
            );
            if snapshot.preferred_editor == "cursor" {
                // Cursor understands the same remote authority scheme in recent builds.
                path
            } else {
                path
            }
        }
        other => return Err(format!("unknown open kind {other}")),
    };
    open::that(&url).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn get_logs(limit: Option<usize>) -> Result<String, String> {
    let limit = limit.unwrap_or(200);
    let path = dirs::data_local_dir()
        .unwrap_or_default()
        .join("CohenixPilot/logs/app.log");
    if !path.exists() {
        return Ok(String::new());
    }
    let text = fs::read_to_string(path).map_err(|e| e.to_string())?;
    let lines: Vec<_> = text.lines().rev().take(limit).collect();
    Ok(lines
        .into_iter()
        .rev()
        .map(redact_line)
        .collect::<Vec<_>>()
        .join("\n"))
}

#[tauri::command]
pub fn diagnostic_report(state: State<'_, SharedState>) -> Result<String, String> {
    let snapshot = with_state(&state, |s| Ok(s.clone()))?;
    Ok(format!(
        "Cohenix Pilot diagnostic (redacted)\n\
         stage={:?}\n\
         distro={}\n\
         profile={}\n\
         bench={}\n\
         site={}\n\
         ports={}/{}/{}\n\
         last_error={}\n\
         note=passwords and tokens omitted\n",
        snapshot.stage.as_str(),
        snapshot.distro_name,
        snapshot.profile,
        snapshot.bench_name,
        snapshot.site_name,
        snapshot.http_port,
        snapshot.socketio_port,
        snapshot.admin_port,
        snapshot
            .last_error
            .as_deref()
            .map(redact_line)
            .unwrap_or_else(|| "none".into())
    ))
}

#[tauri::command]
pub fn list_environments(state: State<'_, SharedState>) -> Result<Value, String> {
    let snapshot = with_state(&state, |s| Ok(s.clone()))?;
    // Prefer probing WSL; fall back to configured defaults.
    let apps = match snapshot.profile.as_str() {
        "frappe" => vec!["frappe"],
        "erp" => vec!["frappe", "erpnext"],
        "hr" | "localisation" | "full-cohenix" => vec!["frappe", "erpnext", "hrms"],
        "integrations" => vec!["frappe", "erpnext", "payments", "ecommerce_integrations"],
        _ => vec![],
    };
    Ok(serde_json::json!({
        "benches": [{
            "name": snapshot.bench_name,
            "sites": [snapshot.site_name],
            "ports": {
                "http": snapshot.http_port,
                "socketio": snapshot.socketio_port,
                "admin": snapshot.admin_port
            },
            "apps": apps
        }]
    }))
}

#[tauri::command]
pub fn create_site(app: AppHandle, state: State<'_, SharedState>, site_name: String) -> Result<Value, String> {
    validate_site(&site_name).map_err(|e| e.to_string())?;
    let snapshot = with_state(&state, |s| Ok(s.clone()))?;
    let (_, site_admin, _) = ensure_install_secrets().unwrap_or_else(|_| {
        (
            "mock".into(),
            "mock-site-admin-not-for-prod".into(),
            "mock".into(),
        )
    });
    let cmd = format!(
        "export PATH=\"$HOME/.local/bin:$HOME/pilot/bin:$PATH\"; \
         pilot --bench '{bench}' new-site '{site}' --admin-password '{pw}' --apps frappe",
        bench = snapshot.bench_name,
        site = site_name,
        pw = site_admin.replace('\'', ""),
    );
    emit(&app, "sites", &format!("Creating site {site_name}"), "info");
    match wsl_exec_as(&snapshot.distro_name, Some("cohenix"), &cmd) {
        Ok(res) if res.ok => Ok(serde_json::json!({"ok": true, "message": format!("Created {site_name}")})),
        Ok(res) => Err(redact_line(&res.stderr)),
        Err(crate::wsl::WslError::NotWindows) => Ok(serde_json::json!({
            "ok": true,
            "message": format!("Mock created {site_name} (Windows required for real create)"),
        })),
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command]
pub fn install_profile(
    app: AppHandle,
    state: State<'_, SharedState>,
    profile: String,
) -> Result<Value, String> {
    validate_profile(&profile).map_err(|e| e.to_string())?;
    with_state(&state, |s| {
        s.profile = profile.clone();
        s.save()
    })?;
    run_provision_stage(app, state, "cohenix_provision".into(), Some(profile))
}

// opener helper without pulling another crate on all targets
mod open {
    pub fn that(path: &str) -> std::io::Result<()> {
        #[cfg(target_os = "windows")]
        {
            std::process::Command::new("cmd")
                .args(["/C", "start", "", path])
                .spawn()?;
            Ok(())
        }
        #[cfg(target_os = "linux")]
        {
            std::process::Command::new("xdg-open").arg(path).spawn()?;
            Ok(())
        }
        #[cfg(target_os = "macos")]
        {
            std::process::Command::new("open").arg(path).spawn()?;
            Ok(())
        }
        #[cfg(not(any(target_os = "windows", target_os = "linux", target_os = "macos")))]
        {
            let _ = path;
            Err(std::io::Error::new(
                std::io::ErrorKind::Unsupported,
                "open not supported",
            ))
        }
    }
}
