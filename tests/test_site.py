"""The published site carries the GoatCounter snippet exactly once per page.

``site/`` and ``scripts/`` are not shipped in the sdist, so these skip there.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
BUILD = REPO / "scripts" / "build_site.py"

pytestmark = pytest.mark.skipif(
    not (SITE.is_dir() and BUILD.is_file()), reason="site/ not in this checkout"
)


def _build_site():  # type: ignore[no-untyped-def]
    if "build_site" in sys.modules:
        return sys.modules["build_site"]
    spec = importlib.util.spec_from_file_location("build_site", BUILD)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_site"] = mod  # dataclasses look their module up there
    spec.loader.exec_module(mod)
    return mod


def test_with_analytics_is_idempotent():
    bs = _build_site()
    html = "<html><body><p>x</p></body></html>"
    once = bs.with_analytics(html)
    assert once.count("prebuttal.goatcounter.com/count") == 1
    assert bs.with_analytics(once) == once


def test_with_banner_is_idempotent():
    """Re-running the site build must not add a blank line per run."""
    bs = _build_site()
    html = "<header>\n    <h1>t</h1>\n  </header>\n  <div class=hero>x</div>"
    once = bs.with_banner(html, "Demo banner")
    assert once.count("Demo banner") == 1
    assert bs.with_banner(once, "Demo banner") == once
    assert bs.with_banner(once, "New text").count("\n") == once.count("\n")


def test_every_site_page_has_the_snippet_once():
    pages = sorted(SITE.rglob("*.html"))
    assert pages
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert html.count("prebuttal.goatcounter.com/count") == 1, page


# -- generated pages (scripts/build_site.py --pages) --------------------------


def test_generated_pages_are_up_to_date():
    """Heads, the guide's reference and settings table, venue pages, sitemap."""
    bs = _build_site()
    for path, text in bs.render_pages(SITE).items():
        on_disk = (SITE / path).read_text(encoding="utf-8") if (SITE / path).exists() else None
        assert on_disk == text, f"site/{path} is stale: run python scripts/build_site.py --pages"


def _sample_config_settings() -> set[tuple[str, str]]:
    """Every (section, key) in the `prebuttal init` sample, commented-out ones too."""
    import re

    from prebuttal.config import DEFAULT_CONFIG_TOML

    found, section = set(), ""
    value = r"(\"[^\"]*\"|\[[^\]]*\]|[-\w.]+)"
    for line in DEFAULT_CONFIG_TOML.splitlines():
        m = re.match(r"^(?:# )?\[\[?([^\]]+?)\]\]?\s*(#.*)?$", line)
        if m:
            section = re.sub(r"^(agents|pricing)\..*", lambda g: g[1] + ".*", m[1])
            found.add((section, ""))
            continue
        # a commented-out setting, not prose that happens to contain "="
        m = re.match(rf"^(?:# )?([a-z_]+)\s*=\s*{value}\s*(#.*)?$", line)
        if m:
            found.add((section, m[1]))
    return found


def test_settings_table_covers_the_sample_config():
    bs = _build_site()
    import re

    documented = set()
    for section, _about, rows in bs.config_docs():
        name = re.sub(r"^(agents|pricing)\..*", lambda g: g[1] + ".*", section.strip("[]"))
        documented.add((name, ""))
        documented |= {(name, key) for key, _d, _t in rows}
    sample = _sample_config_settings()
    assert ("output", "formats") in sample and ("share", "repo_url") in sample  # the scan works
    assert sample - documented == set()


def test_settings_table_documents_only_real_keys():
    bs = _build_site()
    source = (REPO / "prebuttal" / "config.py").read_text(encoding="utf-8")
    for _section, _about, rows in bs.config_docs():
        for key, _d, _t in rows:
            assert f'"{key}"' in source, key


def test_reference_lists_visible_commands_only():
    bs = _build_site()
    ref = bs.reference_html()
    for name in ("run", "check", "show", "venues", "backends", "key"):
        assert f'id="cmd-{name}"' in ref
    assert 'id="cmd-plan"' not in ref  # a hidden alias
    for hidden in ("--seed", "--effort", "--reviewers", "--out-dir", "--figures", "_view"):
        assert hidden not in ref


def test_venue_pages_follow_the_rules_in_code():
    bs = _build_site()
    from prebuttal.venues import VENUES

    for key, venue in VENUES.items():
        _page, text = bs._venue_page(key)
        assert f"--venue {key}" in text
        assert f"within {venue.rules.page_limit} pages" in text
        assert venue.rules.source in text
        for section in venue.rules.required_sections:
            assert section in text


def _pages() -> list[Path]:
    return [p for p in sorted(SITE.rglob("*.html")) if "reports" not in p.parts]


def test_every_page_has_its_own_head():
    import re

    titles, descriptions = set(), set()
    for page in _pages():
        html = page.read_text(encoding="utf-8")
        assert html.count("<!-- head:start -->") == 1, page
        assert html.count("<h1") == 1, page
        assert re.search(r'<link rel="canonical" href="https://[^"]+/">', html), page
        title = re.search(r"<title>(.*?)</title>", html)[1]  # type: ignore[index]
        desc = re.search(r'<meta name="description" content="([^"]*)"', html)[1]  # type: ignore[index]
        assert len(desc) <= 160, page
        assert title not in titles and desc not in descriptions, page
        titles.add(title)
        descriptions.add(desc)


def test_internal_links_resolve():
    """Relative links point at real files, folders end in a slash, anchors exist."""
    import re

    ids: dict[Path, set[str]] = {}
    for page in sorted(SITE.rglob("*.html")):
        ids[page.resolve()] = set(re.findall(r'id="([^"]+)"', page.read_text(encoding="utf-8")))
    for page in _pages():
        html = page.read_text(encoding="utf-8")
        for href in re.findall(r'href="([^"]+)"', html):
            if re.match(r"(https?:|mailto:|//)", href):
                continue
            path, _, anchor = href.partition("#")
            target = (page.parent / path).resolve() if path else page.resolve()
            if path.endswith("/") or not path:
                target = target / "index.html" if path else target
            else:
                assert "." in path.rsplit("/", 1)[-1], f"{page}: {href} needs a trailing slash"
            assert target.is_file(), f"{page}: {href}"
            if anchor and target.suffix == ".html":
                assert anchor in ids[target], f"{page}: {href}"


def test_guide_pins_the_same_action_release_as_the_readme():
    """A release bumps `uses: GuoYuKai-SaMuEl/prebuttal@vX` in the READMEs and the guide."""
    import re

    pin = re.compile(r"GuoYuKai-SaMuEl/prebuttal@(v[\d.]+)")
    readme = set(pin.findall((REPO / "README.md").read_text(encoding="utf-8")))
    guide = set(pin.findall((SITE / "guide" / "index.html").read_text(encoding="utf-8")))
    assert len(readme) == 1 and guide == readme
