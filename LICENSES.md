# Licensing and data provenance

MolDock Studio is an original work released under the MIT licence (see
[`LICENSE`](LICENSE)). It does **not** incorporate code, branding or UI assets
from any other molecular-modelling product.

## Bundled sample data (`backend/app/data/`)

| File | Origin | Licence |
| ---- | ------ | ------- |
| `1UBQ.pdb` | RCSB PDB entry [1UBQ](https://www.rcsb.org/structure/1UBQ) | CC0 1.0 (public domain) |
| `3PTB.pdb` | RCSB PDB entry [3PTB](https://www.rcsb.org/structure/3PTB) | CC0 1.0 (public domain) |
| `1STP.pdb` | RCSB PDB entry [1STP](https://www.rcsb.org/structure/1STP) | CC0 1.0 (public domain) |
| `benzamidine.sdf` | Generated locally with RDKit from `NC(=N)c1ccccc1` | None (generated) |
| `aspirin.sdf` | Generated locally with RDKit from `CC(=O)Oc1ccccc1C(=O)O` | None (generated) |
| `ethanol.sdf` | Generated locally with RDKit from `CCO` | None (generated) |
| `caffeine.sdf` | Generated locally with RDKit from `Cn1cnc2c1c(=O)n(C)c(=O)n2C` | None (generated) |
| `imatinib.sdf` | Generated locally with RDKit from its public SMILES | None (generated) |

The PDB entries are deposited by their authors and released by the
wwPDB/RCSB PDB into the public domain under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).
The ligand files contain no copyrighted coordinates: they are 3D conformers
generated deterministically (RDKit ETKDGv3, fixed random seed) from SMILES
strings that are themselves public chemical facts.

`python -m app.cli fetch-test-data` reproduces all of the above; the committed
files are the exact bytes that command produces. Committed sample data is
registered in [`.gitignore`](.gitignore) so it is never confused with the
runtime data directory (`/data/` or `/backend/data/`).

## Runtime-generated content

Everything MolDock Studio writes at runtime — project directories, cached
surfaces, prepared receptors/ligands, docking poses and reports — is derived
from the user's own inputs and is **not** part of this repository. Nothing a
user imports is redistributed.

## Third-party software

Dependency licences are listed in
[`docs/dependency-matrix.md`](docs/dependency-matrix.md). Notable ones:

- **RDKit** (BSD 3-Clause) — cheminformatics, descriptors, format conversion.
- **gemmi** (MPL-2.0) — PDB/mmCIF parsing.
- **SciPy / NumPy / scikit-image** (BSD 3-Clause) — distance fields and
  isosurface extraction.
- **AutoDock Vina** (Apache-2.0) — docking (Phase 3; x86_64 wheels only).
- **Meeko** (Apache-2.0) — PDBQT preparation (Phase 2).
