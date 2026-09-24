# LendFair

_Loan decisions that explain themselves, learn from repayment outcomes, and stop auto-rejecting a segment when it is treated unfairly. No threshold changes without a human._

[![ci](https://github.com/varunluniya/lendfair/actions/workflows/ci.yml/badge.svg)](https://github.com/varunluniya/lendfair/actions/workflows/ci.yml)

## What's new in v2: an intelligent, deployable service

The v1 scoring engine is unchanged. v2 wraps it in the four Gen-4 layers:

| Layer | In LendFair |
|---|---|
| **Retrieval** | Cites the credit-policy and fair-lending sections behind every decision (`knowledge/`) |
| **Context** | Applicant segment, live reject-rate gap vs a matched segment, thresholds in force |
| **Memory** | Every decision + its repayment outcome; k-NN "what happened to applicants like this?" |
| **Feedback** | Calibration (Brier/ECE), auto-approve default guardrail, threshold proposals a human approves |

Three behaviours the static engine cannot do:

1. **Blind-spot escalation.** If similar past applicants defaulted while the model is confident, the case goes to a human. Memory can only escalate; it never auto-decides.
2. **Live fairness brake.** If no-credit-history applicants are rejected >10 pp more than a matched segment, auto-rejects for that segment pause.
3. **Grounded adverse-action reasons.** Ranked factors, each with what would change the outcome.

**Proof** (`python simulate_learning.py`): in a world with a hidden blind spot, the auto-approve default rate goes 18.7% → 5.5% → 1.1% → 0.0% across three phases as outcomes arrive, while the static engine stays at 15–20%. The full five-part write-up is in [FRAMEWORK.md](FRAMEWORK.md).

## Run it

```bash
pip install -r requirements-dev.txt
uvicorn app:app --reload            # http://127.0.0.1:8000/docs
python -m pytest -q                 # unit + API tests
python run_evals.py                 # eval gate: 21 cases x 3 runs, exits 1 on regression
python simulate_learning.py         # the before/after proof
```

Docker: `docker build -t lendfair . && docker run -p 8000:8000 -v lendfair-data:/data lendfair`
Render: New → Blueprint → this repo (`render.yaml`). Set `ANTHROPIC_API_KEY` to have a live model write explanations. Without it, the service runs in offline mode and says so in every trace.

```bash
curl -X POST localhost:8000/decide -H 'content-type: application/json' -d '{"applicant_id":"a1","credit_score":710,"debt_to_income":0.32,"employment_years":1.5,"annual_income":64000,"has_credit_history":true}'
curl -X POST localhost:8000/feedback -H 'content-type: application/json' -d '{"decision_id":"<id>","repaid":true}'
curl localhost:8000/audit/fairness
```

| Endpoint | Purpose |
|---|---|
| `POST /decide` | Decision, principal reasons, explanation, full Gen-4 trace |
| `POST /feedback` | Repayment outcome → calibration, guardrail, proposals |
| `GET /audit/fairness` · `GET /calibration` | Live monitors |
| `GET /proposals` · `POST /proposals/{param}/approve` | Human-approved learning |
| `GET /knowledge/search` · `/memory/facts` · `/params` · `/health` | Inspect each layer |

**New files:** `service.py` (Gen-4 wiring) · `app.py` (API) · `gen4/` (shared kernel) · `knowledge/` · `run_evals.py` · `simulate_learning.py` · `tests/` · `Dockerfile` · `render.yaml` · `.github/workflows/ci.yml`

## Demo data

`python seed.py` fills `data/lendfair.db` with synthetic history so every endpoint returns something meaningful on first run: 720 applications over 12 months (prime, distressed, thin-file and a hidden blind-spot pocket), repayment outcomes for disbursed loans older than 120 days, memory escalations, and one pending threshold proposal from the default guardrail.

```bash
python seed.py            # create data/lendfair.db
python seed.py --reset    # rebuild it from scratch
```

The Docker image seeds `/data` on first boot (set `GEN4_SEED=0` to start empty). All of it is synthetic: no real customers, patients, tickets or model outputs. `GET /health` shows the dataset's counts.

---

## The original engine (v1)

The v1 demo still runs unchanged; the service wraps it.

_A loan decision engine with differentiated confidence thresholds and a segment-level bias audit._


A rule-based loan-application decision engine with **differentiated confidence
thresholds**, a **no-credit-history recovery path**, and a **segment-level bias
audit** that detects and closes a real fairness gap — all runnable, with output
you can inspect directly (`run_output.txt`).

```
python3 run_demo.py
```

### What it does

Scores loan applicants on credit score, debt-to-income ratio, and employment
history, then routes each to **Approved**, **Rejected**, or **Conditional**
(human review) using asymmetric confidence bars rather than one blanket
threshold: 97% confidence to auto-approve, 95% to auto-reject, and anything
under 85% confidence — in either direction — goes to a human. The gap between
85–97% approve-side and 5–15% reject-side is a *deliberate* no-auto-decide
zone: cases the system isn't sure enough about don't get guessed on.

### The interesting part: catching and fixing a fairness bug

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

### Files

- `decision_engine.py` — the scoring model and threshold routing.
- `test_dataset.py` — applicant test cases: clean sweep cases, three
  credit/DTI/employment interaction profiles, and a no-credit-history segment
  matched against a comparable credit-history segment.
- `audit.py` — the segment-level bias audit (naive vs. recovery-path).
- `run_demo.py` — runs everything and prints the full report.
- `run_output.txt` — captured output from an actual run.

### Design notes

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

### Why this exists

Most "AI loan approval" demos show a model making decisions. This one is about the harder, less glamorous problem underneath: how do you actually evaluate whether such a system is safe to trust — differentiated confidence thresholds, a documented failure mode, and an audit that proves the fix works? This repo is that eval design made runnable, plus the audit that proves the recovery path actually closes the gap.

### Status / limitations

- The scoring model is a transparent heuristic, not a trained classifier —
  intentional, since the point of this project is the eval design (thresholds,
  metrics, bias detection), not model training. A trained model's calibrated
  probability output would drop in in place of `_score_with_credit_history`
  with no changes needed downstream.
- The test dataset here (14 applicants) is a demo-sized subset of the ~90-100
  case dataset the original design called for; it's built to exercise every
  path (clean approve/reject, interaction profiles, both no-history variants),
  not to be a statistically powered sample.
