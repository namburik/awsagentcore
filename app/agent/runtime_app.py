"""Entrypoint for deploying the agent to AgentCore Runtime (tests Runtime
deployment on top of the other four pieces).

Only wires up the Gateway tool source (not the local MCP server, which only
exists on a dev machine and wouldn't be reachable from the deployed
container). Configuration comes from environment variables set at deploy
time (`agentcore deploy --env ...`) -- see deploy/gateway/.gateway_config.json
for the values those env vars are pulled from.
"""

import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from strands.tools.mcp.mcp_types import MCPClientCredentials

MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.amazon.nova-2-lite-v1:0")
GATEWAY_URL = os.environ["GATEWAY_URL"]
GATEWAY_CLIENT_ID = os.environ["GATEWAY_CLIENT_ID"]
GATEWAY_CLIENT_SECRET = os.environ["GATEWAY_CLIENT_SECRET"]
GATEWAY_SCOPE = os.environ["GATEWAY_SCOPE"]

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict) -> dict:
    prompt = payload.get("prompt", "What's the status of order A100, and what's 12 * (3 + 4)?")

    model = BedrockModel(model_id=MODEL_ID)
    gateway_client = MCPClient(
        url=GATEWAY_URL,
        auth=MCPClientCredentials(
            client_id=GATEWAY_CLIENT_ID,
            client_secret=GATEWAY_CLIENT_SECRET,
            scopes=[GATEWAY_SCOPE],
        ),
        application_name="agentcore-demo-runtime-agent",
    )

    with gateway_client:
        tools = gateway_client.list_tools_sync()
        agent = Agent(
            model=model,
            tools=tools,
            system_prompt="You are a helpful support agent. Use the available tools to "
                           "answer questions about orders or arithmetic; don't guess.",
        )
        result = agent(prompt)

    return {"result": str(result)}


if __name__ == "__main__":
    app.run()
