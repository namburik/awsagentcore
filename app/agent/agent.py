"""The actual test app: one Strands Agent wired up to all four pieces.

  #4 LLM call   -> strands.models.BedrockModel (Bedrock Converse API, Claude)
  #3 MCP tool   -> local MCP server (app/mcp_tool/server.py), connected directly
  #1 Gateway    -> AgentCore Gateway's MCP endpoint (deploy/gateway/setup_gateway.py),
                   connected with OAuth client_credentials auth
  #2 Agent      -> strands.Agent, reasoning over both tool sources

Usage:
    python app/mcp_tool/server.py &              # starts the local MCP tool
    python deploy/gateway/setup_gateway.py        # one-time: provisions the Gateway
    python app/agent/agent.py "What's the status of order A100?"
    python app/agent/agent.py "What's 12 * (3 + 4), and is order A200 shipped yet?"

If deploy/gateway/.gateway_config.json doesn't exist yet, the agent still runs
with just the local MCP tool -- useful for testing pieces #2/#3/#4 before
you've provisioned AWS resources for #1.
"""

import json
import os
import sys
from contextlib import ExitStack
from pathlib import Path

from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from strands.tools.mcp.mcp_types import MCPClientCredentials

REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_CONFIG_PATH = REPO_ROOT / "deploy" / "gateway" / ".gateway_config.json"
LOCAL_MCP_URL = os.environ.get("LOCAL_MCP_URL", "http://127.0.0.1:8000/mcp")
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.amazon.nova-2-lite-v1:0")


def build_mcp_clients() -> list[MCPClient]:
    clients = [MCPClient(url=LOCAL_MCP_URL, application_name="agentcore-demo-agent")]

    if GATEWAY_CONFIG_PATH.exists():
        cfg = json.loads(GATEWAY_CONFIG_PATH.read_text())
        cognito = cfg["cognito"]
        gateway_client = MCPClient(
            url=cfg["gateway_url"],
            auth=MCPClientCredentials(
                client_id=cognito["client_id"],
                client_secret=cognito["client_secret"],
                scopes=[cognito["scope"]],
            ),
            application_name="agentcore-demo-agent",
        )
        clients.append(gateway_client)
        print(f"[agent] Using AgentCore Gateway at {cfg['gateway_url']}")
    else:
        print(f"[agent] No {GATEWAY_CONFIG_PATH} found -- skipping the Gateway tool source.")
        print("[agent] Run `python deploy/gateway/setup_gateway.py` to test piece #1 (Agent Gateway).")

    return clients


def main():
    prompt = " ".join(sys.argv[1:]) or "What's the status of order A100, and what's 12 * (3 + 4)?"

    model = BedrockModel(model_id=MODEL_ID)
    mcp_clients = build_mcp_clients()

    with ExitStack() as stack:
        for client in mcp_clients:
            stack.enter_context(client)

        tools = []
        for client in mcp_clients:
            client_tools = client.list_tools_sync()
            tools.extend(client_tools)
            print(f"[agent] Loaded {len(client_tools)} tool(s) from {client}: "
                  f"{[t.tool_name for t in client_tools]}")

        agent = Agent(
            model=model,
            tools=tools,
            system_prompt="You are a helpful support agent. Use the available tools to answer "
                           "questions about orders or arithmetic; don't guess.",
        )

        print(f"\n[agent] Prompt: {prompt}\n")
        result = agent(prompt)
        print(f"\n[agent] Final answer:\n{result}")


if __name__ == "__main__":
    main()
