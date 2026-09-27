"""
Guide 4 Assignment 2 ("RAG with Guardrails") applied to LendFair's own
policy corpus (`knowledge/`), per the guide's own spec: one query that
passes cleanly, one that fires the guardrail, and one genuine edge case.
"""
from decision_engine import Decision
from gen4 import KnowledgeBase, LLMClient
from service import LendFairService


def make_svc():
    from gen4 import Memory
    return LendFairService(memory=Memory(), kb=KnowledgeBase.from_dir("knowledge"),
                           llm=LLMClient(provider="offline"))


def test_passing_query_explanation_is_untouched(svc=None):
    """A correctly-decided, correctly-worded explanation clears the guardrail unchanged."""
    svc = svc or make_svc()
    fallback = "Approved: credit profile, debt load and employment history all meet policy."
    out = svc._guarded(fallback, Decision.APPROVED, fallback, passages=[])
    assert out == fallback
    assert "guardrail replaced" not in out


def test_guardrail_fires_on_a_mismatched_approval_claim():
    """A draft that reads as an approval for a Conditional decision -- the exact
    failure shape of the Air Canada case (a fluent answer that misstates the
    real policy outcome) -- must be caught and replaced, not delivered as-is."""
    svc = make_svc()
    bad_draft = "You are approved! Your loan will be disbursed shortly."
    fallback = "Not approved automatically; a human underwriter will review. Principal reasons: thin credit file."
    out = svc._guarded(bad_draft, Decision.CONDITIONAL, fallback, passages=[])
    assert out != bad_draft
    assert "guardrail replaced" in out
    assert "underwriter will review" in out


def test_edge_case_conditional_explanation_missing_review_disclosure():
    """Genuine edge case: every individual sentence in the draft is factually
    true (it never claims approval), but it omits the one disclosure a
    Conditional decision legally/operationally requires -- that a human will
    review it. This is subtler than a false claim, and is exactly the kind of
    gap a plain fact-check would miss but a policy-aware guardrail should not."""
    svc = make_svc()
    technically_true_but_incomplete = ("Your application scored below the automatic approval "
                                       "threshold due to limited credit history.")
    fallback = "Not approved automatically; a human underwriter will review. Principal reasons: thin credit file."
    out = svc._guarded(technically_true_but_incomplete, Decision.CONDITIONAL, fallback, passages=[])
    assert out != technically_true_but_incomplete
    assert "review" in out.lower()
