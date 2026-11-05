/** Browser preview / screenshot harness when Tauri IPC is unavailable. */

import type {
  AppState,
  InstallStage,
  PreflightReport,
  ProgressEvent,
  StackStatus,
} from "./api";

const STAGES: InstallStage[] = [
  "preflight",
  "wsl_enable",
  "distro",
  "linux_deps",
  "pilot_install",
  "cohenix_provision",
  "verify",
  "ready",
];

function stageFromQuery(): InstallStage {
  const params = new URLSearchParams(window.location.search);
  const mock = params.get("mock");
  if (mock === "home" || mock === "ready") return "ready";
  if (mock === "wizard" || mock === "preflight") return "preflight";
  if (mock && STAGES.includes(mock as InstallStage)) return mock as InstallStage;
  return "preflight";
}

let state: AppState = {
  stage: stageFromQuery(),
  distro_name: "Cohenix-Pilot",
  profile: "hr",
  bench_name: "development-bench",
  site_name: "cohenix.localhost",
  http_port: 8000,
  socketio_port: 9000,
  admin_port: 8002,
  preferred_editor: "cursor",
  last_error: null,
  install_dir: "C:\\Users\\Dev\\AppData\\Local\\CohenixPilot",
  update_channel: "stable",
};

const progress: ProgressEvent[] = [
  { stage: "preflight", message: "Mock preview: Tauri IPC not available", level: "warn" },
  { stage: "preflight", message: "UI rendered for screenshot / browser review", level: "info" },
];

export function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function mockInvoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  switch (cmd) {
    case "get_state":
      return structuredClone(state) as T;
    case "save_settings": {
      state = { ...state, ...(args?.patch as Partial<AppState>) };
      return structuredClone(state) as T;
    }
    case "run_preflight": {
      const report: PreflightReport = {
        ok: true,
        os_caption: "Windows 11 Pro (mock preview)",
        arch: "AMD64",
        admin: false,
        ram_gb: 32,
        disk_free_gb: 120,
        webview2: true,
        wsl_installed: true,
        wsl_version: "WSL version 2.4.0",
        distros: ["Ubuntu", "Cohenix-Pilot"],
        ports_free: { "8000": true, "8002": true, "9000": true },
        remediation: [],
        mock: true,
      };
      return report as T;
    }
    case "enable_wsl":
      state.stage = "distro";
      return { ok: true, restart_required: false, message: "Mock WSL ready" } as T;
    case "create_distro":
      state.stage = "linux_deps";
      return { ok: true, message: "Mock distro created" } as T;
    case "run_provision_stage": {
      const stage = String(args?.stage || "");
      if (stage === "advance_preflight") state.stage = "wsl_enable";
      else if (stage === "advance_wsl") state.stage = "distro";
      else {
        const idx = STAGES.indexOf(state.stage);
        if (idx >= 0 && idx < STAGES.length - 1) state.stage = STAGES[idx + 1];
      }
      progress.push({ stage, message: `Mock completed ${stage}`, level: "info" });
      return { ok: true, message: "Mock stage advanced" } as T;
    }
    case "get_stack_status": {
      const status: StackStatus = {
        stage: state.stage,
        wsl_running: true,
        process: true,
        frappe_http: true,
        admin_health: true,
        site_url: `http://${state.site_name}:${state.http_port}/app`,
        admin_url: `http://127.0.0.1:${state.admin_port}`,
        profile: state.profile,
        bench_name: state.bench_name,
        site_name: state.site_name,
        installed_apps: ["frappe", "erpnext", "hrms"],
      };
      return status as T;
    }
    case "lifecycle_action":
      return mockInvoke("get_stack_status");
    case "open_url":
      return undefined as T;
    case "get_logs":
      return progress.map((p) => `[${p.level}] ${p.stage}: ${p.message}`).join("\n") as T;
    case "diagnostic_report":
      return `Cohenix Pilot diagnostic (mock)\nstage=${state.stage}\ndistro=${state.distro_name}\n` as T;
    case "list_environments":
      return {
        benches: [
          {
            name: state.bench_name,
            sites: [state.site_name],
            ports: {
              http: state.http_port,
              socketio: state.socketio_port,
              admin: state.admin_port,
            },
            apps: ["frappe", "erpnext", "hrms"],
          },
        ],
      } as T;
    case "create_site":
      return { ok: true, message: `Mock created ${args?.siteName}` } as T;
    case "install_profile":
      state.profile = String(args?.profile || state.profile);
      return { ok: true, message: `Mock applied ${state.profile}` } as T;
    default:
      throw new Error(`Mock bridge: unknown command ${cmd}`);
  }
}

export async function mockListen(
  _event: string,
  handler: (event: { payload: ProgressEvent }) => void,
): Promise<() => void> {
  for (const payload of progress) {
    handler({ payload });
  }
  return () => undefined;
}
