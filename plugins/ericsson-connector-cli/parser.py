"""Argparse construction and pre-dispatch gates for connector commands."""

from __future__ import annotations

import argparse
import json
import re
import uuid
from collections.abc import Mapping
from typing import Any

from . import io as local_io
from .descriptors import ArgumentBinding, CommandDescriptor, DESCRIPTORS, SchemaContract


_STRUCTURED_TYPES = {
    "continuation",
    "group_continuation",
    "project_continuation",
    "field_assignment",
}


def _bounded_integer(binding: ArgumentBinding):
    def convert(raw: str) -> int:
        try:
            value = int(raw, 10)
        except ValueError:
            raise argparse.ArgumentTypeError("expected an integer") from None
        if binding.minimum is not None and value < binding.minimum:
            raise argparse.ArgumentTypeError(
                f"value must be at least {binding.minimum}"
            )
        if binding.maximum is not None and value > binding.maximum:
            raise argparse.ArgumentTypeError(
                f"value must be at most {binding.maximum}"
            )
        return value

    return convert


def _bounded_string(binding: ArgumentBinding):
    def convert(raw: str) -> str | int | None:
        if binding.value_type == "nullable_string":
            if raw == "null":
                return None
            if raw.startswith('"'):
                try:
                    decoded = json.loads(raw)
                except (TypeError, ValueError):
                    raise argparse.ArgumentTypeError(
                        "quoted nullable value must be a JSON string"
                    ) from None
                if not isinstance(decoded, str):
                    raise argparse.ArgumentTypeError(
                        "quoted nullable value must be a JSON string"
                    )
                raw = decoded
        if binding.value_type == "string_or_integer" and raw.isdecimal():
            value = int(raw, 10)
            if binding.minimum is not None and value < binding.minimum:
                raise argparse.ArgumentTypeError(
                    f"value must be at least {binding.minimum}"
                )
            if binding.maximum is not None and value > binding.maximum:
                raise argparse.ArgumentTypeError(
                    f"value must be at most {binding.maximum}"
                )
            return value
        if binding.min_length is not None and len(raw) < binding.min_length:
            raise argparse.ArgumentTypeError(
                f"value must contain at least {binding.min_length} characters"
            )
        if binding.max_length is not None and len(raw) > binding.max_length:
            raise argparse.ArgumentTypeError(
                f"value must contain at most {binding.max_length} characters"
            )
        if binding.pattern is not None and re.fullmatch(binding.pattern, raw) is None:
            raise argparse.ArgumentTypeError("value has an invalid format")
        return raw

    return convert


def _argument_kwargs(binding: ArgumentBinding, *, dest: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "dest": dest,
        "default": argparse.SUPPRESS,
        "help": (
            binding.schema_contract.description
            if binding.schema_contract is not None
            else None
        ),
    }
    if binding.value_type == "boolean":
        kwargs["action"] = argparse.BooleanOptionalAction
    else:
        if not binding.choices:
            kwargs["metavar"] = binding.public_name.lstrip("-").upper().replace(
                "-", "_"
            )
        kwargs["type"] = (
            _bounded_integer(binding)
            if binding.value_type == "integer"
            else _bounded_string(binding)
        )
        if binding.choices:
            kwargs["choices"] = binding.choices
        if binding.repeatable or binding.value_type in _STRUCTURED_TYPES:
            kwargs["action"] = "append"
        if binding.source == "positional" and binding.repeatable:
            kwargs.pop("action", None)
            kwargs["nargs"] = "+"
    if binding.source != "positional" and binding.required:
        kwargs["required"] = True
    if binding.source == "positional":
        kwargs.pop("dest")
        kwargs.pop("default")
    return kwargs


def _binding_dest(index: int) -> str:
    return f"_connector_cli_argument_{index}"


def _add_leaf_arguments(leaf, descriptor: CommandDescriptor, ctx) -> None:
    bindings = (
        descriptor.positional_bindings
        + descriptor.option_bindings
        + descriptor.file_bindings
    )
    groups: dict[str, Any] = {}
    destinations = []
    for index, binding in enumerate(bindings):
        dest = _binding_dest(index)
        destinations.append(dest)
        container = leaf
        if binding.mutually_exclusive_group is not None:
            container = groups.get(binding.mutually_exclusive_group)
            if container is None:
                container = leaf.add_mutually_exclusive_group(
                    required=binding.mutually_exclusive_group_required
                )
                groups[binding.mutually_exclusive_group] = container
        kwargs = _argument_kwargs(binding, dest=dest)
        if binding.source == "positional":
            container.add_argument(dest, **kwargs)
        else:
            container.add_argument(binding.public_name, **kwargs)

    leaf.add_argument(
        "--json",
        action="store_true",
        default=False,
        dest="_connector_cli_json",
        help="Emit the stable JSON envelope",
    )
    if descriptor.access == "write":
        intent = leaf.add_mutually_exclusive_group(required=True)
        intent.add_argument("--dry-run", action="store_true", default=False)
        intent.add_argument("--confirm", action="store_true", default=False)
    leaf.set_defaults(
        func=_leaf_handler,
        _connector_cli_ctx=ctx,
        _connector_cli_descriptor=descriptor,
        _connector_cli_binding_dests=tuple(destinations),
    )


def add_domain_commands(domain_parser, domain: str, ctx) -> None:
    """Populate one host-owned top-level domain parser from curated rows."""
    descriptors = [d for d in DESCRIPTORS if d.path_tokens[0] == domain]
    if not descriptors:
        raise ValueError("unknown Ericsson connector command domain")
    children: dict[tuple[str, ...], tuple[Any, Any]] = {}
    root_subparsers = domain_parser.add_subparsers(
        dest=f"_{domain}_resource", required=True
    )
    children[()] = (domain_parser, root_subparsers)
    for descriptor in descriptors:
        parent_tokens: tuple[str, ...] = ()
        for offset, token in enumerate(descriptor.path_tokens[1:]):
            current_tokens = (*parent_tokens, token)
            existing = children.get(current_tokens)
            is_leaf = offset == len(descriptor.path_tokens[1:]) - 1
            if existing is None:
                _parent, subparsers = children[parent_tokens]
                child = subparsers.add_parser(
                    token,
                    help=(
                        descriptor.operation
                        if is_leaf
                        else f"{token.replace('-', ' ').title()} commands"
                    ),
                    description=descriptor.operation if is_leaf else None,
                )
                if is_leaf:
                    children[current_tokens] = (child, None)
                else:
                    nested = child.add_subparsers(
                        dest=f"_{domain}_{'_'.join(current_tokens)}", required=True
                    )
                    children[current_tokens] = (child, nested)
                existing = children[current_tokens]
            if is_leaf:
                leaf, nested = existing
                if nested is not None:
                    raise ValueError("curated command path is both branch and leaf")
                _add_leaf_arguments(leaf, descriptor, ctx)
            parent_tokens = current_tokens


def build_parser(*, prog: str, ctx) -> argparse.ArgumentParser:
    """Build a complete standalone parser for tests and brand-neutral reuse."""
    root = argparse.ArgumentParser(prog=prog)
    domains = root.add_subparsers(dest="_connector_cli_domain", required=True)
    for domain in ("jira", "gitlab", "confluence", "arm"):
        domain_parser = domains.add_parser(
            domain, help=f"Run bounded Ericsson {domain.title()} connector commands"
        )
        add_domain_commands(domain_parser, domain, ctx)
    return root


def _validate_contract(value: Any, contract: SchemaContract | None) -> None:
    if contract is None:
        return
    if contract.one_of:
        matched = 0
        for candidate in contract.one_of:
            try:
                _validate_contract(value, candidate)
            except local_io.CliInputError:
                continue
            matched += 1
        if matched != 1:
            raise local_io.CliInputError("value does not match its command schema")
        return
    expected = set(contract.types)
    actual = (
        "null"
        if value is None
        else "boolean"
        if isinstance(value, bool)
        else "integer"
        if isinstance(value, int)
        else "string"
        if isinstance(value, str)
        else "array"
        if isinstance(value, list)
        else "object"
        if isinstance(value, Mapping)
        else "unsupported"
    )
    if expected and actual not in expected:
        raise local_io.CliInputError("value does not match its command schema")
    if contract.enum and value not in contract.enum:
        raise local_io.CliInputError("value is not an allowed choice")
    if isinstance(value, int) and not isinstance(value, bool):
        if contract.minimum is not None and value < contract.minimum:
            raise local_io.CliInputError("integer is below its minimum")
        if contract.maximum is not None and value > contract.maximum:
            raise local_io.CliInputError("integer exceeds its maximum")
    if isinstance(value, str):
        if contract.min_length is not None and len(value) < contract.min_length:
            raise local_io.CliInputError("string is shorter than its minimum")
        if contract.max_length is not None and len(value) > contract.max_length:
            raise local_io.CliInputError("string exceeds its maximum")
        if contract.pattern and re.fullmatch(contract.pattern, value) is None:
            raise local_io.CliInputError("string has an invalid format")
    if isinstance(value, list):
        if contract.min_items is not None and len(value) < contract.min_items:
            raise local_io.CliInputError("list is shorter than its minimum")
        if contract.max_items is not None and len(value) > contract.max_items:
            raise local_io.CliInputError("list exceeds its maximum")
        for item in value:
            _validate_contract(item, contract.items)
    if isinstance(value, Mapping):
        if contract.min_properties is not None and len(value) < contract.min_properties:
            raise local_io.CliInputError("mapping is smaller than its minimum")
        if contract.max_properties is not None and len(value) > contract.max_properties:
            raise local_io.CliInputError("mapping exceeds its maximum")
        properties = dict(contract.properties)
        if contract.additional_properties is False and not set(value) <= set(properties):
            raise local_io.CliInputError("mapping contains an unknown name")
        if not set(contract.required) <= set(value):
            raise local_io.CliInputError("mapping is missing a required name")
        for name, item in value.items():
            child = properties.get(name)
            if child is None and isinstance(contract.additional_properties, SchemaContract):
                child = contract.additional_properties
            _validate_contract(item, child)


def canonical_arguments(namespace, *, reader=None) -> dict[str, Any]:
    """Acquire local input and return only canonical connector arguments."""
    descriptor = namespace._connector_cli_descriptor
    bindings = (
        descriptor.positional_bindings
        + descriptor.option_bindings
        + descriptor.file_bindings
    )
    destinations = namespace._connector_cli_binding_dests
    input_reader = local_io.BoundedInputReader() if reader is None else reader
    arguments: dict[str, Any] = {}
    for binding, dest in zip(bindings, destinations):
        if not hasattr(namespace, dest):
            continue
        value = getattr(namespace, dest)
        contract = binding.schema_contract
        if isinstance(value, list) and contract is not None and "array" in contract.types:
            if contract.min_items is not None and len(value) < contract.min_items:
                raise local_io.CliInputError("list is shorter than its minimum")
            if contract.max_items is not None and len(value) > contract.max_items:
                raise local_io.CliInputError("list exceeds its maximum")
        if binding.value_type == "field_assignment":
            value = local_io.decode_name_values(value)
        elif binding.value_type in {
            "continuation",
            "group_continuation",
            "project_continuation",
        }:
            value = local_io.decode_name_values(value)
        elif binding.value_type == "change_object_file":
            value = input_reader.read_change_objects(value)
        elif binding.source == "body_file":
            value = input_reader.read_text(value, reject_symlink=True)
        elif binding.source == "local_file":
            value = local_io.resolve_local_path(value)

        target = binding.target_schema_property
        if binding.value_type == "group_continuation":
            arguments.setdefault(target, {})["groups"] = value
            _validate_contract(arguments[target], binding.schema_contract)
            continue
        if binding.value_type == "project_continuation":
            arguments.setdefault(target, {})["projects"] = value
            _validate_contract(arguments[target], binding.schema_contract)
            continue
        if target in arguments:
            raise local_io.CliInputError("duplicate canonical command argument")
        _validate_contract(value, binding.schema_contract)
        arguments[target] = value
    return arguments


def _leaf_handler(namespace) -> int:
    """Run local gates, then make one provisional host dispatch for Task 6."""
    try:
        arguments = canonical_arguments(namespace)
    except local_io.CliInputError:
        return 2
    descriptor = namespace._connector_cli_descriptor
    mode = (
        "read"
        if descriptor.access == "read"
        else "dry_run"
        if namespace.dry_run
        else "confirm"
    )
    invocation_id = str(uuid.uuid4())
    try:
        namespace._connector_cli_ctx.invoke_application_command(
            descriptor.connector_id,
            descriptor.operation,
            arguments,
            mode=mode,
            invocation_id=invocation_id,
        )
    except Exception:
        return 4
    return 0


__all__ = ["add_domain_commands", "build_parser", "canonical_arguments"]
