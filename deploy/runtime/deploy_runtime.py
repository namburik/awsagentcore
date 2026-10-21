"""Deploys app/agent/runtime_app.py to AgentCore Runtime (tests piece #5).

Wraps the `agentcore` CLI end to end:
  1. `agentcore configure --create` (first run only)
  2. Works around two bedrock-agentcore-starter-toolkit bugs hit while
     building this: `configure --create` skips Dockerfile generation, and
     `ecr_auto_create` isn't enabled by default, so a fresh deploy fails
     without both fixes.
  3. Reads the Gateway's URL + Cognito credentials from
     deploy/gateway/.gateway_config.json
  4. `agentcore deploy` with those values injected as Runtime env vars

Requires:
  - deploy/gateway/setup_gateway.py already run (the Gateway must exist first)
  - `pip install bedrock-agentcore-starter-toolkit` (provides the `agentcore` CLI)

Usage:
    python deploy/runtime/deploy_runtime.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_NAME = "agentcore_demo_runtime_agent"
ENTRYPOINT = "app/agent/runtime_app.py"
REGION = "us-east-1"
DEFAULT_MODEL_ID = "us.amazon.nova-2-lite-v1:0"

GATEWAY_CONFIG_PATH = REPO_ROOT / "deploy" / "gateway" / ".gateway_config.json"
BEDROCK_AGENTCORE_YAML = REPO_ROOT / ".bedrock_agentcore.yaml"


def run(cmd: list[str], redact_values: list[str] | None = None) -> None:
    printable = [str(part) for part in cmd]
    for secret in redact_values or []:
        if secret:
            printable = [part.replace(secret, "***REDACTED***") for part in printable]
    print(f"$ {' '.join(printable)}")

    env = {**os.environ, "AGENTCORE_SUPPRESS_RECOMMENDATION": "1"}
    subprocess.run(cmd, cwd=REPO_ROOT, check=True, env=env)


def ensure_configured() -> None:
    if BEDROCK_AGENTCORE_YAML.exists():
        config = yaml.safe_load(BEDROCK_AGENTCORE_YAML.read_text())
        if AGENT_NAME in config.get("agents", {}):
            print(f"[deploy_runtime] Agent '{AGENT_NAME}' already configured, skipping `agentcore configure`.")
            return

    run([
        "agentcore", "configure", "--create",
        "--entrypoint", ENTRYPOINT,
        "--name", AGENT_NAME,
        "--requirements-file", "requirements.txt",
        "--region", REGION,
        "--protocol", "HTTP",
        "--non-interactive",
    ])


def fix_toolkit_bugs() -> None:
    """Work around `configure --create`'s missing Dockerfile generation and
    missing ecr_auto_create default -- both of which broke the first real
    deploy we tried against this account.
    """
    from bedrock_agentcore_starter_toolkit.utils.runtime.config import get_agentcore_directory
    from bedrock_agentcore_starter_toolkit.utils.runtime.container import ContainerRuntime

    config = yaml.safe_load(BEDROCK_AGENTCORE_YAML.read_text())
    agent_config = config["agents"][AGENT_NAME]

    if not agent_config["aws"]["ecr_auto_create"]:
        agent_config["aws"]["ecr_auto_create"] = True
        BEDROCK_AGENTCORE_YAML.write_text(yaml.dump(config, sort_keys=False))
        print("[deploy_runtime] Set ecr_auto_create: true in .bedrock_agentcore.yaml")

    output_dir = get_agentcore_directory(REPO_ROOT, AGENT_NAME, agent_config["source_path"])
    dockerfile_path = output_dir / "Dockerfile"
    if not dockerfile_path.exists():
        memory = agent_config.get("memory") or {}
        ContainerRuntime(print_logs=False).generate_dockerfile(
            agent_path=Path(ENTRYPOINT),
            output_dir=output_dir,
            agent_name=AGENT_NAME,
            aws_region=REGION,
            enable_observability=True,
            requirements_file="requirements.txt",
            memory_id=memory.get("memory_id"),
            memory_name=memory.get("memory_name"),
            source_path=agent_config["source_path"],
            protocol="HTTP",
            silence_warn=True,
            language="python",
            node_version="20",
        )
        print(f"[deploy_runtime] Generated {dockerfile_path}")


def deploy(model_id: str) -> None:
    if not GATEWAY_CONFIG_PATH.exists():
        raise RuntimeError(f"{GATEWAY_CONFIG_PATH} not found -- run deploy/gateway/setup_gateway.py first.")

    gateway_cfg = json.loads(GATEWAY_CONFIG_PATH.read_text())
    cognito = gateway_cfg["cognito"]

    run(
        [
            "agentcore", "deploy",
            "--agent", AGENT_NAME,
            "--env", f"GATEWAY_URL={gateway_cfg['gateway_url']}",
            "--env", f"GATEWAY_CLIENT_ID={cognito['client_id']}",
            "--env", f"GATEWAY_CLIENT_SECRET={cognito['client_secret']}",
            "--env", f"GATEWAY_SCOPE={cognito['scope']}",
            "--env", f"BEDROCK_MODEL_ID={model_id}",
            "--auto-update-on-conflict",
        ],
        redact_values=[cognito["client_secret"]],
    )


def main() -> None:
    model_id = os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)

    ensure_configured()
    fix_toolkit_bugs()
    deploy(model_id)

    config = yaml.safe_load(BEDROCK_AGENTCORE_YAML.read_text())
    agent_arn = config["agents"][AGENT_NAME]["bedrock_agentcore"]["agent_arn"]
    print(f"\n[deploy_runtime] Deployed. Agent ARN: {agent_arn}")
    print('[deploy_runtime] Call it with: python app/agent/client.py "your prompt"')


if __name__ == "__main__":
    main()
