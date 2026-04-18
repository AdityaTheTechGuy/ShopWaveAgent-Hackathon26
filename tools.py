import json
from pathlib import Path
from datetime import datetime
import random
from langchain_core.tools import tool

ROOT_DIR = Path(__file__).resolve().parent

def load_data(filename):
    """Load one of the small JSON fixtures from the data folder."""
    with open(ROOT_DIR / "data" / filename, "r", encoding="utf-8") as f:
        return json.load(f)

customers = load_data("customers.json")
products = load_data("products.json")
orders = load_data("orders.json")

@tool("get_customer_info")
def get_customer_info(email:str):
    """Look up a customer by email address."""
    return next((customer for customer in customers if customer["email"] == email), "Customer not found.")

@tool("get_order")
def get_order(order_id:str):
    """Look up an order by order ID."""
    return next((order for order in orders if order["order_id"] == order_id), "Order not found.")

@tool("get_product_info")
def get_product_info(product_id:str):
    """Look up a product by product ID."""
    return next((product for product in products if product["product_id"] == product_id), "Product not found.")

@tool("search_knowledge_base")
def search_knowledge_base(query:str):
    """Do a lightweight text search over the support knowledge base."""
    knowledge_base_path = ROOT_DIR / "data" / "knowledge-base.md"
    with open(knowledge_base_path, "r", encoding="utf-8") as f:
        knowledge_base = f.read()

    if not query:
        return knowledge_base

    # Keep this simple on purpose so the agent can surface obvious policy matches.
    matches = [line for line in knowledge_base.splitlines() if query.lower() in line.lower()]
    return "\n".join(matches) if matches else "No matching knowledge base entries found."

@tool("check_refund_eligibility")
def check_refund_eligibility(order_id:str):
    """Check whether an order is still inside its return window."""
    order = next((o for o in orders if o['order_id'] == order_id), None)
    if not order:
        return "Order not found."
    
    # Small failure simulation to make the agent feel more realistic in demos.
    if random.random() < 0.2:
        return "Refund request failed due to a system error. Please try again later."
    
    return_deadline = datetime.strptime(order["return_deadline"], "%Y-%m-%d")
    current_date = datetime.now()
    
    if current_date > return_deadline:
        return "Refund request denied. The order is older than 30 days."
    return "Eligible for refund. Please proceed with the refund request."

@tool("process_refund")
def issue_refund(order_id:str):
    """Mark an order as refunded in memory and return a confirmation message."""
    order = next((o for o in orders if o["order_id"] == order_id), None)
    if not order:
        return "Order not found."

    order["refund_status"] = "refunded"
    return f"Refund for order {order_id} has been processed successfully."


@tool("send_reply")
def send_reply(content:str):
    """Return a short confirmation for a customer reply."""
    return f"Reply sent to customer: {content}"

@tool("escalate_to_human")
def escalate_to_human(reason:str):
    """Escalate the ticket with a plain explanation of why."""
    return f"Ticket escalated to human agent. Reason: {reason}"