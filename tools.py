import json
import re
from pathlib import Path
from datetime import datetime
from langchain_core.tools import tool

ROOT_DIR = Path(__file__).resolve().parent
ORDERS_FILE = ROOT_DIR / "data" / "orders.json"
CUSTOMERS_FILE = ROOT_DIR / "data" / "customers.json"
KB_FILE = ROOT_DIR / "data" / "knowledge-base.md"

def load_data(filename):
    """Load one of the small JSON fixtures from the data folder."""
    # Use utf-8-sig so files saved from PowerShell with BOM still parse correctly.
    with open(ROOT_DIR / "data" / filename, "r", encoding="utf-8-sig") as f:
        return json.load(f)

customers = load_data("customers.json")
products = load_data("products.json")
orders = load_data("orders.json")


def get_allowed_companies() -> list[str]:
    """Return sorted unique company names from product catalog."""
    return sorted({str(p.get("company", "")).strip() for p in products if p.get("company")})


def build_catalog_summary() -> str:
    """Return a short plain-text list of products and companies customers can buy."""
    lines = ["Available products and companies:"]
    for p in products:
        lines.append(f"- {p['name']} ({p['product_id']}) by {p.get('company', 'Unknown')}")
    return "\n".join(lines)


def extract_company_hint(request: str) -> str:
    """Extract a simple 'from <company>' hint from purchase request text."""
    match = re.search(r"\bfrom\s+([a-z0-9][a-z0-9&\-\s]{1,40})", request.lower())
    if not match:
        return ""
    return " ".join(match.group(1).split()).strip()


def save_orders() -> None:
    """Persist in-memory orders to disk."""
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, indent=2)


def save_customers() -> None:
    """Persist in-memory customers to disk."""
    with open(CUSTOMERS_FILE, "w", encoding="utf-8") as f:
        json.dump(customers, f, indent=2)


def next_order_id() -> str:
    """Generate the next order ID in ORD-XXXX format."""
    max_num = 1000
    for order in orders:
        match = re.search(r"ORD-(\d+)", order.get("order_id", ""))
        if match:
            max_num = max(max_num, int(match.group(1)))
    return f"ORD-{max_num + 1}"


def normalize_order_id(order_id: str) -> str:
    """Normalize order IDs into ORD-XXXX format."""
    oid = (order_id or "").strip().upper()
    digits = re.sub(r"\D", "", oid)
    if digits:
        return f"ORD-{digits}"
    return oid


def resolve_customer(customer_query: str | None):
    """Find a customer by email, name, or ID. Default to guest (C000)."""
    if not customer_query:
        return next((c for c in customers if c["customer_id"] == "C000"), None)

    q = customer_query.strip().lower()
    if q in {"guest", "no account", "unknown"}:
        return next((c for c in customers if c["customer_id"] == "C000"), None)

    # Search by email, name, or ID
    for c in customers:
        if q == c["email"].lower() or q == c["name"].lower() or q == c["customer_id"].lower():
            return c
    
    # Default to guest
    return next((c for c in customers if c["customer_id"] == "C000"), None)


def parse_quantity_from_request(request: str, fallback_quantity: int) -> int:
    """Extract quantity from request text."""
    if fallback_quantity > 0:
        return fallback_quantity
    
    match = re.search(r"\b(\d+)\b", request)
    return int(match.group(1)) if match else 1


def resolve_product_from_request(request: str):
    """Find a product by ID or name match."""
    req = request.strip().lower()
    company_hint = extract_company_hint(request)
    allowed_companies = get_allowed_companies()
    allowed_companies_lower = {c.lower(): c for c in allowed_companies}

    if company_hint and company_hint not in allowed_companies_lower:
        return {
            "status": "invalid_company",
            "message": "Company not found in our catalog.",
            "allowed_companies": allowed_companies,
        }
    
    # Check for product ID (P001, P002, etc)
    id_match = re.search(r"P\d{3}", req.upper())
    if id_match:
        pid = id_match.group(0)
        p = next((x for x in products if x["product_id"] == pid), None)
        if p:
            if company_hint and p.get("company", "").lower() != company_hint:
                return {
                    "status": "invalid_company",
                    "message": f"{p['name']} is not sold by '{company_hint}'.",
                    "allowed_companies": allowed_companies,
                }
            return {"status": "ok", "product": p}
    
    # Search by product name
    matches = []
    for p in products:
        name = p.get("name", "").lower()
        if req in name or name in req:
            matches.append(p)

    if company_hint:
        matches = [p for p in matches if p.get("company", "").lower() == company_hint]
    
    if not matches:
        return {"status": "not_found", "message": "Product not found."}
    
    if len(matches) > 1:
        return {
            "status": "ambiguous",
            "message": "Multiple products found",
            "choices": [f"{p['name']} ({p['product_id']})" for p in matches[:4]]
        }
    
    return {"status": "ok", "product": matches[0]}


def load_kb_sections() -> list[dict]:
    """Parse KB markdown into searchable sections."""
    with open(KB_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    sections = []
    current_title = "overview"
    current_lines = []

    def flush_section() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append({"title": current_title, "content": content})

    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith("## "):
            flush_section()
            current_title = line[3:].strip().lower()
            current_lines = []
            continue
        if line.strip() == "---":
            continue
        current_lines.append(line)

    flush_section()
    return sections


def extract_kb_highlights(content: str, query_tokens: set[str], max_lines: int = 4) -> list[str]:
    """Extract the most relevant lines from a KB section."""
    highlights = []
    for line in content.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if any(tok in lowered for tok in query_tokens):
            highlights.append(cleaned)
        if len(highlights) >= max_lines:
            break
    if highlights:
        return highlights

    # Fallback to first few non-empty lines when no token match is found.
    for line in content.splitlines():
        cleaned = line.strip()
        if cleaned:
            highlights.append(cleaned)
        if len(highlights) >= max_lines:
            break
    return highlights

@tool("get_customer_info")
def get_customer_info(query: str):
    """Look up a customer by email, name, or ID."""
    q = query.strip().lower()
    for c in customers:
        if q == c["email"].lower() or q == c["name"].lower() or q == c["customer_id"].lower():
            return c
    return {"error": "Customer not found"}

@tool("get_order")
def get_order(order_id: str):
    """Look up an order by order ID."""
    oid = normalize_order_id(order_id)
    return next((o for o in orders if o["order_id"] == oid), {"error": "Order not found"})

@tool("get_product_info")
def get_product_info(product_id: str):
    """Look up a product by ID."""
    pid = product_id.strip().upper()
    return next((p for p in products if p["product_id"] == pid), {"error": "Product not found"})

@tool("search_knowledge_base")
def search_knowledge_base(query: str, section: str = ""):
    """Search support policies and return ranked section highlights."""
    q = (query or "").strip().lower()
    if not q:
        return {"error": "Please provide a policy question."}

    query_tokens = {tok for tok in re.split(r"\W+", q) if len(tok) > 2}
    sections = load_kb_sections()

    if section.strip():
        section_filter = section.strip().lower()
        sections = [s for s in sections if section_filter in s["title"]]

    ranked = []
    for entry in sections:
        title = entry["title"]
        content = entry["content"]
        haystack = f"{title}\n{content}".lower()
        token_hits = sum(1 for tok in query_tokens if tok in haystack)
        phrase_bonus = 3 if q in haystack else 0
        score = token_hits + phrase_bonus
        if score > 0:
            ranked.append((score, entry))

    if not ranked:
        return {
            "query": query,
            "matches": [],
            "message": "No matching policy found. Try keywords like refund, cancellation, warranty, return, or escalation.",
        }

    ranked.sort(key=lambda x: x[0], reverse=True)
    top = ranked[:3]
    matches = []
    for score, entry in top:
        matches.append(
            {
                "section": entry["title"],
                "score": score,
                "highlights": extract_kb_highlights(entry["content"], query_tokens),
            }
        )

    return {"query": query, "matches": matches}

@tool("check_refund_eligibility")
def check_refund_eligibility(order_id: str):
    """Check if an order can be refunded."""
    oid = normalize_order_id(order_id)
    order = next((o for o in orders if o["order_id"] == oid), None)
    if not order:
        return {"eligible": False, "reason": "Order not found"}

    if str(order.get("refund_status", "")).lower() == "refunded":
        return {"eligible": False, "reason": "Refund already processed"}

    if str(order.get("status", "")).lower() != "delivered":
        return {"eligible": False, "reason": "Only delivered orders are eligible for refund"}
    
    if not order.get("return_deadline"):
        return {"eligible": False, "reason": "Order is not returnable"}
    
    deadline = datetime.strptime(order["return_deadline"], "%Y-%m-%d")
    if datetime.now() > deadline:
        return {"eligible": False, "reason": "Return window expired"}
    
    return {
        "eligible": True,
        "reason": "Order is eligible for refund",
        "order_id": oid,
        "return_deadline": order["return_deadline"],
    }

@tool("issue_refund")
def issue_refund(order_id: str):
    """Process a refund for an order."""
    oid = normalize_order_id(order_id)
    order = next((o for o in orders if o["order_id"] == oid), None)
    if not order:
        return {"success": False, "message": "Order not found"}

    if str(order.get("refund_status", "")).lower() == "refunded":
        return {"success": False, "message": f"Refund already processed for {oid}"}

    status = str(order.get("status", "")).lower()
    if status != "delivered":
        return {"success": False, "message": f"Refund not allowed for order status: {status}"}

    deadline_str = order.get("return_deadline")
    if not deadline_str:
        return {"success": False, "message": "Refund not allowed for non-returnable order"}
    deadline = datetime.strptime(deadline_str, "%Y-%m-%d")
    if datetime.now() > deadline:
        return {"success": False, "message": "Refund denied: return window expired"}
    
    order["refund_status"] = "refunded"
    save_orders()
    return {"success": True, "message": f"Refund processed for {oid}"}


@tool("cancel_order")
def cancel_order(order_id: str):
    """Cancel an order if it's in processing state."""
    oid = normalize_order_id(order_id)
    order = next((o for o in orders if o["order_id"] == oid), None)
    if not order:
        return {"success": False, "message": "Order not found"}
    
    status = (order.get("status") or "").lower()
    if status == "cancelled":
        return {"success": False, "message": "Order already cancelled"}
    if status != "processing":
        return {"success": False, "message": f"Cannot cancel order with status: {status}"}
    
    order["status"] = "cancelled"
    save_orders()
    return {"success": True, "message": f"Order {oid} cancelled"}


@tool("place_order")
def place_order(request: str, quantity: int = 0, customer_query: str = "guest"):
    """Create a new processing order from natural purchase request text."""
    if not request or not request.strip():
        return f"Please pick from our catalog.\n{build_catalog_summary()}"

    resolved_customer = resolve_customer(customer_query)
    if not resolved_customer:
        return "Unable to resolve customer profile for checkout."

    resolved_product = resolve_product_from_request(request)
    if resolved_product["status"] == "invalid_company":
        companies = ", ".join(resolved_product.get("allowed_companies", []))
        return (
            "Order denied: that company is not available. "
            f"Allowed companies: {companies}.\n{build_catalog_summary()}"
        )
    if resolved_product["status"] == "not_found":
        return (
            "Order denied: that product is not available. "
            "Please choose one of the listed products.\n"
            f"{build_catalog_summary()}"
        )
    if resolved_product["status"] == "ambiguous":
        options = ", ".join(resolved_product.get("choices", []))
        return f"I found multiple matches: {options}. Please confirm which one you want."

    product = resolved_product["product"]
    resolved_quantity = parse_quantity_from_request(request, quantity)
    if resolved_quantity < 1:
        return "Quantity must be at least 1."

    order_id = next_order_id()
    order_date = datetime.now().strftime("%Y-%m-%d")
    amount = round(float(product["price"]) * resolved_quantity, 2)

    new_order = {
        "order_id": order_id,
        "order_name": product["name"],
        "company": product.get("company", "ShopWave"),
        "customer_id": resolved_customer["customer_id"],
        "product_id": product["product_id"],
        "quantity": resolved_quantity,
        "amount": amount,
        "status": "processing",
        "order_date": order_date,
        "delivery_date": None,
        "return_deadline": None,
        "refund_status": None,
        "notes": "Order placed via support assistant.",
    }

    orders.append(new_order)
    resolved_customer["total_orders"] = int(resolved_customer.get("total_orders", 0)) + 1
    resolved_customer["total_spent"] = round(float(resolved_customer.get("total_spent", 0)) + amount, 2)

    save_orders()
    save_customers()
    return new_order


@tool("send_reply")
def send_reply(content:str):
    """Return a short confirmation for a customer reply."""
    return f"Reply sent to customer: {content}"

@tool("list_available_products")
def list_available_products():
    """List all products and companies available for purchase."""
    return build_catalog_summary()

@tool("escalate_to_human")
def escalate_to_human(reason:str):
    """Escalate the ticket with a plain explanation of why."""
    return f"Ticket escalated to human agent. Reason: {reason}"