"""
LendFair intelligent service — the decision engine wrapped in the Gen-4 layers.

    Retrieval  credit policy + fair-lending rules, cited on every decision
    Context    applicant segment, live segment parity, thresholds in force
    Memory     outcomes of similar past applicants (k-NN) + decision log
    Feedback   repayment outcomes -> calibration, guardrail, threshold proposals

The scoring model in decision_engine.py is unchanged. What the layers add:
  1. A memory check that escalates to a human when similar past applicants
     repaid (or defaulted) very differently from what the model predicts.
  2. A live fairness monitor: if the no-credit-history segment starts being
     rejected more than a matched segment, auto-rejects for that segment are
     paused and sent to a human until the gap closes.
  3. Plain-language adverse-action reasons grounded in the cited policy.
  4. A feedback loop that measures calibration and proposes (never applies)
     threshold changes for a human to approve.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

from decision_engine import (
    AUTO_APPROVE_THRESHOLD, AUTO_REJECT_THRESHOLD, CONFIDENCE_FLOOR,
    Applicant, Decision, _normalize_credit_score, score_applicant,
)
from gen4 import Context, KnowledgeBase, LLMClient, Memory, Trace
from gen4 import feedback as fb

SYSTEM = "lendfair"
HERE = Path(__file__).parent

MEMORY_MIN_NEIGHBOURS = 5
MEMORY_MAX_DISTANCE = 0.25
MEMORY_DISAGREEMENT = 0.35
PARITY_ALERT_GAP = 0.10
PARITY_MIN_N = 20
APPROVED_DEFAULT_LIMIT = 0.05


def _memory_features(a: Applicant) -> dict:
    primary = (_normalize_credit_score(a.credit_score) if a.has_credit_history
               else (a.bank_statement_stability_score if a.bank_statement_stability_score is not None else 0.5))
    return {"primary_signal": round(primary, 4), "debt_to_income": a.debt_to_income,
            "tenure": round(min(1.0, a.employment_years / 10.0), 4)}


def principal_reasons(a: Applicant, top: int = 2) -> list[str]:
    """Rank factors by how much score they cost (weight x shortfall) and say
    what would change the outcome -- the adverse-action reason list."""
    tenure = min(1.0, a.employment_years / 10.0)
    factors = [(0.3 * a.debt_to_income, f"debt-to-income of {a.debt_to_income:.0%} "
                "(below 35% would materially improve the score)"),
               (0.2 * (1 - tenure), f"employment tenure of {a.employment_years:g} years "
                "(the score improves with each year up to 10)")]
    if a.has_credit_history:
        c = _normalize_credit_score(a.credit_score)
        factors.append((0.5 * (1 - c), f"credit score of {a.credit_score} "
                        "(each 55-point increase adds about 0.05 to the score)"))
    elif a.bank_statement_stability_score is None:
        factors.append((0.5, "no credit history and no bank statements on file "
                        "(six months of bank statements would allow a full assessment)"))
    else:
        s = a.bank_statement_stability_score
        factors.append((0.5 * (1 - s), f"bank statement stability of {s:.2f} "
                        "(steadier monthly cash flow would raise the score)"))
    factors.sort(key=lambda x: x[0], reverse=True)
    return [msg for cost, msg in factors[:top] if cost > 0.02] or ["no material weaknesses"]


class LendFairService:
    def __init__(self, memory: Memory | None = None, kb: KnowledgeBase | None = None,
                 llm: LLMClient | None = None):
        self.memory = memory or Memory(os.environ.get("GEN4_DB", HERE / "data" / f"{SYSTEM}.db"))
        self.kb = kb or KnowledgeBase.from_dir(HERE / "knowledge")
        self.llm = llm or LLMClient()

    # -- parameters (learned, human-approved) --------------------------------
    def thresholds(self) -> dict:
        return {"auto_approve": self.memory.get_param("auto_approve", AUTO_APPROVE_THRESHOLD),
                "auto_reject": self.memory.get_param("auto_reject", AUTO_REJECT_THRESHOLD),
                "confidence_floor": self.memory.get_param("confidence_floor", CONFIDENCE_FLOOR)}

    # -- the decision ----------------------------------------------------------
    def decide(self, a: Applicant) -> dict:
        trace = Trace()
        t = self.thresholds()
        trace.params = t
        base = score_applicant(a)
        risk, conf = base.risk_score, base.confidence
        decision, why = self._route(risk, conf, t)

        # Context: segment + live parity
        segment = "credit_history" if a.has_credit_history else "no_credit_history"
        parity = self.parity()
        ctx = (Context()
               .add("segment", segment, "fair-lending monitoring is per segment")
               .add("parity_gap", parity["reject_gap"], "reject-rate gap vs matched segment")
               .add("parity_alert", parity["alert"], f"gap > {PARITY_ALERT_GAP:.0%} pauses auto-rejects"))
        trace.context = ctx.as_dict()

        # Memory: similar applicants' real outcomes
        feats = _memory_features(a)
        neighbours = [n for n in self.memory.similar(feats, list(feats), system=SYSTEM, k=15)
                      if n["distance"] <= MEMORY_MAX_DISTANCE]
        repaid = [1 if n["outcome"].get("repaid") else 0 for n in neighbours]
        prior = (sum(repaid) / len(repaid)) if len(repaid) >= MEMORY_MIN_NEIGHBOURS else None
        trace.memory = {"similar_with_outcomes": len(repaid), "observed_repay_rate": prior,
                        "customer_history": len(self.memory.history(a.applicant_id))}

        escalations = []
        if decision != Decision.CONDITIONAL and prior is not None and abs(prior - risk) > MEMORY_DISAGREEMENT:
            escalations.append(f"similar past applicants repaid at {prior:.0%} vs model score "
                               f"{risk:.2f}; memory disagrees, so a human decides")
        if decision == Decision.REJECTED and segment == "no_credit_history" and parity["alert"]:
            escalations.append("fairness alert active for the no-credit-history segment; "
                               "auto-rejects paused for this segment")
        if escalations:
            decision = Decision.CONDITIONAL
            why = "Escalated to human review: " + "; ".join(escalations) + "."
            trace.note("memory/context escalation applied (can only move toward human review)")

        # Retrieval: cite the policy sections this decision rests on
        query = " ".join([
            "decision bands confidence floor",
            "no credit history bank statement thin-file" if not a.has_credit_history else "credit score debt to income",
            "memory escalation" if escalations and prior is not None else "",
            "segment parity fairness alert" if parity["alert"] else "",
            "adverse action explanations" if decision != Decision.APPROVED else "",
        ])
        passages = self.kb.search(query, k=3)
        trace.cite(passages)

        reasons = principal_reasons(a)
        explanation = self._explain(a, decision, reasons, passages)
        trace.model = {"provider": self.llm.last_provider}

        output = {"decision": decision.value, "risk_score": risk, "confidence": conf,
                  "used_fallback_scoring": base.used_fallback_scoring,
                  "engine_reasoning": base.reasoning, "routing_reason": why,
                  "principal_reasons": reasons, "explanation": explanation,
                  "escalated": bool(escalations), "segment": segment}
        did = self.memory.record_decision(SYSTEM, a.applicant_id, {**feats, "segment": segment,
                                          "applicant": asdict(a)}, output)
        return {"decision_id": did, **output, "trace": trace.as_dict()}

    @staticmethod
    def _route(risk: float, conf: float, t: dict) -> tuple[Decision, str]:
        if risk >= t["auto_approve"]:
            return Decision.APPROVED, f"Risk score {risk:.2f} clears the {t['auto_approve']:.2f} auto-approve bar."
        if risk <= t["auto_reject"]:
            return Decision.REJECTED, f"Risk score {risk:.2f} is at or below the {t['auto_reject']:.2f} auto-reject bar."
        if conf < t["confidence_floor"]:
            return Decision.CONDITIONAL, f"Confidence {conf:.2f} is below the {t['confidence_floor']:.2f} floor."
        return Decision.CONDITIONAL, f"Risk score {risk:.2f} is in the no-auto-decide zone."

    def _explain(self, a: Applicant, decision: Decision, reasons: list[str], passages) -> str:
        def offline() -> str:
            if decision == Decision.APPROVED:
                return "Approved: credit profile, debt load and employment history all meet policy."
            head = ("Not approved automatically; a human underwriter will review." if decision == Decision.CONDITIONAL
                    else "Application declined.")
            return head + " Principal reasons: " + "; ".join(reasons) + "."
        from gen4.context import assemble_prompt
        prompt = assemble_prompt(
            task=f"Write a 2-3 sentence plain-language explanation to the applicant of a '{decision.value}' "
                 f"loan decision. Use only these principal reasons: {reasons}.",
            passages=passages, context=Context(), memory_notes=[],
            output_contract="Plain text. No protected characteristics. Say what would change the outcome.")
        return self.llm.complete(prompt, offline=offline, max_tokens=200)

    # -- context helpers ---------------------------------------------------------
    def parity(self, window: int = 500) -> dict:
        recent = self.memory.decisions(system=SYSTEM, limit=window)
        def is_reject(d):
            return d["output"]["decision"] == Decision.REJECTED.value
        nh = [d for d in recent if d["features"].get("segment") == "no_credit_history"]
        # matched = history applicants with comparable debt load and tenure
        mh = [d for d in recent if d["features"].get("segment") == "credit_history"
              and d["features"]["debt_to_income"] <= 0.35 and d["features"]["tenure"] >= 0.2]
        nh_r = fb.rate(sum(map(is_reject, nh)), len(nh))
        mh_r = fb.rate(sum(map(is_reject, mh)), len(mh))
        gap = round(nh_r - mh_r, 4) if nh_r is not None and mh_r is not None else None
        alert = bool(gap is not None and len(nh) >= PARITY_MIN_N and len(mh) >= PARITY_MIN_N
                     and gap > PARITY_ALERT_GAP)
        return {"no_history_n": len(nh), "matched_n": len(mh), "no_history_reject_rate": nh_r,
                "matched_reject_rate": mh_r, "reject_gap": gap, "alert": alert}

    # -- feedback ------------------------------------------------------------------
    def record_outcome(self, decision_id: str, repaid: bool) -> dict:
        if not self.memory.record_outcome(decision_id, {"repaid": bool(repaid)}):
            raise KeyError(decision_id)
        return self.learn()

    def learn(self) -> dict:
        done = self.memory.decisions(system=SYSTEM, with_outcome=True)
        pairs = [(d["output"]["risk_score"], 1 if d["outcome"]["repaid"] else 0) for d in done]
        cal = fb.calibration(pairs)
        approved = [d for d in done if d["output"]["decision"] == Decision.APPROVED.value]
        bad = sum(1 for d in approved if not d["outcome"]["repaid"])
        guard = fb.Guardrail("auto_approved_default_rate", APPROVED_DEFAULT_LIMIT, min_n=30).check(bad, len(approved))
        proposal = None
        if guard["tripped"]:
            cur = self.thresholds()["auto_approve"]
            proposal = fb.propose(self.memory, "auto_approve", cur, round(min(0.995, cur + 0.01), 3),
                                  "auto-approved loans are defaulting above the guardrail", guard)
        self.memory.add_fact("model:lendfair", "calibration", cal)
        self.memory.add_fact("lane:auto_approve", "default_guardrail", guard)
        return {"calibration": cal, "guardrail": guard, "new_proposal": proposal}
