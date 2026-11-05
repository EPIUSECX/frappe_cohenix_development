import { useMemo, useState } from "react";
import type { AppState, PreflightReport, ProgressEvent } from "../lib/api";
import {
  PROFILES,
  createDistro,
  enableWsl,
  runPreflight,
  runProvisionStage,
  saveSettings,
} from "../lib/api";

const STAGES: Array<{ id: AppState["stage"]; label: string }> = [
  { id: "preflight", label: "Preflight" },
  { id: "wsl_enable", label: "WSL" },
  { id: "distro", label: "Distro" },
  { id: "linux_deps", label: "Linux deps" },
  { id: "pilot_install", label: "Pilot" },
  { id: "cohenix_provision", label: "Provision" },
  { id: "verify", label: "Verify" },
  { id: "ready", label: "Ready" },
];

export function WelcomeWizard({
  state,
  progress,
  error,
  onUpdated,
}: {
  state: AppState;
  progress: ProgressEvent[];
  error: string | null;
  onUpdated: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [preflight, setPreflight] = useState<PreflightReport | null>(null);
  const [profile, setProfile] = useState(state.profile || "hr");
  const [localError, setLocalError] = useState<string | null>(error);
  const logText = useMemo(
    () => progress.map((p) => `[${p.level}] ${p.stage}: ${p.message}`).join("\n"),
    [progress],
  );

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setLocalError(null);
    try {
      await fn();
      await onUpdated();
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="main">
      <div className="welcome-hero">
        <div className="brand-mark">Cohenix Pilot</div>
        <h1>Set up your local Frappe lab</h1>
        <p className="lead">
          Guided install into an isolated Ubuntu 24.04 WSL2 environment. No Docker Desktop.
          You stay in control of restarts, distro names, and credentials.
        </p>
      </div>

      <div className="panel">
        <div className="wizard-steps">
          {STAGES.map((s) => {
            const idx = STAGES.findIndex((x) => x.id === state.stage);
            const mine = STAGES.findIndex((x) => x.id === s.id);
            const cls = mine < idx ? "done" : mine === idx ? "current" : "";
            return (
              <span key={s.id} className={cls}>
                {s.label}
              </span>
            );
          })}
        </div>

        {localError ? <div className="error-banner">{localError}</div> : null}

        {state.stage === "preflight" ? (
          <>
            <h2>Preflight</h2>
            <p className="lead">Check Windows, WSL, disk, WebView2, and ports before changing anything.</p>
            <div className="actions">
              <button type="button" disabled={busy} onClick={() => run(async () => {
                const report = await runPreflight();
                setPreflight(report);
              })}>
                Run checks
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy || !preflight?.ok}
                onClick={() => run(() => runProvisionStage("advance_preflight"))}
              >
                Continue
              </button>
            </div>
            {preflight ? (
              <div className="status-grid">
                <div className="stat">
                  <div className="label">OS</div>
                  <div className="value">{preflight.os_caption}</div>
                </div>
                <div className="stat">
                  <div className="label">WSL</div>
                  <div className={`value ${preflight.wsl_installed ? "ok" : "warn"}`}>
                    {preflight.wsl_installed ? preflight.wsl_version || "present" : "missing"}
                  </div>
                </div>
                <div className="stat">
                  <div className="label">RAM</div>
                  <div className="value">{preflight.ram_gb} GB</div>
                </div>
                <div className="stat">
                  <div className="label">Free disk</div>
                  <div className="value">{preflight.disk_free_gb} GB</div>
                </div>
              </div>
            ) : null}
            {preflight?.remediation?.length ? (
              <ul>
                {preflight.remediation.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            ) : null}
          </>
        ) : null}

        {state.stage === "wsl_enable" ? (
          <>
            <h2>Enable WSL2</h2>
            <p className="lead">
              Uses Microsoft&apos;s <code>wsl.exe</code> commands. Elevation is requested only for
              this step. A restart is never forced — you choose when to reboot, then reopen this app.
            </p>
            <div className="actions">
              <button type="button" disabled={busy} onClick={() => run(async () => {
                const res = await enableWsl();
                if (res.restart_required) {
                  setLocalError(`${res.message}\nRestart Windows, then reopen Cohenix Pilot to resume.`);
                }
              })}>
                Enable WSL
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => run(() => runProvisionStage("advance_wsl"))}
              >
                WSL already ready — continue
              </button>
            </div>
          </>
        ) : null}

        {state.stage === "distro" ? (
          <>
            <h2>Create Cohenix-Pilot distro</h2>
            <p className="lead">
              Imports Ubuntu 24.04 into a dedicated distro named <strong>{state.distro_name}</strong>.
              Existing Ubuntu installs are left alone.
            </p>
            <div className="actions">
              <button type="button" disabled={busy} onClick={() => run(() => createDistro())}>
                Create distro
              </button>
            </div>
          </>
        ) : null}

        {["linux_deps", "pilot_install", "cohenix_provision", "verify"].includes(state.stage) ? (
          <>
            <h2>
              {state.stage === "linux_deps" && "Native Linux dependencies"}
              {state.stage === "pilot_install" && "Install Frappe Pilot"}
              {state.stage === "cohenix_provision" && "Provision Cohenix site"}
              {state.stage === "verify" && "Verify health"}
            </h2>
            {state.stage === "cohenix_provision" ? (
              <div className="field">
                <label htmlFor="profile">App profile</label>
                <select
                  id="profile"
                  value={profile}
                  onChange={(e) => setProfile(e.target.value)}
                  disabled={busy}
                >
                  {PROFILES.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <div className="actions">
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    if (state.stage === "cohenix_provision") {
                      await saveSettings({ profile });
                    }
                    await runProvisionStage(state.stage, profile);
                  })
                }
              >
                {busy ? "Working…" : "Run this stage"}
              </button>
            </div>
          </>
        ) : null}

        {logText ? (
          <>
            <h3 style={{ marginTop: "1.25rem" }}>Progress</h3>
            <div className="log-view">{logText}</div>
          </>
        ) : null}
      </div>
    </div>
  );
}
