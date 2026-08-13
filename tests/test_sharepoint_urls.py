"""U-01 through U-03: SharePoint URL parsing and authority boundaries."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-sharepoint"


def _parser():
    name = "sharepoint_url_parser"
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "url_parser.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("url", "site_path", "library", "item_path"),
    [
        (
            "https://tenant.sharepoint.com/sites/Governance/Shared%20Documents/Tracking/Plan.docx?web=1",
            "sites/Governance",
            "Shared Documents",
            "Tracking/Plan.docx",
        ),
        (
            "https://tenant.sharepoint.com/:w:/r/sites/Governance/Shared%20Documents/Plan.docx?d=abc",
            "sites/Governance",
            "Shared Documents",
            "Plan.docx",
        ),
        (
            "https://tenant.sharepoint.com/:x:/r/teams/Finance/Documents/Budget%202026.xlsx",
            "teams/Finance",
            "Documents",
            "Budget 2026.xlsx",
        ),
        (
            "https://tenant.sharepoint.com/Documents",
            "",
            "Documents",
            "",
        ),
        (
            "https://tenant.sharepoint.com/",
            "",
            "",
            "",
        ),
        (
            "https://tenant.sharepoint.com/sites/Governance/_layouts/15/Doc.aspx?source=ignored",
            "sites/Governance",
            "_layouts",
            "15/Doc.aspx",
        ),
    ],
)
def test_u01_u02_parse_standard_ui_root_and_encoded_paths(
    url, site_path, library, item_path
):
    parser = _parser()

    parsed = parser.parse_sharepoint_url(url, allowed_hosts={"tenant.sharepoint.com"})

    assert parsed.kind == "path"
    assert parsed.host == "tenant.sharepoint.com"
    assert parsed.site_path == site_path
    assert parsed.library == library
    assert parsed.item_path == item_path


def test_u01_sharing_link_preserves_bounded_canonical_url_for_graph_shares():
    parser = _parser()
    url = (
        "https://tenant.sharepoint.com/:w:/g/personal/user_tenant_onmicrosoft_com/"
        "EXAMPLE?e=abc"
    )

    parsed = parser.parse_sharepoint_url(url, allowed_hosts={"tenant.sharepoint.com"})

    assert parsed.kind == "sharing"
    assert parsed.sharing_url == url
    assert parsed.site_path == ""
    assert parsed.library == ""
    assert parsed.item_path == ""


@pytest.mark.parametrize(
    "url",
    [
        "http://tenant.sharepoint.com/sites/Governance/Documents/a.docx",
        "https://other.sharepoint.com/sites/Governance/Documents/a.docx",
        "https://user@tenant.sharepoint.com/sites/Governance/Documents/a.docx",
        "https://tenant.sharepoint.com:444/sites/Governance/Documents/a.docx",
        "https://tenant.sharepoint.com/sites/Governance/Documents/a.docx#fragment",
        "https://tenant.sharepoint.com/sites/Governance/Documents/bad%2.docx",
        "https://tenant.sharepoint.com/sites/Governance/Documents/bad%GG.docx",
        "https:\\tenant.sharepoint.com\\sites\\Governance",
    ],
)
def test_u03_rejects_unsafe_authority_fragments_and_escaping(url):
    parser = _parser()

    with pytest.raises(parser.SharePointURLParseError):
        parser.parse_sharepoint_url(url, allowed_hosts={"tenant.sharepoint.com"})


def test_u03_rejects_decoded_path_separators_and_control_characters():
    parser = _parser()

    for url in (
        "https://tenant.sharepoint.com/sites/Governance/Documents/a%2Fb.docx",
        "https://tenant.sharepoint.com/sites/Governance/Documents/a%5Cb.docx",
        "https://tenant.sharepoint.com/sites/Governance/Documents/a%00b.docx",
    ):
        with pytest.raises(parser.SharePointURLParseError):
            parser.parse_sharepoint_url(url, allowed_hosts={"tenant.sharepoint.com"})

