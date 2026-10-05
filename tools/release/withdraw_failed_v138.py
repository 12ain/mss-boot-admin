#!/usr/bin/env python3
"""Withdraw only the three known artifacts from the failed first v1.3.8 release.

This is a one-off, explicitly authorized recovery, not a general release cleanup
command. Re-published 1.3.8 artifacts with different identities must fail closed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


REPOSITORY = "mss-boot-io/mss-boot-admin"
OWNER = "mss-boot-io"
ACTOR = "lwnmengjing"
OLD_COMMIT = "2c44518c20660e3cfe91daf513809bd4753dbb24"
TAGS = ("v1.3.8", "mss-boot/v1.3.8", "admin/v1.3.8", "web/antd-v6/v1.3.8")
# The three published component Releases plus the absent failed Root Release.
RELEASES = TAGS
NPM_PATH = "/@mss-boot-io%2fadmin-web/1.3.8"
NPM_INTEGRITY = "sha512-D69VExXiQaIb/V7wROJ6BU9KtXTsFQ10+OeOXZuxWU8fHekw/VEnzeerOwfmLHLTVIuCbFCAJBaacJYAczjkLw=="


class CleanupError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    kind: str
    package: str
    version: str

    @property
    def path(self):
        return f"/orgs/{OWNER}/packages/{self.kind}/{self.package}"


TARGETS = (
    Target("npm", "admin-web", "1.3.8"),
    Target("container", "mss-boot-admin", "sha256:adb9087e8dc6d554145dfd1191c476e8483ccfe30725e6a5fbe737248e7d84ac"),
    Target("container", "mss-boot-admin-antd-v6", "sha256:017ed0a9218d03913b9edbb670ef1855d8838d05b11ff47d30462772ad83df95"),
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Never forward GITHUB_TOKEN to a redirect destination.
        return None


class API:
    def __init__(self, token):
        if not token:
            raise CleanupError("GITHUB_TOKEN is required")
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, host, path, *, method="GET", missing=False):
        if host not in {"api.github.com", "npm.pkg.github.com", "registry.npmjs.org"}:
            raise CleanupError("unapproved API host")
        headers = {"Accept": "application/json", "User-Agent": "mss-v138-withdrawal"}
        if host != "registry.npmjs.org":
            headers["Authorization"] = f"Bearer {self.token}"
        if host == "api.github.com":
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        request = urllib.request.Request(f"https://{host}{path}", headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                if method == "DELETE":
                    if response.status != 204:
                        raise CleanupError("version deletion did not return HTTP 204")
                    return None
                return json.load(response)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            if status == 404 and missing:
                return None
            raise CleanupError(f"{method} {host}{path}: HTTP {status}") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
            raise CleanupError(f"{method} {host}{path}: transport or JSON failure") from None

    def get(self, path, *, missing=False):
        return self.request("api.github.com", path, missing=missing)

    def npm(self, *, official=False):
        if official:
            return self.request("registry.npmjs.org", NPM_PATH, missing=True)
        # npm clients query the scoped package packument, then select a version.
        package = self.request("npm.pkg.github.com", NPM_PATH.rsplit("/", 1)[0])
        if (not isinstance(package, dict)
                or package.get("name") != "@mss-boot-io/admin-web"
                or not isinstance(package.get("versions"), dict)):
            raise CleanupError("invalid GitHub npm package metadata")
        return package["versions"].get("1.3.8")

    def delete_version(self, target, version_id):
        if target not in TARGETS or type(version_id) is not int or version_id < 1:
            raise CleanupError("deletion target is outside the fixed recovery scope")
        self.request("api.github.com", f"{target.path}/versions/{version_id}",
                     method="DELETE", missing=True)


def authorize(env):
    expected = {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_ACTOR": ACTOR,
        "GITHUB_TRIGGERING_ACTOR": ACTOR,
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/.github/workflows/withdraw-failed-v138.yml@refs/heads/main",
    }
    for key, value in expected.items():
        if env.get(key) != value:
            raise CleanupError(f"{key} is not authorized for this one-off withdrawal")


def require_withdrawn_refs(api):
    repository = api.get(f"/repos/{REPOSITORY}")
    if not isinstance(repository, dict) or repository.get("full_name") != REPOSITORY:
        raise CleanupError("the source repository is not readable")
    for tag in TAGS:
        encoded = urllib.parse.quote(tag, safe="")
        if api.get(f"/repos/{REPOSITORY}/git/ref/tags/{encoded}", missing=True) is not None:
            raise CleanupError(f"tag {tag} still exists")
    for tag in RELEASES:
        encoded = urllib.parse.quote(tag, safe="")
        if api.get(f"/repos/{REPOSITORY}/releases/tags/{encoded}", missing=True) is not None:
            raise CleanupError(f"GitHub Release {tag} still exists")
    if api.npm(official=True) is not None:
        raise CleanupError("official npm 1.3.8 already exists; withdrawal is forbidden")


def verify_npm_identity(api):
    metadata = api.npm()
    if (not isinstance(metadata, dict)
            or metadata.get("name") != "@mss-boot-io/admin-web"
            or metadata.get("version") != "1.3.8"
            or metadata.get("gitHead") != OLD_COMMIT
            or not isinstance(metadata.get("dist"), dict)
            or metadata["dist"].get("integrity") != NPM_INTEGRITY):
        raise CleanupError("GitHub npm 1.3.8 does not match the withdrawn tarball integrity")


def version_id(row):
    value = row.get("id") if isinstance(row, dict) else None
    if type(value) is not int or value < 1 or not isinstance(row.get("name"), str):
        raise CleanupError("invalid package version metadata")
    return value


def check_container_tags(target, row):
    metadata = row.get("metadata")
    container = metadata.get("container") if isinstance(metadata, dict) else None
    tags = container.get("tags") if isinstance(container, dict) else None
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise CleanupError("invalid container tags")
    if "v1.3.8" in tags and row["name"] != target.version:
        raise CleanupError(f"{target.package}: v1.3.8 points to a different digest")
    if row["name"] == target.version and set(tags) - {"v1.3.8", OLD_COMMIT}:
        raise CleanupError(f"{target.package}: old index also carries unrelated tags")


def inspect_target(api, target):
    # These packages have earlier releases that this task must preserve. A
    # package-level 404 can hide insufficient permissions; only an absent
    # version in a successfully read list is an idempotent success.
    package = api.get(target.path)
    if (not isinstance(package, dict)
            or package.get("name") != target.package
            or package.get("package_type") != target.kind
            or not isinstance(package.get("owner"), dict)
            or package["owner"].get("login") != OWNER
            or not isinstance(package.get("repository"), dict)
            or package["repository"].get("full_name") != REPOSITORY):
        raise CleanupError(f"package ownership or repository mismatch: {target.package}")
    matches = []
    seen = set()
    for page in range(1, 101):
        rows = api.get(f"{target.path}/versions?state=active&per_page=100&page={page}")
        if not isinstance(rows, list):
            raise CleanupError("invalid package version list")
        for row in rows:
            ident = version_id(row)
            if ident in seen:
                raise CleanupError("package pagination repeated a version")
            seen.add(ident)
            if target.kind == "container":
                check_container_tags(target, row)
            if row["name"] == target.version:
                matches.append(ident)
        if len(rows) < 100:
            break
    else:
        raise CleanupError("package pagination exceeded its safety limit")
    if len(matches) > 1:
        raise CleanupError("ambiguous package version identity")
    if target.kind == "npm":
        if matches:
            verify_npm_identity(api)
    return matches[0] if matches else None


def plan(api):
    require_withdrawn_refs(api)
    # Validate every target before any mutation, including later-page conflicts.
    return [(target, inspect_target(api, target)) for target in TARGETS]


def cleanup(api, env, *, write=False, emit=print):
    authorize(env)
    selected = plan(api)
    for target, ident in selected:
        emit(f"{target.kind}/{target.package} {target.version}: "
             + (f"old version id {ident}" if ident is not None else "already absent"))
    if not write:
        return
    for target, ident in selected:
        if ident is None:
            continue
        # Recheck the remote namespace and full artifact plan before each DELETE.
        current = dict(plan(api))[target]
        if current is None:
            continue
        if current != ident:
            raise CleanupError("package version id changed after planning")
        detail = api.get(f"{target.path}/versions/{ident}")
        if version_id(detail) != ident or detail["name"] != target.version:
            raise CleanupError("package version identity changed before deletion")
        if target.kind == "container":
            check_container_tags(target, detail)
        api.delete_version(target, ident)
        emit(f"deleted only {target.kind}/{target.package} version id {ident}")
    if any(ident is not None for _, ident in plan(api)):
        raise CleanupError("withdrawn package versions remain visible after deletion")
    emit("the three fixed old artifact identities are absent")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="delete only the fixed old artifact versions")
    args = parser.parse_args()
    try:
        authorize(os.environ)
        cleanup(API(os.environ.get("GITHUB_TOKEN", "")), os.environ, write=args.write)
    except CleanupError as exc:
        print(f"v1.3.8 withdrawal blocked: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
