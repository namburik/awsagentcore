"""Provisions a real AWS Bedrock AgentCore Gateway backed by a Lambda tool
(tests piece #1: Agent Gateway).

Creates, in order:
  1. IAM execution role for the Lambda tool
  2. The Lambda function (app/lambda_tool.py)
  3. IAM execution role for the Gateway itself (lets it invoke the Lambda)
  4. A Cognito user pool / app client for machine-to-machine auth (JWT)
  5. The AgentCore Gateway (protocol=MCP, authorizer=CUSTOM_JWT)
  6. A Gateway Target that maps the Lambda's two tools into MCP tools

Writes deploy/gateway/.gateway_config.json, which app/agent/agent.py,
app/agent/runtime_app.py, and teardown_gateway.py all read.

Requires AWS credentials with permission to create IAM roles, Lambda
functions, Cognito user pools, and AgentCore Gateways. Re-run
`aws login` / `aws sso login` first if `aws sts get-caller-identity` fails.
"""

import io
import json
import sys
import time
import zipfile
from pathlib import Path

import boto3

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
LAMBDA_SOURCE_PATH = REPO_ROOT / "app" / "lambda_tool.py"
sys.path.insert(0, str(HERE))
from cognito_setup import create_cognito_resources  # noqa: E402
CONFIG_PATH = HERE / ".gateway_config.json"

GATEWAY_NAME = "agentcore-demo-gateway"
TARGET_NAME = "agentcore-demo-lambda-target"
LAMBDA_FUNCTION_NAME = "agentcore-demo-tool"
LAMBDA_ROLE_NAME = "agentcore-demo-lambda-role"
GATEWAY_ROLE_NAME = "agentcore-demo-gateway-role"

TOOL_SCHEMA = [
    {
        "name": "get_order_status",
        "description": "Look up the shipping status for an order id (e.g. 'A100').",
        "inputSchema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "calculate",
        "description": "Evaluate a simple arithmetic expression, e.g. '2 + 2 * 3'.",
        "inputSchema": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
]


def _zip_lambda_source() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(LAMBDA_SOURCE_PATH, arcname="lambda_tool.py")
    return buf.getvalue()


def _create_lambda_role(iam, account_id: str) -> str:
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    try:
        role = iam.create_role(
            RoleName=LAMBDA_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
        )
        role_arn = role["Role"]["Arn"]
        iam.attach_role_policy(
            RoleName=LAMBDA_ROLE_NAME,
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        )
        print(f"Created IAM role {LAMBDA_ROLE_NAME}")
    except iam.exceptions.EntityAlreadyExistsException:
        role_arn = iam.get_role(RoleName=LAMBDA_ROLE_NAME)["Role"]["Arn"]
        print(f"Reusing existing IAM role {LAMBDA_ROLE_NAME}")
    return role_arn


def _create_lambda_function(lam, role_arn: str) -> str:
    code = _zip_lambda_source()
    for attempt in range(6):
        try:
            resp = lam.create_function(
                FunctionName=LAMBDA_FUNCTION_NAME,
                Runtime="python3.12",
                Role=role_arn,
                Handler="lambda_tool.lambda_handler",
                Code={"ZipFile": code},
                Timeout=10,
                Description="Demo tool backing an AgentCore Gateway target",
            )
            print(f"Created Lambda function {LAMBDA_FUNCTION_NAME}")
            return resp["FunctionArn"]
        except lam.exceptions.ResourceConflictException:
            resp = lam.update_function_code(FunctionName=LAMBDA_FUNCTION_NAME, ZipFile=code)
            print(f"Reusing existing Lambda function {LAMBDA_FUNCTION_NAME}")
            return resp["FunctionArn"]
        except lam.exceptions.InvalidParameterValueException:
            # IAM role not yet propagated -- retry.
            print("Waiting for IAM role to propagate...")
            time.sleep(5)
    raise RuntimeError("Timed out waiting for Lambda role to propagate")


def _create_gateway_role(iam, lambda_arn: str) -> str:
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    inline_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "lambda:InvokeFunction",
                "Resource": lambda_arn,
            }
        ],
    }
    try:
        role = iam.create_role(
            RoleName=GATEWAY_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
        )
        role_arn = role["Role"]["Arn"]
        print(f"Created IAM role {GATEWAY_ROLE_NAME}")
    except iam.exceptions.EntityAlreadyExistsException:
        role_arn = iam.get_role(RoleName=GATEWAY_ROLE_NAME)["Role"]["Arn"]
        print(f"Reusing existing IAM role {GATEWAY_ROLE_NAME}")

    iam.put_role_policy(
        RoleName=GATEWAY_ROLE_NAME,
        PolicyName="invoke-lambda-tool",
        PolicyDocument=json.dumps(inline_policy),
    )
    return role_arn


def main():
    session = boto3.Session()
    region = session.region_name or "us-east-1"
    sts = session.client("sts")
    account_id = sts.get_caller_identity()["Account"]
    print(f"Using account {account_id} in {region}")

    iam = session.client("iam")
    lam = session.client("lambda", region_name=region)
    gw = session.client("bedrock-agentcore-control", region_name=region)

    lambda_role_arn = _create_lambda_role(iam, account_id)
    time.sleep(8)  # let the role propagate before the first create_function
    lambda_arn = _create_lambda_function(lam, lambda_role_arn)

    gateway_role_arn = _create_gateway_role(iam, lambda_arn)
    time.sleep(8)

    print("Creating Cognito user pool / app client for Gateway auth...")
    cognito_cfg = create_cognito_resources(region)

    print("Creating AgentCore Gateway (this polls until READY, ~1-2 min)...")
    gateway = gw.create_gateway(
        name=GATEWAY_NAME,
        roleArn=gateway_role_arn,
        protocolType="MCP",
        authorizerType="CUSTOM_JWT",
        authorizerConfiguration={
            "customJWTAuthorizer": {
                "discoveryUrl": cognito_cfg["discovery_url"],
                "allowedClients": [cognito_cfg["client_id"]],
            }
        },
        description="Demo gateway for testing AgentCore end to end",
    )
    gateway_id = gateway["gatewayId"]

    waiter_statuses = {"READY", "FAILED"}
    status = gateway["status"]
    while status not in waiter_statuses:
        time.sleep(10)
        gateway = gw.get_gateway(gatewayIdentifier=gateway_id)
        status = gateway["status"]
        print(f"  gateway status: {status}")
    if status != "READY":
        raise RuntimeError(f"Gateway failed to become READY: {gateway}")

    gateway_url = gateway["gatewayUrl"]
    print(f"Gateway READY: {gateway_url}")

    print("Creating Gateway Target (Lambda -> MCP tools)...")
    target = gw.create_gateway_target(
        gatewayIdentifier=gateway_id,
        name=TARGET_NAME,
        targetConfiguration={
            "mcp": {
                "lambda": {
                    "lambdaArn": lambda_arn,
                    "toolSchema": {"inlinePayload": TOOL_SCHEMA},
                }
            }
        },
        credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
    )
    target_id = target["targetId"]

    status = target["status"]
    while status not in waiter_statuses:
        time.sleep(10)
        target = gw.get_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id)
        status = target["status"]
        print(f"  target status: {status}")
    if status != "READY":
        raise RuntimeError(f"Gateway target failed to become READY: {target}")

    print("Gateway target READY.")

    config = {
        "region": region,
        "account_id": account_id,
        "gateway_id": gateway_id,
        "gateway_url": gateway_url,
        "target_id": target_id,
        "lambda_arn": lambda_arn,
        "lambda_role_arn": lambda_role_arn,
        "gateway_role_arn": gateway_role_arn,
        "cognito": cognito_cfg,
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    print(f"\nSaved config to {CONFIG_PATH}")
    print(f"Gateway MCP URL: {gateway_url}")
    print("Run `python gateway/teardown_gateway.py` when you're done to avoid ongoing charges.")


if __name__ == "__main__":
    main()
