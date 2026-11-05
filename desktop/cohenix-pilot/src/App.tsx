import { useEffect, useState } from "react";
import { listen as tauriListen } from "@tauri-apps/api/event";
import type { AppState, ProgressEvent } from "./lib/api";
import { getState } from "./lib/api";
import { isTauriRuntime, mockListen } from "./lib/mockBridge";
import { WelcomeWizard } from "./pages/WelcomeWizard";
import { HomePage } from "./pages/HomePage";
import { EnvironmentsPage } from "./pages/EnvironmentsPage";
import { LogsPage } from "./pages/LogsPage";
import { SettingsPage } from "./pages/SettingsPage";

type Tab = "home" | "environments" | "logs" | "settings";

function tabFromQuery(): Tab {
  const tab = new URLSearchParams(window.location.search).get("tab");
  if (tab === "environments" || tab === "logs" || tab === "settings" || tab === "home") {
    return tab;
  }
  return "home";
}

export default function App() {
  const [state, setState] = useState<AppState | null>(null);
  const [tab, setTab] = useState<Tab>(tabFromQuery);
  const [progress, setProgress] = useState<ProgressEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    try {
      const next = await getState();
      setState(next);
      setError(next.last_error);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    let unlisten: (() => void) | undefined;
    const listenFn = isTauriRuntime() ? tauriListen : mockListen;
    void listenFn("cohenix-progress", (event: { payload: ProgressEvent }) => {
      setProgress((prev) => [...prev.slice(-400), event.payload]);
    }).then((fn) => {
      unlisten = fn;
    });
    return () => unlisten?.();
  }, []);

  if (loading || !state) {
    return (
      <div className="main">
        <div className="welcome-hero">
          <div className="brand-mark">Cohenix Pilot</div>
          <p className="lead">Loading local control plane…</p>
        </div>
      </div>
    );
  }

  if (state.stage !== "ready") {
    return (
      <WelcomeWizard
        state={state}
        progress={progress}
        error={error}
        onUpdated={async () => {
          await refresh();
        }}
      />
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <strong>Cohenix Pilot</strong>
          <span>Native WSL · Frappe v16</span>
        </div>
        <nav className="nav">
          {(
            [
              ["home", "Home"],
              ["environments", "Environments"],
              ["logs", "Logs"],
              ["settings", "Settings"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={tab === id ? "active" : ""}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </nav>
      </aside>
      <main className="main">
        {error ? <div className="error-banner">{error}</div> : null}
        {tab === "home" ? <HomePage state={state} onRefresh={refresh} /> : null}
        {tab === "environments" ? <EnvironmentsPage state={state} onRefresh={refresh} /> : null}
        {tab === "logs" ? <LogsPage progress={progress} /> : null}
        {tab === "settings" ? <SettingsPage state={state} onSaved={refresh} /> : null}
      </main>
    </div>
  );
}
