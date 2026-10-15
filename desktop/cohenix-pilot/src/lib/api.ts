import { invoke as tauriInvoke } from "@tauri-apps/api/core";
import { isTauriRuntime, mockInvoke } from "./mockBridge";

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (!isTauriRuntime()) {
    return mockInvoke<T>(cmd, args);
  }
  return tauriInvoke<T>(cmd, args);
}

export type InstallStage =
  | "preflight"
  | "wsl_enable"
  | "distro"
  | "linux_deps"
  | "pilot_install"
  | "cohenix_provision"
  | "verify"
  | "ready";

export interface AppState {
  stage: InstallStage;
  distro_name: string;
  profile: string;
  bench_name: string;
  site_name: string;
  http_port: number;
  socketio_port: number;
  admin_port: number;
  preferred_editor: "code" | "cursor";
  last_error: string | null;
  install_dir: string;
  update_channel: "stable" | "preview";
}

export interface PreflightReport {
  ok: boolean;
  os_caption: string;
  arch: string;
  admin: boolean;
  ram_gb: number;
  disk_free_gb: number;
  webview2: boolean;
  wsl_installed: boolean;
  wsl_version: string | null;
  distros: string[];
  ports_free: Record<string, boolean>;
  remediation: string[];
  mock?: boolean;
}

export interface StackStatus {
  stage: InstallStage;
  wsl_running: boolean;
  process: boolean;
  frappe_http: boolean;
  admin_health: boolean;
  site_url: string;
  admin_url: string;
  profile: string;
  bench_name: string;
  site_name: string;
  installed_apps: string[];
}

export interface ProgressEvent {
  stage: string;
  message: string;
  level: "info" | "warn" | "error";
}

export const PROFILES = [
  { id: "frappe", label: "Frappe only" },
  { id: "erp", label: "Frappe + ERPNext" },
  { id: "hr", label: "HR (default)" },
  { id: "localisation", label: "Localisation" },
  { id: "integrations", label: "Integrations" },
  { id: "full-cohenix", label: "Full Cohenix" },
] as const;

export async function getState(): Promise<AppState> {
  return invoke("get_state");
}

export async function saveSettings(patch: Partial<AppState>): Promise<AppState> {
  return invoke("save_settings", { patch });
}

export async function runPreflight(): Promise<PreflightReport> {
  return invoke("run_preflight");
}

export async function enableWsl(): Promise<{ ok: boolean; restart_required: boolean; message: string }> {
  return invoke("enable_wsl");
}

export async function createDistro(): Promise<{ ok: boolean; message: string }> {
  return invoke("create_distro");
}

export async function runProvisionStage(stage: string, profile?: string): Promise<{ ok: boolean; message: string }> {
  return invoke("run_provision_stage", { stage, profile });
}

export async function getStackStatus(): Promise<StackStatus> {
  return invoke("get_stack_status");
}

export async function lifecycle(action: "start" | "stop" | "restart"): Promise<StackStatus> {
  return invoke("lifecycle_action", { action });
}

export async function openUrl(kind: "admin" | "desk" | "editor"): Promise<void> {
  return invoke("open_url", { kind });
}

export async function getLogs(limit = 200): Promise<string> {
  return invoke("get_logs", { limit });
}

export async function diagnosticReport(): Promise<string> {
  return invoke("diagnostic_report");
}

export async function listEnvironments(): Promise<{
  benches: Array<{ name: string; sites: string[]; ports: Record<string, number>; apps: string[] }>;
}> {
  return invoke("list_environments");
}

export async function createSite(siteName: string): Promise<{ ok: boolean; message: string }> {
  return invoke("create_site", { siteName });
}

export async function installProfile(profile: string): Promise<{ ok: boolean; message: string }> {
  return invoke("install_profile", { profile });
}
