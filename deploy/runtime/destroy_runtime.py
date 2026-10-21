"""Tears down what deploy_runtime.py created: the Runtime endpoint, the
agent runtime, CodeBuild project, ECR images/repo, and the execution role
(if unused elsewhere) -- via `agentcore destroy`.

Note: this does not delete the Memory resource `agentcore deploy` creates
(agentcore destroy's own docs don't list it as something it removes). Clean
that up separately with `agentcore memory delete` if you want it gone too.

Usage:
    python deploy/runtime/destroy_runtime.py
"""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_NAME = "agentcore_demo_runtime_agent"


def main() -> None:
    env = {**os.environ, "AGENTCORE_SUPPRESS_RECOMMENDATION": "1"}
    cmd = ["agentcore", "destroy", "--agent", AGENT_NAME, "--force", "--delete-ecr-repo"]
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=REPO_ROOT, check=True, env=env)


if __name__ == "__main__":
    main()
