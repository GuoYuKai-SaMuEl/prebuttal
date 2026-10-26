# Test fixtures

- `demo-paper.pdf` — `examples/demo-paper` compiled with pdflatex.

Real-paper regression tests (`tests/test_pdf_real_papers.py`) do not ship
their PDFs: they download pinned arXiv versions on first use into
`~/.cache/prebuttal/test-papers` (or `$PREBUTTAL_PAPER_CACHE`), and only when
`PREBUTTAL_REAL_PAPERS=1` is set — otherwise they are skipped, so the default
test run stays offline. CI runs them in a dedicated job with the cache saved
between runs.

    PREBUTTAL_REAL_PAPERS=1 python -m pytest tests/test_pdf_real_papers.py
