import { useEffect } from "react";

import { useJobsStore } from "../stores/jobsStore";
import { useSessionStore } from "../stores/sessionStore";
import { formatDateTime } from "../lib/format";
import { Badge, Button, Panel, Row, Spinner } from "./ui";

function statusTone(status: string): "good" | "warn" | "bad" | "neutral" {
  if (status === "implemented" || status === "available") return "good";
  if (status === "in_progress") return "warn";
  if (status === "unavailable") return "bad";
  return "neutral";
}

export function WorkflowPanel() {
  const health = useSessionStore((state) => state.health);
  const healthError = useSessionStore((state) => state.healthError);
  const activeProjectId = useSessionStore((state) => state.activeProjectId);

  const jobs = useJobsStore((state) => state.jobs);
  const startPolling = useJobsStore((state) => state.startPolling);
  const stopPolling = useJobsStore((state) => state.stopPolling);
  const submitSelfTest = useJobsStore((state) => state.submitSelfTest);
  const cancel = useJobsStore((state) => state.cancel);

  useEffect(() => {
    startPolling(activeProjectId ?? undefined);
    return () => stopPolling();
  }, [activeProjectId, startPolling, stopPolling]);

  return (
    <Panel title="Workflow & diagnostics" className="min-h-0">
      <div className="flex flex-col gap-4">
        {healthError ? (
          <div className="rounded-md border border-red-500/40 bg-red-950/50 px-3 py-2 text-[11px] text-red-200">
            {healthError}
          </div>
        ) : null}

        {health ? (
          <>
            <div>
              <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">Scientific tools</h4>
              <div className="flex flex-col gap-1">
                {health.capabilities.map((capability) => (
                  <div key={capability.key} className="rounded-md bg-surface-2 px-2 py-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs text-gray-200">{capability.label}</span>
                      <Badge tone={statusTone(capability.status)}>{capability.status.replace("_", " ")}</Badge>
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10px] text-gray-500">
                      {capability.version ? <span className="font-mono">{capability.version}</span> : null}
                      {capability.mode ? <span>mode: {capability.mode}</span> : null}
                    </div>
                    {capability.remediation ? (
                      <p className="mt-1 text-[10px] text-amber-300/80">{capability.remediation}</p>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>

            <div>
              <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">Roadmap</h4>
              <div className="flex flex-col gap-1">
                {health.phases.map((phase) => (
                  <div key={phase.id} className="rounded-md bg-surface-2 px-2 py-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs text-gray-200">
                        <span className="font-mono text-[10px] text-gray-500">{phase.id}</span> {phase.name}
                      </span>
                      <Badge tone={statusTone(phase.status)}>{phase.status.replace("_", " ")}</Badge>
                    </div>
                    <p className="mt-0.5 text-[10px] leading-snug text-gray-500">{phase.summary}</p>
                    {phase.pending.length > 0 ? (
                      <ul className="mt-1 list-disc pl-4 text-[10px] text-amber-300/70">
                        {phase.pending.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>

            <div>
              <Row label="Backend mode" value={health.scientificBackendMode} />
              <Row label="Database" value={health.database} />
              <Row label="Version" value={health.version} mono />
            </div>
          </>
        ) : (
          <Spinner label="Loading capability report…" />
        )}

        <div>
          <div className="mb-1 flex items-center justify-between">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
              Background jobs ({jobs.length})
            </h4>
            <Button
              variant="ghost"
              onClick={() => void submitSelfTest(activeProjectId)}
              title="Queue a real pipeline self-test on the job worker"
            >
              Run self-test
            </Button>
          </div>
          {jobs.length === 0 ? (
            <p className="text-[11px] text-gray-500">
              No jobs yet. The self-test exercises the durable queue, subprocess worker, progress reporting and
              cancellation end to end.
            </p>
          ) : (
            <ul className="flex flex-col gap-1">
              {jobs.slice(0, 8).map((job) => (
                <li key={job.id} className="rounded-md bg-surface-2 px-2 py-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-gray-200">{job.kind}</span>
                    <Badge tone={statusTone(job.state)}>{job.state}</Badge>
                  </div>
                  <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-surface-3">
                    <div className="h-full bg-accent transition-all" style={{ width: `${Math.round(job.progress * 100)}%` }} />
                  </div>
                  <div className="mt-0.5 flex items-center justify-between text-[10px] text-gray-500">
                    <span>{job.message || "—"}</span>
                    <span>{formatDateTime(job.createdAt)}</span>
                  </div>
                  {job.state === "running" || job.state === "queued" || job.state === "preparing" ? (
                    <div className="mt-1 flex justify-end">
                      <Button variant="ghost" onClick={() => void cancel(job.id)}>
                        Cancel
                      </Button>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Panel>
  );
}
