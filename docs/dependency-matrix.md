# Dependency compatibility matrix

The backend is a Python 3.12 application. **`backend/uv.lock` is the source of
truth** for exact resolved versions; this page records what was actually tested
and the platform constraints that drove the architecture.

Every version below was resolved into a single environment on macOS 14
(arm64) with Python **3.12.13** and verified by
`python scripts/preflight_checks.py` plus the pytest suite.

## Runtime — always installed

| Package | Tested version | Constraint in `pyproject.toml` | Licence | Purpose |
| ------- | -------------- | ------------------------------ | ------- | ------- |
| Python | 3.12.13 | `>=3.12,<3.13` | PSF | Interpreter |
| fastapi | 0.143.1 | `>=0.115,<1` | MIT | HTTP API |
| uvicorn[standard] | 0.54.0 | `>=0.30,<1` | BSD-3 | ASGI server |
| pydantic | 2.14.1 | `>=2.9,<3` | MIT | Validation / schemas |
| pydantic-settings | 2.12.x | `>=2.5,<3` | MIT | Env-driven config |
| SQLAlchemy | 2.1.4 | `>=2.0.35,<3` | MIT | ORM / persistence |
| Alembic | 1.14.x | `>=1.13,<2` | MIT | Migrations (Postgres) |
| python-multipart | 0.0.20 | `>=0.0.12` | Apache-2.0 | Upload parsing |
| httpx | 0.28.x | `>=0.27,<1` | BSD-3 | RCSB fetch, tests |
| NumPy | 2.5.4 | `>=1.26,<3` | BSD-3 | Geometry, math |
| SciPy | 1.18.1 | `>=1.13,<2` | BSD-3 | cKDTree, EDT |
| scikit-image | 0.26.0 | `>=0.24,<1` | BSD-3 | Marching-cubes isosurfaces |
| gemmi | 0.7.5 | `>=0.6.7` | MPL-2.0 | PDB/mmCIF parsing |
| RDKit | 2026.09.1 | `>=2024.9` | BSD-3 | Ligands, SMILES, descriptors |
| Biopython | 1.88 | `>=1.84` | Biopython | Sequence utilities |
| pandas | 2.3.3 | `>=2.2,<3` | BSD-3 | Tabular export |

## Optional extras

| Extra | Package | Tested? | Note |
| ----- | ------- | ------- | ---- |
| `docking` | meeko `>=0.6` | not on macOS arm64 | Used in Docker (amd64) / Phase 2 |
| `docking` | vina `>=1.2.7` | **no native wheel** | manylinux/musllinux **x86_64 only** |
| `protein-prep` | pdb2pqr `>=3.6` | not installed | Phase 2 protonation |
| `dev` | pytest 9.1.1, pytest-cov, ruff 0.17.0 | yes | tests / lint |

## Why the platform split exists

AutoDock Vina 1.2.7 publishes **only** `manylinux`/`musllinux` **x86_64**
wheels on PyPI. There is no macOS arm64 wheel and no pure-Python fallback, so
`pip install vina` cannot succeed on Apple Silicon. This single fact drives the
whole deployment story:

| Configuration | Command | Docking | Notes |
| ------------- | ------- | ------- | ----- |
| Native arm64 (this machine) | `make backend-setup` | no | RDKit, gemmi, SciPy, skimage all have arm64 wheels — everything except Vina/Meeko works. |
| Docker arm64 | `docker compose up --build` | no | `linux/arm64`; identical capability set to native. |
| Docker amd64 | `MOLDOCK_PLATFORM=linux/amd64 MOLDOCK_INSTALL_VINA=1 docker compose up --build` | **yes** | Rosetta emulation on Apple Silicon; slower, full stack. |
| Native + external Vina | `MOLDOCK_VINA_BINARY=/path/to/vina` | **yes** | Backend shells out to a Vina built from source. |

`/api/health` reports the real answer per machine; nothing is assumed.

## Node / frontend toolchain

The Phase 1 viewer is a Vite project. See `frontend/package.json` for the exact
pins; the resolved versions at the time of writing are:

| Package | Resolved version | Purpose |
| ------- | ---------------- | ------- |
| node | 26.x | JavaScript runtime |
| react / react-dom | 19.3 | UI |
| three | 0.186 | Original WebGL viewer engine |
| zustand | 5.0 | Client state |
| vite | 8.3 | Dev server and bundler |
| typescript | 7.0 | Type checking (native compiler) |
| tailwindcss / @tailwindcss/vite | 4.3 | Styling |
| vitest | 5.0 | Unit tests |
| @playwright/test | ^1 | End-to-end acceptance test (installed on demand) |

All are pure JavaScript/native and platform-independent.

## Reproducing the environment

```bash
cd backend
uv sync --extra dev          # resolves and installs from uv.lock
uv run python scripts/preflight_checks.py   # ~1 min: parses sample data, checks physics
uv run pytest -q             # full suite
uv run python -m app.cli capabilities       # what this machine can run
```

To refresh the lock file after editing `pyproject.toml`:

```bash
cd backend && uv lock && uv sync --extra dev
```
