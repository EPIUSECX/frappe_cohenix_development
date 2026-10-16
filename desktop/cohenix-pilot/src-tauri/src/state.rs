//! Persisted first-run / settings state.

use crate::validation::{validate_ident, validate_port, validate_profile, validate_site};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum InstallStage {
    Preflight,
    WslEnable,
    Distro,
    LinuxDeps,
    PilotInstall,
    CohenixProvision,
    Verify,
    Ready,
}

impl InstallStage {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Preflight => "preflight",
            Self::WslEnable => "wsl_enable",
            Self::Distro => "distro",
            Self::LinuxDeps => "linux_deps",
            Self::PilotInstall => "pilot_install",
            Self::CohenixProvision => "cohenix_provision",
            Self::Verify => "verify",
            Self::Ready => "ready",
        }
    }

    pub fn next(&self) -> Self {
        match self {
            Self::Preflight => Self::WslEnable,
            Self::WslEnable => Self::Distro,
            Self::Distro => Self::LinuxDeps,
            Self::LinuxDeps => Self::PilotInstall,
            Self::PilotInstall => Self::CohenixProvision,
            Self::CohenixProvision => Self::Verify,
            Self::Verify => Self::Ready,
            Self::Ready => Self::Ready,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppState {
    pub stage: InstallStage,
    pub distro_name: String,
    pub profile: String,
    pub bench_name: String,
    pub site_name: String,
    pub http_port: u16,
    pub socketio_port: u16,
    pub admin_port: u16,
    pub preferred_editor: String,
    pub last_error: Option<String>,
    pub install_dir: String,
    pub update_channel: String,
}

impl Default for AppState {
    fn default() -> Self {
        let install_dir = dirs::data_local_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("CohenixPilot")
            .to_string_lossy()
            .to_string();
        Self {
            stage: InstallStage::Preflight,
            distro_name: "Cohenix-Pilot".into(),
            profile: "hr".into(),
            bench_name: "development-bench".into(),
            site_name: "cohenix.localhost".into(),
            http_port: 8000,
            socketio_port: 9000,
            admin_port: 8002,
            preferred_editor: "cursor".into(),
            last_error: None,
            install_dir,
            update_channel: "stable".into(),
        }
    }
}

impl AppState {
    pub fn validate(&self) -> Result<(), String> {
        validate_ident("distro", &self.distro_name).map_err(|e| e.to_string())?;
        validate_ident("bench", &self.bench_name).map_err(|e| e.to_string())?;
        validate_site(&self.site_name).map_err(|e| e.to_string())?;
        validate_profile(&self.profile).map_err(|e| e.to_string())?;
        validate_port(self.http_port).map_err(|e| e.to_string())?;
        validate_port(self.socketio_port).map_err(|e| e.to_string())?;
        validate_port(self.admin_port).map_err(|e| e.to_string())?;
        if self.preferred_editor != "code" && self.preferred_editor != "cursor" {
            return Err("preferred_editor must be code or cursor".into());
        }
        Ok(())
    }

    pub fn state_path() -> PathBuf {
        let dir = dirs::data_local_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("CohenixPilot");
        let _ = fs::create_dir_all(&dir);
        dir.join("state.json")
    }

    pub fn load() -> Self {
        let path = Self::state_path();
        if let Ok(bytes) = fs::read(&path) {
            if let Ok(state) = serde_json::from_slice::<AppState>(&bytes) {
                if state.validate().is_ok() {
                    return state;
                }
            }
        }
        let state = Self::default();
        let _ = state.save();
        state
    }

    pub fn save(&self) -> Result<(), String> {
        self.validate()?;
        let path = Self::state_path();
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let data = serde_json::to_vec_pretty(self).map_err(|e| e.to_string())?;
        fs::write(path, data).map_err(|e| e.to_string())
    }

    pub fn advance(&mut self) -> Result<(), String> {
        self.stage = self.stage.next();
        self.last_error = None;
        self.save()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stage_machine_reaches_ready() {
        let mut s = InstallStage::Preflight;
        for _ in 0..10 {
            s = s.next();
        }
        assert_eq!(s, InstallStage::Ready);
    }

    #[test]
    fn default_state_valid() {
        AppState::default().validate().unwrap();
    }

    #[test]
    fn interrupted_install_resumes_same_stage() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("state.json");
        let mut state = AppState::default();
        state.stage = InstallStage::PilotInstall;
        let data = serde_json::to_vec(&state).unwrap();
        std::fs::write(&path, data).unwrap();
        let loaded: AppState = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
        assert_eq!(loaded.stage, InstallStage::PilotInstall);
    }
}
