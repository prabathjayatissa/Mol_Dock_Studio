"""Periodic-table data used across the backend.

Values are the standard published van der Waals radii (Bondi 1964 with the
commonly used extensions for metals) and single-bond covalent radii (Cordero
et al. 2008). Colours are the conventional CPK/Jmol palette.

The same table is mirrored in the frontend (``src/viewer/chemistry.ts``) so the
renderer and the analysis code agree; tests assert that the two stay in sync.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ElementInfo:
    symbol: str
    name: str
    atomic_number: int
    atomic_mass: float
    vdw_radius: float
    covalent_radius: float
    color: str  # hex RGB used by the viewer
    # Element class used by interaction analysis in later phases.
    is_metal: bool = False
    is_halogen: bool = False
    is_hbond_acceptor: bool = False


_ELEMENTS: tuple[ElementInfo, ...] = (
    ElementInfo("H", "Hydrogen", 1, 1.008, 1.20, 0.31, "#FFFFFF"),
    ElementInfo("He", "Helium", 2, 4.0026, 1.40, 0.28, "#D9FFFF"),
    ElementInfo("Li", "Lithium", 3, 6.94, 1.82, 1.28, "#CC80FF", is_metal=True),
    ElementInfo("Be", "Beryllium", 4, 9.0122, 1.53, 0.96, "#C2FF00", is_metal=True),
    ElementInfo("B", "Boron", 5, 10.81, 1.92, 0.84, "#FFB5B5"),
    ElementInfo("C", "Carbon", 6, 12.011, 1.70, 0.76, "#909090"),
    ElementInfo("N", "Nitrogen", 7, 14.007, 1.55, 0.71, "#3050F8", is_hbond_acceptor=True),
    ElementInfo("O", "Oxygen", 8, 15.999, 1.52, 0.66, "#FF0D0D", is_hbond_acceptor=True),
    ElementInfo("F", "Fluorine", 9, 18.998, 1.47, 0.57, "#90E050", is_halogen=True),
    ElementInfo("Ne", "Neon", 10, 20.180, 1.54, 0.58, "#B3E3F5"),
    ElementInfo("Na", "Sodium", 11, 22.990, 2.27, 1.66, "#AB5CF2", is_metal=True),
    ElementInfo("Mg", "Magnesium", 12, 24.305, 1.73, 1.41, "#8AFF00", is_metal=True),
    ElementInfo("Al", "Aluminium", 13, 26.982, 1.84, 1.21, "#BFA6A6", is_metal=True),
    ElementInfo("Si", "Silicon", 14, 28.085, 2.10, 1.11, "#F0C8A0"),
    ElementInfo("P", "Phosphorus", 15, 30.974, 1.80, 1.07, "#FF8000"),
    ElementInfo("S", "Sulfur", 16, 32.06, 1.80, 1.05, "#FFFF30", is_hbond_acceptor=True),
    ElementInfo("Cl", "Chlorine", 17, 35.45, 1.75, 1.02, "#1FF01F", is_halogen=True),
    ElementInfo("Ar", "Argon", 18, 39.948, 1.88, 1.06, "#80D1E3"),
    ElementInfo("K", "Potassium", 19, 39.098, 2.75, 2.03, "#8F40D4", is_metal=True),
    ElementInfo("Ca", "Calcium", 20, 40.078, 2.31, 1.76, "#3DFF00", is_metal=True),
    ElementInfo("Sc", "Scandium", 21, 44.956, 2.30, 1.70, "#E6E6E6", is_metal=True),
    ElementInfo("Ti", "Titanium", 22, 47.867, 2.15, 1.60, "#BFC2C7", is_metal=True),
    ElementInfo("V", "Vanadium", 23, 50.942, 2.05, 1.53, "#A6A6AB", is_metal=True),
    ElementInfo("Cr", "Chromium", 24, 51.996, 2.00, 1.39, "#8A99C7", is_metal=True),
    ElementInfo("Mn", "Manganese", 25, 54.938, 1.79, 1.39, "#9C7AC7", is_metal=True),
    ElementInfo("Fe", "Iron", 26, 55.845, 1.80, 1.24, "#E06633", is_metal=True),
    ElementInfo("Co", "Cobalt", 27, 58.933, 1.83, 1.26, "#F090A0", is_metal=True),
    ElementInfo("Ni", "Nickel", 28, 58.693, 1.63, 1.24, "#50D050", is_metal=True),
    ElementInfo("Cu", "Copper", 29, 63.546, 1.40, 1.32, "#C88033", is_metal=True),
    ElementInfo("Zn", "Zinc", 30, 65.38, 1.39, 1.22, "#7D80B0", is_metal=True),
    ElementInfo("Ga", "Gallium", 31, 69.723, 1.87, 1.22, "#C28F8F", is_metal=True),
    ElementInfo("Ge", "Germanium", 32, 72.630, 2.11, 1.20, "#668F8F"),
    ElementInfo("As", "Arsenic", 33, 74.922, 1.85, 1.19, "#BD80E3"),
    ElementInfo("Se", "Selenium", 34, 78.971, 1.90, 1.20, "#FFA100", is_hbond_acceptor=True),
    ElementInfo("Br", "Bromine", 35, 79.904, 1.85, 1.20, "#A62929", is_halogen=True),
    ElementInfo("Kr", "Krypton", 36, 83.798, 2.02, 1.16, "#5CB8D1"),
    ElementInfo("Rb", "Rubidium", 37, 85.468, 3.03, 2.20, "#702EB0", is_metal=True),
    ElementInfo("Sr", "Strontium", 38, 87.62, 2.49, 1.95, "#00FF00", is_metal=True),
    ElementInfo("Y", "Yttrium", 39, 88.906, 2.40, 1.90, "#94FFFF", is_metal=True),
    ElementInfo("Zr", "Zirconium", 40, 91.224, 2.30, 1.75, "#94E0E0", is_metal=True),
    ElementInfo("Mo", "Molybdenum", 42, 95.95, 2.10, 1.54, "#54B5B5", is_metal=True),
    ElementInfo("Ag", "Silver", 47, 107.87, 1.72, 1.45, "#C0C0C0", is_metal=True),
    ElementInfo("Cd", "Cadmium", 48, 112.41, 1.58, 1.44, "#FFD98F", is_metal=True),
    ElementInfo("Sn", "Tin", 50, 118.71, 2.17, 1.39, "#668080", is_metal=True),
    ElementInfo("I", "Iodine", 53, 126.90, 1.98, 1.39, "#940094", is_halogen=True),
    ElementInfo("Cs", "Caesium", 55, 132.91, 3.43, 2.44, "#57178F", is_metal=True),
    ElementInfo("Ba", "Barium", 56, 137.33, 2.68, 2.15, "#00C900", is_metal=True),
    ElementInfo("Pt", "Platinum", 78, 195.08, 1.75, 1.36, "#D0D0E0", is_metal=True),
    ElementInfo("Au", "Gold", 79, 196.97, 1.66, 1.36, "#FFD123", is_metal=True),
    ElementInfo("Hg", "Mercury", 80, 200.59, 1.55, 1.32, "#B8B8D0", is_metal=True),
    ElementInfo("Pb", "Lead", 82, 207.2, 2.02, 1.46, "#575961", is_metal=True),
)

BY_SYMBOL: dict[str, ElementInfo] = {element.symbol: element for element in _ELEMENTS}
BY_UPPER: dict[str, ElementInfo] = {element.symbol.upper(): element for element in _ELEMENTS}
BY_NUMBER: dict[int, ElementInfo] = {element.atomic_number: element for element in _ELEMENTS}

UNKNOWN_ELEMENT = ElementInfo("X", "Unknown", 0, 0.0, 1.70, 0.77, "#FF1493")


def element_by_symbol(symbol: str | None) -> ElementInfo:
    """Case-insensitive lookup; unknown elements map to a visually obvious pink."""
    if not symbol:
        return UNKNOWN_ELEMENT
    return BY_UPPER.get(symbol.strip().upper(), UNKNOWN_ELEMENT)


def element_by_number(number: int) -> ElementInfo:
    return BY_NUMBER.get(number, UNKNOWN_ELEMENT)


def vdw_radius_table() -> dict[str, float]:
    return {element.symbol: element.vdw_radius for element in _ELEMENTS}


def cpk_table() -> dict[str, str]:
    return {element.symbol: element.color for element in _ELEMENTS}


# --- amino-acid tables ------------------------------------------------------

# Three-letter codes of the standard residues plus the common ambiguous ones.
AMINO_ACIDS: dict[str, dict[str, object]] = {
    "ALA": {"one": "A", "name": "Alanine", "hydropathy": 1.8, "type": "hydrophobic"},
    "ARG": {"one": "R", "name": "Arginine", "hydropathy": -4.5, "type": "positive"},
    "ASN": {"one": "N", "name": "Asparagine", "hydropathy": -3.5, "type": "polar"},
    "ASP": {"one": "D", "name": "Aspartate", "hydropathy": -3.5, "type": "negative"},
    "CYS": {"one": "C", "name": "Cysteine", "hydropathy": 2.5, "type": "polar"},
    "GLN": {"one": "Q", "name": "Glutamine", "hydropathy": -3.5, "type": "polar"},
    "GLU": {"one": "E", "name": "Glutamate", "hydropathy": -3.5, "type": "negative"},
    "GLY": {"one": "G", "name": "Glycine", "hydropathy": -0.4, "type": "hydrophobic"},
    "HIS": {"one": "H", "name": "Histidine", "hydropathy": -3.2, "type": "positive"},
    "ILE": {"one": "I", "name": "Isoleucine", "hydropathy": 4.5, "type": "hydrophobic"},
    "LEU": {"one": "L", "name": "Leucine", "hydropathy": 3.8, "type": "hydrophobic"},
    "LYS": {"one": "K", "name": "Lysine", "hydropathy": -3.9, "type": "positive"},
    "MET": {"one": "M", "name": "Methionine", "hydropathy": 1.9, "type": "hydrophobic"},
    "PHE": {"one": "F", "name": "Phenylalanine", "hydropathy": 2.8, "type": "aromatic"},
    "PRO": {"one": "P", "name": "Proline", "hydropathy": -1.6, "type": "hydrophobic"},
    "SER": {"one": "S", "name": "Serine", "hydropathy": -0.8, "type": "polar"},
    "THR": {"one": "T", "name": "Threonine", "hydropathy": -0.7, "type": "polar"},
    "TRP": {"one": "W", "name": "Tryptophan", "hydropathy": -0.9, "type": "aromatic"},
    "TYR": {"one": "Y", "name": "Tyrosine", "hydropathy": -1.3, "type": "aromatic"},
    "VAL": {"one": "V", "name": "Valine", "hydropathy": 4.2, "type": "hydrophobic"},
    # nucleic acids (rendered but not treated as protein in the UI)
    "DA": {"one": "A", "name": "Deoxyadenosine", "hydropathy": 0.0, "type": "nucleic"},
    "DC": {"one": "C", "name": "Deoxycytidine", "hydropathy": 0.0, "type": "nucleic"},
    "DG": {"one": "G", "name": "Deoxyguanosine", "hydropathy": 0.0, "type": "nucleic"},
    "DT": {"one": "T", "name": "Thymidine", "hydropathy": 0.0, "type": "nucleic"},
    "A": {"one": "A", "name": "Adenosine", "hydropathy": 0.0, "type": "nucleic"},
    "C": {"one": "C", "name": "Cytidine", "hydropathy": 0.0, "type": "nucleic"},
    "G": {"one": "G", "name": "Guanosine", "hydropathy": 0.0, "type": "nucleic"},
    "U": {"one": "U", "name": "Uridine", "hydropathy": 0.0, "type": "nucleic"},
}

WATER_NAMES = {"HOH", "WAT", "DOD", "H2O", "TIP", "TIP3", "SOL"}

BACKBONE_ATOMS = {"N", "CA", "C", "O", "OXT", "H", "HA"}


def residue_info(name: str) -> dict[str, object] | None:
    return AMINO_ACIDS.get(name.strip().upper())


def is_amino_acid(name: str) -> bool:
    info = residue_info(name)
    return bool(info) and info.get("type") != "nucleic"


def is_water(name: str) -> bool:
    return name.strip().upper() in WATER_NAMES
