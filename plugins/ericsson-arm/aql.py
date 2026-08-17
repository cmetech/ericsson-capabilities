"""AQL query preparation.

Raw AQL is exposed deliberately: it is the whole value of Artifactory
search, and the configured token carries the user's own permissions, so a
query cannot reach content the user could not already read. What the
connector adds is bounds and one non-obvious permission rule that
Artifactory enforces but does not advertise.
"""

from __future__ import annotations

import re

if __package__:
    from .models import ArmError
else:
    from models import ArmError


_MAX_QUERY_CHARS = 8192

# A domain call is what makes a string AQL. The domain itself may be dotted
# (archive.entries), so the pattern allows it rather than enumerating the
# domains JFrog happens to ship this version.
_DOMAIN_FIND = re.compile(
    r"^\s*[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*\s*\.\s*find\s*\("
)
_LIMIT_CALL = re.compile(r"\.\s*limit\s*\(")
_INCLUDE_CALL = re.compile(r"\.\s*include\s*\(([^)]*)\)")
_QUOTED_FIELD = re.compile(r"""['\"]([^'\"]+)['\"]""")

# Artifactory rejects an include that omits any of these:
#   "For permissions reasons AQL demands the following fields:
#    repo, path and name."
# Documented at oscar_app/oscar/utils/cleanup_artifactory_releases.sh:174-178.
REQUIRED_FIELDS = ("repo", "path", "name")

# Used when the caller supplies no include at all. Without one Artifactory
# returns roughly forty columns per row.
DEFAULT_FIELDS = ("repo", "path", "name", "size", "created", "modified")


def _render(fields) -> str:
    return ".include(" + ",".join(f'"{field}"' for field in fields) + ")"


def prepare(query: str, *, max_results: int) -> str:
    """Validate an AQL query and return it with bounds and permission fields.

    Adding fields to an include changes which columns come back, never which
    rows match. Appending the limit is the connector-enforced result bound.
    """
    if not isinstance(query, str):
        raise ArmError("invalid_input")
    text = query.strip()
    if not text or len(text) > _MAX_QUERY_CHARS:
        raise ArmError(
            "invalid_input",
            remediation=f"AQL query must be 1 to {_MAX_QUERY_CHARS} characters.",
        )
    if _DOMAIN_FIND.match(text) is None:
        raise ArmError(
            "invalid_input",
            remediation=(
                "AQL must begin with a domain find call, for example "
                'items.find({"repo":"generic-local"}).'
            ),
        )
    if _LIMIT_CALL.search(text):
        raise ArmError(
            "invalid_input",
            remediation=(
                "Do not put .limit() in the query; AQL accepts only one and "
                "the connector supplies it. Use max_results instead."
            ),
        )

    match = _INCLUDE_CALL.search(text)
    if match is None:
        text = f"{text}{_render(DEFAULT_FIELDS)}"
    else:
        present = _QUOTED_FIELD.findall(match.group(1))
        missing = [field for field in REQUIRED_FIELDS if field not in present]
        if missing:
            text = (
                text[:match.start()]
                + _render([*present, *missing])
                + text[match.end():]
            )

    return f"{text}.limit({max_results})"
