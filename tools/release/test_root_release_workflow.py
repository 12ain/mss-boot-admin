import re
import subprocess
import unittest
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
CONTAINER_WORKFLOW_PATH = (
    REPOSITORY_ROOT / ".github" / "workflows" / "container.yml"
)
GITHUB_EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


class RootReleaseWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.content = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.workflow = yaml.load(self.content, Loader=yaml.BaseLoader)
        self.jobs = self.workflow["jobs"]

    def step(self, job_name, step_name):
        return next(
            step
            for step in self.jobs[job_name]["steps"]
            if step.get("name") == step_name
        )

    @staticmethod
    def bash_array(script, name):
        match = re.search(
            rf"^\s*{re.escape(name)}=\(\n(?P<body>.*?)^\s*\)",
            script,
            flags=re.MULTILINE | re.DOTALL,
        )
        if match is None:
            raise AssertionError(f"missing bash array {name}")
        return tuple(
            line.strip().strip('"').strip("'")
            for line in match.group("body").splitlines()
            if line.strip()
        )

    def test_agent_tool_identity_uses_the_exact_commit_timestamp(self):
        build = self.step("backend-build", "Build Admin runtime and Agent tools")[
            "run"
        ]
        for required in (
            'git show -s --format=%cI "${RELEASE_COMMIT}"',
            "internal/mss/buildinfo.Timestamp=${release_timestamp}",
            'echo "timestamp=${release_timestamp}"',
            "cp AGENTS.md CLAUDE.md LICENSE README.md README.zh-CN.md",
            "for command in mss mss-mcp; do",
            '[[ "${output}" == *"${release_timestamp}"* ]]',
        ):
            self.assertIn(required, build)

    def test_release_checkout_includes_installers_and_validation_tools(self):
        checkout = self.step("assemble", "Checkout release validation tooling")
        sparse_paths = set(checkout["with"]["sparse-checkout"].splitlines())
        self.assertEqual(sparse_paths, {"tools/install", "tools/release"})

    def test_every_tag_candidate_verifies_exact_merged_main_source(self):
        checkout = self.step("release-evidence", "Checkout release source")
        verify = self.step(
            "release-evidence", "Verify merged-main release source"
        )
        self.assertNotIn("if", checkout)
        self.assertNotIn("if", verify)
        self.assertEqual(
            self.jobs["release-evidence"]["if"],
            "needs.metadata.outputs.publish == 'true'",
        )
        script = verify["run"]
        for required in (
            "tools/release/verify_release_source.py",
            '--commit "${RELEASE_COMMIT}"',
            '--tag "${RELEASE_VERSION}"',
            "--policy .mss/release-policy.yaml",
        ):
            self.assertIn(required, script)

    def test_root_tag_builds_and_publishes_without_an_independent_preview(self):
        self.assertEqual(self.workflow['on']['push']['tags'], ['v*.*.*'])
        self.assertNotIn('workflow_dispatch', self.workflow['on'])
        self.assertNotIn('resolve_successful_preview', self.content)
        self.assertEqual(self.workflow['concurrency']['group'], 'root-release-publication')
        self.assertEqual(self.workflow['concurrency']['cancel-in-progress'], 'false')
        gate = self.step('release-evidence', 'Require successful main workflows for this commit')['run']
        for required in ('check_release_runs.py', '--phase main', '--commit "${RELEASE_COMMIT}"', '--version "${RELEASE_VERSION}"'):
            self.assertIn(required, gate)

    def test_root_does_not_repeat_container_build_or_frontend_build(self):
        self.assertNotIn('container-preview', self.jobs)
        self.assertNotIn('frontend-build', self.jobs)
        download = self.step('assemble', 'Reuse the published frontend release assets')['run']
        self.assertIn('gh release download "web/antd-v6/${RELEASE_VERSION}"', download)
        self.assertIn('sha256sum --strict --check SHA256SUMS.frontend-v6', download)
        self.assertIn('sha256sum --strict --check SHA256SUMS.admin-web', download)
        self.assertNotIn('pnpm build', download)

    def test_root_requires_only_exact_public_component_releases(self):
        evidence = self.step(
            "release-evidence", "Require exact component releases"
        )["run"]
        for required in (
            'component_commit="$(resolve_tag_commit',
            '"${component_commit}" != "${RELEASE_COMMIT}"',
            'gh release view "${component_tag}"',
            '.tagName == $tag and .isDraft == false and .isPrerelease == $prerelease',
            "mss-boot/${RELEASE_VERSION}",
            "admin/${RELEASE_VERSION}",
            "web/antd-v6/${RELEASE_VERSION}",
        ):
            self.assertIn(required, evidence)
        for forbidden in (
            "for attempt in $(seq",
            "sleep ",
            "component_train_ready",
            "container.yml",
            "npm-release.yml",
            "gh run watch",
            "gh workflow run",
            "/actions/workflows/",
            ".workflow_runs",
            "framework-release.yml",
            "admin-release.yml",
            "frontend-v6-release.yml",
        ):
            self.assertNotIn(forbidden, evidence)

    def test_assembly_produces_and_qualifies_all_tool_archives(self):
        assemble = self.step("assemble", "Assemble release packages")["run"]
        expected_tools = (
            "mss-tools-${RELEASE_VERSION}-linux-amd64.tar.gz",
            "mss-tools-${RELEASE_VERSION}-linux-arm64.tar.gz",
            "mss-tools-${RELEASE_VERSION}-darwin-amd64.tar.gz",
            "mss-tools-${RELEASE_VERSION}-darwin-arm64.tar.gz",
            "mss-tools-${RELEASE_VERSION}-windows-amd64.zip",
            "mss-tools-${RELEASE_VERSION}-windows-arm64.zip",
        )
        self.assertEqual(self.bash_array(assemble, "tool_assets"), expected_tools)

        for required in (
            'release_timestamp="$(git show -s --format=%cI "${RELEASE_COMMIT}")"',
            'source_date_epoch="$(git show -s --format=%ct "${RELEASE_COMMIT}")"',
            'cmp -- "${reference_build_info}" "${dir}/BUILD-INFO"',
            'cmp -- "${reference_license}" "${dir}/LICENSE"',
            "--sort=name",
            "--owner=0",
            "--group=0",
            "--numeric-owner",
            '--mtime="@${source_date_epoch}"',
            "gzip -n",
            "TZ=UTC zip -X -q",
            "expected_unix_entries=$'BUILD-INFO\\nLICENSE\\nmss\\nmss-mcp'",
            "expected_windows_entries=$'BUILD-INFO\\nLICENSE\\nmss-mcp.exe\\nmss.exe'",
            "python3 tools/release/check_portable_paths.py",
            'install -m 0755 tools/install/install-mss.sh install-mss.sh',
            'install -m 0644 tools/install/install-mss.ps1 install-mss.ps1',
            'grep -Fx "readonly DEFAULT_VERSION=\\"${RELEASE_VERSION}\\"" install-mss.sh',
            'grep -Fx "    [string]\\$Version = \'${RELEASE_VERSION}\'," install-mss.ps1',
            "bash -n install-mss.sh",
            'tar -xzf "mss-tools-${RELEASE_VERSION}-linux-amd64.tar.gz"',
            'output="$("${smoke_dir}/tools/${command}" --version)"',
            '[[ "${output}" == *"${RELEASE_VERSION}"* ]]',
            '[[ "${output}" == *"${RELEASE_COMMIT}"* ]]',
            '[[ "${output}" == *"${release_timestamp}"* ]]',
            '"${smoke_dir}/tools/mss" new app release-smoke',
            '--destination "${smoke_dir}/release-smoke"',
            "'.success == true and .dryRun == false'",
            'test -f "${smoke_dir}/release-smoke/go.sum"',
            'test -f "${smoke_dir}/release-smoke/web/pnpm-lock.yaml"',
            'admin_web_package_dir="frontend-v6-dist/admin-web-release-package"',
            'sha256sum --check SHA256SUMS.admin-web',
            'admin_web_package="${admin_web_packages[0]}"',
            'registry_pid=""',
            'kill "${registry_pid}"',
            'wait "${registry_pid}"',
            'sha512(tarball.read_bytes()).digest()',
            'ThreadingHTTPServer(("127.0.0.1", 0), Handler)',
            '--contributor-npm-registry "${registry_url}"',
            'sha256sum "${tool_assets[@]}" install-mss.sh install-mss.ps1',
            '[[ "$(wc -l < "SHA256SUMS.tools-${RELEASE_VERSION}")" -eq 8 ]]',
            'sha256sum --check "SHA256SUMS.tools-${RELEASE_VERSION}"',
        ):
            self.assertIn(required, assemble)

        upload_step = self.step("assemble", "Upload assembled packages")
        upload = upload_step["with"]["path"]
        self.assertEqual(upload_step["with"]["retention-days"], "30")
        for expected in (
            "mss-boot-admin-*.zip",
            "SHA256SUMS",
            "mss-tools-*.tar.gz",
            "mss-tools-*.zip",
            "SHA256SUMS.tools-*",
            "install-mss.sh",
            "install-mss.ps1",
        ):
            self.assertIn(expected, upload.splitlines())

    def test_assembly_smokes_exact_admin_web_package_without_public_npm(self):
        assemble = self.step("assemble", "Assemble release packages")["run"]
        smoke = assemble.split('smoke_dir="$(mktemp -d)"', 1)[1]
        self.assertIn('package_name = "@mss-boot-io/admin-web"', smoke)
        self.assertIn('"integrity": integrity', smoke)
        self.assertIn('--contributor-npm-registry "${registry_url}"', smoke)
        self.assertNotIn("registry.npmjs.org", smoke)

    def test_public_release_asset_set_is_exact_and_has_no_retired_tools(self):
        publish = self.step(
            "publish", "Stage, verify, and publish GitHub release atomically"
        )["run"]
        expected_assets = (
            "mss-boot-admin-linux-amd64.zip",
            "mss-boot-admin-linux-arm64.zip",
            "mss-boot-admin-darwin-amd64.zip",
            "mss-boot-admin-darwin-arm64.zip",
            "mss-boot-admin-windows-amd64.zip",
            "mss-boot-admin-windows-arm64.zip",
            "SHA256SUMS",
            "mss-tools-${RELEASE_VERSION}-linux-amd64.tar.gz",
            "mss-tools-${RELEASE_VERSION}-linux-arm64.tar.gz",
            "mss-tools-${RELEASE_VERSION}-darwin-amd64.tar.gz",
            "mss-tools-${RELEASE_VERSION}-darwin-arm64.tar.gz",
            "mss-tools-${RELEASE_VERSION}-windows-amd64.zip",
            "mss-tools-${RELEASE_VERSION}-windows-arm64.zip",
            "SHA256SUMS.tools-${RELEASE_VERSION}",
            "install-mss.sh",
            "install-mss.ps1",
        )
        assets = self.bash_array(publish, "assets")
        self.assertEqual(assets, expected_assets)
        self.assertNotIn("admin", assets)
        self.assertFalse(any("mss-pr" in asset for asset in assets))
        self.assertNotIn("mss-pr", self.content)
        self.assertIn('sha256sum --check "SHA256SUMS.tools-${RELEASE_VERSION}"', publish)
        for required in (
            "verify_release_assets()",
            '.isDraft == false and .isPrerelease == $prerelease',
            "is already public with the exact tag assets",
            "exit 0",
            '--latest=false',
        ):
            self.assertIn(required, publish)
        self.assertNotIn('current_latest="$(gh api', publish)
        self.assertNotIn('sort -V | tail -n 1', publish)
        self.assertNotIn("is already public; refusing to mutate it", publish)

    def test_release_notes_are_package_first(self):
        notes = self.step("publish", "Prepare deterministic root release notes")["run"]
        for required in (
            "## Package-first runtime and tools",
            "install-mss.sh",
            "install-mss.ps1",
            "SHA256SUMS.tools-*",
            "versioned Foundation Blueprint embedded in the installed tool",
            "without a Foundation source checkout",
            "## Migration",
            "mss_boot_presentation_profiles",
            "mss_boot_presentation_revisions",
            "admin migrate",
            "admin server -a",
            "v1.3.3 through v1.3.6",
            "20260824121000",
            "20260830193000",
            "intentionally fails closed",
            "leaves its version pending",
            "restorable pre-upgrade backup",
            "docs/adr/2026-08-24-admin-presentation-publication-workflow.md",
            "mss_boot_menus",
            "mss_boot_casbin_rule",
            "Do not insert the attestation merely because current values look canonical",
            "only after the documented recovery review",
            "--password",
            "-p",
            "## Compatibility",
            "fourteen Foundation built-in management page capabilities",
            "exact startup allowlist",
            "## Security",
            "data-only",
            "Backend RBAC remains authoritative",
            "## Rollback",
            "presentation.recoveryMode",
            "one previously qualified coordinated Admin Distribution",
            "matching Framework, Admin, frontend, configuration, and lock",
            "Keep the live forward-compatible database schema and data",
            "full database-backup restore is disaster recovery only",
            "discards every write after the backup time",
            "post-backup audit and business data outside the target database",
            "## Known limits",
            "six accepted non-runtime advisories",
            "2026-11-08",
            "not a zero-vulnerability claim",
        ):
            self.assertIn(required, notes)
        for forbidden in (
            "must run from a checked-out Foundation source tree",
            "must clone",
            "mss-pr",
            "zero vulnerabilities",
            "current stable distribution",
            "production capability registration remains empty",
            "matching v1.3.2",
        ):
            self.assertNotIn(forbidden, notes)

    def test_tag_builds_once_and_publishes_same_run_artifacts(self):
        for name in ('backend-build', 'assemble'):
            self.assertNotIn('if', self.jobs[name])
            self.assertNotIn('environment', self.jobs[name])
        self.assertEqual(self.jobs['backend-build']['needs'], ['metadata', 'release-evidence'])
        self.assertEqual(self.jobs['assemble']['needs'], ['metadata', 'backend-build', 'release-evidence'])
        self.assertEqual(self.jobs['publish']['needs'], ['metadata', 'release-evidence', 'assemble'])
        download = self.step('publish', 'Download assembled packages from this tag run')['with']
        self.assertNotIn('run-id', download)
        self.assertNotIn('repository', download)
        self.assertEqual(download['name'], 'release-packages-${{ needs.metadata.outputs.version }}')
        self.assertEqual(self.jobs['publish']['environment'], 'release-auto')
        for forbidden in ('go test ./...', 'pnpm run test:ci', 'playwright install', 'mss verify --all', 'resolve_successful_preview.sh'):
            self.assertNotIn(forbidden, self.content)

    def test_all_run_blocks_are_valid_bash(self):
        for job_name, job in self.jobs.items():
            for index, step in enumerate(job.get("steps", [])):
                script = step.get("run")
                if script is None:
                    continue
                sanitized = GITHUB_EXPRESSION.sub("gha_expression", script)
                result = subprocess.run(
                    ["bash", "-n"],
                    input=sanitized,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    msg=(
                        f"invalid bash in job {job_name} step {index} "
                        f"({step.get('name', 'unnamed')}): {result.stderr}"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
