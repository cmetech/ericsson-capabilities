"""Bounded deterministic GitLab repository read operations."""

from __future__ import annotations

import base64
import binascii
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import quote, unquote, urlsplit

if __package__:
    from .client import GitLabClient
    from .models import GitLabError, PageResult
else:  # Standalone source tests import modules directly from the plugin root.
    from client import GitLabClient
    from models import GitLabError, PageResult


_MAX_PROJECT_REFERENCE = 2048
_MAX_PROJECT_SLUG = 1024
_MAX_REF = 512
_MAX_PATH = 4096
_MAX_TREE_ITEMS = 2000
_MAX_PIPELINES = 500
_MAX_FILE_BYTES = 512 * 1024


def _bounded_string(value: Any, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise GitLabError("invalid_input")
    value = value.strip()
    if (not value and not allow_empty) or len(value) > maximum or "\x00" in value:
        raise GitLabError("invalid_input")
    return value


def _validate_path(path: str, *, allow_empty: bool = True) -> str:
    path = _bounded_string(path, _MAX_PATH, allow_empty=allow_empty)
    if path.startswith("/") or any(part in {".", ".."} for part in path.split("/")):
        raise GitLabError("invalid_input")
    return path


def _validate_ref(ref: str) -> str:
    ref = _bounded_string(ref, _MAX_REF)
    if ref.startswith("/") or ref.endswith("/"):
        raise GitLabError("invalid_input")
    return ref


def _positive_bound(value: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise GitLabError("invalid_input")
    return value


def _as_object(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GitLabError("invalid_remote_data")
    return value


def _as_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise GitLabError("invalid_remote_data")
    return value


def _same_origin_url(value: Any, origin: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_PROJECT_REFERENCE:
        raise GitLabError("invalid_remote_data")
    parsed = urlsplit(value)
    configured = urlsplit(origin)
    if (
        parsed.scheme != configured.scheme
        or parsed.hostname != configured.hostname
        or parsed.port != configured.port
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise GitLabError("invalid_remote_data")
    return value


def _project_endpoint(project: str | int) -> str:
    if isinstance(project, bool):
        raise GitLabError("invalid_input")
    if isinstance(project, int):
        if project <= 0:
            raise GitLabError("invalid_input")
        return str(project)
    value = _bounded_string(project, _MAX_PROJECT_SLUG)
    if value.isdigit():
        return str(int(value))
    if "/" not in value or value.startswith("/") or value.endswith("/"):
        raise GitLabError("group_ambiguity")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise GitLabError("invalid_input")
    return quote(value, safe="")


class GitLabOperations:
    def __init__(self, client: GitLabClient) -> None:
        self.client = client

    def _parse_project_reference(self, reference: str | int) -> dict[str, Any]:
        if isinstance(reference, int) and not isinstance(reference, bool):
            return {"project": str(reference), "link_kind": "root", "link_suffix": ""}
        value = _bounded_string(reference, _MAX_PROJECT_REFERENCE)
        if value.isdigit():
            return {"project": str(int(value)), "link_kind": "root", "link_suffix": ""}
        if not value.startswith(("http://", "https://")):
            return {"project": value.removesuffix(".git"), "link_kind": "root", "link_suffix": ""}

        parsed = urlsplit(value)
        configured = urlsplit(self.client.auth.origin)
        if (
            parsed.scheme != configured.scheme
            or parsed.hostname != configured.hostname
            or parsed.port != configured.port
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise GitLabError("invalid_input")
        path = unquote(parsed.path).strip("/")
        if not path:
            raise GitLabError("group_ambiguity")
        if "/-/" not in path:
            slug = path.removesuffix(".git")
            return {"project": slug, "link_kind": "root", "link_suffix": ""}
        slug, suffix = path.split("/-/", 1)
        slug = slug.removesuffix(".git")
        kind, separator, remainder = suffix.partition("/")
        if kind not in {"tree", "blob"} or not separator or not remainder:
            raise GitLabError("invalid_input")
        return {"project": slug, "link_kind": kind, "link_suffix": remainder}

    def resolve_project(self, reference: str | int) -> dict[str, Any]:
        deadline = self.client.operation_deadline()
        parsed = self._parse_project_reference(reference)
        endpoint = _project_endpoint(parsed["project"])
        payload = _as_object(
            self.client.get_json(f"/api/v4/projects/{endpoint}", deadline=deadline)
        )
        project_id = payload.get("id")
        slug = payload.get("path_with_namespace")
        name = payload.get("name")
        web_url = payload.get("web_url")
        if (
            isinstance(project_id, bool)
            or not isinstance(project_id, int)
            or project_id <= 0
            or not isinstance(slug, str)
            or "/" not in slug
            or len(slug) > _MAX_PROJECT_SLUG
            or not isinstance(name, str)
            or len(name) > 512
        ):
            raise GitLabError("invalid_remote_data")
        _same_origin_url(web_url, self.client.auth.origin)
        if any(part in {"", ".", ".."} for part in slug.split("/")):
            raise GitLabError("invalid_remote_data")
        if unquote(urlsplit(web_url).path).strip("/") != slug:
            raise GitLabError("invalid_remote_data")
        default = payload.get("default_branch")
        fallback = not isinstance(default, str) or not default.strip()
        default_branch = "main" if fallback else _validate_ref(default)
        result: dict[str, Any] = {
            "id": project_id,
            "name": name,
            "path_with_namespace": slug,
            "default_branch": default_branch,
            "default_branch_fallback": fallback,
            "web_url": f"{self.client.auth.origin}/{quote(slug, safe='/')}",
            "origin": self.client.auth.origin,
            "link_kind": parsed["link_kind"],
            "link_suffix": parsed["link_suffix"],
        }
        if parsed["link_kind"] in {"tree", "blob"}:
            resolved_ref, repository_path = self._resolve_link_ref(
                project_id, parsed["link_suffix"], deadline=deadline
            )
            result["resolved_ref"] = resolved_ref
            result["repository_path"] = repository_path
        else:
            result["resolved_ref"] = default_branch
            result["repository_path"] = ""
        root_link = result["web_url"]
        selected_ref = quote(result["resolved_ref"], safe="")
        encoded_path = quote(result["repository_path"], safe="/")
        suffix = f"/{encoded_path}" if encoded_path else ""
        result["links"] = {
            "root": root_link,
            "tree": f"{root_link}/-/tree/{selected_ref}{suffix}",
            "blob": (
                f"{root_link}/-/blob/{selected_ref}{suffix}"
                if parsed["link_kind"] == "blob"
                else None
            ),
        }
        return result

    def _list_named_refs(self, project_id: int, kind: str, *, deadline: float) -> list[str]:
        refs: list[str] = []
        page = 1
        while page <= self.client.max_ref_pages:
            payload, headers = self.client.get_json_page(
                f"/api/v4/projects/{project_id}/repository/{kind}",
                params={"per_page": 100, "page": page},
                deadline=deadline,
            )
            values = _as_list(payload)
            for value in values:
                item = _as_object(value)
                name = item.get("name")
                if not isinstance(name, str) or not name or len(name) > _MAX_REF:
                    raise GitLabError("invalid_remote_data")
                refs.append(name)
                if len(refs) >= 2000:
                    raise GitLabError("capacity")
            next_header = str(headers.get("x-next-page", "")).strip()
            if not next_header and len(values) < 100:
                break
            if next_header:
                try:
                    next_page = int(next_header)
                except ValueError:
                    raise GitLabError("invalid_remote_data") from None
                if next_page <= page:
                    raise GitLabError("invalid_remote_data")
                candidate = next_page
            else:
                candidate = page + 1
            if page >= self.client.max_ref_pages:
                raise GitLabError("capacity")
            page = candidate
        return refs

    def _resolve_link_ref(
        self, project_id: int, suffix: str, *, deadline: float
    ) -> tuple[str, str]:
        suffix = _bounded_string(suffix, _MAX_PATH + _MAX_REF)
        refs = self._list_named_refs(project_id, "branches", deadline=deadline)
        refs.extend(self._list_named_refs(project_id, "tags", deadline=deadline))
        matches = [name for name in refs if suffix == name or suffix.startswith(name + "/")]
        if matches:
            selected = max(matches, key=lambda item: (len(item), item))
        else:
            selected = suffix.split("/", 1)[0]
            selected = _validate_ref(selected)
            encoded = quote(selected, safe="")
            self.client.get_json(
                f"/api/v4/projects/{project_id}/repository/commits/{encoded}",
                deadline=deadline,
            )
        remainder = suffix[len(selected):].lstrip("/")
        return selected, _validate_path(remainder, allow_empty=True)

    def _paginate(
        self,
        path: str,
        *,
        params: Mapping[str, Any],
        max_items: int,
        normalize: Callable[[Mapping[str, Any]], dict[str, Any]],
    ) -> PageResult:
        deadline = self.client.operation_deadline()
        page = 1
        items: list[dict[str, Any]] = []
        truncated = False
        next_page: int | None = None
        while page <= self.client.max_pages:
            query = dict(params)
            query.update({"per_page": 100, "page": page})
            payload, headers = self.client.get_json_page(
                path, params=query, deadline=deadline
            )
            values = _as_list(payload)
            for raw in values:
                if len(items) >= max_items:
                    truncated = True
                    next_page = page
                    break
                items.append(normalize(_as_object(raw)))
            if truncated:
                break
            next_header = str(headers.get("x-next-page", "")).strip()
            if not next_header and len(values) < 100:
                break
            candidate = page + 1
            if next_header:
                try:
                    candidate = int(next_header)
                except ValueError:
                    raise GitLabError("invalid_remote_data") from None
                if candidate <= page:
                    raise GitLabError("invalid_remote_data")
            if page >= self.client.max_pages:
                truncated = True
                next_page = candidate
                break
            page = candidate
        return PageResult(tuple(items), truncated, next_page)

    def list_repository_tree(
        self,
        project: str | int,
        *,
        ref: str,
        path: str = "",
        recursive: bool = False,
        max_items: int = 200,
    ) -> dict[str, Any]:
        project_endpoint = _project_endpoint(project)
        ref = _validate_ref(ref)
        path = _validate_path(path, allow_empty=True)
        max_items = _positive_bound(max_items, _MAX_TREE_ITEMS)
        if not isinstance(recursive, bool):
            raise GitLabError("invalid_input")

        def normalize(item: Mapping[str, Any]) -> dict[str, Any]:
            output = {}
            for field in ("id", "name", "path", "type", "mode"):
                value = item.get(field)
                if not isinstance(value, str) or len(value) > _MAX_PATH:
                    raise GitLabError("invalid_remote_data")
                output[field] = value
            if output["type"] not in {"blob", "tree", "commit"}:
                raise GitLabError("invalid_remote_data")
            return output

        pages = self._paginate(
            f"/api/v4/projects/{project_endpoint}/repository/tree",
            params={"ref": ref, "path": path, "recursive": str(recursive).lower()},
            max_items=max_items,
            normalize=normalize,
        )
        entries = sorted(pages.items, key=lambda item: (item["path"], item["id"]))
        return {
            "project": str(project),
            "ref": ref,
            "path": path,
            "recursive": recursive,
            "entries": entries,
            "count": len(entries),
            "truncated": pages.truncated,
            "continuation": {"next_page": pages.next_page} if pages.next_page else None,
        }

    def read_file(
        self,
        project: str | int,
        file_path: str,
        *,
        ref: str,
        max_bytes: int = 100 * 1024,
    ) -> dict[str, Any]:
        project_endpoint = _project_endpoint(project)
        file_path = _validate_path(file_path, allow_empty=False)
        ref = _validate_ref(ref)
        max_bytes = _positive_bound(max_bytes, _MAX_FILE_BYTES)
        encoded_path = quote(file_path, safe="")
        payload = _as_object(
            self.client.get_json(
                f"/api/v4/projects/{project_endpoint}/repository/files/{encoded_path}",
                params={"ref": ref},
            )
        )
        if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
            raise GitLabError("invalid_remote_data")
        declared_size = payload.get("size")
        if (
            isinstance(declared_size, bool)
            or not isinstance(declared_size, int)
            or declared_size < 0
        ):
            raise GitLabError("invalid_remote_data")
        if declared_size > max_bytes:
            raise GitLabError("capacity")
        compact = "".join(payload["content"].split())
        try:
            decoded = base64.b64decode(compact, validate=True)
        except (binascii.Error, ValueError):
            raise GitLabError("invalid_remote_data") from None
        if len(decoded) > max_bytes:
            raise GitLabError("capacity")
        output: dict[str, Any] = {
            "project": str(project),
            "ref": ref,
            "path": file_path,
            "size": len(decoded),
            "blob_id": payload.get("blob_id") if isinstance(payload.get("blob_id"), str) else None,
        }
        diagnostic = None
        if b"\x00" in decoded:
            diagnostic = "binary"
        else:
            try:
                text = decoded.decode("utf-8")
            except UnicodeDecodeError:
                diagnostic = "undecodable"
        if diagnostic:
            output.update({"kind": "binary", "diagnostic": diagnostic})
        else:
            output.update({"kind": "text", "content": text})
        return output

    def read_merge_request(self, project: str | int, iid: int) -> dict[str, Any]:
        project_endpoint = _project_endpoint(project)
        iid = _positive_bound(iid, 2_147_483_647)
        payload = _as_object(
            self.client.get_json(
                f"/api/v4/projects/{project_endpoint}/merge_requests/{iid}/changes"
            )
        )
        raw_changes = _as_list(payload.get("changes"))
        changes: list[dict[str, Any]] = []
        remaining = self.client.max_diff_bytes
        truncated = len(raw_changes) > self.client.max_changes
        for raw in raw_changes[: self.client.max_changes]:
            item = _as_object(raw)
            diff = item.get("diff")
            if not isinstance(diff, str):
                raise GitLabError("invalid_remote_data")
            encoded = diff.encode("utf-8")
            if len(encoded) > remaining:
                diff = encoded[:remaining].decode("utf-8", errors="ignore")
                truncated = True
            remaining -= len(diff.encode("utf-8"))
            projected = {"diff": diff}
            for field in ("old_path", "new_path"):
                value = item.get(field)
                if not isinstance(value, str) or len(value) > _MAX_PATH:
                    raise GitLabError("invalid_remote_data")
                projected[field] = value
            for field in ("new_file", "renamed_file", "deleted_file"):
                projected[field] = item.get(field) is True
            changes.append(projected)
            if remaining <= 0:
                truncated = truncated or len(changes) < len(raw_changes)
                break
        result = {
            "id": payload.get("id"),
            "iid": payload.get("iid"),
            "title": payload.get("title"),
            "state": payload.get("state"),
            "source_branch": payload.get("source_branch"),
            "target_branch": payload.get("target_branch"),
            "web_url": payload.get("web_url"),
            "changes": changes,
            "change_count": len(changes),
            "truncated": truncated,
            "warnings": ["merge_request_changes_truncated"] if truncated else [],
        }
        for field in ("id", "iid"):
            value = result[field]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise GitLabError("invalid_remote_data")
        if result["iid"] != iid:
            raise GitLabError("invalid_remote_data")
        for field in ("title", "state", "source_branch", "target_branch", "web_url"):
            if not isinstance(result[field], str) or len(result[field]) > _MAX_PROJECT_REFERENCE:
                raise GitLabError("invalid_remote_data")
        _same_origin_url(result["web_url"], self.client.auth.origin)
        return result

    def list_pipelines(
        self,
        project: str | int,
        *,
        ref: str | None = None,
        status: str | None = None,
        max_items: int = 50,
    ) -> dict[str, Any]:
        project_endpoint = _project_endpoint(project)
        max_items = _positive_bound(max_items, _MAX_PIPELINES)
        params: dict[str, Any] = {"order_by": "id", "sort": "desc"}
        if ref is not None:
            params["ref"] = _validate_ref(ref)
        if status is not None:
            params["status"] = _bounded_string(status, 64)

        def normalize(item: Mapping[str, Any]) -> dict[str, Any]:
            identifier = item.get("id")
            if isinstance(identifier, bool) or not isinstance(identifier, int):
                raise GitLabError("invalid_remote_data")
            projected: dict[str, Any] = {"id": identifier}
            iid = item.get("iid")
            if isinstance(iid, int) and not isinstance(iid, bool):
                projected["iid"] = iid
            for field in (
                "ref",
                "sha",
                "status",
                "source",
                "web_url",
                "created_at",
                "updated_at",
            ):
                value = item.get(field)
                if value is not None and (
                    not isinstance(value, str)
                    or len(value) > _MAX_PROJECT_REFERENCE
                ):
                    raise GitLabError("invalid_remote_data")
                projected[field] = value
            if projected.get("web_url") is not None:
                _same_origin_url(projected["web_url"], self.client.auth.origin)
            return projected

        pages = self._paginate(
            f"/api/v4/projects/{project_endpoint}/pipelines",
            params=params,
            max_items=max_items,
            normalize=normalize,
        )
        return {
            "project": str(project),
            "pipelines": list(pages.items),
            "count": len(pages.items),
            "truncated": pages.truncated,
            "continuation": {"next_page": pages.next_page} if pages.next_page else None,
        }
