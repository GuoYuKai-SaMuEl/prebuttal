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
