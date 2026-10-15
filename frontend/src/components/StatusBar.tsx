import { useJobsStore } from "../stores/jobsStore";
import { useSessionStore } from "../stores/sessionStore";
import { useStructureStore } from "../stores/structureStore";
import { Badge } from "./ui";

export function StatusBar() {
  const health = useSessionStore((state) => state.health);
  const healthError = useSessionStore((state) => state.healthError);
  const projects = useSessionStore((state) => state.projects);
  const activeProjectId = useSessionStore((state) => state.activeProjectId);

  const packet = useStructureStore((state) => state.packet);
  const selection = useStructureStore((state) => state.selection);
  const error = useStructureStore((state) => state.error);
  const running = useJobsStore((state) => state.jobs.filter((job) => job.state === "running").length);

  const project = projects.find((candidate) => candidate.id === activeProjectId) ?? null;

  return (
    <footer className="flex items-center gap-4 border-t border-border-subtle bg-surface-1 px-3 py-1.5 text-[11px] text-gray-400">
      <span className="flex items-center gap-1.5">
        {health ? (
          <>
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
            Backend ready · {health.scientificBackendMode}
          </>
        ) : healthError ? (
          <>
            <span className="h-2 w-2 rounded-full bg-red-500" />
            Backend unreachable
          </>
        ) : (
          <>
            <span className="h-2 w-2 rounded-full bg-amber-400" />
            Connecting…
          </>
        )}
      </span>

      <span>{project ? `Project: ${project.name}` : "No project"}</span>

      {packet ? (
        <>
          <span>
            {packet.structure.name} · {packet.structure.atoms.toLocaleString()} atoms ·{" "}
            {packet.structure.residues.toLocaleString()} residues
          </span>
          <span>Selection: {selection.size}</span>
        </>
      ) : (
        <span>No structure loaded</span>
      )}

      <span className="ml-auto flex items-center gap-2">
        {running > 0 ? <Badge tone="warn">{running} job(s) running</Badge> : null}
        {error ? <Badge tone="bad">{error.code}</Badge> : null}
        <span className="font-mono text-gray-600">MolDock Studio {health?.version ?? "—"}</span>
      </span>
    </footer>
  );
}
