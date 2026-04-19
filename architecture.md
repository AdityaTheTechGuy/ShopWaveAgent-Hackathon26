# ShopWave Architecture

```mermaid
%%{init: {'theme': 'base'}}%%
flowchart TD
    User["User"] --> CLI["CLI (main.py)"]
    CLI --> InputGuard{"Input <= 600 chars?"}
    InputGuard -- "No" --> PromptShort["Ask user to shorten message"]
    InputGuard -- "Yes" --> Graph["LangGraph App (agent.py)"]

    Graph --> IntentCheck{"Missing details?"}
    IntentCheck -- "Place order missing name/email/phone" --> AskCheckout["Ask for required checkout fields"]
    IntentCheck -- "Cancel/refund missing order ID" --> AskOrderId["Ask for valid order ID"]
    IntentCheck -- "No" --> ToolNode["Tool execution node"]

    ToolNode --> OrderTools["get_order / cancel_order / refund tools"]
    OrderTools --> OrderIdGuard{"Order ID valid?"}
    OrderIdGuard -- "No" --> IdError["Return invalid order ID message"]
    OrderIdGuard -- "Yes" --> OrderOps["Fetch/update order"]

    ToolNode --> PlaceOrder["place_order"]
    PlaceOrder --> QtyGuard{"Quantity 1..10?"}
    QtyGuard -- "No" --> QtyError["Return quantity limit message"]
    QtyGuard -- "Yes" --> ContactGuard{"Valid email + 10-digit phone?"}
    ContactGuard -- "No" --> ContactError["Return contact validation message"]
    ContactGuard -- "Yes" --> CustomerFlow["Find customer by email or create new customer"]
    CustomerFlow --> Persist["Persist customers.json and orders.json"]

    ToolNode --> OtherTools["product lookup / policy search / escalation"]

    AskCheckout --> Response["Final response"]
    AskOrderId --> Response
    IdError --> Response
    QtyError --> Response
    ContactError --> Response
    OrderOps --> Response
    Persist --> Response
    OtherTools --> Response

    Response --> Audit["Append audit log"]
    Audit --> CLI
```

## Notes

- Business rules are enforced in tools, not only by prompt instructions.
- Checkout requires full name, valid email, and exactly 10-digit phone.
- New customers are created when email is not found; existing customers are updated.
