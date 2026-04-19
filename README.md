# ShopWave Support Agent

ShopWave is a customer support assistant for order lookup, cancellations, refunds, product questions, policy answers, and guided checkout.

It uses a hybrid design:
- LLM router for intent normalization
- deterministic tool execution for business-rule safety

## What Is Included

- Core runtime: agent.py, tools.py, main.py
- Architecture docs: architecture.md, architecture.md.mermaid, architecture.png, architecture.svg
- Test artifacts: data/tickets.json, audit_log_demo.json, logs/tickets_audit_*.jsonl, logs/tickets_summary_*.json

## Tech Stack

- Python 3.11+
- LangGraph + LangChain
- Groq model: llama-3.1-8b-instant (temperature 0)
- Rich (CLI interface)

## Quick Start

### Run on Windows PC (from clone)

1. Open PowerShell.
2. Clone the repository.
3. Move into the project folder.
4. Create and activate a virtual environment.
5. Install dependencies.
6. Create a .env file with your Groq API key.
7. Run the CLI app.

```bash
git clone https://github.com/AdityaTheTechGuy/ShopWaveAgent-Hackathon26.git
cd ShopWaveAgent-Hackathon26

python -m venv venv
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt

echo GROQ_API_KEY=your_groq_api_key_here > .env

python main.py
```

If PowerShell blocks script execution when activating venv, run:

```bash
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

Then run activation again:

```bash
.\venv\Scripts\Activate.ps1
```

You should see the ShopWave welcome panel, then you can test with prompts like:
- what is the status of ORD-1002?
- what is the cost of P012?
- refund order 1002

Example .env:

```bash
GROQ_API_KEY=your_groq_api_key_here
```

## Core Capabilities

- Order status and ownership lookup
- Cancellation flow with eligibility checks
- Refund eligibility and refund processing
- Product lookup and catalog browsing
- Guided checkout with multi-turn detail collection
- Policy Q&A from knowledge base
- Human escalation for angry/suspicious/replacement scenarios
- Async audit logging per session

## Safety Guardrails

- Input cap: 600 characters
- Order ID normalization and validation
- Quantity bounds for checkout: 1-10
- Email format validation
- Phone must be exactly 10 digits
- Actions execute only through validated tool layer

## Routing Model

- Step 1: Router converts user message into structured action JSON.
- Step 2: Executor maps action to deterministic tools.
- Step 3: If routing fails, fallback heuristics still handle common intents.

## Tools Bound at Runtime

- get_customer_info
- get_order
- get_product_info
- list_available_products
- search_knowledge_base
- check_refund_eligibility
- issue_refund
- cancel_order
- place_order
- escalate_to_human

## Testing Status

- Regression suite: 19 tickets
- Last validated run: 19/19 pass
- Demo run output: audit_log_demo.json

## Notes for Evaluators

- Architecture diagram is available in both PNG and SVG for readability.
- Data is fixture-based under data/ and intentionally deterministic.
- Known edge cases and mitigations are documented in failure_modes.md.
