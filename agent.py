import os
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
 
llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0)
tool_list = [
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
model_with_tools = llm.bind_tools(tool_list)

SYSTEM_PROMPT = (
    "You are a customer support agent for ShopWave. Help customers with orders, refunds, "
    "cancellations, exchanges, and product questions.\n\n"
    "Execution rules:\n"
    "- Always use tools to verify facts. Do not guess policy or order data.\n"
    "- Use get_customer_info for customer lookup (email, name, or customer ID).\n"
    "- For order status or ownership questions, use get_order first.\n"
    "- For refund requests, follow this exact sequence: get_order -> check_refund_eligibility -> issue_refund only if eligible is true.\n"
    "- For cancellations, call get_order first, then cancel_order only when status is processing.\n"
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


def _to_text(chat_message) -> str:
    content = getattr(chat_message, "content", "")
    return content if isinstance(content, str) else str(content)


def _has_order_id(text: str) -> bool:
    cleaned = text.replace(":", " ").replace("#", " ").upper()
    words = cleaned.split()
    for i, word in enumerate(words):
        if word.startswith("ORD-") and word[4:].isdigit():
            return True
        if word.isdigit() and i > 0 and words[i - 1] in {"ORDER", "ID", "NUMBER"}:
            return True
    return False


def _has_email(text: str) -> bool:
    return bool(re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text))


def _has_name(text: str) -> bool:
    lowered = text.lower()
    markers = ["my name is", "name is", "name:", "i am", "this is"]
    for marker in markers:
        idx = lowered.find(marker)
        if idx == -1:
            continue
        tail = text[idx + len(marker):].strip(" .,:;-")
        words = [w for w in tail.split() if w]
        if len(words) >= 2:
            return True
    return False


def _has_phone(text: str) -> bool:
    lowered = text.lower()
    markers = ["phone", "mobile", "contact", "number"]
    for marker in markers:
        idx = lowered.find(marker)
        if idx == -1:
            continue
        snippet = text[idx: idx + 50]
        digits = "".join(ch for ch in snippet if ch.isdigit())
        if len(digits) == 10:
            return True
    return False


def _has_quantity(text: str) -> bool:
    lowered = text.lower().replace(":", " ")
    words = lowered.split()

    for i, word in enumerate(words):
        if word.endswith("x") and word[:-1].isdigit():
            return True
        if word in {"unit", "units", "qty", "quantity"} and i > 0 and words[i - 1].isdigit():
            return True
        if word in {"qty", "quantity"} and i + 1 < len(words) and words[i + 1].isdigit():
            return True
        if word in {"buy", "purchase", "order", "get"} and i + 1 < len(words) and words[i + 1].isdigit():
            return True
    return False


def _has_product(text: str) -> bool:
    words = text.upper().replace(",", " ").split()
    for word in words:
        cleaned = word.strip(".,:;!?()[]{}")
        if len(cleaned) == 4 and cleaned.startswith("P") and cleaned[1:].isdigit():
            return True

    lowered = text.lower()
    product_terms = [
        "headphones",
        "running shoes",
        "coffee maker",
        "laptop stand",
        "yoga mat",
        "smartwatch",
        "smart watch",
        "desk lamp",
        "bluetooth speaker",
        "analog watch",
        "chronoclassic",
        "novafit",
        "pulsex",
        "prosound",
        "swiftrun",
        "brewmaster",
        "ergolift",
        "zenflow",
        "lumidesk",
        "skyband",
        "aster",
    ]
    return any(term in lowered for term in product_terms)


def _pick_request_type(latest_user_text: str, chat_history_text: str) -> str:
    text = f"{latest_user_text}\n{chat_history_text}".lower()
    if any(word in text for word in ["refund", "money back", "return"]):
        return "refund"
    if any(word in text for word in ["cancel", "cancellation"]):
        return "cancel"
    if any(word in text for word in ["place order", "buy", "purchase", "checkout"]):
        return "place"
    return ""


def _follow_up_for_missing_details(messages: list) -> str:
    if not messages or not isinstance(messages[-1], HumanMessage):
        return ""

    latest_user_text = _to_text(messages[-1])
    all_user_text = "\n".join(_to_text(m) for m in messages if isinstance(m, HumanMessage))
    request_type = _pick_request_type(latest_user_text, all_user_text)

    if request_type in {"cancel", "refund"} and not _has_order_id(all_user_text):
        action_label = "cancellation" if request_type == "cancel" else "a refund"
        return (
            f"I can help with {action_label}. Before I proceed, please share your order ID "
            "(for example, ORD-1012)."
        )

    if request_type == "place":
        missing_fields = []
        if not _has_product(all_user_text):
            missing_fields.append("product name or product ID")
        if not _has_quantity(all_user_text):
            missing_fields.append("quantity")
        if not _has_name(all_user_text):
            missing_fields.append("full name")
        if not _has_email(all_user_text):
            missing_fields.append("email address")
        if not _has_phone(all_user_text):
            missing_fields.append("phone number")

        if not missing_fields:
            return ""

        prompt_lines = ["I can place that order. Please share:"]
        for idx, field_name in enumerate(missing_fields, start=1):
            prompt_lines.append(f"{idx}. {field_name}")
        prompt_lines.append("Example: Buy 2 units of P011. My name is Alice Turner, email alice.turner@email.com, phone 4155550101")
        return "\n".join(prompt_lines)

    return ""

# Nodes
def call_model(state: AgentState):
    follow_up_question = _follow_up_for_missing_details(state["messages"])
    if follow_up_question:
        return {"messages": [AIMessage(content=follow_up_question)]}

    last_message = state["messages"][-1]
    if isinstance(last_message, ToolMessage) and str(last_message.content).startswith("PLACE_ORDER_RESULT:"):
        payload_text = str(last_message.content).replace("PLACE_ORDER_RESULT:", "", 1).strip()
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
            return {"messages": [AIMessage(content=payload_text)]}

        response = AIMessage(
            content=(
                f"Your order has been placed successfully. Order ID: {order_id}. "
                f"Product: {product_id}. Quantity: {quantity}. Total: ${amount}."
            )
        )
        return {"messages": [response]}

    try:
        response = model_with_tools.invoke(state["messages"])
    except Exception:
        response = AIMessage(
            content=(
                "I hit a temporary issue while checking that. Please share the order ID or customer email again, "
                "and I will retry right away."
            )
        )
    return {"messages": [response]}


def tool_node(state: AgentState):
    last_message = state["messages"][-1]
    tool_map = {t.name: t for t in tool_list}
    tool_calls = getattr(last_message, "tool_calls", [])

    def execute_tool(tool_call):
        name = tool_call.get("name")
        tool_id = tool_call.get("id", "tool-call")
        args = tool_call.get("args", {})

        if name not in tool_map:
            return ToolMessage(
                content=f"Tool '{name}' is not available.",
                tool_call_id=tool_id,
            )

        try:
            output = tool_map[name].invoke(args)
            if name == "place_order":
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
                content=f"Tool '{name}' failed: {exc}",
                tool_call_id=tool_id,
            )

    # Execute multiple tools in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(execute_tool, tool_calls))

    return {"messages": results}


def router(state: AgentState):
    if getattr(state["messages"][-1], "tool_calls", None):
        return "tools"

    return END

# Graph Assembly

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