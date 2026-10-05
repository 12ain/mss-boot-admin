#!/usr/bin/env python3
"""Render release installers with the exact tag as their default version."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path


VERSION_RE = re.compile(r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
INSTALLERS = (
    ("install-mss.sh", r'^readonly DEFAULT_VERSION="[^"\r\n]*"$',
     'readonly DEFAULT_VERSION="{version}"', 0o755),
    ("install-mss.ps1", r"^    \[string\]\$Version = '[^'\r\n]*',$",
     "    [string]$Version = '{version}',", 0o644),
)


class RenderError(ValueError):
    pass


def render(version: str, source_directory: Path, output_directory: Path) -> list[Path]:
    if VERSION_RE.fullmatch(version) is None:
        raise RenderError("release version must be an exact stable vX.Y.Z")
    sources = [source_directory / name for name, _, _, _ in INSTALLERS]
    outputs = [output_directory / name for name, _, _, _ in INSTALLERS]
    source_paths = {path.resolve() for path in sources}
    rendered = []
    # Validate the complete pair before creating any output.
    for (name, pattern, replacement, mode), source, output in zip(INSTALLERS, sources, outputs):
        if not source.is_file() or source.is_symlink():
            raise RenderError(f"installer source must be a regular file: {source}")
        if output.resolve() in source_paths or output.is_symlink():
            raise RenderError(f"installer output must not overwrite or link to source: {output}")
        if output.exists() and not output.is_file():
            raise RenderError(f"installer output is not a regular file: {output}")
        text = source.read_text(encoding="utf-8")
        matches = list(re.finditer(pattern, text, flags=re.MULTILINE))
        if len(matches) != 1:
            raise RenderError(f"{name} must contain exactly one default-version declaration")
        match = matches[0]
        content = text[:match.start()] + replacement.format(version=version) + text[match.end():]
        rendered.append((output, content.encode("utf-8"), mode))
    output_directory.mkdir(parents=True, exist_ok=True)
    for output, content, mode in rendered:
        # Replace the output entry atomically: even a pre-existing hardlink
        # cannot cause the source installer to be changed in place.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=output_directory, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            temporary.chmod(mode)
            os.replace(temporary, output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-directory", type=Path, default=Path("tools/install"))
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        outputs = render(args.version, args.source_directory, args.output_directory)
    except (RenderError, OSError, UnicodeError) as exc:
        print(f"installer rendering failed: {exc}", file=sys.stderr)
        return 1
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
