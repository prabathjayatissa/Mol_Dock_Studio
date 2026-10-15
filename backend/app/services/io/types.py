"""Format-neutral structure representation.

Every parser (gemmi, RDKit, our own PDBQT reader) produces a
:class:`ParsedStructure`. Downstream code — the viewer packet builder, surface
generation, preparation and (later) docking — only ever sees this type, so a
new format is added by writing one parser.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from app.services.chemistry.elements import element_by_symbol

Severity = Literal["info", "warning", "error"]


@dataclass
class StructureWarning:
    """A user-visible note about parsing or information loss."""

    code: str
    message: str
    severity: Severity = "warning"
    count: int = 1
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        if self.count != 1:
            payload["count"] = self.count
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass
class Atom:
    index: int
    serial: int
    name: str
    element: str
    x: float
    y: float
    z: float
    residue_index: int
    chain_index: int
    occupancy: float = 1.0
    bfactor: float = 0.0
    formal_charge: int = 0
    partial_charge: float | None = None
    altloc: str = ""
    record: str = "ATOM"
    is_hetero: bool = False
    is_water: bool = False
    is_backbone: bool = False
    # AutoDock atom type when read from PDBQT (used from Phase 3 onwards).
    autodock_type: str | None = None

    @property
    def vdw_radius(self) -> float:
        return element_by_symbol(self.element).vdw_radius

    @property
    def covalent_radius(self) -> float:
        return element_by_symbol(self.element).covalent_radius

    @property
    def color(self) -> str:
        return element_by_symbol(self.element).color

    @property
    def coords(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass
class Residue:
    index: int
    name: str
    seq: int
    chain_index: int
    atom_start: int
    atom_count: int
    insertion_code: str = ""
    ss: Literal["H", "E", "C"] = "C"
    is_hetero: bool = False
    is_water: bool = False
    is_amino_acid: bool = False
    is_nucleic: bool = False
    one_letter: str = "X"
    # Atom indices (into ``ParsedStructure.atoms``) of the backbone trace.
    ca_index: int | None = None
    n_index: int | None = None
    c_index: int | None = None
    o_index: int | None = None
    cb_index: int | None = None
    title: str = ""
    smiles: str | None = None

    @property
    def label(self) -> str:
        base = f"{self.name}{self.seq}{self.insertion_code}".strip()
        return f"{self.chain_label}:{base}" if self.chain_label else base

    chain_label: str = ""


@dataclass
class Chain:
    index: int
    id: str
    residue_start: int
    residue_count: int
    kind: Literal["polymer", "ligand", "water", "ion", "other"] = "polymer"

    @property
    def residue_end(self) -> int:
        return self.residue_start + self.residue_count


@dataclass
class Bond:
    a: int
    b: int
    order: int = 1
    source: Literal["file", "geometry"] = "geometry"
    aromatic: bool = False

    def as_tuple(self) -> tuple[int, int]:
        return (self.a, self.b)


@dataclass
class ParsedStructure:
    """A fully parsed structure, ready to be stored and rendered."""

    format: str
    name: str = "structure"
    source: str = "uploaded"
    atoms: list[Atom] = field(default_factory=list)
    residues: list[Residue] = field(default_factory=list)
    chains: list[Chain] = field(default_factory=list)
    bonds: list[Bond] = field(default_factory=list)
    warnings: list[StructureWarning] = field(default_factory=list)
    # chain id -> one-letter sequence
    sequences: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    # --- convenience properties -------------------------------------------
    @property
    def atom_count(self) -> int:
        return len(self.atoms)

    @property
    def heavy_atom_count(self) -> int:
        return sum(1 for atom in self.atoms if atom.element.upper() != "H")

    @property
    def has_coordinates(self) -> bool:
        return len(self.atoms) > 0

    @property
    def is_ligand_like(self) -> bool:
        """True when nothing in the structure looks like a polymer chain."""
        return bool(self.atoms) and all(chain.kind in {"ligand", "other", "ion"} for chain in self.chains)

    @property
    def element_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for atom in self.atoms:
            counts[atom.element] = counts.get(atom.element, 0) + 1
        return counts

    @property
    def secondary_structure_content(self) -> dict[str, int]:
        content = {"helix": 0, "sheet": 0, "coil": 0}
        for residue in self.residues:
            if residue.ss == "H":
                content["helix"] += 1
            elif residue.ss == "E":
                content["sheet"] += 1
            elif residue.is_amino_acid:
                content["coil"] += 1
        return content

    def bounds(self) -> dict[str, list[float]]:
        if not self.atoms:
            return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0]}
        xs = [atom.x for atom in self.atoms]
        ys = [atom.y for atom in self.atoms]
        zs = [atom.z for atom in self.atoms]
        return {"min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]}

    def centroid(self) -> tuple[float, float, float]:
        if not self.atoms:
            return (0.0, 0.0, 0.0)
        count = len(self.atoms)
        return (
            sum(atom.x for atom in self.atoms) / count,
            sum(atom.y for atom in self.atoms) / count,
            sum(atom.z for atom in self.atoms) / count,
        )

    def bounding_radius(self) -> float:
        cx, cy, cz = self.centroid()
        return max(
            (
                math.dist((atom.x, atom.y, atom.z), (cx, cy, cz)) + atom.vdw_radius
                for atom in self.atoms
            ),
            default=1.0,
        )

    def add_warning(self, warning: StructureWarning) -> None:
        self.warnings.append(warning)

    def warn(self, code: str, message: str, *, severity: Severity = "warning", count: int = 1, **detail: Any) -> None:
        self.add_warning(StructureWarning(code, message, severity, count, detail))

    def summary(self) -> dict[str, Any]:
        """Compact statistics used by the UI and stored with the structure."""
        return {
            "atoms": self.atom_count,
            "heavy_atoms": self.heavy_atom_count,
            "residues": len(self.residues),
            "chains": len(self.chains),
            "bonds": len(self.bonds),
            "waters": sum(1 for residue in self.residues if residue.is_water),
            "hetero_residues": sum(
                1 for residue in self.residues if residue.is_hetero and not residue.is_water
            ),
            "elements": self.element_counts,
            "secondary_structure": self.secondary_structure_content,
            "has_coordinates": self.has_coordinates,
            "bounds": self.bounds(),
            "centroid": list(self.centroid()),
            "bounding_radius": round(self.bounding_radius(), 4),
        }
