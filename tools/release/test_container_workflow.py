import hashlib
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "container.yml"
DOCKERFILE_PATH = REPOSITORY_ROOT / "Dockerfile"
GITHUB_EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


class ContainerWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.content = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
        self.workflow = yaml.load(self.content, Loader=yaml.BaseLoader)
        self.jobs = self.workflow["jobs"]

    def test_multi_platform_go_build_cross_compiles_on_the_native_builder(self):
        self.assertIn("FROM --platform=$BUILDPLATFORM golang:", self.dockerfile)
        self.assertIn("ARG TARGETOS", self.dockerfile)
        self.assertIn("ARG TARGETARCH", self.dockerfile)
        self.assertIn(
            "CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build",
            self.dockerfile,
        )

        publish_timeout = int(self.jobs["publish"]["timeout-minutes"])
        self.assertGreaterEqual(publish_timeout, 75)

    def test_publish_authority_is_confined_to_the_release_job(self):
        self.assertNotIn("packages", self.workflow["permissions"])

        package_writers = [
            name
            for name, job in self.jobs.items()
            if job.get("permissions", {}).get("packages") == "write"
        ]
        self.assertEqual(package_writers, ["publish"])

        release_jobs = [
            name
            for name, job in self.jobs.items()
            if job.get("environment") == "release-auto"
        ]
        self.assertEqual(release_jobs, ["publish"])
        self.assertNotIn("environment", self.jobs["build"])

        registry_logins = [
            name
            for name, job in self.jobs.items()
            if any(
                step.get("uses", "").startswith("docker/login-action@")
                for step in job.get("steps", [])
            )
        ]
        image_pushers = [
            name
            for name, job in self.jobs.items()
            if any(
                step.get("uses", "").startswith("docker/build-push-action@")
                and step.get("with", {}).get("push") == "true"
                for step in job.get("steps", [])
            )
        ]
        self.assertEqual(registry_logins, ["publish"])
        self.assertEqual(image_pushers, [])

    def test_publish_job_requires_an_exact_tag_publication_request(self):
        condition = " ".join(self.jobs["publish"]["if"].split())
        self.assertEqual(
            condition,
            "${{ needs.build.outputs.publish == 'true' && "
            "github.event_name == 'push' && "
            "github.ref_type == 'tag' && "
            "github.ref_name == needs.build.outputs.version }}",
        )
        self.assertNotIn("workflow_dispatch", self.workflow["on"])
        self.assertNotIn("workflow_call", self.workflow["on"])
        self.assertNotIn("resolve_successful_preview", self.content)

    def test_root_tag_container_run_does_not_share_the_root_release_lock(self):
        self.assertEqual(
            self.workflow["concurrency"]["group"],
            "container-${{ github.ref }}",
        )
        self.assertEqual(
            self.workflow["concurrency"]["cancel-in-progress"],
            "${{ !startsWith(github.ref, 'refs/tags/') }}",
        )
        root_content = (
            REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("foundation-release-${{ github.ref }}", root_content)
        self.assertNotIn("foundation-release-{0}", self.content)

    def test_pr_smokes_amd64_while_root_preview_builds_and_smokes_one_exact_multiarch_artifact(self):
        build_steps = self.jobs["build"]["steps"]
        build_info = next(step for step in build_steps if step.get("id") == "build-info")
        for required in ('publish=false', 'publish=true', 'version="${GITHUB_REF_NAME}"', '--intent qualify'):
            self.assertIn(required, build_info['run'])
        gate = next(step for step in build_steps if step.get('name') == 'Require merged source and successful main workflows')
        self.assertEqual(gate['if'], "github.ref_type == 'tag'")
        self.assertIn('verify_release_source.py', gate['run'])
        self.assertIn('check_release_runs.py', gate['run'])
        self.assertIn('--phase main', gate['run'])
        self.assertLess(build_steps.index(gate), next(i for i, step in enumerate(build_steps) if step.get('name') == 'Vendor workspace for Docker context'))

        build_image = next(
            step
            for step in build_steps
            if step.get("uses", "").startswith("docker/build-push-action@")
        )
        self.assertEqual(build_image["with"]["push"], "false")
        self.assertEqual(build_image["with"]["load"], "true")
        self.assertEqual(build_image["with"]["platforms"], "linux/amd64")
        self.assertEqual(
            build_image["if"],
            "github.ref_type != 'tag'",
        )
        self.assertFalse(
            any(
                step.get("uses", "").startswith("docker/login-action@")
                for step in build_steps
            )
        )

        smoke = next(
            step for step in build_steps if step.get("name") == "Smoke-test candidate image"
        )
        self.assertEqual(
            smoke["if"],
            "github.ref_type != 'tag'",
        )
        for label in (
            "org.opencontainers.image.title=mss-boot-admin",
            "org.opencontainers.image.description=Complete Go Admin backend for the mss-boot agent-native management-system distribution.",
        ):
            self.assertIn(label, build_image["with"]["labels"])
            self.assertIn(label.split("=", 1)[1], smoke["run"])

        qualification = next(
            step
            for step in build_steps
            if step.get("name") == "Qualify the exact multi-platform release image"
        )
        self.assertEqual(
            qualification["if"], "steps.build-info.outputs.publish == 'true'"
        )
        self.assertEqual(qualification["id"], "release-image")
        self.assertEqual(qualification["with"]["push"], "false")
        self.assertEqual(
            qualification["with"]["outputs"],
            "type=oci,dest=${{ runner.temp }}/root-image.oci.tar",
        )
        self.assertEqual(
            qualification["with"]["platforms"], "linux/amd64,linux/arm64"
        )
        self.assertEqual(qualification["with"]["provenance"], "true")
        self.assertEqual(qualification["with"]["sbom"], "true")

        stage = next(
            step
            for step in build_steps
            if step.get("name") == "Verify and stage the exact Root OCI image"
        )
        self.assertEqual(stage["env"]["BUILD_DIGEST"], "${{ steps.release-image.outputs.digest }}")
        for required in (
            'source_archive="${RUNNER_TEMP}/root-image.oci.tar"',
            "OCI layout must expose exactly one top-level image",
            'test "sha256:$(sha256sum "${source_manifest}"',
            'test "${archive_digest}" = "${BUILD_DIGEST}"',
            '.platform.architecture == "amd64"',
            '.platform.architecture == "arm64"',
            'inspect --config "oci-archive:${source_archive}"',
            'skopeo copy',
            '--override-arch amd64',
            '"docker-daemon:${smoke_image}"',
            'docker run --rm "${smoke_image}" --version',
            '[[ "${output}" == *"${RELEASE_VERSION}"* ]]',
            '[[ "${output}" == *"${GITHUB_SHA}"* ]]',
            'org.opencontainers.image.title"] == "mss-boot-admin"',
            'org.opencontainers.image.version"] == $version',
            'org.opencontainers.image.revision"] == $commit',
            "echo 'application=mss-boot-admin'",
            'echo "digest=${archive_digest}"',
            "sha256sum root-image.oci.tar ROOT-IMAGE-INFO.txt",
            "sha256sum --check SHA256SUMS.root-image",
            "tools/release/check_portable_paths.py",
            '"${artifact_dir}/ROOT-IMAGE-INFO.txt"',
        ):
            self.assertIn(required, stage["run"])

        upload = next(
            step
            for step in build_steps
            if step.get("name") == "Upload exact Root OCI artifact"
        )
        self.assertTrue(upload["uses"].startswith("actions/upload-artifact@"))
        self.assertEqual(
            upload["if"], "steps.build-info.outputs.publish == 'true'"
        )
        self.assertEqual(
            upload["with"]["name"],
            "root-image-preview-${{ steps.build-info.outputs.version }}",
        )
        for required in (
            "root-image.oci.tar",
            "ROOT-IMAGE-INFO.txt",
            "SHA256SUMS.root-image",
        ):
            self.assertIn(required, upload["with"]["path"])
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        self.assertEqual(upload["with"]["compression-level"], "0")

        non_tag_setup_steps = {
            "Setup Go",
            "Vendor workspace for Docker context",
            "Set up Docker Buildx",
            "Extract Docker metadata",
        }
        for step in build_steps:
            if step.get("name") in non_tag_setup_steps:
                with self.subTest(step=step["name"]):
                    self.assertNotIn("if", step)

        non_preview_ci_steps = {
            "Build candidate image",
            "Smoke-test candidate image",
        }
        for step in build_steps:
            if step.get("name") in non_preview_ci_steps:
                with self.subTest(step=step["name"]):
                    self.assertEqual(
                        step["if"],
                        "github.ref_type != 'tag'",
                    )

        root_preview_only_steps = {
            "Set up QEMU",
            "Qualify the exact multi-platform release image",
            "Verify and stage the exact Root OCI image",
            "Upload exact Root OCI artifact",
        }
        for step in build_steps:
            if step.get("name") in root_preview_only_steps:
                with self.subTest(step=step["name"]):
                    self.assertEqual(
                        step["if"], "steps.build-info.outputs.publish == 'true'"
                    )

    def test_metadata_executes_for_main_and_exact_tag_and_rejects_invalid_versions(self):
        script = next(step['run'] for step in self.jobs['build']['steps'] if step.get('id') == 'build-info')
        policy = yaml.load((REPOSITORY_ROOT / '.mss/release-policy.yaml').read_text(), Loader=yaml.BaseLoader)
        version = policy['spec']['nextPublicVersion']
        cases = [('branch', 'main', False, True), ('tag', version, True, True), ('tag', 'v01.3.8', False, False), ('tag', 'v1.3.5', False, False)]
        for ref_type, ref_name, publish, succeeds in cases:
            with self.subTest(ref=ref_name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'output'
                environment = dict(os.environ, GITHUB_REF_TYPE=ref_type, GITHUB_REF_NAME=ref_name,
                    GITHUB_SHA='a'*40, GITHUB_OUTPUT=str(output), REGISTRY='ghcr.io', IMAGE_NAME='owner/repo')
                result = subprocess.run(['bash', '-c', script], cwd=REPOSITORY_ROOT, env=environment, text=True, capture_output=True)
                self.assertEqual(result.returncode == 0, succeeds, result.stderr)
                if succeeds:
                    values = dict(line.split('=', 1) for line in output.read_text().splitlines())
                    self.assertEqual(values['publish'], str(publish).lower())
                    self.assertEqual(values['version'], version if publish else 'sha-'+'a'*12)

    def test_publish_job_keeps_policy_and_image_evidence_without_manual_gate(self):
        publish_steps = self.jobs["publish"]["steps"]
        authority = next(
            step
            for step in publish_steps
            if step.get("name") == "Require exact release publication authority"
        )
        for required in (
            "check_release_policy.py",
            "--intent publish",
            '"${GITHUB_EVENT_NAME}" != "push"',
            '"${GITHUB_REF_NAME}" != "${RELEASE_VERSION}"',
        ):
            self.assertIn(required, authority["run"])
        for forbidden in (
            "INPUT_PUBLISH",
            "READINESS_RUN_ID",
            "verify_readiness_run.sh",
            "workflow_dispatch",
        ):
            self.assertNotIn(forbidden, authority["run"])
        self.assertNotIn("inputs.publish", self.content)

        download = next(
            step
            for step in publish_steps
            if step.get("name")
            == "Download exact Root OCI image from this tag run"
        )
        self.assertTrue(download["uses"].startswith("actions/download-artifact@"))
        self.assertEqual(
            download["with"]["name"],
            "root-image-preview-${{ needs.build.outputs.version }}",
        )
        self.assertNotIn("run-id", download["with"])
        self.assertNotIn("repository", download["with"])
        self.assertNotIn("repository", download["with"])

        verification = next(
            step
            for step in publish_steps
            if step.get("name") == "Verify the exact Root OCI artifact"
        )
        for required in (
            "sha256sum --check SHA256SUMS.root-image",
            "grep -Fx 'application=mss-boot-admin'",
            'grep -Fx "version=${RELEASE_VERSION}"',
            'grep -Fx "commit=${GITHUB_SHA}"',
            'test "$(wc -l < "${image_info}")" -eq 4',
            "OCI layout must expose exactly one top-level image",
            'test "${actual_digest}" = "${expected_digest}"',
            '.platform.architecture == "amd64"',
            '.platform.architecture == "arm64"',
            'inspect --config "oci-archive:${archive}"',
            'org.opencontainers.image.title"] == "mss-boot-admin"',
            'org.opencontainers.image.description"] == "Complete Go Admin backend',
            'org.opencontainers.image.version"] == $version',
            'org.opencontainers.image.revision"] == $commit',
        ):
            self.assertIn(required, verification["run"])

        publication = next(
            step
            for step in publish_steps
            if step.get("name") == "Publish the exact Root OCI image"
        )
        self.assertEqual(publication["id"], "image")
        self.assertEqual(publication["env"]["VERSION"], "${{ needs.build.outputs.version }}")
        for required in (
            'archive="${RUNNER_TEMP}/root-image-preview/root-image.oci.tar"',
            'image_info="${RUNNER_TEMP}/root-image-preview/ROOT-IMAGE-INFO.txt"',
            'version_ref="${image_repository}:${VERSION}"',
            'commit_ref="${image_repository}:${GITHUB_SHA}"',
            "manifest unknown|manifest_unknown|name unknown|name_unknown",
            'preflight_reference "${version_ref}" root-version',
            'preflight_reference "${commit_ref}" root-commit',
            'validate_preflight "${version_ref}" root-version || preflight_failed=1',
            'validate_preflight "${commit_ref}" root-commit || preflight_failed=1',
            "image publication preflight failed before any registry write",
            "skopeo copy",
            "--all",
            "--preserve-digests",
            '"oci-archive:${archive}"',
            'publish_reference_if_missing "${version_ref}" root-version',
            'publish_reference_if_missing "${commit_ref}" root-commit',
            'verify_exact_reference "${version_ref}" root-version',
            'verify_exact_reference "${commit_ref}" root-commit',
            "--raw",
            '.platform.architecture == "amd64"',
            '.platform.architecture == "arm64"',
            'org.opencontainers.image.title"] == "mss-boot-admin"',
            'org.opencontainers.image.description"] == "Complete Go Admin backend',
            'org.opencontainers.image.version"] == $version',
            'org.opencontainers.image.revision"] == $commit',
            'echo "digest=${digest}"',
        ):
            self.assertIn(required, publication["run"])
        self.assertNotIn("name_unknown|not found", publication["run"])
        self.assertLess(
            publish_steps.index(verification), publish_steps.index(publication)
        )

        forbidden_names = {
            "Setup Go",
            "Vendor workspace for Docker context",
            "Set up QEMU",
            "Set up Docker Buildx",
            "Extract Docker metadata",
            "Build and publish image",
        }
        self.assertTrue(
            forbidden_names.isdisjoint(
                {step.get("name") for step in publish_steps}
            )
        )
        for step in publish_steps:
            self.assertFalse(
                step.get("uses", "").startswith("docker/build-push-action@")
            )
            self.assertFalse(
                step.get("uses", "").startswith("docker/setup-qemu-action@")
            )
            self.assertFalse(
                step.get("uses", "").startswith("docker/setup-buildx-action@")
            )
            self.assertNotIn("go work vendor", step.get("run", ""))

    def test_candidate_and_publish_metadata_never_create_latest_alias(self):
        metadata_steps = [
            step
            for job in self.jobs.values()
            for step in job.get("steps", [])
            if step.get("uses", "").startswith("docker/metadata-action@")
        ]
        self.assertEqual(len(metadata_steps), 1)
        for step in metadata_steps:
            with self.subTest(step=step.get("name")):
                self.assertEqual(step["with"]["flavor"].strip(), "latest=false")
                self.assertIn("type=ref,event=tag", step["with"]["tags"])
                self.assertIn(
                    "type=sha,prefix=,format=long,enable=true,priority=100",
                    step["with"]["tags"],
                )
                self.assertNotIn("value=latest", step["with"]["tags"])
                self.assertNotIn("latest=auto", step["with"]["flavor"])
        self.assertNotIn(":latest", self.content)
        self.assertNotIn("Restore stable alias", self.content)
        self.assertNotIn("imagetools create", self.content)

    def test_root_image_publication_preflights_both_refs_before_writes(self):
        image_script = next(
            step
            for step in self.jobs["publish"]["steps"]
            if step.get("name") == "Publish the exact Root OCI image"
        )["run"]
        calls = [line.strip() for line in image_script.splitlines()]
        ordered_calls = (
            'preflight_reference "${version_ref}" root-version',
            'preflight_reference "${commit_ref}" root-commit',
            'validate_preflight "${version_ref}" root-version || preflight_failed=1',
            'validate_preflight "${commit_ref}" root-commit || preflight_failed=1',
            'publish_reference_if_missing "${version_ref}" root-version',
            'publish_reference_if_missing "${commit_ref}" root-commit',
            'verify_exact_reference "${version_ref}" root-version',
            'verify_exact_reference "${commit_ref}" root-commit',
        )
        positions = [calls.index(call) for call in ordered_calls]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(
            "manifest unknown|manifest_unknown|name unknown|name_unknown",
            image_script,
        )
        self.assertNotIn("name_unknown|not found", image_script)

        version = "v9.8.7"
        commit = "0123456789abcdef0123456789abcdef01234567"
        manifest = json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": f"sha256:{'a' * 64}",
                        "size": 1,
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": f"sha256:{'b' * 64}",
                        "size": 1,
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                ],
            },
            separators=(",", ":"),
        )
        digest = f"sha256:{hashlib.sha256(manifest.encode()).hexdigest()}"
        conflict_manifest = json.dumps(
            {"schemaVersion": 2, "manifests": []}, separators=(",", ":")
        )
        config = json.dumps(
            {
                "config": {
                    "Labels": {
                        "org.opencontainers.image.title": "mss-boot-admin",
                        "org.opencontainers.image.description": "Complete Go Admin backend for the mss-boot agent-native management-system distribution.",
                        "org.opencontainers.image.version": version,
                        "org.opencontainers.image.revision": commit,
                    }
                }
            },
            separators=(",", ":"),
        )
        cases = (
            ("both missing", "missing", "missing", ("version", "commit"), True),
            ("one missing", "missing", "matching", ("version",), True),
            ("both matching", "matching", "matching", (), True),
            ("commit conflicts", "missing", "conflict", (), False),
            ("version conflicts", "conflict", "missing", (), False),
            ("inspection error", "missing", "error", (), False),
            ("generic not found error", "missing", "generic-not-found", (), False),
        )

        with tempfile.TemporaryDirectory() as directory:
            fixture_root = Path(directory)
            fake_bin = fixture_root / "bin"
            fake_bin.mkdir()
            fake_skopeo = fake_bin / "skopeo"
            fake_skopeo.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
reference="${!#}"
case "${reference}" in
  *":${VERSION}") key=version ;;
  *":${GITHUB_SHA}") key=commit ;;
  *) echo "unexpected reference: ${reference}" >&2; exit 64 ;;
esac
state_file="${FAKE_STATE_DIR}/${key}"
if [[ " $* " == *" --config "* ]]; then
  cat "${FAKE_CONFIG}"
  exit 0
fi
if [[ "${1:-}" == inspect ]]; then
  printf 'inspect:%s\n' "${key}" >> "${FAKE_OPERATIONS}"
  case "$(cat "${state_file}")" in
    matching) cat "${FAKE_MANIFEST}" ;;
    conflict) cat "${FAKE_CONFLICT_MANIFEST}" ;;
    missing) echo 'manifest unknown' >&2; exit 1 ;;
    error) echo 'temporary registry inspection failure' >&2; exit 1 ;;
    generic-not-found) echo 'credential helper executable not found' >&2; exit 1 ;;
    *) exit 65 ;;
  esac
  exit 0
fi
if [[ "${1:-}" == copy ]]; then
  printf 'copy:%s\n' "${key}" >> "${FAKE_OPERATIONS}"
  digest_file=''
  for ((argument_index=1; argument_index <= $#; argument_index++)); do
    if [[ "${!argument_index}" == --digestfile ]]; then
      digest_index=$((argument_index + 1))
      digest_file="${!digest_index}"
    fi
  done
  test -n "${digest_file}"
  printf '%s\n' "${EXPECTED_DIGEST}" > "${digest_file}"
  printf '%s\n' matching > "${state_file}"
  exit 0
fi
exit 66
""",
                encoding="utf-8",
            )
            fake_skopeo.chmod(0o755)
            manifest_path = fixture_root / "manifest.json"
            manifest_path.write_text(manifest, encoding="utf-8")
            conflict_manifest_path = fixture_root / "conflict-manifest.json"
            conflict_manifest_path.write_text(
                conflict_manifest, encoding="utf-8"
            )
            config_path = fixture_root / "config.json"
            config_path.write_text(config, encoding="utf-8")

            for name, version_state, commit_state, expected_writes, succeeds in cases:
                with self.subTest(name=name):
                    case_root = fixture_root / name.replace(" ", "-")
                    runner_temp = case_root / "runner"
                    preview = runner_temp / "root-image-preview"
                    state_dir = case_root / "state"
                    home = case_root / "home"
                    preview.mkdir(parents=True)
                    state_dir.mkdir(parents=True)
                    (home / ".docker").mkdir(parents=True)
                    (preview / "root-image.oci.tar").write_bytes(b"oci")
                    (preview / "ROOT-IMAGE-INFO.txt").write_text(
                        f"application=mss-boot-admin\nversion={version}\ncommit={commit}\ndigest={digest}\n",
                        encoding="utf-8",
                    )
                    (home / ".docker" / "config.json").write_text(
                        "{}\n", encoding="utf-8"
                    )
                    (state_dir / "version").write_text(
                        f"{version_state}\n", encoding="utf-8"
                    )
                    (state_dir / "commit").write_text(
                        f"{commit_state}\n", encoding="utf-8"
                    )
                    operations = case_root / "operations"
                    output = case_root / "github-output"
                    summary = case_root / "github-step-summary"
                    environment = os.environ.copy()
                    environment.pop("DOCKER_CONFIG", None)
                    environment.update(
                        {
                            "PATH": f"{fake_bin}:{environment['PATH']}",
                            "HOME": str(home),
                            "RUNNER_TEMP": str(runner_temp),
                            "GITHUB_OUTPUT": str(output),
                            "GITHUB_STEP_SUMMARY": str(summary),
                            "GITHUB_SHA": commit,
                            "REGISTRY": "ghcr.example.invalid",
                            "IMAGE_NAME": "mss/example",
                            "VERSION": version,
                            "FAKE_STATE_DIR": str(state_dir),
                            "FAKE_OPERATIONS": str(operations),
                            "FAKE_MANIFEST": str(manifest_path),
                            "FAKE_CONFLICT_MANIFEST": str(conflict_manifest_path),
                            "FAKE_CONFIG": str(config_path),
                            "EXPECTED_DIGEST": digest,
                        }
                    )
                    result = subprocess.run(
                        ["bash", "-c", image_script],
                        cwd=REPOSITORY_ROOT,
                        env=environment,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )
                    self.assertEqual(
                        result.returncode == 0,
                        succeeds,
                        msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
                    )
                    operation_lines = (
                        operations.read_text(encoding="utf-8").splitlines()
                        if operations.exists()
                        else []
                    )
                    self.assertEqual(
                        operation_lines[:2], ["inspect:version", "inspect:commit"]
                    )
                    writes = tuple(
                        line.removeprefix("copy:")
                        for line in operation_lines
                        if line.startswith("copy:")
                    )
                    self.assertEqual(writes, expected_writes)
                    if succeeds:
                        self.assertIn(
                            f"digest={digest}", output.read_text(encoding="utf-8")
                        )
                    else:
                        self.assertIn(
                            "before any registry write", result.stderr
                        )

    def test_root_container_publication_does_not_wait_for_root_or_npm(self):
        for forbidden in (
            "gh run watch",
            "gh workflow run",
            "npm-release.yml",
            "/actions/workflows/release.yml/runs",
            "/actions/workflows/npm-release.yml/runs",
        ):
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
                        f"invalid bash in {job_name} step {index} "
                        f"({step.get('name', 'unnamed')}): {result.stderr}"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
