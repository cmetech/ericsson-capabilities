"""Bounded, redacted Confluence operations."""

from __future__ import annotations

import re
from typing import Any, Mapping

if __package__:
    from ._common.envelope import UNTRUSTED_CONTENT_WARNING, result_envelope
    from .models import ConfluenceError
    from .storage import storage_to_markdown
else:
    from _common.envelope import UNTRUSTED_CONTENT_WARNING, result_envelope
    from models import ConfluenceError
    from storage import storage_to_markdown


EXPAND_PAGE = "body.storage,version,space,ancestors,metadata.labels,history.lastUpdated"
EXPAND_LIST = "version,space,ancestors"

_CONTENT_ID = re.compile(r"^[0-9]{1,19}$")
_MAX_BODY_CHARS = 100_000
_MAX_CQL_CHARS = 4096


def _bounded_string(value: Any, maximum: int) -> str | None:
    return value[:maximum] if isinstance(value, str) else None


class ConfluenceOperations:
    def __init__(self, client, *, max_pages: int = 10) -> None:
        if type(max_pages) is not int or not 1 <= max_pages <= 10:
            raise ConfluenceError("invalid_configuration")
        self.client = client
        self.max_pages = max_pages
        self.base = client.path_prefix.rstrip("/")

    def _redact(self, value: str | None) -> str | None:
        """Strip the configured token out of remote text."""
        if value is None:
            return None
        authorization = getattr(self.client.auth, "authorization", "")
        candidates = [authorization]
        if isinstance(authorization, str) and " " in authorization:
            candidates.append(authorization.split(" ", 1)[1])
        for secret in candidates:
            if isinstance(secret, str) and len(secret) >= 4:
                value = value.replace(secret, "<redacted>")
        return value

    @staticmethod
    def _content_id(value: Any) -> str:
        if not isinstance(value, str) or _CONTENT_ID.fullmatch(value) is None:
            raise ConfluenceError("invalid_input")
        return value

    @staticmethod
    def _mapping(payload: Any) -> Mapping[str, Any]:
        if not isinstance(payload, Mapping):
            raise ConfluenceError("invalid_remote_data")
        return payload

    def _storage_value(self, payload: Mapping[str, Any]) -> str:
        body = payload.get("body")
        if not isinstance(body, Mapping):
            return ""
        storage = body.get("storage")
        if not isinstance(storage, Mapping):
            return ""
        return _bounded_string(storage.get("value"), _MAX_BODY_CHARS) or ""

    @staticmethod
    def _version(payload: Mapping[str, Any]) -> int | None:
        version = payload.get("version")
        if isinstance(version, Mapping) and type(version.get("number")) is int:
            return version["number"]
        return None

    def _markdown(self, storage_value: str, *, max_chars: int) -> tuple[str, bool]:
        full = self._redact(storage_to_markdown(storage_value)) or ""
        if len(full) <= max_chars:
            return full, False
        return full[:max_chars], True

    def _content_summary(self, row: Mapping[str, Any]) -> dict[str, Any]:
        space = row.get("space")
        return {
            "id": _bounded_string(row.get("id"), 64) or "",
            "title": self._redact(_bounded_string(row.get("title"), 512)) or "",
            "type": _bounded_string(row.get("type"), 64) or "",
            "space_key": self._redact(_bounded_string(space.get("key"), 255)) if isinstance(space, Mapping) else None,
        }

    def _paged(self, path: str, params: dict[str, Any], max_results: int) -> tuple[list[Mapping[str, Any]], int | None, bool]:
        rows: list[Mapping[str, Any]] = []
        total: int | None = None
        start = 0
        page_size = min(max_results, 100)
        pages_fetched = 0
        last_results: list[Any] = []
        for _ in range(self.max_pages):
            pages_fetched += 1
            payload = self._mapping(self.client.get_json(path, params={**params, "start": start, "limit": page_size}))
            results = payload.get("results")
            if not isinstance(results, list):
                raise ConfluenceError("invalid_remote_data")
            last_results = results
            if type(payload.get("totalSize")) is int:
                total = payload["totalSize"]
            rows.extend(row for row in results if isinstance(row, Mapping))
            if not results:
                break
            if len(rows) >= max_results or (
                len(results) < page_size and (total is None or total <= len(rows))
            ):
                break
            start += len(results)
        reached_page_cap = (
            pages_fetched == self.max_pages
            and len(rows) < max_results
            and len(last_results) >= page_size
        )
        truncated = (
            len(rows) > max_results
            or (total is not None and total > len(rows))
            or reached_page_cap
        )
        return rows[:max_results], total, truncated

    def search(self, cql: str, *, max_results: int = 25) -> dict[str, Any]:
        """Search content with CQL.

        Raw CQL is exposed deliberately: it is the whole value of Confluence
        search, and the configured token carries the user's own permissions,
        so a query cannot reach content the user could not already read.
        Enumeration uses EXPAND_LIST -- bodies are fetched deliberately via
        confluence_get_page rather than dragged along with every hit.
        """
        if (
            not isinstance(cql, str)
            or not cql.strip()
            or len(cql) > _MAX_CQL_CHARS
        ):
            raise ConfluenceError("invalid_input")
        if type(max_results) is not int or not 1 <= max_results <= 100:
            raise ConfluenceError("invalid_input")
        rows, total, truncated = self._paged(
            f"{self.base}/content/search",
            {"cql": cql, "expand": EXPAND_LIST},
            max_results,
        )
        return result_envelope(
            [self._content_summary(row) for row in rows],
            total=total,
            truncated=truncated,
            hint=(
                "More content matches this CQL. Raise max_results or narrow "
                "the query." if truncated else None
            ),
            untrusted=True,
        )

    def get_page(self, content_id: str) -> dict[str, Any]:
        content_id = self._content_id(content_id)
        payload = self._mapping(self.client.get_json(f"{self.base}/content/{content_id}", params={"expand": EXPAND_PAGE}))
        space = payload.get("space")
        breadcrumb = []
        ancestors = payload.get("ancestors")
        if isinstance(ancestors, list):
            for ancestor in ancestors[:20]:
                if isinstance(ancestor, Mapping):
                    title = self._redact(_bounded_string(ancestor.get("title"), 255))
                    if title:
                        breadcrumb.append(title)
        markdown, _ = self._markdown(self._storage_value(payload), max_chars=_MAX_BODY_CHARS)
        return {
            "id": _bounded_string(payload.get("id"), 64) or content_id,
            "title": self._redact(_bounded_string(payload.get("title"), 512)) or "",
            "type": _bounded_string(payload.get("type"), 64) or "",
            "version": self._version(payload),
            "space_key": self._redact(_bounded_string(space.get("key"), 255)) if isinstance(space, Mapping) else None,
            "breadcrumb": breadcrumb,
            "markdown": markdown,
            "content_warning": UNTRUSTED_CONTENT_WARNING,
        }

    def get_page_body(self, content_id: str, *, raw_storage: bool = False, max_chars: int = 32_000) -> dict[str, Any]:
        content_id = self._content_id(content_id)
        if type(raw_storage) is not bool or type(max_chars) is not int or not 1 <= max_chars <= _MAX_BODY_CHARS:
            raise ConfluenceError("invalid_input")
        payload = self._mapping(self.client.get_json(f"{self.base}/content/{content_id}", params={"expand": "body.storage,version"}))
        storage_value = self._storage_value(payload)
        markdown, truncated = self._markdown(storage_value, max_chars=max_chars)
        result: dict[str, Any] = {
            "id": content_id,
            "version": self._version(payload),
            "markdown": markdown,
            "truncated": truncated,
            "content_warning": UNTRUSTED_CONTENT_WARNING,
        }
        if truncated:
            result["hint"] = "The page body was truncated. Raise max_chars to read more."
        if raw_storage:
            result["raw_storage"] = self._redact(storage_value) or ""
        return result
