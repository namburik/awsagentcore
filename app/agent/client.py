"""External client for the deployed AgentCore Runtime agent.

This is what a real caller looks like: it never touches the Gateway, the
Lambda, or Cognito directly -- it only knows the Runtime's agent ARN and
calls the `bedrock-agentcore` data-plane API. Everything else (Gateway auth,
tool calls, the LLM call) happens inside the Runtime container, invisible to
this script.

Usage:
    python agent/client.py "What's the status of order A100?"

Reads the agent ARN from .bedrock_agentcore.yaml (written by `agentcore
deploy`) so you don't have to hardcode it. Override with --arn if you want
to point at a different agent/account.
"""

import argparse
import json
import sys
from pathlib import Path

import boto3
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / ".bedrock_agentcore.yaml"


def _load_agent_arn(agent_name: str | None) -> tuple[str, str]:
    config = yaml.safe_load(CONFIG_PATH.read_text())
    agent_name = agent_name or config["default_agent"]
    agent_config = config["agents"][agent_name]
    region = agent_config["aws"]["region"]
    agent_arn = agent_config["bedrock_agentcore"]["agent_arn"]
    if not agent_arn:
        raise RuntimeError(
            f"No agent_arn recorded for '{agent_name}' in {CONFIG_PATH} -- run `agentcore deploy` first."
        )
    return agent_arn, region


def invoke(prompt: str, agent_name: str | None = None, agent_arn: str | None = None, region: str | None = None) -> dict:
    if not agent_arn:
        agent_arn, config_region = _load_agent_arn(agent_name)
        region = region or config_region

    client = boto3.client("bedrock-agentcore", region_name=region)
    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        qualifier="DEFAULT",
        payload=json.dumps({"prompt": prompt}).encode("utf-8"),
        contentType="application/json",
    )
    body = response["response"].read()
    return json.loads(body)


def main():
    parser = argparse.ArgumentParser(description="Invoke the deployed AgentCore Runtime agent")
    parser.add_argument("prompt", nargs="*", help="Prompt to send; defaults to a canned test prompt")
    parser.add_argument("--agent", help="Agent name from .bedrock_agentcore.yaml (defaults to default_agent)")
    parser.add_argument("--arn", help="Explicit agent runtime ARN, bypassing .bedrock_agentcore.yaml")
    parser.add_argument("--region", help="AWS region, if not inferred from config")
    args = parser.parse_args()

    prompt = " ".join(args.prompt) or "What's the status of order A100, and what's 12 * (3 + 4)?"

    print(f"[client] Invoking agent with prompt: {prompt}")
    result = invoke(prompt, agent_name=args.agent, agent_arn=args.arn, region=args.region)
    print(f"[client] Response: {result.get('result', result)}")


if __name__ == "__main__":
    main()
