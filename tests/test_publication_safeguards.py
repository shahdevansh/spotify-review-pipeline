"""Synthetic offline publication tests; no provider calls or real database writes."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import pytest

from spotify_pipeline import database
from test_database import synthetic_bundle
from test_hero_gzip_tools import prepare_package_fixture


def snapshot_support(root):
    for name in ('configuration.json', 'run_summary.json'):
        (root / 'runs/hero-v1/recovery' / name).write_text(json.dumps({'synthetic': True}))
    destination = root / 'runtime-evidence/publication-support'
    sources = [p for folder in ('evals/hero-pilot', 'runs/hero-v1/recovery')
               for p in (root / folder).rglob('*') if p.is_file()]
    sources.append(root / 'runs/hero-v1/recovery.cast')
    files = {}
    for source in sources:
        relative = str(source.relative_to(root))
        copied = destination / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        copied.write_bytes(data)
        files[relative] = {'resident_path': str(copied), 'source_path': str(source),
                          'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    manifest = {'version': 'resident-publication-support-v1', 'status': 'ready',
                'pending': [], 'files': files}
    (destination / 'manifest.json').write_text(json.dumps(manifest))
    return destination, manifest


def test_package_uses_verified_resident_frozen_files_when_originals_unavailable(tmp_path, monkeypatch):
    hero, base = prepare_package_fixture(tmp_path, monkeypatch)
    support, _ = snapshot_support(tmp_path)
    expected = (support / 'evals/hero-pilot/cold100/report.json').read_bytes()
    # An unavailable/offloaded original must never be opened during packaging.
    shutil.rmtree(tmp_path / 'evals/hero-pilot')
    shutil.rmtree(base / 'recovery')
    (base / 'recovery.cast').unlink()
    archive = hero.package_evidence()
    with zipfile.ZipFile(archive) as result:
        assert result.read('cost/report.json') == expected
        assert result.read('evals/hero-pilot/cold100/report.json') == expected
        assert 'recovery/calls.jsonl.gz' in result.namelist()
        assert 'resident-publication-support.json' in result.namelist()


@pytest.mark.parametrize('damage', ['missing_file', 'same_size_corruption', 'size_mismatch', 'missing_entry'])
def test_package_fails_closed_on_bad_resident_support(tmp_path, monkeypatch, damage):
    hero, base = prepare_package_fixture(tmp_path, monkeypatch)
    support, manifest = snapshot_support(tmp_path)
    archive = hero.package_evidence()
    original_archive = archive.read_bytes()
    key = 'evals/hero-pilot/cold100/report.json'
    artifact = support / key
    if damage == 'missing_file':
        artifact.unlink()
    elif damage == 'same_size_corruption':
        artifact.write_bytes(b'x' * artifact.stat().st_size)
    elif damage == 'size_mismatch':
        artifact.write_bytes(b'{}')
    else:
        manifest['files'].pop(key)
        (support / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match='[Rr]esident publication support'):
        hero.package_evidence()
    assert archive.read_bytes() == original_archive


class FakeCursor:
    def __init__(self, size):
        self.size = size
        self.statements = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def execute(self, sql, parameters=None):
        self.statements.append(sql)
    def executemany(self, sql, rows):
        self.statements.append(sql)
    def copy(self, sql):
        self.statements.append(sql)
        return self
    def write_row(self, row):
        pass
    def fetchone(self):
        return (self.size,)


class FakeConnection:
    def __init__(self, size):
        self.cursor_instance = FakeCursor(size)
        self.committed = False
        self.rolled_back = False
    def __enter__(self):
        return self
    def __exit__(self, exc_type, value, traceback):
        self.committed = exc_type is None
        self.rolled_back = exc_type is not None
        return False
    def cursor(self):
        return self.cursor_instance


def fake_import(monkeypatch, size):
    import psycopg
    connection = FakeConnection(size)
    monkeypatch.setattr(psycopg, 'connect', lambda *args, **kwargs: connection)
    monkeypatch.setattr(database, 'load_run', lambda *args, **kwargs: synthetic_bundle())
    return connection


def test_oversized_import_raises_inside_transaction_and_rolls_back(monkeypatch, tmp_path):
    connection = fake_import(monkeypatch, 700_000_001)
    with pytest.raises(ValueError, match='publication rolled back'):
        database.import_run(tmp_path, 'synthetic-no-network', max_storage_bytes=700_000_000)
    assert connection.rolled_back
    assert not connection.committed
    assert any('UPDATE spotify_runs SET is_current' in sql for sql in connection.cursor_instance.statements)
    assert any('pg_total_relation_size' in sql for sql in connection.cursor_instance.statements)


@pytest.mark.parametrize('limit,size', [(700_000_000, 700_000_000), (None, 900_000_000)])
def test_storage_limit_boundary_and_legacy_default_commit(monkeypatch, tmp_path, limit, size):
    connection = fake_import(monkeypatch, size)
    result = database.import_run(tmp_path, 'synthetic-no-network', max_storage_bytes=limit)
    assert result['storage_bytes'] == size
    assert connection.committed and not connection.rolled_back


def test_invalid_storage_limit_rejected_before_loading_or_connection(monkeypatch, tmp_path):
    monkeypatch.setattr(database, 'load_run', lambda *args, **kwargs: pytest.fail('Must validate first'))
    with pytest.raises(ValueError, match='positive integer'):
        database.import_run(tmp_path, 'synthetic-no-network', max_storage_bytes=True)
