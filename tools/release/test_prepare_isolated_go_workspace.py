from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name("prepare-isolated-go-workspace.py")
SPEC = importlib.util.spec_from_file_location("prepare_isolated_go_workspace", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IsolatedGoWorkspaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="mss-go-workspace-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "go.work"
        self.target = self.root / "reports" / "go.work"
        self.source.write_text(
            'go 1.24.0\n\ntoolchain go1.24.1\n\ngodebug default=go1.24\n\n'
            'use "./app with spaces"\n\n'
            'replace example.invalid/library v1.0.0 => "./local library"\n'
            'replace example.invalid/unused => "./local library"\n'
            'replace example.invalid/unused v1.2.0 => example.invalid/public v1.3.0\n',
            encoding="utf-8",
        )
        self.source.with_name("go.work.sum").write_text("", encoding="utf-8")
        app = self.root / "app with spaces"
        library = self.root / "local library"
        app.mkdir()
        library.mkdir()
        (app / "go.mod").write_text(
            "module example.invalid/app\n\ngo 1.24.0\n\n"
            "require example.invalid/library v1.0.0\n", encoding="utf-8"
        )
        (app / "main.go").write_text(
            'package main\nimport "example.invalid/library"\nfunc main() { library.Run() }\n',
            encoding="utf-8",
        )
        (library / "go.mod").write_text(
            "module example.invalid/library\n\ngo 1.24.0\n", encoding="utf-8"
        )
        (library / "library.go").write_text(
            "package library\nfunc Run() {}\n", encoding="utf-8"
        )

    def read_workspace(self, path: Path) -> dict:
        return json.loads(
            subprocess.check_output(["go", "work", "edit", "-json", str(path)], text=True)
        )

    def test_preserves_resolution_and_directives_without_changing_source(self) -> None:
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        original = self.read_workspace(self.source)
        MODULE.prepare_workspace(self.source, self.target)
        isolated = self.read_workspace(self.target)
        expected = json.loads(json.dumps(original))
        for entry in expected["Use"]:
            entry["DiskPath"] = str((self.root / entry["DiskPath"]).resolve())
        for entry in expected["Replace"]:
            replacement = entry["New"]
            if not replacement.get("Version"):
                replacement["Path"] = str((self.root / replacement["Path"]).resolve())
        self.assertEqual(isolated, expected)
        self.assertEqual(self.target.with_name("go.work.sum").read_bytes(), b"")
        subprocess.run(
            ["go", "build", "-o", str(self.target.parent / "app"), "."],
            cwd=self.root / "app with spaces",
            env={**os.environ, "GOWORK": str(self.target), "GOPROXY": "off"},
            check=True,
        )
        # Go owns only the isolated checksum file; the source is never restored
        # after a write, so unexpected tracked changes remain visible to the gate.
        self.target.with_name("go.work.sum").write_text("isolated updates\n", encoding="utf-8")
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content, str(path))

    def test_refuses_source_overwrite_or_repository_escape(self) -> None:
        for target in [self.source, self.root.parent / "outside-go.work"]:
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "inside"):
                MODULE.prepare_workspace(self.source, target)

    def test_refuses_existing_target(self) -> None:
        self.target.parent.mkdir()
        self.target.write_text("keep this file", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            MODULE.prepare_workspace(self.source, self.target)
        self.assertEqual(self.target.read_text(), "keep this file")

    def test_refuses_workspace_vendor_resolution_change(self) -> None:
        (self.root / "vendor").mkdir()
        with self.assertRaisesRegex(ValueError, "vendoring"):
            MODULE.prepare_workspace(self.source, self.target)


if __name__ == "__main__":
    unittest.main()
