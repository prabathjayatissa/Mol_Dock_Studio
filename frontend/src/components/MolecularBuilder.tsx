/**
 * Molecular builder: build a ligand from a SMILES string with an RDKit
 * ETKDGv3 3D conformer, computed entirely locally.
 */

import { useState } from "react";

import { useSessionStore } from "../stores/sessionStore";
import { useStructureStore } from "../stores/structureStore";
import { Button, Field, Panel, Spinner } from "./ui";

export function MolecularBuilder() {
  const activeProjectId = useSessionStore((state) => state.activeProjectId);
  const ligandFromSmiles = useStructureStore((state) => state.ligandFromSmiles);
  const loading = useStructureStore((state) => state.loading);
  const error = useStructureStore((state) => state.error);

  const [smiles, setSmiles] = useState("");
  const [name, setName] = useState("");

  if (!activeProjectId) {
    return (
      <Panel title="Molecular builder">
        <p className="text-[11px] text-gray-500">
          Create or select a project to build a ligand.
        </p>
      </Panel>
    );
  }

  async function build() {
    if (!smiles.trim() || !activeProjectId) return;
    await ligandFromSmiles(activeProjectId, smiles.trim(), name || "Ligand");
  }

  return (
    <Panel title="Molecular builder">
      <div className="flex flex-col gap-3">
        <p className="text-[11px] text-gray-500">
          Enter a SMILES string to generate a 3D conformer locally with RDKit
          (ETKDGv3 + MMFF94). The ligand is added to the current project.
        </p>

        <div className="flex flex-col gap-1">
          <Field label="SMILES">
            <input
              value={smiles}
              onChange={(event) => setSmiles(event.target.value)}
              placeholder="CC(=O)Oc1ccccc1C(=O)O"
              className="rounded-md border border-border-subtle bg-surface-2 px-2 py-1.5 font-mono text-xs text-gray-100 outline-none focus:border-accent"
            />
          </Field>
          <Field label="Name (optional)">
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Aspirin"
              className="rounded-md border border-border-subtle bg-surface-2 px-2 py-1.5 text-xs text-gray-100 outline-none focus:border-accent"
            />
          </Field>
        </div>

        {loading ? (
          <Spinner label="Building ligand…" />
        ) : (
          <Button
            disabled={loading || smiles.trim().length === 0}
            onClick={build}
          >
            Build ligand
          </Button>
        )}

        {error ? (
          <div className="rounded-md border border-red-500/40 bg-red-950/60 px-3 py-2 text-xs text-red-200">
            <p className="font-medium">{error.message}</p>
            {error.remediation ? (
              <p className="mt-1 text-red-300/80">{error.remediation}</p>
            ) : null}
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
