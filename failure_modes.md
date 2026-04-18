# ShopWave AI Support Agent - Failure Modes

This file lists five common problems we tested and how the assistant handles them.

## 1. Invalid Order ID

Scenario:
A user asks for an order that does not exist, for example: ORD-9999.

What can go wrong:
The assistant might show wrong order details or return a vague error.

How we handle it:
- The assistant checks the order using get_order first.
- If no match is found, it returns a clear "order not found" reply.
- The assistant asks for a valid order ID or registered email instead of guessing.

Expected result:
No crash, no fabricated data, and the customer gets a clear next step.

## 2. Repeat Cancellation

Scenario:
A user cancels the same order more than once.

What can go wrong:
A second cancel request could still show success or change data again by mistake.

How we handle it:
- cancel_order checks current status before any update.
- Only processing orders are cancellable.
- If status is already cancelled, the assistant returns a direct already cancelled message.

Expected result:
Order data stays correct and the user gets a simple explanation.

## 3. Refund Requested After Return Window

Scenario:
A user requests a refund after the return deadline has passed.

What can go wrong:
The assistant could approve a refund that should be denied, or deny it without a reason.

How we handle it:
- The assistant checks eligibility using check_refund_eligibility before issue_refund.
- The tool checks delivery status and return deadline.
- If not eligible, the assistant explains why and offers to pass it to a human agent when needed.

Expected result:
Policy is enforced consistently and the customer receives a clear reason.

## 4. Ambiguous Product Request

Scenario:
A user asks to buy a broad category (for example: smartwatch) without enough detail.

What can go wrong:
The assistant may place the wrong order if the request is not clear.

How we handle it:
- Product resolution checks catalog matches first.
- If multiple items match, the assistant asks the user to confirm the exact product.
- If product/company is outside the catalog, the request is denied with available options.

Expected result:
No accidental purchases.

## 5. JSON Read Error from File Encoding (Real Issue During Build)

Scenario:
While updating data files from PowerShell, one JSON file was saved with different text encoding.

What can go wrong:
The app can fail at startup with a JSON read error even if the file looks fine.

How we handle it:
- Data loading now reads JSON in a way that supports both common UTF-8 formats.
- We re-tested startup after the fix.

Expected result:
No startup failures from file encoding differences.

## Notes

- These are the five failure modes included for hackathon review.
- Each one is based on real behavior in this project.
