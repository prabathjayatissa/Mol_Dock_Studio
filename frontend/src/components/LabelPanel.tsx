/**
 * Label panel: toggle residue/selected-atom labels and label atoms on pick.
 */

import { useViewerStore } from "../stores/viewerStore";
import { useStructureStore } from "../stores/structureStore";
import type { LabelMode } from "../stores/viewerStore";
import { Button, Field, Panel, Segmented } from "./ui";

export function LabelPanel() {
  const packet = useStructureStore((state) => state.packet);
  const selection = useStructureStore((state) => state.selection);
  const showLabels = useViewerStore((state) => state.showLabels);
  const setShowLabels = useViewerStore((state) => state.setShowLabels);
  const labelMode = useViewerStore((state) => state.labelMode);
  const setLabelMode = useViewerStore((state) => state.setLabelMode);
  const labelSelectedAtoms = useViewerStore((state) => state.labelSelectedAtoms);
  const labelAtom = useViewerStore((state) => state.labelAtom);
  const clearLabels = useViewerStore((state) => state.clearLabels);

  if (!packet) {
    return (
      <Panel title="Label">
        <p className="text-[11px] text-gray-500">Load a structure to add labels.</p>
      </Panel>
    );
  }

  const LABEL_MODES: { value: LabelMode; label: string }[] = [
    { value: "none", label: "Off" },
    { value: "residue", label: "All residues" },
    { value: "selected", label: "Selected atoms" },
  ];

  return (
    <Panel title="Label">
      <div className="flex flex-col gap-3">
        <div>
          <Field label="Label mode">
            <Segmented
              value={labelMode}
              options={LABEL_MODES}
              onChange={setLabelMode}
            />
          </Field>
        </div>

        <div className="flex items-center gap-1.5">
          <Button
            active={showLabels}
            onClick={() => setShowLabels(!showLabels)}
            title="Toggle labels on/off"
          >
            Toggle
          </Button>
          <Button
            variant="danger"
            onClick={clearLabels}
            disabled={labelSelectedAtoms.length === 0 && !showLabels}
            title="Clear all labels"
          >
            Clear
          </Button>
        </div>

        <div className="flex flex-col gap-1">
          <Field label="Label selected atoms">
            <p className="text-[11px] text-gray-500">
              Shift-click atoms in the viewport, then press Label.
            </p>
            <Button
              variant="ghost"
              onClick={() => {
                [...selection].forEach((atomIndex) => labelAtom(atomIndex));
              }}
              disabled={selection.size === 0}
              title="Label all currently selected atoms"
            >
              Label selected ({selection.size})
            </Button>
          </Field>

          <div className="text-[11px] text-gray-500">
            {labelSelectedAtoms.length > 0 ? (
              <>
                {labelSelectedAtoms.length} atom(s) labelled.{" "}
                <span className="font-mono text-gray-400">
                  {labelSelectedAtoms
                    .map((i) => {
                      const residueIndex = packet.atoms.residueIndex[i];
                      const residue = packet.residues[residueIndex];
                      return residue ? residue.label : `atom ${i}`;
                    })
                    .join(", ")}
                </span>
              </>
            ) : (
              "No atoms labelled."
            )}
          </div>
        </div>
      </div>
    </Panel>
  );
}
