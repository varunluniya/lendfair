"""
LendFair API.   uvicorn app:app --reload    ->  http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from decision_engine import Applicant
from gen4.api import common_router
from service import LendFairService

service = LendFairService()
app = FastAPI(title="LendFair", version="2.0.0",
              description="Loan decisions with differentiated confidence thresholds, memory-backed "
                          "escalation, live fair-lending monitoring and a human-approved feedback loop.")
app.include_router(common_router(service, "lendfair"))


class ApplicantIn(BaseModel):
    applicant_id: str
    credit_score: int | None = Field(None, ge=300, le=850)
    debt_to_income: float = Field(..., ge=0, le=1.5)
    employment_years: float = Field(..., ge=0, le=60)
    annual_income: float = Field(..., ge=0)
    has_credit_history: bool
    bank_statement_stability_score: float | None = Field(None, ge=0, le=1)


class OutcomeIn(BaseModel):
    decision_id: str
    repaid: bool


@app.get("/", tags=["ops"])
def root():
    return {"service": "LendFair", "docs": "/docs",
            "flow": "POST /decide -> POST /feedback (repayment outcome) -> GET /audit/fairness, /calibration"}


@app.post("/decide", tags=["decision"])
def decide(body: ApplicantIn):
    if body.has_credit_history and body.credit_score is None:
        raise HTTPException(422, "credit_score is required when has_credit_history is true")
    return service.decide(Applicant(**body.model_dump()))


@app.post("/feedback", tags=["feedback"])
def feedback(body: OutcomeIn):
    try:
        return service.record_outcome(body.decision_id, body.repaid)
    except KeyError:
        raise HTTPException(404, f"unknown decision_id {body.decision_id}")


@app.get("/audit/fairness", tags=["feedback"])
def fairness():
    return service.parity()


@app.get("/calibration", tags=["feedback"])
def calibration():
    return service.learn()
