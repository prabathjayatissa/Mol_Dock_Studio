# HTTP API

Base URL: `/api`. Interactive, always-current docs are served by FastAPI at
`/docs` (Swagger UI) and `/redoc`. This page is the human-readable companion.

All responses are JSON unless noted. Field names are **camelCase** on the wire.
The default local base is <http://127.0.0.1:8000>.

## Errors

Every failure uses one envelope, with a stable machine-readable `code`:

```json
{
  "error": {
    "code": "validation_failure",
    "message": "The upload is not a recognised structure format.",
    "detail": { "detected": "unknown" },
    "remediation": "Export as PDB, mmCIF, SDF, MOL, MOL2, PDBQT or XYZ."
  }
}
```

| Code | HTTP | Meaning |
| ---- | ---- | ------- |
| `not_found` | 404 | Referenced project/structure/ligand/job does not exist |
| `conflict` | 409 | Illegal state transition (e.g. cancelling a finished job) |
| `validation_failure` | 422 | Bad request body/params, or a path that escapes its root |
| `unsupported_format` | 415 | The upload format could not be detected or is not supported |
| `structure_parse_error` | 422 | The format was recognised but the content is malformed |
| `upload_rejected` | 413 | Upload exceeds `MOLDOCK_MAX_UPLOAD_MB` |
| `job_timeout` | — | A job exceeded `MOLDOCK_JOB_TIMEOUT_SECONDS` |

---

## System

### `GET /api/health`

Capability report for *this* machine. Never fabricates availability.

```json
{
  "status": "ok",
  "version": "0.1.0",
  "environment": "development",
  "scientificBackendMode": "native",
  "database": "sqlite",
  "dataDirectory": "/abs/path/data",
  "capabilities": [
    { "key": "rdkit", "label": "RDKit", "category": "chemistry",
      "status": "available", "version": "2026.09.1" },
    { "key": "vina", "label": "AutoDock Vina", "category": "docking",
      "status": "unavailable",
      "remediation": "Vina publishes Linux x86_64 wheels only; run the amd64 container or set MOLDOCK_VINA_BINARY." }
  ],
  "phases": [ { "id": "phase-1", "name": "Molecular viewer", "status": "implemented",
               "summary": "…", "pending": ["…"] } ],
  "handlers": { "generate_surface": "app.services.jobs.handlers:generate_surface" },
  "limits": { "maxUploadBytes": 209715200, "maxAtoms": 500000 }
}
```

`status` is one of `available`, `unavailable`, `not_implemented`. Missing optional
fields are **omitted** (e.g. an available tool has no `remediation`), so the UI
shows a remediation only when there is something to fix.

---

## Projects

| Method | Path | Body / query | Returns |
| ------ | ---- | ------------ | ------- |
| `POST` | `/api/projects` | `{name, description?, settings?}` | `201` `Project` (counts = `null`) |
| `GET` | `/api/projects` | `?limit&offset` | `{items, total}` |
| `GET` | `/api/projects/{id}` | — | `Project` (with counts) |
| `PATCH` | `/api/projects/{id}` | `{name?, description?, settings?}` | `Project` |
| `DELETE` | `/api/projects/{id}` | — | `204` |
| `GET` | `/api/projects/{id}/export` | — | `ProjectExport` (a `.moldock.zip`) |

`Project`:

```json
{ "id": "prj_…", "name": "Trypsin study", "description": "",
  "settings": {}, "createdAt": "…", "updatedAt": "…",
  "counts": { "structures": 2, "ligands": 1, "jobs": 0 } }
```

The project export writes a portable ZIP (`manifest.json` + every stored
artefact) and records it in the provenance log.

---

## Structures

| Method | Path | Body / query | Returns |
| ------ | ---- | ------------ | ------- |
| `POST` | `/api/structures/import` | multipart: `file`, `projectId`, `name?`, `kind?`, `format?` | `201` `ImportResult` |
| `POST` | `/api/structures/fetch-rcsb` | `{projectId, entryId, format?, name?}` | `201` `ImportResult` |
| `GET` | `/api/structures` | `?projectId&kind` | `{items, total}` |
| `GET` | `/api/structures/{id}` | — | `StructureDetail` |
| `GET` | `/api/structures/{id}/packet` | — | `StructurePacket` |
| `GET` | `/api/structures/{id}/surface` | `?mode=vdw\|sas&probeRadius&gridSpacing&includeHydrogens&useCache` | `Surface` |
| `POST` | `/api/structures/{id}/surface/jobs` | `{mode, probeRadius?, gridSpacing?, includeHydrogens?, useCache?}` | `202` `Job` |
| `GET` | `/api/structures/{id}/export` | `?format=pdb\|mmcif\|sdf\|mol\|mol2\|xyz` | `text/plain` (attachment) |
| `DELETE` | `/api/structures/{id}` | — | `204` |

`ImportResult`:

```json
{ "structure": { "id": "str_…", "kind": "complex", "format": "pdb",
                 "atomsCount": 1701, "residuesCount": 287, "warnings": [ … ] },
  "warnings": [ … ],
  "statistics": { "waters": 62, "hetero": { "BEN": 1, "CA": 1 }, … },
  "ligand": { "id": "lig_…", "smiles": "N=C(N)c1ccccc1", "formula": "C7H8N2" },
  "packetUrl": "/api/structures/str_…/packet",
  "provenance": { "tool": "gemmi", "toolVersion": "0.7.5", … } }
```

### The structure packet

`GET /api/structures/{id}/packet` returns a **column-oriented** payload — the
viewer's transport format. Nothing here is per-atom objects:

```json
{ "packetVersion": 1,
  "structure": { "atoms": 660, "residues": 134, "chains": 1, "bonds": 649,
                 "centroid": [x,y,z], "radius": 12.3, "bounds": {…} },
  "chains":   [ { "index": 0, "id": "A", "kind": "polymer", "residueStart": 0, "residueCount": 76 } ],
  "residues": [ { "index": 0, "name": "MET", "seq": 1, "ss": "C", "caIndex": 1, "atomStart": 0, "atomCount": 8, … } ],
  "atoms": { "x": [...], "y": [...], "z": [...], "element": [...],
             "radius": [...], "color": [...], "residueIndex": [...],
             "chainIndex": [...], "bfactor": [...], "isWater": [...], … },
  "bonds": { "a": [...], "b": [...], "order": [...], "source": ["file"|"geometry", …] },
  "secondaryStructure": "file-records",
  "warnings": [ … ], "metadata": { … }, "properties": { … }, "provenance": { … } }
```

Atoms are grouped by (chain, residue) so each residue is a contiguous slice.
`packetVersion` lets the client reject a mismatch.

### Surfaces

`GET …/surface` computes synchronously and caches the result on disk, keyed by a
hash of (structure sha256, mode, probe radius, spacing, hydrogens). For very
large structures use the background variant, which returns `202` with a `Job`.

```json
{ "structureId": "str_…", "encoding": "base64",
  "vertexCount": 12345, "triangleCount": 24680,
  "positions": "<base64 float32 LE>", "normals": "<base64 float32 LE>",
  "indices": "<base64 uint32 LE>",
  "stats": { "mode": "sas", "probeRadius": 1.4, "spacingUsed": 0.4,
             "vertices": 12345, "triangles": 24680, "area": 5123.4,
             "volume": 15678.9, "atomsUsed": 660, "gridShape": [..],
             "warnings": [] } }
```

---

## Ligands

| Method | Path | Body | Returns |
| ------ | ---- | ---- | ------- |
| `POST` | `/api/ligands/import` | multipart: `file`, `projectId`, `name?` | `201` `ImportResult` |
| `POST` | `/api/ligands/from-smiles` | `{projectId, smiles, name?, embed3d?, seed?}` | `201` `ImportResult` |
| `GET` | `/api/ligands` | `?projectId` | `{items, total}` |
| `GET` | `/api/ligands/{id}` | — | `Ligand` |

`from-smiles` builds a 3D conformer with **RDKit ETKDGv3 + MMFF94** (fixed seed),
stores it as a real SDF file, and recomputes descriptors from that file, so the
record and the coordinates can never disagree. `Ligand` carries computed
descriptors (`logp`, `tpsa`, `hBondDonors`, …, `descriptorSource: "computed"`)
and `validationMessages`. These are **calculated** values, not measurements.

---

## Jobs

| Method | Path | Body | Returns |
| ------ | ---- | ---- | ------- |
| `GET` | `/api/jobs` | `?projectId&kind&state&limit` | `{items, total, running}` |
| `GET` | `/api/jobs/handlers` | — | registered job kinds |
| `POST` | `/api/jobs/self-test` | `{projectId?, steps?, secondsPerStep?}` | `202` `Job` |
| `GET` | `/api/jobs/{id}` | — | `Job` |
| `POST` | `/api/jobs/{id}/cancel` | — | `{jobId, state, message}` |
| `GET` | `/api/jobs/{id}/log` | — | `{jobId, available, text, truncated}` |

`Job` states: `queued → preparing → running → completed | failed | cancelled`.
`progress` is `0..1`. Cancelling a job that has already finished returns `409`.

The only job kinds registered in Phase 1 are `generate_surface` (real work) and
`pipeline_self_test` (a diagnostic that exercises the queue, worker, progress
and cancellation). **There are no docking job kinds** — docking is Phase 3 and is
advertised as `not_implemented`.

---

## Using it from the shell

```bash
curl -s localhost:8000/api/health | jq '.capabilities[] | {key, status}'

PID=$(curl -s -XPOST localhost:8000/api/projects \
        -H 'content-type: application/json' \
        -d '{"name":"Demo"}' | jq -r .id)

curl -s -XPOST localhost:8000/api/structures/fetch-rcsb \
        -H 'content-type: application/json' \
        -d "{\"projectId\":\"$PID\",\"entryId\":\"1UBQ\"}" | jq '{name: .structure.name, atoms: .structure.atomsCount}'
```
