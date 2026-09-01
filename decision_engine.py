"""
Loan Eval Decision Engine

A rule-based loan-application decision engine that implements the eval
framework this project implements: differentiated confidence
thresholds by decision type, a no-credit-history fallback path, and
segment-level bias auditing.

This is deliberately a transparent, weighted heuristic rather than a
trained ML model -- the point of this demo is the EVAL DESIGN (thresholds,
metrics, failure-mode detection/recovery), not model training. A real
deployment would swap `score_applicant`'s internals for a trained
classifier's calibrated probability output and keep everything downstream
(thresholds, routing, audit) unchanged.

Scoring model: `risk_score` is treated as P(should approve), in [0, 1].
Confidence is derived directly from how far risk_score sits from the 0.5
midpoint (confidence = max(p, 1-p)) -- a score near either extreme means
the signals agree strongly; a score near the middle means they conflict,
which is exactly the ambiguous, interaction-heavy case the design doc's
"correlation / interaction handling" metric is meant to catch.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Decision(str, Enum):
    APPROVED = "Approved"
    CONDITIONAL = "Conditional"
    REJECTED = "Rejected"


# Thresholds from the eval design (differentiated by decision type).
# Both are expressed directly on risk_score (P(approve)), since confidence
# is derived from risk_score's distance from 0.5 -- see module docstring.
AUTO_APPROVE_THRESHOLD = 0.97   # risk_score >= this -> auto-approve
AUTO_REJECT_THRESHOLD = 0.05    # risk_score <= this -> auto-reject (95% confidence of reject)
CONFIDENCE_FLOOR = 0.85         # derived confidence below this -> always Conditional


@dataclass
class Applicant:
    applicant_id: str
    credit_score: int | None  # 300-850, None if no credit history
    debt_to_income: float     # 0.0-1.0
    employment_years: float
    annual_income: float
    has_credit_history: bool
    # alternative signal, used only when has_credit_history is False
    bank_statement_stability_score: float | None = None  # 0.0-1.0, if available


@dataclass
class ScoreResult:
    applicant_id: str
    risk_score: float       # 0.0 (worst) - 1.0 (best), the underlying "model" output
    confidence: float       # 0.0-1.0, derived certainty in that risk_score
    decision: Decision
    reasoning: str
    used_fallback_scoring: bool


def _normalize_credit_score(score: int) -> float:
    # 300-850 -> 0.0-1.0
    return max(0.0, min(1.0, (score - 300) / (850 - 300)))


def _score_with_credit_history(a: Applicant) -> float:
    """Returns risk_score using credit score, DTI, and employment history --
    the three variables identified as most likely to interact in Section 1
    of the eval design."""
    credit_component = _normalize_credit_score(a.credit_score)
    dti_component = max(0.0, 1.0 - a.debt_to_income)  # lower DTI is better
    tenure_component = min(1.0, a.employment_years / 10.0)  # caps benefit at 10y

    # Weighted blend -- credit score is the strongest single signal, but DTI
    # and tenure can meaningfully shift a borderline case (this is the
    # "correlation / interaction handling" metric from the design doc).
    return 0.5 * credit_component + 0.3 * dti_component + 0.2 * tenure_component


def _score_no_credit_history(a: Applicant) -> tuple[float, str]:
    """Recovery path from Section 4 of the design doc: for applicants with
    no credit history, fall back to 6 months of bank statement data
    (spending stability, cash flow) instead of defaulting to a low score
    purely because one field is empty."""
    dti_component = max(0.0, 1.0 - a.debt_to_income)
    tenure_component = min(1.0, a.employment_years / 10.0)

    if a.bank_statement_stability_score is None:
        # No alternative data available either -- fall back further to
        # DTI/employment only, and the result is deliberately pulled toward
        # the uncertain middle (0.5) rather than trusted at face value,
        # since two of three normal signals are missing.
        raw = 0.5 * dti_component + 0.5 * tenure_component
        risk_score = 0.5 + (raw - 0.5) * 0.5  # shrink toward 0.5 -> low confidence
        reason = (
            "No credit history AND no bank statement data available -- "
            "scored on DTI/employment only, pulled toward the uncertain "
            "midpoint so confidence is capped low by design."
        )
        return risk_score, reason

    risk_score = (
        0.5 * a.bank_statement_stability_score
        + 0.3 * dti_component
        + 0.2 * tenure_component
    )
    reason = (
        "No credit history -- used 6-month bank statement stability as the "
        "alternative signal (recovery path from the eval design's failure-mode fix)."
    )
    return risk_score, reason


def score_applicant(a: Applicant) -> ScoreResult:
    used_fallback = not a.has_credit_history

    if a.has_credit_history:
        risk_score = _score_with_credit_history(a)
        reasoning = (
            f"Credit-history path: credit_score={a.credit_score}, "
            f"DTI={a.debt_to_income:.2f}, employment_years={a.employment_years:.1f}."
        )
    else:
        risk_score, fallback_reason = _score_no_credit_history(a)
        reasoning = fallback_reason

    confidence = max(risk_score, 1.0 - risk_score)
    decision, decision_reason = _route(risk_score, confidence)
    reasoning = f"{reasoning} {decision_reason}"

    return ScoreResult(
        applicant_id=a.applicant_id,
        risk_score=round(risk_score, 3),
        confidence=round(confidence, 3),
        decision=decision,
        reasoning=reasoning,
        used_fallback_scoring=used_fallback,
    )


def _route(risk_score: float, confidence: float) -> tuple[Decision, str]:
    """Implements Section 3's differentiated thresholds: a strict bar for
    auto-approve, a slightly more forgiving bar for auto-reject, and a
    confidence floor below which nothing is auto-decided at all -- including
    the deliberate 85-97% (and 5-15%) "too close to call" band the design
    doc calls out explicitly."""
    if risk_score >= AUTO_APPROVE_THRESHOLD:
        return (
            Decision.APPROVED,
            f"Risk score {risk_score:.2f} clears the {AUTO_APPROVE_THRESHOLD:.2f} auto-approve bar.",
        )
    if risk_score <= AUTO_REJECT_THRESHOLD:
        return (
            Decision.REJECTED,
            f"Risk score {risk_score:.2f} falls below the {AUTO_REJECT_THRESHOLD:.2f} "
            f"auto-reject bar (95% confidence of reject).",
        )
    if confidence < CONFIDENCE_FLOOR:
        return (
            Decision.CONDITIONAL,
            f"Confidence {confidence:.2f} below the {CONFIDENCE_FLOOR:.2f} floor -> "
            f"routed to human review rather than auto-decided.",
        )
    return (
        Decision.CONDITIONAL,
        f"Risk score {risk_score:.2f} lands in the deliberate no-auto-decide zone "
        f"between the approve and reject bars -> routed to human review.",
    )
