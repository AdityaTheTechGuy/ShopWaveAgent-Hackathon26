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
    "- For policy questions, call search_knowledge_base and cite the matching policy section briefly.\n"
    "- For product lookup, use get_product_info by ID. For buying options, use list_available_products. For buying intent, use place_order.\n"
    "- Escalate with escalate_to_human for replacement requests, suspicious behavior, or conflicting records.\n\n"
    "Response style:\n"
    "- Keep replies concise, clear, and empathetic.\n"
    "- If a request is denied, explain why and provide the next best option.\n"
    "- Never claim an action succeeded unless a tool result confirms it."
)

# Nodes
def call_model(state: AgentState):
    last_message = state["messages"][-1]
    if isinstance(last_message, ToolMessage) and str(last_message.content).startswith("PLACE_ORDER_RESULT:"):
        payload_text = str(last_message.content).replace("PLACE_ORDER_RESULT:", "", 1).strip()
        order_id_match = re.search(r"order_id=([^;]+)", payload_text)
        product_match = re.search(r"product_id=([^;]+)", payload_text)
        quantity_match = re.search(r"quantity=([^;]+)", payload_text)
        amount_match = re.search(r"amount=([^;]+)", payload_text)

        order_id = order_id_match.group(1).strip() if order_id_match else "N/A"
        product_id = product_match.group(1).strip() if product_match else "N/A"
        quantity = quantity_match.group(1).strip() if quantity_match else "N/A"
        amount = amount_match.group(1).strip() if amount_match else "N/A"

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