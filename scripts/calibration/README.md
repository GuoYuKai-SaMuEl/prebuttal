# Calibration (README asset)

This directory produces the calibration scatter plot shown in the main README:
Prebuttal's simulated ratings vs **real** OpenReview ratings for the same papers.

## What this is — and is not

- It **is** an honesty device: proof that the tool was *measured*, unlike random
  "act as Reviewer 2" prompts. Cross-model averaging shifts system bias; the
  scatter plot shows how much signal survives.
- It is **not** a claim of score prediction. Reviews are noisy; disagreement
  between real reviewers on the same paper is often larger than this tool's
  error. Quote MAE together with real-reviewer inter-rater spread or don't
  quote it at all.

## Run it

```bash
pip install "prebuttal[calibration]"
python scripts/calibration/calibrate.py \
    --venue-id ICLR.cc/2024/Conference --venue iclr -n 20 --out-dir calib_out
```

Cost note: 20 papers x (3 reviewers + AC) full runs. Use a `prebuttal.toml`
with cheap/free backends (Gemini free tier, agent CLIs) and a fixed `seed`
for reproducibility.

Outputs:

- `calib_out/pairs.json` — per-paper true vs predicted
- `calib_out/scatter.png` — the README figure

## Upgrading later

The natural next step (frozen until v0.1 has real users): the same script
becomes a public benchmark + leaderboard. Keep `--seed` and the config file
with the results; that's what makes the numbers defensible.
