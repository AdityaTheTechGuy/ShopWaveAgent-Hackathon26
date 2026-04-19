import json
import os
import uuid
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import Future
from langchain_core.messages import HumanMessage, SystemMessage
from rich.console import Console
from rich.panel import Panel

from agent import app, SYSTEM_PROMPT

console = Console()
AUDIT_EXECUTOR = ThreadPoolExecutor(max_workers=1)
MAX_USER_INPUT_CHARS = 600


def save_audit_log_async(audit_log_path: str, history: list) -> Future:
    """Schedule an audit log write without blocking the CLI."""
    history_snapshot = list(history)

    def write_file(items: list) -> None:
        with open(audit_log_path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

    return AUDIT_EXECUTOR.submit(write_file, history_snapshot)


def show_help_panel() -> None:
    """Display starter instructions for customers at the beginning of each session."""
    help_text = (
        "[bold]What you can ask me:[/bold]\n"
        "1. Order status and ownership\n"
        "   Example: [italic]my order id is 1012[/italic] or [italic]who is ORD-1002 assigned to?[/italic]\n"
        "2. Cancellations\n"
        "   Example: [italic]cancel my order ORD-1012[/italic]\n"
        "3. Returns and refunds\n"
        "   Example: [italic]can I get a refund for ORD-1002?[/italic]\n"
        "4. Product help\n"
        "   Example: [italic]tell me about NovaFit Smartwatch X2[/italic]\n"
        "5. Place a new order\n"
        "   Example: [italic]Buy 2 units of P011. My name is Alice Turner, email alice.turner@email.com, phone 4155550101[/italic]\n\n"
        "[bold]Tips:[/bold] Mention order ID if you have it, and include name/email/phone for checkout.\n"
        "Type [italic]exit[/italic], [italic]quit[/italic], [italic]bye[/italic], or [italic]goodbye[/italic] to end chat."
    )
    console.print(Panel(help_text, title="[bold yellow]How To Use ShopWave Support[/bold yellow]", border_style="yellow"))


def run_cli():
    session_id = str(uuid.uuid4())[:8]
    audit_log_path = f"logs/audit_log{session_id}.jsonl"
    history = []
    messages = [SystemMessage(content=SYSTEM_PROMPT)]

    console.print(Panel.fit(
        "[bold cyan]ShopWave AI Support Agent[/bold cyan]\n"
        "[dim]Powered by llama-3.1-8b-instant and LangGraph[/dim]",
        border_style="blue"
    ))
    show_help_panel()
    
    while True:
        try:
            user_input = console.input("[bold green]You:[/bold green] ")
            
            if user_input.lower() in {"exit", "quit", "bye", "goodbye"}:
                console.print("[bold red]Exiting. Goodbye![/bold red]")
                break

            if len(user_input) > MAX_USER_INPUT_CHARS:
                console.print(
                    f"[bold yellow]Please keep messages under {MAX_USER_INPUT_CHARS} characters.[/bold yellow]"
                )
                continue

            messages.append(HumanMessage(content=user_input))
            result = app.invoke({"messages": messages})
            messages = result["messages"]
            answer = messages[-1].content
            history.append({
                "timestamp": datetime.now().isoformat(),
                "type": "user_and_ai",
                "content": user_input,
                "response": answer,
            })
            save_audit_log_async(audit_log_path, history)
            console.print(Panel(
                answer,
                title="[bold green]ShopWave Agent[/bold green]",
                border_style="green"
            ))

        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")

    final_write = save_audit_log_async(audit_log_path, history)
    final_write.result(timeout=5)
    console.print(f"\n[bold yellow]Session ended. Audit log: {audit_log_path}[/bold yellow]")
    AUDIT_EXECUTOR.shutdown(wait=True)

if __name__ == "__main__":
    if not os.path.exists("logs"):
        os.makedirs("logs")
        
    run_cli()