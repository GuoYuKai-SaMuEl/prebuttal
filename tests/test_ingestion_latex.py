from prebuttal.ingestion import ingest
from prebuttal.ingestion.latex import ingest_latex_source


def test_latex_project_full_parse(latex_project):
    paper = ingest_latex_source(latex_project)

    assert paper.source_type == "latex"
    assert "Latent Bottleneck" in paper.title
    assert "97.3" in paper.abstract
    assert "61% less memory" in paper.abstract  # \% unescaped

    headings = [s.heading for s in paper.sections]
    # numbered sections resolved across \input merge, appendix lettered
    assert any(h.startswith("1 Introduction") for h in headings)
    assert any(h.startswith("2 Method") for h in headings)
    assert any(h.startswith("2.1 Routing") for h in headings)
    assert any(h.startswith("3 Experiments") for h in headings)
    assert any(h.startswith("A Hyperparameters") for h in headings)
    assert any(s.title == "References" for s in paper.sections)

    # references from .bbl
    refs = next(s for s in paper.sections if s.title == "References")
    assert "Vaswani" in refs.text

    # comments must not leak
    assert "a comment line" not in paper.abstract + "".join(s.text for s in paper.sections)

    # --- the moat: cell-accurate table
    assert len(paper.tables) == 1
    t = paper.tables[0]
    assert t.source == "latex-tabular"
    assert t.header == ["Model", "Score", "Mem"]
    assert t.rows[0] == ["Full", "96.8", "41.2"]
    assert "97.3" in t.rows[-1]
    assert "16.1" in t.rows[-1]
    # \multicolumn{2}{c}{Ours} expands to two cells
    mc = t.rows[1]
    assert mc[0] == "Ours" and mc[1] == "" and mc[2] == "16.1"

    # refs resolved to display numbers in body text
    intro = next(s for s in paper.sections if s.heading.startswith("1 Introduction"))
    assert "Table 1" in intro.text  # \ref{tab:main} -> 1
    assert "Section 2" in intro.text  # \ref{sec:method} -> 2
    assert "(1)" in intro.text  # \eqref{eq:route} -> (1)
    routing = next(s for s in paper.sections if s.heading.startswith("2.1 Routing"))
    assert "softmax" in routing.text  # math content survives cleaning

    # figure caption captured
    assert any(f.caption.startswith("Quality vs") for f in paper.figures)

    # table attached to its section
    assert "3 Experiments" in t.section


def test_ingest_dispatch_dir(latex_project):
    paper = ingest(str(latex_project))
    assert paper.tables and paper.tables[0].rows


def test_single_tex_file(tmp_path):
    (tmp_path / "solo.tex").write_text(
        r"\documentclass{article}\begin{document}\title{Solo}\maketitle"
        r"\section{One}hello \LaTeX\ world\end{document}",
        encoding="utf-8",
    )
    paper = ingest_latex_source(tmp_path / "solo.tex")
    assert paper.title == "Solo"
    assert paper.sections[0].number == "1"
