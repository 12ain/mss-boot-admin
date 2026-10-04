import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/npm-release.yml'
SHA = 'a' * 40
VERSION = '1.3.8'
INTEGRITY = 'sha512-test-integrity'


class OfficialNpmReleaseWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.content = WORKFLOW.read_text()
        self.workflow = yaml.load(self.content, Loader=yaml.BaseLoader)
        self.jobs = self.workflow['jobs']
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.env = {
            **os.environ,
            'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF_TYPE': 'tag',
            'GITHUB_REF_NAME': 'v' + VERSION, 'GITHUB_SHA': SHA,
            'GITHUB_ENV': str(self.directory / 'env'),
            'GITHUB_OUTPUT': str(self.directory / 'output'),
            'RUNNER_TEMP': str(self.directory),
            'REQUESTED_VERSION': '', 'RELEASE_VERSION': 'v' + VERSION,
            'UNPREFIXED_VERSION': VERSION, 'RELEASE_COMMIT': SHA,
            'GITHUB_REPOSITORY': 'mss-boot-io/mss-boot-admin',
            'EXPECTED_LATEST': VERSION,
            'RELEASE_ACTOR_LOGIN': 'lwnmengjing',
            'GITHUB_ACTOR': 'lwnmengjing', 'GITHUB_TRIGGERING_ACTOR': 'lwnmengjing',
        }
        self.evidence = self.directory / 'evidence.json'
        self.evidence.write_text(json.dumps({'artifact': {'integrity': INTEGRITY}}))
        self.env['PACKAGE_EVIDENCE'] = str(self.evidence)
        self.tarball = self.directory / 'package.tgz'
        self.tarball.write_bytes(b'exact-frontend-release-bytes')
        self.env['PACKAGE_TARBALL'] = str(self.tarball)

    def step(self, name, job='publish'):
        return next(step for step in self.jobs[job]['steps'] if step.get('name') == name)

    def execute(self, name, *, job='publish', extra=None):
        env = {**self.env, **(extra or {})}
        return subprocess.run(['bash', '-c', self.step(name, job)['run']],
                              env=env, text=True, capture_output=True, cwd=ROOT, timeout=15)

    def install_registry_mocks(self):
        mocks = self.directory / 'bin'
        mocks.mkdir()
        program = '''#!/usr/bin/env python3
import json,os,pathlib,shutil,sys
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
metadata={"name":"@mss-boot-io/admin-web", "version":os.environ['UNPREFIXED_VERSION'],
          "gitHead":os.environ['RELEASE_COMMIT'], "dist.integrity":"sha512-test-integrity",
          "dist.tarball":"https://registry.npmjs.org/example.tgz",
          "dist.attestations":{"provenance":{"predicateType":"https://slsa.dev/provenance/v1"},"url":"https://registry.npmjs.org/attestations"}}
metadata.update(json.loads(os.environ.get('MOCK_METADATA','{}')))
if name=='npm':
    if args[0]=='publish':
        pathlib.Path(os.environ['RUNNER_TEMP'],'published.json').write_text(json.dumps({"args":args,"token":os.environ.get('NPM_TOKEN'),"nodeToken":os.environ.get('NODE_AUTH_TOKEN'),"config":os.environ.get('NPM_CONFIG_USERCONFIG')}))
    elif 'dist-tags.latest' in args:
        print(json.dumps(os.environ.get('MOCK_LATEST','1.3.7')))
    elif os.environ.get('MOCK_MISSING'):
        print(json.dumps({"error":{"code":os.environ.get('MOCK_ERROR','E404')}}))
        sys.exit(1)
    else:
        counter=pathlib.Path(os.environ['RUNNER_TEMP'],'metadata-reads')
        count=int(counter.read_text())+1 if counter.exists() else 1
        counter.write_text(str(count))
        if count <= int(os.environ.get('MOCK_PROVENANCE_DELAY','0')):
            metadata['dist.attestations']={}
        print(json.dumps(metadata))
elif name=='gh':
    print(os.environ.get('MOCK_GITHUB_LATEST','v1.3.7'))
elif name=='curl':
    dest=args[args.index('--output')+1]
    shutil.copyfile(os.environ['PACKAGE_TARBALL'],dest)
elif name=='sleep':
    pass
'''
        for command in ('npm', 'gh', 'curl', 'sleep'):
            script = mocks / command
            script.write_text(program)
            script.chmod(0o755)
        self.env['PATH'] = str(mocks) + os.pathsep + self.env['PATH']

    def test_root_tag_trigger_and_read_only_gate_precede_oidc(self):
        self.assertEqual(set(self.workflow['on']), {'push', 'workflow_dispatch'})
        self.assertEqual(self.workflow['on']['push']['tags'], ['v*.*.*'])
        self.assertEqual(set(self.workflow['on']['workflow_dispatch']['inputs']), {'version'})
        gate = self.jobs['gate']
        self.assertNotIn('environment', gate)
        self.assertTrue(all(value == 'read' for value in gate['permissions'].values()))
        self.assertEqual(self.jobs['publish']['needs'], 'gate')
        self.assertEqual(self.jobs['publish']['environment'], 'npm-auto')
        self.assertEqual(self.jobs['publish']['permissions']['id-token'], 'write')
        self.assertEqual(self.workflow['concurrency'],
                         {'group': 'official-npm-publication', 'cancel-in-progress': 'false'})
        wait = self.step('Wait for successful exact-source main and tag workflows', 'gate')['run']
        self.assertIn('check_release_runs.py', wait)
        self.assertIn('--phase all', wait)
        self.assertIn('--timeout-seconds 7200', wait)
        self.assertEqual(self.jobs['promote-github']['needs'], 'publish')

    def test_tag_identity_runs_for_push_and_exact_tag_retry(self):
        for extra in ({}, {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'REQUESTED_VERSION': 'v' + VERSION}):
            result = self.execute('Validate exact root tag identity', job='gate', extra=extra)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('commit=' + SHA, Path(self.env['GITHUB_OUTPUT']).read_text())
        for extra in ({'GITHUB_REF_TYPE': 'branch'},
                      {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'REQUESTED_VERSION': 'v1.3.9'},
                      {'GITHUB_REF_NAME': 'v1.3.8-rc.1'}, {'GITHUB_EVENT_NAME': 'pull_request'},
                      {'GITHUB_SHA': 'abcd'}, {'GITHUB_REF_NAME': 'v01.3.8'}):
            with self.subTest(extra=extra):
                self.assertNotEqual(self.execute('Validate exact root tag identity', job='gate', extra=extra).returncode, 0)

    def test_each_privileged_job_rechecks_rerun_actor(self):
        for job in ('gate', 'publish', 'promote-github'):
            with self.subTest(job=job):
                self.assertEqual(self.jobs[job]['steps'][0]['name'], 'Require authorized release operator')
                allowed = self.execute('Require authorized release operator', job=job)
                self.assertEqual(allowed.returncode, 0, allowed.stderr)
                for actor in ('GITHUB_ACTOR', 'GITHUB_TRIGGERING_ACTOR'):
                    denied = self.execute('Require authorized release operator', job=job,
                                          extra={actor: 'different-collaborator'})
                    self.assertNotEqual(denied.returncode, 0)

    def test_reuses_verified_frontend_release_without_duplicate_suites(self):
        assets = self.step('Download and verify existing frontend package assets')['run']
        for required in ('gh release download', "--pattern '*.tgz'", 'SHA256SUMS.admin-web',
                         'sha256sum --strict --check', 'verify_admin_web_package.py',
                         '--source-commit "${RELEASE_COMMIT}"', 'cmp --'):
            self.assertIn(required, assets)
        for forbidden in ('stablePromotionReady', '--intent promote', 'origin/main:.mss/release-policy.yaml',
                          'resolve_successful_preview.sh', 'docker ', 'setup-go', 'go test',
                          'npm.pkg.github.com', 'build:release', 'pnpm ', 'npm pack'):
            self.assertNotIn(forbidden, self.content)
        source = self.step('Verify merged-main release source', 'gate')['run']
        self.assertIn('verify_release_source.py', source)
        self.assertIn('--source-mode promotion', source)
        self.assertIn('--intent publish', source)

    def test_existing_identical_version_is_idempotent(self):
        self.install_registry_mocks()
        result = self.execute('Reconcile immutable npmjs publication state', extra={'MOCK_LATEST': VERSION})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('publish=false', Path(self.env['GITHUB_OUTPUT']).read_text())
        self.assertFalse((self.directory / 'published.json').exists())

    def test_existing_conflicting_immutable_metadata_fails(self):
        self.install_registry_mocks()
        for mutation in ({'name': 'another-package'}, {'version': '1.3.9'},
                         {'gitHead': 'b' * 40}, {'dist.integrity': 'sha512-other'}):
            with self.subTest(mutation=mutation):
                result = self.execute('Reconcile immutable npmjs publication state',
                                      extra={'MOCK_LATEST': VERSION, 'MOCK_METADATA': json.dumps(mutation)})
                self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.directory / 'published.json').exists())

    def test_version_not_found_allows_publish_but_transport_and_auth_errors_do_not(self):
        self.install_registry_mocks()
        result = self.execute('Reconcile immutable npmjs publication state', extra={'MOCK_MISSING': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('publish=true', Path(self.env['GITHUB_OUTPUT']).read_text())
        for error in ('E401', 'E403', 'E500', 'ETIMEDOUT'):
            with self.subTest(error=error):
                result = self.execute('Reconcile immutable npmjs publication state',
                                      extra={'MOCK_MISSING': '1', 'MOCK_ERROR': error})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('without an authoritative E404', result.stderr)

    def test_older_rerun_cannot_roll_back_npm_or_github_latest(self):
        self.install_registry_mocks()
        for extra in ({'MOCK_LATEST': '1.3.9'}, {'MOCK_LATEST': '1.10.0'},
                      {'MOCK_GITHUB_LATEST': 'v1.4.0'}, {'MOCK_LATEST': '1.3.8-rc.1'},
                      {'MOCK_LATEST': 'garbage'}):
            with self.subTest(extra=extra):
                result = self.execute('Reconcile immutable npmjs publication state',
                                      extra={'MOCK_MISSING': '1', **extra})
                self.assertNotEqual(result.returncode, 0)
        result = self.execute('Reconcile immutable npmjs publication state',
                              extra={'MOCK_MISSING': '1', 'UNPREFIXED_VERSION': '1.10.0', 'MOCK_LATEST': '1.9.0'})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_publish_uses_only_oidc_latest_and_provenance(self):
        self.install_registry_mocks()
        result = self.execute('Publish the existing tarball to official npm',
                              extra={'NPM_TOKEN': 'test', 'NODE_AUTH_TOKEN': 'test',
                                     'NPM_CONFIG_USERCONFIG': 'test'})
        self.assertEqual(result.returncode, 0, result.stderr)
        published = json.loads((self.directory / 'published.json').read_text())
        self.assertIsNone(published['token'])
        self.assertIsNone(published['nodeToken'])
        self.assertIsNone(published['config'])
        self.assertEqual(published['args'], ['publish', str(self.tarball), '--access', 'public',
                                            '--tag', 'latest', '--provenance', '--registry=https://registry.npmjs.org'])
        self.assertNotIn('secrets.NPM_TOKEN', self.content)
        self.assertNotRegex(self.content, r'\bnpm dist-tag (?:add|rm)\b')

    def test_final_verification_requires_integrity_provenance_latest_and_exact_bytes(self):
        self.install_registry_mocks()
        result = self.execute('Verify npmjs integrity provenance and immutable identity',
                              extra={'MOCK_LATEST': VERSION})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.directory / 'npmjs-published-admin-web.tgz').read_bytes(), self.tarball.read_bytes())
        for mutation in ({'dist.integrity': 'sha512-other'}, {'gitHead': 'b' * 40},
                         {'dist.attestations': {}}, {'version': '1.3.9'}):
            with self.subTest(mutation=mutation):
                result = self.execute('Verify npmjs integrity provenance and immutable identity',
                                      extra={'MOCK_LATEST': VERSION, 'MOCK_METADATA': json.dumps(mutation)})
                self.assertNotEqual(result.returncode, 0)

    def test_provenance_propagation_is_polled_but_immutable_conflicts_fail_immediately(self):
        self.install_registry_mocks()
        result = self.execute('Verify npmjs integrity provenance and immutable identity',
                              extra={'MOCK_LATEST': VERSION, 'MOCK_PROVENANCE_DELAY': '2'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.directory / 'metadata-reads').read_text(), '3')
        (self.directory / 'metadata-reads').unlink()
        result = self.execute('Verify npmjs integrity provenance and immutable identity',
                              extra={'MOCK_LATEST': VERSION,
                                     'MOCK_METADATA': json.dumps({'gitHead': 'b' * 40})})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.directory / 'metadata-reads').read_text(), '1')
        for predicate in ('https://example.invalid/other-provenance', 123):
            with self.subTest(predicate=predicate):
                (self.directory / 'metadata-reads').unlink()
                result = self.execute('Verify npmjs integrity provenance and immutable identity',
                                      extra={'MOCK_LATEST': VERSION, 'MOCK_METADATA': json.dumps({
                                          'dist.attestations': {'provenance': {'predicateType': predicate}}
                                      })})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('conflicting provenance', result.stderr)
                self.assertEqual((self.directory / 'metadata-reads').read_text(), '1')

    def test_all_run_blocks_parse_as_bash(self):
        for job in self.jobs.values():
            for step in job.get('steps', []):
                if 'run' in step:
                    script = re.sub(r'\$\{\{.*?\}\}', 'gha_expression', step['run'], flags=re.S)
                    result = subprocess.run(['bash', '-n'], input=script, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, step['name'] + ': ' + result.stderr)


if __name__ == '__main__':
    unittest.main()
