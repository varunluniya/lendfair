"""
Segment-level bias audit.

Implements the detection method this project's eval design calls for: compare
the decision-rate breakdown for the "no credit history" segment against a
matched comparable-credit-history segment. A significantly higher
reject/conditional rate for the no-history segment is the signal that the
failure mode is active -- not a one-off complaint, but a measurable pattern.

Run this twice: once with the recovery path DISABLED (to reproduce the
failure mode) and once with it ENABLED (the current decision_engine.py
behavior), to show the recovery path actually closes the gap.
"""

from __future__ import annotations

from collections import Counter

from decision_engine import Applicant, Decision, score_applicant


def decision_rate_breakdown(results) -> dict:
    counts = Counter(r.decision for r in results)
    total = len(results)
    return {d.value: round(counts.get(d, 0) / total, 3) for d in Decision} if total else {}


def run_audit(applicants: list[Applicant]) -> dict:
    no_history = [a for a in applicants if not a.has_credit_history]
    matched = [a for a in applicants if a.applicant_id.startswith("matched-history")]

    no_history_results = [score_applicant(a) for a in no_history]
    matched_results = [score_applicant(a) for a in matched]

    return {
        "no_credit_history_segment": {
            "n": len(no_history_results),
            "decision_rates": decision_rate_breakdown(no_history_results),
            "avg_confidence": round(
                sum(r.confidence for r in no_history_results) / len(no_history_results), 3
            ) if no_history_results else None,
        },
        "matched_credit_history_segment": {
            "n": len(matched_results),
            "decision_rates": decision_rate_breakdown(matched_results),
            "avg_confidence": round(
                sum(r.confidence for r in matched_results) / len(matched_results), 3
            ) if matched_results else None,
        },
    }


def run_audit_without_recovery_path(applicants: list[Applicant]) -> dict:
    """Reproduces the FAILURE MODE by scoring no-credit-history applicants
    as if they were simply missing data (worst-case score), instead of
    using the bank-statement recovery path -- this is what the design doc
    says naive systems do wrong."""
    no_history = [a for a in applicants if not a.has_credit_history]
    matched = [a for a in applicants if a.applicant_id.startswith("matched-history")]

    # Naive scoring: no credit history -> treated as a low/failing score
    # outright (risk_score=0.03, confidently wrong -- exactly the dangerous
    # case Section 2's "confidence calibration" metric is designed to catch).
    from decision_engine import _route, ScoreResult

    naive_results = []
    for a in no_history:
        naive_risk = 0.03
        naive_confidence = max(naive_risk, 1.0 - naive_risk)
        decision, reason = _route(naive_risk, naive_confidence)
        naive_results.append(ScoreResult(a.applicant_id, naive_risk, naive_confidence, decision,
                                          "NAIVE (no recovery path): missing credit history "
                                          "treated as bad credit outright. " + reason, True))

    matched_results = [score_applicant(a) for a in matched]

    return {
        "no_credit_history_segment_NAIVE": {
            "n": len(naive_results),
            "decision_rates": decision_rate_breakdown(naive_results),
            "avg_confidence": round(sum(r.confidence for r in naive_results) / len(naive_results), 3)
            if naive_results else None,
        },
        "matched_credit_history_segment": {
            "n": len(matched_results),
            "decision_rates": decision_rate_breakdown(matched_results),
            "avg_confidence": round(sum(r.confidence for r in matched_results) / len(matched_results), 3)
            if matched_results else None,
        },
    }
