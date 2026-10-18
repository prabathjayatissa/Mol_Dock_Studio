/**
 * Action panel: measurements, screenshot, export, view reset, undo/redo.
 */

import { api } from "../api/client";
import { getEngine } from "../viewer/engineRef";
import { useViewerStore } from "../stores/viewerStore";
import { useStructureStore } from "../stores/structureStore";
import { Button, Field, Panel } from "./ui";
import { angleBetween, distanceBetween } from "../lib/measure";

export function ActionPanel() {
  const addMeasurement = useViewerStore((state) => state.addMeasurement);
  const removeMeasurement = useViewerStore((state) => state.removeMeasurement);
  const clearMeasurements = useViewerStore((state) => state.clearMeasurements);
  const measurements = useViewerStore((state) => state.measurements);
  const undo = useViewerStore((state) => state.undo);
  const redo = useViewerStore((state) => state.redo);
  const canUndo = useViewerStore((state) => state.canUndo);
  const canRedo = useViewerStore((state) => state.canRedo);
  const requestReset = useViewerStore((state) => state.requestReset);

  const packet = useStructureStore((state) => state.packet);
  const selection = useStructureStore((state) => state.selection);

  if (!packet) {
    return (
      <Panel title="Actions">
        <p className="text-[11px] text-gray-500">Load a structure to use actions.</p>
      </Panel>
    );
  }

  function measureDistance() {
    if (!packet) return;
    const atoms = [...selection];
    if (atoms.length < 2) return;
    const value = distanceBetween(packet, atoms[0], atoms[1]);
    addMeasurement({
      kind: "distance",
      atoms: [atoms[0], atoms[1]],
      value,
      label: `${value.toFixed(2)} Å`,
    });
  }

  function measureAngle() {
    if (!packet) return;
    const atoms = [...selection];
    if (atoms.length < 3) return;
    const value = angleBetween(packet, atoms[0], atoms[1], atoms[2]);
    addMeasurement({
      kind: "angle",
      atoms: atoms.slice(0, 3),
      value,
      label: `${value.toFixed(1)}°`,
    });
  }

  function screenshot() {
    if (!packet) return;
    const engine = getEngine();
    if (!engine) return;
    const dataUrl = engine.capturePng();
    const link = document.createElement("a");
    link.href = dataUrl;
    link.download = `${packet.structure.name.replace(/\s+/g, "_") || "moldock"}.png`;
    link.click();
  }

  function exportStructure(format: string) {
    if (!packet) return;
    const link = document.createElement("a");
    link.href = api.exportUrl(packet.structure.id, format);
    link.rel = "noopener";
    link.download = `${packet.structure.name.replace(/\s+/g, "_") || "moldock"}.${format}`;
    link.click();
  }

  return (
    <Panel title="Actions">
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <Field label="Measurements">
            <div className="flex gap-1.5">
              <Button
                onClick={measureDistance}
                disabled={selection.size < 2}
                title="Measure distance between 2 selected atoms"
              >
                Distance
              </Button>
              <Button
                onClick={measureAngle}
                disabled={selection.size < 3}
                title="Measure angle across 3 selected atoms"
              >
                Angle
              </Button>
              <Button
                variant="danger"
                onClick={clearMeasurements}
                disabled={measurements.length === 0}
                title="Clear all measurements"
              >
                Clear
              </Button>
            </div>
          </Field>
        </div>

        {measurements.length > 0 ? (
          <div className="flex flex-col gap-1">
            <Field label="Results">
              <ul className="flex flex-col gap-1">
                {measurements.map((m) => (
                  <li key={m.id} className="flex items-center justify-between rounded-md bg-surface-2 px-2 py-1 text-xs">
                    <span className="font-mono text-gray-200">
                      {m.kind === "distance" ? "d" : "∠"} {m.label}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeMeasurement(m.id)}
                      className="text-gray-500 hover:text-red-300"
                      title="Remove"
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            </Field>
          </div>
        ) : null}

        <div className="flex flex-col gap-1">
          <Field label="View">
            <div className="flex gap-1.5">
              <Button
                onClick={requestReset}
                disabled={!packet}
                title="Reset camera to frame the structure"
              >
                Reset view
              </Button>
              <Button onClick={undo} disabled={!canUndo} title="Undo">
                ↶ Undo
              </Button>
              <Button onClick={redo} disabled={!canRedo} title="Redo">
                ↷ Redo
              </Button>
            </div>
          </Field>
        </div>

        <div className="flex flex-col gap-1">
          <Field label="Export">
            <div className="flex gap-1.5">
              <Button onClick={screenshot} title="Save a PNG figure">
                PNG
              </Button>
              <select
                value=""
                onChange={(event) => {
                  if (event.target.value) exportStructure(event.target.value);
                  event.target.value = "";
                }}
                className="flex-1 rounded-md border border-border-subtle bg-surface-2 px-2 py-1 text-xs text-gray-100 outline-none focus:border-accent"
              >
                <option value="">Export…</option>
                <option value="pdb">PDB</option>
                <option value="mmcif">mmCIF</option>
                <option value="sdf">SDF</option>
                <option value="mol2">MOL2</option>
                <option value="xyz">XYZ</option>
              </select>
            </div>
          </Field>
        </div>
      </div>
    </Panel>
  );
}
