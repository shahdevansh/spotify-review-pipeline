import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spotify_pipeline import storage


class JSONLShortReadTests(unittest.TestCase):
    def test_empty_and_unicode_plain_gzip_remain_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".jsonl", ".jsonl.gz"):
                path = Path(directory) / ("rows" + suffix)
                storage.atomic_jsonl(path, [])
                self.assertEqual(list(storage.read_jsonl(path)), [])
                values = [{"text": "é🎵\n你好", "id": 1}]
                storage.atomic_jsonl(path, values)
                self.assertEqual(list(storage.read_jsonl(path)), values)

    def test_nonempty_plain_file_returning_eof_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.jsonl"
            path.write_text('{"id":1}\n')
            with patch.object(storage, "open_jsonl", return_value=io.StringIO("")):
                with self.assertRaisesRegex(OSError, "hydrate the exact file"):
                    list(storage.read_jsonl(path))

    def test_partial_plain_file_read_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.jsonl"
            path.write_text('{"id":1}\n{"id":2}\n')
            with patch.object(storage, "open_jsonl", return_value=io.StringIO('{"id":1}\n')):
                with self.assertRaisesRegex(OSError, "Incomplete JSONL read"):
                    list(storage.read_jsonl(path))


if __name__ == "__main__":
    unittest.main()
