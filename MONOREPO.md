# Monorepo guide

## Layout

| Path | Purpose |
| --- | --- |
| `/` | Agent/Foundation Go tooling and shared repository contracts |
| `admin/` | `github.com/mss-boot-io/mss-boot-admin/admin`, the complete importable Admin application |
| `mss-boot/` | `github.com/mss-boot-io/mss-boot-admin/mss-boot`, the reusable Go framework |
| `web/antd-v6/` | Sole React 19 + Ant Design 6 source and `@mss-boot-io/admin-web` package |
| `docs/` | Dumi documentation site |

`go.work` activates the backend and framework modules together. Do not add a local `replace` directive to either published `go.mod`; workspace mode is the source of truth for repository-local development.

`go.work` is only a repository-development convenience. Every publishable Go
module and the generated Thin Host are also qualified with `GOWORK=off`; normal
module files never contain a local checkout replacement.

## Common commands

```shell
make deps-all
make test-all
make web-install web-lint web-test web-build
make docs-install docs-build
```

## Release tags

- Root Admin Distribution: `vX.Y.Z`
- Framework module: `mss-boot/vX.Y.Z`
- Complete Admin Go module: `admin/vX.Y.Z`
- Admin Web package and image: `web/antd-v6/vX.Y.Z`
- Documentation: `docs/vX.Y.Z`

Runtime components have independently triggered workflows, but one Admin
Distribution release requires the same version core and exact merged-main commit.
v1.3.5 is permanently stopped as an immutable partial release. v1.3.6 is
permanently stopped as an immutable partial release. Neither can be qualified,
resumed, completed, or reused. v1.3.6 published its Framework, Admin, Admin Web,
and Root releases, but its Root image and npm workflows failed and Docs was
never created.

v1.3.7 is the current stable and adoptable Distribution from exact release
commit `77b53d41092741eac62fa6418c0bdbf87413c7cd`. Framework, Admin,
Admin Web, Root tools, both images, official npm, npm `latest`, GitHub Latest,
and current-stable policy are reconciled. Docs is an asynchronous website
publication; its `docs/v*` tag, credential, workflow, Release, and site state
never gate the Distribution or adopter availability.

For new releases, main CI and the tag workflows must succeed on the same exact
commit. Each component tag builds and publishes its own artifacts from that
merged-main source. The Admin tag resolves the already published Framework with
`GOWORK=off`. The Root tag automatically starts `npm-release.yml`, which waits
for the matching main and tag results and publishes through Trusted Publishing
without a separate preview or manual stable-promotion step. It uses
`npm publish --tag latest --provenance` and advances GitHub Latest only after npm
identity and provenance reconcile. Existing package versions, tags, and image
digests are immutable; reruns verify their exact identities before reusing them.
The workflows do not repeat expensive qualification through a separate release
rehearsal or request a manual environment approval.

The v1.3.7 release used the previous preview and reviewed-promotion procedure.
Its exact publication evidence remains in the
[historical stable release record](docs/docs/releases/v1-3-7.md); that procedure
does not govern new releases. Adopter documentation remains on
`currentStableVersion` until public artifact reconciliation updates the policy.
`nextPublicVersion` identifies preparation work only.

A later qualified merged-main descendant may update the website by deleting the
current Docs Release and tag, proving both are absent, and recreating the same
`docs/<stable-version>` tag. Direct force-update is prohibited. A release-source
repair after public Distribution identity requires another unused product
version; a Docs failure uses only the independent Docs PR and same-tag
replacement path.

## Workflow location

Only workflows under the repository-root `.github/workflows/` directory are
active. Imported, nested workflow snapshots are not retained because GitHub does
not execute them in this monorepo.

## Import provenance

`MONOREPO_IMPORTS.md` records the source repositories and exact imported commits
as historical provenance. It does not define a current checkout, build, adoption,
or release path.
