"""The npm publish job must keep checkout readable and name a deploy environment.

A job-level ``permissions:`` block replaces the workflow-level one rather than
merging with it.  ``id-token: write`` alone therefore leaves ``actions/checkout``
with ``contents: none``.  The job also needs an ``environment:`` so a deployment
rule can hold it, the same shape as the PyPI publish job.
"""

from pathlib import Path

import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "publish-npm.yml"


def test_publish_npm_job_keeps_checkout_readable_and_names_an_environment():
    config = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    assert isinstance(config, dict) and "jobs" in config
    job = config["jobs"]["publish"]
    permissions = job["permissions"]
    assert permissions.get("contents") == "read"
    assert permissions.get("id-token") == "write"
    assert job.get("environment"), "publish job must name an environment: for npm trusted publishing"
