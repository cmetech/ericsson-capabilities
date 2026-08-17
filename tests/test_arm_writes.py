"""Artifactory write operations: intent gating and checksum deploy."""

import hashlib
import importlib.util
import os
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-arm"
sys.path.insert(0, str(PLUGIN))

from _common.transport import Response  # noqa: E402
from models import ArmError  # noqa: E402
import operations as arm_operations  # noqa: E402
from operations import ArmOperations  # noqa: E402
import tools as arm_tools  # noqa: E402


def _is_arm_module(module: object) -> bool:
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, (str, Path)):
        return False
    try:
        return Path(module_file).resolve().is_relative_to(PLUGIN.resolve())
    except (OSError, ValueError):
        return False


def _detach_arm_standalone_imports() -> None:
    """Keep the ARM write test from shadowing sibling standalone plugins."""
    for name in ("auth", "client", "models", "operations", "tools"):
        module = sys.modules.get(name)
        if _is_arm_module(module):
            sys.modules.pop(name, None)
    for name in tuple(sys.modules):
        if (
            (name == "_common" or name.startswith("_common."))
            and _is_arm_module(sys.modules[name])
        ):
            sys.modules.pop(name, None)
    while str(PLUGIN) in sys.path:
        sys.path.remove(str(PLUGIN))


_detach_arm_standalone_imports()


class FakeClient:
    def __init__(self, json_results=None, raw_results=None, *, deploy_root=None,
                 max_deploy_bytes=1024 * 1024):
        self.json_results = list(json_results or [])
        self.raw_results = list(raw_results or [])
        self.calls = []

        class _Auth:
            pass

        self.auth = _Auth()
        self.auth.auth_header_value = "Bearer secret-token-value"
        self.auth.token = "secret-token-value"
        self.auth.default_max_results = 25
        self.auth.max_deploy_bytes = max_deploy_bytes
        self.auth.deploy_root = deploy_root
        self.path_prefix = "/artifactory/"

    def send(self, method, path, *, params=None, json_body=None, content=None,
             extra_headers=None, deadline=None, classify=True):
        body = content.read() if hasattr(content, "read") else content
        self.calls.append({
            "method": method, "path": path, "headers": dict(extra_headers or {}),
            "has_body": content is not None, "body": body, "classify": classify,
        })
        result = self.raw_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def checksum_probe(self, path, *, extra_headers=None, deadline=None):
        return self.send(
            "PUT", path, extra_headers=extra_headers, deadline=deadline, classify=False
        )


@pytest.fixture
def artifact(tmp_path):
    source = tmp_path / "oscar.tar.gz"
    payload = b"artifact-bytes" * 100
    source.write_bytes(payload)
    return source, {
        "md5": hashlib.md5(payload, usedforsecurity=False).hexdigest(),
        "sha1": hashlib.sha1(payload, usedforsecurity=False).hexdigest(),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _deployed(checksums, status=201):
    return Response(
        status, {},
        (
            '{"repo":"generic-local","path":"/Infra/a.tgz",'
            '"downloadUri":"https://artifactory.test/x",'
            f'"checksums":{{"md5":"{checksums["md5"]}",'
            f'"sha1":"{checksums["sha1"]}",'
            f'"sha256":"{checksums["sha256"]}"}}}}'
        ).encode(),
    )


class TestDeployIntent:
    def test_neither_flag_is_refused_without_a_request(self, artifact):
        source, _sums = artifact
        client = FakeClient()
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy("generic-local", "Infra/a.tgz", str(source))
        assert excinfo.value.category == "confirmation_required"
        assert client.calls == []

    def test_dry_run_reports_checksums_without_any_request(self, artifact):
        source, sums = artifact
        client = FakeClient()
        result = ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), dry_run=True
        )
        assert result["dry_run"] is True
        assert result["checksums"]["sha256"] == sums["sha256"]
        assert result["deduplicated"] is None
        assert client.calls == []


class TestChecksumDeploy:
    def test_checksum_deploy_sends_no_body_and_all_three_checksums(self, artifact):
        source, sums = artifact
        client = FakeClient(raw_results=[_deployed(sums)])
        result = ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), confirm=True
        )
        first = client.calls[0]
        assert first["method"] == "PUT"
        assert first["path"] == "/artifactory/generic-local/Infra/a.tgz"
        assert first["headers"]["X-Checksum-Deploy"] == "true"
        assert first["headers"]["X-Checksum-Sha256"] == sums["sha256"]
        assert first["headers"]["X-Checksum-Sha1"] == sums["sha1"]
        assert first["headers"]["X-Checksum-Md5"] == sums["md5"]
        assert first["has_body"] is False
        assert result["deduplicated"] is True
        assert result["bytes_uploaded"] == 0

    def test_only_one_request_when_the_blob_already_exists(self, artifact):
        source, sums = artifact
        client = FakeClient(raw_results=[_deployed(sums, status=200)])
        ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), confirm=True
        )
        assert len(client.calls) == 1

    def test_falls_back_to_a_full_upload(self, artifact):
        source, sums = artifact
        client = FakeClient(raw_results=[Response(404, {}, b""), _deployed(sums)])
        result = ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), confirm=True
        )
        assert len(client.calls) == 2
        second = client.calls[1]
        assert second["has_body"] is True
        assert "X-Checksum-Deploy" not in second["headers"]
        assert second["headers"]["X-Checksum-Sha256"] == sums["sha256"]
        assert second["headers"]["X-Checksum-Sha1"] == sums["sha1"]
        assert second["headers"]["X-Checksum-Md5"] == sums["md5"]
        assert result["deduplicated"] is False
        assert result["bytes_uploaded"] == source.stat().st_size

    @pytest.mark.parametrize("status", [302, 503])
    def test_any_received_probe_status_falls_back_to_a_full_upload(self, artifact, status):
        source, sums = artifact
        client = FakeClient(raw_results=[Response(status, {}, b""), _deployed(sums)])
        result = ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), confirm=True
        )
        assert [call["method"] for call in client.calls] == ["PUT", "PUT"]
        assert client.calls[0]["classify"] is False
        assert client.calls[1]["classify"] is True
        assert result["deduplicated"] is False

    def test_probe_transport_failure_does_not_fall_back(self, artifact):
        source, _sums = artifact
        client = FakeClient(raw_results=[ArmError("write_ambiguous")])
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(source), confirm=True
            )
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1

    def test_the_probe_does_not_classify_its_response(self, artifact):
        source, sums = artifact
        client = FakeClient(raw_results=[Response(404, {}, b""), _deployed(sums)])
        ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), confirm=True
        )
        assert client.calls[0]["classify"] is False
        assert client.calls[1]["classify"] is True

    def test_a_checksum_mismatch_in_the_response_is_an_error(self, artifact):
        source, _sums = artifact
        wrong = {"md5": "0" * 32, "sha1": "0" * 40, "sha256": "0" * 64}
        client = FakeClient(raw_results=[_deployed(wrong)])
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(source), confirm=True
            )
        assert excinfo.value.category == "invalid_remote_data"
        assert "checksum" in (excinfo.value.remediation or "").lower()

    def test_a_response_without_checksums_is_an_error(self, artifact):
        source, _sums = artifact
        client = FakeClient(raw_results=[Response(201, {}, b'{"repo":"x"}')])
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(source), confirm=True
            )
        assert excinfo.value.category == "invalid_remote_data"


class TestDeploySource:
    def test_a_relative_path_is_rejected(self, artifact):
        client = FakeClient()
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", "./oscar.tar.gz", confirm=True
            )
        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_a_missing_file_is_rejected(self, tmp_path):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(tmp_path / "absent"), confirm=True
            )
        assert client.calls == []

    def test_a_directory_is_rejected(self, tmp_path):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(tmp_path), confirm=True
            )
        assert client.calls == []

    def test_a_file_over_the_size_bound_is_rejected(self, artifact):
        source, _sums = artifact
        client = FakeClient(max_deploy_bytes=10)
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(source), confirm=True
            )
        assert excinfo.value.category == "capacity"
        assert client.calls == []

    def test_deploy_root_confines_the_source(self, artifact, tmp_path):
        source, _sums = artifact
        other = tmp_path / "elsewhere"
        other.mkdir()
        client = FakeClient(deploy_root=str(other))
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(source), confirm=True
            )
        assert excinfo.value.category == "permission"
        assert client.calls == []

    def test_a_symlink_escaping_deploy_root_is_rejected(self, artifact, tmp_path):
        source, _sums = artifact
        root = tmp_path / "allowed"
        root.mkdir()
        link = root / "sneaky.tar.gz"
        link.symlink_to(source)
        client = FakeClient(deploy_root=str(root))
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(link), confirm=True
            )
        assert excinfo.value.category == "permission"

    def test_a_source_inside_deploy_root_is_allowed(self, tmp_path):
        root = tmp_path / "allowed"
        root.mkdir()
        source = root / "oscar.tar.gz"
        source.write_bytes(b"bytes")
        sums = {
            "md5": hashlib.md5(b"bytes", usedforsecurity=False).hexdigest(),
            "sha1": hashlib.sha1(b"bytes", usedforsecurity=False).hexdigest(),
            "sha256": hashlib.sha256(b"bytes").hexdigest(),
        }
        client = FakeClient(raw_results=[_deployed(sums)], deploy_root=str(root))
        result = ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), confirm=True
        )
        assert result["ok"] is True

    def test_open_descriptor_is_uploaded_after_source_becomes_an_escape_symlink(
        self, monkeypatch, tmp_path
    ):
        root = tmp_path / "allowed"
        root.mkdir()
        source = root / "archive.tgz"
        original = b"inside-root"
        source.write_bytes(original)
        outside = tmp_path / "outside.tgz"
        outside.write_bytes(b"outside-root" * 100)
        sums = {
            "md5": hashlib.md5(original, usedforsecurity=False).hexdigest(),
            "sha1": hashlib.sha1(original, usedforsecurity=False).hexdigest(),
            "sha256": hashlib.sha256(original).hexdigest(),
        }
        client = FakeClient(raw_results=[Response(404, {}, b""), _deployed(sums)], deploy_root=str(root), max_deploy_bytes=64)
        original_checksums = ArmOperations._file_checksums

        def replace_path_then_hash(handle, maximum_bytes):
            source.unlink()
            source.symlink_to(outside)
            return original_checksums(handle, maximum_bytes)

        monkeypatch.setattr(ArmOperations, "_file_checksums", staticmethod(replace_path_then_hash))
        ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), confirm=True
        )
        assert client.calls[1]["body"] == original

    def test_path_replacement_before_open_is_rejected_without_upload(
        self, monkeypatch, tmp_path
    ):
        root = tmp_path / "allowed"
        root.mkdir()
        source = root / "archive.tgz"
        source.write_bytes(b"inside-root")
        replacement = root / "replacement.tgz"
        replacement.write_bytes(b"replacement")
        client = FakeClient(deploy_root=str(root))
        original_open = os.open

        def replace_then_open(path, flags):
            os.replace(replacement, source)
            return original_open(path, flags)

        monkeypatch.setattr(arm_operations.os, "open", replace_then_open)
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(source), confirm=True
            )
        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_ancestor_symlink_replacement_is_rejected_before_any_upload(
        self, monkeypatch, tmp_path
    ):
        root = tmp_path / "allowed"
        nested = root / "nested"
        nested.mkdir(parents=True)
        source = nested / "archive.tgz"
        source.write_bytes(b"inside-root")
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "archive.tgz").write_bytes(b"outside-root")
        replacement = root / "nested-original"
        client = FakeClient(deploy_root=str(root))
        original_open = os.open

        def replace_ancestor(path, flags, *args, **kwargs):
            if path == "nested":
                os.replace(nested, replacement)
                nested.symlink_to(outside, target_is_directory=True)
            return original_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(arm_operations.os, "open", replace_ancestor)
        monkeypatch.setattr(ArmOperations, "_supports_secure_open", staticmethod(lambda: True))
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(source), confirm=True
            )
        assert excinfo.value.category in {"invalid_input", "permission"}
        assert client.calls == []

    def test_growth_after_fstat_hits_the_byte_cap_before_any_request(
        self, monkeypatch, tmp_path
    ):
        source = tmp_path / "archive.tgz"
        source.write_bytes(b"small")
        client = FakeClient(max_deploy_bytes=8)
        original_fstat = os.fstat
        appended = False

        def append_after_fstat(fd):
            nonlocal appended
            result = original_fstat(fd)
            if not appended:
                appended = True
                with source.open("ab") as handle:
                    handle.write(b"growth-beyond-limit")
            return result

        monkeypatch.setattr(arm_operations.os, "fstat", append_after_fstat)
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(source), confirm=True
            )
        assert excinfo.value.category == "capacity"
        assert client.calls == []

    def test_growth_after_hash_is_not_read_or_uploaded(self, tmp_path):
        source = tmp_path / "archive.tgz"
        original = b"hashed-bytes"
        source.write_bytes(original)
        sums = {
            "md5": hashlib.md5(original, usedforsecurity=False).hexdigest(),
            "sha1": hashlib.sha1(original, usedforsecurity=False).hexdigest(),
            "sha256": hashlib.sha256(original).hexdigest(),
        }
        client = FakeClient(raw_results=[Response(404, {}, b""), _deployed(sums)])
        original_probe = client.checksum_probe

        def append_after_hash(*args, **kwargs):
            with source.open("ab") as handle:
                handle.write(b"must-not-be-uploaded")
            return original_probe(*args, **kwargs)

        client.checksum_probe = append_after_hash
        result = ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), confirm=True
        )
        assert result["size"] == len(original)
        assert client.calls[1]["body"] == original

    def test_download_uri_redacts_a_token_split_at_the_output_bound(self, artifact):
        source, sums = artifact
        uri = "x" * 2044 + "Bearer secret-token-value"
        response = Response(
            201,
            {},
            (
                '{"repo":"generic-local","path":"/Infra/a.tgz",'
                f'"downloadUri":"{uri}",'
                f'"checksums":{{"sha256":"{sums["sha256"]}"}}}}'
            ).encode(),
        )
        result = ArmOperations(FakeClient(raw_results=[response])).deploy(
            "generic-local", "Infra/a.tgz", str(source), confirm=True
        )
        assert "secret-token-value" not in result["download_uri"]
        assert "Bearer" not in result["download_uri"]


def _load_plugin():
    spec = importlib.util.spec_from_file_location("arm_deploy_plugin", PLUGIN / "__init__.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _HookContext:
    def __init__(self):
        self.hook = None

    def register_hook(self, _event, hook):
        self.hook = hook


class TestDeployToolWiring:
    def test_schema_invoke_and_approval_are_bound_to_the_source_path(self, monkeypatch):
        schema = arm_tools.SCHEMAS["arm_deploy"]["parameters"]
        assert schema["required"] == ["repo", "path", "source_file"]
        assert schema["properties"]["source_file"]["maxLength"] == 4096
        assert not {"approved", "tool_admission"} & set(schema["properties"])

        calls = []

        class Operations:
            class Client:
                def close(self):
                    pass

            client = Client()

            def deploy(self, *args, **kwargs):
                calls.append((args, kwargs))
                return {"ok": True}

        monkeypatch.setattr(arm_tools, "operations_from_configuration", lambda *_a, **_k: Operations())
        assert arm_tools.invoke(
            "arm_deploy",
            {"repo": "generic-local", "path": "Infra/a.tgz", "source_file": "/tmp/a.tgz", "confirm": True},
            object(),
        ) == {"ok": True}
        assert calls == [
            (("generic-local", "Infra/a.tgz", "/tmp/a.tgz"), {"dry_run": False, "confirm": True})
        ]

        plugin = _load_plugin()
        context = _HookContext()
        plugin.register(context)
        first = context.hook(
            "arm_deploy",
            {"repo": "generic-local", "path": "Infra/a.tgz", "source_file": "/tmp/a.tgz", "confirm": True},
        )
        second = context.hook(
            "arm_deploy",
            {"repo": "generic-local", "path": "Infra/a.tgz", "source_file": "/tmp/b.tgz", "confirm": True},
        )
        assert first["action"] == second["action"] == "approve"
        assert first["message"].splitlines()[1] == 'Upload file: "/tmp/a.tgz"'
        assert first["rule_key"] != second["rule_key"]
        assert context.hook("arm_artifact_info", {}) is None
