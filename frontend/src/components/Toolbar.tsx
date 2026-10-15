import { api } from "../api/client";
import { useSessionStore } from "../stores/sessionStore";
import { useStructureStore } from "../stores/structureStore";
import { useViewerStore, type ColorScheme, type Representation, type SurfaceMode } from "../stores/viewerStore";
import { getEngine } from "../viewer/engineRef";
import { angleBetween, distanceBetween } from "../lib/measure";
import { Button, Segmented } from "./ui";

const REPRESENTATIONS: { value: Representation; label: string; title: string }[] = [
  { value: "cartoon", label: "Cartoon", title: "Schematic ribbon through the Cα trace" },
  { value: "backbone", label: "Trace", title: "Cα trace plus backbone atoms" },
  { value: "ball-stick", label: "Ball & stick", title: "Atoms scaled to 30% vdW with stick bonds" },
  { value: "stick", label: "Stick", title: "Bonds as cylinders" },
  { value: "lines", label: "Lines", title: "Thin bond lines" },
  { value: "spacefill", label: "Spacefill", title: "Atoms at full van der Waals radius" },
];

const COLOR_SCHEMES: { value: ColorScheme; label: string }[] = [
  { value: "element", label: "By element" },
  { value: "chain", label: "By chain" },
  { value: "secondary-structure", label: "By secondary structure" },
  { value: "residue", label: "By residue" },
  { value: "hydropathy", label: "By hydropathy" },
  { value: "bfactor", label: "By B-factor" },
];

const SURFACE_MODES: { value: SurfaceMode; label: string; title: string }[] = [
  { value: "sas", label: "SAS", title: "Solvent-accessible surface (Richards probe)" },
  { value: "vdw", label: "vdW", title: "Exact van der Waals surface" },
];

export function Toolbar() {
  const viewer = useViewerStore();
  const packet = useStructureStore((state) => state.packet);
  const selection = useStructureStore((state) => state.selection);
  const addMeasurement = useViewerStore((state) => state.addMeasurement);
  const capability = useSessionStore((state) => state.capability);

  const surfaceAvailable = capability("surface-sas")?.status === "available";
  const hasStructure = Boolean(packet);

  function measureDistance() {
    if (!packet) return;
    const atoms = [...selection];
    if (atoms.length < 2) return;
    const value = distanceBetween(packet, atoms[0], atoms[1]);
    addMeasurement({ kind: "distance", atoms: [atoms[0], atoms[1]], value, label: `${value.toFixed(2)} Å` });
  }

  function measureAngle() {
    if (!packet) return;
    const atoms = [...selection];
    if (atoms.length < 3) return;
    const value = angleBetween(packet, atoms[0], atoms[1], atoms[2]);
    addMeasurement({ kind: "angle", atoms: atoms.slice(0, 3), value, label: `${value.toFixed(1)}°` });
  }

  function screenshot() {
    const engine = getEngine();
    if (!engine || !packet) return;
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
    link.click();
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border-subtle bg-surface-1 px-3 py-2">
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">Represent</span>
        <Segmented
          value={viewer.representation}
          options={REPRESENTATIONS}
          onChange={viewer.setRepresentation}
        />
      </div>

      <div className="flex items-center gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">Colour</span>
        <select
          value={viewer.colorScheme}
          onChange={(event) => viewer.setColorScheme(event.target.value as ColorScheme)}
          className="rounded-md border border-border-subtle bg-surface-2 px-2 py-1 text-xs text-gray-100 outline-none focus:border-accent"
        >
          {COLOR_SCHEMES.map((scheme) => (
            <option key={scheme.value} value={scheme.value}>
              {scheme.label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex items-center gap-1.5">
        <Button active={viewer.showHydrogens} onClick={() => viewer.setShowHydrogens(!viewer.showHydrogens)} title="Show hydrogens">
          H
        </Button>
        <Button active={viewer.showWaters} onClick={() => viewer.setShowWaters(!viewer.showWaters)} title="Show crystallographic waters">
          H₂O
        </Button>
        <Button active={viewer.showLabels} onClick={() => viewer.setShowLabels(!viewer.showLabels)} title="Show residue labels">
          Labels
        </Button>
      </div>

      <div className="flex items-center gap-2">
        <Button
          active={viewer.showSurface}
          disabled={!surfaceAvailable || !hasStructure}
          onClick={() => viewer.setShowSurface(!viewer.showSurface)}
          title={
            surfaceAvailable
              ? "Toggle the molecular surface"
              : capability("surface-sas")?.remediation ?? "Surface generation unavailable on this machine"
          }
        >
          Surface
        </Button>
        {viewer.showSurface ? (
          <>
            <Segmented value={viewer.surfaceMode} options={SURFACE_MODES} onChange={viewer.setSurfaceMode} />
            <input
              type="range"
              min={0.05}
              max={1}
              step={0.05}
              value={viewer.surfaceOpacity}
              onChange={(event) => viewer.setSurfaceOpacity(Number(event.target.value))}
              className="w-20"
              title="Surface opacity"
            />
          </>
        ) : null}
      </div>

      <div className="ml-auto flex items-center gap-1.5">
        <Button onClick={viewer.undo} disabled={viewer.past.length === 0} title="Undo viewer change">
          ↶
        </Button>
        <Button onClick={viewer.redo} disabled={viewer.future.length === 0} title="Redo viewer change">
          ↷
        </Button>
        <Button onClick={viewer.requestReset} disabled={!hasStructure} title="Reset the camera">
          Reset view
        </Button>
        <Button
          onClick={() => viewer.setBackground(viewer.background === "dark" ? "light" : "dark")}
          title="Toggle the background"
        >
          {viewer.background === "dark" ? "Light bg" : "Dark bg"}
        </Button>
        <Button onClick={measureDistance} disabled={selection.size < 2} title="Measure the distance between two selected atoms">
          Distance
        </Button>
        <Button onClick={measureAngle} disabled={selection.size < 3} title="Measure the angle across three selected atoms">
          Angle
        </Button>
        <Button onClick={viewer.clearMeasurements} disabled={viewer.measurements.length === 0}>
          Clear measures
        </Button>
        <Button onClick={screenshot} disabled={!hasStructure} title="Save a PNG figure">
          PNG
        </Button>
        <select
          value=""
          disabled={!hasStructure}
          onChange={(event) => {
            if (event.target.value) exportStructure(event.target.value);
            event.target.value = "";
          }}
          className="rounded-md border border-border-subtle bg-surface-2 px-2 py-1 text-xs text-gray-100 outline-none focus:border-accent disabled:opacity-40"
          title="Export the structure"
        >
          <option value="">Export…</option>
          <option value="pdb">PDB</option>
          <option value="mmcif">mmCIF</option>
          <option value="sdf">SDF (small molecules)</option>
          <option value="mol2">MOL2</option>
          <option value="xyz">XYZ</option>
        </select>
      </div>
    </div>
  );
}
