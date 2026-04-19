# ShopWave Support Agent

A lightweight AI customer support agent for handling orders, cancellations, refunds, product lookups, and policy questions.

## Hackathon Submission Files

- `README.md`
- `architecture.md`
- `architecture.md.mermaid`
- `failure_modes.md`
- `audit_log_demo.json`
- `agent.py`
- `tools.py`
- `main.py`
- `requirements.txt`
- `data/` (fixtures)

## Tech Stack

- LangGraph
- LangChain
- Groq API (`llama-3.1-8b-instant`)
- Rich
- Python 3.11+

## Project Structure

```text
ShopWaveAgent-Hackathon26/
├── README.md
├── architecture.md
├── architecture.md.mermaid
├── failure_modes.md
├── audit_log_demo.json
├── agent.py
├── tools.py
├── main.py
├── requirements.txt
├── data/
│   ├── customers.json
│   ├── products.json
│   ├── orders.json
│   ├── tickets.json
│   └── knowledge-base.md
└── logs/
```

## Setup

```bash
cd ShopWaveAgent-Hackathon26
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Important judge setup steps:

1. Create a `.env` file.
2. Add `GROQ_API_KEY=your_key`.


Example `.env` contents:

```bash
GROQ_API_KEY=your_groq_api_key_here
```

## Run

```bash
python main.py
```

Challenge checks:

- `I want to buy a smartwatch.`
- `Buy 2 units of P011. My name is Alice Turner, email alice.turner@email.com, phone 4155550101.`
- `Buy 25 units of P011. My name is Test User, email test.user@example.com, phone 9995551212.`
- `Buy 1 unit of P011. My name is Test User, email test@@example, phone 4155550101.`
- `Buy 1 unit of P011. My name is Test User, email test.user@example.com, phone 14155550101.`
- `Cancel my order.`
- `Cancel order ABC-77.`
- `Refund order 1002.`
- `Refund order ORD-9999.`
- `Buy 1 unit of P010. My name is New Person, email new.person@example.com, phone 7775551111.`

## Core Features

- Order status and lookup
- Cancellation workflow with status checks
- Refund eligibility and processing
- Product lookup by product ID
- Policy search from knowledge base
- Order placement with guided checkout details (name, email, phone)
- Existing customer auto-update by email; auto-create new customer profile when needed
- Human escalation path
- Audit log output to `logs/`

## Safety Guardrails

- Input length cap in CLI (600 characters)
- Strict order ID format validation (`ORD-1234` or `1234`)
- Quantity limits for order placement (1 to 10 units per order)
- Email format validation for checkout
- Phone validation: must be exactly 10 digits

## Implemented Tools

- `get_customer_info`
- `get_order`
- `get_product_info`
- `list_available_products`
- `search_knowledge_base`
- `check_refund_eligibility`
- `issue_refund`
- `cancel_order`
- `place_order`
- `escalate_to_human`

## Notes

- Business logic is enforced in `tools.py`.
- The agent orchestration and tool routing are in `agent.py`.
- CLI and audit logging are in `main.py`.
- Customer and order records are updated together during successful checkout.
