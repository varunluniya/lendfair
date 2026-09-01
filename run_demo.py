"""
Run the full demo: score every applicant, print a decision report, then run
the segment-bias audit twice (naive vs. recovery-path-enabled) to show the
failure mode from the eval design and its fix, side by side.
"""

import json

from decision_engine import score_applicant
from test_dataset import build_dataset
from audit import run_audit, run_audit_without_recovery_path


def main():
    applicants = build_dataset()

    print("=" * 78)
    print("LOAN DECISION REPORT")
    print("=" * 78)
    for a in applicants:
        r = score_applicant(a)
        print(f"[{r.decision.value:^11}] {r.applicant_id:45s} "
              f"risk={r.risk_score:.2f} conf={r.confidence:.2f}")
        print(f"             {r.reasoning}")
    print()

    print("=" * 78)
    print("SEGMENT BIAS AUDIT -- WITHOUT recovery path (reproduces the failure mode)")
    print("=" * 78)
    naive_audit = run_audit_without_recovery_path(applicants)
    print(json.dumps(naive_audit, indent=2))
    print()

    print("=" * 78)
    print("SEGMENT BIAS AUDIT -- WITH recovery path (current engine behavior)")
    print("=" * 78)
    fixed_audit = run_audit(applicants)
    print(json.dumps(fixed_audit, indent=2))
    print()

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    naive_reject_rate = naive_audit["no_credit_history_segment_NAIVE"]["decision_rates"].get("Rejected", 0)
    fixed_reject_rate = fixed_audit["no_credit_history_segment"]["decision_rates"].get("Rejected", 0)
    matched_reject_rate = fixed_audit["matched_credit_history_segment"]["decision_rates"].get("Rejected", 0)
    print(f"No-credit-history reject rate WITHOUT recovery path: {naive_reject_rate:.0%}")
    print(f"No-credit-history reject rate WITH recovery path:    {fixed_reject_rate:.0%}")
    print(f"Matched comparable-history segment reject rate:      {matched_reject_rate:.0%}")
    print()
    print("This is the detection method from the eval design (Section 4): comparing "
          "decision rates between the no-history segment and a matched comparable "
          "segment. The naive engine shows a large gap (the failure mode); the "
          "recovery-path engine closes it substantially.")


if __name__ == "__main__":
    main()
