"""Lambda handler deployed behind the AgentCore Gateway (tests piece #1: Agent Gateway).

The Gateway invokes this Lambda for every tool call it fans out. It tells us
which tool was requested via context.client_context.custom['bedrockAgentCoreToolName'],
formatted as "<target_name>___<tool_name>". `event` carries the tool's arguments.
"""

_ORDERS = {
    "A100": {"status": "shipped", "eta": "2026-10-23"},
    "A200": {"status": "processing", "eta": "2026-10-25"},
}


def _get_order_status(args: dict) -> dict:
    order_id = args.get("order_id", "")
    return _ORDERS.get(order_id, {"status": "unknown", "eta": None})


def _calculate(args: dict) -> dict:
    expression = args.get("expression", "")
    allowed = set("0123456789+-*/(). ")
    if not set(expression) <= allowed:
        raise ValueError("expression contains disallowed characters")
    return {"result": eval(expression, {"__builtins__": {}})}


_HANDLERS = {
    "get_order_status": _get_order_status,
    "calculate": _calculate,
}


def lambda_handler(event, context):
    tool_name = context.client_context.custom.get("bedrockAgentCoreToolName", "")
    tool_name = tool_name.split("___")[-1] if "___" in tool_name else tool_name

    handler = _HANDLERS.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown tool requested via gateway: {tool_name!r}")

    return handler(event)
