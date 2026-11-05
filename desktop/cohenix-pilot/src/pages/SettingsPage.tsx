import { useState } from "react";
import type { AppState } from "../lib/api";
import { saveSettings } from "../lib/api";

export function SettingsPage({
  state,
  onSaved,
}: {
  state: AppState;
  onSaved: () => Promise<void>;
}) {
  const [draft, setDraft] = useState(state);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <>
      <h1>Settings</h1>
      <p className="lead">
        Install location, distro, ports, and editor. Resource limits in{" "}
        <code>%UserProfile%\.wslconfig</code> affect every WSL2 distro — this app will not change
        that file silently.
      </p>
      {message ? <div className="error-banner">{message}</div> : null}
      <div className="panel">
        <div className="field">
          <label>Install / data directory</label>
          <input value={draft.install_dir} readOnly />
        </div>
        <div className="field">
          <label htmlFor="distro">WSL distro name</label>
          <input
            id="distro"
            value={draft.distro_name}
            onChange={(e) => setDraft({ ...draft, distro_name: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="editor">Preferred editor</label>
          <select
            id="editor"
            value={draft.preferred_editor}
            onChange={(e) =>
              setDraft({
                ...draft,
                preferred_editor: e.target.value as AppState["preferred_editor"],
              })
            }
          >
            <option value="cursor">Cursor</option>
            <option value="code">VS Code</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="http">HTTP port</label>
          <input
            id="http"
            type="number"
            value={draft.http_port}
            onChange={(e) => setDraft({ ...draft, http_port: Number(e.target.value) })}
          />
        </div>
        <div className="field">
          <label htmlFor="admin">Pilot Admin port</label>
          <input
            id="admin"
            type="number"
            value={draft.admin_port}
            onChange={(e) => setDraft({ ...draft, admin_port: Number(e.target.value) })}
          />
        </div>
        <div className="field">
          <label htmlFor="channel">Update channel (app only; Frappe never auto-upgrades)</label>
          <select
            id="channel"
            value={draft.update_channel}
            onChange={(e) =>
              setDraft({
                ...draft,
                update_channel: e.target.value as AppState["update_channel"],
              })
            }
          >
            <option value="stable">stable</option>
            <option value="preview">preview</option>
          </select>
        </div>
        <div className="actions">
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              void saveSettings(draft)
                .then(async () => {
                  setMessage("Settings saved.");
                  await onSaved();
                })
                .catch((err) => setMessage(String(err)))
                .finally(() => setBusy(false));
            }}
          >
            Save
          </button>
          <button
            type="button"
            className="danger"
            onClick={() =>
              setMessage(
                "Data removal is a separate confirmed flow and is not performed by uninstall. Use documentation in docs/windows-desktop/SUPPORT.md.",
              )
            }
          >
            Remove Cohenix data…
          </button>
        </div>
      </div>
    </>
  );
}
