"""Shared pydantic configuration for the wire schemas.

Two naming conventions meet in the API layer:

* **JSON on the wire is camelCase** (``projectId``, ``fileSha256``). That is what
  the SPA consumes and it is frozen.
* **Python attributes are snake_case** (``project_id``, ``file_sha256``). That is
  what the SQLAlchemy models expose, and renaming them is not an option.

:class:`ORMModel` reconciles the two. Field names stay camelCase — so nothing
that constructs a schema has to change and the serialised JSON is unchanged —
while a *validation* alias derived with :func:`to_snake` lets
``Model.model_validate(orm_row)`` read the snake_case attributes directly.

``populate_by_name=True`` means a client may send either spelling, so requests
written against the camelCase docs keep working.

A handful of names do not round-trip through the generator (``fileSha256`` would
become ``file_sha_256``); those set an explicit ``validation_alias`` on the field,
which takes precedence.
"""

from __future__ import annotations

from pydantic import AliasGenerator, BaseModel, ConfigDict
from pydantic.alias_generators import to_snake


class ORMModel(BaseModel):
    """Base for schemas that are validated from (or mirror) database rows."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        alias_generator=AliasGenerator(validation_alias=to_snake),
    )
