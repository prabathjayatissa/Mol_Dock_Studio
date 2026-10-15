/**
 * A single place to reach the live viewer engine from UI controls (screenshot,
 * reset view, export figure) without threading refs through every component.
 * The Viewport registers its engine here on mount and clears it on unmount.
 */

import type { ViewerEngine } from "./engine";

let engine: ViewerEngine | null = null;

export function setEngine(next: ViewerEngine | null): void {
  engine = next;
}

export function getEngine(): ViewerEngine | null {
  return engine;
}
