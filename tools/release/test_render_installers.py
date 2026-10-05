import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_installers as renderer

ROOT = Path(__file__).resolve().parents[2]


class RenderInstallersTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.output = self.root / "output"
        self.source.mkdir()
        for name, _, _, _ in renderer.INSTALLERS:
            shutil.copyfile(ROOT / "tools/install" / name, self.source / name)

    def test_exact_version_modes_determinism_and_unchanged_sources(self):
        originals = {path.name: path.read_bytes() for path in self.source.iterdir()}
        outputs = renderer.render("v9.8.7", self.source, self.output)
        first = {path.name: path.read_bytes() for path in outputs}
        self.assertIn(b'readonly DEFAULT_VERSION="v9.8.7"', first["install-mss.sh"])
        self.assertIn(b"    [string]$Version = 'v9.8.7',", first["install-mss.ps1"])
        self.assertEqual(stat.S_IMODE(outputs[0].stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(outputs[1].stat().st_mode), 0o644)
        renderer.render("v9.8.7", self.source, self.output)
        self.assertEqual(first, {path.name: path.read_bytes() for path in outputs})
        self.assertEqual(originals, {path.name: path.read_bytes() for path in self.source.iterdir()})

    def test_rejects_invalid_or_nonstable_version_before_writing(self):
        for version in ("latest", "1.3.8", "v01.3.8", "v1.03.8", "v1.3.08",
                        "v1.3.8-rc.1", "v1.3.8+build", "v1.3.8\n", 'v1.3.8"; touch bad'):
            with self.subTest(version=version):
                with self.assertRaisesRegex(renderer.RenderError, "exact stable"):
                    renderer.render(version, self.source, self.output)
                self.assertFalse(self.output.exists())

    def test_missing_or_duplicate_declaration_rejects_entire_pair(self):
        for name, _, _, _ in renderer.INSTALLERS:
            source = self.source / name
            original = source.read_text()
            declaration = next(line for line in original.splitlines()
                               if "DEFAULT_VERSION=" in line or "[string]$Version =" in line)
            for changed in (original.replace(declaration, "# missing declaration"),
                            original + "\n" + declaration + "\n"):
                with self.subTest(name=name, changed=changed[-50:]):
                    source.write_text(changed)
                    with self.assertRaisesRegex(renderer.RenderError, "exactly one"):
                        renderer.render("v9.8.7", self.source, self.output)
                    self.assertFalse(self.output.exists())
            source.write_text(original)

    def test_rejects_source_overwrite_and_output_symlink(self):
        original = (self.source / "install-mss.sh").read_bytes()
        with self.assertRaisesRegex(renderer.RenderError, "overwrite or link"):
            renderer.render("v9.8.7", self.source, self.source)
        self.output.mkdir()
        (self.output / "install-mss.sh").symlink_to(self.source / "install-mss.sh")
        with self.assertRaisesRegex(renderer.RenderError, "overwrite or link"):
            renderer.render("v9.8.7", self.source, self.output)
        self.assertEqual((self.source / "install-mss.sh").read_bytes(), original)

    def test_atomic_replacement_does_not_modify_a_hardlinked_source(self):
        self.output.mkdir()
        original = (self.source / "install-mss.sh").read_bytes()
        os.link(self.source / "install-mss.sh", self.output / "install-mss.sh")
        renderer.render("v9.8.7", self.source, self.output)
        self.assertEqual((self.source / "install-mss.sh").read_bytes(), original)

    @unittest.skipUnless(shutil.which("bash"), "Bash is required for installer behavior")
    def test_rendered_default_downloads_exact_tag_and_rejects_tampered_archive(self):
        for version in ("v9.8.7", "v9.8.8"):
            with self.subTest(version=version):
                renderer.render(version, self.source, self.output)
                result = subprocess.run(
                    ["bash", str(ROOT / "tools/install/test-install-mss.sh")],
                    env={**os.environ, "MSS_INSTALLER_TEST_PATH": str(self.output / "install-mss.sh"),
                         "MSS_INSTALLER_TEST_VERSION": version},
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("PASS install-mss checksum", result.stdout)
                self.assertIn("tamper rejection", result.stdout)


if __name__ == "__main__":
    unittest.main()
