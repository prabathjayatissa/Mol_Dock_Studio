import { useState } from "react";

import { useSessionStore } from "../stores/sessionStore";
import { useStructureStore } from "../stores/structureStore";
import { formatBytes } from "../lib/format";
import { Button, Panel, Row, Spinner } from "./ui";
import { ImportDialog } from "./ImportDialog";
import { RcsbDialog } from "./RcsbDialog";

export function StructurePanel() {
  const projects = useSessionStore((state) => state.projects);
  const activeProjectId = useSessionStore((state) => state.activeProjectId);
  const structures = useSessionStore((state) => state.structures);
  const selectProject = useSessionStore((state) => state.selectProject);
  const createProject = useSessionStore((state) => state.createProject);

  const packet = useStructureStore((state) => state.packet);
  const loading = useStructureStore((state) => state.loading);
  const loadPacket = useStructureStore((state) => state.loadPacket);
  const selectChain = useStructureStore((state) => state.selectChain);
  const selectResidue = useStructureStore((state) => state.selectResidue);

  const [dialog, setDialog] = useState<"import" | "rcsb" | "smiles" | null>(null);
  const [newProjectName, setNewProjectName] = useState("");

  const activeProject = projects.find((project) => project.id === activeProjectId) ?? null;

  return (
    <Panel
      title="Structures"
      actions={
        <div className="flex gap-1">
          <Button variant="ghost" disabled={!activeProjectId} onClick={() => setDialog("import")}>
            Import
          </Button>
          <Button variant="ghost" disabled={!activeProjectId} onClick={() => setDialog("rcsb")}>
            RCSB
          </Button>
          <Button variant="ghost" disabled={!activeProjectId} onClick={() => setDialog("smiles")}>
            SMILES
          </Button>
        </div>
      }
      className="min-h-0"
    >
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-medium uppercase tracking-wide text-gray-400">Project</span>
          <select
            value={activeProjectId ?? ""}
            onChange={(event) => void selectProject(event.target.value || null)}
            className="rounded-md border border-border-subtle bg-surface-2 px-2 py-1.5 text-xs text-gray-100 outline-none focus:border-accent"
          >
            {projects.length === 0 ? <option value="">No projects yet</option> : null}
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>

        <div className="flex gap-1">
          <input
            value={newProjectName}
            onChange={(event) => setNewProjectName(event.target.value)}
            placeholder="New project name"
            className="min-w-0 flex-1 rounded-md border border-border-subtle bg-surface-2 px-2 py-1.5 text-xs text-gray-100 outline-none focus:border-accent"
          />
          <Button
            disabled={newProjectName.trim().length === 0}
            onClick={async () => {
              const created = await createProject(newProjectName.trim());
              if (created) setNewProjectName("");
            }}
          >
            Create
          </Button>
        </div>

        {loading ? <Spinner label="Working…" /> : null}

        <div className="flex flex-col gap-1">
          {structures.length === 0 ? (
            <p className="text-[11px] text-gray-500">
              {activeProject ? "No structures in this project yet." : "Create a project to get started."}
            </p>
          ) : null}
          {structures.map((structure) => {
            const isActive = packet?.structure.id === structure.id;
            return (
              <button
                key={structure.id}
                type="button"
                onClick={() => void loadPacket(structure.id)}
                className={`flex flex-col items-start rounded-md border px-2 py-1.5 text-left transition-colors ${
                  isActive
                    ? "border-accent/60 bg-surface-2"
                    : "border-transparent bg-surface-1 hover:bg-surface-2"
                }`}
              >
                <span className="text-xs font-medium text-gray-100">{structure.name}</span>
                <span className="text-[10px] text-gray-500">
                  {structure.kind} · {structure.format.toUpperCase()} · {structure.atomsCount.toLocaleString()} atoms ·{" "}
                  {formatBytes(structure.sizeBytes)}
                </span>
              </button>
            );
          })}
        </div>

        {packet ? (
          <div className="border-t border-border-subtle pt-2">
            <Row label="Chains" value={packet.structure.chains} />
            <Row label="Residues" value={packet.structure.residues.toLocaleString()} />
            <Row label="Bonds" value={packet.structure.bonds.toLocaleString()} />
            <Row label="Secondary structure" value={packet.secondaryStructure} />
            <div className="mt-2 flex flex-col gap-1">
              {packet.chains.map((chain) => (
                <button
                  key={chain.index}
                  type="button"
                  onClick={() => selectChain(chain.index)}
                  className="flex items-center justify-between rounded-md px-2 py-1 text-left hover:bg-surface-2"
                >
                  <span className="text-xs text-gray-200">
                    Chain {chain.id || "—"}{" "}
                    <span className="text-gray-500">({chain.kind})</span>
                  </span>
                  <span className="text-[10px] text-gray-500">{chain.residueCount} res</span>
                </button>
              ))}
            </div>
            <details className="mt-2">
              <summary className="cursor-pointer text-[11px] text-gray-400">
                Residues ({packet.residues.length})
              </summary>
              <div className="mt-1 max-h-48 overflow-y-auto">
                {packet.residues.map((residue) => (
                  <button
                    key={residue.index}
                    type="button"
                    onClick={() => selectResidue(residue.index)}
                    className="flex w-full items-center justify-between rounded px-2 py-0.5 text-left hover:bg-surface-2"
                  >
                    <span className="font-mono text-[11px] text-gray-300">
                      {residue.chainId}
                      {residue.name}
                      {residue.seq}
                      {residue.insertionCode}
                    </span>
                    <span className="text-[10px] text-gray-500">{residue.ss}</span>
                  </button>
                ))}
              </div>
            </details>
          </div>
        ) : null}
      </div>

      {dialog === "import" && activeProjectId ? (
        <ImportDialog projectId={activeProjectId} onClose={() => setDialog(null)} />
      ) : null}
      {dialog === "rcsb" && activeProjectId ? (
        <RcsbDialog projectId={activeProjectId} onClose={() => setDialog(null)} />
      ) : null}
      {dialog === "smiles" && activeProjectId ? (
        <ImportDialog projectId={activeProjectId} mode="smiles" onClose={() => setDialog(null)} />
      ) : null}
    </Panel>
  );
}
