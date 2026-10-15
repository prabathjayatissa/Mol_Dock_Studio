# Troubleshooting

MolDock Studio prefers to *tell you the truth* rather than fail silently. Start
here: **`GET /api/health`** (or the app's *Workflow* panel) reports exactly what
this machine can do, with a `remediation` string when something is missing.

```bash
cd backend && uv run python -m app.cli capabilities
```

## The backend will not start

**Symptom:** `uvicorn: command not found`, or `ModuleNotFoundError: app`.

- Run from `backend/` (the app package lives there), or use `make dev-backend`.
- Create the environment first: `cd backend && uv sync --extra dev`. This reads
  the pinned `uv.lock`, so the versions match the dependency matrix.
- If a dependency failed to install, run `uv sync --extra dev --refresh` and read
  the resolver output — do not hand-edit versions.

**Symptom:** `sqlite3.OperationalError: unable to open database file`.

- The data directory is missing or read-only. `MOLDOCK_DATA_DIR` (default
  `./data`) must be writable. `mkdir -p data` from `backend/`, or point the
  variable somewhere writable.

## "Docking is unavailable" — and that is correct

AutoDock Vina publishes **Linux x86-64 wheels only**. On macOS (Intel *or*
Apple Silicon) the native backend cannot install it, so `/api/health` reports
`vina` as `unavailable` with a remediation string, and the UI disables docking
rather than pretending.

Reach Vina in one of three ways:

1. **The container** (recommended): `MOLDOCK_PLATFORM=linux/amd64
   MOLDOCK_INSTALL_VINA=1 docker compose up`. On Apple Silicon this runs the
   image under Rosetta.
2. **A native binary**: install Vina yourself and set `MOLDOCK_VINA_BINARY`
   (and, for Meeko, ensure `meeko` is importable).
3. **Build from source** — see the Vina repository; then set the same variable.

Everything except docking (parsing, descriptors, surfaces, the viewer) runs
natively everywhere.

## Everything is *extremely* slow (minutes per import)

This is almost always the **filesystem, not the program**. The tell-tale sign: a
trivial import burns minutes of wall-clock at ≈0 % CPU, e.g.

```bash
cd backend
time .venv/bin/python -c "import fastapi"
# real  3m36s   user 0m0.2s   <-- wall time, no CPU: it is blocked on I/O
```

The unmistakable signature is **wall-clock time with almost no CPU time**. Compare:

```bash
time .venv/bin/python -c "import fastapi"
# real 3m36s   user 0m0.2s   sys 0m0.1s   <-- 3.5 minutes of waiting, 0.3 s of work
```

A blocking `uvicorn app.main:app` can show the same thing at the process level —
the server is "Waiting for application startup" for many minutes while
`ps -o time -p <pid>` shows only a couple of seconds of CPU. It is not deadlocked;
it is queued behind the filesystem.

Common causes on macOS:

- **The project lives in iCloud Drive** (`~/Documents` or `~/Desktop` with
  *Desktop & Documents Folders* syncing on). iCloud serves those paths through a
  File Provider, so *every* `open()` is an RPC to a system daemon — and a Python
  environment is tens of thousands of files. The giveaway is a
  `com.apple.CloudDocs.iCloudDriveFileProvider` process, plus `fileproviderd`,
  `bird` and `cloudd` high in `ps -Ao %cpu,comm -r`.
- **Spotlight is indexing** a fresh `node_modules`/`.venv`
  (`mds_stores` pegged). It subsides, but not quickly.

Fixes, best first:

1. **Get the Python environment off the synced folder.** This is by far the
   biggest win and it is not necessary to move the whole repository — only the
   venv and the process that loads it. Because `uv`'s cache lives in
   `~/.cache/uv` (i.e. *not* under iCloud), a venv can be rebuilt at a local path
   in seconds:

   ```bash
   RUN=~/src/moldock-run                      # any path outside iCloud
   mkdir -p "$RUN"
   rsync -a --exclude 'node_modules' --exclude '.venv' \
         --exclude '/data' --exclude 'dist' --exclude '.git' \
         /path/to/MD_DAB/ "$RUN/"              # source only; venv excluded
   cd "$RUN/backend" && uv sync --extra dev    # fast: hardlinks from the uv cache
   .venv/bin/uvicorn app.main:app --port 8000  # starts in seconds
   ```

   The frontend can keep running from the original checkout (Vite proxies `/api`
   to `127.0.0.1:8000`, so the two halves may live anywhere). Moving the whole
   repository out of iCloud — e.g. to `~/src/moldock-studio` — is equivalent and
   simpler if you can spare the disk.
2. Add a `.metadata_never_index` marker so Spotlight skips the trees:

   ```bash
   touch .metadata_never_index frontend/.metadata_never_index backend/.metadata_never_index
   ```

   (Put the marker *inside* `node_modules` and `.venv` too — those are the trees
   Spotlight actually chokes on.)
3. Reduce BLAS thread thrash on a loaded box:
   `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1`.
4. Let it finish: `mdutil -s /` shows indexing state (`sudo` required to disable).

None of these change what the program *does* — they change how long the operating
system makes it wait. Note also that a Vite dev server may bind only to IPv6
(`[::1]:5173`), so `curl http://127.0.0.1:5173` can be refused while
`curl http://localhost:5173` succeeds. Use `localhost`, or set
`server.host` in `vite.config.ts`.

## The frontend type-check is killed ("Killed: 9")

`tsc` (TypeScript 7, a native binary) can be OOM-killed on a machine under memory
pressure — often the same iCloud/Spotlight situation above.

- Re-run once the box is calm: `cd frontend && npm run typecheck`.
- `npm run build` runs only the bundler (`vite build`) and does **not** type-check,
  so it can succeed even when types are broken; treat it as a bundling check.
  Use `npm run build:check` (type-check **then** build) when you want both, and
  `npm test` for the unit suite.
- `NODE_OPTIONS=--max-old-space-size=4096 npm run typecheck` helps when the
  pressure is ordinary, not when the OS is thrashing.

## Upload rejected

| Response | Meaning | Fix |
| -------- | ------- | --- |
| `413 upload_rejected` | File exceeds `MOLDOCK_MAX_UPLOAD_MB` (default 200) | Raise the limit, or split the file |
| `415 unsupported_format` | The format could not be detected | Export as PDB/mmCIF/SDF/MOL/MOL2/PDBQT/XYZ |
| `422 structure_parse_error` | Format recognised, content malformed | Check the file; the message names the problem |

Uploads are validated by content, not by extension, and are written to a
per-request temporary directory that is cleaned up even on failure.

## A structure imports but looks wrong

Open the *Properties* panel — **import warnings** are shown there, and the same
list is on the import response. Common, *expected* messages:

- `secondary-structure-inferred` — no `HELIX`/`SHEET` records were present, so a
  geometric Cα heuristic was used. This is **not** DSSP; helices render as coils.
- `bond-perception-geometry` — bonds were inferred from interatomic distances
  (PDB/mmCIF/PDBQT/XYZ), not read from a file.
- `large-structure-coarsened` — the surface grid was coarsened to stay within the
  memory budget; the reported `spacingUsed` reflects it. The mesh is *coarser*,
  not truncated.

If a *hydrogen* or a *water* seems to be missing, check the toolbar toggles:
hydrogens and waters are **hidden** by default and never removed from the data.

## Surface generation is slow or fails

- Generation is CPU-bound and cached on disk (keyed by structure hash + mode +
  probe radius + spacing + hydrogens). The first request is slow; repeats are
  instant.
- Very large structures should use the **job** variant
  (`POST /api/structures/{id}/surface/jobs`), which returns `202` and streams
  progress.
- "Surface generation unavailable" means `scipy`/`scikit-image` are missing —
  `uv sync --extra dev` and re-check `/api/health`.

## A job never leaves "queued"

- Check the worker limit: `MOLDOCK_MAX_CONCURRENT_JOBS` (default small). Queued
  jobs wait behind running ones.
- Look at the job log: `GET /api/jobs/{id}/log`. Child stdout/stderr is captured.
- The dispatcher polls roughly every 0.4 s; on a very loaded machine that can
  stretch. Cancelling a job that already finished returns `409` — that is
  expected, not an error to retry.

## Browser cannot reach the API

- In development the Vite server proxies `/api` to `http://127.0.0.1:8000`, so
  the browser talks to the same origin and CORS is not involved.
- If you run the frontend and backend on *different* origins, add the frontend
  origin to `MOLDOCK_CORS_ORIGINS` (comma-separated) and restart the backend.

## Resetting everything

```bash
# Backend state (projects, artefacts, caches, SQLite files)
cd backend && rm -rf data/

# Re-fetch the reference structures after a reset
uv run python -m app.cli fetch-test-data
```

Nothing outside `MOLDOCK_DATA_DIR` is written, so this is a complete reset.
