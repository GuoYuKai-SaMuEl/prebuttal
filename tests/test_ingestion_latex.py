import pytest

from prebuttal.ingestion import ingest
from prebuttal.ingestion.latex import LatexError, ingest_latex_source


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


def test_starred_floats_counted_once_in_document_order(tmp_path):
    """Regression: `table*` was captured by both the `table` and `table*` passes
    (duplicate table, shifted numbers, \\ref resolving to the duplicate)."""
    (tmp_path / "main.tex").write_text(
        r"""\documentclass{article}
\begin{document}
\section{Results}
Wide is Table~\ref{tab:wide}, narrow is Table~\ref{tab:narrow}, plot is Figure~\ref{fig:b}.
\begin{table*}
\caption{Wide}\label{tab:wide}
\begin{tabular}{cc} a & b \\ 1 & 2 \\ \end{tabular}
\end{table*}
\begin{table}
\caption{Narrow}\label{tab:narrow}
\begin{tabular}{cc} c & d \\ 3 & 4 \\ \end{tabular}
\end{table}
\begin{figure*}\caption{Alpha}\label{fig:a}\end{figure*}
\begin{figure}\caption{Beta}\label{fig:b}\end{figure}
\end{document}
""",
        encoding="utf-8",
    )
    paper = ingest_latex_source(tmp_path)
    assert [(t.number, t.caption) for t in paper.tables] == [("1", "Wide"), ("2", "Narrow")]
    assert [(f.number, f.caption) for f in paper.figures] == [("1", "Alpha"), ("2", "Beta")]
    text = paper.sections[0].text
    assert "Wide is Table 1" in text and "narrow is Table 2" in text
    assert "plot is Figure 2" in text


def test_tabular_star_column_spec_not_in_cells(tmp_path):
    """Regression: `tabular` also matched `tabular*`, leaking `{lcc}` into cell 1."""
    (tmp_path / "main.tex").write_text(
        r"""\documentclass{article}
\begin{document}
\section{Results}
\begin{table}
\caption{Star}
\begin{tabular*}{\linewidth}{lcc} Model & Acc & F1 \\ Ours & 91.2 & 88.0 \\ \end{tabular*}
\end{table}
\end{document}
""",
        encoding="utf-8",
    )
    t = ingest_latex_source(tmp_path).tables[0]
    assert t.header == ["Model", "Acc", "F1"]
    assert t.rows == [["Ours", "91.2", "88.0"]]


def test_nested_input_resolves_from_root_dir(tmp_path):
    """Regression: a nested \\input resolved against the including file's folder
    (LaTeX uses the root's), and an unresolved input vanished without a trace."""
    (tmp_path / "sections").mkdir()
    (tmp_path / "main.tex").write_text(
        r"""\documentclass{article}
\begin{document}
\section{Intro}
\input{sections/body}
\end{document}
""",
        encoding="utf-8",
    )
    (tmp_path / "sections" / "body.tex").write_text(
        "BODY-START \\input{sections/inner} \\input{sections/missing} BODY-END\n",
        encoding="utf-8",
    )
    (tmp_path / "sections" / "inner.tex").write_text("INNER-TEXT\n", encoding="utf-8")

    paper = ingest_latex_source(tmp_path)
    text = paper.sections[0].text
    assert "BODY-START INNER-TEXT BODY-END" in text
    assert any("sections/missing" in w for w in paper.warnings)


def test_input_relative_to_including_file_still_works(tmp_path):
    """Fallback kept: projects that \\input siblings by bare name still parse."""
    (tmp_path / "sections").mkdir()
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}\\section{Intro}"
        "\\input{sections/body}\\end{document}",
        encoding="utf-8",
    )
    (tmp_path / "sections" / "body.tex").write_text("A \\input{sibling} B\n", encoding="utf-8")
    (tmp_path / "sections" / "sibling.tex").write_text("SIBLING\n", encoding="utf-8")
    paper = ingest_latex_source(tmp_path)
    assert "A SIBLING B" in paper.sections[0].text
    assert paper.warnings == [] or not any("not found" in w for w in paper.warnings)


def test_input_outside_the_project_is_not_read(tmp_path):
    """The merged text goes to a model provider: a hostile source must not be
    able to pull in ~/.ssh keys or other local files via \\input."""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-KEY\n", encoding="utf-8")
    proj = tmp_path / "paper"
    proj.mkdir()
    (proj / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}\\section{Intro}\n"
        f"A \\input{{../secret.txt}} B \\input{{{secret.as_posix()}}} C\n"
        "\\end{document}",
        encoding="utf-8",
    )
    paper = ingest_latex_source(proj)
    text = paper.sections[0].text
    assert "TOP-SECRET-KEY" not in text
    assert "A B C" in " ".join(text.split())
    assert sum("outside the paper's folder" in w for w in paper.warnings) == 2


def test_input_from_a_subfolder_root_may_reach_the_project_folder(tmp_path):
    """The project folder passed on the command line is the boundary, not the
    root file's own folder."""
    (tmp_path / "src").mkdir()
    (tmp_path / "shared.tex").write_text("SHARED-TEXT\n", encoding="utf-8")
    (tmp_path / "src" / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}\\section{Intro}"
        "\\input{../shared}\\end{document}",
        encoding="utf-8",
    )
    assert "SHARED-TEXT" in ingest_latex_source(tmp_path).sections[0].text


def test_bare_input_without_braces(tmp_path):
    (tmp_path / "sections").mkdir()
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Intro}\n"
        "\\input sections/body\n\\includegraphics{fig.png}\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "sections" / "body.tex").write_text("BARE-INPUT-TEXT\n", encoding="utf-8")
    paper = ingest_latex_source(tmp_path)
    assert "BARE-INPUT-TEXT" in paper.sections[0].text
    assert not any("fig.png" in w for w in paper.warnings)


def test_single_tex_file(tmp_path):
    (tmp_path / "solo.tex").write_text(
        r"\documentclass{article}\begin{document}\title{Solo}\maketitle"
        r"\section{One}hello \LaTeX\ world\end{document}",
        encoding="utf-8",
    )
    paper = ingest_latex_source(tmp_path / "solo.tex")
    assert paper.title == "Solo"
    assert paper.sections[0].number == "1"


def test_lists_and_math_survive_cleaning(tmp_path):
    # reviewers flagged "broken itemize markup" and an "unnumbered equation"
    # that were artifacts of this conversion, not of the paper
    (tmp_path / "m.tex").write_text(
        r"""\documentclass{article}\begin{document}\section{Method}
We contribute:
\begin{itemize}
\item a gate $\sigma(g_h)$ costing \$5;
\item[(b)] a proof.\footnote{See $\alpha$.}
\end{itemize}
\begin{equation}\mathrm{y} = \sigma(x)\label{eq:a}\end{equation}
\begin{align} a &= b \\ c &= d \nonumber \\ e &= f \label{eq:c}\end{align}
\begin{equation*} z = 0 \end{equation*}
By Eq.~\eqref{eq:a} and Eq.~\eqref{eq:c} it holds.
\end{document}""",
        encoding="utf-8",
    )
    text = ingest_latex_source(tmp_path / "m.tex").sections[0].text
    assert "itemize" not in text
    assert "\n- a gate $\\sigma(g_h)$ costing $5;\n- (b) a proof. [note: See $\\alpha$.]" in text
    assert "$$\\mathrm{y} = \\sigma(x)$$ (1)" in text
    assert "$$a &= b \\\\ c &= d \\\\ e &= f$$ (2) (3)" in text
    assert "$$z = 0$$ By Eq. (1) and Eq. (3) it holds." in text


def _symlink(link, target):
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available (Windows without developer mode)")


def test_symlinked_bbl_outside_the_project_is_not_read(tmp_path):
    secret = tmp_path / "secret.bbl"
    secret.write_text("\\bibitem{k} TOP-SECRET-KEY\n", encoding="utf-8")
    proj = tmp_path / "paper"
    proj.mkdir()
    (proj / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}\\section{Intro}\nText.\n\\end{document}",
        encoding="utf-8",
    )
    (proj / "main.bbl").write_text("\\bibitem{k} OWN-ENTRY\n", encoding="utf-8")
    texts = [s.text for s in ingest_latex_source(proj).sections]
    assert any("OWN-ENTRY" in t for t in texts)  # a real .bbl is read
    (proj / "main.bbl").unlink()
    _symlink(proj / "main.bbl", secret)
    paper = ingest_latex_source(proj)
    assert all("TOP-SECRET-KEY" not in s.text for s in paper.sections)


def test_symlinked_root_tex_outside_the_project_is_refused(tmp_path):
    outside = tmp_path / "elsewhere.tex"
    outside.write_text(
        "\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8"
    )
    proj = tmp_path / "paper"
    proj.mkdir()
    _symlink(proj / "main.tex", outside)
    with pytest.raises(LatexError):
        ingest_latex_source(proj)


def test_section_levels_and_unnumbered_sections(tmp_path):
    """Each section keeps its own level; \\section* gets no number and does not
    shift the numbering that the PDF shows."""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}\n"
        "\\section{Intro}a\n\\section*{Limitations}b\n\\section{Method}c\n"
        "\\subsection{Detail}d\n\\end{document}\n",
        encoding="utf-8",
    )
    got = [(s.number, s.title, s.level) for s in ingest_latex_source(tmp_path).sections]
    assert got[:4] == [
        ("1", "Intro", 1),
        ("", "Limitations", 1),
        ("2", "Method", 1),
        ("2.1", "Detail", 2),
    ]
