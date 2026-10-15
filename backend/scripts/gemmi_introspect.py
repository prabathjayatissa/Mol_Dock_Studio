"""Fast gemmi-only API introspection (no numpy/rdkit import)."""

from __future__ import annotations

import gemmi

doc = gemmi.read_structure("app/data/1UBQ.pdb")
print("helices:", len(doc.helices), "sheets:", len(doc.sheets), "connections:", len(doc.connections))
helix = list(doc.helices)[0]
print("helix attrs:", [a for a in dir(helix) if not a.startswith("__")])
print("start:", repr(helix.start), "start attrs:", [a for a in dir(helix.start) if not a.startswith("__")])
res_id = helix.start.res_id
print("res_id:", repr(res_id), "attrs:", [a for a in dir(res_id) if not a.startswith("__")])
print("res_id.num:", getattr(res_id, "num", "NO num"), "seqnum:", getattr(res_id, "seqnum", "NO seqnum"))
sheet = list(doc.sheets)[0]
strand = list(sheet.strands)[0]
print("strand attrs:", [a for a in dir(strand) if not a.startswith("__")])
print("strand.start:", repr(strand.start), "end:", repr(strand.end))
conn = list(doc.connections)[0]
print("connection attrs:", [a for a in dir(conn) if not a.startswith("__")])
print("partner1:", repr(conn.partner1), "attrs:", [a for a in dir(conn.partner1) if not a.startswith("__")])
print("p1.res_id:", repr(conn.partner1.res_id), "num:", getattr(conn.partner1.res_id, "num", None))
print("p1.atom_name:", repr(conn.partner1.atom_name), "chain:", repr(conn.partner1.chain_name))
print("connection.type:", repr(getattr(conn, "type", None)), "conn.conn_type:", repr(getattr(conn, "conn_type", None)))
