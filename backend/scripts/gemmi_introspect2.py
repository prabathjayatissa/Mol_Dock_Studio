"""Fast gemmi-only API introspection, part 2."""

from __future__ import annotations

import gemmi

doc = gemmi.read_structure("app/data/1UBQ.pdb")
helix = list(doc.helices)[0]
res_id = helix.start.res_id
print("type(res_id):", type(res_id))
for attr in dir(res_id):
    if attr.startswith("__"):
        continue
    try:
        value = getattr(res_id, attr)
    except Exception as exc:  # noqa: BLE001
        value = f"<error {exc}>"
    print(f"  res_id.{attr} = {value!r}")
print("str(res_id):", str(res_id))
try:
    print("int(res_id):", int(res_id))
except Exception as exc:  # noqa: BLE001
    print("int(res_id) failed:", exc)

print()
doc3 = gemmi.read_structure("app/data/3PTB.pdb")
print("3PTB connections:", len(doc3.connections))
conn = list(doc3.connections)[0]
print("conn type:", type(conn))
for attr in dir(conn):
    if attr.startswith("__"):
        continue
    try:
        value = getattr(conn, attr)
    except Exception as exc:  # noqa: BLE001
        value = f"<error {exc}>"
    print(f"  conn.{attr} = {value!r}")
print("partner1 type:", type(conn.partner1))
for attr in dir(conn.partner1):
    if attr.startswith("__"):
        continue
    try:
        value = getattr(conn.partner1, attr)
    except Exception as exc:  # noqa: BLE001
        value = f"<error {exc}>"
    print(f"  partner1.{attr} = {value!r}")
p1 = conn.partner1.res_id
for attr in dir(p1):
    if attr.startswith("__"):
        continue
    try:
        value = getattr(p1, attr)
    except Exception as exc:  # noqa: BLE001
        value = f"<error {exc}>"
    print(f"  p1.res_id.{attr} = {value!r}")
