# AgentCore test app

A minimal app exercising the core AgentCore building blocks end to end, runnable
two ways: **locally** (everything on your machine, fastest iteration) and
**deployed to AWS** (the agent hosted on AgentCore Runtime, called like a real
external client would).

| # | Piece | File |
|---|-------|------|
| 1 | AgentCore **Gateway** | `deploy/gateway/setup_gateway.py` (infra), `app/lambda_tool.py` (the tool logic it fronts) |
| 2 | **Agent** (Strands) | `app/agent/agent.py` / `app/agent/runtime_app.py` |
| 3 | **MCP tool** (plain, no Gateway) | `app/mcp_tool/server.py` |
| 4 | **LLM call** (Bedrock) | `app/agent/agent.py` / `app/agent/runtime_app.py` (`BedrockModel`) |
| 5 | **AgentCore Runtime** | `app/agent/runtime_app.py`, deployed via `agentcore deploy` |
| 6 | **Runtime client** | `app/agent/client.py` |

```
app/                  # application code
  agent/
    agent.py           # local dev runner: Bedrock LLM + local MCP tool + Gateway, all direct
    runtime_app.py      # entrypoint deployed to AgentCore Runtime (talks to Gateway internally)
    client.py           # external client: calls the deployed Runtime, nothing else
  mcp_tool/
    server.py           # standalone local MCP tool server
  lambda_tool.py         # same get_order_status/calculate logic as mcp_tool/server.py,
                          # packaged as the Lambda handler behind the Gateway target
deploy/                # infra provisioning (not shipped in the Runtime image, no business logic)
  gateway/
    setup_gateway.py    # creates IAM roles, Lambda (from app/lambda_tool.py), Cognito, Gateway + Target
    teardown_gateway.py # deletes everything setup_gateway.py created
    cognito_setup.py     # Cognito user pool / app client for Gateway auth
  runtime/
    deploy_runtime.py   # wraps `agentcore configure`+`deploy`, injects Gateway creds as env vars
    destroy_runtime.py   # wraps `agentcore destroy`
  local/
    run_local.py         # one-command local test: starts the MCP server, runs the agent, stops it
.bedrock_agentcore.yaml  # agentcore CLI's own state file (toolkit-managed, project root)
```

## Architecture: the two modes

Gateway and Lambda are always real AWS resources (created once by
`setup_gateway.py`, shared by both modes below). What differs is where the
*agent* runs and how you reach it.

**Local mode** — `app/agent/agent.py` runs on your machine and talks to
everything directly:

```
you → agent.py (on your laptop)
        ├─→ local MCP server (127.0.0.1:8000)         [piece #3]
        ├─→ Gateway (Cognito OAuth) → Lambda tool      [piece #1]
        └─→ Bedrock (Converse API)                     [piece #4]
```

**AWS mode** — the same agent logic is deployed to AgentCore Runtime
(`runtime_app.py`); you only ever call the Runtime, never the Gateway:

```
you → client.py → invoke_agent_runtime() → AgentCore Runtime [piece #5]
                                               (runs runtime_app.py)
                                               ├─→ Gateway (Cognito OAuth) → Lambda  [piece #1]
                                               └─→ Bedrock (Converse API)            [piece #4]
```

The local MCP server (#3) is dev-only and unreachable from the deployed
container, so `runtime_app.py` only wires up the Gateway.

## Setup

```bash
pip install -r requirements.txt
aws login          # or `aws sso login` -- refresh credentials first
aws sts get-caller-identity   # sanity check
```

If you see `MissingDependencyException` about the login credential
provider, run `pip install "botocore[crt]"`.

**Both modes need the Gateway provisioned first.** This creates real AWS
resources: an IAM role + Lambda function, an IAM role + Cognito user pool for
the Gateway, and the Gateway + Gateway Target themselves.

```bash
python deploy/gateway/setup_gateway.py
```

Takes 1-2 minutes. On success it writes `deploy/gateway/.gateway_config.json`
(gateway URL + Cognito client credentials) and prints the Gateway's MCP URL.

---

## Local deployment

One command (starts the MCP server, runs the agent, stops the server):
```bash
python deploy/local/run_local.py "What's the status of order A100, and what's 12 * (3 + 4)?"
```

Or step by step:

1. Start the local MCP tool server (tests piece #3 on its own):
   ```bash
   python app/mcp_tool/server.py
   ```
   Leave it running.

2. Run the agent (tests #2 Agent, #4 LLM call, and both tool sources):
   ```bash
   python app/agent/agent.py "What's the status of order A100, and what's 12 * (3 + 4)?"
   ```
   If you haven't provisioned the Gateway yet, the agent still runs fine
   against just the local MCP tool -- useful for checking #2/#3/#4 in
   isolation.

   Example output:
   ```
   [agent] Using AgentCore Gateway at https://....gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp
   [agent] Loaded 2 tool(s) from ...: ['get_order_status', 'calculate']
   [agent] Loaded 2 tool(s) from ...: ['agentcore-demo-lambda-target___calculate', '...get_order_status']
   Tool #1: get_order_status
   Tool #2: calculate
   [agent] Final answer:
   The status of order A100 is shipped, with an ETA of 2026-10-23.
   12 * (3 + 4) equals 84.
   ```

## AWS deployment

One command (runs `agentcore configure` on first use, works around the two
toolkit bugs below automatically, then `agentcore deploy` with the Gateway's
credentials injected as Runtime env vars):
```bash
python deploy/runtime/deploy_runtime.py
```

> Why it's not just a raw `agentcore deploy`: `agentcore configure --create`
> has a toolkit bug where it skips Dockerfile generation, and
> `ecr_auto_create` isn't enabled by default -- both break a from-scratch
> deploy. `deploy_runtime.py` detects and fixes both every run (generates
> the Dockerfile via the toolkit's own `ContainerRuntime.generate_dockerfile()`
> if missing, flips `ecr_auto_create: true` in `.bedrock_agentcore.yaml` if
> needed) before calling `agentcore deploy`.

Then check it's ready and call it as an external client would -- straight to
the Runtime, never the Gateway:
```bash
agentcore status
python app/agent/client.py "What's the status of order A100?"
```

Example output:
```
[client] Invoking agent with prompt: What's the status of order A100?
[client] Response: Your order A100 has been shipped and is expected to arrive by October 23, 2026.
```

`client.py` reads the agent's ARN from `.bedrock_agentcore.yaml` and calls
`bedrock-agentcore.invoke_agent_runtime()` directly via boto3 -- the same
call `agentcore invoke` makes under the hood, just without the CLI.

To confirm the Gateway hop actually happened (rather than the model
guessing), tail the Runtime's logs for that invocation:
```bash
agentcore status   # prints the exact log group/stream-prefix to use
aws logs tail "/aws/bedrock-agentcore/runtimes/<agent-id>-DEFAULT" \
  --log-stream-name-prefix "<date>/[runtime-logs]" --since 10m
```
You should see an OAuth token fetch against the Cognito domain followed by
`POST .../mcp` calls to the Gateway URL.

## Tear down

```bash
python deploy/runtime/destroy_runtime.py    # Runtime, ECR repo, CodeBuild project
python deploy/gateway/teardown_gateway.py   # Gateway, Lambda, IAM roles, Cognito pool
```
(`destroy_runtime.py` doesn't remove the Memory resource -- see its docstring.)

## Notes

- Default model is `us.amazon.nova-2-lite-v1:0` (override with
  `BEDROCK_MODEL_ID=<id>`). Claude models on Bedrock require an Anthropic
  "model use case" form submitted for the account first (AWS console ->
  Bedrock -> Model access), independent of model/account permissions.
- Default region comes from your AWS config/profile (`~/.aws/config` has
  `us-east-1` set here).
- The Gateway uses `CUSTOM_JWT` auth (Cognito, `client_credentials` grant) --
  the standard way AgentCore Gateway secures its MCP endpoint for
  machine-to-machine callers. `app/agent/agent.py` and `app/agent/runtime_app.py`
  fetch the token automatically via Strands' `MCPClientCredentials`.
- `deploy/gateway/.gateway_config.json` and `.bedrock_agentcore.yaml` both
  contain account-specific state and are gitignored -- the former has a
  Cognito secret, the latter has your AWS account ID baked into every ARN.
  Both get regenerated by `setup_gateway.py` / `agentcore configure`+`deploy`
  on a fresh clone.
- Passing secrets via `agentcore deploy --env KEY=$VALUE` (shell variable,
  not literal text) keeps them out of your shell history/transcripts, but
  they still end up as plaintext Runtime env vars in AWS. Fine for this test;
  for anything long-lived, use AgentCore Identity instead so the agent's
  execution role fetches the credential at runtime rather than it being
  baked into the container's environment at deploy time.
