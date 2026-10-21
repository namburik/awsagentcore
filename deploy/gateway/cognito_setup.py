"""Creates the Cognito User Pool + domain + app client AgentCore Gateway needs
for its inbound CUSTOM_JWT authorizer (machine-to-machine client_credentials grant).

Not meant to be run directly -- imported by setup_gateway.py / teardown_gateway.py.
"""

import time
import uuid

import boto3

POOL_NAME = "agentcore-demo-pool"
RESOURCE_SERVER_ID = "agentcore-demo"
SCOPE_NAME = "gateway.invoke"
CLIENT_NAME = "agentcore-demo-client"


def create_cognito_resources(region: str) -> dict:
    cognito = boto3.client("cognito-idp", region_name=region)

    pool = cognito.create_user_pool(PoolName=POOL_NAME)
    pool_id = pool["UserPool"]["Id"]

    cognito.create_resource_server(
        UserPoolId=pool_id,
        Identifier=RESOURCE_SERVER_ID,
        Name=RESOURCE_SERVER_ID,
        Scopes=[{"ScopeName": SCOPE_NAME, "ScopeDescription": "Invoke the demo gateway"}],
    )

    full_scope = f"{RESOURCE_SERVER_ID}/{SCOPE_NAME}"
    client = cognito.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName=CLIENT_NAME,
        GenerateSecret=True,
        AllowedOAuthFlows=["client_credentials"],
        AllowedOAuthScopes=[full_scope],
        AllowedOAuthFlowsUserPoolClient=True,
        SupportedIdentityProviders=["COGNITO"],
    )
    client_id = client["UserPoolClient"]["ClientId"]
    client_secret = client["UserPoolClient"]["ClientSecret"]

    domain_prefix = f"agentcore-demo-{uuid.uuid4().hex[:12]}"
    cognito.create_user_pool_domain(Domain=domain_prefix, UserPoolId=pool_id)

    # Domain propagation can take a few seconds before the token endpoint resolves.
    time.sleep(10)

    discovery_url = (
        f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/openid-configuration"
    )
    token_url = f"https://{domain_prefix}.auth.{region}.amazoncognito.com/oauth2/token"

    return {
        "user_pool_id": pool_id,
        "domain_prefix": domain_prefix,
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": full_scope,
        "discovery_url": discovery_url,
        "token_url": token_url,
    }


def delete_cognito_resources(region: str, cognito_cfg: dict) -> None:
    cognito = boto3.client("cognito-idp", region_name=region)
    pool_id = cognito_cfg["user_pool_id"]

    try:
        cognito.delete_user_pool_domain(Domain=cognito_cfg["domain_prefix"], UserPoolId=pool_id)
    except Exception as exc:  # noqa: BLE001
        print(f"  (warning) could not delete Cognito domain: {exc}")

    try:
        cognito.delete_user_pool(UserPoolId=pool_id)
    except Exception as exc:  # noqa: BLE001
        print(f"  (warning) could not delete Cognito user pool: {exc}")
