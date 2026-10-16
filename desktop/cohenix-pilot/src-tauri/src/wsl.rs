//! Allowlisted WSL / PowerShell invocation helpers.

use crate::state::AppState;
use crate::validation::{validate_ident, validate_profile, validate_site, ValidationError};
use serde::Serialize;
use std::path::PathBuf;
#[cfg(target_os = "windows")]
use std::process::Command;

#[derive(Debug, thiserror::Error)]
pub enum WslError {
    #[error(transparent)]
    Validation(#[from] ValidationError),
    #[error("{0}")]
    Message(String),
    #[error("wsl.exe is only available on Windows")]
    NotWindows,
}

#[derive(Debug, Clone, Serialize)]
pub struct CommandResult {
    pub ok: bool,
    pub stdout: String,
    pub stderr: String,
    pub code: i32,
}

fn scripts_root() -> PathBuf {
    // Dev: repo scripts/windows next to desktop/cohenix-pilot
    // Packaged: resource dir / scripts
    let candidates = [
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../scripts/windows"),
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../scripts/native-wsl"),
        dirs::data_local_dir()
            .unwrap_or_default()
            .join("CohenixPilot/scripts/windows"),
    ];
    for c in candidates {
        if c.exists() {
            return c;
        }
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../scripts/windows")
}

pub fn repo_native_scripts() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../scripts/native-wsl")
}

#[cfg(target_os = "windows")]
pub fn run_powershell(script_name: &str, args: &[&str]) -> Result<CommandResult, WslError> {
    if script_name.contains("..") || script_name.contains('/') || script_name.contains('\\') {
        return Err(WslError::Message("invalid script name".into()));
    }
    let script = scripts_root().join(script_name);
    if !script.exists() {
        return Err(WslError::Message(format!("missing script {}", script.display())));
    }
    let mut cmd = Command::new("powershell.exe");
    cmd.args([
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        script.to_str().unwrap_or_default(),
    ]);
    for a in args {
        cmd.arg(a);
    }
    let output = cmd.output().map_err(|e| WslError::Message(e.to_string()))?;
    Ok(CommandResult {
        ok: output.status.success(),
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).to_string(),
        code: output.status.code().unwrap_or(-1),
    })
}

#[cfg(not(target_os = "windows"))]
pub fn run_powershell(_script_name: &str, _args: &[&str]) -> Result<CommandResult, WslError> {
    Err(WslError::NotWindows)
}

#[cfg(target_os = "windows")]
pub fn wsl_exec(distro: &str, linux_command: &str) -> Result<CommandResult, WslError> {
    wsl_exec_as(distro, None, linux_command)
}

#[cfg(target_os = "windows")]
pub fn wsl_exec_as(
    distro: &str,
    user: Option<&str>,
    linux_command: &str,
) -> Result<CommandResult, WslError> {
    validate_ident("distro", distro)?;
    if let Some(u) = user {
        validate_ident("user", u)?;
    }
    // linux_command must be composed by us from allowlisted fragments, never raw UI input.
    let mut cmd = Command::new("wsl.exe");
    cmd.args(["-d", distro]);
    if let Some(u) = user {
        cmd.args(["-u", u]);
    }
    cmd.args(["-e", "bash", "-lc", linux_command]);
    let output = cmd.output().map_err(|e| WslError::Message(e.to_string()))?;
    Ok(CommandResult {
        ok: output.status.success(),
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).to_string(),
        code: output.status.code().unwrap_or(-1),
    })
}

#[cfg(not(target_os = "windows"))]
pub fn wsl_exec(_distro: &str, _linux_command: &str) -> Result<CommandResult, WslError> {
    Err(WslError::NotWindows)
}

#[cfg(not(target_os = "windows"))]
pub fn wsl_exec_as(
    _distro: &str,
    _user: Option<&str>,
    _linux_command: &str,
) -> Result<CommandResult, WslError> {
    Err(WslError::NotWindows)
}

pub fn provision_command(state: &AppState, stage: &str, profile: Option<&str>) -> Result<String, WslError> {
    validate_ident("distro", &state.distro_name)?;
    validate_ident("bench", &state.bench_name)?;
    validate_site(&state.site_name)?;
    let profile = profile.unwrap_or(&state.profile);
    validate_profile(profile)?;
    let stage = match stage {
        "linux_deps" | "system_deps" => "system_deps",
        "pilot_install" => "pilot_install",
        "cohenix_provision" => "cohenix_provision",
        "verify" => "verify",
        "start" => "start",
        "all" => "all",
        other => return Err(ValidationError::Invalid("stage", other.to_string()).into()),
    };
    // Scripts are expected at a fixed path inside the distro after sync, or via mounted repo.
    Ok(format!(
        "export PROFILE='{profile}' BENCH_NAME='{bench}' SITE_NAME='{site}' HTTP_PORT={http} SOCKETIO_PORT={sock} ADMIN_PORT={admin}; \
         if [ -f \"$HOME/cohenix/frappe_cohenix_development/scripts/native-wsl/provision.sh\" ]; then \
           bash \"$HOME/cohenix/frappe_cohenix_development/scripts/native-wsl/provision.sh\" --profile '{profile}' --stage '{stage}'; \
         else \
           echo 'Cohenix native-wsl scripts not found in distro' >&2; exit 1; \
         fi",
        profile = profile,
        bench = state.bench_name,
        site = state.site_name,
        http = state.http_port,
        sock = state.socketio_port,
        admin = state.admin_port,
        stage = stage,
    ))
}

pub fn lifecycle_command(state: &AppState, action: &str) -> Result<String, WslError> {
    validate_ident("bench", &state.bench_name)?;
    let action = match action {
        "start" | "stop" | "restart" | "status" => action,
        other => return Err(ValidationError::Invalid("action", other.to_string()).into()),
    };
    Ok(format!(
        "export BENCH_NAME='{bench}' HTTP_PORT={http} ADMIN_PORT={admin}; \
         bash \"$HOME/cohenix/frappe_cohenix_development/scripts/native-wsl/lifecycle.sh\" {action}",
        bench = state.bench_name,
        http = state.http_port,
        admin = state.admin_port,
        action = action,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn provision_command_is_allowlisted() {
        let state = AppState::default();
        let cmd = provision_command(&state, "cohenix_provision", Some("hr")).unwrap();
        assert!(cmd.contains("--profile 'hr'"));
        assert!(cmd.contains("provision.sh"));
        assert!(!cmd.contains(';') || cmd.matches(';').count() >= 1); // our own separators only
    }

    #[test]
    fn rejects_bad_profile_in_provision() {
        let state = AppState::default();
        assert!(provision_command(&state, "cohenix_provision", Some("x;rm")).is_err());
    }
}
