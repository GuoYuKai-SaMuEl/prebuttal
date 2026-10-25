"""The published site carries the GoatCounter snippet exactly once per page.

``site/`` and ``scripts/`` are not shipped in the sdist, so these skip there.
"""

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
BUILD = REPO / "scripts" / "build_site.py"

pytestmark = pytest.mark.skipif(
    not (SITE.is_dir() and BUILD.is_file()), reason="site/ not in this checkout"
)


def _build_site():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("build_site", BUILD)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_with_analytics_is_idempotent():
    bs = _build_site()
    html = "<html><body><p>x</p></body></html>"
    once = bs.with_analytics(html)
    assert once.count("prebuttal.goatcounter.com/count") == 1
    assert bs.with_analytics(once) == once


def test_every_site_page_has_the_snippet_once():
    pages = sorted(SITE.rglob("*.html"))
    assert pages
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert html.count("prebuttal.goatcounter.com/count") == 1, page
