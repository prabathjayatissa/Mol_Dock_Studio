import { useStructureStore } from "../stores/structureStore";
import { useViewerStore } from "../stores/viewerStore";
import { formatNumber } from "../lib/format";
import { atomLabel } from "../lib/measure";
import { Badge, Button, Panel, Row } from "./ui";

export function PropertiesPanel() {
  const packet = useStructureStore((state) => state.packet);
  const selection = useStructureStore((state) => state.selection);
  const toggleAtom = useStructureStore((state) => state.toggleAtom);
  const measurements = useViewerStore((state) => state.measurements);
  const removeMeasurement = useViewerStore((state) => state.removeMeasurement);
  const clearMeasurements = useViewerStore((state) => state.clearMeasurements);

  if (!packet) {
    return (
      <Panel title="Properties">
        <p className="text-[11px] text-gray-500">Load a structure to inspect its atoms, measurements and warnings.</p>
      </Panel>
    );
  }

  const atoms = [...selection];
  const primary = atoms.length > 0 ? atoms[atoms.length - 1] : null;
  const residue = primary !== null ? packet.residues[packet.atoms.residueIndex[primary]] : null;
  const properties = packet.properties ?? {};

  return (
    <Panel
      title="Properties"
      actions={
        selection.size > 0 ? (
          <Button variant="ghost" onClick={() => atoms.forEach((atom) => toggleAtom(atom))}>
            Clear selection
          </Button>
        ) : null
      }
    >
      <div className="flex flex-col gap-4">
        <div>
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">Selection</h4>
          {primary === null ? (
            <p className="text-[11px] text-gray-500">Click an atom in the viewport to inspect it. Shift-click adds to the selection.</p>
          ) : (
            <div className="flex flex-col gap-0.5">
              <Row label="Atom" value={packet.atoms.name[primary]} mono />
              <Row label="Residue" value={`${residue?.name ?? "?"} ${residue?.seq ?? ""}${residue?.insertionCode ?? ""}`} />
              <Row label="Chain" value={residue?.chainId || "—"} />
              <Row label="Element" value={packet.atoms.element[primary]} />
              <Row label="Position (Å)" value={`${formatNumber(packet.atoms.x[primary])}, ${formatNumber(packet.atoms.y[primary])}, ${formatNumber(packet.atoms.z[primary])}`} mono />
              <Row label="Occupancy" value={formatNumber(packet.atoms.occupancy[primary])} />
              <Row label="B-factor" value={formatNumber(packet.atoms.bfactor[primary])} />
              <Row label="Formal charge" value={packet.atoms.formalCharge[primary]} />
              {atoms.length > 1 ? <Row label="Selected atoms" value={atoms.length} /> : null}
              <Row label="Label" value={atomLabel(packet, primary)} mono />
            </div>
          )}
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
              Measurements ({measurements.length})
            </h4>
            {measurements.length > 0 ? (
              <Button variant="ghost" onClick={clearMeasurements}>
                Clear
              </Button>
            ) : null}
          </div>
          {measurements.length === 0 ? (
            <p className="text-[11px] text-gray-500">
              Select 2 atoms and press <em>Distance</em>, or 3 atoms and press <em>Angle</em>.
            </p>
          ) : (
            <ul className="flex flex-col gap-1">
              {measurements.map((measurement) => (
                <li
                  key={measurement.id}
                  className="flex items-center justify-between rounded-md bg-surface-2 px-2 py-1 text-xs"
                >
                  <span className="font-mono text-gray-200">
                    <Badge tone={measurement.kind === "distance" ? "good" : "neutral"}>
                      {measurement.kind === "distance" ? "d" : "∠"}
                    </Badge>{" "}
                    {measurement.label}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeMeasurement(measurement.id)}
                    className="text-gray-500 hover:text-red-300"
                    title="Remove"
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {packet.warnings.length > 0 ? (
          <div>
            <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
              Import warnings ({packet.warnings.length})
            </h4>
            <ul className="flex flex-col gap-1">
              {packet.warnings.map((warning) => (
                <li key={warning.code} className="rounded-md border border-amber-500/30 bg-amber-950/30 px-2 py-1 text-[11px] text-amber-200">
                  <span className="font-mono text-[10px] text-amber-300/70">{warning.code}</span>
                  <p>{warning.message}</p>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <div>
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">Composition</h4>
          {typeof properties.formula === "string" ? <Row label="Formula" value={properties.formula} mono /> : null}
          {typeof properties.molecularWeight === "number" ? (
            <Row label="Molecular weight" value={`${formatNumber(properties.molecularWeight)} Da`} />
          ) : null}
          {typeof properties.radiusOfGyration === "number" ? (
            <Row label="Radius of gyration" value={`${formatNumber(properties.radiusOfGyration)} Å`} />
          ) : null}
          {typeof properties.disulfideCount === "number" ? (
            <Row label="Disulfide bonds" value={properties.disulfideCount} />
          ) : null}
          {properties.secondaryStructure ? (
            <div className="mt-1 flex gap-1">
              {(["helix", "sheet", "coil"] as const).map((key) => {
                const value = (properties.secondaryStructure as Record<string, number>)[key];
                if (value === undefined) return null;
                return (
                  <Badge key={key} tone={key === "helix" ? "bad" : key === "sheet" ? "warn" : "neutral"}>
                    {key} {formatNumber(value, 2)}
                  </Badge>
                );
              })}
            </div>
          ) : null}
        </div>

        {Object.keys(properties.descriptors ?? {}).length > 0 ? (
          <div>
            <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">Ligand descriptors</h4>
            {Object.entries(properties.descriptors as Record<string, unknown>).map(([key, value]) => (
              <Row
                key={key}
                label={key}
                value={typeof value === "number" ? formatNumber(value, 3) : String(value ?? "—")}
                mono
              />
            ))}
            <p className="mt-1 text-[10px] text-gray-500">
              Computed with RDKit. These are calculated descriptors, not measured properties.
            </p>
          </div>
        ) : null}

        <div>
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">Provenance</h4>
          <Row label="Source" value={packet.structure.source} />
          <Row label="Format" value={packet.structure.format.toUpperCase()} />
          <Row label="Parser" value={String(packet.provenance["tool"] ?? "—")} />
          {packet.provenance["toolVersion"] ? (
            <Row label="Parser version" value={String(packet.provenance["toolVersion"])} mono />
          ) : null}
          {packet.provenance["importedAt"] ? (
            <Row label="Imported" value={new Date(String(packet.provenance["importedAt"])).toLocaleString()} />
          ) : null}
        </div>
      </div>
    </Panel>
  );
}
