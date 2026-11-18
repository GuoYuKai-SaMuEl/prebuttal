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


@pytest.mark.parametrize(
    "line, kept",
    [
        (r"a & b \\% trailing comment", r"a & b \\"),  # line break, then a comment
        (r"50\% of runs % comment", r"50\% of runs "),  # escaped percent sign
        (r"x \\\% y % comment", r"x \\\% y "),  # line break + escaped percent
        (r"% whole line", ""),
        (r"no comment", r"no comment"),
    ],
)
def test_strip_comments_counts_backslashes(line, kept):
    from prebuttal.ingestion.latex import _strip_comments

    assert _strip_comments(line) == kept


def test_bare_longtable_wide_rows_verbatim_percent_and_thanks(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"""\documentclass{article}
\title{My Paper\thanks{Funded by Grant 123}}
\begin{document}
\section{Appendix tables}
Before \hspace{2em}see Table~\ref{tab:long}.
\begin{longtable}[c]{lcc}
\caption{Per-task results}\label{tab:long}\\
Task & A & B \\
\endfirsthead
x & 91.2 & 93.4 \\
y & 1 & 2 & 3 \\
\end{longtable}
\begin{verbatim}
accuracy = 95% (top-1)
\end{verbatim}
Done. % a comment
\end{document}
""",
        encoding="utf-8",
    )
    paper = ingest(str(tmp_path))
    assert paper.title == "My Paper"  # the funding note is not part of it
    (t,) = paper.tables  # a longtable outside any table float
    assert t.caption == "Per-task results" and t.header == ["Task", "A", "B"]
    md = t.to_markdown()
    assert "93.4" in md and "| y | 1 | 2 | 3 |" in md  # the extra cell is kept
    text = paper.sections[0].text
    assert "Table 1" in text and "2em" not in text
    assert "95% (top-1)" in text and "a comment" not in text


def test_comment_stripping_around_verbatim_on_one_line():
    from prebuttal.ingestion.latex import _strip_comments

    src = "\n".join(
        [
            r"a \begin{verbatim}x = 50% y\end{verbatim} b % gone1",
            r"c % gone2",
            r"\begin{lstlisting}[caption={Acc (%)}]",
            r"z = 5 % 3",
            r"\end{lstlisting} % gone3",
        ]
    )
    out = _strip_comments(src)
    assert "50% y" in out and "5 % 3" in out and "Acc (%)" in out
    assert not any(g in out for g in ("gone1", "gone2", "gone3"))


@pytest.mark.parametrize(
    "src",
    [
        r"\newcommand{\foo}[1]{bar #1}Hello",
        r"\newcommand{\foo}[2][d]{bar}Hello",
        r"\setlength\tabcolsep{4pt}Hello",
        r"\renewcommand\arraystretch{1.2}Hello",
        r"\includegraphics[width=1cm]{fig.png}Hello",
    ],
)
def test_dropped_commands_take_all_their_arguments(src):
    from prebuttal.ingestion.latex import _clean_inline

    assert _clean_inline(src).strip() == "Hello"


def test_longtable_head_and_foot_count_once(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"""\documentclass{article}
\begin{document}
\section{Appendix}
\begin{longtable}{lc}
\caption{Results}\label{tab:r}\\
Model & Score \\
\endfirsthead
\caption*{Results (continued)}\\
Model & Score \\
\endhead
\multicolumn{2}{r}{continued on next page} \\
\endfoot
Note & end \\
\endlastfoot
Ours & 95.0 \\
\end{longtable}
\end{document}
""",
        encoding="utf-8",
    )
    (t,) = ingest(str(tmp_path)).tables
    assert t.caption == "Results" and t.header == ["Model", "Score"]
    assert t.rows == [["Ours", "95.0"], ["Note", "end"]]


def test_starred_verbatim_ends_only_at_its_own_end_and_image_tables_are_clean(tmp_path):
    from prebuttal.ingestion.latex import _strip_comments

    src = "\n".join(
        [
            r"\begin{Verbatim*}",
            r"\end{Verbatim} 50% literal",  # not the end of Verbatim*
            r"\end{Verbatim*} % gone",
        ]
    )
    out = _strip_comments(src)
    assert "50% literal" in out and "gone" not in out

    (tmp_path / "main.tex").write_text(
        r"""\documentclass{article}
\begin{document}
\section{Results}
\begin{table}[htbp]
\centering
\includegraphics[width=0.8\textwidth, clip]{table1.pdf}
\caption{Main results}
\end{table}
\end{document}
""",
        encoding="utf-8",
    )
    (t,) = ingest(str(tmp_path)).tables
    assert t.caption == "Main results"
    assert "clip" not in t.raw and "table1" not in t.raw and "Main results" not in t.raw
    assert "htbp" not in t.raw


_BIB = r"""
@string{nips = "Advances in Neural Information Processing Systems"}
@inproceedings{vaswani2017,
  author = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki and Uszkoreit, Jakob},
  title = {Attention Is All You Need},
  booktitle = nips # " 30",
  year = 2017,
}
@article(he2016,
  author = "Kaiming He and Xiangyu Zhang",
  title = "{Deep} Residual Learning",
  journal = {CVPR},
  year = {2016}
)
@misc{unused2020, title = {Secret Unpublished Detail}, year = {2020}}
"""


def _bib_paper(tmp_path, cites: str):
    from prebuttal.ingestion.latex import ingest_latex_source

    (tmp_path / "refs.bib").write_text(_BIB, encoding="utf-8")
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\title{T}\begin{document}\section{Intro}"
        + f"Text {cites}.\n"
        + r"\bibliography{refs}\end{document}",
        encoding="utf-8",
    )
    paper = ingest_latex_source(tmp_path / "main.tex")
    refs = [s for s in paper.sections if s.title == "References"]
    return (refs[0].text if refs else ""), paper.warnings


def test_a_source_without_its_bbl_lists_the_cited_bib_entries(tmp_path):
    # an Overleaf download: main.tex and refs.bib, no .bbl
    text, warnings = _bib_paper(tmp_path, r"\citep{he2016} and \cite{vaswani2017,he2016}")
    assert text.splitlines() == [  # in order of first citation
        "[1] Kaiming He, Xiangyu Zhang. Deep Residual Learning. CVPR, 2016.",
        "[2] Ashish Vaswani et al. Attention Is All You Need. "
        "Advances in Neural Information Processing Systems 30, 2017.",
    ]
    assert "Secret" not in text  # only what the paper cites
    assert not any("references not included" in w for w in warnings)


def test_nocite_star_lists_every_bib_entry(tmp_path):
    text, _w = _bib_paper(tmp_path, r"\cite{he2016}\nocite{*}")
    assert text.startswith("[1] Kaiming He") and "Secret Unpublished Detail" in text
