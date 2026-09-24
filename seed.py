#!/usr/bin/env python3
"""
Seed LendFair's memory with 12 months of synthetic lending history.

    python seed.py              # writes data/lendfair.db (or $GEN4_DB)
    python seed.py --reset      # rebuild from scratch
    python seed.py --if-empty   # used by the Docker entrypoint

720 applications, one every ~12 hours, run through the real service in
date order so memory, escalations and parity monitoring build up the way
they would in production. Repayment outcomes are only known for loans
decided more than 120 days before the seed date and actually disbursed
(auto-approved, or approved by a simulated underwriter); newer loans are pending.

The synthetic ground truth includes one blind spot (near-perfect profiles
with 4-6% DTI default half the time) so the memory layer has something real
to learn. All data is synthetic: no real applicants.
"""

import math
from pathlib import Path

from decision_engine import Applicant
from gen4 import Memory
from gen4.seedkit import already_seeded, args, iso, mark
from service import LendFairService

N, DAYS, OUTCOME_LAG = 720, 360, 120


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def make(rng, i):
    history = rng.random() < 0.72
    dti = round(clamp(rng.betavariate(2.2, 6.5), 0.0, 0.95), 3)
    tenure = round(clamp(rng.expovariate(1 / 5.5), 0, 30), 1)
    income = round(rng.lognormvariate(math.log(720000), 0.55), -3)   # INR per year
    if rng.random() < 0.06:                                            # the blind-spot pocket
        return Applicant(f"APP-{i:05d}", rng.randint(835, 850), round(rng.uniform(0.04, 0.06), 3),
                         round(rng.uniform(12, 25), 1), income, True)
    seg = rng.random()
    if seg < 0.12:                                                      # prime salaried segment
        return Applicant(f"APP-{i:05d}", rng.randint(826, 850), round(rng.uniform(0.0, 0.05), 3),
                         round(rng.uniform(10, 28), 1), income * 1.8, True)
    if seg < 0.18:                                                      # distressed segment
        return Applicant(f"APP-{i:05d}", rng.randint(300, 420), round(rng.uniform(0.75, 0.95), 3),
                         round(rng.uniform(0, 0.5), 1), income * 0.4, True)
    if history:
        score = int(clamp(rng.gauss(705, 75), 300, 850))
        return Applicant(f"APP-{i:05d}", score, dti, tenure, income, True)
    bank = None if rng.random() < 0.2 else round(clamp(rng.betavariate(5, 2.5), 0, 1), 2)
    return Applicant(f"APP-{i:05d}", None, dti, tenure, income, False, bank)


def p_repay(a: Applicant, model_score: float) -> float:
    if a.has_credit_history and a.credit_score >= 835 and 0.04 <= a.debt_to_income <= 0.06:
        return 0.50
    return clamp(0.55 + 0.45 * model_score, 0.3, 0.995)


def main():
    a, rng = args("data/lendfair.db", "Seed LendFair with synthetic lending history")
    Path(a.db).parent.mkdir(parents=True, exist_ok=True)
    mem = Memory(a.db)
    if a.if_empty and already_seeded(mem):
        print(f"{a.db} already has data -- skipping seed")
        return
    svc = LendFairService(memory=mem)
    decided = repaid = defaulted = escalated = 0
    for i in range(N):
        days_ago = DAYS - i * DAYS / N
        app = make(rng, i)
        r = svc.decide(app)
        decided += 1
        escalated += r["escalated"]
        outcome_ts = None
        # A loan is disbursed if auto-approved, or if a human underwriter approves a
        # Conditional case (simulated: more likely the higher the risk score).
        disbursed = r["decision"] == "Approved" or (
            r["decision"] == "Conditional" and rng.random() < clamp((r["risk_score"] - 0.45) * 2.2, 0, 0.95))
        if disbursed and days_ago > OUTCOME_LAG:
            ok = rng.random() < p_repay(app, r["risk_score"])
            svc.memory.record_outcome(r["decision_id"], {"repaid": ok})
            outcome_ts = iso(days_ago - OUTCOME_LAG)
            repaid += ok
            defaulted += not ok
        mem.backdate(r["decision_id"], iso(days_ago), outcome_ts)
    learned = svc.learn()
    rows = mem.decisions(system="lendfair")
    by = {k: sum(1 for d in rows if d["output"]["decision"] == k) for k in ("Approved", "Conditional", "Rejected")}
    counts = {"applications": decided, **by, "repaid": repaid, "defaulted": defaulted,
              "memory_escalations": escalated}
    mark(mem, "lendfair", a.seed, counts)
    print(f"seeded {a.db}: {counts}")
    print(f"calibration brier={learned['calibration']['brier']} guardrail={learned['guardrail']['status']} "
          f"parity_gap={svc.parity()['reject_gap']}")


if __name__ == "__main__":
    main()
