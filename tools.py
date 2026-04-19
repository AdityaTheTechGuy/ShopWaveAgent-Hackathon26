import json
import re
from pathlib import Path
from datetime import datetime
from langchain_core.tools import tool

ROOT_DIR = Path(__file__).resolve().parent
ORDERS_FILE = ROOT_DIR / "data" / "orders.json"
CUSTOMERS_FILE = ROOT_DIR / "data" / "customers.json"
KB_FILE = ROOT_DIR / "data" / "knowledge-base.md"
MIN_ORDER_QTY = 1
MAX_ORDER_QTY = 10
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

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
    """Normalize order IDs into ORD-XXXX format if input is valid."""
    oid = (order_id or "").strip().upper()
    if oid.startswith("ORD-") and oid[4:].isdigit():
        return oid
    if oid.isdigit():
        return f"ORD-{oid}"
    return ""


def next_customer_id() -> str:
    """Generate the next customer ID in CXXX format."""
    max_num = 0
    for customer in customers:
        customer_id = str(customer.get("customer_id", "")).upper()
        if customer_id.startswith("C") and customer_id[1:].isdigit():
            max_num = max(max_num, int(customer_id[1:]))
    return f"C{max_num + 1:03d}"


def matches_customer_query(customer: dict, query: str) -> bool:
    """Return True when query matches customer email, name, or ID."""
    q = query.strip().lower()
    return q in {
        customer.get("email", "").lower(),
        customer.get("name", "").lower(),
        customer.get("customer_id", "").lower(),
    }


def is_valid_email(email: str) -> bool:
    """Return True when email format looks valid."""
    return bool(EMAIL_PATTERN.match((email or "").strip()))


def normalize_phone_10(phone_text: str) -> str:
    """Return 10-digit phone number or empty string if invalid."""
    digits = "".join(ch for ch in (phone_text or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def resolve_customer(customer_query: str | None):
    """Find a customer by email, name, or ID. Default to guest (C000)."""
    if not customer_query:
        return next((c for c in customers if c["customer_id"] == "C000"), None)

    raw_query = customer_query.strip()
    q = raw_query.lower()
    if q in {"guest", "no account", "unknown"}:
        return next((c for c in customers if c["customer_id"] == "C000"), None)

    # Handle free-form text like "Customer email: x@y.com. ..."
    email_match = re.search(r"\b[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}\b", raw_query)
    if email_match:
        q = email_match.group(0).strip().lower()
    else:
        id_match = re.search(r"\bC\d{3}\b", raw_query.upper())
        if id_match:
            q = id_match.group(0).lower()

    # Search by email, name, or ID
    for c in customers:
        if matches_customer_query(c, q):
            return c
    
    # Default to guest
    return next((c for c in customers if c["customer_id"] == "C000"), None)


def extract_customer_profile(request: str, customer_query: str | None) -> dict:
    """Extract customer details from checkout text and optional query hint."""
    text = (request or "").strip()
    lowered = text.lower()
    profile = {
        "name": "",
        "email": "",
        "phone": "",
        "email_provided": False,
        "phone_provided": False,
    }

    email_marker = re.search(r"\b(?:email|e-mail)\b", text, re.IGNORECASE)
    if email_marker:
        profile["email_provided"] = True

    email_match = re.search(r"\b[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}\b", text)
    if email_match:
        profile["email"] = email_match.group(0).strip().lower().rstrip(".,;:")
        profile["email_provided"] = True

    phone_match = re.search(r"(?:phone|mobile|contact|number)\s*(?:is|:)?\s*([+()\d\-\s]{7,24})", text, re.IGNORECASE)
    if phone_match:
        raw_phone = " ".join(phone_match.group(1).split()).rstrip(".,;:")
        profile["phone_provided"] = True
        profile["phone"] = normalize_phone_10(raw_phone)
    else:
        # Fallback for plain entries like ", 8900199912,"
        standalone_phone = re.search(r"(?<!\d)(\d{10})(?!\d)", text)
        if standalone_phone:
            profile["phone_provided"] = True
            profile["phone"] = standalone_phone.group(1)

    name_markers = ["my name is", "name is", "name:", "i am", "this is"]
    for marker in name_markers:
        idx = lowered.find(marker)
        if idx == -1:
            continue

        tail = text[idx + len(marker):].strip(" .,:;-")
        tokens = [t.strip(".,:;-") for t in tail.split() if t.strip(".,:;-")]
        name_tokens = []
        for token in tokens:
            if "@" in token or any(ch.isdigit() for ch in token):
                break
            name_tokens.append(token)
            if len(name_tokens) >= 4:
                break
        if len(name_tokens) >= 2:
            profile["name"] = " ".join(name_tokens)
            break

    if not profile["name"]:
        # Fallback for comma-separated checkout style:
        # "Aditya Gupta, aditya@email.com, 8900199912, 2"
        for segment in text.split(","):
            candidate = segment.strip(" .,:;-")
            if not candidate:
                continue
            if "@" in candidate or any(ch.isdigit() for ch in candidate):
                continue
            words = [w for w in candidate.split() if w]
            if len(words) < 2 or len(words) > 4:
                continue
            if any(w.lower() in {"buy", "order", "units", "quantity", "phone", "email"} for w in words):
                continue
            if all(token.replace("-", "").isalpha() for token in words):
                profile["name"] = " ".join(words)
                break

    query = (customer_query or "").strip()
    if not profile["email"] and "@" in query and "." in query.split("@")[-1]:
        profile["email"] = query.lower().rstrip(".,;:")
        profile["email_provided"] = True

    if not profile["phone_provided"] and any(ch.isdigit() for ch in query):
        profile["phone_provided"] = True
        profile["phone"] = normalize_phone_10(query)

    if not profile["name"] and query and "@" not in query:
        q_lower = query.lower()
        if not q_lower.startswith("c") and q_lower not in {"guest", "no account", "unknown"}:
            words = [w for w in query.split() if w]
            if len(words) >= 2:
                profile["name"] = " ".join(words[:3])

    return profile


def resolve_or_create_customer(profile: dict, customer_query: str | None):
    """Find an existing customer and update details, or create a new record."""
    existing_customer = None
    email = profile.get("email", "").strip().lower()

    if email:
        existing_customer = next(
            (c for c in customers if c.get("email", "").strip().lower() == email),
            None,
        )

    if not existing_customer and customer_query:
        candidate = resolve_customer(customer_query)
        if candidate and candidate.get("customer_id") != "C000":
            existing_customer = candidate

    if existing_customer:
        if profile.get("name"):
            existing_customer["name"] = profile["name"]
        if profile.get("email"):
            existing_customer["email"] = profile["email"]
        if profile.get("phone"):
            existing_customer["phone"] = profile["phone"]
        return existing_customer

    if not profile.get("name") or not profile.get("email"):
        return None

    new_customer = {
        "customer_id": next_customer_id(),
        "name": profile["name"],
        "email": profile["email"],
        "phone": profile.get("phone") or "N/A",
        "tier": "standard",
        "member_since": datetime.now().strftime("%Y-%m-%d"),
        "total_orders": 0,
        "total_spent": 0.0,
        "address": {
            "street": "N/A",
            "city": "N/A",
            "state": "N/A",
            "zip": "00000",
        },
        "notes": "Customer profile created by support assistant during checkout.",
    }
    customers.append(new_customer)
    return new_customer


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
        # Fuzzy fallback: match by informative token overlap (name/company/ID).
        stop_words = {
            "i", "want", "to", "buy", "order", "please", "my", "a", "an", "the",
            "unit", "units", "qty", "quantity", "product", "products",
            "for", "of", "this", "that", "is", "it",
        }

        def token_set(value: str) -> set[str]:
            return {
                tok
                for tok in re.split(r"[^a-z0-9]+", (value or "").lower())
                if tok and tok not in stop_words
            }

        query_tokens = token_set(req)
        if query_tokens:
            scored = []
            for p in products:
                if company_hint and p.get("company", "").lower() != company_hint:
                    continue
                product_tokens = token_set(p.get("name", "")) | token_set(p.get("company", "")) | token_set(p.get("product_id", ""))
                score = len(query_tokens & product_tokens)
                if score > 0:
                    scored.append((score, p))

            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)
                top_score = scored[0][0]
                top_matches = [p for s, p in scored if s == top_score]
                if len(top_matches) == 1:
                    return {"status": "ok", "product": top_matches[0]}
                return {
                    "status": "ambiguous",
                    "message": "Multiple products found",
                    "choices": [f"{p['name']} ({p['product_id']})" for p in top_matches[:4]],
                }

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
        if matches_customer_query(c, q):
            return c
    return {"error": "Customer not found"}

@tool("get_order")
def get_order(order_id: str):
    """Look up an order by order ID."""
    oid = normalize_order_id(order_id)
    if not oid:
        return {"error": "Invalid order ID format. Use ORD-1234 or 1234."}
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

    intent_map = {
        "cancellation": {"cancel", "cancellation"},
        "refund": {"refund", "money", "back"},
        "return": {"return", "returns", "exchange"},
        "warranty": {"warranty", "guarantee"},
        "escalation": {"escalate", "escalation", "human", "agent"},
    }

    for entry in sections:
        title = entry["title"]
        content = entry["content"]
        haystack = f"{title}\n{content}".lower()
        token_hits = sum(1 for tok in query_tokens if tok in haystack)
        phrase_bonus = 3 if q in haystack else 0
        intent_bonus = 0
        title_lower = title.lower()
        for section_key, keywords in intent_map.items():
            if any(keyword in q for keyword in keywords) and section_key in title_lower:
                intent_bonus += 4

        score = token_hits + phrase_bonus + intent_bonus
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
    if not oid:
        return {"eligible": False, "reason": "Invalid order ID format. Use ORD-1234 or 1234."}
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
    if not oid:
        return {"success": False, "message": "Invalid order ID format. Use ORD-1234 or 1234."}
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
    if not oid:
        return {"success": False, "message": "Invalid order ID format. Use ORD-1234 or 1234."}
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

    customer_profile = extract_customer_profile(request, customer_query)
    existing_customer = resolve_customer(customer_query)
    if existing_customer and existing_customer.get("customer_id") != "C000":
        if not customer_profile.get("name") and existing_customer.get("name"):
            customer_profile["name"] = str(existing_customer.get("name", "")).strip()
        if not customer_profile.get("email") and existing_customer.get("email"):
            customer_profile["email"] = str(existing_customer.get("email", "")).strip().lower()
            customer_profile["email_provided"] = True
        if not customer_profile.get("phone") and existing_customer.get("phone"):
            phone = normalize_phone_10(str(existing_customer.get("phone", "")))
            customer_profile["phone"] = phone
            customer_profile["phone_provided"] = bool(phone)

    missing_details = []
    invalid_details = []
    if not customer_profile.get("name"):
        missing_details.append("full name")
    if not customer_profile.get("email_provided"):
        missing_details.append("email address")
    elif not is_valid_email(customer_profile.get("email", "")):
        invalid_details.append("email format is invalid")
    if not customer_profile.get("phone_provided"):
        missing_details.append("phone number")
    elif not customer_profile.get("phone"):
        invalid_details.append("phone number must be exactly 10 digits")

    if missing_details:
        return "Please share these checkout details: " + ", ".join(missing_details) + "."
    if invalid_details:
        return "Please correct these checkout details: " + ", ".join(invalid_details) + "."

    resolved_customer = resolve_or_create_customer(customer_profile, customer_query)
    if not resolved_customer:
        return "Unable to resolve customer profile for checkout. Please provide full name and email."

    product = resolved_product["product"]
    resolved_quantity = parse_quantity_from_request(request, quantity)
    if resolved_quantity < MIN_ORDER_QTY:
        return f"Quantity must be at least {MIN_ORDER_QTY}."
    if resolved_quantity > MAX_ORDER_QTY:
        return f"For safety, you can place up to {MAX_ORDER_QTY} units per order."

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