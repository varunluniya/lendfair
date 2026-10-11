# Day 47 changelog — LendFair

## Finding

`service.py`'s `learn()` called `self.memory.decisions(system=SYSTEM, with_outcome=True)`
with no timestamp filter — every call re-pulled and re-aggregated every
decision+outcome pair the system had ever logged, from the beginning of
time, including rows already processed by earlier calls. That's Guide 5's
own "Mistake 5: using full load past the point it scales," found in
already-shipped code. `learn()` runs on every `record_outcome()` call, so
this was a full-table re-scan on the hottest feedback path in the service.

A secondary finding: `add_fact()` used plain `INSERT OR REPLACE` (upsert,
no history), while `set_param()`/`param_history` in the same file correctly
implements an SCD Type 2 pattern (current value + full audit trail with
reasons). Inconsistent within one codebase.

A latent bug surfaced while designing the fix: `_select()` selected
`o.ts AS outcome_ts` in its SQL but never included it in the dict it
returned — advancing a watermark on outcome arrival requires knowing each
row's outcome timestamp, so this had to be fixed first.

## Changes

- `gen4/memory.py`
  - Added `fact_history` table (append-only) so `add_fact()` preserves the
    history `facts` was losing on every upsert; `add_fact()` now writes to
    both tables under one shared timestamp. New `fact_history()` getter.
  - `decisions()` gained an `outcome_since` parameter (`o.ts > ?` filter;
    implies `with_outcome=True` when not set) — the actual watermarking hook.
  - Fixed `_select()` to return `outcome_ts` in the dict (it was already in
    the SQL `SELECT`, just silently dropped before returning).
  - Added a `(system, ts DESC)` index on `decisions` — `decisions(system=...,
    limit=...)` looks bounded because of the `LIMIT`, but without this index
    SQLite still did a full table `SCAN` + a temp B-tree sort to produce the
    `ORDER BY ts DESC` every call, regardless of result size (confirmed via
    `EXPLAIN QUERY PLAN`). Purely an access-path optimization — no behavior
    change.
  - `stats()` extended to also count `fact_history` rows.

- `gen4/feedback.py` — four new primitives:
  - `new_rows_since(memory, system, watermark_key, grace_days, ...)` — pulls
    only outcomes newer than the last watermark (minus a grace window for
    late-arriving outcomes), filters out ids already marked processed.
  - `mark_processed(memory, watermark_key, rows)` — persists the processed-id
    set and advances the watermark to the latest outcome timestamp actually
    seen.
  - `accumulate(memory, key, **deltas)` — merges numeric deltas into a
    persisted running total.
  - `incremental_calibration(memory, key, new_pairs, bins)` — same contract
    as `calibration()`, but built from persisted per-bin sufficient
    statistics (n, sum predicted, sum observed) updated with only the new
    pairs. Proven bin-for-bin equivalent to `calibration()` by test.

- `service.py`
  - `learn()` rewritten to use `new_rows_since()` / `incremental_calibration()`
    / `accumulate()` / `mark_processed()` instead of re-pulling and
    re-aggregating every row. `LEARN_KEY = "lendfair_learn"`,
    `LEARN_GRACE_DAYS = 7` (justified by `seed.py`'s 120-day outcome lag
    constant — 7 days comfortably covers realistic late-arrival skew without
    re-pulling an excessive window every call).

- `tests/test_incremental_learning.py` — new, 3 tests: incremental result
  matches a from-scratch full recompute of `calibration()`; repeated
  `learn()` calls with nothing new are idempotent (no double-counting);
  a second `learn()` call after new outcomes arrive picks them up.

## Verification

- `pytest -q` → 17/17 passed (14 original + 3 new).
- `run_evals.py` → GATE PASS, 100%/100% accuracy/consistency, unchanged.
- `seed.py --reset` → identical output to pre-fix baseline (720 applications,
  68 approved, 650 conditional, 2 rejected, 208 repaid, 30 defaulted, 31
  memory escalations; calibration brier=0.1457, guardrail=TRIPPED,
  parity_gap=0.0).
- `simulate_learning.py` → identical documented auto-approve default-rate
  progression across phases (18.7% → 5.5% → 1.1% → 0.0%).
- `run_demo.py` → unchanged output.

No behavioral change in any observable output — this is a performance /
scalability fix only, verified bit-for-bit against the pre-fix baseline.
