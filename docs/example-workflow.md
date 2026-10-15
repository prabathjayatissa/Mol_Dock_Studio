# Example workflow — a scripted tour

This is the command-line companion to the *five-minute tour* in the README. It
exercises Phase 1 end to end against a running backend. Every value it prints was
observed on a real run; nothing here is illustrative fiction.

Start the backend first:

```bash
cd backend
uv run uvicorn app.main:app --port 8000
```

Then, in another shell, set a base URL and walk the workflow.

```bash
API=http://127.0.0.1:8000/api
```

## 0. What can this machine actually do?

```bash
curl -s $API/health | jq '{mode: .scientificBackendMode,
                            available: [.capabilities[] | select(.status=="available") | .key],
                            missing:   [.capabilities[] | select(.status!="available") | .key]}'
```

Typical on Apple Silicon (native): `rdkit`, `gemmi`, `numpy`, `scipy`,
`scikit-image` available; `vina`, `meeko`, `openbabel` missing with a
`remediation` string. On the `linux/amd64` container, `vina` and `meeko` are
present too.

## 1. Create a project

```bash
PROJECT=$(curl -s -XPOST $API/projects \
            -H 'content-type: application/json' \
            -d '{"name":"Trypsin study","description":"3PTB redocking dry-run"}' \
          | jq -r .id)
echo "project = $PROJECT"
```

## 2. Fetch a real protein (ubiquitin) from the RCSB

```bash
UBQ=$(curl -s -XPOST $API/structures/fetch-rcsb \
        -H 'content-type: application/json' \
        -d "{\"projectId\":\"$PROJECT\",\"entryId\":\"1UBQ\"}")
echo "$UBQ" | jq '{name: .structure.name, atoms: .structure.atomsCount,
                    residues: .structure.residuesCount, kind: .structure.kind}'
```

Expected: **660 atoms, 134 residues** (76 amino acids + 58 waters), `kind` =
`protein`. The statistics block also reports `waters: 58`.

## 3. Fetch a protein–ligand complex (β-trypsin + benzamidine)

```bash
PTB=$(curl -s -XPOST $API/structures/fetch-rcsb \
        -H 'content-type: application/json' \
        -d "{\"projectId\":\"$PROJECT\",\"entryId\":\"3PTB\"}")
echo "$PTB" | jq '{atoms: .structure.atomsCount, residues: .structure.residuesCount,
                    waters: .statistics.waters, hetero: .statistics.hetero,
                    ligand: .ligand.smiles}'
STRUCTURE=$(echo "$PTB" | jq -r .structure.id)
```

Expected: **1701 atoms, 287 residues, 62 waters**, hetero `{CA: 1, BEN: 1}`, and
a detected benzamidine ligand with SMILES `N=C(N)c1ccccc1`.

> **No silent data loss.** 3PTB is stored as a **complex**; the waters, the
> calcium ion and the benzamidine are all kept. The UI lets you *hide* waters,
> never delete them.

## 4. Look at the viewer packet

```bash
curl -s $API/structures/$STRUCTURE/packet | jq '{
  packetVersion, atoms: .structure.atoms, bonds: .structure.bonds,
  chains: (.chains | length), waters: [.atoms.isWater[]] | add,
  ss: .secondaryStructure, warnings: (.warnings | length),
  bondSources: (.bonds.source | group_by(.) | map({(.[0]): length}) | add)
}'
```

Expected: `packetVersion: 1`, `atoms: 1701`, `chains: 1`, `waters: null`
(column arrays omit water flags you did not ask for) — the point is that the
numbers match what the file said. Bond sources are `{file: 12, geometry: 1669}`:
the twelve file-declared bonds (peptide + disulfides) are trusted, everything
else is perceived from geometry.

## 5. Compute a surface

Van der Waals (fast, exact union of spheres):

```bash
curl -s "$API/structures/$STRUCTURE/surface?mode=vdw" | jq '.stats |
  {mode, vertices, triangles, area: (.area|round), volume: (.volume|round),
   spacing: .spacingUsed, warnings: (.warnings|length)}'
```

Solvent-accessible (Richards probe, ~1.4 Å):

```bash
curl -s "$API/structures/$STRUCTURE/surface?mode=sas&probeRadius=1.4" | jq '.stats |
  {mode, vertices, triangles, area: (.area|round), volume: (.volume|round)}'
```

The SAS surface is larger than the vdW surface (the probe rolls over the atoms),
which is the sanity check that the two modes are doing different things. The
payload is base64 little-endian float32 positions/normals plus uint32 indices —
about a quarter the size of the equivalent JSON arrays.

> The **Connolly solvent-excluded surface (SES) is not implemented.** Phase 1
> ships `vdw` and `sas` only, and says so.

## 6. Build a ligand from SMILES

```bash
curl -s -XPOST $API/ligands/from-smiles \
  -H 'content-type: application/json' \
  -d "{\"projectId\":\"$PROJECT\",\"smiles\":\"CC(=O)Oc1ccccc1C(=O)O\",\"name\":\"Aspirin\"}" \
| jq '.ligand | {name, formula, molecularWeight, logp, hBondDonors, hBondAcceptors,
                  rotatableBonds, descriptorSource}'
```

Expected: `C9H8O4`, MW 180.16, **computed** logP ≈ 1.31, 1 donor, 4 acceptors, 2
rotatable bonds. The structure is stored as a real SDF with an ETKDGv3 + MMFF94
conformer, so the coordinates and the descriptors cannot drift apart.

## 7. Run a real background job

```bash
JOB=$(curl -s -XPOST $API/jobs/self-test \
        -H 'content-type: application/json' \
        -d "{\"projectId\":\"$PROJECT\",\"steps\":5}" | jq -r .id)
watch -n1 "curl -s $API/jobs/$JOB | jq '{state, progress, message}'"
```

You will see `queued → preparing → running → completed` with `progress` climbing
from 0 to 1. Press Ctrl-C and check the log:

```bash
curl -s $API/jobs/$JOB/log | jq -r .text | tail
```

This proves the durable queue, the subprocess worker, progress reporting and
cancellation are real — the same machinery Phase 2/3 jobs will use.

## 8. Export

```bash
curl -s "$API/structures/$STRUCTURE/export?format=pdb" -o 3ptb.pdb
grep -c '^ATOM' 3ptb.pdb        # 1637 protein atoms
grep -c '^CONECT' 3ptb.pdb      # non-zero; CONECT comes before END
tail -1 3ptb.pdb                # END
```

Exporting a *protein* to SDF is refused with `unsupported_format` and a clear
message, because an SDF cannot represent a macromolecule — that refusal is a
feature, not a bug.

## 9. Wrap up

```bash
curl -s "$API/projects/$PROJECT/export" -o trypsin-study.moldock.zip
unzip -l trypsin-study.moldock.zip
```

The archive contains a `manifest.json` plus every stored artefact — enough to
reproduce the project elsewhere.

---

### What this workflow deliberately does **not** do

- It does not dock. Docking is Phase 3; `/api/health` reports it as
  `not_implemented` and there is no fake endpoint standing in for it.
- It does not claim the computed logP is a measured property, nor that any score
  is a binding affinity.
