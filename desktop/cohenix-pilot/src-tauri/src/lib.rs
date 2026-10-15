mod commands;
mod secrets;
mod state;
mod validation;
mod wsl;

use commands::SharedState;
use state::AppState;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let initial = AppState::load();
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(SharedState(std::sync::Mutex::new(initial)))
        .invoke_handler(tauri::generate_handler![
            commands::get_state,
            commands::save_settings,
            commands::run_preflight,
            commands::enable_wsl,
            commands::create_distro,
            commands::run_provision_stage,
            commands::get_stack_status,
            commands::lifecycle_action,
            commands::open_url,
            commands::get_logs,
            commands::diagnostic_report,
            commands::list_environments,
            commands::create_site,
            commands::install_profile,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Cohenix Pilot");
}
