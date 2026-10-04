---
name: mss-release
description: Prepare, execute, retry, and reconcile an MSS release using successful main and matching tag workflows. Use for release preparation, immutable component tags, automatic npm OIDC publication, failed-job recovery, release notes, and rollback. Do not bypass failed checks or publish unmerged source.
---

# Release an MSS component

Use one version and exact reviewed merged-main commit. Main checks own quality;
tag workflows own builds and publication. Official npm publication waits for
both. Do not add a standalone artifact preview, a mandatory local full suite,
or a second PR solely to authorize stable promotion.

## Prepare source

1. Read `AGENTS.md`, `.mss/project.yaml`, `.mss/lock.yaml`,
   `.mss/release-policy.yaml`, `.mss/release-qualification.json`, selected
   Features, changelogs, and relevant workflows.
2. Align the unpublished candidate version in Project, lock, Blueprint,
   Admin dependency, workspace, and frontend manifest. Keep the current stable
   version and commit unchanged until publication succeeds.
3. Commit implementation before regenerating candidate module checksums with
   `python3 tools/release/verify_framework_admin_checksum.py --version <version> --write`.
   Commit its deterministic metadata, then verify again without `--write`.
4. Run `mss verify --changed` and focused regression tests. Submit every change
   through a reviewed PR to `main`. Never push directly to `main`.
5. Fetch `origin/main`, use a clean checkout at the selected merged commit,
   and verify the source with `tools/release/verify_release_source.py`.
6. Record version, full commit, PR, active actor, main workflow URLs, component
   tags, and publication state. Preserve all stopped-train and public identities.

## Main and tag gates

Check the same-commit main workflows using the shared read-only resolver:

```shell
python3 tools/release/check_release_runs.py \
  --repository <owner/repo> --commit <full-sha> --version <version> --phase main
```

The resolver checks CI, govulncheck, CodeQL, Docs build, Framework CI, and Admin
Distribution Compatibility. It accepts only successful main-branch push or
manual runs at that exact SHA. If a path filter omitted a workflow, dispatch
that workflow on `main` while main still points at the selected commit; never
substitute evidence from another SHA. Main branch and tag workflows do not need
an additional complete local qualification run. `mss verify --all` remains an
optional diagnostic when investigating failures.

Only the authorized release operator creates annotated tags. Create and verify
these in order from the same commit:

1. `mss-boot/<version>`: publish Framework and verify public module resolution.
2. `admin/<version>`: consume the public matching Framework and publish Admin.
3. `web/antd-v6/<version>`: build once, then publish the frontend archive,
   npm tarball, GitHub Packages mirror, and multi-platform image.
4. `<version>`: build Root tools and archives, reuse the frontend Release
   assets, and build/publish the Root image in its tag workflow.

Each workflow verifies merged source and the reviewed candidate version.
Successful build jobs pass artifacts to publication jobs within the same run.
Root does not rebuild frontend assets. Public refs, packages, images, and
checksums are immutable.

## Automatic official npm publication

The Root tag starts `npm-release.yml`. Its read-only gate waits for the exact
main workflows and all five tag workflows: Framework, Admin, frontend, Root,
and Root container. Missing or running results wait within a finite timeout;
a failed result or mismatched commit cannot authorize publication.

The protected `npm-auto` job downloads the existing frontend tarball and
checksums. It verifies package name, version, source commit, and integrity,
then publishes through Trusted Publishing/OIDC with `--tag latest --provenance`.
There is no long-lived npm token or separate promotion-authorization PR.
The legacy `stablePromotion*` fields remain disabled solely so historical
Foundation readers can parse the policy; the workflow does not use them.

An already-public exact package is reconciled without another publish.
A mismatched package or an attempt to move `latest` backward fails closed.
Only after npm identity, provenance, and `latest` are verified may the workflow
update the matching Root GitHub Release to Latest.

For a transient failure, retry failed jobs in the same run so successful build
artifacts remain byte-identical. A manual npm retry uses the exact Root tag:

```shell
gh workflow run npm-release.yml --ref <version> -f version=<version>
```

Retrying never bypasses the main/tag gate. Do not move tags, overwrite package
versions, or rebuild and overwrite already-public bytes. A source repair after
any immutable core publication requires a new unused patch version through a PR.

## Reconcile and document

Verify published version, commit, package integrity/provenance, image digests,
and workflow URLs. Update current stable and adopter guidance through an
ordinary factual reconciliation PR after successful publication; this PR is
not an npm publication prerequisite. Keep historical release records intact.

Docs is a separate website deployment. Its main build is checked alongside
main quality workflows, but Docs tags, deployment credentials, public site,
and Docs Release state are not package-publication prerequisites. The authorized
operator may replace only `docs/<current-stable-version>` by deleting its Release
and tag, proving both absent, then recreating an annotated tag at a qualified
merged-main descendant of the Root commit. Never force-update the tag. Verify
checksums, the Docs workflow, `/release.json`, and visible browser behavior.

Report completed checks and workflow URLs, unresolved failures, version and
full commit, PR, publication state, migration/compatibility/security impact,
rollback baseline, and the next executable action. Never include credentials
or claim that a local build or a draft PR is a published release.
