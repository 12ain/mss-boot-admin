#!/usr/bin/env python3
"""Wait for successful, exact-source main and tag workflow runs (read-only)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


MAIN_WORKFLOWS = (
    "ci.yml", "govulncheck.yml", "codeql.yml", "docs.yml",
    "admin-distribution-compatibility.yml", "mss-boot-ci.yml",
)
TAG_WORKFLOWS = {
    "framework-release.yml": "mss-boot/{version}",
    "admin-release.yml": "admin/{version}",
    "frontend-v6-release.yml": "web/antd-v6/{version}",
    "release.yml": "{version}",
    "container.yml": "{version}",
}
VERSION_RE = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class GateError(ValueError):
    pass


@dataclass(frozen=True)
class Requirement:
    workflow: str
    branch: str
    events: tuple[str, ...]


def requirements(version: str, phase: str) -> list[Requirement]:
    if not VERSION_RE.fullmatch(version):
        raise GateError("version must be an exact stable vX.Y.Z")
    if phase not in {"main", "all"}:
        raise GateError("phase must be main or all")
    result = [Requirement(name, "main", ("push", "workflow_dispatch"))
              for name in MAIN_WORKFLOWS]
    if phase == "all":
        result.extend(Requirement(name, tag.format(version=version), ("push",))
                      for name, tag in TAG_WORKFLOWS.items())
    return result


class GitHub:
    def __init__(self, repository: str, token: str, *, sleep=time.sleep):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise GateError("repository must be owner/name")
        if not token:
            raise GateError("GH_TOKEN or GITHUB_TOKEN is required")
        self.repository = repository
        self.token = token
        self.sleep = sleep

    def get(self, path: str) -> dict:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repository}/{path}",
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
        )
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    value = json.load(response)
                if not isinstance(value, dict):
                    raise GateError("GitHub returned a non-object response")
                return value
            except urllib.error.HTTPError as exc:
                transient = exc.code in {408, 429, 500, 502, 503, 504} or (
                    exc.code == 403 and exc.headers.get("Retry-After") is not None
                )
                exc.close()
                if not transient or attempt == 3:
                    raise GateError(f"GitHub request failed (HTTP {exc.code})") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 3:
                    raise GateError("GitHub request failed after bounded retries") from exc
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise GateError("GitHub returned malformed JSON") from exc
            self.sleep(2 ** attempt)
        raise GateError("GitHub request exhausted retries")

    def runs(self, commit: str) -> list[dict]:
        result = []
        # Read one exact-commit snapshot for every required workflow. Polling
        # each workflow separately can exhaust GITHUB_TOKEN's repository-wide
        # request budget while a slow tag build is still running.
        # Never silently truncate history: the pagination cap fails closed.
        for page in range(1, 11):
            query = urllib.parse.urlencode({"head_sha": commit,
                                           "per_page": 100, "page": page})
            value = self.get(f"actions/runs?{query}")
            rows = value.get("workflow_runs")
            total = value.get("total_count")
            if not isinstance(rows, list) or not isinstance(total, int) or total < 0:
                raise GateError("GitHub workflow-run response is incomplete")
            if any(not isinstance(row, dict) for row in rows):
                raise GateError("GitHub workflow-run response contains an invalid run")
            result.extend(rows)
            if len(result) >= total:
                return result
            if not rows:
                raise GateError("GitHub workflow-run pagination ended early")
        raise GateError("GitHub workflow-run pagination exceeded its safety limit")


def latest_run(rows: list[dict], requirement: Requirement, commit: str,
               repository: str) -> dict | None:
    exact = [row for row in rows if (
        row.get("head_sha") == commit
        and row.get("head_branch") == requirement.branch
        and row.get("event") in requirement.events
        and row.get("path") == f".github/workflows/{requirement.workflow}"
        and isinstance(row.get("head_repository"), dict)
        and row["head_repository"].get("full_name", "").lower() == repository.lower()
    )]
    for row in exact:
        if (type(row.get("id")) is not int or row["id"] < 1
                or type(row.get("run_attempt")) is not int or row["run_attempt"] < 1):
            raise GateError("GitHub run is missing its id or latest attempt")
    return max(exact, key=lambda row: (row["id"], row["run_attempt"]), default=None)


def inspect(api: GitHub, commit: str, selected: list[Requirement]) -> list[dict]:
    evidence = []
    rows = api.runs(commit)
    for requirement in selected:
        row = latest_run(rows, requirement, commit, api.repository)
        item = {"workflow": requirement.workflow, "branch": requirement.branch,
                "state": "missing"}
        if row is not None:
            item.update({"runId": row["id"], "attempt": row["run_attempt"],
                         "event": row["event"], "url": row.get("html_url"),
                         "state": row.get("status"), "conclusion": row.get("conclusion")})
            if item["state"] == "completed":
                if item["conclusion"] != "success":
                    raise GateError(f"{requirement.workflow} on {requirement.branch}: "
                                    f"latest run {row['id']} attempt {row['run_attempt']} "
                                    f"concluded {item['conclusion']!r}; rerun that failed workflow")
            elif item["state"] not in {"queued", "in_progress", "waiting", "pending", "requested"}:
                raise GateError(f"{requirement.workflow}: unknown run status {item['state']!r}")
        evidence.append(item)
    return evidence


def wait_for_runs(api: GitHub, commit: str, version: str, phase: str,
                  timeout: int, poll: int, *, clock=time.monotonic,
                  sleep=time.sleep, emit=print) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise GateError("commit must be a full lowercase Git SHA")
    if not 0 <= timeout <= 14400 or not 1 <= poll <= 60:
        raise GateError("timeout must be 0..14400 seconds and poll must be 1..60 seconds")
    selected = requirements(version, phase)
    deadline = clock() + timeout
    previous = None
    while True:
        evidence = inspect(api, commit, selected)
        status = [(row["workflow"], row["state"], row.get("runId"), row.get("attempt"))
                  for row in evidence]
        if status != previous:
            emit(json.dumps({"workflows": evidence}, sort_keys=True))
            previous = status
        if all(row["state"] == "completed" for row in evidence):
            return {"repository": api.repository, "commit": commit, "version": version,
                    "phase": phase, "success": True, "workflows": evidence}
        remaining = deadline - clock()
        if remaining <= 0:
            unresolved = ", ".join(f"{row['workflow']} ({row['branch']}: {row['state']})"
                                   for row in evidence if row["state"] != "completed")
            raise GateError(f"timed out waiting for exact-source workflows: {unresolved}. "
                            "For path-filtered main checks, dispatch that workflow on main "
                            "only while main still equals the required commit.")
        sleep(min(poll, remaining))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--phase", choices=("main", "all"), default="all")
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        api = GitHub(args.repository, os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", ""))
        result = wait_for_runs(api, args.commit, args.version, args.phase,
                               args.timeout_seconds, args.poll_seconds)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, sort_keys=True))
        return 0
    except GateError as exc:
        print(f"release workflow gate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
