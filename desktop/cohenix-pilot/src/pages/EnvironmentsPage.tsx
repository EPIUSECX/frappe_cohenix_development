import { useEffect, useState } from "react";
import type { AppState } from "../lib/api";
import { PROFILES, createSite, installProfile, listEnvironments } from "../lib/api";

export function EnvironmentsPage({
  state,
  onRefresh,
}: {
  state: AppState;
  onRefresh: () => Promise<void>;
}) {
  const [rows, setRows] = useState<
    Array<{ name: string; sites: string[]; ports: Record<string, number>; apps: string[] }>
  >([]);
  const [siteName, setSiteName] = useState("");
  const [profile, setProfile] = useState(state.profile);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = async () => {
    const data = await listEnvironments();
    setRows(data.benches);
  };

  useEffect(() => {
    void refresh().catch((err) => setMessage(String(err)));
  }, []);

  return (
    <>
      <h1>Environments</h1>
      <p className="lead">Benches and sites inside the Cohenix-Pilot distro.</p>
      {message ? <div className="error-banner">{message}</div> : null}
      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>Bench</th>
              <th>Sites</th>
              <th>Ports</th>
              <th>Apps</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((b) => (
              <tr key={b.name}>
                <td>{b.name}</td>
                <td>{b.sites.join(", ") || "—"}</td>
                <td>
                  {Object.entries(b.ports)
                    .map(([k, v]) => `${k}:${v}`)
                    .join(" · ") || "—"}
                </td>
                <td>{b.apps.join(", ") || "—"}</td>
              </tr>
            ))}
            {!rows.length ? (
              <tr>
                <td colSpan={4}>No benches reported yet.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h2>Create site</h2>
        <div className="field">
          <label htmlFor="site">Site name (prefer *.localhost)</label>
          <input
            id="site"
            value={siteName}
            onChange={(e) => setSiteName(e.target.value)}
            placeholder="second.localhost"
          />
        </div>
        <div className="actions">
          <button
            type="button"
            disabled={busy || !siteName}
            onClick={() => {
              setBusy(true);
              void createSite(siteName)
                .then(async (r) => {
                  setMessage(r.message);
                  await refresh();
                  await onRefresh();
                })
                .catch((err) => setMessage(String(err)))
                .finally(() => setBusy(false));
            }}
          >
            Create site
          </button>
        </div>
      </div>
      <div className="panel">
        <h2>Install / switch profile</h2>
        <div className="field">
          <label htmlFor="profile2">Profile from config/profiles.toml</label>
          <select id="profile2" value={profile} onChange={(e) => setProfile(e.target.value)}>
            {PROFILES.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
        <div className="actions">
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              void installProfile(profile)
                .then(async (r) => {
                  setMessage(r.message);
                  await refresh();
                  await onRefresh();
                })
                .catch((err) => setMessage(String(err)))
                .finally(() => setBusy(false));
            }}
          >
            Apply profile
          </button>
        </div>
      </div>
    </>
  );
}
