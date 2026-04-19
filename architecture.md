# ShopWave Architecture

## Dual-Layer Routing Design

The agent uses a **two-layer approach** to balance flexibility with reliability:

1. **Layer 1 - LLM Router** (`_route_user_message`): Normalizes user input to structured JSON
2. **Layer 2 - Deterministic Executor** (`_execute_routed_action`): Maps JSON to deterministic tool calls

This decoupling ensures that business logic remains rule-based and verifiable, while user input handling is flexible via LLM.

## System Flow

```
┌─────────────────────────────────────────────────────────────┐
│ User Input (CLI / main.py)                                  │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
        ┌─────────────────────┐
        │ Input Guard         │
        │ (600 char limit)    │
        └────────┬────────────┘
                 │
                 ▼
    ┌────────────────────────────┐
    │ LAYER 1: LLM Router        │
    │ (_route_user_message)      │
    │                            │
    │ • Parse user intent        │
    │ • TOOL_GUIDE context       │
    │ • Detect escalation words  │
    │ • Output: JSON command     │
    │ {                          │
    │   action: "...",           │
    │   order_id: "...",         │
    │   reason: "..."            │
    │ }                          │
    └────────┬───────────────────┘
             │
             ▼
    ┌────────────────────────────┐
    │ Escalation Check           │
    │ (_is_angry_or_             │
    │  supervisor_request)       │
    │                            │
    │ Keywords: angry, furious,  │
    │ supervisor, manager, etc.  │
    └────────┬───────────────────┘
             │
             ├─── [YES] ──→ escalate_to_human ──→ Response
             │
             └─── [NO] ──→ Continue
                          │
                          ▼
         ┌────────────────────────────────┐
         │ LAYER 2: Deterministic Exec    │
         │ (_execute_routed_action)       │
         │                                │
         │ Map action → tool invocation   │
         │ • order_lookup                 │
         │ • cancel_order (validate)      │
         │ • refund_order (check, issue)  │
         │ • product_lookup               │
         │ • place_order (multi-turn)     │
         │ • policy_question              │
         │ • escalate_human               │
         └────────┬─────────────────────┘
                  │
                  ▼
         ┌────────────────────────────┐
         │ Tool Invocation            │
         │ (tools.py)                 │
         │                            │
         │ Business Logic Layer       │
         │ • Validation checks        │
         │ • Refund/cancel eligibility│
         │ • JSON persistence         │
         │ • Customer auto-create     │
         └────────┬───────────────────┘
                  │
                  ▼
         ┌────────────────────────────┐
         │ Response Formatting        │
         │ (_format_product_response) │
         │                            │
         │ LLM decides:               │
         │ What details to return?    │
         └────────┬───────────────────┘
                  │
                  ▼
        ┌─────────────────────┐
        │ Rich CLI Formatting │
        │ (main.py)           │
        │ Render + Panel      │
        └────────┬────────────┘
                 │
                 ▼
        ┌─────────────────────┐
        │ Audit Log (async)   │
        │ logs/audit_log*.    │
        │ jsonl               │
        └─────────────────────┘
```

## Key Components

### 1. LLM Router Layer

**Function**: `_route_user_message(state, latest_user_text)`

Converts free-form user input to structured JSON commands using the model.

**Input**: User message + conversation history
**Output**: JSON with keys:
- `action`: order_lookup, cancel_order, refund_order, place_order, product_lookup, policy_question, escalate_human, etc.
- `order_id`: Normalized ORD-1234 format
- `product_id`: P001-P012
- `quantity`: 1-10
- `reason`: Escalation reason
- `customer_query`: Context string

**Prompt Strategy**:
- Includes TOOL_GUIDE (all 10 tools documented)
- Temperature=0 for deterministic behavior
- Clear routing rules for escalation, policy, product, checkout scenarios

### 2. Deterministic Executor Layer

**Function**: `_execute_routed_action(action, route, state, ...)`

Maps JSON action to tool invocation with business rule enforcement.

**Actions Handled**:
| Action | Tool | Validation |
|--------|------|-----------|
| order_lookup | get_order | Order ID format |
| refund_order | check_refund_eligibility → issue_refund | Window check, eligibility |
| cancel_order | get_order → cancel_order | Status check (processing only) |
| place_order | place_order | Quantity, email, phone format |
| product_lookup | get_product_info | Product ID exists |
| policy_question | search_knowledge_base | Query string |
| escalate_human | escalate_to_human | Reason provided |

**Design Principle**: All business logic is deterministic and rule-based. LLM router cannot bypass validation.

### 3. Escalation Detection

**Function**: `_is_angry_or_supervisor_request(text)`

Detects 25+ keywords indicating hostile or escalation intent:
- Anger: angry, furious, frustrated, upset, mad, sick of, fed up, ridiculous, useless
- Escalation: supervisor, manager, complaint, dispute, human, agent, real person, speak to
- Suspicious: fraud, scam, suspicious, damaged, replacement, defective

**Action**: If true, immediately route to `escalate_to_human` action.

### 4. Checkout Persistence (Multi-Turn)

Functions for collecting & recalling checkout details:
- `_extract_name_from_detail_text(text)`: Regex-based name extraction
- `_extract_email_from_text(text)`: Email format validation + extraction
- `_extract_phone_from_text(text)`: 10-digit phone extraction

**Multi-turn Flow**:
1. Turn 1: "Buy P011" → Agent asks for name
2. Turn 2: "My name is John Smith" → Extracted, asks for email
3. Turn 3: "john@example.com" → Extracted, asks for phone
4. Turn 4: "5551234567" → Extracted, place_order executed with all details

**Context Accumulation**: Details are retained in `messages` list and searched back through recent history.

### 5. Product Response Formatter

**Function**: `_format_product_response(user_text, product)`

LLM intelligently decides what product information to return.

**Examples**:
- Query: "what is the cost of P012?" → Response: "The SkyBand Fitness Smartwatch costs $159.99."
- Query: "Tell me about P001" → Response: Full details with features, warranty, category
- Query: "What is the warranty on P003?" → Response: "24 months, covers manufacturing defects only."

**Design**: Avoids raw JSON dumps; produces natural, customer-friendly responses.

### 6. Fail-Safe Design

If LLM routing fails or produces invalid JSON:
1. Falls back to legacy heuristic paths
2. Can still execute deterministic operations
3. System remains functional with reduced flexibility

## Data Model

### Customers (JSON)
```json
{
  "customer_id": "C001",
  "name": "Alice Turner",
  "email": "alice.turner@email.com",
  "phone": "4155550101",
  "profile": {...}
}
```

### Orders (JSON)
```json
{
  "order_id": "ORD-1001",
  "customer_id": "C001",
  "product_id": "P011",
  "quantity": 2,
  "amount": 559.98,
  "status": "processing|shipped|delivered",
  "order_date": "2026-04-15",
  "delivery_date": "2026-04-20",
  "refund_status": "none|pending|processed"
}
```

### Products (JSON)
```json
{
  "product_id": "P011",
  "name": "NovaFit Smartwatch X2",
  "company": "TechVibe",
  "category": "watch_smart",
  "price": 279.99,
  "warranty_months": 12,
  "return_window_days": 30,
  "returnable": true
}
```

## Validation & Safety

### Order ID Normalization
- Accepts: "ORD-1234", "1234", bare numeric
- Output: Always "ORD-1234" format
- Validation: Must be 4 digits, 1000-9999 range

### Quantity Validation
- Range: 1-10 units per order
- Enforced in `place_order` tool

### Email Validation
- Pattern: `^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$`
- Enforced in `place_order` and `get_customer_info` lookups

### Phone Validation
- Exactly 10 digits
- US-format (no +1 prefix)
- Enforced in `place_order`

### Refund/Cancel Eligibility
- Refunds: Within return window (checked per product category)
- Cancellations: Order status must be "processing" only

## Audit Logging

### Per-Session Logs
- Format: `logs/audit_log<session_id>.jsonl`
- Content: One JSON per line with {timestamp, type, content, response}
- Written asynchronously during session

### Test Execution Logs
- Format: `logs/tickets_audit_<timestamp>.jsonl`
- Content: One JSON per test ticket with expected vs. actual results

## File Organization

| File | Lines | Purpose |
|------|-------|---------|
| agent.py | ~1000 | LangGraph orchestration, routing, escalation |
| tools.py | ~500 | 10 business logic tools, data persistence |
| main.py | ~150 | CLI, Rich formatting, audit logging |
| data/knowledge-base.md | ~200 | Policy documentation |
| data/tickets.json | 19 entries | Test suite specifications |
