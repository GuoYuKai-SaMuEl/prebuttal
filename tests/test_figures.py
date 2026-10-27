"""Figures as images for vision-capable reviewers (`--figures`)."""

import pytest
from conftest import PersonaFakeProvider, make_pdf_bytes

from prebuttal import cli
from prebuttal.config import load_config
from prebuttal.ingestion import ingest
from prebuttal.ingestion.latex import ingest_latex_source
from prebuttal.ingestion.pdf import ingest_pdf_bytes
from prebuttal.models import FigureImage
from prebuttal.orchestrator import run_reviews
from prebuttal.providers import register_backend
from prebuttal.providers.api import AnthropicProvider, GeminiProvider, OpenAIProvider
from prebuttal.providers.base import ProviderError
from prebuttal.runs import load_history
from prebuttal.venues import get_venue

PNG = b"\x89PNG\r\n\x1a\n"


def _png_file(path):
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 30), (200, 30, 30)).save(path)


class _Vision(PersonaFakeProvider):
    supports_images = True

    def __init__(self, *a, fail_with_images: bool = False, **kw):
        super().__init__(*a, **kw)
        self.fail_with_images = fail_with_images
        self.seen: list[list[bytes] | None] = []

    def _complete(self, *, images=None, **kw):
        self.seen.append(images)
        if images and self.fail_with_images:
            raise ProviderError("HTTP 400: this model does not support image input")
        return super()._complete(**kw)


# ------------------------------------------------------------------ ingestion


def test_pdf_figure_pages_rendered_only_when_asked():
    data = make_pdf_bytes()
    assert ingest_pdf_bytes(data).figure_images == []
    images = ingest_pdf_bytes(data, figure_images=3).figure_images
    assert [im.label for im in images] == ["page 1 (Figure 1)"]
    assert images[0].png.startswith(PNG)


def test_latex_figures_from_inside_the_project_only(tmp_path):
    proj = tmp_path / "paper"
    _png_file(proj / "figs" / "plot.png")
    _png_file(tmp_path / "private.png")
    (proj / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}\\section{Intro}\n"
        "\\begin{figure}\\includegraphics[width=\\linewidth]{figs/plot}"
        "\\caption{Accuracy.}\\end{figure}\n"
        "\\begin{figure}\\includegraphics{../private.png}\\caption{Leak?}\\end{figure}\n"
        "\\end{document}",
        encoding="utf-8",
    )
    paper = ingest_latex_source(proj, figure_images=6)
    assert [im.label for im in paper.figure_images] == ["Figure 1"]
    assert paper.figure_images[0].png.startswith(PNG)


# ------------------------------------------------------------------ dispatch

IMAGES = [FigureImage("page 2 (Figure 1)", PNG + b"one"), FigureImage("Figure 2", PNG + b"two")]


def _run(providers, cfg=None):
    cfg = cfg or load_config(None)
    return run_reviews(cfg, get_venue("iclr"), "PACK", providers, lambda m: None, IMAGES)


def test_only_vision_backends_get_the_images():
    cfg = load_config(None)
    vision = _Vision()
    providers = {r.id: PersonaFakeProvider() for r in cfg.reviewers}
    providers["R1"] = vision
    reviews = _run(providers, cfg)
    assert vision.seen == [[PNG + b"one", PNG + b"two"]]
    assert [r.images for r in reviews] == [2, 0, 0]
    # the vision reviewer is told what the images are; others are not
    user_r1 = vision.calls[0]["user"]
    assert "page 2 (Figure 1); Figure 2" in user_r1
    assert "Attached images" not in providers["R2"].calls[0]["user"]


def test_text_only_model_falls_back_without_images():
    cfg = load_config(None)
    vision = _Vision(fail_with_images=True)
    providers = {r.id: PersonaFakeProvider() for r in cfg.reviewers}
    providers["R1"] = vision
    reviews = _run(providers, cfg)
    assert reviews[0].parse_ok and reviews[0].images == 0
    assert vision.seen[-1] is None
    assert "Attached images" not in vision.calls[-1]["user"]


@pytest.mark.parametrize("cls,env", [
    (AnthropicProvider, "ANTHROPIC_API_KEY"),
    (OpenAIProvider, "OPENAI_API_KEY"),
    (GeminiProvider, "GEMINI_API_KEY"),
])  # fmt: skip
def test_api_payloads_carry_the_images(monkeypatch, cls, env):
    monkeypatch.setenv(env, "k")
    p = cls(model="m")
    sent: list[dict] = []

    def fake_post(url, headers, payload):
        sent.append(payload)
        return {
            "content": [{"text": "{}"}],
            "choices": [{"message": {"content": "{}"}}],
            "candidates": [{"content": {"parts": [{"text": "{}"}]}}],
        }

    monkeypatch.setattr(p, "_post_json", fake_post)
    p.complete(system="s", user="USER", retries=0, images=[PNG + b"x"])
    body = str(sent[0])
    assert "iVBORw0KGgp" in body  # base64 of the PNG signature
    assert "USER" in body


# ------------------------------------------------------------------ CLI + archive


def test_cli_figures_flag_archives_images_for_retry(
    tmp_path, monkeypatch, fake_statuses, fake_config, capsys
):
    seen: list = []

    class _V(_Vision):
        def _complete(self, *, images=None, **kw):
            seen.append(len(images or []))
            return super()._complete(images=images, **kw)

    register_backend("fake", lambda m, cfg, t: _V(model="fake-m"))
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(make_pdf_bytes())
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["run", str(pdf), "--config", str(fake_config), "--figures"])
    assert rc == cli.EXIT_OK
    assert seen.count(1) == 3  # three reviewers saw the one figure page; the AC none
    rec = load_history()[0]
    assert (rec.dir_path / "figures" / "01.png").read_bytes().startswith(PNG)
    assert "saw 1 figure image(s)" in (rec.dir_path / "report.md").read_text(encoding="utf-8")
    from prebuttal.retry import load_figures

    assert [im.label for im in load_figures(rec.dir_path)] == ["page 1 (Figure 1)"]


def test_figures_are_off_by_default(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(make_pdf_bytes())
    assert ingest(str(pdf)).figure_images == []
    assert load_config(None).figures is False


def test_images_are_never_in_report_json(latex_project):
    from conftest import make_report

    from prebuttal.report import dumps_json

    report, venue = make_report(latex_project)
    report.paper.figure_images = [FigureImage("Figure 1", PNG * 100)]
    assert "iVBORw0KGgp" not in dumps_json(report, venue)
