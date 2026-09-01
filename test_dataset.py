"""
Builds the applicant test dataset used to exercise the decision engine.

Follows the design from guide1-assignment.md:
  - A handful of single-variable sweep cases (clear approve / clear reject)
  - The 3 interaction profiles worked out in that assignment
  - A no-credit-history segment AND a matched comparable-credit-history
    segment (same income/employment), so the audit module can compare
    decision rates between them -- this is what makes the failure-mode
    detection method in the design doc actually testable.

This is a trimmed demo set (not the full ~90-100 case sweep from the
design doc) -- enough to show the engine and the audit working end-to-end.
"""

from decision_engine import Applicant


def build_dataset() -> list[Applicant]:
    applicants = []

    # -- Clear-cut sweep cases -------------------------------------------
    applicants.append(Applicant("sweep-clear-approve", credit_score=800, debt_to_income=0.15,
                                 employment_years=12, annual_income=140000, has_credit_history=True))
    applicants.append(Applicant("sweep-clear-reject", credit_score=520, debt_to_income=0.55,
                                 employment_years=0.5, annual_income=32000, has_credit_history=True))
    applicants.append(Applicant("sweep-borderline", credit_score=670, debt_to_income=0.35,
                                 employment_years=3, annual_income=58000, has_credit_history=True))
    applicants.append(Applicant("sweep-extreme-approve", credit_score=850, debt_to_income=0.03,
                                 employment_years=20, annual_income=210000, has_credit_history=True))
    applicants.append(Applicant("sweep-extreme-reject", credit_score=300, debt_to_income=0.98,
                                 employment_years=0.0, annual_income=18000, has_credit_history=True))

    # -- The 3 interaction profiles from the design doc --------------------
    applicants.append(Applicant("interaction-low-credit-low-dti-long-tenure",
                                 credit_score=580, debt_to_income=0.18, employment_years=11,
                                 annual_income=72000, has_credit_history=True))
    applicants.append(Applicant("interaction-high-credit-high-dti-mid-tenure",
                                 credit_score=790, debt_to_income=0.52, employment_years=5,
                                 annual_income=98000, has_credit_history=True))
    applicants.append(Applicant("interaction-good-credit-avg-dti-short-tenure",
                                 credit_score=710, debt_to_income=0.32, employment_years=1.5,
                                 annual_income=64000, has_credit_history=True))

    # -- No-credit-history segment (the failure mode from the design doc) --
    # These are matched on income/employment to the comparable segment below,
    # varying only has_credit_history and whether bank-statement data exists.
    applicants.append(Applicant("no-history-with-bank-data-1", credit_score=None,
                                 debt_to_income=0.22, employment_years=4, annual_income=70000,
                                 has_credit_history=False, bank_statement_stability_score=0.82))
    applicants.append(Applicant("no-history-with-bank-data-2", credit_score=None,
                                 debt_to_income=0.28, employment_years=2, annual_income=55000,
                                 has_credit_history=False, bank_statement_stability_score=0.68))
    applicants.append(Applicant("no-history-no-bank-data-1", credit_score=None,
                                 debt_to_income=0.25, employment_years=3.5, annual_income=62000,
                                 has_credit_history=False, bank_statement_stability_score=None))
    applicants.append(Applicant("no-history-with-bank-data-3", credit_score=None,
                                 debt_to_income=0.19, employment_years=6, annual_income=81000,
                                 has_credit_history=False, bank_statement_stability_score=0.91))

    # -- Matched comparable-credit-history segment (same income/employment) -
    applicants.append(Applicant("matched-history-1", credit_score=700, debt_to_income=0.22,
                                 employment_years=4, annual_income=70000, has_credit_history=True))
    applicants.append(Applicant("matched-history-2", credit_score=690, debt_to_income=0.28,
                                 employment_years=2, annual_income=55000, has_credit_history=True))
    applicants.append(Applicant("matched-history-3", credit_score=705, debt_to_income=0.25,
                                 employment_years=3.5, annual_income=62000, has_credit_history=True))
    applicants.append(Applicant("matched-history-4", credit_score=720, debt_to_income=0.19,
                                 employment_years=6, annual_income=81000, has_credit_history=True))

    return applicants
