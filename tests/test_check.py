"""`prebuttal check`: the deterministic desk-reject pre-flight."""

import io
import json

import pytest
from conftest import FAKE_TOML, latest_report

from prebuttal import cli
from prebuttal.check import ERROR, WARNING, check_latex, check_pdf_bytes
from prebuttal.venues import CheckRules, get_venue

pytest.importorskip("reportlab")


def make_paper(pages, *, author: str = "") -> bytes:
    """A PDF with one list of (y, text, size) lines per page (y from the top)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    if author:
        c.setAuthor(author)
    height = A4[1]
    for lines in pages:
        for y, text, size in lines:
            c.setFont("Helvetica-Bold" if size > 10 else "Helvetica", size)
            c.drawString(72, height - y, text)
        c.showPage()
    c.save()
    return buf.getvalue()


def body(n: int, start: int = 120) -> list[tuple[int, str, int]]:
    return [
        (start + 14 * i, f"Body sentence number {i} about widgets and results.", 10)
        for i in range(n)
    ]


def page1(extra=()) -> list[tuple[int, str, int]]:
    return [
        (80, "Deep Widgets for Structured Prediction", 16),
        (104, "Anonymous Authors", 10),
        *extra,
        *body(10, 140),
    ]


def levels(result, area: str) -> list[str]:
    return [f.level for f in result.findings if f.area == area]


RULES = CheckRules(page_limit=3, required_sections=("Limitations",))


def test_clean_anonymous_pdf_passes():
    pdf = make_paper(
        [
            page1(),
            body(30),
            [(80, "5 Limitations", 12), *body(10, 100), (300, "References", 12), *body(5, 320)],
        ]
    )
    result = check_pdf_bytes(pdf, RULES)
    assert result.errors == [] and result.warnings == []
    assert "main text 3 of 3 pages" in result.passed


def test_page_limit_counts_to_the_references_heading():
    over = [page1(), body(30), body(30), [(300, "References", 12), *body(5, 320)]]
    result = check_pdf_bytes(make_paper(over), CheckRules(page_limit=3))
    assert any("runs to page 4" in f.message for f in result.errors)
    # References at the very top of page 4: the main text ended on page 3
    top = [page1(), body(30), body(30), [(60, "References", 12), *body(5, 80)]]
    assert check_pdf_bytes(make_paper(top), CheckRules(page_limit=3)).errors == []


def test_uncounted_statement_ends_the_main_text():
    """ICML: the impact statement before References is outside the 8 pages."""
    pages = [page1(), body(30), [(80, "Impact Statement", 12), *body(5, 100)], body(30)]
    pages.append([(80, "References", 12)])
    rules = CheckRules(page_limit=2, uncounted=("References", "Impact Statement"))
    assert check_pdf_bytes(make_paper(pages), rules).errors == []


def test_missing_required_section_is_an_error():
    result = check_pdf_bytes(make_paper([page1(), [(80, "References", 12)]]), RULES)
    assert any('no "Limitations" section' in f.message for f in result.errors)


def test_anonymity_problems_are_found():
    pdf = make_paper(
        [
            page1(extra=[(118, "alice@uni.edu", 9)]),
            [
                (80, "Our code is available at github.com/alicesmith/widgets for all.", 10),
                (100, "As shown in our previous work [12], widgets scale.", 10),
                (120, "We use PyTorch (github.com/pytorch/pytorch) as is.", 10),
                (200, "Acknowledgments", 12),
                (220, "We thank our funders.", 10),
            ],
        ],
        author="Alice Smith",
    )
    result = check_pdf_bytes(pdf, CheckRules())
    text = " | ".join(f.message for f in result.findings)
    assert "Alice Smith" in text and "alice@uni.edu" in text
    assert "github.com/alicesmith/widgets" in text
    assert "pytorch/pytorch" not in text  # someone else's repo is not a leak
    assert "our previous work" in text
    assert levels(result, "anonymity").count(ERROR) == 2  # metadata + e-mail
    assert "acknowledgements section is visible" in text


def test_not_double_blind_skips_anonymity():
    pdf = make_paper([page1(extra=[(118, "alice@uni.edu", 9)])], author="Alice Smith")
    result = check_pdf_bytes(pdf, CheckRules(double_blind=False))
    assert levels(result, "anonymity") == []


def test_camera_ready_build_is_flagged():
    pdf = make_paper([page1(extra=[(60, "Published as a conference paper at ICLR 2027", 9)])])
    result = check_pdf_bytes(pdf, get_venue("iclr").rules)
    assert any("camera-ready" in f.message for f in result.errors)
    neurips = get_venue("neurips").rules
    submitted = (
        "Submitted to 40th Conference on Neural Information Processing Systems (NeurIPS 2026)."
    )
    assert not any(
        "camera-ready" in f.message
        for f in check_pdf_bytes(make_paper([page1(extra=[(800, submitted, 8)])]), neurips).findings
    )


def test_leftovers_are_found():
    pdf = make_paper(
        [
            page1(),
            [(80, "As Table ?? shows, we beat [?] by far.", 10), (100, "TODO: add seeds", 10)],
        ]
    )
    result = check_pdf_bytes(pdf, CheckRules())
    text = " | ".join(f"{f.level}:{f.message}" for f in result.findings)
    assert "error:unresolved references (??) on page 2" in text
    assert "error:unresolved citations ([?]) on page 2" in text
    assert "warning:TODO" in text


# ------------------------------------------------------------------ LaTeX

MAIN_TEX = r"""\documentclass{article}
\usepackage[final]{neurips_2026}
%\usepackage[preprint]{neurips_2026}
\begin{document}
\section{Introduction}
See Table~\ref{tab:main} and Table~\ref{tab:gone}. Prior work \cite{known,unknown}.
\todo{add seeds}
\begin{table}\label{tab:main}\end{table}
\section{Acknowledgments}
Thanks.
\bibliography{refs}
\end{document}
"""


def test_latex_project_checks(tmp_path):
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (tmp_path / "refs.bib").write_text("@article{known,\n title={T}}\n", encoding="utf-8")
    result = check_latex(tmp_path, get_venue("neurips").rules)
    text = " | ".join(f"{f.level}:{f.message}" for f in result.findings)
    assert "camera-ready" in text and "[final]" in text
    assert "tab:gone" in text and "tab:main" not in text
    assert "unknown" in text and "known," not in text
    assert 'no "NeurIPS Paper Checklist" section' in text
    assert f"{WARNING}:main.tex: \\todo" in text
    assert "acknowledgements" in text
    assert any("page limit" in s for s in result.skipped)


def test_commented_out_switch_is_not_flagged(tmp_path):
    tex = MAIN_TEX.replace(r"\usepackage[final]{neurips_2026}", "")
    (tmp_path / "main.tex").write_text(tex, encoding="utf-8")
    result = check_latex(tmp_path, get_venue("neurips").rules)
    assert not any("camera-ready" in f.message for f in result.findings)


# ------------------------------------------------------------------ CLI


def test_cli_check_exit_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    clean = make_paper([page1(), [(80, "References", 12)]])
    (tmp_path / "clean.pdf").write_bytes(clean)
    (tmp_path / "prebuttal.toml").write_text('[default]\nvenue = "iclr"\n', encoding="utf-8")
    assert cli.main(["check", "clean.pdf"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "ICLR rules" in out and "No problems found." in out

    (tmp_path / "bad.pdf").write_bytes(make_paper([page1(extra=[(118, "a@b.org", 9)])]))
    assert cli.main(["check", "bad.pdf"]) == cli.EXIT_CHECK_FAILED
    assert cli.main(["check", "missing.pdf"]) == cli.EXIT_USAGE


def test_run_report_carries_the_preflight(tmp_path, monkeypatch, latex_project, fake_statuses):
    monkeypatch.chdir(tmp_path)
    (latex_project / "main.tex").write_text(
        (latex_project / "main.tex")
        .read_text(encoding="utf-8")
        .replace(r"\end{document}", r"See Table~\ref{tab:nowhere}.\end{document}"),
        encoding="utf-8",
    )
    cfg_path = tmp_path / "prebuttal.toml"
    cfg_path.write_text(FAKE_TOML, encoding="utf-8")
    rc = cli.main(
        ["run", str(latex_project), "--config", str(cfg_path), "--json", "o.json", "--out-dir", "r"]
    )
    assert rc == cli.EXIT_OK
    warnings = json.loads((tmp_path / "o.json").read_text(encoding="utf-8"))["paper"]["warnings"]
    assert any(w.startswith("Pre-flight check (error)") and "tab:nowhere" in w for w in warnings)
    assert "tab:nowhere" in latest_report(tmp_path / "r").read_text(encoding="utf-8")
