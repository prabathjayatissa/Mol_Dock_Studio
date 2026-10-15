/**
 * MolDock Studio viewer engine.
 *
 * An original Three.js renderer — no third-party molecular viewer is used. The
 * engine owns a scene and turns a structure packet plus the current viewer
 * document (representation, colour scheme, filters, measurements) into GPU
 * objects. It never reads the network; the React layer feeds it.
 *
 * Design notes:
 *  * Atoms and bonds are drawn with `InstancedMesh`, so a 100k-atom structure is
 *    a handful of draw calls.
 *  * Picking is analytic (ray–sphere), see `picking.ts`.
 *  * The structure is translated by `-centroid` inside `this.root`, so the
 *    camera orbits the molecule, and picking adds the same offset back.
 */

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { StructurePacket, SurfacePayload } from "../api/types";
import type { ViewerDocument } from "../stores/viewerStore";
import { buildCartoon } from "./cartoon";
import { buildColoringContext, residueColor, type ColoringContext } from "./coloring";
import { pickAtom, rayFromNdc } from "./picking";
import { computeAtomStyles, computeBondPlan, type AtomStyle } from "./representations";
import { buildSurfaceGeometry } from "./surface";

export interface ViewerEngineOptions {
  onPick?: (atomIndex: number | null, additive: boolean) => void;
  onHover?: (atomIndex: number | null) => void;
}

const BACKGROUNDS = {
  dark: new THREE.Color("#0b0f14"),
  light: new THREE.Color("#eef2f7"),
};

interface LabelEntry {
  atomIndex: number;
  text: string;
}

export class ViewerEngine {
  private readonly container: HTMLElement;
  private readonly options: ViewerEngineOptions;

  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly controls: OrbitControls;
  private readonly root = new THREE.Group();

  private readonly resizeObserver: ResizeObserver;
  private animationFrame = 0;
  private disposed = false;

  private packet: StructurePacket | null = null;
  private coloring: ColoringContext | null = null;
  private selection: Set<number> = new Set();

  private atomStyles: AtomStyle | null = null;
  private centerOffset = new THREE.Vector3();

  // Drawables
  private atomMesh: THREE.InstancedMesh | null = null;
  private bondMesh: THREE.InstancedMesh | null = null;
  private lineSegments: THREE.LineSegments | null = null;
  private cartoonMesh: THREE.Mesh | null = null;
  private backboneTrace: THREE.LineSegments | null = null;
  private surfaceMesh: THREE.Mesh | null = null;
  private readonly selectionGroup = new THREE.Group();
  private readonly labelGroup = new THREE.Group();
  private readonly measurementGroup = new THREE.Group();

  private pointerDown = { x: 0, y: 0, time: 0 };

  private readonly atomGeometry = new THREE.SphereGeometry(1, 18, 12);
  private readonly bondGeometry = new THREE.CylinderGeometry(1, 1, 1, 12, 1, false);
  private readonly up = new THREE.Vector3(0, 1, 0);

  constructor(container: HTMLElement, options: ViewerEngineOptions = {}) {
    this.container = container;
    this.options = options;

    const width = container.clientWidth || 640;
    const height = container.clientHeight || 480;

    this.camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100000);
    this.camera.position.set(0, 0, 60);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(width, height);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.domElement.style.display = "block";
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "100%";
    container.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.controls.rotateSpeed = 0.85;
    this.controls.panSpeed = 0.9;

    const hemi = new THREE.HemisphereLight(0xffffff, 0x334455, 1.15);
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(1, 1.4, 1);
    const fill = new THREE.DirectionalLight(0xaaccff, 0.5);
    fill.position.set(-1, -0.6, -1);
    this.scene.add(hemi, key, fill);
    this.scene.add(this.root);
    this.root.add(this.selectionGroup, this.labelGroup, this.measurementGroup);

    this.scene.background = BACKGROUNDS.dark;

    this.resizeObserver = new ResizeObserver(() => this.onResize());
    this.resizeObserver.observe(container);

    const element = this.renderer.domElement;
    element.addEventListener("pointerdown", this.onPointerDown);
    element.addEventListener("pointerup", this.onPointerUp);
    element.addEventListener("pointermove", this.onPointerMove);
    element.addEventListener("pointerleave", this.onPointerLeave);

    this.animate();
  }

  // --- lifecycle ----------------------------------------------------------
  private animate = (): void => {
    if (this.disposed) return;
    this.animationFrame = requestAnimationFrame(this.animate);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };

  private onResize(): void {
    const width = this.container.clientWidth || 640;
    const height = this.container.clientHeight || 480;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }

  dispose(): void {
    this.disposed = true;
    cancelAnimationFrame(this.animationFrame);
    this.resizeObserver.disconnect();
    const element = this.renderer.domElement;
    element.removeEventListener("pointerdown", this.onPointerDown);
    element.removeEventListener("pointerup", this.onPointerUp);
    element.removeEventListener("pointermove", this.onPointerMove);
    element.removeEventListener("pointerleave", this.onPointerLeave);
    this.controls.dispose();
    this.clearDrawables();
    this.atomGeometry.dispose();
    this.bondGeometry.dispose();
    this.renderer.dispose();
    if (element.parentElement === this.container) this.container.removeChild(element);
  }

  // --- structure ----------------------------------------------------------
  setStructure(packet: StructurePacket): void {
    this.packet = packet;
    const [cx, cy, cz] = packet.structure.centroid;
    this.centerOffset.set(-cx, -cy, -cz);
    this.root.position.copy(this.centerOffset);
    this.clearDrawables();
    this.frameCamera();
  }

  private frameCamera(): void {
    if (!this.packet) return;
    const radius = Math.max(6, this.packet.structure.radius);
    const distance = radius / Math.sin((this.camera.fov * Math.PI) / 360) + radius * 0.35;
    this.camera.near = Math.max(0.1, distance / 500);
    this.camera.far = distance * 40;
    this.camera.updateProjectionMatrix();
    this.camera.position.set(0, 0, distance);
    this.controls.target.set(0, 0, 0);
    this.controls.update();
  }

  resetView(): void {
    this.frameCamera();
  }

  capturePng(): string {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL("image/png");
  }

  // --- settings -----------------------------------------------------------
  update(doc: ViewerDocument, selection: Set<number>): void {
    this.selection = selection;
    this.scene.background = BACKGROUNDS[doc.background];
    if (!this.packet) return;

    this.coloring = buildColoringContext(this.packet, doc.colorScheme);
    this.atomStyles = computeAtomStyles(this.packet, this.coloring, {
      showHydrogens: doc.showHydrogens,
      showWaters: doc.showWaters,
    }, doc.representation);

    this.rebuildAtoms();
    this.rebuildBonds(doc);
    this.rebuildCartoon(doc);
    this.rebuildBackbone(doc);
    this.rebuildSelection();
    this.rebuildLabels(doc);
    this.rebuildMeasurements(doc);
  }

  private clearGroup(group: THREE.Group): void {
    for (const child of [...group.children]) {
      group.remove(child);
      disposeObject(child);
    }
  }

  private clearDrawables(): void {
    for (const mesh of [this.atomMesh, this.bondMesh, this.lineSegments, this.cartoonMesh, this.backboneTrace, this.surfaceMesh]) {
      if (mesh) {
        this.root.remove(mesh);
        disposeObject(mesh);
      }
    }
    this.atomMesh = null;
    this.bondMesh = null;
    this.lineSegments = null;
    this.cartoonMesh = null;
    this.backboneTrace = null;
    this.surfaceMesh = null;
    this.clearGroup(this.selectionGroup);
    this.clearGroup(this.labelGroup);
    this.clearGroup(this.measurementGroup);
  }

  private rebuildAtoms(): void {
    if (this.atomMesh) {
      this.root.remove(this.atomMesh);
      disposeObject(this.atomMesh);
      this.atomMesh = null;
    }
    if (!this.atomStyles || !this.packet) return;

    const drawn: number[] = [];
    for (let i = 0; i < this.atomStyles.radii.length; i += 1) {
      if (this.atomStyles.radii[i] > 0) drawn.push(i);
    }
    if (drawn.length === 0) return;
    if (this.atomStyles.radii.length !== this.packet.structure.atoms) return;

    const material = new THREE.MeshStandardMaterial({ roughness: 0.42, metalness: 0.05 });
    const mesh = new THREE.InstancedMesh(this.atomGeometry, material, drawn.length);
    mesh.frustumCulled = false;
    const matrix = new THREE.Matrix4();
    const color = new THREE.Color();

    for (let instance = 0; instance < drawn.length; instance += 1) {
      const atom = drawn[instance];
      const radius = this.atomStyles.radii[atom];
      matrix.makeScale(radius, radius, radius);
      matrix.setPosition(this.atomStyles.positions[atom * 3], this.atomStyles.positions[atom * 3 + 1], this.atomStyles.positions[atom * 3 + 2]);
      mesh.setMatrixAt(instance, matrix);
      color.setRGB(this.atomStyles.colors[atom * 3], this.atomStyles.colors[atom * 3 + 1], this.atomStyles.colors[atom * 3 + 2]);
      mesh.setColorAt(instance, color);
    }
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    this.atomMesh = mesh;
    this.root.add(mesh);
  }

  private rebuildBonds(doc: ViewerDocument): void {
    if (this.bondMesh) {
      this.root.remove(this.bondMesh);
      disposeObject(this.bondMesh);
      this.bondMesh = null;
    }
    if (this.lineSegments) {
      this.root.remove(this.lineSegments);
      disposeObject(this.lineSegments);
      this.lineSegments = null;
    }
    if (!this.atomStyles || !this.packet) return;

    const plan = computeBondPlan(this.packet, doc.representation, this.atomStyles);
    if (plan.a.length === 0) return;

    if (plan.mode === "lines") {
      const positions = new Float32Array(plan.a.length * 6);
      const colors = new Float32Array(plan.a.length * 6);
      for (let i = 0; i < plan.a.length; i += 1) {
        const ai = plan.a[i];
        const bi = plan.b[i];
        positions.set(
          [this.atomStyles.positions[ai * 3], this.atomStyles.positions[ai * 3 + 1], this.atomStyles.positions[ai * 3 + 2],
           this.atomStyles.positions[bi * 3], this.atomStyles.positions[bi * 3 + 1], this.atomStyles.positions[bi * 3 + 2]],
          i * 6,
        );
        colors.set(
          [this.atomStyles.colors[ai * 3], this.atomStyles.colors[ai * 3 + 1], this.atomStyles.colors[ai * 3 + 2],
           this.atomStyles.colors[bi * 3], this.atomStyles.colors[bi * 3 + 1], this.atomStyles.colors[bi * 3 + 2]],
          i * 6,
        );
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
      const material = new THREE.LineBasicMaterial({ vertexColors: true });
      const lines = new THREE.LineSegments(geometry, material);
      lines.frustumCulled = false;
      this.lineSegments = lines;
      this.root.add(lines);
      return;
    }

    if (plan.mode === "cylinders") {
      const halfCount = plan.a.length * 2;
      const material = new THREE.MeshStandardMaterial({ roughness: 0.45, metalness: 0.05 });
      const mesh = new THREE.InstancedMesh(this.bondGeometry, material, halfCount);
      mesh.frustumCulled = false;
      const matrix = new THREE.Matrix4();
      const quaternion = new THREE.Quaternion();
      const direction = new THREE.Vector3();
      const midpoint = new THREE.Vector3();
      const start = new THREE.Vector3();
      const end = new THREE.Vector3();
      const color = new THREE.Color();

      for (let i = 0; i < plan.a.length; i += 1) {
        const ai = plan.a[i];
        const bi = plan.b[i];
        start.set(this.atomStyles.positions[ai * 3], this.atomStyles.positions[ai * 3 + 1], this.atomStyles.positions[ai * 3 + 2]);
        end.set(this.atomStyles.positions[bi * 3], this.atomStyles.positions[bi * 3 + 1], this.atomStyles.positions[bi * 3 + 2]);
        direction.subVectors(end, start);
        const length = direction.length();
        if (length < 1e-4) continue;
        direction.normalize();
        quaternion.setFromUnitVectors(this.up, direction);

        for (let half = 0; half < 2; half += 1) {
          const from = half === 0 ? start : midpoint;
          if (half === 0) {
            midpoint.copy(start).addScaledVector(direction, length / 2);
          }
          const to = half === 0 ? midpoint : end;
          const segment = new THREE.Vector3().subVectors(to, from);
          const segmentLength = segment.length();
          const center = new THREE.Vector3().addVectors(from, to).multiplyScalar(0.5);
          matrix.compose(
            center,
            quaternion,
            new THREE.Vector3(plan.radius, segmentLength, plan.radius),
          );
          const instance = i * 2 + half;
          mesh.setMatrixAt(instance, matrix);
          const atom = half === 0 ? ai : bi;
          color.setRGB(this.atomStyles.colors[atom * 3], this.atomStyles.colors[atom * 3 + 1], this.atomStyles.colors[atom * 3 + 2]);
          mesh.setColorAt(instance, color);
        }
      }
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      this.bondMesh = mesh;
      this.root.add(mesh);
    }
  }

  private rebuildCartoon(doc: ViewerDocument): void {
    if (this.cartoonMesh) {
      this.root.remove(this.cartoonMesh);
      disposeObject(this.cartoonMesh);
      this.cartoonMesh = null;
    }
    if (!this.packet || !this.coloring) return;
    if (doc.representation !== "cartoon") return;

    const ribbon = buildCartoon(this.packet, (residueIndex) => residueColor(this.coloring as ColoringContext, residueIndex));
    if (!ribbon) return;

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(ribbon.positions, 3));
    geometry.setAttribute("normal", new THREE.BufferAttribute(ribbon.normals, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(ribbon.colors, 3));
    geometry.setIndex(new THREE.BufferAttribute(ribbon.indices, 1));
    geometry.computeBoundingSphere();
    const material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.6, metalness: 0.02, side: THREE.DoubleSide });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.frustumCulled = false;
    this.cartoonMesh = mesh;
    this.root.add(mesh);
  }

  private rebuildBackbone(doc: ViewerDocument): void {
    if (this.backboneTrace) {
      this.root.remove(this.backboneTrace);
      disposeObject(this.backboneTrace);
      this.backboneTrace = null;
    }
    if (!this.packet || !this.coloring) return;
    if (doc.representation !== "backbone") return;

    const positions: number[] = [];
    const colors: number[] = [];
    const byChain = new Map<number, number[]>();
    for (const residue of this.packet.residues) {
      if (!residue.isAminoAcid || residue.caIndex === null) continue;
      const list = byChain.get(residue.chainIndex) ?? [];
      list.push(residue.index);
      byChain.set(residue.chainIndex, list);
    }

    for (const residueIndices of byChain.values()) {
      for (let i = 0; i < residueIndices.length - 1; i += 1) {
        const a = this.packet.residues[residueIndices[i]].caIndex as number;
        const b = this.packet.residues[residueIndices[i + 1]].caIndex as number;
        positions.push(
          this.packet.atoms.x[a], this.packet.atoms.y[a], this.packet.atoms.z[a],
          this.packet.atoms.x[b], this.packet.atoms.y[b], this.packet.atoms.z[b],
        );
        const ca = residueColor(this.coloring, residueIndices[i]);
        const cb = residueColor(this.coloring, residueIndices[i + 1]);
        colors.push(ca[0], ca[1], ca[2], cb[0], cb[1], cb[2]);
      }
    }
    if (positions.length === 0) return;

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(positions), 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(colors), 3));
    const material = new THREE.LineBasicMaterial({ vertexColors: true, linewidth: 2 });
    const trace = new THREE.LineSegments(geometry, material);
    trace.frustumCulled = false;
    this.backboneTrace = trace;
    this.root.add(trace);
  }

  private rebuildSelection(): void {
    this.clearGroup(this.selectionGroup);
    if (!this.atomStyles || this.selection.size === 0) return;
    const indices = [...this.selection].filter((i) => i >= 0 && i < this.atomStyles!.radii.length);
    if (indices.length === 0) return;

    const material = new THREE.MeshBasicMaterial({ color: 0xffd54a, transparent: true, opacity: 0.45, depthWrite: false });
    const mesh = new THREE.InstancedMesh(this.atomGeometry, material, indices.length);
    mesh.frustumCulled = false;
    const matrix = new THREE.Matrix4();
    indices.forEach((atom, instance) => {
      const radius = (this.atomStyles!.radii[atom] || 0.5) * 1.35;
      matrix.makeScale(radius, radius, radius);
      matrix.setPosition(this.atomStyles!.positions[atom * 3], this.atomStyles!.positions[atom * 3 + 1], this.atomStyles!.positions[atom * 3 + 2]);
      mesh.setMatrixAt(instance, matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    this.selectionGroup.add(mesh);
  }

  private rebuildLabels(doc: ViewerDocument): void {
    this.clearGroup(this.labelGroup);
    if (!this.packet || !doc.showLabels) return;
    const entries: LabelEntry[] = [];
    for (const residue of this.packet.residues) {
      if (residue.isWater) continue;
      if (!residue.isAminoAcid && !residue.isHetero) continue;
      const anchor = residue.caIndex ?? residue.atomStart;
      entries.push({ atomIndex: anchor, text: residue.label });
    }
    // Cap label count; hundreds of sprites would dominate the frame.
    for (const entry of entries.slice(0, 220)) {
      const atom = entry.atomIndex;
      const sprite = makeTextSprite(entry.text);
      sprite.position.set(
        this.packet.atoms.x[atom],
        this.packet.atoms.y[atom] + 0.6,
        this.packet.atoms.z[atom],
      );
      this.labelGroup.add(sprite);
    }
  }

  private rebuildMeasurements(doc: ViewerDocument): void {
    this.clearGroup(this.measurementGroup);
    if (!this.packet || doc.measurements.length === 0) return;
    const material = new THREE.LineBasicMaterial({ color: 0x4fd1c5 });
    for (const measurement of doc.measurements) {
      const points = measurement.atoms.map(
        (atom) => new THREE.Vector3(this.packet!.atoms.x[atom], this.packet!.atoms.y[atom], this.packet!.atoms.z[atom]),
      );
      if (points.length < 2) continue;
      const geometry = new THREE.BufferGeometry().setFromPoints(points);
      const line = new THREE.Line(geometry, material);
      line.frustumCulled = false;
      this.measurementGroup.add(line);
      const center = points.reduce((acc, p) => acc.add(p), new THREE.Vector3()).multiplyScalar(1 / points.length);
      const sprite = makeTextSprite(measurement.label, "#0b0f14", "#4fd1c5");
      sprite.position.copy(center);
      this.measurementGroup.add(sprite);
    }
  }

  // --- surface ------------------------------------------------------------
  setSurface(payload: SurfacePayload | null, opts: { mode: string; opacity: number }): void {
    if (this.surfaceMesh) {
      this.root.remove(this.surfaceMesh);
      disposeObject(this.surfaceMesh);
      this.surfaceMesh = null;
    }
    if (!payload) return;
    const geometry = buildSurfaceGeometry(payload);
    const color = opts.mode === "vdw" ? 0x8fb8de : 0x9ad0a3;
    const material = new THREE.MeshStandardMaterial({
      color,
      transparent: true,
      opacity: opts.opacity,
      roughness: 0.55,
      metalness: 0.0,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.frustumCulled = false;
    this.surfaceMesh = mesh;
    this.root.add(mesh);
  }

  setSurfaceOpacity(opacity: number): void {
    const material = this.surfaceMesh?.material as THREE.MeshStandardMaterial | undefined;
    if (material) material.opacity = opacity;
  }

  // --- pointer ------------------------------------------------------------
  private onPointerDown = (event: PointerEvent): void => {
    this.pointerDown = { x: event.clientX, y: event.clientY, time: performance.now() };
  };

  private onPointerUp = (event: PointerEvent): void => {
    const moved = Math.hypot(event.clientX - this.pointerDown.x, event.clientY - this.pointerDown.y);
    if (moved > 4) return; // a drag, not a click
    const hit = this.pick(event);
    this.options.onPick?.(hit, event.shiftKey || event.metaKey || event.ctrlKey);
  };

  private onPointerMove = (event: PointerEvent): void => {
    if (!this.options.onHover) return;
    this.options.onHover(this.pick(event));
  };

  private onPointerLeave = (): void => {
    this.options.onHover?.(null);
  };

  private pick(event: PointerEvent): number | null {
    if (!this.atomStyles || !this.packet) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndcX = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    const ndcY = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    const { origin, direction } = rayFromNdc(this.camera, ndcX, ndcY);
    const result = pickAtom(
      this.atomStyles.positions,
      this.atomStyles.pickRadii,
      this.atomStyles.visible,
      origin,
      direction,
      this.centerOffset,
    );
    return result ? result.index : null;
  }

  /** Convenience for tests and callers that already have a ray. */
  raycast(origin: THREE.Vector3, direction: THREE.Vector3): number | null {
    if (!this.atomStyles) return null;
    const result = pickAtom(this.atomStyles.positions, this.atomStyles.pickRadii, this.atomStyles.visible, origin, direction, this.centerOffset);
    return result ? result.index : null;
  }

  get cameraInstance(): THREE.PerspectiveCamera {
    return this.camera;
  }
}

function disposeObject(object: THREE.Object3D): void {
  const anyObject = object as unknown as { geometry?: THREE.BufferGeometry; material?: THREE.Material | THREE.Material[] };
  anyObject.geometry?.dispose();
  const material = anyObject.material;
  if (Array.isArray(material)) material.forEach((m) => m.dispose());
  else material?.dispose();
  if (object instanceof THREE.Sprite) object.material.map?.dispose();
}

function makeTextSprite(text: string, background = "#0b0f14", foreground = "#e6edf3"): THREE.Sprite {
  const canvas = document.createElement("canvas");
  const scale = 2;
  const font = 26 * scale;
  canvas.width = 512;
  canvas.height = 64 * scale;
  const context = canvas.getContext("2d");
  if (context) {
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.font = `600 ${font}px "Inter", system-ui, sans-serif`;
    const metrics = context.measureText(text);
    const width = Math.min(canvas.width, metrics.width + 24 * scale);
    context.fillStyle = background;
    context.globalAlpha = 0.82;
    context.fillRect(0, 0, width, canvas.height);
    context.globalAlpha = 1;
    context.fillStyle = foreground;
    context.textBaseline = "middle";
    context.fillText(text, 12 * scale, canvas.height / 2);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false });
  const sprite = new THREE.Sprite(material);
  const worldHeight = 1.6;
  sprite.scale.set((canvas.width / canvas.height) * worldHeight, worldHeight, 1);
  return sprite;
}
