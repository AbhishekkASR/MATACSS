import type { ExecutionOutput } from "@/types";

interface OutputPanelProps {
  output: ExecutionOutput | null;
}

export function OutputPanel({ output }: OutputPanelProps) {
  return (
    <section className="output-panel" aria-live="polite" aria-labelledby="output-title">
      <div className="output-header">
        <span id="output-title">Execution output</span>
        {output && <span>{output.status}</span>}
      </div>
      {!output ? (
        <div className="output-empty">Run your solution to see output here.</div>
      ) : (
        <>
          <div className="output-meta">
            <span>Exit code: <strong className="output-value">{output.exitCode ?? "—"}</strong></span>
            <span>Time: <strong className="output-value">{output.executionTimeMs ?? "—"}{output.executionTimeMs === null ? "" : " ms"}</strong></span>
            <span>Timed out: <strong className="output-value">{output.timedOut ? "Yes" : "No"}</strong></span>
          </div>
          <div className="output-content">
            <div className="output-block"><h3>stdout</h3><pre>{output.stdout || "No output"}</pre></div>
            <div className="output-block"><h3>stderr</h3><pre>{output.stderr || "No errors"}</pre></div>
          </div>
        </>
      )}
    </section>
  );
}
