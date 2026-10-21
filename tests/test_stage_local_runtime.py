"""Offline safety checks for the resident runtime staging helper."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/stage_local_runtime.py"
SPEC = importlib.util.spec_from_file_location("stage_local_runtime", MODULE_PATH)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class LocalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / "source"
        self.destination = self.base / "runtime"
        for relative in runtime.REQUIRED:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n" if path.suffix == ".json" else "fixture\n")
        (self.source / "prompts").mkdir()
        (self.source / "prompts/labels.md").write_text("rubric\n")
        (self.source / "data/hero-v1.sqlite3").write_bytes(b"fixture database")
        (self.source / "data/spend.sqlite3").write_bytes(b"fixture ledger")
        (self.source / "runs").mkdir()
        (self.source / "evals").mkdir()
        (self.source / ".git").mkdir()
        (self.source / ".env").write_text("DUMMY_TOKEN=not-a-real-secret\n")

    def tearDown(self):
        self.temporary.cleanup()

    def test_verified_inputs_canonical_storage_and_private_credentials(self):
        result = runtime.stage(self.source, self.destination, refresh=False, copy_env=True)
        for relative in runtime.INPUTS:
            self.assertEqual(runtime.digest(self.source / relative), runtime.digest(self.destination / relative))
            self.assertFalse((self.destination / relative).is_symlink())
        for relative in ("runs", "evals", "data/hero-v1.sqlite3", "data/spend.sqlite3"):
            self.assertEqual((self.destination / relative).resolve(), self.source / relative)
        self.assertEqual((self.destination / ".env").stat().st_mode & 0o777, 0o600)
        manifest = (self.destination / runtime.MANIFEST).read_text()
        self.assertNotIn("not-a-real-secret", manifest + json.dumps(result))
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(runtime.stage(self.source, self.destination, refresh=False, copy_env=True)["replaced_files"], 0)

    def test_refresh_required_and_preserves_unrelated_files(self):
        runtime.stage(self.source, self.destination, refresh=False, copy_env=False)
        self.assertTrue((self.destination / ".env").is_symlink())
        changed = "tools/run_hero.py"
        previous = (self.destination / changed).read_text()
        (self.source / changed).write_text("changed\n")
        (self.destination / "personal-note.txt").write_text("keep me")
        with self.assertRaisesRegex(ValueError, "explicit --refresh"):
            runtime.stage(self.source, self.destination, refresh=False, copy_env=False)
        self.assertEqual((self.destination / changed).read_text(), previous)
        runtime.stage(self.source, self.destination, refresh=True, copy_env=False)
        self.assertEqual((self.destination / changed).read_text(), "changed\n")
        self.assertEqual((self.destination / "personal-note.txt").read_text(), "keep me")
        self.assertEqual((self.source / "data/spend.sqlite3").read_bytes(), b"fixture ledger")

    def test_rejects_unsafe_destination_and_directory_links(self):
        with self.assertRaisesRegex(ValueError, "non-nested"):
            runtime.stage(self.source, self.source / "nested", refresh=False, copy_env=False)
        self.destination.mkdir()
        (self.destination / "src").symlink_to(self.source / "src", target_is_directory=True)
        original = (self.source / "src/spotify_pipeline/engine.py").read_text()
        with self.assertRaisesRegex(ValueError, "directory symlink"):
            runtime.stage(self.source, self.destination, refresh=True, copy_env=False)
        self.assertEqual((self.source / "src/spotify_pipeline/engine.py").read_text(), original)


if __name__ == "__main__":
    unittest.main()
