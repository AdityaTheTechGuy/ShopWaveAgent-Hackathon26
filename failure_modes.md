# ShopWave AI Support Agent - Failure Modes

This file lists practical failure scenarios and expected behavior after the latest guardrail and checkout updates.

## 1. Invalid Order ID Format

Scenario:
User sends an invalid ID like `ABC-77` for order status, cancellation, or refund.

What can go wrong:
The system might normalize bad input and fetch the wrong order.

How we handle it:
- `normalize_order_id` now accepts only `ORD-<digits>` or plain digits.
- Invalid input returns a clear validation message.
- No order mutation happens for invalid IDs.

Expected result:
User gets a direct correction message and no data is changed.

## 2. Oversized User Input

Scenario:
User pastes a very long prompt in the CLI.

What can go wrong:
Very large input can stress token usage and degrade response quality.

How we handle it:
- CLI blocks input over 600 characters.
- User gets a friendly prompt to shorten the request.
- The agent does not process oversized input.

Expected result:
Session remains responsive and safe.

## 3. Quantity Abuse During Checkout

Scenario:
User requests very high quantity, for example 25 units.

What can go wrong:
Unrealistic bulk orders can bypass demo constraints.

How we handle it:
- `place_order` enforces quantity range 1 to 10.
- Out-of-range requests return explicit limits.

Expected result:
No oversized orders are created.

## 4. Missing Real-World Checkout Details

Scenario:
User asks to place an order without customer details.

What can go wrong:
Order may be placed without enough identity/contact data.

How we handle it:
- Agent asks follow-up questions for missing full name, email, and phone.
- `place_order` independently validates and blocks checkout when those details are missing.

Expected result:
Order creation only happens after required checkout details are provided.

## 5. Existing vs New Customer During Checkout

Scenario:
User places order with an email that may or may not already exist.

What can go wrong:
Duplicate customer records or stale customer profile details.

How we handle it:
- Existing customer is matched by email and profile fields are updated.
- If no existing customer is found, a new customer ID is created.
- Order and customer totals are updated together.

Expected result:
Customer records stay consistent, and each order links to a valid customer profile.

## Notes

- These scenarios are aligned with the current implementation in `agent.py`, `tools.py`, and `main.py`.
- Tool-layer checks remain the source of truth for business-rule enforcement.
