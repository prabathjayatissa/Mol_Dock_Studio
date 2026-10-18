/**
 * Colour panel: colour scheme, surface settings, atom visibility filters.
 */

import { useViewerStore } from "../stores/viewerStore";
import { Button, Field, Panel, Segmented } from "./ui";

export function ColourPanel() {
  const colorScheme = useViewerStore((state) => state.colorScheme);
  const setColorScheme = useViewerStore((state) => state.setColorScheme);
  const showHydrogens = useViewerStore((state) => state.showHydrogens);
  const setShowHydrogens = useViewerStore((state) => state.setShowHydrogens);
  const showWaters = useViewerStore((state) => state.showWaters);
  const setShowWaters = useViewerStore((state) => state.setShowWaters);
  const showLabels = useViewerStore((state) => state.showLabels);
  const setShowLabels = useViewerStore((state) => state.setShowLabels);
  const surfaceOpacity = useViewerStore((state) => state.surfaceOpacity);
  const setSurfaceOpacity = useViewerStore((state) => state.setSurfaceOpacity);

  const COLOR_SCHEMES = [
    { value: "element" as const, label: "By element" },
    { value: "chain" as const, label: "By chain" },
    { value: "secondary-structure" as const, label: "By secondary structure" },
    { value: "residue" as const, label: "By residue" },
    { value: "hydropathy" as const, label: "By hydropathy" },
    { value: "bfactor" as const, label: "By B-factor" },
  ];

  return (
    <Panel title="Colour">
      <div className="flex flex-col gap-3">
        <div>
          <Field label="Colour scheme">
            <Segmented
              value={colorScheme}
              options={COLOR_SCHEMES}
              onChange={setColorScheme}
            />
          </Field>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
              Atom visibility
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <Button
              active={showHydrogens}
              onClick={() => setShowHydrogens(!showHydrogens)}
              title="Show hydrogen atoms"
            >
              H
            </Button>
            <Button
              active={showWaters}
              onClick={() => setShowWaters(!showWaters)}
              title="Show crystallographic waters"
            >
              H₂O
            </Button>
            <Button
              active={showLabels}
              onClick={() => setShowLabels(!showLabels)}
              title="Show residue labels"
            >
              Labels
            </Button>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <Field label="Surface opacity">
            <input
              type="range"
              min={0.05}
              max={1}
              step={0.05}
              value={surfaceOpacity}
              onChange={(event) => setSurfaceOpacity(Number(event.target.value))}
              className="w-full h-2 bg-surface-2 rounded-lg appearance-none cursor-pointer accent-accent"
            />
            <span className="text-[10px] text-gray-500 text-right">
              {Math.round(surfaceOpacity * 100)}%
            </span>
          </Field>
        </div>
      </div>
    </Panel>
  );
}
