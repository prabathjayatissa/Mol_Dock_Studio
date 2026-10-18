/**
 * Show panel: reveal hidden chains and residues, or show everything.
 */

import { useViewerStore } from "../stores/viewerStore";
import { useStructureStore } from "../stores/structureStore";
import { Button, Field, Panel } from "./ui";

export function ShowPanel() {
  const packet = useStructureStore((state) => state.packet);
  const hiddenChains = useViewerStore((state) => state.hiddenChains);
  const hiddenResidues = useViewerStore((state) => state.hiddenResidues);
  const showChain = useViewerStore((state) => state.showChain);
  const showResidue = useViewerStore((state) => state.showResidue);
  const showAll = useViewerStore((state) => state.showAll);

  if (!packet) {
    return (
      <Panel title="Show">
        <p className="text-[11px] text-gray-500">Load a structure to manage visibility.</p>
      </Panel>
    );
  }

  const hiddenChainIds = hiddenChains.map((i) => packet.chains[i]?.id ?? i);
  const hiddenResidueLabels = hiddenResidues.map(
    (i) => packet.residues[i]?.label ?? i.toString(),
  );

  return (
    <Panel title="Show">
      <div className="flex flex-col gap-3">
        <Button
          onClick={showAll}
          title="Show all hidden chains and residues"
        >
          Show all
        </Button>

        {hiddenChainIds.length > 0 ? (
          <div>
            <Field label="Hidden chains">
              <div className="flex flex-wrap gap-1">
                {hiddenChainIds.map((id) => (
                  <Button
                    key={id}
                    variant="ghost"
                    onClick={() => showChain(packet.chains.findIndex((c) => c.id === id))}
                  >
                    {id}
                  </Button>
                ))}
              </div>
            </Field>
          </div>
        ) : null}

        {hiddenResidueLabels.length > 0 ? (
          <div>
            <Field label="Hidden residues">
              <div className="flex flex-wrap gap-1">
                {hiddenResidueLabels.map((label) => {
                  const index = hiddenResidues.findIndex(
                    (i) => packet.residues[i]?.label === label,
                  );
                  return (
                    <Button
                      key={label}
                      variant="ghost"
                      onClick={() => showResidue(index)}
                    >
                      {label}
                    </Button>
                  );
                })}
              </div>
            </Field>
          </div>
        ) : null}

        {hiddenChainIds.length === 0 && hiddenResidueLabels.length === 0 ? (
          <p className="text-[11px] text-gray-500">
            No chains or residues are hidden.
          </p>
        ) : null}
      </div>
    </Panel>
  );
}
