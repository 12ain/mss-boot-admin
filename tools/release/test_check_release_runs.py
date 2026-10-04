import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_release_runs as gate

SHA = "a" * 40
REPO = "mss-boot-io/mss-boot-admin"
VERSION = "v1.3.8"


def run(requirement, **changes):
    value = {"id": 50, "run_attempt": 1, "head_sha": SHA,
             "head_branch": requirement.branch, "event": "push",
             "path": ".github/workflows/" + requirement.workflow,
             "head_repository": {"full_name": REPO},
             "status": "completed", "conclusion": "success",
             "html_url": "https://github.com/" + REPO + "/actions/runs/50"}
    value.update(changes)
    return value


class FakeAPI:
    repository = REPO

    def __init__(self, override=None):
        self.override = override or {}

    def runs(self, commit):
        return [row for requirement in gate.requirements(VERSION, "all")
                for row in self.override.get(requirement.workflow, [run(requirement)])]


class ReleaseRunGateTest(unittest.TestCase):
    def test_complete_main_and_tag_success(self):
        result = gate.wait_for_runs(FakeAPI(), SHA, VERSION, "all", 0, 1, emit=lambda _: None)
        self.assertTrue(result["success"])
        self.assertEqual(len(result["workflows"]), 11)
        self.assertEqual(result["commit"], SHA)
        self.assertEqual({r["workflow"] for r in result["workflows"]},
                         set(gate.MAIN_WORKFLOWS) | set(gate.TAG_WORKFLOWS))
        self.assertNotIn("docs/v1.3.8", {r["branch"] for r in result["workflows"]})

    def test_one_repository_snapshot_satisfies_all_eleven_requirements(self):
        api = gate.GitHub(REPO, "unused-test-token")
        rows = [run(requirement, id=index + 1)
                for index, requirement in enumerate(gate.requirements(VERSION, "all"))]
        # Unrelated branch, PR and workflow results share the same endpoint;
        # none may displace the exact main/tag identities.
        main = gate.requirements(VERSION, "main")[0]
        rows.extend([run(main, id=100, head_branch="feature", conclusion="failure"),
                     run(main, id=101, event="pull_request", conclusion="failure"),
                     run(main, id=102, path=".github/workflows/other.yml", conclusion="failure")])
        response = io.BytesIO(json.dumps({"workflow_runs": rows, "total_count": len(rows)}).encode())
        with patch.object(gate.urllib.request, "urlopen", return_value=response) as opener:
            result = gate.wait_for_runs(api, SHA, VERSION, "all", 0, 1, emit=lambda _: None)
        self.assertTrue(result["success"])
        self.assertEqual(len(result["workflows"]), 11)
        self.assertEqual(opener.call_count, 1)
        url = opener.call_args.args[0].full_url
        self.assertIn("/actions/runs?head_sha=" + SHA, url)
        self.assertNotIn("/actions/workflows/", url)
        self.assertNotIn("branch=", url)

    def test_wrong_identity_never_satisfies_gate(self):
        required = gate.requirements(VERSION, "main")[0]
        for change in ({"head_sha": "b" * 40}, {"head_branch": "feature"},
                       {"event": "pull_request"}, {"event": "schedule"},
                       {"path": ".github/workflows/not-ci.yml"},
                       {"head_repository": {"full_name": "fork/repository"}},
                       {"head_repository": None}):
            with self.subTest(change=change):
                self.assertIsNone(gate.latest_run([run(required, **change)], required, SHA, REPO))

    def test_main_dispatch_backfills_path_filtered_workflow_but_tag_dispatch_cannot(self):
        main, tag = gate.requirements(VERSION, "all")[0], gate.requirements(VERSION, "all")[-1]
        self.assertIsNotNone(gate.latest_run([run(main, event="workflow_dispatch")], main, SHA, REPO))
        self.assertIsNone(gate.latest_run([run(tag, event="workflow_dispatch")], tag, SHA, REPO))

    def test_old_success_does_not_hide_new_failure_or_rerun(self):
        requirement = gate.requirements(VERSION, "main")[0]
        for newer in (run(requirement, id=51, conclusion="failure"),
                      run(requirement, run_attempt=2, conclusion="failure")):
            with self.subTest(newer=newer):
                with self.assertRaisesRegex(gate.GateError, "latest run"):
                    gate.inspect(FakeAPI({"ci.yml": [run(requirement), newer]}), SHA, [requirement])
        pending = run(requirement, run_attempt=2, status="in_progress", conclusion=None)
        evidence = gate.inspect(FakeAPI({"ci.yml": [run(requirement), pending]}), SHA, [requirement])
        self.assertEqual(evidence[0]["state"], "in_progress")
        self.assertEqual(evidence[0]["attempt"], 2)

    def test_completed_non_success_is_never_accepted(self):
        requirement = gate.requirements(VERSION, "main")[0]
        for conclusion in ("failure", "cancelled", "skipped", "neutral", "timed_out", None):
            with self.subTest(conclusion=conclusion):
                with self.assertRaises(gate.GateError):
                    gate.inspect(FakeAPI({"ci.yml": [run(requirement, conclusion=conclusion)]}),
                                 SHA, [requirement])

    def test_missing_workflow_times_out_with_exact_branch_diagnostic(self):
        with self.assertRaisesRegex(gate.GateError, r"ci.yml \(main: missing\)"):
            gate.wait_for_runs(FakeAPI({"ci.yml": []}), SHA, VERSION, "main", 0, 1,
                               emit=lambda _: None)

    def test_waits_for_new_attempt_completion_without_accepting_old_success(self):
        requirement = gate.requirements(VERSION, "main")[0]
        api = FakeAPI({"ci.yml": [run(requirement, run_attempt=2, status="in_progress", conclusion=None)]})
        sleeps = []

        def finish(seconds):
            sleeps.append(seconds)
            api.override["ci.yml"] = [run(requirement, run_attempt=2)]

        result = gate.wait_for_runs(api, SHA, VERSION, "main", 60, 1,
                                    clock=lambda: 0, sleep=finish, emit=lambda _: None)
        self.assertEqual(sleeps, [1])
        self.assertEqual(result["workflows"][0]["attempt"], 2)

    def test_invalid_input_and_unknown_run_status_fail_closed(self):
        for commit, version, timeout, poll in (("short", VERSION, 1, 1),
                                              (SHA, "v1.3.8-rc.1", 1, 1),
                                              (SHA, VERSION, -1, 1),
                                              (SHA, VERSION, 1, 0)):
            with self.assertRaises(gate.GateError):
                gate.wait_for_runs(FakeAPI(), commit, version, "all", timeout, poll)
        requirement = gate.requirements(VERSION, "main")[0]
        for change in ({"status": "unknown"}, {"run_attempt": None}, {"id": 0}):
            with self.assertRaises(gate.GateError):
                gate.inspect(FakeAPI({"ci.yml": [run(requirement, **change)]}), SHA, [requirement])

    def test_transient_api_failure_is_retried_and_auth_failure_is_not(self):
        delays = []
        api = gate.GitHub(REPO, "unused-test-token", sleep=delays.append)
        transient = urllib.error.HTTPError("unused", 503, "unavailable", {}, None)
        success = io.BytesIO(json.dumps({"workflow_runs": [], "total_count": 0}).encode())
        with patch.object(gate.urllib.request, "urlopen", side_effect=[transient, success]) as opener:
            self.assertEqual(api.get("actions/runs")["total_count"], 0)
            self.assertEqual(opener.call_count, 2)
        self.assertEqual(delays, [1])
        denied = urllib.error.HTTPError("unused", 403, "forbidden", {}, None)
        with patch.object(gate.urllib.request, "urlopen", side_effect=denied) as opener:
            with self.assertRaisesRegex(gate.GateError, "HTTP 403"):
                api.get("actions/runs")
            self.assertEqual(opener.call_count, 1)

    def test_transient_retry_budget_is_finite(self):
        api = gate.GitHub(REPO, "unused-test-token", sleep=lambda _: None)
        with patch.object(gate.urllib.request, "urlopen", side_effect=TimeoutError) as opener:
            with self.assertRaisesRegex(gate.GateError, "bounded retries"):
                api.get("actions/runs")
            self.assertEqual(opener.call_count, 4)

    def test_pagination_does_not_omit_later_matching_run(self):
        api = gate.GitHub(REPO, "unused-test-token")
        requirement = gate.requirements(VERSION, "main")[0]
        rows = [run(requirement, id=i + 1) for i in range(100)]
        with patch.object(api, "get", side_effect=[
            {"workflow_runs": rows, "total_count": 101},
            {"workflow_runs": [run(requirement, id=101)], "total_count": 101},
        ]) as getter:
            result = api.runs(SHA)
        self.assertEqual(gate.latest_run(result, requirement, SHA, REPO)["id"], 101)
        self.assertIn("page=2", getter.call_args_list[1].args[0])

    def test_batched_gate_checks_all_pages_before_accepting_old_successes(self):
        api = gate.GitHub(REPO, "unused-test-token")
        selected = gate.requirements(VERSION, "all")
        rows = [run(requirement, id=index + 1)
                for index, requirement in enumerate(selected)]
        rows.extend(run(selected[0], id=index + 100, event="pull_request")
                    for index in range(100 - len(rows)))
        newer_failure = run(selected[0], id=1000, conclusion="failure")
        with patch.object(api, "get", side_effect=[
            {"workflow_runs": rows, "total_count": 101},
            {"workflow_runs": [newer_failure], "total_count": 101},
        ]) as getter:
            with self.assertRaisesRegex(gate.GateError, "latest run 1000"):
                gate.wait_for_runs(api, SHA, VERSION, "all", 0, 1, emit=lambda _: None)
        self.assertEqual(getter.call_count, 2)


if __name__ == "__main__":
    unittest.main()
