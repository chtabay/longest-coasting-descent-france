"""The audit page must consume the engine's outputs, and must survive publishing.

Two properties are defended here, and neither is cosmetic.

*One source of truth.* Every number on the page comes from
``outputs/phase3/variants.json``. A figure typed into the HTML would drift the
moment the engine is re-run, and a stale number on a page that looks generated
is worse than no page.

*It has to work wherever it is published.* GitHub Pages serves exactly one
subtree — the repository root, ``docs/``, or whatever an action uploads. A page
that reaches outside its own directory for an image renders with broken figures
under any publish root that does not happen to contain both trees. The test
therefore refuses any asset reference that escapes ``site/``.

No browser is involved: these are the failures a screenshot would not catch.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DATA = SITE / "data"

pytestmark = pytest.mark.skipif(not SITE.exists(), reason="the audit page is not built")


def payload() -> dict:
    """The generated data, read the way the page reads it."""
    source = (DATA / "phase3.js").read_text(encoding="utf-8")
    start = source.index("{")
    end = source.rindex("}") + 1
    return json.loads(source[start:end])


def test_the_page_data_matches_the_engine_output_exactly() -> None:
    """The three files are one object written three times, never edited apart."""
    generated = payload()
    assert generated == json.loads((DATA / "phase3.json").read_text(encoding="utf-8"))
    canonical = ROOT / "outputs" / "phase3" / "variants.json"
    assert generated == json.loads(canonical.read_text(encoding="utf-8"))


def test_every_referenced_asset_exists_and_stays_inside_the_site() -> None:
    """An asset outside `site/` is a broken figure on a published page."""
    for variant in payload()["variants"]:
        for name, reference in (variant.get("assets") or {}).items():
            assert not reference.startswith("/"), f"{name} is an absolute path: {reference}"
            assert ".." not in reference, (
                f"{name} escapes the published subtree: {reference}. "
                "Copy the file into site/assets instead of linking across trees."
            )
            assert (SITE / reference).exists(), f"{name} is missing: {reference}"


def test_the_page_only_loads_files_that_are_shipped_with_it() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    for reference in re.findall(r'(?:src|href)="([^"]+)"', html):
        if reference.startswith(("http://", "https://", "#", "data:")):
            continue
        assert ".." not in reference, f"{reference} escapes the published subtree"
        assert (SITE / reference).exists(), f"{reference} is referenced but absent"


def test_every_element_the_script_addresses_exists_in_the_page() -> None:
    """A renamed id fails silently in a browser; here it fails loudly."""
    html = (SITE / "index.html").read_text(encoding="utf-8")
    script = (SITE / "app.js").read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', html))
    for wanted in re.findall(r'getElementById\("([^"]+)"\)', script):
        assert wanted in ids, f"app.js addresses #{wanted}, which index.html does not define"
    for selector in re.findall(r'querySelector(?:All)?\("#([\w-]+)', script):
        assert selector in ids, f"app.js selects #{selector}, which index.html does not define"


def test_no_result_is_written_into_the_markup() -> None:
    """The page is a consumer. A number in the HTML is a second source of truth.

    Distances, speeds and elevations are what would actually be copied, so the
    check looks for numeric literals with more than two digits rather than for
    any digit at all — headings and viewport values are not results.
    """
    html = (SITE / "index.html").read_text(encoding="utf-8")
    body = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    body = re.sub(r"<meta[^>]*>", "", body)
    offenders = [
        found
        for found in re.findall(r"(?<![\w.-])\d[\d\s]{2,}(?:[.,]\d+)?(?![\w-])", body)
        if found.strip() and len(found.replace(" ", "")) >= 3
    ]
    assert not offenders, f"numeric literals in index.html: {offenders}"


def test_every_variant_carries_a_termination_status_with_its_distance() -> None:
    """A distance without its status is exactly the error the statuses exist to stop."""
    known = set(payload()["termination_statuses"])
    assert known == {"physical_stop", "model_gap", "network_boundary", "budget_limit"}
    for variant in payload()["variants"]:
        for route in variant["ranking"]:
            assert route["termination_status"] in known
            complete = route["termination_status"] == "physical_stop"
            assert route["is_complete"] is complete
            assert route["distance_label"].startswith(">=") is not complete
