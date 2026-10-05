#!/usr/bin/env python3
"""Copy a candidate workspace without allowing Go to rewrite tracked sums."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess


def prepare_workspace(source: Path, target: Path) -> None:
    source = source.resolve(strict=True)
    target = target.resolve()
    if source.name != "go.work":
        raise ValueError("source must be the repository go.work")
    if target == source or not target.is_relative_to(source.parent):
        raise ValueError("isolated workspace must stay inside the repository")
    if target.exists() or target.with_name(target.name + ".sum").exists():
        raise ValueError("isolated workspace must not overwrite existing files")
    if (source.parent / "vendor").exists():
        raise ValueError("isolated workspace does not support workspace vendoring")

    workspace = json.loads(
        subprocess.check_output(["go", "work", "edit", "-json", str(source)], text=True)
    )
    # Let Go preserve every directive and escape paths, including paths with
    # spaces. Only relative filesystem references change location in this copy.
    edits: list[str] = []
    for entry in workspace.get("Use") or []:
        path = Path(entry["DiskPath"])
        if not path.is_absolute():
            edits.extend(
                [f"-dropuse={path}", f"-use={(source.parent / path).resolve()}"]
            )
    # A wildcard -replace removes version-specific replacements for that module.
    # Restore the complete original set, with version-specific entries last.
    for entry in sorted(
        workspace.get("Replace") or [], key=lambda item: bool(item["Old"].get("Version"))
    ):
        replacement = entry["New"]
        path = Path(replacement["Path"])
        destination = replacement["Path"]
        if not replacement.get("Version") and not path.is_absolute():
            destination = str((source.parent / path).resolve())
        if replacement.get("Version"):
            destination += "@" + replacement["Version"]
        previous = entry["Old"]
        module = previous["Path"]
        if previous.get("Version"):
            module += "@" + previous["Version"]
        edits.append(f"-replace={module}={destination}")
    rendered = subprocess.check_output(
        ["go", "work", "edit", "-print", *edits, str(source)], text=True
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    source_sum = source.with_name(source.name + ".sum")
    if source_sum.exists():
        shutil.copyfile(source_sum, target.with_name(target.name + ".sum"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()
    prepare_workspace(args.source, args.target)


if __name__ == "__main__":
    main()
