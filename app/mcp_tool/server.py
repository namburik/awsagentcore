"""Standalone MCP tool server (tests piece #3: a plain MCP tool).

Run directly: python app/mcp_tool/server.py
Exposes two tools over streamable-HTTP at http://127.0.0.1:8000/mcp
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo-tools", host="127.0.0.1", port=8000)

_ORDERS = {
    "A100": {"status": "shipped", "eta": "2026-10-23"},
    "A200": {"status": "processing", "eta": "2026-10-25"},
}


@mcp.tool()
def get_order_status(order_id: str) -> dict:
    """Look up the shipping status for an order id (e.g. 'A100')."""
    return _ORDERS.get(order_id, {"status": "unknown", "eta": None})


@mcp.tool()
def calculate(expression: str) -> float:
    """Evaluate a simple arithmetic expression, e.g. '2 + 2 * 3'."""
    allowed = set("0123456789+-*/(). ")
    if not set(expression) <= allowed:
        raise ValueError("expression contains disallowed characters")
    return eval(expression, {"__builtins__": {}})


if __name__ == "__main__":
    print("MCP tool server listening on http://127.0.0.1:8000/mcp")
    mcp.run(transport="streamable-http")
