"""Deletes everything setup_gateway.py created, in reverse order."""

import json
import sys
from pathlib import Path

import boto3

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from cognito_setup import delete_cognito_resources  # noqa: E402

CONFIG_PATH = HERE / ".gateway_config.json"

LAMBDA_FUNCTION_NAME = "agentcore-demo-tool"
LAMBDA_ROLE_NAME = "agentcore-demo-lambda-role"
GATEWAY_ROLE_NAME = "agentcore-demo-gateway-role"


def main():
    if not CONFIG_PATH.exists():
        print(f"No {CONFIG_PATH} found -- nothing to tear down.")
        return

    config = json.loads(CONFIG_PATH.read_text())
    region = config["region"]
    session = boto3.Session(region_name=region)

    gw = session.client("bedrock-agentcore-control")
    lam = session.client("lambda")
    iam = session.client("iam")

    print("Deleting gateway target...")
    try:
        gw.delete_gateway_target(gatewayIdentifier=config["gateway_id"], targetId=config["target_id"])
    except Exception as exc:  # noqa: BLE001
        print(f"  (warning) {exc}")

    print("Deleting gateway...")
    try:
        gw.delete_gateway(gatewayIdentifier=config["gateway_id"])
    except Exception as exc:  # noqa: BLE001
        print(f"  (warning) {exc}")

    print("Deleting Lambda function...")
    try:
        lam.delete_function(FunctionName=LAMBDA_FUNCTION_NAME)
    except Exception as exc:  # noqa: BLE001
        print(f"  (warning) {exc}")

    print("Deleting IAM roles...")
    for role_name, policy_names in (
        (LAMBDA_ROLE_NAME, []),
        (GATEWAY_ROLE_NAME, ["invoke-lambda-tool"]),
    ):
        try:
            for policy_name in policy_names:
                iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
            for attached in iam.list_attached_role_policies(RoleName=role_name)["AttachedPolicies"]:
                iam.detach_role_policy(RoleName=role_name, PolicyArn=attached["PolicyArn"])
            iam.delete_role(RoleName=role_name)
        except Exception as exc:  # noqa: BLE001
            print(f"  (warning) could not delete role {role_name}: {exc}")

    print("Deleting Cognito resources...")
    delete_cognito_resources(region, config["cognito"])

    CONFIG_PATH.unlink()
    print("Teardown complete.")


if __name__ == "__main__":
    main()
