# Loan Eval Decision Engine

A rule-based loan-application decision engine with **differentiated confidence
thresholds**, a **no-credit-history recovery path**, and a **segment-level bias
audit** that detects and closes a real fairness gap — all runnable, with output
you can inspect directly (`run_output.txt`).

```
python3 run_demo.py
```

## What it does

Scores loan applicants on credit score, debt-to-income ratio, and employment
history, then routes each to **Approved**, **Rejected**, or **Conditional**
(human review) using asymmetric confidence bars rather than one blanket
threshold: 97% confidence to auto-approve, 95% to auto-reject, and anything
under 85% confidence — in either direction — goes to a human. The gap between
85–97% approve-side and 5–15% reject-side is a *deliberate* no-auto-decide
zone: cases the system isn't sure enough about don't get guessed on.

## The interesting part: catching and fixing a fairness bug

Applicants with no credit history are a known failure mode for naive
underwriting systems — "no data" gets silently treated as "bad data." This
engine instead falls back to 6 months of bank statement stability as an
alternative signal. `audit.py` runs a **segment-level bias audit**: comparing
decision rates for the no-history segment against a matched segment with
comparable income/employment but an established credit history.

Run `run_demo.py` and you'll see the audit run twice — once with the recovery
path disabled (reproducing the naive failure mode) and once with it enabled:

| | No-credit-history reject rate | Matched-segment reject rate |
|---|---|---|
| **Naive** (no recovery path) | 100% | 0% |
| **This engine** (recovery path) | 0% | 0% |

That's the failure mode made visible and then closed, not just described.

## Files

- `decision_engine.py` — the scoring model and threshold routing.
- `test_dataset.py` — applicant test cases: clean sweep cases, three
  credit/DTI/employment interaction profiles, and a no-credit-history segment
  matched against a comparable credit-history segment.
- `audit.py` — the segment-level bias audit (naive vs. recovery-path).
- `run_demo.py` — runs everything and prints the full report.
- `run_output.txt` — captured output from an actual run.

## Design notes

- `risk_score` is treated as P(approve); confidence is derived from how far
  that score sits from 0.5 (`max(p, 1-p)`) — scores near the extremes mean the
  signals agree strongly, scores near the middle mean they conflict. This
  naturally makes ambiguous, conflicting-signal cases (like the three
  interaction profiles below) land in human review, without hand-tuning a
  separate uncertainty rule for each one.
- The three interaction profiles were chosen because a model that reacts to
  each variable independently — rather than their interaction — gets them
  wrong: low credit score with strong offsetting factors, high credit score
  undermined by high DTI, and short tenure that shouldn't outweigh otherwise
  solid financials.
- The no-history recovery path is deliberately capped below what an
  established credit history can reach: bank-statement data is informative
  but not as proven a signal, and a system that pretended otherwise would be
  overconfident in the wrong direction.

## Background

This started as Guide 1, Assignment 1 in a self-directed FDE (Forward
Deployed Engineer) learning program — "design a complete evaluation framework
for a bank loan-approval AI." That assignment (metrics, thresholds, and the
no-credit-history failure mode + recovery path) is what this engine
implements end to end. The original design write-up focused on *how you'd
evaluate* such a system before trusting it; this repo is that design made
runnable, plus the audit that proves the recovery path actually works.

## Status / limitations

- The scoring model is a transparent heuristic, not a trained classifier —
  intentional, since the point of this project is the eval design (thresholds,
  metrics, bias detection), not model training. A trained model's calibrated
  probability output would drop in in place of `_score_with_credit_history`
  with no changes needed downstream.
- The test dataset here (14 applicants) is a demo-sized subset of the ~90-100
  case dataset the original design called for; it's built to exercise every
  path (clean approve/reject, interaction profiles, both no-history variants),
  not to be a statistically powered sample.
