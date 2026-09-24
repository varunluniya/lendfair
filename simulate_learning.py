#!/usr/bin/env python3
"""
Prove-It simulation: does the memory + feedback loop actually make LendFair
safer over time?

A synthetic world where the scoring model is *wrong* for one pocket of
applicants: near-perfect credit and long tenure, but debt-to-income of 4-6%
(think: a new lender stacking loans not yet on the bureau). The model scores
them ~0.98 and auto-approves; in this world half of them default. The static
engine keeps auto-approving them. The Gen-4 service sees repayment outcomes,
and once enough similar cases have defaulted, memory escalates new look-alike
applicants to a human instead of auto-approving them.

Deterministic (seeded). Prints auto-approve default rate per phase.
"""

import random

from decision_engine import Applicant, score_applicant
from gen4 import KnowledgeBase, LLMClient, Memory
from service import LendFairService


def true_repay_prob(a: Applicant) -> float:
    if a.debt_to_income >= 0.04:
        return 0.50          # the model's blind spot
    return 0.99


def applicant(rng, i):
    hidden_pocket = rng.random() < 0.3
    return Applicant(f"sim-{i}", credit_score=rng.randint(845, 850),
                     debt_to_income=round(rng.uniform(0.04, 0.06) if hidden_pocket else rng.uniform(0.0, 0.015), 3),
                     employment_years=rng.uniform(15, 25), annual_income=150000, has_credit_history=True)


def main(n_per_phase: int = 150, seed: int = 7):
    rng = random.Random(seed)
    svc = LendFairService(memory=Memory(), kb=KnowledgeBase.from_dir("knowledge"), llm=LLMClient(provider="offline"))
    rows = []
    for phase in (1, 2, 3):
        static_auto = static_bad = g4_auto = g4_bad = escalated = 0
        for i in range(n_per_phase):
            a = applicant(rng, f"{phase}-{i}")
            repaid = rng.random() < true_repay_prob(a)
            if score_applicant(a).decision.value == "Approved":
                static_auto += 1
                static_bad += not repaid
            r = svc.decide(a)
            escalated += r["escalated"]
            if r["decision"] == "Approved":
                g4_auto += 1
                g4_bad += not repaid
            svc.record_outcome(r["decision_id"], repaid)   # outcome arrives later in real life
        rows.append((phase, static_auto, static_bad, g4_auto, g4_bad, escalated))
    print(f"{'phase':<6}{'static auto-approved':>22}{'static defaults':>17}{'gen4 auto-approved':>20}"
          f"{'gen4 defaults':>15}{'escalated':>11}")
    for p, sa, sb, ga, gb, e in rows:
        print(f"{p:<6}{sa:>22}{sb:>10} ({sb/max(sa,1):5.1%}){ga:>20}{gb:>8} ({gb/max(ga,1):5.1%}){e:>11}")
    learn = svc.learn()
    print("\nguardrail:", learn["guardrail"]["status"], "| pending proposals:",
          [p["param"] + f" {p['current']}->{p['proposed']}" for p in [learn["new_proposal"]] if p])


if __name__ == "__main__":
    main()
