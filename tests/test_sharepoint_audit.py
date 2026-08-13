"""B-06 through B-15 and E-01 through E-05: audit normalization."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "ericsson-sharepoint"
FIXTURE = Path(__file__).parent / "fixtures/sharepoint/audit/site.json"


def _load():
    name = "sharepoint_audit_test"
    for key in list(sys.modules):
        if key == name or key.startswith(name + "."):
            sys.modules.pop(key)
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return sys.modules[name + ".audit"], sys.modules[name + ".models"]


class Session:
    def __init__(self, fixture, failures=()):
        self.fixture = fixture
        self.failures = set(failures)
        self.navigated = []
        self.expressions = []

    def navigate(self, url):
        self.navigated.append(url)
        return {"success": True}

    def eval(self, expression):
        self.expressions.append(expression)
        category = next(name for name in self.fixture if f'"category":"{name}"' in expression)
        if category in self.failures:
            return {"success": False, "error": "cookie=secret cdp://private"}
        return {"success": True, "result": self.fixture[category]}


@pytest.mark.anyio
async def test_b06_b12_e01_normalizes_all_categories_and_exact_site_selection():
    audit, _ = _load()
    fixture = json.loads(FIXTURE.read_text())
    session = Session(fixture)
    sites = [
        {"name": "Governance", "url": "https://tenant.sharepoint.com/sites/Governance"},
        {"name": "Other", "url": "https://tenant.sharepoint.com/sites/Other"},
    ]

    result = await audit.audit_sites_with_session(
        session, sites=sites, selected=("governance",), allowed_hosts={"tenant.sharepoint.com"},
        max_sites=2, max_pages_per_category=3, max_rows_per_category=20,
        max_total_rows=100, max_total_bytes=50_000,
    )

    assert result["status"] == "complete"
    assert len(result["sites"]) == 1
    site = result["sites"][0]
    assert site["status"] == "complete"
    assert site["metadata"]["title"] == "Governance"
    assert site["users"][0]["site_admin"] is True
    assert site["permissions"][1]["role"] == "Edit"
    assert site["group_members"][0]["group_name"] == "Members"
    assert site["lists"][0]["item_count"] == 4
    assert site["subsites"][0]["template"] == "STS"
    assert session.navigated == ["https://tenant.sharepoint.com/sites/Governance"]
    assert all("tenant.sharepoint.com" not in expression for expression in session.expressions)


@pytest.mark.anyio
async def test_b13_e05_category_failure_is_partial_not_false_complete():
    audit, _ = _load()
    session = Session(json.loads(FIXTURE.read_text()), failures={"members"})
    result = await audit.audit_sites_with_session(
        session, sites=[{"name": "Governance", "url": "https://tenant.sharepoint.com/sites/Governance"}],
        selected=(), allowed_hosts={"tenant.sharepoint.com"}, max_sites=1,
        max_pages_per_category=2, max_rows_per_category=20, max_total_rows=100,
        max_total_bytes=50_000,
    )
    assert result["status"] == "partial"
    assert result["sites"][0]["status"] == "partial"
    assert {warning["category"] for warning in result["sites"][0]["warnings"]} == {"members"}
    assert "cookie" not in repr(result) and "cdp" not in repr(result)


@pytest.mark.anyio
async def test_b14_limits_are_explicit_and_same_origin_is_mandatory():
    audit, models = _load()
    fixture = json.loads(FIXTURE.read_text())
    fixture["users"] = fixture["users"] * 5
    result = await audit.audit_sites_with_session(
        Session(fixture), sites=[{"name": "Governance", "url": "https://tenant.sharepoint.com/sites/Governance"}],
        selected=(), allowed_hosts={"tenant.sharepoint.com"}, max_sites=1,
        max_pages_per_category=1, max_rows_per_category=2, max_total_rows=5,
        max_total_bytes=50_000,
    )
    assert result["status"] == "truncated"
    assert result["sites"][0]["status"] == "truncated"
    assert result["truncation_reasons"]
    with pytest.raises(models.SharePointAuditError, match="tenant origin"):
        await audit.audit_sites_with_session(
            Session(fixture), sites=[{"name": "Evil", "url": "https://evil.example/site"}],
            selected=(), allowed_hosts={"tenant.sharepoint.com"}, max_sites=1,
            max_pages_per_category=1, max_rows_per_category=1, max_total_rows=1,
            max_total_bytes=1000,
        )


@pytest.mark.anyio
async def test_b14_audit_honors_cancel_and_deadline():
    audit, models = _load()
    kwargs = dict(
        session=Session(json.loads(FIXTURE.read_text())),
        sites=[{"name": "Governance", "url": "https://tenant.sharepoint.com/sites/Governance"}],
        selected=(), allowed_hosts={"tenant.sharepoint.com"}, max_sites=1,
        max_pages_per_category=1, max_rows_per_category=1, max_total_rows=10,
        max_total_bytes=10_000,
    )
    with pytest.raises(models.SharePointCancelledError):
        await audit.audit_sites_with_session(**kwargs, cancel_check=lambda: True)
    with pytest.raises(models.SharePointDeadlineError):
        await audit.audit_sites_with_session(**kwargs, deadline=0, clock=lambda: 1)
