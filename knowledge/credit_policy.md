# LendFair Credit Policy

## Decision bands
Every application gets a risk score, read as the probability the loan should be approved.
Auto-approve only when the risk score clears the auto-approve bar (default 0.97).
Auto-reject only when the risk score is at or below the auto-reject bar (default 0.05).
Everything in between is Conditional and goes to a human underwriter.
The gap between the bars is deliberate: cases the system is unsure about are not guessed on.

## Confidence floor
Confidence is the distance of the risk score from 0.5. Below the 0.85 confidence floor, nothing is auto-decided.
Conflicting signals (for example a high credit score undermined by high debt to income) produce mid-range scores and land in human review by design.

## Credit history path
Credit score (300-850) carries 50% of the weight, debt to income 30%, employment tenure 20% (benefit capped at 10 years).
A debt to income ratio above 0.45 is high risk even with a strong credit score.

## Thin-file and no credit history applicants
Missing credit history is not evidence of bad credit.
Applicants with no bureau record are scored on six months of bank statement stability (50%), debt to income (30%) and tenure (20%).
If bank statement data is also missing, the score is pulled toward 0.5 so the case goes to a human rather than being auto-rejected.
The bank statement path is capped below what an established credit history can reach.

## Memory escalation rule
When outcomes of similar past applicants disagree strongly with the model score, the case is escalated to human review.
Memory may only move a case toward human review. It can never auto-approve or auto-reject on its own.

## Threshold changes
Thresholds are never changed automatically. The feedback loop may propose a change with evidence; a credit risk owner must approve it.
