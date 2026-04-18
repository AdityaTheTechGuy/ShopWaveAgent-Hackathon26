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

Create `.env`:

```bash
GROQ_API_KEY=your_groq_api_key_here
```

## Run

```bash
python main.py
```

Try prompts:

- `my order id is ORD-1002`
- `cancel my order ORD-1010`
- `can I get a refund for ORD-1008?`
- `show details for product P006`
- `what is your cancellation policy for shipped orders?`

## Core Features

- Order status and lookup
- Cancellation workflow with status checks
- Refund eligibility and processing
- Product lookup by product ID
- Policy search from knowledge base
- Order placement via natural language
- Human escalation path
- Audit log output to `logs/`

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
