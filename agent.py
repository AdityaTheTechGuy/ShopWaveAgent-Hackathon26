import os
import json
import re
from typing import Annotated, TypedDict
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_groq import ChatGroq
from langchain_core.messages import ToolMessage
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.messages import AIMessage

from tools import (
    get_customer_info,
    get_order,
    get_product_info,
    list_available_products,
    search_knowledge_base,
    check_refund_eligibility,
    issue_refund,
    cancel_order,
    place_order,
    escalate_to_human
)

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found. Please set it in .env before running.")

# State Definition
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
 
chat_model = ChatGroq(model="llama-3.1-8b-instant", temperature=0)
tools_registry = [
    get_customer_info,
    get_order,
    get_product_info,
    list_available_products,
    search_knowledge_base,
    check_refund_eligibility,
    issue_refund,
    cancel_order,
    place_order,
    escalate_to_human
]
chat_model_with_tools = chat_model.bind_tools(tools_registry)

TOOL_GUIDE = (
    "Tools available:\n"
    "- get_customer_info(query): find customer by email, name, or customer ID.\n"
    "- get_order(order_id): fetch order details and ownership.\n"
    "- get_product_info(product_id): fetch a product by ID.\n"
    "- list_available_products(): return the catalog for shopping.\n"
    "- search_knowledge_base(query, section?): return matching policy text.\n"
    "- check_refund_eligibility(order_id): validate refund eligibility.\n"
    "- issue_refund(order_id): issue refund after eligibility check.\n"
    "- cancel_order(order_id): cancel processing orders.\n"
    "- place_order(request, quantity?, customer_query?): create an order after checkout details are present.\n"
    "- escalate_to_human(reason): hand off angry, abusive, suspicious, or unresolved cases to a human."
)

ROUTER_PROMPT = (
    "You are a routing layer for a customer support assistant. "
    "Convert the user's latest message and recent context into a single JSON object only. "
    "Do not answer the user. Do not add markdown. Return valid JSON with these keys: "
    "action, order_id, product_id, quantity, customer_query, followup, confidence, reason. "
    "Allowed action values are: order_lookup, order_owner, cancel_order, refund_order, place_order, "
    "product_lookup, policy_question, catalog_request, replacement, escalate_human, out_of_scope, clarify. "
    "Use null when a field is unknown. "
    f"{TOOL_GUIDE}\n"
    "Routing rules: \n"
    "- Normalize cancellation/refund/order IDs to ORD-1234 when possible.\n"
    "- Normalize product IDs when possible for product lookup or buy intent.\n"
    "- For order follow-up questions, use order_owner or order_lookup.\n"
    "- For purchase or reorder requests, use place_order.\n"
    "- For policy/warranty/return/cancellation policy questions, use policy_question.\n"
    "- If the user sounds angry, hostile, repeated, or asks for a supervisor/human/help from manager, use escalate_human.\n"
    "- If the user mentions damage, replacement, fraud, or suspicious behavior, use escalate_human.\n"
    "- If the message is too vague, choose clarify and set followup to the exact next question."
)

SYSTEM_PROMPT = (
    "You are a customer support agent for ShopWave. Help customers with orders, refunds, "
    "cancellations, exchanges, and product questions.\n\n"
    "Execution rules:\n"
    "- Always use tools to verify facts. Do not guess policy or order data.\n"
    "- Use get_customer_info for customer lookup (email, name, or customer ID).\n"
    "- For order status or ownership questions, use get_order first.\n"
    "- For refund requests, follow this exact sequence: get_order -> check_refund_eligibility -> issue_refund only if eligible is true.\n"
    "- For cancellations, call get_order first, then cancel_order only when status is processing.\n"
    "- If a refund request already includes a valid order ID, do not ask extra clarification first; run the refund sequence immediately.\n"
    "- If a cancellation request already includes a valid order ID, do not ask for the order ID again.\n"
    "- Before running place_order, cancel_order, check_refund_eligibility, or issue_refund, collect missing required details by asking follow-up questions.\n"
    "- Required details: place_order => product (name or product ID), quantity, full name, email, and phone number; cancellation/refund => order ID.\n"
    "- For policy questions, call search_knowledge_base and cite the matching policy section briefly.\n"
    "- For product lookup, use get_product_info by ID. For buying options, use list_available_products. For buying intent, use place_order.\n"
    "- Escalate with escalate_to_human for replacement requests, suspicious behavior, or conflicting records.\n\n"
    "Response style:\n"
    "- Keep replies concise, clear, and empathetic.\n"
    "- If a request is denied, explain why and provide the next best option.\n"
    "- Never claim an action succeeded unless a tool result confirms it."
)

def _message_text(chat_message) -> str:
    content = getattr(chat_message, "content", "")
    return content if isinstance(content, str) else str(content)


def _json_object_from_text(text: str) -> dict:
    if not text:
        return {}
    candidate = text.strip()
    first = candidate.find("{")
    last = candidate.rfind("}")
    if first == -1 or last == -1 or last <= first:
        return {}
    snippet = candidate[first:last + 1]
    try:
        parsed = json.loads(snippet)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _route_user_message(latest_user_text: str, recent_messages: list) -> dict:
    recent_context = []
    for msg in recent_messages[-6:]:
        text = _message_text(msg).strip()
        if text:
            role = "user" if isinstance(msg, HumanMessage) else "assistant"
            recent_context.append(f"{role}: {text}")

    prompt = (
        f"Recent context:\n{chr(10).join(recent_context)}\n\n"
        f"Latest user message:\n{latest_user_text}\n\n"
        "Return JSON only."
    )

    try:
        response = chat_model.invoke([
            SystemMessage(content=ROUTER_PROMPT),
            HumanMessage(content=prompt),
        ])
        route = _json_object_from_text(_message_text(response))
    except Exception:
        route = {}

    if not route:
        return {}

    action = str(route.get("action", "")).strip().lower()
    if action not in {
        "order_lookup",
        "order_owner",
        "cancel_order",
        "refund_order",
        "place_order",
        "product_lookup",
        "policy_question",
        "catalog_request",
        "replacement",
        "escalate_human",
        "out_of_scope",
        "clarify",
    }:
        return {}

    return route


def _has_order_id(text: str) -> bool:
    cleaned = text.replace(":", " ").replace("#", " ").upper()
    words = cleaned.split()
    for i, word in enumerate(words):
        if word.startswith("ORD-") and word[4:].isdigit():
            return True
        if word.isdigit() and i > 0 and words[i - 1] in {"ORDER", "ID", "NUMBER"}:
            return True
    return False


def _extract_order_id(text: str) -> str:
    if not text:
        return ""
    normalized = text.upper()
    tagged = re.search(r"\bORD-(\d{4})\b", normalized)
    if tagged:
        return f"ORD-{tagged.group(1)}"

    spaced = re.search(r"\bORD\s*[-:]?\s*(\d{4})\b", normalized)
    if spaced:
        return f"ORD-{spaced.group(1)}"

    # Accept plain 4-digit IDs only when context clearly indicates an order ID.
    marker_match = re.search(
        r"\b(?:ORDER(?:\s*ID)?|ID|NUMBER)\s*(?:IS|:|#)?\s*(\d{4})\b",
        normalized,
    )
    if marker_match:
        return f"ORD-{marker_match.group(1)}"

    shorthand_match = re.search(
        r"^\s*(?:REFUND|CANCEL|CANCELLATION)\s*(?:ORDER\s*)?(?:ID\s*)?(?:#|:)?\s*(\d{4})\b",
        normalized,
    )
    if shorthand_match:
        return f"ORD-{shorthand_match.group(1)}"

    return ""


def _extract_product_id(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"\bP(\d{3})\b", text.upper())
    if match:
        return f"P{match.group(1)}"
    return ""


def _last_order_id_from_messages(messages: list) -> str:
    """Return the most recent order ID mentioned in conversation history."""
    for msg in reversed(messages):
        oid = _extract_order_id(_message_text(msg))
        if oid:
            return oid
    return ""


def _last_product_id_from_messages(messages: list) -> str:
    """Return the most recent product ID mentioned in conversation history."""
    for msg in reversed(messages):
        product_id = _extract_product_id(_message_text(msg))
        if product_id:
            return product_id
    return ""


def _last_checkout_name_from_messages(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            name = _extract_name_from_detail_text(_message_text(msg))
            if name:
                return name
    return ""


def _cancel_context_active(messages: list) -> bool:
    recent = messages[-6:]
    for msg in recent:
        if isinstance(msg, AIMessage):
            text = _message_text(msg).lower()
            if "share your order id" in text or "cancel" in text and "order id" in text:
                return True
    return False


def _purchase_context_active(messages: list) -> bool:
    """Detect active buying flow from recent assistant turns."""
    recent = messages[-8:]
    for msg in recent:
        if isinstance(msg, AIMessage):
            text = _message_text(msg).lower()
            if any(
                phrase in text
                for phrase in [
                    "i found multiple matches",
                    "confirm which one you want",
                    "tell me the product id and quantity",
                    "checkout details",
                    "please share these checkout details",
                ]
            ):
                return True
    return False


def _extract_quantity(text: str) -> int:
    if not text:
        return 0

    explicit = re.search(r"\b(?:qty|quantity|units?)\s*(?:is|:)?\s*(\d{1,2})\b", text, re.IGNORECASE)
    if explicit:
        return int(explicit.group(1))

    buy_style = re.search(r"\b(?:buy|purchase|order)\b[^\d]{0,12}(\d{1,2})\b", text, re.IGNORECASE)
    if buy_style:
        return int(buy_style.group(1))

    return 0


def _recent_human_checkout_text(messages: list) -> str:
    """Collect recent human turns to preserve checkout details across follow-ups."""
    human_texts = []
    for msg in messages[-8:]:
        if isinstance(msg, HumanMessage):
            text = _message_text(msg).strip()
            if text:
                human_texts.append(text)
    return ". ".join(human_texts)


def _recent_checkout_details_text(messages: list) -> str:
    """Collect only checkout-detail messages (name/email/phone) from recent human turns."""
    details = []
    for msg in messages[-8:]:
        if not isinstance(msg, HumanMessage):
            continue
        text = _message_text(msg).strip()
        if text and _is_checkout_detail_message(text):
            details.append(text)
    return ". ".join(details)


def _extract_email_from_text(text: str) -> str:
    match = re.search(r"\b[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}\b", text or "")
    return match.group(0).strip().lower() if match else ""


def _extract_phone_from_text(text: str) -> str:
    digits = "".join(ch for ch in (text or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def _extract_name_from_detail_text(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""

    lowered = raw.lower()
    marker_match = re.search(r"(?:my name is|name is|i am|this is)\s+([A-Za-z][A-Za-z\s\-]{1,40})", raw, re.IGNORECASE)
    if marker_match:
        return " ".join(marker_match.group(1).split()).strip()

    if "," in raw:
        first_segment = raw.split(",", 1)[0].strip()
        if first_segment and "@" not in first_segment and not any(ch.isdigit() for ch in first_segment):
            words = [w for w in first_segment.split() if w]
            if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-z][A-Za-z\-]*", word) for word in words):
                return " ".join(words)

    if "@" in raw or any(ch.isdigit() for ch in raw):
        return ""

    if any(term in lowered for term in ["buy", "order", "refund", "cancel", "policy", "product"]):
        return ""

    if re.fullmatch(r"[A-Za-z][A-Za-z\s\-]{1,40}", raw):
        words = [w for w in raw.split() if w]
        if 2 <= len(words) <= 4:
            return " ".join(words)

    return ""


def _is_order_followup_request(text: str) -> bool:
    lowered = (text or "").lower().strip()
    if not lowered:
        return False

    followup_terms = [
        "order details",
        "order detail",
        "details",
        "more info",
        "more information",
        "status",
        "what is order",
        "what is my order",
        "owner",
        "assigned to",
        "delivered to",
        "who was it delivered to",
        "who is it for",
        "order date",
        "delivery date",
        "refund status",
        "date",
    ]
    return any(term in lowered for term in followup_terms)


def _is_low_information_reply(text: str) -> bool:
    lowered = (text or "").strip().lower()
    return lowered in {
        "ok",
        "okay",
        "idk",
        "not sure",
        "hmm",
        "uh",
        "huh",
        "thanks",
        "thank you",
    }


def _is_angry_or_supervisor_request(text: str) -> bool:
    lowered = (text or "").lower().strip()
    if not lowered:
        return False

    angry_terms = [
        "angry",
        "frustrated",
        "annoyed",
        "mad",
        "unacceptable",
        "ridiculous",
        "useless",
        "terrible",
        "awful",
        "not helping",
        "helpful",
        "waste of time",
        "supervisor",
        "manager",
        "human",
        "agent",
        "escalate",
        "complaint",
        "complain",
        "talk to someone",
        "talk to a human",
        "talk to the supervisor",
        "talk to the manager",
        "speak to",
        "representative",
    ]
    return any(term in lowered for term in angry_terms)


def _extract_order_id_with_context(text: str, fallback_messages: list | None = None) -> str:
    order_id = _extract_order_id(text)
    if order_id:
        return order_id

    if text and _cancel_context_active(fallback_messages or []):
        raw = (text or "").strip().upper()
        digits = re.search(r"\b(\d{4})\b", raw)
        if digits:
            return f"ORD-{digits.group(1)}"

    if text and _is_order_followup_request(text):
        raw = (text or "").strip().upper()
        digits = re.search(r"\b(\d{4})\b", raw)
        if digits:
            return f"ORD-{digits.group(1)}"

    return ""


def _format_order_details_response(user_text: str, order: dict, customer: dict | None) -> str:
    """Build a concise but informative response for order detail follow-ups."""
    order_id = str(order.get("order_id", "N/A"))
    order_name = str(order.get("order_name", "Unknown item"))
    product_id = str(order.get("product_id", "N/A"))
    status = str(order.get("status", "unknown"))
    amount = order.get("amount", "N/A")
    order_date = order.get("order_date") or "N/A"
    delivery_date = order.get("delivery_date") or "N/A"
    refund_status = order.get("refund_status") or "none"

    base = (
        f"Order {order_id}: {order_name} ({product_id}). Status: {status}. "
        f"Amount: ${amount}. Order date: {order_date}. "
        f"Delivery date: {delivery_date}. Refund status: {refund_status}."
    )

    lowered = (user_text or "").lower()
    asks_owner = any(term in lowered for term in ["owner", "delivered to", "assigned to", "who"])
    asks_date_only = "date" in lowered and not asks_owner

    if asks_owner and isinstance(customer, dict) and not customer.get("error"):
        name = customer.get("name", "Unknown")
        email = customer.get("email", "Unknown")
        return f"{base} This order is associated with {name} ({email})."

    if asks_owner:
        return f"{base} I could not confirm the customer profile for this order."

    if asks_date_only:
        return f"Order {order_id} dates: order date {order_date}, delivery date {delivery_date}."

    return base


def _format_product_response(user_text: str, product: dict) -> str:
    """Let the LLM decide what product information to return based on user query."""
    if not isinstance(product, dict):
        return str(product)
    
    # Use LLM to determine what product information is most relevant
    llm_prompt = (
        f"The user asked: '{user_text}'\n\n"
        f"Product data: {json.dumps(product)}\n\n"
        f"Respond naturally with only the relevant product information the user asked about. "
        f"Be concise and customer-friendly. Do not return raw JSON or product data dump."
    )
    
    try:
        response = chat_model.invoke([SystemMessage(content="You are a helpful product information assistant."), HumanMessage(content=llm_prompt)])
        return _message_text(response)
    except Exception:
        # Fallback to brief summary if LLM fails
        product_id = product.get("product_id", "N/A")
        name = product.get("name", "Unknown")
        price = product.get("price", "N/A")
        return f"{name} ({product_id}): ${price}."


def _is_buy_message(text: str) -> bool:
    lowered = (text or "").lower().strip()
    if not lowered:
        return False
    has_buy_intent = any(term in lowered for term in ["buy", "purchase", "order"])
    asks_to_list = any(term in lowered for term in ["what", "which", "show", "list", "catalog", "available", "options", "anything", "can i", "do you"])
    return has_buy_intent and not asks_to_list


def _is_catalog_request(text: str) -> bool:
    lowered = (text or "").lower().strip()
    if not lowered:
        return False
    if _has_order_id(lowered):
        return False
    catalog_terms = ["buy", "purchase", "catalog", "products", "sell", "available", "shop"]
    if not any(term in lowered for term in catalog_terms):
        return False
    question_terms = ["what", "which", "show", "list", "anything", "options", "can i", "do you"]
    return any(term in lowered for term in question_terms)


def _is_replacement_request(text: str) -> bool:
    lowered = (text or "").lower()
    return "replacement" in lowered or ("damaged" in lowered and "refund" in lowered)


def _is_place_order_request(text: str) -> bool:
    lowered = (text or "").lower()
    if not lowered:
        return False
    if any(term in lowered for term in ["cancel", "refund", "money back", "status", "where is my order"]):
        return False
    has_purchase_intent = any(term in lowered for term in ["buy", "purchase", "place order", "order ", "want"])
    has_product_hint = bool(re.search(r"\bP\d{3}\b", text.upper())) or any(
        term in lowered for term in [
            "watch", "smartwatch", "headphones", "shoes", "coffee", "laptop",
            "yoga", "lamp", "speaker", "novafit", "chronoclassic", "pulsex",
        ]
    )
    return has_purchase_intent and has_product_hint


def _is_checkout_detail_message(text: str) -> bool:
    lowered = (text or "").lower()
    if "@" in lowered:
        return True
    if re.search(r"(?<!\d)\d{10}(?!\d)", lowered):
        return True
    if re.fullmatch(r"[A-Za-z][A-Za-z\s\-]{1,40}", (text or "").strip()):
        words = [w for w in (text or "").strip().split() if w]
        if 2 <= len(words) <= 4:
            return True
    return any(term in lowered for term in ["my name is", "name is", "phone", "email", "quantity", "qty"])


def _checkout_context_active(messages: list) -> bool:
    recent = messages[-6:]
    for msg in recent:
        if isinstance(msg, AIMessage):
            text = _message_text(msg).lower()
            if "checkout details" in text or "full name" in text or "email address" in text:
                return True
    return False


def _is_cancel_request(text: str) -> bool:
    lowered = (text or "").lower()
    return any(term in lowered for term in ["cancel", "cancellation"])


def _is_policy_question(text: str) -> bool:
    lowered = (text or "").lower()
    return any(term in lowered for term in ["policy", "warranty", "return window", "cancellation policy", "refund policy"])


def _is_support_related(text: str) -> bool:
    lowered = (text or "").lower()
    if _extract_product_id(text):
        return True
    support_terms = [
        "order", "refund", "cancel", "return", "policy", "warranty", "product", "products",
        "buy", "purchase", "catalog", "shopwave", "replace", "replacement", "damaged",
        "email", "phone", "customer", "ticket", "delivery", "shipped", "p0", "p1", "ord-",
    ]
    return any(term in lowered for term in support_terms)


def _is_buy_intent_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(term in lowered for term in ["buy", "purchase", "place order", "order", "want", "get"])


def _should_use_as_customer_query(text: str) -> bool:
    lowered = (text or "").lower()
    if not lowered:
        return False
    if "@" in lowered:
        return True
    if re.search(r"\bC\d{3}\b", text.upper()):
        return True
    if re.search(r"(?<!\d)\d{10}(?!\d)", lowered):
        return True
    return any(term in lowered for term in ["my name is", "name is", "email", "phone", "contact"])


def _contains_unverified_success_claim(text: str) -> bool:
    lowered = (text or "").lower()
    risky_phrases = [
        "order has been placed",
        "placed your order",
        "your order is confirmed",
        "your order has been confirmed",
    ]
    return any(phrase in lowered for phrase in risky_phrases)


def _format_policy_response(result: object) -> str:
    if isinstance(result, dict):
        if result.get("error"):
            return str(result["error"])
        matches = result.get("matches", [])
        if matches:
            top = matches[0]
            section = str(top.get("section", "policy")).title()
            highlights = top.get("highlights", [])
            if highlights:
                return f"{section}: {highlights[0]}"
        if result.get("message"):
            return str(result["message"])
    return str(result)


def _catalog_response(quick_action: str, full_catalog: str) -> str:
    if quick_action == "catalog_watches":
        watch_lines = [line for line in full_catalog.splitlines() if "watch" in line.lower()]
        if watch_lines:
            watches = "\n".join(watch_lines)
            return (
                "Here are the watches you can buy:\n"
                f"{watches}\n"
                "Tell me the product ID and quantity, and I can place the order."
            )

    return (
        "Here is what you can buy right now:\n"
        f"{full_catalog}\n"
        "Tell me the product ID and quantity, and I can place the order."
    )


def _format_place_order_message(tool_content: str) -> str:
    payload_text = tool_content.replace("PLACE_ORDER_RESULT:", "", 1).strip()
    parsed_fields = {}
    for part in payload_text.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed_fields[key.strip()] = value.strip()

    order_id = parsed_fields.get("order_id", "N/A")
    product_id = parsed_fields.get("product_id", "N/A")
    quantity = parsed_fields.get("quantity", "N/A")
    amount = parsed_fields.get("amount", "N/A")

    if not order_id.startswith("ORD-"):
        return payload_text

    return (
        f"Your order has been placed successfully. Order ID: {order_id}. "
        f"Product: {product_id}. Quantity: {quantity}. Total: ${amount}."
    )


def _execute_routed_action(
    route: dict,
    latest_user_text: str,
    latest_lower: str,
    state: AgentState,
    context_order_id: str,
    context_product_id: str,
    checkout_name: str,
):
    action = str(route.get("action", "")).strip().lower()
    route_order_id = str(route.get("order_id", "") or "").strip()
    route_product_id = str(route.get("product_id", "") or "").strip()
    route_quantity = route.get("quantity", 0)
    route_customer_query = str(route.get("customer_query", "") or "").strip()
    followup = str(route.get("followup", "") or "").strip()

    if action == "clarify":
        return {
            "messages": [
                AIMessage(content=followup or "Could you share a bit more detail so I can help?")
            ]
        }

    if action == "out_of_scope":
        return {
            "messages": [
                AIMessage(
                    content=(
                        "I can help with ShopWave support topics like orders, cancellations, refunds, "
                        "returns, and product questions."
                    )
                )
            ]
        }

    if action == "policy_question":
        try:
            policy_result = search_knowledge_base.invoke({"query": latest_user_text})
            return {"messages": [AIMessage(content=_format_policy_response(policy_result))]}
        except Exception:
            return None

    if action == "catalog_request":
        try:
            catalog = str(list_available_products.invoke({}))
            quick_action = "catalog_watches" if "watch" in latest_lower else "catalog"
            return {"messages": [AIMessage(content=_catalog_response(quick_action, catalog))]}
        except Exception:
            return None

    if action == "product_lookup":
        # If the user intent is buying, route through place_order so name/ambiguity
        # handling and checkout collection remain deterministic in tools.py.
        if _is_buy_intent_text(latest_user_text):
            action = "place_order"
        else:
            pid = route_product_id or context_product_id or _extract_product_id(latest_user_text)
            if not pid:
                return {"messages": [AIMessage(content="Please share a product ID like P011 so I can look it up.")]}
            try:
                product = get_product_info.invoke({"product_id": pid})
                return {"messages": [AIMessage(content=_format_product_response(latest_user_text, product))]}
            except Exception:
                return None

    if action in {"order_lookup", "order_owner"}:
        oid = route_order_id or context_order_id or _extract_order_id_with_context(latest_user_text, state["messages"][:-1])
        if not oid:
            return {"messages": [AIMessage(content="Please share your order ID so I can look that up.")]}
        try:
            order_result = get_order.invoke({"order_id": oid})
            if isinstance(order_result, dict) and order_result.get("error"):
                return {"messages": [AIMessage(content=str(order_result["error"]))]}

            customer_result = None
            customer_id = str(order_result.get("customer_id", "")).strip() if isinstance(order_result, dict) else ""
            if customer_id:
                lookup = get_customer_info.invoke({"query": customer_id})
                if isinstance(lookup, dict) and not lookup.get("error"):
                    customer_result = lookup

            return {"messages": [AIMessage(content=_format_order_details_response(latest_user_text, order_result, customer_result))]}
        except Exception:
            return None

    if action == "cancel_order":
        oid = route_order_id or context_order_id or _extract_order_id_with_context(latest_user_text, state["messages"][:-1])
        if not oid:
            return {"messages": [AIMessage(content="Sure, please share your order ID so I can cancel it.")]}
        try:
            cancel_result = cancel_order.invoke({"order_id": oid})
            if isinstance(cancel_result, dict):
                message = str(cancel_result.get("message", "Unable to cancel order."))
                if cancel_result.get("success"):
                    return {"messages": [AIMessage(content=message)]}
                if "already cancelled" in message.lower():
                    return {"messages": [AIMessage(content=f"The order {oid} is already cancelled.")]}
                if "cannot cancel order with status: shipped" in message.lower():
                    return {
                        "messages": [
                            AIMessage(
                                content=(
                                    f"The order {oid} has already been shipped and cannot be cancelled. "
                                    "You can request a return after delivery."
                                )
                            )
                        ]
                    }
                return {"messages": [AIMessage(content=message)]}
            return {"messages": [AIMessage(content=str(cancel_result))]}
        except Exception:
            return {"messages": [AIMessage(content="I hit a temporary issue while cancelling your order. Please try again with your order ID.")]}

    if action == "refund_order":
        oid = route_order_id or context_order_id or _extract_order_id_with_context(latest_user_text, state["messages"][:-1])
        if not oid:
            return {"messages": [AIMessage(content="To process a refund, please share your order ID in the format ORD-1234 or 1234.")]}
        try:
            order_result = get_order.invoke({"order_id": oid})
            if isinstance(order_result, dict) and order_result.get("error"):
                return {"messages": [AIMessage(content=str(order_result["error"]))]}

            eligibility = check_refund_eligibility.invoke({"order_id": oid})
            if isinstance(eligibility, dict) and eligibility.get("eligible"):
                refund_result = issue_refund.invoke({"order_id": oid})
                if isinstance(refund_result, dict):
                    return {"messages": [AIMessage(content=refund_result.get("message", f"Refund processed for {oid}."))]}
                return {"messages": [AIMessage(content=str(refund_result))]}

            reason = "Not eligible for refund."
            if isinstance(eligibility, dict):
                reason = eligibility.get("reason", reason)
            return {"messages": [AIMessage(content=f"Refund cannot be processed for {oid}: {reason}")]}
        except Exception:
            return {"messages": [AIMessage(content="I hit a temporary issue while processing the refund. Please try once more with your order ID.")]}

    if action == "replacement":
        try:
            escalated = escalate_to_human.invoke({"reason": "Customer requested replacement or reported damage."})
            return {"messages": [AIMessage(content=str(escalated))]}
        except Exception:
            return None

    if action == "escalate_human":
        try:
            reason = route.get("reason") or latest_user_text or "Customer requested human escalation."
            escalated = escalate_to_human.invoke({"reason": str(reason)})
            return {"messages": [AIMessage(content=str(escalated))]}
        except Exception:
            return None

    if action == "place_order":
        try:
            qty = int(route_quantity) if str(route_quantity).strip() else 0
        except Exception:
            qty = 0

        product_hint = route_product_id or context_product_id or _extract_product_id(latest_user_text)
        recent_details = _recent_checkout_details_text(state["messages"][:-1])
        current_name = checkout_name or _last_checkout_name_from_messages(state["messages"][:-1])

        detail_messages = []
        for msg in state["messages"][:-1][-8:]:
            if isinstance(msg, HumanMessage):
                text = _message_text(msg).strip()
                if text and _is_checkout_detail_message(text):
                    detail_messages.append(text)
        if _is_checkout_detail_message(latest_user_text):
            detail_messages.append(latest_user_text)

        if not current_name:
            for text in detail_messages:
                current_name = _extract_name_from_detail_text(text)
                if current_name:
                    break

        collected_email = ""
        collected_phone = ""
        for text in detail_messages:
            if not collected_email:
                collected_email = _extract_email_from_text(text)
            if not collected_phone:
                collected_phone = _extract_phone_from_text(text)

        checkout_fields = []
        if current_name:
            checkout_fields.append(f"My name is {current_name}")
        if collected_email:
            checkout_fields.append(f"email {collected_email}")
        if collected_phone:
            checkout_fields.append(f"phone {collected_phone}")
        checkout_context = ". ".join(checkout_fields)

        # If product ID is unavailable, keep the original natural-language request
        # so place_order can resolve by product name or return ambiguity options.
        if product_hint:
            composed_request = f"Buy {qty or 1} units of {product_hint}. {checkout_context}"
        else:
            composed_request = latest_user_text if latest_user_text.strip() else ""
            if checkout_context:
                composed_request = f"{composed_request}. {checkout_context}".strip(". ")

        try:
            placed = place_order.invoke({
                "request": composed_request,
                "customer_query": checkout_context if checkout_context else (route_customer_query or "guest"),
                "quantity": qty,
            })
            if isinstance(placed, dict):
                content = (
                    "PLACE_ORDER_RESULT: "
                    f"order_id={placed.get('order_id', 'N/A')}; "
                    f"product_id={placed.get('product_id', 'N/A')}; "
                    f"quantity={placed.get('quantity', 'N/A')}; "
                    f"amount={placed.get('amount', 'N/A')}"
                )
                return {"messages": [AIMessage(content=_format_place_order_message(content))]}
            return {"messages": [AIMessage(content=str(placed))]}
        except Exception:
            return None

    return None

# Nodes
def call_model(state: AgentState):
    if state["messages"] and isinstance(state["messages"][-1], HumanMessage):
        latest_user_text = _message_text(state["messages"][-1])
        latest_lower = latest_user_text.lower()
        order_id = _extract_order_id_with_context(latest_user_text, state["messages"][:-1])
        context_order_id = order_id or _last_order_id_from_messages(state["messages"][:-1])
        product_id = _extract_product_id(latest_user_text)
        context_product_id = product_id or _last_product_id_from_messages(state["messages"][:-1])
        checkout_name = _last_checkout_name_from_messages(state["messages"][:-1])

        if checkout_name and any(term in latest_lower for term in ["under what name", "what name", "whose name", "customer name"]):
            return {
                "messages": [
                    AIMessage(content=f"You placed that order under the name {checkout_name}.")
                ]
            }

        if _is_angry_or_supervisor_request(latest_user_text):
            try:
                escalated = escalate_to_human.invoke({"reason": latest_user_text})
                return {"messages": [AIMessage(content=str(escalated))]}
            except Exception:
                return {
                    "messages": [
                        AIMessage(content="I’m escalating this to a human agent now.")
                    ]
                }

        if _is_policy_question(latest_user_text):
            try:
                policy_result = search_knowledge_base.invoke({"query": latest_user_text})
                return {"messages": [AIMessage(content=_format_policy_response(policy_result))]}
            except Exception:
                pass

        has_explicit_order_number = bool(re.search(r"\b(?:ORD\s*[-:]?\s*)?\d{4}\b", latest_user_text, re.IGNORECASE))

        if _cancel_context_active(state["messages"][:-1]):
            cancel_digits = re.search(r"\b(\d{4})\b", latest_user_text)
            if cancel_digits:
                oid = f"ORD-{cancel_digits.group(1)}"
                try:
                    cancel_result = cancel_order.invoke({"order_id": oid})
                    if isinstance(cancel_result, dict):
                        message = str(cancel_result.get("message", "Unable to cancel order."))
                        if cancel_result.get("success"):
                            return {"messages": [AIMessage(content=message)]}
                        if "already cancelled" in message.lower():
                            return {"messages": [AIMessage(content=f"The order {oid} is already cancelled.")]}
                        if "cannot cancel order with status: shipped" in message.lower():
                            return {
                                "messages": [
                                    AIMessage(
                                        content=(
                                            f"The order {oid} has already been shipped and cannot be cancelled. "
                                            "You can request a return after delivery."
                                        )
                                    )
                                ]
                            }
                        return {"messages": [AIMessage(content=message)]}
                    return {"messages": [AIMessage(content=str(cancel_result))]}
                except Exception:
                    return {"messages": [AIMessage(content="I hit a temporary issue while cancelling your order. Please try again with your order ID.")]}

        if _is_cancel_request(latest_user_text) and not has_explicit_order_number:
            return {"messages": [AIMessage(content="Sure, please share your order ID so I can cancel it.")]}

        route = _route_user_message(latest_user_text, state["messages"][:-1])
        routed_result = _execute_routed_action(
            route,
            latest_user_text,
            latest_lower,
            state,
            context_order_id,
            context_product_id,
            checkout_name,
        )
        if routed_result is not None:
            return routed_result

        if _is_cancel_request(latest_user_text) and not order_id:
            return {"messages": [AIMessage(content="Sure, please share your order ID so I can cancel it.")]}

        if any(term in latest_lower for term in ["refund", "money back"]) and not order_id:
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "To process a refund, please share your order ID in the format ORD-1234 or 1234."
                        )
                    )
                ]
            }

        if context_product_id and any(term in latest_lower for term in ["under what name", "what name", "whose name", "name", "customer name"]):
            if checkout_name:
                return {
                    "messages": [
                        AIMessage(
                            content=f"You placed that order under the name {checkout_name}."
                        )
                    ]
                }
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "I need the checkout details from the original order flow to confirm the name. "
                            "If you just placed an order, please share the full name again."
                        )
                    )
                ]
            }

        is_transaction_intent = any(term in latest_lower for term in ["refund", "money back", "cancel", "buy", "purchase", "policy"])
        if context_order_id and _is_order_followup_request(latest_user_text) and not is_transaction_intent:
            try:
                order_result = get_order.invoke({"order_id": context_order_id})
                if isinstance(order_result, dict) and order_result.get("error"):
                    return {"messages": [AIMessage(content=str(order_result["error"]))]}

                customer_result = None
                customer_id = ""
                if isinstance(order_result, dict):
                    customer_id = str(order_result.get("customer_id", "")).strip()

                if customer_id:
                    lookup = get_customer_info.invoke({"query": customer_id})
                    if isinstance(lookup, dict) and not lookup.get("error"):
                        customer_result = lookup

                response_text = _format_order_details_response(latest_user_text, order_result, customer_result)
                return {"messages": [AIMessage(content=response_text)]}
            except Exception:
                pass

        if context_order_id and _is_low_information_reply(latest_user_text):
            return {
                "messages": [
                    AIMessage(
                        content=(
                            f"No problem. I still have order {context_order_id} in context. "
                            "You can ask for owner, status, order/delivery dates, cancellation check, or refund eligibility."
                        )
                    )
                ]
            }

        if _cancel_context_active(state["messages"][:-1]):
            cancel_digits = re.search(r"\b(\d{4})\b", latest_user_text)
            if cancel_digits:
                order_id = f"ORD-{cancel_digits.group(1)}"
            else:
                order_id = ""
        if order_id and _cancel_context_active(state["messages"][:-1]):
            try:
                cancel_result = cancel_order.invoke({"order_id": order_id})
                if isinstance(cancel_result, dict):
                    message = str(cancel_result.get("message", "Unable to cancel order."))
                    if cancel_result.get("success"):
                        return {"messages": [AIMessage(content=message)]}
                    if "already cancelled" in message.lower():
                        return {"messages": [AIMessage(content=f"The order {order_id} is already cancelled.")]}
                    if "cannot cancel order with status: shipped" in message.lower():
                        return {
                            "messages": [
                                AIMessage(
                                    content=(
                                        f"The order {order_id} has already been shipped and cannot be cancelled. "
                                        "You can request a return after delivery."
                                    )
                                )
                            ]
                        }
                    return {"messages": [AIMessage(content=message)]}
                return {"messages": [AIMessage(content=str(cancel_result))]}
            except Exception:
                return {"messages": [AIMessage(content="I hit a temporary issue while cancelling your order. Please try again with your order ID.")]}

        if _purchase_context_active(state["messages"][:-1]) and (
            bool(context_product_id)
            and (
                _is_checkout_detail_message(latest_user_text)
                or _is_buy_intent_text(latest_user_text)
                or _extract_quantity(latest_user_text) > 0
                or product_id == context_product_id
            )
        ):
            try:
                quantity = _extract_quantity(latest_user_text)
                if quantity <= 0:
                    recent_human = _recent_human_checkout_text(state["messages"][:-1])
                    quantity = _extract_quantity(recent_human)
                if quantity <= 0:
                    quantity = 1

                detail_messages = []
                for msg in state["messages"][:-1][-8:]:
                    if isinstance(msg, HumanMessage):
                        text = _message_text(msg).strip()
                        if text and _is_checkout_detail_message(text):
                            detail_messages.append(text)
                if _is_checkout_detail_message(latest_user_text):
                    detail_messages.append(latest_user_text)

                collected_name = ""
                collected_email = ""
                collected_phone = ""
                for text in detail_messages:
                    if not collected_name:
                        collected_name = _extract_name_from_detail_text(text)
                    if not collected_email:
                        collected_email = _extract_email_from_text(text)
                    if not collected_phone:
                        collected_phone = _extract_phone_from_text(text)

                checkout_fields = []
                if collected_name:
                    checkout_fields.append(f"My name is {collected_name}")
                if collected_email:
                    checkout_fields.append(f"email {collected_email}")
                if collected_phone:
                    checkout_fields.append(f"phone {collected_phone}")
                checkout_context = ". ".join(checkout_fields)

                composed_request = (
                    f"Buy {quantity} units of {context_product_id}. "
                    f"{checkout_context}"
                )
                placed = place_order.invoke({
                    "request": composed_request,
                    "customer_query": checkout_context if checkout_context else "guest",
                })
                if isinstance(placed, dict):
                    content = (
                        "PLACE_ORDER_RESULT: "
                        f"order_id={placed.get('order_id', 'N/A')}; "
                        f"product_id={placed.get('product_id', 'N/A')}; "
                        f"quantity={placed.get('quantity', 'N/A')}; "
                        f"amount={placed.get('amount', 'N/A')}"
                    )
                    return {"messages": [AIMessage(content=_format_place_order_message(content))]}
                return {"messages": [AIMessage(content=str(placed))]}
            except Exception:
                pass

        if product_id and not _is_buy_intent_text(latest_user_text):
            try:
                product = get_product_info.invoke({"product_id": product_id})
                return {"messages": [AIMessage(content=str(product))]}
            except Exception:
                pass

        if product_id and _is_buy_intent_text(latest_user_text):
            try:
                placed = place_order.invoke({
                    "request": latest_user_text,
                    "customer_query": "guest",
                })
                if isinstance(placed, dict):
                    content = (
                        "PLACE_ORDER_RESULT: "
                        f"order_id={placed.get('order_id', 'N/A')}; "
                        f"product_id={placed.get('product_id', 'N/A')}; "
                        f"quantity={placed.get('quantity', 'N/A')}; "
                        f"amount={placed.get('amount', 'N/A')}"
                    )
                    return {"messages": [AIMessage(content=_format_place_order_message(content))]}
                return {"messages": [AIMessage(content=str(placed))]}
            except Exception:
                pass

        if not _is_support_related(latest_user_text) and not (
            _checkout_context_active(state["messages"]) and _is_checkout_detail_message(latest_user_text)
        ):
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "I can help with ShopWave support topics like orders, cancellations, refunds, "
                            "returns, and product questions."
                        )
                    )
                ]
            }

        quick_action = "none"
        if _is_catalog_request(latest_user_text) and not _is_buy_message(latest_user_text):
            quick_action = "catalog_watches" if "watch" in latest_lower else "catalog"

        if quick_action in {"catalog", "catalog_watches"}:
            try:
                catalog = str(list_available_products.invoke({}))
                return {
                    "messages": [
                        AIMessage(content=_catalog_response(quick_action, catalog))
                    ]
                }
            except Exception:
                pass

        if _is_replacement_request(latest_user_text):
            try:
                escalated = escalate_to_human.invoke({"reason": "Customer requested replacement or reported damage."})
                return {"messages": [AIMessage(content=str(escalated))]}
            except Exception:
                pass

        if _is_place_order_request(latest_user_text) and not _has_order_id(latest_user_text):
            try:
                placed = place_order.invoke({
                    "request": latest_user_text,
                    "customer_query": "guest",
                })
                if isinstance(placed, dict):
                    content = (
                        "PLACE_ORDER_RESULT: "
                        f"order_id={placed.get('order_id', 'N/A')}; "
                        f"product_id={placed.get('product_id', 'N/A')}; "
                        f"quantity={placed.get('quantity', 'N/A')}; "
                        f"amount={placed.get('amount', 'N/A')}"
                    )
                    return {"messages": [AIMessage(content=_format_place_order_message(content))]}
                return {"messages": [AIMessage(content=str(placed))]}
            except Exception:
                pass

    if state["messages"] and isinstance(state["messages"][-1], HumanMessage):
        latest_user_text = _message_text(state["messages"][-1])
        latest_lower = latest_user_text.lower()
        order_id = _extract_order_id(latest_user_text)
        if order_id and any(term in latest_lower for term in ["refund", "money back"]):
            try:
                order_result = get_order.invoke({"order_id": order_id})
                if isinstance(order_result, dict) and order_result.get("error"):
                    return {"messages": [AIMessage(content=str(order_result["error"]))]}

                eligibility = check_refund_eligibility.invoke({"order_id": order_id})
                if isinstance(eligibility, dict) and eligibility.get("eligible"):
                    refund_result = issue_refund.invoke({"order_id": order_id})
                    if isinstance(refund_result, dict):
                        return {"messages": [AIMessage(content=refund_result.get("message", f"Refund processed for {order_id}."))]}
                    return {"messages": [AIMessage(content=str(refund_result))]}

                reason = "Not eligible for refund."
                if isinstance(eligibility, dict):
                    reason = eligibility.get("reason", reason)
                return {"messages": [AIMessage(content=f"Refund cannot be processed for {order_id}: {reason}")]}
            except Exception:
                return {"messages": [AIMessage(content="I hit a temporary issue while processing the refund. Please try once more with your order ID.")]}

        if order_id and any(term in latest_lower for term in ["cancel", "cancellation"]):
            try:
                cancel_result = cancel_order.invoke({"order_id": order_id})
                if isinstance(cancel_result, dict):
                    message = str(cancel_result.get("message", "Unable to cancel order."))
                    if cancel_result.get("success"):
                        return {"messages": [AIMessage(content=message)]}
                    if "already cancelled" in message.lower():
                        return {"messages": [AIMessage(content=f"The order {order_id} is already cancelled.")]}
                    if "cannot cancel order with status: shipped" in message.lower():
                        return {
                            "messages": [
                                AIMessage(
                                    content=(
                                        f"The order {order_id} has already been shipped and cannot be cancelled. "
                                        "You can request a return after delivery."
                                    )
                                )
                            ]
                        }
                    return {"messages": [AIMessage(content=message)]}
                return {"messages": [AIMessage(content=str(cancel_result))]}
            except Exception:
                return {"messages": [AIMessage(content="I hit a temporary issue while cancelling your order. Please try again with your order ID.")]}

    last_message = state["messages"][-1]
    if isinstance(last_message, ToolMessage) and str(last_message.content).startswith("PLACE_ORDER_RESULT:"):
        response_text = _format_place_order_message(str(last_message.content))
        return {"messages": [AIMessage(content=response_text)]}

    try:
        response = chat_model_with_tools.invoke(state["messages"])
    except Exception:
        response = AIMessage(
            content=(
                "I hit a temporary issue while checking that. Please repeat your request in one line, "
                "and I will retry right away."
            )
        )

    if isinstance(response, AIMessage) and not getattr(response, "tool_calls", None):
        if _contains_unverified_success_claim(_message_text(response)):
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "I can place that order after I verify details with tools. "
                            "Please share product ID, quantity, full name, email, and phone number."
                        )
                    )
                ]
            }

    return {"messages": [response]}


def tool_node(state: AgentState):
    last_message = state["messages"][-1]
    tools_by_name = {t.name: t for t in tools_registry}
    tool_calls = getattr(last_message, "tool_calls", [])
    latest_user_message = ""
    for msg in reversed(state["messages"][:-1]):
        if isinstance(msg, HumanMessage):
            latest_user_message = _message_text(msg)
            break

    def execute_tool(tool_call):
        tool_name = tool_call.get("name")
        tool_id = tool_call.get("id", "tool-call")
        args = dict(tool_call.get("args", {}))

        if tool_name == "place_order" and latest_user_message:
            base_request = str(args.get("request", "")).strip()
            if not base_request:
                args["request"] = latest_user_message
            elif latest_user_message.lower() not in base_request.lower():
                args["request"] = f"{base_request}. {latest_user_message}"

            customer_query = str(args.get("customer_query", "")).strip().lower()
            if (not customer_query or customer_query == "guest") and _should_use_as_customer_query(latest_user_message):
                args["customer_query"] = latest_user_message

        if tool_name not in tools_by_name:
            return ToolMessage(
                content=f"Tool '{tool_name}' is not available.",
                tool_call_id=tool_id,
            )

        try:
            output = tools_by_name[tool_name].invoke(args)
            if tool_name == "place_order":
                if isinstance(output, dict):
                    order_id = output.get("order_id", "N/A")
                    product_id = output.get("product_id", "N/A")
                    quantity = output.get("quantity", "N/A")
                    amount = output.get("amount", "N/A")
                    content = (
                        "PLACE_ORDER_RESULT: "
                        f"order_id={order_id}; product_id={product_id}; quantity={quantity}; amount={amount}"
                    )
                else:
                    content = f"PLACE_ORDER_RESULT: {output}"
                return ToolMessage(content=content, tool_call_id=tool_id)
            else:
                return ToolMessage(content=str(output), tool_call_id=tool_id)
        except Exception as exc:
            return ToolMessage(
                content=f"Tool '{tool_name}' failed: {exc}",
                tool_call_id=tool_id,
            )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(execute_tool, tool_calls))

    return {"messages": results}


def router(state: AgentState):
    if getattr(state["messages"][-1], "tool_calls", None):
        return "tools"

    return END

workflow = StateGraph(AgentState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", tool_node)

workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", router)
workflow.add_edge("tools", "agent")

app = workflow.compile()


def run_agent(user_text: str, prior_messages: list | None = None) -> str:
    """Small helper so other files can call the graph easily."""
    state = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            *(prior_messages or []),
            HumanMessage(content=user_text),
        ]
    }
    result = app.invoke(state)
    return result["messages"][-1].content