from __future__ import annotations

import dataclasses
import importlib.util
import sys
import uuid
from collections import Counter
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-connector-cli"

EXPECTED_COMMANDS = {
    ("jira", "issue", "mine"): "jira_my_tickets",
    ("jira", "issue", "search"): "jira_search_issues",
    ("jira", "issue", "get"): "jira_get_issue",
    ("jira", "issue", "comment"): "jira_add_comment",
    ("jira", "field", "list"): "jira_list_fields",
    ("jira", "project", "get"): "jira_get_project",
    ("jira", "transition", "list"): "jira_list_transitions",
    ("jira", "user", "search-assignable"): "jira_search_assignable_users",
    ("jira", "issue", "transition"): "jira_transition_issue",
    ("jira", "issue", "assign"): "jira_assign_issue",
    ("jira", "issue", "update"): "jira_update_fields",
    ("jira", "issue", "label"): "jira_manage_labels",
    ("jira", "issue", "create"): "jira_create_issue",
    ("jira", "link-type", "list"): "jira_list_link_types",
    ("jira", "issue", "link"): "jira_link_issues",
    ("gitlab", "project", "resolve"): "gitlab_resolve_project",
    ("gitlab", "group", "project-list"): "gitlab_list_group_projects",
    ("gitlab", "commit", "list"): "gitlab_list_commits",
    ("gitlab", "commit", "show"): "gitlab_read_commit",
    ("gitlab", "commit", "comment-list"): "gitlab_list_commit_comments",
    ("gitlab", "commit", "discussion-list"): "gitlab_list_commit_discussions",
    ("gitlab", "mr", "list"): "gitlab_list_merge_requests",
    ("gitlab", "mr", "commit-list"): "gitlab_list_merge_request_commits",
    ("gitlab", "mr", "discussion-list"): "gitlab_list_merge_request_discussions",
    ("gitlab", "repository", "tree"): "gitlab_list_repository_tree",
    ("gitlab", "file", "show"): "gitlab_read_file",
    ("gitlab", "mr", "show"): "gitlab_read_merge_request",
    ("gitlab", "pipeline", "list"): "gitlab_list_pipelines",
    ("gitlab", "pipeline", "view"): "gitlab_read_pipeline",
    ("gitlab", "ci", "inspect"): "gitlab_inspect_ci",
    ("gitlab", "branch", "create"): "gitlab_create_named_branch",
    ("gitlab", "branch", "create-ticket"): "gitlab_create_branch",
    ("gitlab", "commit", "create"): "gitlab_commit_changes",
    ("gitlab", "mr", "create"): "gitlab_create_merge_request",
    ("gitlab", "job", "log"): "gitlab_job_log",
    ("gitlab", "mr", "note"): "gitlab_create_mr_note",
    ("gitlab", "mr", "discussion-reply"): "gitlab_reply_to_discussion",
    ("gitlab", "mr", "discussion-resolve"): "gitlab_resolve_discussion",
    ("gitlab", "mr", "approval-show"): "gitlab_merge_request_approvals",
    ("gitlab", "mr", "approve"): "gitlab_approve_merge_request",
    ("gitlab", "mr", "merge"): "gitlab_merge_merge_request",
    ("gitlab", "mr", "update"): "gitlab_update_merge_request",
    ("gitlab", "job", "play"): "gitlab_play_job",
    ("gitlab", "job", "retry"): "gitlab_retry_job",
    ("gitlab", "pipeline", "retry"): "gitlab_retry_pipeline",
    ("confluence", "space", "list"): "confluence_list_spaces",
    ("confluence", "page", "search"): "confluence_search",
    ("confluence", "page", "get"): "confluence_get_page",
    ("confluence", "page", "body"): "confluence_get_page_body",
    ("confluence", "page", "child-list"): "confluence_list_children",
    ("confluence", "page", "comment-list"): "confluence_list_comments",
    ("confluence", "page", "create"): "confluence_create_page",
    ("confluence", "page", "update"): "confluence_update_page",
    ("confluence", "page", "comment"): "confluence_add_comment",
    ("arm", "repository", "list"): "arm_list_repositories",
    ("arm", "artifact", "info"): "arm_artifact_info",
    ("arm", "artifact", "properties"): "arm_get_properties",
    ("arm", "artifact", "search"): "arm_search_artifacts",
    ("arm", "artifact", "deploy"): "arm_deploy",
    ("arm", "artifact", "delete"): "arm_delete",
}
CONNECTORS = {
    "jira": "ericsson-jira",
    "gitlab": "ericsson-gitlab",
    "confluence": "ericsson-confluence",
    "arm": "ericsson-arm",
}


def _load_module(path: Path, name: str, *, package: bool = False):
    module_name = f"connector_cli_{name}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
        submodule_search_locations=[str(path.parent)] if package else None,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def descriptors_module():
    return _load_module(PLUGIN / "descriptors.py", "descriptors")


@pytest.fixture(scope="module")
def live_connectors():
    loaded = {}
    for family, connector_id in CONNECTORS.items():
        root = REPO / "plugins" / connector_id
        package = _load_module(root / "__init__.py", family, package=True)
        loaded[connector_id] = (
            getattr(package, f"{family}_tools").SCHEMAS,
            package._WRITE_TOOLS,
        )
    return loaded


def test_descriptor_values_are_frozen_and_declare_complete_contract(descriptors_module):
    descriptors = descriptors_module.DESCRIPTORS
    assert descriptors
    assert all(dataclasses.is_dataclass(value) for value in descriptors)
    with pytest.raises(dataclasses.FrozenInstanceError):
        descriptors[0].operation = "changed"
    with pytest.raises(dataclasses.FrozenInstanceError):
        descriptors[1].option_bindings[0].required = False
    with pytest.raises(dataclasses.FrozenInstanceError):
        descriptors[0].option_bindings[0].schema_contract.maximum = 101

    for descriptor in descriptors:
        assert descriptor.connector_id in CONNECTORS.values()
        assert isinstance(descriptor.path_tokens, tuple) and descriptor.path_tokens
        assert descriptor.operation
        assert descriptor.access in {"read", "write"}
        assert isinstance(descriptor.positional_bindings, tuple)
        assert isinstance(descriptor.option_bindings, tuple)
        assert isinstance(descriptor.file_bindings, tuple)
        assert descriptor.render_hint
        for binding in descriptor.positional_bindings:
            assert binding.source == "positional"
        for binding in descriptor.option_bindings:
            assert binding.source == "option"
        for binding in descriptor.file_bindings:
            assert binding.source in {"body_file", "local_file"}
        for binding in (
            descriptor.positional_bindings
            + descriptor.option_bindings
            + descriptor.file_bindings
        ):
            assert binding.public_name
            assert binding.target_schema_property
            assert isinstance(binding.required, bool)
            assert isinstance(binding.repeatable, bool)
            assert binding.value_type
            assert isinstance(binding.choices, tuple)
            assert binding.mutually_exclusive_group is None or isinstance(
                binding.mutually_exclusive_group, str
            )
            assert isinstance(binding.mutually_exclusive_group_required, bool)
            if binding.mutually_exclusive_group is None:
                assert binding.mutually_exclusive_group_required is False


def test_descriptor_table_is_the_exact_unique_60_command_contract(descriptors_module):
    descriptors = descriptors_module.DESCRIPTORS
    by_path = {descriptor.path_tokens: descriptor.operation for descriptor in descriptors}

    assert len(descriptors) == len(EXPECTED_COMMANDS) == 60
    assert by_path == EXPECTED_COMMANDS
    assert len({descriptor.operation for descriptor in descriptors}) == 60
    assert {descriptor.path_tokens[0] for descriptor in descriptors} == set(CONNECTORS)
    assert Counter(descriptor.path_tokens[0] for descriptor in descriptors) == {
        "jira": 15,
        "gitlab": 30,
        "confluence": 9,
        "arm": 6,
    }


def test_descriptor_bindings_and_access_match_live_connector_contracts(
    descriptors_module, live_connectors
):
    for connector_id, (schemas, _writes) in live_connectors.items():
        assert {
            descriptor.operation
            for descriptor in descriptors_module.DESCRIPTORS
            if descriptor.connector_id == connector_id
        } == set(schemas)

    for descriptor in descriptors_module.DESCRIPTORS:
        schemas, writes = live_connectors[descriptor.connector_id]
        parameters = schemas[descriptor.operation]["parameters"]
        expected = set(parameters.get("properties", {}))
        if descriptor.operation in writes:
            expected -= {"dry_run", "confirm"}
        bindings = (
            descriptor.positional_bindings
            + descriptor.option_bindings
            + descriptor.file_bindings
        )
        actual = {binding.target_schema_property for binding in bindings}
        assert actual == expected, descriptor.operation
        required = set(parameters.get("required", [])) - {"dry_run", "confirm"}
        required_targets = {
            binding.target_schema_property
            for binding in bindings
            if binding.required or binding.mutually_exclusive_group_required
        }
        assert required <= required_targets, descriptor.operation
        assert descriptor.access == (
            "write" if descriptor.operation in writes else "read"
        )
        for binding in bindings:
            property_schema = parameters["properties"][
                binding.target_schema_property
            ]
            enum = property_schema.get("enum")
            if property_schema.get("type") == "array":
                enum = property_schema.get("items", {}).get("enum")
            assert binding.choices == tuple(enum or ()), (
                descriptor.operation,
                binding.public_name,
            )


def test_descriptor_validation_bounds_exactly_match_expanded_live_schemas(
    descriptors_module, live_connectors
):
    metadata_fields = (
        "minimum",
        "maximum",
        "min_length",
        "max_length",
        "pattern",
        "min_items",
        "max_items",
        "min_properties",
        "max_properties",
        "item_minimum",
        "item_maximum",
        "item_min_length",
        "item_max_length",
        "item_pattern",
    )
    for descriptor in descriptors_module.DESCRIPTORS:
        schemas, _writes = live_connectors[descriptor.connector_id]
        properties = schemas[descriptor.operation]["parameters"].get(
            "properties", {}
        )
        for binding in (
            descriptor.positional_bindings
            + descriptor.option_bindings
            + descriptor.file_bindings
        ):
            expected = _expanded_bounds(properties[binding.target_schema_property])
            actual = {
                field: getattr(binding, field) for field in metadata_fields
            }
            assert actual == expected, (
                descriptor.operation,
                binding.public_name,
            )


def test_recursive_binding_schema_contract_exactly_matches_live_properties(
    descriptors_module, live_connectors
):
    for descriptor in descriptors_module.DESCRIPTORS:
        schemas, _writes = live_connectors[descriptor.connector_id]
        properties = schemas[descriptor.operation]["parameters"].get(
            "properties", {}
        )
        for binding in (
            descriptor.positional_bindings
            + descriptor.option_bindings
            + descriptor.file_bindings
        ):
            expected = _live_schema_contract(
                descriptors_module,
                properties[binding.target_schema_property],
            )
            assert binding.schema_contract == expected, (
                descriptor.operation,
                binding.public_name,
            )
            assert _value_type_is_compatible(binding, expected), (
                descriptor.operation,
                binding.public_name,
                binding.value_type,
            )


def _live_schema_contract(descriptors_module, schema):
    known = {
        "type",
        "description",
        "default",
        "enum",
        "oneOf",
        "anyOf",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "minProperties",
        "maxProperties",
    }
    assert set(schema) <= known, set(schema) - known
    raw_type = schema.get("type", ())
    types = (raw_type,) if isinstance(raw_type, str) else tuple(raw_type)
    properties = tuple(
        sorted(
            (
                name,
                _live_schema_contract(descriptors_module, subschema),
            )
            for name, subschema in schema.get("properties", {}).items()
        )
    )
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        additional = _live_schema_contract(descriptors_module, additional)
    return descriptors_module.SchemaContract(
        types=types,
        description=schema.get("description"),
        has_default="default" in schema,
        default=schema.get("default"),
        enum=tuple(schema.get("enum", ())),
        one_of=tuple(
            _live_schema_contract(descriptors_module, item)
            for item in schema.get("oneOf", ())
        ),
        any_of=tuple(
            _live_schema_contract(descriptors_module, item)
            for item in schema.get("anyOf", ())
        ),
        properties=properties,
        required=tuple(schema.get("required", ())),
        additional_properties=additional,
        items=(
            _live_schema_contract(descriptors_module, schema["items"])
            if "items" in schema
            else None
        ),
        minimum=schema.get("minimum"),
        maximum=schema.get("maximum"),
        min_length=schema.get("minLength"),
        max_length=schema.get("maxLength"),
        pattern=schema.get("pattern"),
        min_items=schema.get("minItems"),
        max_items=schema.get("maxItems"),
        min_properties=schema.get("minProperties"),
        max_properties=schema.get("maxProperties"),
    )


def _value_type_is_compatible(binding, contract):
    accepted = set(contract.types)
    for alternative in contract.one_of + contract.any_of:
        accepted.update(alternative.types)
    expected = {
        "boolean": {"boolean"},
        "integer": {"integer"},
        "nullable_string": {"null", "string"},
        "string_or_integer": {"integer", "string"},
        "continuation": {"object"},
        "group_continuation": {"object"},
        "project_continuation": {"object"},
        "field_assignment": {"object"},
        "change_object_file": {"array"},
        "path": {"string"},
        "text": {"string"},
        "string": {"array"} if binding.repeatable else {"string"},
    }[binding.value_type]
    return accepted == expected


def _expanded_bounds(schema):
    expanded = [schema, *schema.get("oneOf", ()), *schema.get("anyOf", ())]

    def first(key):
        return next((part[key] for part in expanded if key in part), None)

    items = schema.get("items", {})
    return {
        "minimum": first("minimum"),
        "maximum": first("maximum"),
        "min_length": first("minLength"),
        "max_length": first("maxLength"),
        "pattern": first("pattern"),
        "min_items": first("minItems"),
        "max_items": first("maxItems"),
        "min_properties": first("minProperties"),
        "max_properties": first("maxProperties"),
        "item_minimum": items.get("minimum"),
        "item_maximum": items.get("maximum"),
        "item_min_length": items.get("minLength"),
        "item_max_length": items.get("maxLength"),
        "item_pattern": items.get("pattern"),
    }


def test_structured_and_file_arguments_use_curated_repeatable_bindings(
    descriptors_module,
):
    by_operation = {
        descriptor.operation: descriptor for descriptor in descriptors_module.DESCRIPTORS
    }

    update = by_operation["jira_update_fields"]
    assert _binding(update, "fields") == (
        "option",
        "--field",
        True,
        True,
        "field_assignment",
    )
    changes = by_operation["gitlab_commit_changes"]
    assert _binding(changes, "actions") == (
        "body_file",
        "--change-file",
        True,
        True,
        "change_object_file",
    )
    assert _binding(by_operation["arm_deploy"], "source_file") == (
        "local_file",
        "--file",
        True,
        False,
        "path",
    )

    aql = by_operation["arm_search_artifacts"]
    query_bindings = [
        binding
        for binding in aql.option_bindings + aql.file_bindings
        if binding.target_schema_property == "query"
    ]
    assert {(binding.source, binding.public_name) for binding in query_bindings} == {
        ("option", "--query"),
        ("body_file", "--query-file"),
    }
    assert all(binding.required is False for binding in query_bindings)
    assert {
        (
            binding.mutually_exclusive_group,
            binding.mutually_exclusive_group_required,
        )
        for binding in query_bindings
    } == {("aql-input", True)}
    assert {binding.target_schema_property for binding in query_bindings} == {
        "query"
    }
    grouped = [
        binding
        for descriptor in descriptors_module.DESCRIPTORS
        for binding in descriptor.option_bindings + descriptor.file_bindings
        if binding.mutually_exclusive_group is not None
    ]
    assert grouped == query_bindings

    repeatable_lists = {
        ("jira_search_issues", "fields"): "--field",
        ("jira_search_issues", "statuses"): "--status",
        ("jira_search_issues", "issue_types"): "--issue-type",
        ("jira_search_issues", "priorities"): "--priority",
        ("jira_search_issues", "labels"): "--label",
        ("gitlab_update_merge_request", "add_labels"): "--add-label",
        ("gitlab_update_merge_request", "remove_labels"): "--remove-label",
        ("arm_get_properties", "keys"): "--key",
    }
    for (operation, target), public_name in repeatable_lists.items():
        binding = next(
            binding
            for binding in (
                by_operation[operation].positional_bindings
                + by_operation[operation].option_bindings
            )
            if binding.target_schema_property == target
        )
        assert binding.public_name == public_name
        assert binding.repeatable is True
        assert binding.value_type == "string"

    for operation in (
        "jira_add_comment",
        "gitlab_create_mr_note",
        "gitlab_reply_to_discussion",
    ):
        binding = by_operation[operation].file_bindings[0]
        assert (binding.source, binding.public_name, binding.value_type) == (
            "body_file",
            "--body-file",
            "text",
        )
    for operation in (
        "confluence_create_page",
        "confluence_update_page",
        "confluence_add_comment",
    ):
        markdown = next(
            binding
            for binding in by_operation[operation].file_bindings
            if binding.target_schema_property == "markdown"
        )
        assert (markdown.source, markdown.public_name, markdown.value_type) == (
            "body_file",
            "--body-file",
            "text",
        )

    structured = {
        binding.value_type
        for descriptor in descriptors_module.DESCRIPTORS
        for binding in descriptor.option_bindings + descriptor.file_bindings
        if binding.value_type in {
            "continuation",
            "group_continuation",
            "project_continuation",
            "field_assignment",
            "change_object_file",
        }
    }
    assert structured == {
        "continuation",
        "group_continuation",
        "project_continuation",
        "field_assignment",
        "change_object_file",
    }


def _binding(descriptor, target):
    binding = next(
        binding
        for binding in (
            descriptor.positional_bindings
            + descriptor.option_bindings
            + descriptor.file_bindings
        )
        if binding.target_schema_property == target
    )
    return (
        binding.source,
        binding.public_name,
        binding.required,
        binding.repeatable,
        binding.value_type,
    )
