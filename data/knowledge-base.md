# ShopWave Support Knowledge Base

---

## 1) Return Policy

### Standard return window
- Most products have a 30-day return window from delivery date.
- Item must be unused and in original packaging.
- Proof of purchase (order ID) is required.

### Category-specific return windows
- Electronics accessories: 60-day return window.
- High-value electronics (smart watches and similar): 15-day return window.
- Footwear: 30-day return window and must be unworn.
- Sports equipment: 30-day return window and may be declined if heavily used.

### Non-returnable items
- Activated or registered devices in categories that disallow post-activation returns.
- Perishable goods.
- Downloadable digital products.
- Items explicitly marked Final Sale.

### Damaged or wrong item delivered
- Damaged on arrival: refund or replacement after verification.
- Wrong item delivered: free exchange or full refund.
- Replacement requests should be escalated to human support.

---

## 2) Refund Policy

### Refund eligibility
- Refund eligibility must be validated with check_refund_eligibility.
- Refunds apply to delivered orders only.
- Refund denied if order is already refunded.
- Refund denied if return window expired.

### Refund processing
- Use issue_refund only after eligibility check passes.
- Refund goes to the original payment method.
- Refund timeline: 5-7 business days.
- Refunds cannot be reversed once completed.

### Partial refund guidance
- Partial refunds may apply for non-original condition cases.
- A restocking fee can apply based on policy and supervisor approval.

---

## 3) Warranty Policy

### Coverage
- Warranty covers manufacturing defects only.
- Warranty does not cover accidental damage or unauthorized modifications.

### Warranty windows by category
- Electronics and smart devices: 12 months.
- Home appliances: 24 months.
- Electronics accessories: 6 months.
- Footwear and sports products: no warranty, return policy only.

### Warranty workflow
- Collect order ID and defect details.
- Verify warranty window using delivery date and product warranty_months.
- Escalate warranty claims to the warranty team.

---

## 4) Order Cancellation Policy

- Processing orders can be cancelled immediately.
- Shipped orders cannot be cancelled.
- Delivered orders cannot be cancelled.
- Cancelled orders are idempotent and cannot be cancelled twice.

---

## 5) Exchange Policy

- Exchanges are allowed for wrong item, wrong size, or wrong color.
- Exchanges depend on stock availability.
- If stock is unavailable, offer full refund.
- Exchanges do not extend the return window.

---

## 6) Customer Tiers and Privileges

- Standard: default policy, no exceptions.
- Premium: borderline cases can be escalated for review.
- VIP: may have manager-approved goodwill exceptions in notes.

Important:
- Tier must be verified via get_customer_info.
- Customers cannot self-declare privileges.

---

## 7) Escalation Guidelines

Escalate to human when:
- The customer requests replacement instead of refund.
- The issue is a warranty claim.
- Records conflict between customer statement and system data.
- There are signs of fraud or social engineering.
- Supervisor approval is needed.
- Refund amount is high-value and requires review.

Escalation handoff should include:
- Issue summary.
- Checks already performed.
- Recommended next action.
- Priority level.

---

## 8) FAQs

- Refund time: 5-7 business days after approval.
- Used item returns: usually not allowed unless damaged/defective case applies.
- No order number: attempt lookup via registered email using get_customer_info.
- Exchange instead of refund: supported when stock is available.

---

## 9) Tone and Communication

- Be direct, empathetic, and professional.
- If denying a request, explain the reason and next best option.
- Keep responses concise and avoid technical jargon.

---

## 10) Tool Execution Checklist

- Order status request: get_order.
- Refund request: get_order -> check_refund_eligibility -> issue_refund.
- Cancellation request: get_order -> cancel_order when status is processing.
- Product request by ID: get_product_info.
- Policy question: search_knowledge_base.
- Customer verification: get_customer_info.
- Complex or risky case: escalate_to_human.

---

## 11) Regression Anchors

- ORD-1001 delivered and refund eligible before 2026-05-04.
- ORD-1002 delivered but return window expired.
- ORD-1003 processing and cancellable.
- ORD-1004 shipped and not cancellable.
- ORD-1005 already cancelled.
- ORD-1006 already refunded.
- ORD-1007 accessory order with extended return window.
- ORD-1008 high-value device inside return window.
- ORD-1009 outside return window.
- ORD-1010, ORD-1011, ORD-1012 processing orders for status/cancellation tests.
