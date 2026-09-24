# LendFair — FDE Framework Build Notes

How the LendFair demo became an intelligent system, following the five parts of the FDE framework.

## Part 1 — Problem Reframing

| Step | Output |
|---|---|
| Ordinary problem | "Automate loan approvals." |
| Lever 1: Data liquidity | Repayment outcomes sit in the loan-servicing system and never reach the decision engine. Bank-statement cash flow is collected and then ignored for thin-file applicants. |
| Lever 2: Network effect | Each repaid or defaulted loan adds a labelled neighbour. At 10 loans the memory is empty; at 1,000 it can find blind spots, like a pocket of profiles the model trusts but that default. |
| Lever 3: Algorithmic leverage | Asymmetric thresholds plus a memory check that can only escalate. The model is never overruled into an auto-decision; it can only be sent to a human. That makes learning safe to switch on in a regulated flow. |
| Lever 4: First principles × JTBD | The lender's real job is "approve the most good borrowers without a fairness or loss incident I can't explain", not "decide fast". Speed is a side effect of confidence. |
| Extraordinary problem | Build a lending decision system that **explains every decision, catches its own blind spots from real repayment outcomes, and stops itself when a segment is being treated unfairly**, while never changing a threshold without human sign-off. |
| Rating | 4 / 5. The reframe moves the system from a static scorer to one that monitors and corrects itself. |

## Part 2 — Design the Eval

**Outcome of intelligence (measurable)**
- Auto-approved loans default at ≤ 5% (Wilson upper bound, n ≥ 30). This is the `auto_approved_default_rate` guardrail.
- The no-credit-history reject rate stays within 10 pp of the matched segment.
- Every non-approval names at least one concrete principal reason.
- Policy decisions are 100% consistent across repeated runs.

**EQ(PRE): what's likely to go wrong**
| Angle | Hypothesis |
|---|---|
| Causal | The fixed 0.5/0.3/0.2 weights miss interactions, so a pocket of applicants is confidently mis-scored. |
| Context | Thin-file applicants are scored without the data that would clear them, so "no data" gets treated as "bad data". |
| Consistency | An LLM-written explanation cites different reasons on different runs. |

**EQ(POST): fixes in cheapest-first order**
1. Prompt: explanations may only use the computed `principal_reasons`, and the offline template is the floor.
2. Context/retrieval: cite the thin-file policy, and apply the live parity signal to the decision.
3. Feedback loop: k-NN memory escalation from repayment outcomes, the guardrail, and threshold *proposals*.

**Executable:** `python run_evals.py` runs 21 cases × 3 runs across four segments (policy, fairness, memory, explain). CI fails the build below 100%.

## Part 3 — Gen-4 Architecture

```
POST /decide ─► Retrieval ─► Context ─► Memory ─► Prompt assembly ─► Model ─► decision + trace
                                                                                  │
POST /feedback (repaid / defaulted) ◄─────────────────────────────────────────────┘
      └─► calibration · guardrail · proposals ─► knowledge graph (facts) ─► next decision
```

| Layer | What LendFair does |
|---|---|
| Retrieval | BM25 over `knowledge/credit_policy.md` and `fair_lending.md`. Each decision cites the 3 sections it relies on (for example, the thin-file policy for no-history applicants). |
| Context | The applicant's segment, the live reject-rate gap against the matched segment, and whether the parity alert is active. The thresholds in force are read from memory, not hard-coded. |
| Memory | Every decision is stored with its features. Outcomes are joined later. A k-NN search (distance ≤ 0.25, ≥ 5 neighbours) gives the observed repay rate of similar applicants. |
| Feedback | Repayment outcomes feed calibration (Brier score, ECE) and the auto-approve default guardrail. When the guardrail trips, the loop files a threshold proposal, which a human approves at `POST /proposals/auto_approve/approve`. Results are written as facts. |

The model (LLM) writes the adverse-action explanation using only the computed reasons. Without an API key, a deterministic template is used, and the trace records which one ran.

## Part 4 — Implementation Plan

| Component | Priority | Estimate | Status |
|---|---|---|---|
| Wrap the scoring engine in a service with thresholds read from memory | MVP | 0.5 day | done |
| Decision log + outcome join (SQLite) | MVP | 0.5 day | done |
| k-NN memory escalation (escalate-only) | MVP | 0.5 day | done |
| Live segment-parity monitor + auto-reject pause | MVP | 0.5 day | done |
| Principal reasons + grounded explanation (LLM with offline fallback) | MVP | 0.5 day | done |
| Calibration, guardrail, human-approved proposals | MVP | 0.5 day | done |
| FastAPI, Docker, Render blueprint, CI eval gate | MVP | 0.5 day | done |
| Trained classifier in place of the heuristic (same interface) | nice-to-have | 2 days | future |
| Postgres memory and multi-instance deploy | nice-to-have | 1 day | future |
| Bureau and bank-statement connectors | future | 3–5 days | future |

The bottleneck is not code. It is outcome latency: repayment labels arrive months later. The simulation compresses that time.

## Part 5 — Prove It

**Visible change.** `python simulate_learning.py` runs a seeded world where 30% of near-perfect profiles actually default half the time (a blind spot of the model):

| Phase (150 applicants each) | Static engine: auto-approved defaults | Gen-4 service: auto-approved defaults | Escalated to a human |
|---|---|---|---|
| 1 | 28 / 150 (18.7%) | 6 / 109 (5.5%) | 41 |
| 2 | 30 / 150 (20.0%) | 1 / 93 (1.1%) | 57 |
| 3 | 23 / 150 (15.3%) | 0 / 105 (0.0%) | 45 |

An outside observer would see that the same scoring model, given memory of real outcomes, stops auto-approving the pocket it was wrong about. Within one phase, the auto-approve default rate falls from about 19% to near zero, and no threshold changes without a human. Output is in `run_output_learning.txt`.
