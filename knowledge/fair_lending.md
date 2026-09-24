# Fair Lending Monitoring

## Segment parity check
Compare decision rates of the no-credit-history segment with a matched segment that has comparable income and employment but an established credit history.
An absolute reject-rate gap above 10 percentage points is a fairness alert and must be investigated before more auto-decisions are made for that segment.

## Adverse action explanations
Every rejection or conditional outcome must come with the specific, principal reasons in plain language.
Reasons must name the factor (credit score, debt to income, employment tenure, missing data) and what would change the outcome.
Never cite protected characteristics. Never give generic reasons such as "internal policy".

## Calibration
The risk score is only trustworthy if it is calibrated: among applicants scored around 0.9, roughly 90% should repay.
Calibration is tracked with the Brier score and expected calibration error once repayment outcomes arrive.
