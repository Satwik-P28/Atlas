#!/usr/bin/env python3
"""Refuse to publish unless the release environment actually requires approval.

`environment: open-data-release` in a workflow is only a *name*. If the environment
does not exist, GitHub creates it on first use **without** protection, and the job
then holds a write token with no human gate. This script reads the environment's
actual protection rules and fails unless:

* the environment exists;
* at least one required reviewer is configured;
* self-review is prevented (when the API exposes that setting);
* the deployment branch policy admits only ``main`` (or protected branches).

It runs inside the draft and publish jobs, so a misconfigured repository cannot
quietly publish data. Run it locally with a token that can read environments:

    GH_TOKEN=... python scripts/check_release_environment.py --repo Satwik-P28/Atlas
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ENVIRONMENT = "open-data-release"


def fetch_environment(repo: str, environment: str, token: str, *,
                      base: str = "https://api.github.com", timeout: float = 30.0) -> dict:
    url = f"{base}/repos/{repo}/environments/{environment}"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "Atlas-Data-Engine/1.0",
        "Authorization": f"Bearer {token}",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"cannot read environment {environment}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"cannot read environment {environment}: {exc}") from exc


def evaluate(payload: dict, *, allowed_branch: str = "main") -> dict:
    """Judge an environment payload. Returns a report with ``ok`` and findings."""
    rules = payload.get("protection_rules") or []
    reviewers = 0
    prevent_self_review = False
    review_rule = None
    for rule in rules:
        if rule.get("type") == "required_reviewers":
            review_rule = rule
            reviewers = len(rule.get("reviewers") or [])
            prevent_self_review = bool(rule.get("prevent_self_review"))
    branch_policy = payload.get("deployment_branch_policy")
    if branch_policy is None:
        branches = []
        policy_ok = False
        policy_detail = "no deployment branch policy: every branch can reach the token"
    else:
        protected = bool(branch_policy.get("protected_branches"))
        custom = bool(branch_policy.get("custom_branch_policies"))
        branches = list(payload.get("branch_policies") or [])
        names = {str(item.get("name")) for item in branches}
        if protected:
            policy_ok = True
            policy_detail = "only protected branches may deploy"
        elif custom:
            policy_ok = allowed_branch in names
            policy_detail = f"custom branches: {sorted(names) or 'none configured'}"
        else:
            policy_ok = False
            policy_detail = "deployment branch policy admits no branch"
    findings: list[str] = []
    if reviewers < 1:
        findings.append("no required reviewer: approval is not enforced")
    if branch_policy is not None and not policy_ok:
        findings.append(policy_detail)
    if branch_policy is None:
        findings.append(policy_detail)
    if review_rule is not None and not prevent_self_review:
        findings.append(
            "prevent_self_review is false: the operator who dispatched can approve their own "
            "publication")
    return {
        "environment": payload.get("name"),
        "exists": True,
        "required_reviewers": reviewers,
        "prevent_self_review": prevent_self_review,
        "deployment_branch_policy": branch_policy,
        "branch_policy_detail": policy_detail,
        "findings": findings,
        "ok": not findings,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--environment", default=ENVIRONMENT)
    parser.add_argument("--allowed-branch", default="main")
    parser.add_argument("--payload", help="read a saved API response instead of the network")
    args = parser.parse_args(argv)
    if args.payload:
        payload = json.loads(open(args.payload, encoding="utf-8").read())
    else:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            print("a token able to read environments is required (GH_TOKEN)", file=sys.stderr)
            return 2
        if not args.repo:
            print("--repo or GITHUB_REPOSITORY is required", file=sys.stderr)
            return 2
        payload = fetch_environment(args.repo, args.environment, token)
    report = evaluate(payload, allowed_branch=args.allowed_branch)
    print(json.dumps(report, indent=2))
    if not report["ok"]:
        print(
            "The publication environment is not protected. Configure it in Settings -> "
            "Environments: required reviewers (at least one, self-review prevented) and a "
            "deployment branch policy limited to main. See docs/OPEN_DATA_RELEASE_SECURITY.md.",
            file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
