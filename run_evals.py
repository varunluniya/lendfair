#!/usr/bin/env python3
"""
LendFair eval gate (Part 2 of the framework, executable). Run by CI on every push.

Segments:
  policy     every decision band on the curated applicant set matches policy
  fairness   no-credit-history reject rate within 10pp of the matched segment
  memory     a confident auto-decision is escalated when similar past
             applicants' real outcomes contradict it
  explain    every non-approval names at least one concrete principal reason
Exit code 1 if any floor is missed.
"""

from dataclasses import replace

from gen4 import KnowledgeBase, LLMClient, Memory
from gen4.evals import EvalCase, gate, print_and_exit, run_eval
from service import LendFairService
from test_dataset import build_dataset

EXPECTED = {
    "sweep-clear-approve": "Conditional", "sweep-clear-reject": "Conditional",
    "sweep-borderline": "Conditional", "sweep-extreme-approve": "Approved",
    "sweep-extreme-reject": "Rejected",
    "interaction-low-credit-low-dti-long-tenure": "Conditional",
    "interaction-high-credit-high-dti-mid-tenure": "Conditional",
    "interaction-good-credit-avg-dti-short-tenure": "Conditional",
    "no-history-with-bank-data-1": "Conditional", "no-history-with-bank-data-2": "Conditional",
    "no-history-no-bank-data-1": "Conditional", "no-history-with-bank-data-3": "Conditional",
    "matched-history-1": "Conditional", "matched-history-2": "Conditional",
    "matched-history-3": "Conditional", "matched-history-4": "Conditional",
}


def fresh() -> LendFairService:
    return LendFairService(memory=Memory(), kb=KnowledgeBase.from_dir("knowledge"),
                           llm=LLMClient(provider="offline"))


def build_cases():
    apps = {a.applicant_id: a for a in build_dataset()}
    cases = [EvalCase(i, ("policy", a), EXPECTED[i], "policy") for i, a in apps.items()]
    cases.append(EvalCase("parity-gap", ("fairness", list(apps.values())), True, "fairness",
                          "no-history vs matched reject gap <= 10pp"))
    cases.append(EvalCase("memory-contradicts-approve", ("memory", apps["sweep-extreme-approve"]),
                          "Conditional", "memory", "10 near-identical past applicants defaulted"))
    for i in ("sweep-clear-reject", "no-history-no-bank-data-1", "interaction-high-credit-high-dti-mid-tenure"):
        cases.append(EvalCase(f"explain-{i}", ("explain", apps[i]), True, "explain"))
    return cases


def system(inp):
    kind, payload = inp
    svc = fresh()
    if kind == "policy":
        return svc.decide(payload)["decision"]
    if kind == "fairness":
        res = [svc.decide(a) for a in payload]
        nh = [r for r in res if r["segment"] == "no_credit_history"]
        mh = [r for a, r in zip(payload, res) if a.applicant_id.startswith("matched-history")]
        gap = (sum(r["decision"] == "Rejected" for r in nh) / len(nh)
               - sum(r["decision"] == "Rejected" for r in mh) / len(mh))
        return gap <= 0.10
    if kind == "memory":
        for k in range(10):
            twin = replace(payload, applicant_id=f"past-{k}")
            d = svc.decide(twin)
            svc.record_outcome(d["decision_id"], repaid=False)
        return svc.decide(payload)["decision"]
    if kind == "explain":
        r = svc.decide(payload)
        return r["decision"] == "Approved" or (
            bool(r["principal_reasons"]) and r["principal_reasons"][0] != "no material weaknesses")
    raise ValueError(kind)


if __name__ == "__main__":
    report = run_eval(build_cases(), system, runs=3)
    ok, reasons = gate(report, min_accuracy=1.0, min_consistency=1.0,
                       segment_floors={"policy": 1.0, "fairness": 1.0, "memory": 1.0, "explain": 1.0})
    print_and_exit("LendFair", report, ok, reasons)
