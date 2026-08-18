"""MSAL device-code auth for Microsoft Graph (Teams tools).

- Public client (Azure CLI's well-known client id — no app registration),
  scope https://graph.microsoft.com/.default, authority organizations.
- Serializable token cache at $HERMES_HOME/ericsson/msal_token_cache.json.
- msal is imported LAZILY so the plugin loads even if msal is absent.
- Device flow is two-step for chat UX: start_device_flow() returns the code
  message immediately (module-level pending flow survives because the plugin
  lives in the persistent Hermes process); complete_device_flow() polls.
"""
from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path
from typing import Callable, NamedTuple

CLIENT_ID = os.environ.get("ERICSSON_GRAPH_CLIENT_ID",
                           "04b07795-8ddb-461a-bbee-02f9e1bf7b46")  # Azure CLI public client
AUTHORITY = "https://login.microsoftonline.com/organizations"
SCOPES = ["https://graph.microsoft.com/.default"]

_PENDING_FLOW = None
_MAX_CACHE_BYTES = 16 * 1024 * 1024


class _WindowsAclApi(NamedTuple):
    restrict_directory_to_current_user: Callable[[Path], object]
    inspect_directory_acl: Callable[[Path], object]
    restrict_file_to_current_user: Callable[[Path], object]
    inspect_file_acl: Callable[[Path], object]


class AuthRequired(RuntimeError):
    pass


def cache_path() -> Path:
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    return home / "ericsson" / "msal_token_cache.json"


def _platform_name() -> str:
    return os.name


def _windows_acl_api() -> _WindowsAclApi:
    from hermes_cli.windows_permissions import (
        inspect_directory_acl,
        inspect_file_acl,
        restrict_directory_to_current_user,
        restrict_file_to_current_user,
    )

    return _WindowsAclApi(
        restrict_directory_to_current_user=restrict_directory_to_current_user,
        inspect_directory_acl=inspect_directory_acl,
        restrict_file_to_current_user=restrict_file_to_current_user,
        inspect_file_acl=inspect_file_acl,
    )


def _app():
    import msal
    cache = msal.SerializableTokenCache()
    serialized = _read_cache_text()
    if serialized is not None:
        cache.deserialize(serialized)
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY,
                                        token_cache=cache)
    return app, cache


def _read_cache_text() -> str | None:
    try:
        platform = _platform_name()
        if platform == "posix":
            return _read_cache_posix()
        if platform == "nt":
            return _read_cache_windows()
        path = cache_path()
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
    except (OSError, UnicodeError, ValueError):
        raise AuthRequired(
            "could not read the Microsoft Graph sign-in cache securely"
        ) from None


def _load_windows_acl_api() -> _WindowsAclApi:
    try:
        return _windows_acl_api()
    except Exception as error:
        raise OSError("Windows ACL host API is unavailable") from error


def _validate_windows_path(path: Path, opened, *, directory: bool) -> None:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(opened, "st_file_attributes", 0)
    if stat.S_ISLNK(opened.st_mode) or attributes & reparse_flag:
        raise OSError("cache path is a reparse point")
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_type(opened.st_mode):
        kind = "directory" if directory else "regular file"
        raise OSError(f"cache path is not a {kind}")


def _snapshot_windows_path(path: Path, *, directory: bool):
    opened = path.lstat()
    _validate_windows_path(path, opened, directory=directory)
    return opened


def _require_same_windows_identity(expected, actual) -> None:
    try:
        same = os.path.samestat(expected, actual)
    except (AttributeError, OSError, TypeError) as error:
        raise OSError("could not verify cache path identity") from error
    if not same:
        raise OSError("cache path identity changed")


def _protect_windows_directory(api: _WindowsAclApi, path: Path):
    before = _snapshot_windows_path(path, directory=True)
    try:
        api.restrict_directory_to_current_user(path)
        inspection = api.inspect_directory_acl(path)
        if not inspection.secure:
            raise OSError("cache directory ACL is not private")
    except Exception as error:
        raise OSError("could not protect cache directory") from error
    after = _snapshot_windows_path(path, directory=True)
    _require_same_windows_identity(before, after)
    return after


def _protect_windows_file(api: _WindowsAclApi, path: Path):
    before = _snapshot_windows_path(path, directory=False)
    try:
        api.restrict_file_to_current_user(path)
        inspection = api.inspect_file_acl(path)
        if not inspection.secure:
            raise OSError("cache file ACL is not private")
    except Exception as error:
        raise OSError("could not protect cache file") from error
    after = _snapshot_windows_path(path, directory=False)
    _require_same_windows_identity(before, after)
    return after


def _read_cache_windows() -> str | None:
    path = cache_path()
    try:
        path.parent.lstat()
    except FileNotFoundError:
        return None
    api = _load_windows_acl_api()
    parent_identity = _protect_windows_directory(api, path.parent)
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    file_identity = _protect_windows_file(api, path)
    _require_same_windows_identity(
        parent_identity,
        _snapshot_windows_path(path.parent, directory=True),
    )

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        opened = os.fstat(descriptor)
        _validate_windows_path(path, opened, directory=False)
        _require_same_windows_identity(file_identity, opened)
        _require_same_windows_identity(
            file_identity,
            _snapshot_windows_path(path, directory=False),
        )
        _require_same_windows_identity(
            parent_identity,
            _snapshot_windows_path(path.parent, directory=True),
        )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_CACHE_BYTES:
                raise ValueError("cache is too large")
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_cache_posix() -> str | None:
    path = cache_path()
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("secure no-follow opens are unavailable")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | nofollow
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        directory_fd = os.open(path.parent, directory_flags)
    except FileNotFoundError:
        return None
    descriptor: int | None = None
    try:
        directory_stat = os.fstat(directory_fd)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise OSError("cache parent is not a directory")
        if directory_stat.st_uid != os.geteuid():  # windows-footgun: ok — POSIX-only path (see os.name guards above)
            raise OSError("cache parent is not owned by the current user")
        os.fchmod(directory_fd, 0o700)
        if stat.S_IMODE(os.fstat(directory_fd).st_mode) != 0o700:
            raise OSError("cache parent permissions are not private")
        file_flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(path.name, file_flags, dir_fd=directory_fd)
        except FileNotFoundError:
            return None
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError("cache destination is not a regular file")
        if opened.st_uid != os.geteuid():  # windows-footgun: ok — POSIX-only path (see os.name guards above)
            raise OSError("cache destination is not owned by the current user")
        os.fchmod(descriptor, 0o600)
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600:
            raise OSError("cache permissions are not private")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_CACHE_BYTES:
                raise ValueError("cache is too large")
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory_fd)


def _persist(cache) -> None:
    if not cache.has_state_changed:
        return
    try:
        serialized = cache.serialize().encode("utf-8")
        platform = _platform_name()
        if platform == "posix":
            _persist_posix(serialized)
        elif platform == "nt":
            _persist_windows(serialized)
        else:
            _persist_portable(serialized)
    except (OSError, UnicodeError, TypeError, ValueError):
        raise AuthRequired(
            "could not store the Microsoft Graph sign-in cache securely"
        ) from None


def _persist_windows(serialized: bytes) -> None:
    """Atomically publish a cache protected by the host's Windows ACL API."""
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    api = _load_windows_acl_api()
    parent_identity = _protect_windows_directory(api, path.parent)
    try:
        destination = path.lstat()
    except FileNotFoundError:
        destination = None
    if destination is not None:
        _validate_windows_path(path, destination, directory=False)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    temporary: Path | None = None
    descriptor: int | None = None
    try:
        for _ in range(8):
            candidate = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
            try:
                descriptor = os.open(candidate, flags, 0o600)
            except FileExistsError:
                continue
            temporary = candidate
            break
        if descriptor is None or temporary is None:
            raise OSError("could not reserve a cache temporary file")

        opened_identity = os.fstat(descriptor)
        _validate_windows_path(temporary, opened_identity, directory=False)
        _require_same_windows_identity(
            parent_identity,
            _snapshot_windows_path(path.parent, directory=True),
        )
        temporary_identity = _protect_windows_file(api, temporary)
        _require_same_windows_identity(temporary_identity, opened_identity)
        _require_same_windows_identity(temporary_identity, os.fstat(descriptor))
        _require_same_windows_identity(
            parent_identity,
            _snapshot_windows_path(path.parent, directory=True),
        )
        view = memoryview(serialized)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short cache write")
            view = view[written:]
        os.fsync(descriptor)
        temporary_identity = os.fstat(descriptor)
        _validate_windows_path(temporary, temporary_identity, directory=False)
        _require_same_windows_identity(
            temporary_identity,
            _snapshot_windows_path(temporary, directory=False),
        )
        _require_same_windows_identity(
            parent_identity,
            _snapshot_windows_path(path.parent, directory=True),
        )
        os.close(descriptor)
        descriptor = None

        os.replace(temporary, path)
        final_identity = _snapshot_windows_path(path, directory=False)
        _require_same_windows_identity(temporary_identity, final_identity)
        _require_same_windows_identity(
            parent_identity,
            _snapshot_windows_path(path.parent, directory=True),
        )
        protected_final_identity = _protect_windows_file(api, path)
        _require_same_windows_identity(temporary_identity, protected_final_identity)
        _require_same_windows_identity(
            parent_identity,
            _snapshot_windows_path(path.parent, directory=True),
        )
        temporary = None
    finally:
        cleanup_error: OSError | None = None
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as error:
                cleanup_error = error
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError as error:
                if cleanup_error is None:
                    cleanup_error = error
        if cleanup_error is not None:
            raise cleanup_error


def _persist_posix(serialized: bytes) -> None:
    """Atomically replace the cache through a private, no-follow directory."""
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("secure no-follow opens are unavailable")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | nofollow
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    directory_fd = os.open(path.parent, directory_flags)
    temporary_name: str | None = None
    temporary_fd: int | None = None
    try:
        directory_stat = os.fstat(directory_fd)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise OSError("cache parent is not a directory")
        if directory_stat.st_uid != os.geteuid():  # windows-footgun: ok — POSIX-only path (see os.name guards above)
            raise OSError("cache parent is not owned by the current user")
        os.fchmod(directory_fd, 0o700)
        if stat.S_IMODE(os.fstat(directory_fd).st_mode) != 0o700:
            raise OSError("cache parent permissions are not private")

        try:
            current = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            current = None
        if current is not None and not stat.S_ISREG(current.st_mode):
            raise OSError("cache destination is not a regular file")

        file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow
        file_flags |= getattr(os, "O_CLOEXEC", 0)
        for _ in range(8):
            candidate = f".{path.name}.{secrets.token_hex(8)}.tmp"
            try:
                temporary_fd = os.open(
                    candidate, file_flags, 0o600, dir_fd=directory_fd
                )
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        if temporary_fd is None or temporary_name is None:
            raise OSError("could not reserve a private cache temporary file")

        view = memoryview(serialized)
        while view:
            written = os.write(temporary_fd, view)
            if written <= 0:
                raise OSError("short cache write")
            view = view[written:]
        os.fchmod(temporary_fd, 0o600)
        temporary_stat = os.fstat(temporary_fd)
        if not stat.S_ISREG(temporary_stat.st_mode):
            raise OSError("cache temporary is not a regular file")
        if temporary_stat.st_uid != os.geteuid():  # windows-footgun: ok — POSIX-only path (see os.name guards above)
            raise OSError("cache temporary is not owned by the current user")
        if stat.S_IMODE(temporary_stat.st_mode) != 0o600:
            raise OSError("cache temporary permissions are not private")
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None

        os.replace(
            temporary_name,
            path.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_name = None
        os.fsync(directory_fd)
    finally:
        if temporary_fd is not None:
            os.close(temporary_fd)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def _persist_portable(serialized: bytes) -> None:
    """Keep atomic replacement semantics on Windows using native path APIs."""
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        view = memoryview(serialized)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short cache write")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def get_token() -> str:
    """Silent token from cache. Raises AuthRequired with next-step guidance."""
    if not cache_path().exists():
        raise AuthRequired("Not signed in to Microsoft Graph — run the "
                           "teams_auth tool to sign in with a device code.")
    app, cache = _app()
    accounts = app.get_accounts()
    result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
    _persist(cache)
    if not result or "access_token" not in result:
        raise AuthRequired("Graph session expired — run the teams_auth tool "
                           "to sign in again.")
    return result["access_token"]


def start_device_flow() -> dict:
    global _PENDING_FLOW
    app, _cache = _app()
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise AuthRequired(f"could not start device flow: {flow.get('error_description', flow)}")
    _PENDING_FLOW = (app, _cache, flow)
    return {"message": flow["message"], "verification_uri": flow["verification_uri"],
            "user_code": flow["user_code"]}


def complete_device_flow() -> dict:
    global _PENDING_FLOW
    if _PENDING_FLOW is None:
        raise AuthRequired("no device flow in progress — call teams_auth first")
    app, cache, flow = _PENDING_FLOW
    flow["expires_at"] = 0  # poll once; the tool is re-invoked to retry
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        _persist(cache)
        _PENDING_FLOW = None
        return {"ok": True, "account": result.get("id_token_claims", {}).get("preferred_username")}
    err = result.get("error")
    if err in ("authorization_pending", "slow_down"):
        return {"ok": False, "pending": True,
                "detail": result.get("error_description", "authorization pending — "
                                     "finish signing in, then run teams_auth complete again")}
    _PENDING_FLOW = None
    return {"ok": False, "pending": False,
            "error": result.get("error_description") or err or "device flow failed",
            "hint": "run teams_auth again to restart sign-in"}
