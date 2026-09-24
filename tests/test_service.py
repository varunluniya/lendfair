from dataclasses import replace

import pytest

from decision_engine import Applicant
from gen4 import KnowledgeBase, LLMClient, Memory
from service import LendFairService, principal_reasons
from test_dataset import build_dataset


@pytest.fixture
def svc():
    return LendFairService(memory=Memory(), kb=KnowledgeBase.from_dir("knowledge"),
                           llm=LLMClient(provider="offline"))


def app(i):
    return {a.applicant_id: a for a in build_dataset()}[i]


def test_every_decision_cites_policy_and_is_logged(svc):
    r = svc.decide(app("sweep-borderline"))
    assert r["trace"]["retrieval"], "decision must cite the knowledge base"
    assert r["trace"]["model"]["provider"] == "offline"
    assert svc.memory.get_decision(r["decision_id"])["output"]["decision"] == "Conditional"


def test_no_history_applicant_cites_thin_file_policy(svc):
    r = svc.decide(app("no-history-no-bank-data-1"))
    headings = [c["heading"] for c in r["trace"]["retrieval"]]
    assert any("credit history" in h.lower() for h in headings)
    assert r["decision"] == "Conditional"


def test_memory_only_escalates_never_auto_decides(svc):
    # past twins of a borderline applicant all repaid -> memory must NOT auto-approve
    a = app("sweep-borderline")
    for k in range(8):
        d = svc.decide(replace(a, applicant_id=f"twin-{k}"))
        svc.record_outcome(d["decision_id"], repaid=True)
    assert svc.decide(a)["decision"] == "Conditional"


def test_memory_contradiction_escalates_auto_approve(svc):
    a = app("sweep-extreme-approve")
    assert svc.decide(a)["decision"] == "Approved"
    for k in range(6):
        d = svc.decide(replace(a, applicant_id=f"twin-{k}"))
        svc.record_outcome(d["decision_id"], repaid=False)
    r = svc.decide(a)
    assert r["decision"] == "Conditional" and r["escalated"]


def test_parity_alert_pauses_auto_reject_for_no_history_segment(svc):
    bad_nh = Applicant("nh", None, 0.95, 0.0, 10000, False, 0.0)
    good_h = Applicant("h", 800, 0.10, 8, 90000, True)
    for k in range(20):
        svc.memory.record_decision("lendfair", f"nh{k}", {"segment": "no_credit_history",
                                   "debt_to_income": 0.3, "tenure": 0.4, "primary_signal": 0.1},
                                   {"decision": "Rejected", "risk_score": 0.04})
        svc.memory.record_decision("lendfair", f"h{k}", {"segment": "credit_history",
                                   "debt_to_income": 0.2, "tenure": 0.5, "primary_signal": 0.8},
                                   {"decision": "Conditional", "risk_score": 0.7})
    assert svc.parity()["alert"] is True
    r = svc.decide(bad_nh)
    assert r["decision"] == "Conditional"
    assert "fairness alert" in r["routing_reason"]
    assert svc.decide(good_h)["decision"] in ("Approved", "Conditional")


def test_guardrail_proposes_but_does_not_apply_threshold_change(svc):
    a = app("sweep-extreme-approve")
    for k in range(35):
        d = svc.decide(replace(a, applicant_id=f"x{k}", debt_to_income=0.03 + k * 1e-4))
        svc.record_outcome(d["decision_id"], repaid=(k % 5 != 0))  # 20% default
    out = svc.learn()
    assert out["guardrail"]["tripped"]
    assert out["new_proposal"]["proposed"] > out["new_proposal"]["current"]
    assert svc.thresholds()["auto_approve"] == 0.97  # unchanged until approved


def test_principal_reasons_name_the_weakest_factor():
    r = principal_reasons(Applicant("x", 520, 0.55, 0.5, 30000, True))
    assert "credit score of 520" in r[0]
