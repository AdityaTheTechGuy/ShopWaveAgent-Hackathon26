# ShopWave Failure Modes

This document captures realistic failure scenarios, impact, and current mitigation in the codebase.

## 1) Invalid Order ID Input

Scenario:
User sends malformed IDs such as ABC-77 for refund/cancel/status.

Risk:
Wrong normalization can trigger incorrect lookup or action attempts.

Mitigation:
- normalize_order_id accepts only ORD-<digits> or plain digits.
- Invalid formats return correction prompts.
- No state mutation happens on invalid IDs.

Expected behavior:
User gets a validation message and nothing is changed.

## 2) Oversized Messages

Scenario:
User pastes large text blocks into CLI.

Risk:
High token usage and reduced response quality.

Mitigation:
- CLI rejects messages longer than 600 chars.
- Agent is not invoked for rejected input.

Expected behavior:
User is asked to shorten input, session remains responsive.

## 3) Ambiguous 4-Digit Numbers

Scenario:
User mentions a random 4-digit number in support chat.

Risk:
Number is misread as order ID and leads to misleading errors.

Mitigation:
- ORD-XXXX patterns are preferred.
- Bare 4-digit values are accepted only in clear order/refund/cancel context.
- Refund/cancel without valid context triggers follow-up prompt.

Expected behavior:
Incidental numbers do not trigger accidental order operations.

## 4) Checkout Quantity Abuse

Scenario:
User requests unrealistic quantity, for example 25 units.

Risk:
Demo constraints and inventory assumptions are violated.

Mitigation:
- place_order enforces quantity range 1-10.
- Out-of-range requests return explicit guidance.

Expected behavior:
No oversized order is created.

## 5) Missing Checkout Identity Fields

Scenario:
User starts purchase without name/email/phone.

Risk:
Order gets created without required contactability.

Mitigation:
- Agent asks for missing checkout fields across turns.
- Tool-layer validation blocks placement without all required fields.

Expected behavior:
Order is created only after all required details are provided.

## 6) Duplicate Customer Creation

Scenario:
User reorders with an email that already exists.

Risk:
Duplicate customer records, fragmented history.

Mitigation:
- Existing customer is matched by email.
- Existing profile is updated in place when needed.
- New customer is created only when no match exists.

Expected behavior:
Orders consistently link to a single valid customer record.

## 7) Product Lookup by Name vs ID

Scenario:
User asks for product details using a natural name only.

Risk:
Lookup path may ask for product ID instead of resolving name.

Mitigation:
- Product detail lookup is strict by product_id.
- Name resolution is supported in buy/place_order context.
- Agent asks for product ID when required.

Expected behavior:
No wrong product is returned; user gets a clear next step.

## 8) Policy Retrieval Drift

Scenario:
User asks mixed policy questions with noisy wording.

Risk:
Retrieved section may be adjacent but not exact policy intent.

Mitigation:
- Knowledge base search uses intent-aware matching and section boosts.
- Response prioritizes top-scoring relevant section.

Expected behavior:
Policy answer usually aligns to the asked topic; fallback asks clarifying follow-up.

## 9) Escalation Misses in Edge Phrasing

Scenario:
User asks for manager/supervisor in unusual wording.

Risk:
Escalation may be under-triggered for non-standard phrasing.

Mitigation:
- Escalation detector includes broad keyword coverage.
- Router also supports escalate_human action.
- Manual fallback remains available via explicit user request.

Expected behavior:
Most hostile/escalation cases route to human; rare edge phrasing may need one clarification turn.

## Notes

- Deterministic tool validation is the source of truth for all state-changing actions.
- Router flexibility does not bypass business rules in tools layer.
