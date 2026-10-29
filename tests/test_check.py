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
    over = [page1(), body(30), body(30), [*body(10, 80), (300, "References", 12), *body(5, 320)]]
    result = check_pdf_bytes(make_paper(over), CheckRules(page_limit=3))
    assert any("runs to page 4" in f.message for f in result.errors)
    # References at the very top of page 4: the main text ended on page 3
    top = [page1(), body(30), body(30), [(60, "References", 12), *body(5, 80)]]
    assert check_pdf_bytes(make_paper(top), CheckRules(page_limit=3)).errors == []


def test_page_limit_with_a_centred_references_heading():
    """ACL-style centred heading: reference entries below a lone centred
    heading are not a second column, so a references-only page does not count."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    height = A4[1]
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, height - 80, "Deep Widgets for Structured Prediction")
    c.setFont("Helvetica", 10)
    for i in range(10):
        c.drawString(72, height - 140 - 14 * i, f"Body sentence number {i} about widgets.")
    c.showPage()
    c.setFont("Helvetica-Bold", 12)
    c.drawString(290, height - 100, "References")  # centred on the page
    c.setFont("Helvetica", 10)
    for i in range(12):
        c.drawString(72, height - 160 - 14 * i, f"Some Author {i}. A journal paper, 2020.")
    c.showPage()
    c.save()
    result = check_pdf_bytes(buf.getvalue(), CheckRules(page_limit=1))
    assert result.errors == []
    assert "main text 1 of 1 pages" in result.passed


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


AUTHOR_TEX = r"""\documentclass{article}
%s
\author{Alice Smith \and Bob Jones \\ University of Awesome}
\begin{document}
\section{Introduction}
Text.
\end{document}
"""


@pytest.mark.parametrize(
    "preamble, flagged",
    [
        ("", True),
        (r"\usepackage{iclr2027_conference}", False),
        (r"\usepackage{neurips_2026}", False),
        (r"\usepackage{icml2026}", False),
        (r"\usepackage[review]{acl}", False),
        (r"\usepackage{acl}", True),  # acl.sty without [review] is the final version
        (r"\usepackage{hyperref,amsmath}", True),
    ],
)
def test_latex_author_names_without_an_anonymizing_style(tmp_path, preamble, flagged):
    (tmp_path / "main.tex").write_text(AUTHOR_TEX % preamble, encoding="utf-8")
    result = check_latex(tmp_path, get_venue("iclr").rules)
    hits = [f for f in result.findings if "\\author{" in f.message]
    assert bool(hits) == flagged
    if flagged:
        assert "Alice Smith" in hits[0].message and hits[0].level == WARNING


def test_anonymous_author_is_not_flagged(tmp_path):
    tex = (AUTHOR_TEX % "").replace(r"Alice Smith \and Bob Jones \\ University", "Anonymous")
    (tmp_path / "main.tex").write_text(tex, encoding="utf-8")
    result = check_latex(tmp_path, get_venue("iclr").rules)
    assert not any("\\author{" in f.message for f in result.findings)


@pytest.mark.parametrize(
    "line, unresolved",
    [
        ("As Table ?? shows", True),
        ("see Sec.~?? and (??).", True),
        ("Figure??", True),
        ("?? is how LaTeX prints it", True),
        ('the reviewer asked "what??"', False),
        ("really??? no", False),
    ],
)
def test_bare_question_marks(line, unresolved):
    from prebuttal.check import _UNRESOLVED_REF

    assert bool(_UNRESOLVED_REF.search(line)) == unresolved


def test_neurips_nonanonymous_option_is_flagged(tmp_path):
    tex = MAIN_TEX.replace("[final]{neurips_2026}", "[eandd, nonanonymous]{neurips_2026}")
    (tmp_path / "main.tex").write_text(tex, encoding="utf-8")
    result = check_latex(tmp_path, get_venue("neurips").rules)
    assert any("nonanonymous" in f.message and f.level == ERROR for f in result.findings)


def test_commented_out_switch_is_not_flagged(tmp_path):
    tex = MAIN_TEX.replace(r"\usepackage[final]{neurips_2026}", "")
    (tmp_path / "main.tex").write_text(tex, encoding="utf-8")
    result = check_latex(tmp_path, get_venue("neurips").rules)
    assert not any("camera-ready" in f.message for f in result.findings)


def test_macro_parameters_and_natbib_settings_are_not_keys(tmp_path):
    """`\\ref{#1}` inside a \\newcommand, `\\nocite{*}` and `\\citestyle{...}`."""
    (tmp_path / "main.tex").write_text(
        r"""\documentclass{article}
\newcommand{\figref}[1]{Figure~\ref{#1}}
\citestyle{plainnat}
\begin{document}
\section{Intro}
See \figref{fig:a}, \citet{known} and \citep[p.~3]{known}.
\begin{figure}\label{fig:a}\end{figure}
\nocite{*}
\bibliography{refs}
\end{document}
""",
        encoding="utf-8",
    )
    (tmp_path / "refs.bib").write_text("@article{known,\n title={T}}\n", encoding="utf-8")
    result = check_latex(tmp_path, CheckRules())
    assert result.errors == []
    assert "all 1 cited keys are in the bibliography" in result.passed


def _two_column(last_right_column: bool) -> bytes:
    """Three letter pages, two columns; References starts the last page's right
    column (left column still main text) or its left column (nothing before it)."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    height = letter[1]
    for page in range(3):
        last = page == 2
        for x in (54, 320):
            refs_here = last and (x == 320) == last_right_column
            if last and not refs_here and not last_right_column:
                continue  # after References in the left column: no more main text
            c.setFont("Helvetica-Bold" if refs_here else "Helvetica", 11 if refs_here else 9)
            if refs_here:
                c.drawString(x, height - 76, "References")
                continue
            for i in range(50):
                c.drawString(x, height - 72 - 12 * i, f"Body line {i} of page {page + 1}.")
        c.showPage()
    c.save()
    return buf.getvalue()


def test_two_column_page_counts_when_its_left_column_is_main_text():
    rules = CheckRules(page_limit=2)
    result = check_pdf_bytes(_two_column(last_right_column=True), rules)
    assert any("runs to page 3" in f.message for f in result.errors)
    # References opening the left column: the main text ended on page 2
    assert check_pdf_bytes(_two_column(last_right_column=False), rules).errors == []


def test_custom_venue_required_sections_do_not_count_toward_the_limit():
    from prebuttal.venues.custom import _checks

    rules = _checks({"page_limit": 8, "required_sections": ["Limitations"]})
    assert "Limitations" in rules.uncounted and "References" in rules.uncounted
    with pytest.raises(Exception, match="unknown setting"):
        _checks({"uncounted": ["X"]})


# ------------------------------------------------------------------ CLI


def test_cli_check_venue_flag(tmp_path, monkeypatch, capsys):
    """Most users have no prebuttal.toml: `check` takes --venue like `run`."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "p.pdf").write_bytes(make_paper([page1(), [(80, "References", 12)]]))
    assert cli.main(["check", "p.pdf", "--venue", "icml"]) == cli.EXIT_CHECK_FAILED
    out = capsys.readouterr().out
    assert "ICML rules" in out and 'no "Impact Statement" section' in out
    assert cli.main(["check", "p.pdf", "--venue", "nope"]) == cli.EXIT_USAGE


def test_run_skips_the_preflight_for_arxiv_papers(monkeypatch):
    """A public arXiv paper is camera-ready: its 'problems' would only be noise."""
    from prebuttal import check

    def boom(*a, **k):
        raise AssertionError("check_source must not run for arXiv sources")

    monkeypatch.setattr(check, "check_source", boom)
    assert cli._preflight("2312.00752", get_venue("iclr")) == []


def test_run_survives_a_broken_preflight(tmp_path, monkeypatch):
    from prebuttal import check

    def broken(*a, **k):
        raise RuntimeError("pdfminer exploded")

    monkeypatch.setattr(check, "check_source", broken)
    (tmp_path / "p.pdf").write_bytes(b"%PDF-1.4")
    found = cli._preflight(str(tmp_path / "p.pdf"), get_venue("iclr"))
    assert found == ["Pre-flight check skipped: pdfminer exploded"]


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


def test_stored_keys_load_only_for_commands_that_call_models(
    tmp_path, monkeypatch, capsys, latex_project, fake_statuses
):
    """`check` calls no model: no keys in the environment, no "using stored keys"."""
    import os

    from prebuttal import keys

    monkeypatch.chdir(tmp_path)
    # setenv first so monkeypatch restores the real state afterwards
    monkeypatch.setenv("GEMINI_API_KEY", "placeholder")
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setattr(keys, "_applied", set())
    keys.store_key("GEMINI_API_KEY", "AIzaStored1234567")
    (tmp_path / "p.pdf").write_bytes(make_paper([page1(), [(80, "References", 12)]]))

    for argv in (["check", "p.pdf", "--venue", "iclr"], ["runs"], ["venues"]):
        cli.main(argv)
        assert "using stored keys" not in capsys.readouterr().err
        assert "GEMINI_API_KEY" not in os.environ

    cfg_path = tmp_path / "prebuttal.toml"
    cfg_path.write_text(FAKE_TOML, encoding="utf-8")
    cli.main(["run", str(latex_project), "--config", str(cfg_path), "--out-dir", "r"])
    assert "using stored keys: GEMINI_API_KEY" in capsys.readouterr().err
