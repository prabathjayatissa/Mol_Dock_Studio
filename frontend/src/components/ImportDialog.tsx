import { useState } from "react";

import type { ImportResult } from "../api/types";
import { useStructureStore } from "../stores/structureStore";
import { Button, Field, Spinner } from "./ui";

interface ImportDialogProps {
  projectId: string;
  mode?: "file" | "smiles";
  onClose: () => void;
}

const ACCEPTED = ".pdb,.cif,.mmcif,.ent,.sdf,.mol,.mol2,.xyz,.pdbqt,.fasta,.fa,.fa.gz";

export function ImportDialog({ projectId, mode = "file", onClose }: ImportDialogProps) {
  const importFile = useStructureStore((state) => state.importFile);
  const ligandFromSmiles = useStructureStore((state) => state.ligandFromSmiles);
  const loading = useStructureStore((state) => state.loading);
  const error = useStructureStore((state) => state.error);
  const clearError = useStructureStore((state) => state.setError);

  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("");
  const [smiles, setSmiles] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);

  async function submitFile() {
    if (!file) return;
    const outcome = await importFile(projectId, file, { kind: kind || undefined, name: name || undefined });
    if (outcome) setResult(outcome);
  }

  async function submitSmiles() {
    if (!smiles.trim()) return;
    const outcome = await ligandFromSmiles(projectId, smiles.trim(), name || "Ligand");
    if (outcome) setResult(outcome);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog">
      <div className="w-full max-w-lg rounded-xl border border-border-subtle bg-surface-1 shadow-2xl">
        <header className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
          <h3 className="text-sm font-semibold text-gray-100">
            {mode === "smiles" ? "Build ligand from SMILES" : "Import structure"}
          </h3>
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        </header>

        <div className="flex flex-col gap-3 p-4">
          {mode === "file" ? (
            <>
              <Field label="File" hint={`Accepted: ${ACCEPTED}`}>
                <input
                  type="file"
                  accept={ACCEPTED}
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                  className="text-xs text-gray-300"
                />
              </Field>
              <Field label="Name (optional)">
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  className="rounded-md border border-border-subtle bg-surface-2 px-2 py-1.5 text-xs text-gray-100 outline-none focus:border-accent"
                />
              </Field>
              <Field label="Kind override (optional)" hint="Usually inferred from the file contents.">
                <select
                  value={kind}
                  onChange={(event) => setKind(event.target.value)}
                  className="rounded-md border border-border-subtle bg-surface-2 px-2 py-1.5 text-xs text-gray-100 outline-none focus:border-accent"
                >
                  <option value="">Auto-detect</option>
                  <option value="protein">Protein</option>
                  <option value="complex">Complex</option>
                  <option value="ligand">Ligand</option>
                  <option value="library">Library</option>
                  <option value="receptor">Receptor</option>
                </select>
              </Field>
            </>
          ) : (
            <>
              <Field label="SMILES" hint="A 3D conformer is generated locally with RDKit (ETKDGv3 + MMFF94).">
                <input
                  value={smiles}
                  onChange={(event) => setSmiles(event.target.value)}
                  placeholder="CC(=O)Oc1ccccc1C(=O)O"
                  className="rounded-md border border-border-subtle bg-surface-2 px-2 py-1.5 font-mono text-xs text-gray-100 outline-none focus:border-accent"
                />
              </Field>
              <Field label="Name">
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Aspirin"
                  className="rounded-md border border-border-subtle bg-surface-2 px-2 py-1.5 text-xs text-gray-100 outline-none focus:border-accent"
                />
              </Field>
            </>
          )}

          {loading ? <Spinner label="Importing…" /> : null}

          {error ? (
            <div className="rounded-md border border-red-500/40 bg-red-950/60 px-3 py-2 text-xs text-red-200">
              <p className="font-medium">{error.message}</p>
              {error.remediation ? <p className="mt-1 text-red-300/80">{error.remediation}</p> : null}
              <p className="mt-1 font-mono text-[10px] text-red-300/60">code: {error.code}</p>
            </div>
          ) : null}

          {result ? (
            <div className="rounded-md border border-emerald-500/40 bg-emerald-950/40 px-3 py-2 text-xs text-emerald-200">
              Imported <strong>{result.structure.name}</strong> — {result.structure.atomsCount} atoms,{" "}
              {result.structure.residuesCount} residues.
              {result.warnings.length > 0 ? (
                <ul className="mt-1 list-disc pl-4 text-emerald-100/80">
                  {result.warnings.map((warning) => (
                    <li key={warning.code}>{warning.message}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}

          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose} disabled={loading}>
              {result ? "Done" : "Cancel"}
            </Button>
            <Button
              variant="primary"
              disabled={loading || (mode === "file" ? !file : smiles.trim().length === 0)}
              onClick={() => {
                clearError(null);
                void (mode === "file" ? submitFile() : submitSmiles());
              }}
            >
              {mode === "file" ? "Import" : "Build"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
