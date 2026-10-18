import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api } from "../api/client";
import type { SurfacePayload } from "../api/types";
import { useSessionStore } from "../stores/sessionStore";
import { useStructureStore } from "../stores/structureStore";
import { useViewerStore } from "../stores/viewerStore";
import { ViewerEngine } from "../viewer/engine";
import { setEngine } from "../viewer/engineRef";
import { Spinner } from "./ui";

export function Viewport() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const engineRef = useRef<ViewerEngine | null>(null);

  const packet = useStructureStore((state) => state.packet);
  const selection = useStructureStore((state) => state.selection);
  const toggleAtom = useStructureStore((state) => state.toggleAtom);
  const setSelection = useStructureStore((state) => state.setSelection);

  const document = useViewerStore();
  const resetNonce = useViewerStore((state) => state.resetNonce);
  const capability = useSessionStore((state) => state.capability);

  const [surface, setSurface] = useState<SurfacePayload | null>(null);
  const [surfaceLoading, setSurfaceLoading] = useState(false);
  const [surfaceError, setSurfaceError] = useState<string | null>(null);

  // Create the engine exactly once, and register it for toolbar actions.
  useEffect(() => {
    if (!containerRef.current) return undefined;
    const engine = new ViewerEngine(containerRef.current, {
      onPick: (atomIndex, additive) => {
        if (atomIndex === null) {
          if (!additive) useStructureStore.getState().clearSelection();
          return;
        }
        if (additive) toggleAtom(atomIndex);
        else setSelection([atomIndex], false);
      },
    });
    engineRef.current = engine;
    setEngine(engine);
    return () => {
      setEngine(null);
      engine.dispose();
      engineRef.current = null;
    };
  }, [toggleAtom, setSelection]);

  // Load a new structure.
  useEffect(() => {
    if (packet) engineRef.current?.setStructure(packet);
  }, [packet]);

  // Apply viewer settings whenever anything visual changes.
  const documentKey = useMemo(
    () =>
      [
        document.representation,
        document.colorScheme,
        document.showHydrogens,
        document.showWaters,
        document.surfaceMode,
        document.showLabels,
        document.labelMode,
        document.hiddenChains.join(","),
        document.hiddenResidues.join(","),
        document.background,
        document.measurements.map((m) => m.id).join(","),
      ].join("|"),
    [document],
  );

  useEffect(() => {
    engineRef.current?.update(document, selection);
    // documentKey intentionally captures the fields that affect the scene.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentKey, selection]);

  useEffect(() => {
    engineRef.current?.setSurface(document.showSurface ? surface : null, {
      mode: document.surfaceMode,
      opacity: document.surfaceOpacity,
    });
  }, [surface, document.showSurface, document.surfaceMode, document.surfaceOpacity]);

  useEffect(() => {
    engineRef.current?.setSurfaceOpacity(document.surfaceOpacity);
  }, [document.surfaceOpacity]);

  useEffect(() => {
    if (resetNonce > 0) engineRef.current?.resetView();
  }, [resetNonce]);

  // Fetch the surface when it is switched on (or the mode changes).
  const structureId = packet?.structure.id ?? null;
  useEffect(() => {
    if (!document.showSurface || !structureId) {
      setSurface(null);
      setSurfaceError(null);
      return;
    }
    if (surface && surface.structureId === structureId && surface.stats.mode === document.surfaceMode) {
      return;
    }
    let cancelled = false;
    setSurfaceLoading(true);
    setSurfaceError(null);
    api
      .getSurface(structureId, { mode: document.surfaceMode, useCache: true })
      .then((payload) => {
        if (!cancelled) setSurface(payload);
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        const message = cause instanceof ApiError ? cause.message : String(cause);
        setSurfaceError(message);
      })
      .finally(() => {
        if (!cancelled) setSurfaceLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [document.showSurface, document.surfaceMode, structureId, surface]);

  const emptyState = !packet;
  const surfaceCapability = capability("surface-sas");

  return (
    <div className="relative h-full w-full overflow-hidden bg-surface-0">
      <div ref={containerRef} className="h-full w-full" />

      {emptyState ? (
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 text-center">
          <p className="text-sm font-medium text-gray-300">No structure loaded</p>
          <p className="max-w-xs text-xs text-gray-500">
            Import a PDB/mmCIF/SDF file, fetch an entry from the RCSB PDB, or build a ligand from
            SMILES to begin.
          </p>
        </div>
      ) : null}

      {surfaceLoading ? (
        <div className="absolute right-3 top-3 rounded-md border border-border-subtle bg-surface-1/90 px-3 py-2">
          <Spinner label="Computing surface…" />
        </div>
      ) : null}

      {surfaceError ? (
        <div className="absolute right-3 top-3 max-w-xs rounded-md border border-red-500/40 bg-red-950/80 px-3 py-2 text-xs text-red-200">
          Surface failed: {surfaceError}
        </div>
      ) : null}

      {surface && document.showSurface ? (
        <div className="absolute bottom-3 left-3 rounded-md border border-border-subtle bg-surface-1/90 px-3 py-1.5 font-mono text-[10px] text-gray-400">
          {surface.stats.mode.toUpperCase()} · {surface.stats.vertices.toLocaleString()} verts ·{" "}
          {surface.stats.triangles.toLocaleString()} tris · area {surface.stats.area.toFixed(0)} Å²
          {surface.stats.warnings.length > 0 ? ` · ${surface.stats.warnings.length} warning(s)` : ""}
        </div>
      ) : null}

      {surfaceCapability && surfaceCapability.status !== "available" ? (
        <div className="absolute bottom-3 right-3 max-w-xs rounded-md border border-amber-500/40 bg-amber-950/70 px-3 py-2 text-[11px] text-amber-200">
          Surface generation unavailable: {surfaceCapability.remediation ?? surfaceCapability.status}
        </div>
      ) : null}
    </div>
  );
}
