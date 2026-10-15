import { useState } from "react";

import type { ImportResult } from "../api/types";
import { useStructureStore } from "../stores/structureStore";
import { Button, Field, Spinner } from "./ui";

interface RcsbDialogProps {
  projectId: string;
  onClose: () => void;
}

const EXAMPLE_ENTRIES = ["1UBQ", "3PTB", "1STP", "4HHB", "6LU7"];

export function RcsbDialog({ projectId, onClose }: RcsbDialogProps) {
  const fetchRcsb = useStructureStore((state) => state.fetchRcsb);
  const loading = useStructureStore((state) => state.loading);
  const error = useStructureStore((state) => state.error);

  const [entryId, setEntryId] = useState("1UBQ");
  const [format, setFormat] = useState<"pdb" | "mmcif">("pdb");
  const [result, setResult] = useState<ImportResult | null>(null);

  async function submit() {
    const outcome = await fetchRcsb(projectId, entryId.trim(), format);
    if (outcome) setResult(outcome);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog">
      <div className="w-full max-w-md rounded-xl border border-border-subtle bg-surface-1 shadow-2xl">
        <header className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
          <h3 className="text-sm font-semibold text-gray-100">Fetch from the RCSB PDB</h3>
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        </header>

        <div className="flex flex-col gap-3 p-4">
          <Field label="PDB ID" hint="The entry is downloaded from files.rcsb.org and parsed locally.">
            <input
              value={entryId}
              onChange={(event) => setEntryId(event.target.value.toUpperCase())}
              maxLength={8}
              className="rounded-md border border-border-subtle bg-surface-2 px-2 py-1.5 font-mono text-xs uppercase text-gray-100 outline-none focus:border-accent"
            />
          </Field>

          <div className="flex flex-wrap gap-1">
            {EXAMPLE_ENTRIES.map((entry) => (
              <Button key={entry} variant="ghost" onClick={() => setEntryId(entry)}>
                {entry}
              </Button>
            ))}
          </div>

          <Field label="Format">
            <select
              value={format}
              onChange={(event) => setFormat(event.target.value as "pdb" | "mmcif")}
              className="rounded-md border border-border-subtle bg-surface-2 px-2 py-1.5 text-xs text-gray-100 outline-none focus:border-accent"
            >
              <option value="pdb">PDB</option>
              <option value="mmcif">mmCIF</option>
            </select>
          </Field>

          {loading ? <Spinner label="Downloading…" /> : null}

          {error ? (
            <div className="rounded-md border border-red-500/40 bg-red-950/60 px-3 py-2 text-xs text-red-200">
              <p className="font-medium">{error.message}</p>
              {error.remediation ? <p className="mt-1 text-red-300/80">{error.remediation}</p> : null}
            </div>
          ) : null}

          {result ? (
            <div className="rounded-md border border-emerald-500/40 bg-emerald-950/40 px-3 py-2 text-xs text-emerald-200">
              Fetched <strong>{result.structure.name}</strong> — {result.structure.atomsCount} atoms.
            </div>
          ) : null}

          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose} disabled={loading}>
              {result ? "Done" : "Cancel"}
            </Button>
            <Button variant="primary" disabled={loading || entryId.trim().length < 4} onClick={() => void submit()}>
              Fetch
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
