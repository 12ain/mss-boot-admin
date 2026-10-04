import importlib.util
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


MODULE_PATH = Path(__file__).with_name("check_release_policy.py")
SPEC = importlib.util.spec_from_file_location("check_release_policy", MODULE_PATH)
assert SPEC and SPEC.loader
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPOSITORY_ROOT / ".mss" / "release-policy.yaml"
GITHUB_EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


class ReleasePolicyTest(unittest.TestCase):
    def setUp(self):
        self.policy = POLICY.load_policy(POLICY_PATH)

    def test_candidate_and_stable_are_distinct_and_stopped_trains_stay_frozen(self):
        self.assertEqual(self.policy['nextPublicVersion'], 'v1.3.8')
        self.assertEqual(self.policy['distributionVersion'], 'v1.3.8')
        self.assertEqual(self.policy['currentStableVersion'], 'v1.3.7')
        self.assertEqual(self.policy['currentStableCommit'], '77b53d41092741eac62fa6418c0bdbf87413c7cd')
        self.assertEqual(self.policy['releaseTargetState'], 'active')
        self.assertEqual(POLICY.immutable_stopped_trains(self.policy), POLICY.PERMANENTLY_STOPPED_TRAINS)
        for version, train in POLICY.PERMANENTLY_STOPPED_TRAINS.items():
            for component, ref in train['refs'].items():
                for intent in ('qualify', 'publish', 'promote'):
                    with self.subTest(version=version, component=component, intent=intent):
                        with self.assertRaisesRegex(POLICY.PolicyError, 'immutable stopped train'):
                            POLICY.check_public_ref(self.policy, component, version, ref, intent=intent)

    def test_current_candidate_and_independent_stable_docs_refs(self):
        self.assertTrue(self.policy['publicationWorkflowsReady'])
        self.assertFalse(self.policy['publicPrereleases'])
        for component in POLICY.COMPONENT_TEMPLATE_KEYS:
            version = self.policy['currentStableVersion'] if component == 'docs' else self.policy['nextPublicVersion']
            ref = POLICY.release_ref(self.policy, component, version)
            for intent in ('qualify', 'publish'):
                POLICY.check_public_ref(self.policy, component, version, ref, intent=intent)
        for wrong in ('v1.3.7', 'v1.3.9', 'v1.3.8-rc.1'):
            with self.assertRaises(POLICY.PolicyError):
                POLICY.check_public_ref(self.policy, 'root', wrong, wrong)
        with self.assertRaises(POLICY.PolicyError):
            POLICY.check_public_ref(self.policy, 'docs', 'v1.3.8', 'docs/v1.3.8')

    def test_publication_switch_is_fail_closed_but_docs_is_independent(self):
        disabled = dict(self.policy, publicationWorkflowsReady=False)
        POLICY.check_public_ref(disabled, 'root', 'v1.3.8', 'v1.3.8', intent='qualify')
        with self.assertRaisesRegex(POLICY.PolicyError, 'remain disabled'):
            POLICY.check_public_ref(disabled, 'root', 'v1.3.8', 'v1.3.8')
        POLICY.check_public_ref(disabled, 'docs', 'v1.3.7', 'docs/v1.3.7')

    def test_legacy_promotion_fields_remain_disabled_and_do_not_gate_npm_publish(self):
        self.assertFalse(self.policy['stablePromotionReady'])
        self.assertEqual(self.policy['stablePromotionVersion'], 'v1.3.8')
        self.assertEqual(self.policy['stablePromotionCommit'], 'disabled')
        POLICY.check_public_ref(self.policy, 'npm', 'v1.3.8', '@mss-boot-io/admin-web@1.3.8', intent='publish')
        with self.assertRaisesRegex(POLICY.PolicyError, 'promotion remains disabled'):
            POLICY.check_public_ref(self.policy, 'npm', 'v1.3.8', '@mss-boot-io/admin-web@1.3.8', intent='promote', commit='a'*40)
        legacy = dict(self.policy, stablePromotionReady=True, stablePromotionCommit='a'*40)
        POLICY.check_public_ref(legacy, 'npm', 'v1.3.8', '@mss-boot-io/admin-web@1.3.8', intent='promote', commit='a'*40)
        with self.assertRaisesRegex(POLICY.PolicyError, 'exact release commit'):
            POLICY.check_public_ref(legacy, 'npm', 'v1.3.8', '@mss-boot-io/admin-web@1.3.8', intent='promote', commit='b'*40)
        legacy['currentStableVersion'] = 'v1.3.8'
        with self.assertRaisesRegex(POLICY.PolicyError, 'already consumed'):
            POLICY.check_public_ref(legacy, 'npm', 'v1.3.8', '@mss-boot-io/admin-web@1.3.8', intent='promote', commit='a'*40)

    def test_admin_framework_dependency_matches_candidate_without_local_replace(self):
        version = self.policy['nextPublicVersion']
        module = 'github.com/mss-boot-io/mss-boot-admin/mss-boot'
        admin = (REPOSITORY_ROOT / 'admin/go.mod').read_text()
        self.assertIn(f'{module} {version}', admin)
        self.assertNotIn(f'replace {module}', admin)
        self.assertIn(f'replace {module} {version} => ./mss-boot', (REPOSITORY_ROOT / 'go.work').read_text())
        lines = [line for line in (REPOSITORY_ROOT / 'admin/go.sum').read_text().splitlines() if line.startswith(f'{module} {version}')]
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.split()[-1].startswith('h1:') for line in lines))

    def test_parser_rejects_invalid_or_weakened_policy(self):
        original = POLICY_PATH.read_text()
        changes = (
            ('  distributionVersion: v1.3.8', '  distributionVersion: v1.3.9'),
            ('  releaseBranch: main', '  releaseBranch: topic'),
            ('  requireMergedPullRequestSource: true', '  requireMergedPullRequestSource: false'),
            ('  docsTagMutable: true', '  docsTagMutable: false'),
            ('  docsTagMutable: true\n', ''),
            ('  publicPrereleases: false', '  publicPrereleases: true'),
            ('  currentStableVersion: v1.3.7', '  currentStableVersion: v1.3.7-rc.1'),
            ('  releaseTargetState: active', '  releaseTargetState: stopped'),
            ('stablePromotionVersion: v1.3.8', 'stablePromotionVersion: v1.3.9'),
            ('stablePromotionCommit: disabled', 'stablePromotionCommit: '+ 'a'*40),
            ('currentStableCommit: 77b53d41092741eac62fa6418c0bdbf87413c7cd', 'currentStableCommit: short'),
            ('commit: 396f60615cdfa589353b16ef9d3531e249e65432', 'commit: '+ 'a'*40),
            ('        docs: docs/v1.3.5\n', ''),
            ('        framework: mss-boot/v1.3.6', '        framework: mss-boot/v1.3.5'),
            ('  nextPublicVersion: v1.3.8', '  nextPublicVersion: v01.3.8'),
            ('  distributionComponents: "root,framework,admin,frontend"', '  distributionComponents: "root,frontend"'),
        )
        malformed = []
        for before, after in changes:
            self.assertIn(before, original)
            malformed.append(original.replace(before, after))
        malformed += [original + '  unexpected: true\n', original + '  nextPublicVersion: v1.3.8\n']
        for content in malformed:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                candidate = Path(directory) / 'policy.yaml'
                candidate.write_text(content)
                with self.assertRaises(POLICY.PolicyError):
                    POLICY.load_policy(candidate)

    def test_wrong_ref_namespace_and_noncanonical_versions_fail(self):
        for component, version, ref in (
            ('root', 'v1.3.8', 'admin/v1.3.8'),
            ('framework', 'v1.3.8', 'v1.3.8'),
            ('docs', 'v1.3.7', 'docs/v1.3.8'),
            ('root', 'v1.3.8+docs.1', 'v1.3.8+docs.1'),
            ('root', 'v1.3.8-rc.01', 'v1.3.8-rc.01'),
        ):
            with self.subTest(ref=ref), self.assertRaises(POLICY.PolicyError):
                POLICY.check_public_ref(self.policy, component, version, ref)

    def test_publication_workflows_share_policy_without_readiness_run_gates(self):
        workflows = (
            "release.yml",
            "framework-release.yml",
            "admin-release.yml",
            "frontend-v6-release.yml",
            "container.yml",
        )
        for workflow in workflows:
            with self.subTest(workflow=workflow):
                content = (
                    REPOSITORY_ROOT / ".github" / "workflows" / workflow
                ).read_text(encoding="utf-8")
                self.assertIn("check_release_policy.py", content)
                self.assertNotIn("verify_readiness_run.sh", content)
                self.assertNotIn("RELEASE_READINESS_RUN_ID", content)
                self.assertNotIn("readiness_run_id", content)

    def test_current_release_contract_reuses_main_and_tag_workflows(self):
        skill = (REPOSITORY_ROOT / '.agents/skills/mss-release/SKILL.md').read_text()
        self.assertIn('check_release_runs.py', skill)
        self.assertIn('mss verify --changed', skill)
        self.assertIn('optional diagnostic', skill)
        self.assertNotIn('gh workflow run release.yml', skill)
        for filename in ('release.yml', 'framework-release.yml', 'admin-release.yml', 'frontend-v6-release.yml', 'container.yml', 'npm-release.yml'):
            content = (REPOSITORY_ROOT / '.github/workflows' / filename).read_text()
            for obsolete in ('resolve_successful_preview.sh', 'mss verify --all', 'make test-all', 'go test ./...', 'playwright test'):
                self.assertNotIn(obsolete, content, filename)
        npm = (REPOSITORY_ROOT / '.github/workflows/npm-release.yml').read_text()
        self.assertIn('check_release_runs.py', npm)
        self.assertNotIn('--intent promote', npm)
        self.assertNotIn('stablePromotionReady', npm)


    def test_release_workflows_require_pr_merged_main_source_and_exact_tag(self):
        cases = {
            "release.yml": ("release-evidence", True),
            "framework-release.yml": ("release", True),
            "admin-release.yml": ("release", True),
            "frontend-v6-release.yml": ("release", True),
            "container.yml": ("publish", True),
            "docs.yml": ("build", True),
            "npm-release.yml": ("gate", True),
        }
        for workflow_name, (job_name, requires_tag) in cases.items():
            with self.subTest(workflow=workflow_name):
                content = (
                    REPOSITORY_ROOT / ".github" / "workflows" / workflow_name
                ).read_text(encoding="utf-8")
                workflow = yaml.load(content, Loader=yaml.BaseLoader)
                job = workflow["jobs"][job_name]
                permissions = job.get("permissions", workflow.get("permissions", {}))
                self.assertEqual(permissions.get("pull-requests"), "read")
                guard_index, guard = next(
                    (index, step)
                    for index, step in enumerate(job["steps"])
                    if step.get("name") == "Verify merged-main release source"
                )
                self.assertIn("verify_release_source.py", guard["run"])
                if requires_tag:
                    self.assertIn("--tag", guard["run"])
                else:
                    self.assertNotIn("--tag", guard["run"])
                self.assertLess(guard_index, len(job["steps"]) - 1)

        root_release = yaml.load(
            (
                REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
            ).read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        self.assertIn(
            "release-evidence", root_release["jobs"]["publish"]["needs"]
        )

    def test_release_workflow_yaml_and_run_blocks_are_valid(self):
        workflows = (
            "release.yml",
            "framework-release.yml",
            "admin-release.yml",
            "admin-distribution-compatibility.yml",
            "frontend-v6-release.yml",
            "frontend-v6-ci.yml",
            "container.yml",
            "docs.yml",
            "npm-release.yml",
        )
        for workflow_name in workflows:
            with self.subTest(workflow=workflow_name):
                content = (
                    REPOSITORY_ROOT / ".github" / "workflows" / workflow_name
                ).read_text(encoding="utf-8")
                workflow = yaml.load(content, Loader=yaml.BaseLoader)
                self.assertIsInstance(workflow.get("jobs"), dict)
                for job in workflow["jobs"].values():
                    for step in job.get("steps", []):
                        script = step.get("run")
                        if script is None:
                            continue
                        result = subprocess.run(
                            ["bash", "-n"],
                            input=GITHUB_EXPRESSION.sub("gha_expression", script),
                            text=True,
                            capture_output=True,
                            check=False,
                        )
                        self.assertEqual(
                            result.returncode,
                            0,
                            msg=(
                                f"invalid bash in {workflow_name} step "
                                f"{step.get('name')}: {result.stderr}"
                            ),
                        )

    def test_frontend_tag_build_upload_is_portable_and_published_in_same_run(self):
        workflow = yaml.load((REPOSITORY_ROOT / '.github/workflows/frontend-v6-release.yml').read_text(), Loader=yaml.BaseLoader)
        build = workflow['jobs']['build']['steps']
        package = next(step for step in build if step.get('name') == 'Package and verify portable primary V6 artifact')
        for required in ('--sort=name', '--file dist-v6.tar.gz', 'sha256sum --check SHA256SUMS.frontend-v6', 'check_portable_paths.py'):
            self.assertIn(required, package['run'])
        upload = next(step for step in build if step.get('name') == 'Upload primary V6 artifact')
        self.assertEqual(upload['with']['name'], 'frontend-v6-dist')
        self.assertNotIn('web/antd-v6/dist/', upload['with']['path'].splitlines())
        release = workflow['jobs']['release']
        self.assertEqual(release['needs'], 'build')
        download = next(step for step in release['steps'] if step.get('uses', '').startswith('actions/download-artifact@'))
        self.assertEqual(download['with']['name'], 'frontend-v6-dist')
        for cross_run in ('run-id', 'repository', 'github-token'):
            self.assertNotIn(cross_run, download['with'])
        stage = next(step for step in release['steps'] if step.get('name') == 'Verify and stage the exact tagged Frontend artifacts')['run']
        for checksum in ('SHA256SUMS.frontend-v6', 'SHA256SUMS.admin-web', 'SHA256SUMS.frontend-v6-image'):
            self.assertIn('sha256sum --check '+checksum, stage)


    def test_all_raw_directory_uploads_have_portability_guards(self):
        extensionless_files = {
            "FRONTEND-V6-BUILD-INFO",
            "FRONTEND-V6-IMAGE-INFO",
            "SHA256SUMS",
        }
        raw_uploads = []
        for workflow_path in sorted(
            (REPOSITORY_ROOT / ".github" / "workflows").glob("*.yml")
        ):
            workflow = yaml.load(
                workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
            )
            for job_name, job in workflow.get("jobs", {}).items():
                steps = job.get("steps", [])
                for upload_index, step in enumerate(steps):
                    if "actions/upload-artifact@" not in step.get("uses", ""):
                        continue
                    paths = [
                        line.strip()
                        for line in step.get("with", {}).get("path", "").splitlines()
                        if line.strip()
                    ]
                    for upload_path in paths:
                        basename = upload_path.rsplit("/", 1)[-1]
                        portable_basename = GITHUB_EXPRESSION.sub(
                            "expression", basename
                        )
                        is_file = (
                            "." in portable_basename
                            or portable_basename in extensionless_files
                            or portable_basename.startswith("SHA256SUMS")
                        )
                        if is_file:
                            continue
                        guard = next(
                            (
                                previous
                                for previous in reversed(steps[:upload_index])
                                if "check_portable_paths.py" in previous.get("run", "")
                            ),
                            None,
                        )
                        self.assertIsNotNone(
                            guard,
                            msg=(
                                f"{workflow_path.name}:{job_name}:{step.get('name')} "
                                f"uploads raw directory {upload_path} without a portability guard"
                            ),
                        )
                        self.assertIn(basename, guard["run"])
                        raw_uploads.append(
                            (workflow_path.name, job_name, upload_path)
                        )

        self.assertEqual(
            raw_uploads,
            [
                (
                    "frontend-v6-ci.yml",
                    "browser",
                    "web/antd-v6/playwright-report",
                ),
                ("frontend-v6-ci.yml", "browser", "web/antd-v6/test-results"),
                (
                    "release.yml",
                    "backend-build",
                    "mss-boot-admin-${{ matrix.os }}-${{ matrix.arch }}",
                ),
            ],
        )

    def test_root_release_validates_extracted_frontend_and_every_final_zip(self):
        content = (
            REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text(encoding="utf-8")
        workflow = yaml.load(content, Loader=yaml.BaseLoader)
        assemble = next(
            step
            for step in workflow["jobs"]["assemble"]["steps"]
            if step.get("name") == "Assemble release packages"
        )
        script = assemble["run"]
        self.assertIn("sha256sum --check SHA256SUMS.frontend-v6", script)
        self.assertIn("frontend-v6-extracted/dist", script)
        self.assertIn(
            "check_portable_paths.py mss-boot-admin-*.zip", script
        )

    def test_static_release_builds_normalize_dynamic_route_placeholders(self):
        frontend_package = (
            REPOSITORY_ROOT / "web" / "antd-v6" / "package.json"
        ).read_text(encoding="utf-8")
        docs_package = (REPOSITORY_ROOT / "docs" / "package.json").read_text(
            encoding="utf-8"
        )
        self.assertIn("prepare_portable_frontend.py dist", frontend_package)
        self.assertIn(
            "prepare_portable_frontend.py dist --markdown-root docs", docs_package
        )

    def test_manual_frontend_qualification_and_docs_cover_portability_tooling(self):
        frontend_content = (
            REPOSITORY_ROOT / ".github" / "workflows" / "frontend-v6-ci.yml"
        ).read_text(encoding="utf-8")
        frontend = yaml.load(frontend_content, Loader=yaml.BaseLoader)
        self.assertEqual(set(frontend["on"]), {"workflow_dispatch"})
        compile_steps = frontend["jobs"]["compile"]["steps"]
        self.assertTrue(
            any(step.get("run") == "pnpm run build:release" for step in compile_steps)
        )

        docs_content = (
            REPOSITORY_ROOT / ".github" / "workflows" / "docs.yml"
        ).read_text(encoding="utf-8")
        docs = yaml.load(docs_content, Loader=yaml.BaseLoader)
        self.assertNotIn("pull_request", docs["on"])
        self.assertIn("tools/release/**", docs["on"]["push"]["paths"])

    def test_docs_release_is_component_scoped_and_merged_main_only(self):
        content = (
            REPOSITORY_ROOT / ".github" / "workflows" / "docs.yml"
        ).read_text(encoding="utf-8")
        workflow = yaml.load(content, Loader=yaml.BaseLoader)
        build_steps = workflow["jobs"]["build"]["steps"]
        deployment = workflow["jobs"]["deployment"]

        self.assertIn("docs/v*.*.*", content)
        self.assertIn("refs/tags/docs/v", deployment["if"])
        self.assertNotIn("refs/heads/main", deployment["if"])
        self.assertTrue(
            any(
                "verify_release_source.py" in step.get("run", "")
                and "--tag" in step.get("run", "")
                for step in build_steps
            )
        )
        self.assertTrue(
            any(
                "check_release_policy.py" in step.get("run", "")
                and "--component docs" in step.get("run", "")
                and "--commit" in step.get("run", "")
                for step in build_steps
            )
        )
        source = next(
            step
            for step in build_steps
            if step.get("name") == "Verify merged-main release source"
        )["run"]
        self.assertIn("--source-mode", source)
        policy = next(
            step
            for step in build_steps
            if step.get("name") == "Enforce reviewed docs release target"
        )["run"]
        self.assertIn("--policy ../.mss/release-policy.yaml", policy)
        self.assertIn("--source-mode docs", source)
        for required in (
            "dist/release.json",
            "DOCS-BUILD-INFO.txt",
            "SHA256SUMS.docs",
            "gh release create",
            "https://docs.mss-boot-io.top/release.json",
        ):
            self.assertIn(required, content)

    def test_local_browser_qualification_cannot_reuse_the_development_server(self):
        playwright = (
            REPOSITORY_ROOT / "web" / "antd-v6" / "playwright.config.ts"
        ).read_text(encoding="utf-8")
        runner = (
            REPOSITORY_ROOT / "tools" / "verification" / "run-frontend-e2e.sh"
        ).read_text(encoding="utf-8")
        package = (
            REPOSITORY_ROOT / "web" / "antd-v6" / "package.json"
        ).read_text(encoding="utf-8")
        support = (
            REPOSITORY_ROOT / "web" / "antd-v6" / "e2e" / "support" / "session.ts"
        ).read_text(encoding="utf-8")
        backend = (
            REPOSITORY_ROOT
            / "web"
            / "antd-v6"
            / "scripts"
            / "start-e2e-backend.sh"
        ).read_text(encoding="utf-8")
        e2e_config = (
            REPOSITORY_ROOT / "admin" / "config" / "application-e2e.yml"
        ).read_text(encoding="utf-8")
        package_business_config = (
            REPOSITORY_ROOT / "web" / "antd-v6" / "package" / "business.cjs"
        ).read_text(encoding="utf-8")
        generated_supplier = (
            REPOSITORY_ROOT
            / "web"
            / "antd-v6"
            / "e2e"
            / "generated"
            / "supplier.spec.ts"
        ).read_text(encoding="utf-8")
        supplier_template = (
            REPOSITORY_ROOT
            / "templates"
            / "module"
            / "frontend-v6"
            / "e2e.spec.ts.tmpl"
        ).read_text(encoding="utf-8")

        self.assertNotIn("reuseExistingServer: !process.env.CI", playwright)
        self.assertEqual(playwright.count("reuseExistingServer: false"), 2)
        self.assertIn("http://127.0.0.1:18001", playwright)
        for required in (
            "MSS_V6_BACKEND_ORIGIN",
            "MSS_V6_BACKEND_PORT",
            "MSS_V6_WEB_PORT",
            "qualificationBackendOrigin",
            "qualificationWebPort",
            "corepack pnpm@10.34.5 exec max dev",
        ):
            self.assertIn(required, playwright)
        for required in (
            "flock -w 600",
            "current.bind(('127.0.0.1', 0))",
            'export MSS_V6_BACKEND_ORIGIN="http://127.0.0.1:${backend_port}"',
            'export MSS_V6_BASE_URL="http://127.0.0.1:${web_port}"',
            'export MSS_E2E_BACKEND_API_URL="${MSS_V6_BACKEND_ORIGIN}/admin/api"',
            'export MSS_V6_E2E_EVIDENCE_ROOT="${evidence_root}"',
            "corepack pnpm@10.34.5 run test:e2e",
        ):
            self.assertIn(required, runner)
        self.assertNotIn("exec playwright test", runner)
        self.assertLess(
            runner.index("playwright install chromium"),
            runner.index("read -r backend_port web_port"),
        )
        for required in (
            "MSS_V6_BACKEND_PORT",
            "MSS_V6_WEB_PORT",
            '"${runtime_dir}/config/application.yml"',
            '"${runtime_dir}/config/application-e2e.yml"',
            "MSS_V6_E2E_RUN_ID",
            'case "${run_root}/" in',
            '"${repo_dir}/.mss/run/"*)',
            'run_dir="$(realpath -m "${run_root}/${run_id}")"',
        ):
            self.assertIn(required, backend)
        self.assertIn('"start:e2e"', package)
        self.assertIn("MSS_V6_E2E=1", package)
        for required in (
            'MSS_V6_E2E_RUN_ID=baseline playwright test --grep-invert @presentation',
            'MSS_V6_E2E_RUN_ID=presentation playwright test --grep @presentation',
        ):
            self.assertIn(required, package)
        for required in (
            "MSS_V6_E2E_EVIDENCE_ROOT",
            "MSS_V6_E2E_RUN_ID",
            "outputDir",
            "outputFolder",
        ):
            self.assertIn(required, playwright)
        self.assertIn(
            "persistentCaching: !browserQualification", package_business_config
        )
        for content in (
            support,
            backend,
            e2e_config,
            generated_supplier,
            supplier_template,
        ):
            self.assertIn("18001", content)
        for content in (support, backend, generated_supplier, supplier_template):
            self.assertNotIn("http://127.0.0.1:8001", content)
        for content in (generated_supplier, supplier_template):
            self.assertIn("const authorizedMenu = page.waitForResponse", content)
            self.assertIn("{ timeout: 20_000 }", content)
            self.assertIn("toBeVisible({ timeout: 15_000 })", content)

    def test_e2e_backend_rejects_a_symlinked_run_root_outside_the_repository(self):
        source = (
            REPOSITORY_ROOT
            / "web"
            / "antd-v6"
            / "scripts"
            / "start-e2e-backend.sh"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            script = repository / "web" / "antd-v6" / "scripts" / source.name
            script.parent.mkdir(parents=True)
            script.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            run_parent = repository / ".mss" / "run"
            run_parent.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            (run_parent / "antd-v6-e2e").symlink_to(
                outside, target_is_directory=True
            )

            result = subprocess.run(
                ["bash", str(script)],
                cwd=repository,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "Refusing to use an E2E run root outside the repository",
            result.stderr,
        )

    def test_root_is_tag_driven_without_a_separate_preview(self):
        content = (REPOSITORY_ROOT / '.github/workflows/release.yml').read_text()
        workflow = yaml.load(content, Loader=yaml.BaseLoader)
        self.assertNotIn('workflow_dispatch', workflow['on'])
        self.assertEqual(workflow['on']['push']['tags'], ['v*.*.*'])
        self.assertNotIn('resolve_successful_preview.sh', content)
        self.assertNotIn('inputs.publish', content)
        for obsolete in ('release-readiness.yml', 'root-tag-promotion.yml'):
            self.assertFalse((REPOSITORY_ROOT / '.github/workflows' / obsolete).exists())


    def test_development_push_does_not_publish_a_checkpoint_image(self):
        content = (
            REPOSITORY_ROOT / ".github" / "workflows" / "container.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn(
            '[[ "${GITHUB_EVENT_NAME}" == "push" ]]',
            content,
        )
        self.assertNotIn("verify_readiness_run.sh", content)
        self.assertNotIn("inputs.publish", content)

    def test_retired_release_evidence_helpers_are_absent(self):
        for relative_path in (
            "tools/release/verify_readiness_run.sh",
            "tools/release/release_readiness_attestation.py",
            "tools/release/release_phase_evidence.py",
            "tools/release/release_qualification_decision.py",
        ):
            with self.subTest(path=relative_path):
                self.assertFalse((REPOSITORY_ROOT / relative_path).exists())

    def test_root_release_has_no_published_version_default(self):
        content = (
            REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("default: v1.0.0", content)


if __name__ == "__main__":
    unittest.main()
