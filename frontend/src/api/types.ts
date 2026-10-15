/**
 * TypeScript mirrors of the backend wire models.
 *
 * These are hand-written to match `app/schemas/*.py` exactly. They are the only
 * place the frontend knows about the server's field names; everything else works
 * with these types. Camel-case keys mirror the Pydantic models.
 */

export type CapabilityStatus = "available" | "unavailable" | "not_implemented";

export interface Capability {
  key: string;
  label: string;
  category: string;
  status: CapabilityStatus;
  version?: string;
  location?: string;
  mode?: string;
  remediation?: string;
  detail?: string;
}

export interface Phase {
  id: string;
  name: string;
  status: "implemented" | "in_progress" | "pending";
  summary: string;
  pending: string[];
}

export interface Health {
  status: string;
  application: string;
  version: string;
  environment: string;
  scientificBackendMode: string;
  database: string;
  dataDirectory: string;
  capabilities: Capability[];
  phases: Phase[];
  handlers: Record<string, string>;
  limits: Record<string, number>;
}

export interface ProjectCounts {
  structures: number;
  ligands: number;
  jobs: number;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  settings: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  counts: ProjectCounts | null;
}

export interface ProjectList {
  items: Project[];
  total: number;
}

export interface StructureList {
  items: StructureSummary[];
  total: number;
}

export interface Warning {
  code: string;
  message: string;
  severity: string;
  count?: number | null;
  detail?: Record<string, unknown> | null;
}

export interface StructureSummary {
  id: string;
  projectId: string;
  name: string;
  kind: string;
  format: string;
  source: string;
  fileSha256: string;
  sizeBytes: number;
  atomsCount: number;
  residuesCount: number;
  chainsCount: number;
  createdAt: string;
}

export interface StructureDetail extends StructureSummary {
  warnings: Warning[];
  properties: Record<string, unknown>;
  provenance: Record<string, unknown>;
  chains: ChainInfo[];
  ligand: LigandSummary | null;
}

export interface ChainInfo {
  index: number;
  id: string;
  kind: string;
  residueCount: number;
  atomCount: number;
  sequence: string;
}

export interface LigandSummary {
  id: string;
  name: string;
  smiles: string | null;
  formula: string | null;
  molecularWeight: number | null;
}

export interface Ligand {
  id: string;
  projectId: string;
  structureId: string;
  name: string;
  smiles: string | null;
  inchiKey: string | null;
  formula: string | null;
  molecularWeight: number | null;
  logp: number | null;
  tpsa: number | null;
  hBondDonors: number | null;
  hBondAcceptors: number | null;
  rotatableBonds: number | null;
  formalCharge: number | null;
  heavyAtoms: number | null;
  aromaticRings: number | null;
  stereocenters: number | null;
  descriptorSource: string;
  valid: boolean;
  validationMessages: unknown[];
  createdAt: string;
}

export interface ImportResult {
  structure: StructureDetail;
  warnings: Warning[];
  statistics: Record<string, number | string | Record<string, number>>;
  ligand: LigandSummary | null;
  packetUrl: string;
  provenance: Record<string, unknown>;
}

/** Column-oriented atom arrays. Every array has `structure.atoms` entries. */
export interface PacketAtoms {
  x: number[];
  y: number[];
  z: number[];
  element: string[];
  radius: number[];
  covalentRadius: number[];
  color: string[];
  residueIndex: number[];
  chainIndex: number[];
  serial: number[];
  formalCharge: number[];
  partialCharge: (number | null)[];
  bfactor: number[];
  occupancy: number[];
  altloc: string[];
  isHetero: boolean[];
  isWater: boolean[];
  isBackbone: boolean[];
  name: string[];
  autodockType: (string | null)[];
  bondCount: number[];
}

export interface PacketBonds {
  a: number[];
  b: number[];
  order: number[];
  aromatic: boolean[];
  source: string[];
}

export interface PacketResidue {
  index: number;
  name: string;
  seq: number;
  insertionCode: string;
  chainIndex: number;
  chainId: string;
  label: string;
  ss: "H" | "E" | "C";
  isHetero: boolean;
  isWater: boolean;
  isAminoAcid: boolean;
  isNucleic: boolean;
  oneLetter: string;
  residueType: string;
  hydropathy: number;
  atomStart: number;
  atomCount: number;
  caIndex: number | null;
  nIndex: number | null;
  cIndex: number | null;
  oIndex: number | null;
  cbIndex: number | null;
  title: string;
  smiles: string | null;
}

export interface PacketChain {
  index: number;
  id: string;
  kind: string;
  residueStart: number;
  residueCount: number;
  label: string;
}

export interface StructurePacket {
  packetVersion: number;
  structure: {
    id: string;
    name: string;
    kind: string;
    format: string;
    source: string;
    atoms: number;
    residues: number;
    chains: number;
    bonds: number;
    hasCoordinates: boolean;
    centroid: [number, number, number];
    bounds: { min: [number, number, number]; max: [number, number, number] };
    radius: number;
  };
  chains: PacketChain[];
  residues: PacketResidue[];
  atoms: PacketAtoms;
  bonds: PacketBonds;
  sequences: Record<string, string>;
  secondaryStructure: string;
  statistics: Record<string, unknown>;
  warnings: Warning[];
  metadata: Record<string, unknown>;
  properties: Record<string, unknown>;
  provenance: Record<string, unknown>;
}

export interface SurfaceStats {
  mode: string;
  probeRadius: number;
  requestedSpacing: number | null;
  spacingUsed: number;
  vertices: number;
  triangles: number;
  area: number;
  volume: number;
  atomsUsed: number;
  gridShape: number[];
  warnings: string[];
  cached?: boolean | null;
  computeSeconds?: number | null;
  cachePath?: string | null;
}

export interface SurfacePayload {
  structureId: string;
  encoding: string;
  vertexCount: number;
  triangleCount: number;
  positions: string;
  normals: string;
  indices: string;
  stats: SurfaceStats;
}

export type JobState = "queued" | "preparing" | "running" | "completed" | "failed" | "cancelled";

export interface Job {
  id: string;
  projectId: string | null;
  kind: string;
  state: JobState;
  progress: number;
  message: string;
  params: Record<string, unknown>;
  result: Record<string, unknown>;
  error: Record<string, unknown>;
  logPath: string | null;
  cancelRequested: boolean;
  pid: number | null;
  queuedAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  createdAt: string;
  provenance: Record<string, unknown>;
}

export interface JobList {
  items: Job[];
  total: number;
  running: number;
}

export interface JobLog {
  jobId: string;
  available: boolean;
  text: string;
  truncated: boolean;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  detail?: Record<string, unknown>;
  remediation?: string;
}
