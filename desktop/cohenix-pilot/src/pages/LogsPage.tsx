import { useEffect, useState } from "react";
import type { ProgressEvent } from "../lib/api";
import { diagnosticReport, getLogs } from "../lib/api";

export function LogsPage({ progress }: { progress: ProgressEvent[] }) {
  const [logs, setLogs] = useState("");
  const [diag, setDiag] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    void getLogs(300)
      .then(setLogs)
      .catch((err) => setLogs(String(err)));
  }, [progress.length]);

  return (
    <>
      <h1>Logs & diagnostics</h1>
      <p className="lead">Installation and runtime output with secrets redacted.</p>
      <div className="panel">
        <div className="actions" style={{ marginBottom: "0.75rem" }}>
          <button
            type="button"
            className="secondary"
            onClick={() => {
              void diagnosticReport().then(async (text) => {
                setDiag(text);
                try {
                  await navigator.clipboard.writeText(text);
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 2000);
                } catch {
                  /* clipboard may be unavailable */
                }
              });
            }}
          >
            {copied ? "Copied" : "Copy diagnostic report"}
          </button>
        </div>
        <div className="log-view">
          {[...progress.map((p) => `[${p.level}] ${p.stage}: ${p.message}`), logs, diag]
            .filter(Boolean)
            .join("\n\n")}
        </div>
      </div>
    </>
  );
}
