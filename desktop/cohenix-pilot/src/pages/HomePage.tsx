import { useEffect, useState } from "react";
import type { AppState, StackStatus } from "../lib/api";
import { getStackStatus, lifecycle, openUrl } from "../lib/api";

export function HomePage({ state, onRefresh }: { state: AppState; onRefresh: () => Promise<void> }) {
  const [status, setStatus] = useState<StackStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      setStatus(await getStackStatus());
      await onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 8000);
    return () => window.clearInterval(id);
  }, []);

  const act = async (action: "start" | "stop" | "restart") => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await lifecycle(action));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const flag = (ok: boolean | undefined) => (ok ? "ok" : "bad");

  return (
    <>
      <h1>Home</h1>
      <p className="lead">
        Live status for <code>{state.distro_name}</code> · profile {state.profile} · site{" "}
        {state.site_name}
      </p>
      {error ? <div className="error-banner">{error}</div> : null}
      <div className="panel">
        <div className="status-grid">
          <div className="stat">
            <div className="label">WSL</div>
            <div className={`value ${flag(status?.wsl_running)}`}>
              {status?.wsl_running ? "Running" : "Stopped"}
            </div>
          </div>
          <div className="stat">
            <div className="label">Pilot process</div>
            <div className={`value ${flag(status?.process)}`}>
              {status?.process ? "Up" : "Down"}
            </div>
          </div>
          <div className="stat">
            <div className="label">Frappe HTTP</div>
            <div className={`value ${flag(status?.frappe_http)}`}>
              {status?.frappe_http ? "Healthy" : "Unreachable"}
            </div>
          </div>
          <div className="stat">
            <div className="label">Pilot Admin</div>
            <div className={`value ${flag(status?.admin_health)}`}>
              {status?.admin_health ? "Healthy" : "Unreachable"}
            </div>
          </div>
        </div>
        <div className="actions">
          <button type="button" disabled={busy} onClick={() => void act("start")}>
            Start
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={() => void act("stop")}>
            Stop
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={() => void act("restart")}>
            Restart
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={() => void openUrl("admin")}>
            Open Pilot Admin
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={() => void openUrl("desk")}>
            Open Frappe Desk
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={() => void openUrl("editor")}>
            Open in {state.preferred_editor === "cursor" ? "Cursor" : "VS Code"}
          </button>
        </div>
      </div>
    </>
  );
}
