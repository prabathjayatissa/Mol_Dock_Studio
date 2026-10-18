/**
 * Hide panel: hide individual chains and residues from the view.
 */

import { useViewerStore } from "../stores/viewerStore";
import { useStructureStore } from "../stores/structureStore";
import { Button, Field, Panel } from "./ui";

export function HidePanel() {
  const packet = useStructureStore((state) => state.packet);
  const hiddenChains = useViewerStore((state) => state.hiddenChains);
  const hiddenResidues = useViewerStore((state) => state.hiddenResidues);
  const hideChain = useViewerStore((state) => state.hideChain);
  const hideResidue = useViewerStore((state) => state.hideResidue);

  if (!packet) {
    return (
      <Panel title="Hide">
        <p className="text-[11px] text-gray-500">Load a structure to manage visibility.</p>
      </Panel>
    );
  }

  const visibleChains = packet.chains.filter((_, i) => !hiddenChains.includes(i));
  const visibleResidues = packet.residues.filter((_, i) => !hiddenResidues.includes(i));

  return (
    <Panel title="Hide">
      <div className="flex flex-col gap-3">
        <div>
          <Field label="Hide chain">
            <div className="flex flex-wrap gap-1">
              {visibleChains.map((chain) => (
                <Button
                  key={chain.index}
                  variant="ghost"
                  onClick={() => hideChain(chain.index)}
                >
                  {chain.id || "—"}
                </Button>
              ))}
            </div>
          </Field>
        </div>

        <div className="flex flex-col gap-1">
          <Field label="Hide residue">
            <div className="flex flex-wrap gap-1">
              {visibleResidues.map((residue) => (
                <Button
                  key={residue.index}
                  variant="ghost"
                  onClick={() => hideResidue(residue.index)}
                >
                  {residue.label}
                </Button>
              ))}
            </div>
          </Field>
        </div>

        {visibleChains.length === 0 && visibleResidues.length === 0 ? (
          <p className="text-[11px] text-gray-500">
            Everything is already hidden. Use Show panel to reveal.
          </p>
        ) : null}
      </div>
    </Panel>
  );
}
