"""Worker limits are bounded operational settings, separate from label identity."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from spotify_pipeline.engine import Engine, fingerprint


def configuration(root, maximum=32):
    return {"_root": str(root), "_prompts": {r: "test prompt" for r in ("labels", "enrich", "fallback", "verify", "group", "memo")},
            "schema_version": "spotify-labels-v1", "prompt_version": "test-v1", "max_workers": maximum,
            "models": {"enrich": "jev-1.13.0", **{r: "gpt-6-luna" for r in ("fallback", "verify", "group", "memo")}},
            "reasoning_effort": {}, "ledger_path": str(root / "ledger.sqlite3")}


class OperationalWorkerTests(unittest.TestCase):
    def test_workers_32_and_fingerprint_stability(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); c = configuration(root)
            self.assertEqual(fingerprint(c), fingerprint({**c, "max_workers": 16}))
            engine = Engine(c, root / "results.sqlite3", root / "run", workers=32)
            self.assertEqual(engine.workers, 32)
            asyncio.run(engine.close())

    def test_hard_and_configured_limits_reject_without_ledger_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for workers, maximum in ((33, 64), (32, 16), (0, 32)):
                with self.assertRaisesRegex(ValueError, "workers must"):
                    Engine(configuration(root, maximum), root / "results.sqlite3", root / "run", workers=workers)
            self.assertFalse((root / "ledger.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
