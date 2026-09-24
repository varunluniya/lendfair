import os
import tempfile

os.environ["GEN4_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["GEN4_LLM_PROVIDER"] = "offline"

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402

c = TestClient(app)


def test_health():
    r = c.get("/health").json()
    assert r["status"] == "ok" and r["knowledge_sections"] > 0


def test_decide_feedback_roundtrip():
    r = c.post("/decide", json={"applicant_id": "a1", "credit_score": 850, "debt_to_income": 0.03,
                                "employment_years": 20, "annual_income": 210000,
                                "has_credit_history": True}).json()
    assert r["decision"] == "Approved"
    f = c.post("/feedback", json={"decision_id": r["decision_id"], "repaid": True}).json()
    assert f["calibration"]["n"] == 1
    assert c.post("/feedback", json={"decision_id": "nope", "repaid": True}).status_code == 404


def test_validation():
    r = c.post("/decide", json={"applicant_id": "a2", "debt_to_income": 0.2, "employment_years": 2,
                                "annual_income": 1, "has_credit_history": True})
    assert r.status_code == 422


def test_fairness_and_knowledge_endpoints():
    assert "reject_gap" in c.get("/audit/fairness").json()
    assert c.get("/knowledge/search", params={"q": "thin-file bank statement"}).json()
