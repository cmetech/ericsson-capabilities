"""Bounded, redacted Artifactory operations.

The endpoint set follows super-cli's internal/arm. The operational
behaviour -- checksum-first deploy with a fallback, AQL include rules,
folder delete semantics -- follows the OSCAR shell scripts in
oscar_app/oscar/utils, which have production knowledge super-cli does not.
Redaction and approval discipline follow ericsson-jira.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

if __package__:
    from ._common.envelope import result_envelope
    from .models import ArmError
else:
    from _common.envelope import result_envelope
    from models import ArmError


_REPO_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_PATH_CHARS = 1024
_MAX_CHILDREN = 1000


def _bounded_string(value: Any, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    return value[:maximum]


def _as_int(value: Any) -> int | None:
    """Artifactory sends size as a JSON string. Coerce, or report nothing."""
    if type(value) is int:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


class ArmOperations:
    def __init__(self, client, *, max_pages: int = 1) -> None:
        if type(max_pages) is not int or not 1 <= max_pages <= 10:
            raise ArmError("invalid_configuration")
        self.client = client
        self.max_pages = max_pages
        self.base = client.path_prefix.rstrip("/")

    def _redact(self, value: str | None) -> str | None:
        """Strip configured credentials from every remote text value."""
        if value is None:
            return None
        auth = self.client.auth
        for secret in (
            getattr(auth, "auth_header_value", ""),
            getattr(auth, "token", ""),
        ):
            if isinstance(secret, str) and len(secret) >= 4:
                value = value.replace(secret, "<redacted>")
        return value

    def _remote_string(self, value: Any, maximum: int) -> str | None:
        """Bound and redact one string copied from an Artifactory response."""
        return self._redact(_bounded_string(value, maximum))

    @staticmethod
    def _repo(value: Any) -> str:
        if not isinstance(value, str) or _REPO_KEY.fullmatch(value) is None:
            raise ArmError(
                "invalid_input",
                remediation="Repository must be a single Artifactory repository key.",
            )
        return value

    @staticmethod
    def _path(value: Any, *, allow_empty: bool = False) -> str:
        """Normalise a path while refusing confinement-escaping values."""
        if not isinstance(value, str) or len(value) > _MAX_PATH_CHARS:
            raise ArmError("invalid_input")
        cleaned = value.strip().strip("/")
        if not cleaned:
            if allow_empty:
                return ""
            raise ArmError("invalid_input")
        if (
            "\x00" in cleaned
            or "\\" in cleaned
            or ".." in cleaned.split("/")
            or any(character.isspace() for character in cleaned)
        ):
            raise ArmError(
                "invalid_input",
                remediation="Path must be a plain repository path with no '..' segments.",
            )
        return cleaned

    @staticmethod
    def _bounded_max(value: Any, maximum: int) -> int:
        if type(value) is not int or not 1 <= value <= maximum:
            raise ArmError("invalid_input")
        return value

    @staticmethod
    def _mapping(payload: Any) -> Mapping[str, Any]:
        if not isinstance(payload, Mapping):
            raise ArmError("invalid_remote_data")
        return payload

    def _storage_path(self, repo: str, path: str) -> str:
        suffix = f"/{path}" if path else ""
        return f"{self.base}/api/storage/{repo}{suffix}"

    def list_repositories(
        self,
        *,
        repository_type: str | None = None,
        package_type: str | None = None,
        max_results: int = 25,
    ) -> dict[str, Any]:
        """Enumerate visible repositories, optionally filtered."""
        max_results = self._bounded_max(max_results, 100)
        params: dict[str, Any] = {}
        for name, value in (("type", repository_type),
                            ("packageType", package_type)):
            if value is None:
                continue
            if not isinstance(value, str) or not 1 <= len(value) <= 64:
                raise ArmError("invalid_input")
            params[name] = value

        payload = self.client.get_json(f"{self.base}/api/repositories", params=params)
        if not isinstance(payload, list):
            raise ArmError("invalid_remote_data")

        rows = [row for row in payload if isinstance(row, Mapping)]
        items = [
            {
                "key": self._remote_string(row.get("key"), 128) or "",
                "type": self._remote_string(row.get("type"), 64) or "",
                "package_type": self._remote_string(row.get("packageType"), 64) or "",
                "description": self._remote_string(row.get("description"), 512) or "",
                "url": self._remote_string(row.get("url"), 2048) or "",
            }
            for row in rows[:max_results]
        ]
        truncated = len(rows) > max_results
        return result_envelope(
            items,
            total=len(rows),
            truncated=truncated,
            hint=(
                "More repositories exist. Raise max_results, or filter with "
                "repository_type or package_type." if truncated else None
            ),
        )

    def artifact_info(
        self, repo: str, path: str, *, max_children: int = 100
    ) -> dict[str, Any]:
        """Fetch one artefact's or folder's metadata from one endpoint."""
        repo = self._repo(repo)
        path = self._path(path, allow_empty=True)
        max_children = self._bounded_max(max_children, _MAX_CHILDREN)

        payload = self._mapping(self.client.get_json(self._storage_path(repo, path)))
        raw_children = payload.get("children")
        is_folder = isinstance(raw_children, list)

        children: list[dict[str, Any]] = []
        children_truncated = False
        if is_folder:
            entries = [child for child in raw_children if isinstance(child, Mapping)]
            children_truncated = len(entries) > max_children
            for child in entries[:max_children]:
                uri = self._remote_string(child.get("uri"), 1024) or ""
                children.append({
                    "name": uri.lstrip("/"),
                    "folder": child.get("folder") is True,
                })

        checksums = payload.get("checksums")
        return {
            "repo": self._remote_string(payload.get("repo"), 128) or self._redact(repo),
            "path": self._remote_string(payload.get("path"), _MAX_PATH_CHARS) or self._redact(f"/{path}"),
            "kind": "folder" if is_folder else "file",
            "size": None if is_folder else _as_int(payload.get("size")),
            "mime_type": self._remote_string(payload.get("mimeType"), 255),
            "created": self._remote_string(payload.get("created"), 64),
            "modified": self._remote_string(payload.get("lastModified"), 64),
            "download_uri": self._remote_string(payload.get("downloadUri"), 2048),
            "checksums": {
                name: self._remote_string(checksums.get(name), 128) or ""
                for name in ("md5", "sha1", "sha256")
            } if isinstance(checksums, Mapping) else {},
            "children": children,
            "children_truncated": children_truncated,
        }
