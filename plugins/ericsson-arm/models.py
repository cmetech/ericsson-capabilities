"""Stable, redacted error and identity types for the Artifactory connector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SAFE_ERROR_MESSAGES = {
    "invalid_configuration": "Artifactory configuration is invalid",
    "invalid_input": "Artifactory request input is invalid",
    "authentication": "Artifactory authentication failed",
    "permission": "Artifactory permission denied",
    "not_found": "Artifactory content was not found",
    "conflict": "Artifactory content changed since it was read",
    "rate_limited": "Artifactory rate limit was reached",
    "transient": "Artifactory service is temporarily unavailable",
    "write_ambiguous": "Artifactory write outcome is unknown",
    "invalid_remote_data": "Artifactory returned invalid data",
    "cancelled": "Artifactory request was cancelled",
    "deadline": "Artifactory request deadline was exceeded",
    "capacity": "Artifactory result exceeded a safe limit",
    "circuit_open": "Artifactory calls are paused after repeated failures",
    "confirmation_required": "Artifactory change needs explicit confirmation",
    # Distinct from ``authentication``: this is the mTLS certificate at
    # Cloudflare Access, not the Artifactory token at the origin.
    "edge_authentication": (
        "Artifactory edge access was refused before the request reached "
        "Artifactory"
    ),
    "certificate_invalid": (
        "Artifactory client certificate is missing, expired, or unreadable"
    ),
}

# Exception-derived remediation is an output boundary. Only a connector-owned
# literal can cross it; remote text and token-bearing values are always dropped.
_SAFE_REMEDIATIONS = frozenset({"Update the Artifactory token."})


def safe_remediation(value: object) -> str | None:
    """Return only static, connector-owned remediation guidance."""
    if type(value) is not str or value not in _SAFE_REMEDIATIONS:
        return None
    return value


class ArmError(RuntimeError):
    """Stable classified failure that never includes remote or secret text."""

    def __init__(self, category: object, *, remediation: object = None) -> None:
        self.category = (
            category
            if type(category) is str and category in SAFE_ERROR_MESSAGES
            else "transient"
        )
        self.remediation = safe_remediation(remediation)
        super().__init__(SAFE_ERROR_MESSAGES[self.category])


@dataclass(frozen=True, slots=True)
class ArmAuth:
    origin: str
    # Every path in this connector lives under /artifactory/. Xray would add
    # a second root and is deliberately out of this cut.
    api_root: str
    auth_header_name: str
    auth_header_value: str
    # Retained separately so later redaction can strip both the bare token and
    # its complete Authorization header value.
    token: str
    # ssl.SSLContext or None. Kept loose so this identity module imports no ssl.
    tls_context: Any
    # Unix seconds from the client certificate's notAfter, or None when absent.
    certificate_not_after: float | None
    request_timeout_seconds: int
    default_max_results: int
    max_deploy_bytes: int
    deploy_root: str | None
