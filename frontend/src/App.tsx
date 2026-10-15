import { useEffect } from "react";

import { useSessionStore } from "./stores/sessionStore";
import { PropertiesPanel } from "./components/PropertiesPanel";
import { StatusBar } from "./components/StatusBar";
import { StructurePanel } from "./components/StructurePanel";
import { Toolbar } from "./components/Toolbar";
import { Viewport } from "./components/Viewport";
import { WorkflowPanel } from "./components/WorkflowPanel";

export default function App() {
  const loadHealth = useSessionStore((state) => state.loadHealth);
  const loadProjects = useSessionStore((state) => state.loadProjects);
  const health = useSessionStore((state) => state.health);

  useEffect(() => {
    void loadHealth();
    void loadProjects();
  }, [loadHealth, loadProjects]);

  // Poll health periodically so a backend that comes up later is noticed.
  useEffect(() => {
    const timer = setInterval(() => void loadHealth(), 30_000);
    return () => clearInterval(timer);
  }, [loadHealth]);

  return (
    <div className="flex h-full flex-col bg-surface-0 text-gray-100">
      <header className="flex items-center gap-3 border-b border-border-subtle bg-surface-1 px-4 py-2.5">
        <div className="flex items-baseline gap-2">
          <h1 className="text-sm font-semibold tracking-tight text-gray-50">MolDock Studio</h1>
          <span className="text-[10px] uppercase tracking-widest text-accent">Phase 1 · viewer</span>
        </div>
        <p className="hidden text-[11px] text-gray-500 md:block">
          Molecular visualisation and docking workbench — original implementation
        </p>
        {health ? (
          <span className="ml-auto text-[10px] text-gray-500">
            {health.capabilities.filter((c) => c.status === "available").length}/{health.capabilities.length} tools
            available
          </span>
        ) : null}
      </header>

      <Toolbar />

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-2 p-2 lg:grid-cols-[300px_minmax(0,1fr)_320px]">
        <div className="flex min-h-0 flex-col gap-2">
          <StructurePanel />
        </div>

        <div className="min-h-0 overflow-hidden rounded-lg border border-border-subtle">
          <Viewport />
        </div>

        <div className="flex min-h-0 flex-col gap-2">
          <PropertiesPanel />
          <WorkflowPanel />
        </div>
      </main>

      <StatusBar />
    </div>
  );
}
