import copy
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import withdraw_failed_v138 as recovery


ENV = {
    "GITHUB_REPOSITORY": recovery.REPOSITORY,
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_EVENT_NAME": "workflow_dispatch",
    "GITHUB_ACTOR": recovery.ACTOR,
    "GITHUB_TRIGGERING_ACTOR": recovery.ACTOR,
    "GITHUB_WORKFLOW_REF": f"{recovery.REPOSITORY}/.github/workflows/withdraw-failed-v138.yml@refs/heads/main",
}


def version(target, ident):
    return {"id": ident, "name": target.version,
            "metadata": {"container": {"tags": ["v1.3.8", recovery.OLD_COMMIT]}}}


class FakeAPI:
    def __init__(self):
        self.rows = {target: [version(target, index + 1)]
                     for index, target in enumerate(recovery.TARGETS)}
        self.metadata = {"name": "@mss-boot-io/admin-web", "version": "1.3.8",
                         "gitHead": recovery.OLD_COMMIT,
                         "dist": {"integrity": recovery.NPM_INTEGRITY}}
        self.official = None
        self.blocked_path = None
        self.deleted = []
        self.reads = []
        self.detail_override = None

    def get(self, path, *, missing=False):
        self.reads.append(path)
        if path == self.blocked_path:
            return {"id": 999}
        if path == f"/repos/{recovery.REPOSITORY}":
            return {"full_name": recovery.REPOSITORY}
        if path.startswith(f"/repos/{recovery.REPOSITORY}/"):
            return None
        for target, rows in self.rows.items():
            if path == target.path:
                return {"name": target.package, "package_type": target.kind,
                        "owner": {"login": recovery.OWNER},
                        "repository": {"full_name": recovery.REPOSITORY}}
            if path.startswith(target.path + "/versions?"):
                page = int(path.rsplit("page=", 1)[1])
                return copy.deepcopy(rows[(page - 1) * 100:page * 100])
            if path.startswith(target.path + "/versions/"):
                if self.detail_override is not None:
                    return self.detail_override
                ident = int(path.rsplit("/", 1)[1])
                return copy.deepcopy(next(row for row in rows if row["id"] == ident))
        raise AssertionError(f"unexpected read {path}")

    def npm(self, *, official=False):
        return copy.deepcopy(self.official if official else self.metadata)

    def delete_version(self, target, ident):
        self.deleted.append((target, ident))
        self.rows[target] = [row for row in self.rows[target] if row["id"] != ident]
        if target.kind == "npm":
            self.metadata = None


def execute(api, *, write=True, env=ENV):
    recovery.cleanup(api, env, write=write, emit=lambda _: None)


class WithdrawalTest(unittest.TestCase):
    def test_deletes_only_three_old_versions_and_keeps_shared_children(self):
        api = FakeAPI()
        for target in recovery.TARGETS[1:]:
            api.rows[target].append({"id": 100, "name": "sha256:" + "a" * 64,
                                     "metadata": {"container": {"tags": []}}})
        execute(api)
        self.assertEqual(api.deleted, list(zip(recovery.TARGETS, [1, 2, 3])))
        self.assertEqual([r["id"] for r in api.rows[recovery.TARGETS[1]]], [100])
        self.assertEqual([r["id"] for r in api.rows[recovery.TARGETS[2]]], [100])
        execute(api)
        self.assertEqual(len(api.deleted), 3)

    def test_dry_run_is_default_and_never_deletes(self):
        api = FakeAPI()
        recovery.cleanup(api, ENV, emit=lambda _: None)
        self.assertFalse(api.deleted)

    def test_wrong_actor_repository_event_ref_or_workflow_cannot_read_or_delete(self):
        for key in ENV:
            with self.subTest(key=key):
                api = FakeAPI()
                with self.assertRaisesRegex(recovery.CleanupError, key):
                    execute(api, env={**ENV, key: "unauthorized"})
                self.assertFalse(api.deleted)
                self.assertFalse(api.reads)

    def test_all_four_tags_and_all_component_releases_must_be_absent(self):
        self.assertEqual(set(recovery.RELEASES), set(recovery.TAGS))
        paths = [f"/repos/{recovery.REPOSITORY}/{prefix}/{recovery.urllib.parse.quote(tag, safe='')}"
                 for prefix in ("git/ref/tags", "releases/tags") for tag in recovery.TAGS]
        for path in paths:
            with self.subTest(path=path):
                api = FakeAPI()
                api.blocked_path = path
                with self.assertRaisesRegex(recovery.CleanupError, "still exists"):
                    execute(api)
                self.assertFalse(api.deleted)

    def test_official_npm_publication_blocks_all_deletion(self):
        api = FakeAPI()
        api.official = {"version": "1.3.8"}
        with self.assertRaisesRegex(recovery.CleanupError, "official npm"):
            execute(api)
        self.assertFalse(api.deleted)

    def test_new_npm_source_or_integrity_never_deleted(self):
        for update in ({"gitHead": "b" * 40}, {"dist": {"integrity": "sha512-new"}},
                       {"name": "another-package"}, {"version": "1.3.9"}):
            with self.subTest(update=update):
                api = FakeAPI()
                api.metadata.update(update)
                with self.assertRaisesRegex(recovery.CleanupError, "tarball integrity"):
                    execute(api)
                self.assertFalse(api.deleted)

    def test_new_container_digest_or_shared_tag_blocks_entire_plan(self):
        for change in ("digest", "tag"):
            api = FakeAPI()
            row = api.rows[recovery.TARGETS[-1]][0]
            if change == "digest":
                row["name"] = "sha256:" + "f" * 64
            else:
                row["metadata"]["container"]["tags"].append("v1.3.7")
            with self.subTest(change=change), self.assertRaises(recovery.CleanupError):
                execute(api)
            self.assertFalse(api.deleted)

    def test_reads_all_pages_before_deciding_or_deleting(self):
        api = FakeAPI()
        target = recovery.TARGETS[-1]
        old = api.rows[target][0]
        api.rows[target] = [
            {"id": i + 100, "name": "sha256:" + f"{i:064x}",
             "metadata": {"container": {"tags": []}}} for i in range(100)
        ] + [old]
        execute(api, write=False)
        self.assertIn(target.path + "/versions?state=active&per_page=100&page=2", api.reads)
        old["name"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(recovery.CleanupError, "different digest"):
            execute(api)
        self.assertFalse(api.deleted)

    def test_identity_change_between_plan_and_delete_is_rejected(self):
        api = FakeAPI()
        api.detail_override = {"id": 1, "name": "1.3.9"}
        with self.assertRaisesRegex(recovery.CleanupError, "identity changed"):
            execute(api)
        self.assertFalse(api.deleted)

    def test_new_shared_tag_in_final_version_detail_prevents_index_deletion(self):
        api = FakeAPI()
        api.rows[recovery.TARGETS[0]] = []
        row = version(recovery.TARGETS[1], 2)
        row["metadata"]["container"]["tags"].append("latest")
        api.detail_override = row
        with self.assertRaisesRegex(recovery.CleanupError, "unrelated tags"):
            execute(api)
        self.assertFalse(api.deleted)

    def test_new_tag_appearing_after_initial_plan_stops_deletion(self):
        api = FakeAPI()
        original = api.get
        count = 0

        def get(path, **kwargs):
            nonlocal count
            if path == f"/repos/{recovery.REPOSITORY}/git/ref/tags/v1.3.8":
                count += 1
                if count == 2:
                    return {"ref": "refs/tags/v1.3.8"}
            return original(path, **kwargs)

        api.get = get
        with self.assertRaisesRegex(recovery.CleanupError, "tag .* still exists"):
            execute(api)
        self.assertFalse(api.deleted)

    def test_malformed_metadata_and_package_ownership_fail_closed(self):
        for override in (None, {}, {"name": "admin-web", "package_type": "npm", "owner": None}):
            api = FakeAPI()
            original = api.get
            api.get = lambda path, **kw: override if path == recovery.TARGETS[0].path else original(path, **kw)
            with self.subTest(override=override), self.assertRaises(recovery.CleanupError):
                execute(api)
            self.assertFalse(api.deleted)

    def test_absent_rest_version_is_idempotent_despite_cached_registry_metadata(self):
        api = FakeAPI()
        api.rows[recovery.TARGETS[0]] = []
        execute(api)
        self.assertEqual([target for target, _ in api.deleted], list(recovery.TARGETS[1:]))

    def test_github_npm_reads_exact_version_from_scoped_package_metadata(self):
        api = recovery.API("private-test-token")
        value = {"name": "@mss-boot-io/admin-web", "versions": {"1.3.8": FakeAPI().metadata}}
        response = io.BytesIO(json.dumps(value).encode())
        with patch.object(api.opener, "open", return_value=response) as opener:
            self.assertEqual(api.npm(), value["versions"]["1.3.8"])
        self.assertEqual(opener.call_args.args[0].full_url,
                         "https://npm.pkg.github.com/@mss-boot-io%2fadmin-web")

    def test_delete_failure_and_remaining_version_cannot_report_success(self):
        api = FakeAPI()
        api.delete_version = lambda *_: None
        with self.assertRaisesRegex(recovery.CleanupError, "remain visible"):
            execute(api)

    def test_api_never_deletes_a_whole_package_or_sends_token_to_npmjs(self):
        api = recovery.API("private-test-token")
        response = io.BytesIO(b"{}")
        with patch.object(api.opener, "open", return_value=response) as opener:
            api.npm(official=True)
        self.assertIsNone(opener.call_args.args[0].get_header("Authorization"))
        response = io.BytesIO()
        response.status = 204
        with patch.object(api.opener, "open", return_value=response) as opener:
            api.delete_version(recovery.TARGETS[1], 123)
        request = opener.call_args.args[0]
        self.assertEqual(request.method, "DELETE")
        self.assertEqual(request.full_url, "https://api.github.com" + recovery.TARGETS[1].path + "/versions/123")
        for ident in (None, True, 0, "123", "../"):
            with self.subTest(ident=ident), self.assertRaises(recovery.CleanupError):
                api.delete_version(recovery.TARGETS[0], ident)

    def test_http_auth_errors_and_package_404_fail_closed_without_token_leak(self):
        api = recovery.API("private-test-token")
        for status in (401, 403, 404, 500):
            error = urllib.error.HTTPError("url", status, "private-test-token", {}, None)
            with self.subTest(status=status), patch.object(api.opener, "open", side_effect=error):
                with self.assertRaises(recovery.CleanupError) as caught:
                    api.get(recovery.TARGETS[0].path)
                self.assertNotIn("private-test-token", str(caught.exception))
                self.assertIn(f"HTTP {status}", str(caught.exception))
        self.assertIsNone(recovery.NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.invalid"))

    def test_delete_requires_204(self):
        api = recovery.API("private-test-token")
        response = io.BytesIO()
        response.status = 200
        with patch.object(api.opener, "open", return_value=response):
            with self.assertRaisesRegex(recovery.CleanupError, "HTTP 204"):
                api.delete_version(recovery.TARGETS[0], 1)

    def test_workflow_is_manual_main_and_exact_operator_only(self):
        path = Path(__file__).resolve().parents[2] / ".github/workflows/withdraw-failed-v138.yml"
        workflow = yaml.safe_load(path.read_text())
        self.assertEqual(workflow.get("on", workflow.get(True)), {"workflow_dispatch": None})
        self.assertEqual(workflow["permissions"], {})
        job = workflow["jobs"]["withdraw"]
        self.assertEqual(job["permissions"], {"contents": "read", "packages": "write"})
        for guard in ("github.repository == 'mss-boot-io/mss-boot-admin'",
                      "github.ref == 'refs/heads/main'", "github.actor == 'lwnmengjing'",
                      "github.triggering_actor == 'lwnmengjing'"):
            self.assertIn(guard, job["if"])
        self.assertFalse(job["steps"][0]["with"]["persist-credentials"])
        self.assertEqual(job["steps"][1]["run"], "python3 tools/release/withdraw_failed_v138.py --write")


if __name__ == "__main__":
    unittest.main()
