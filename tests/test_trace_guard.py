"""Synthetic trace-archive integrity tests; no uploads, models, or source data."""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

import pytest


def guard_module(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / 'tools/trace_guard.py'
    spec = importlib.util.spec_from_file_location('synthetic_trace_guard', script)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    base = tmp_path / 'runs/hero-v1'
    monkeypatch.setattr(guard, 'BASE', base)
    monkeypatch.setattr(guard, 'ARCH', base / 'trace-archives')
    folder = base / 'run/handoffs'
    folder.mkdir(parents=True)
    pair = (folder / 'synthetic.request.json.gz', folder / 'synthetic.response.json.gz')
    values = (gzip.compress(b'{"request":"cafe"}', mtime=0), gzip.compress(b'{"response":"ok"}', mtime=0))
    for path, content in zip(pair, values):
        path.write_bytes(content)
        os.utime(path, (time.time()-200, time.time()-200))
    return guard, folder, pair, values


@pytest.mark.parametrize('read_kind', ['empty', 'short'])
def test_source_short_read_never_archives_or_deletes(tmp_path, monkeypatch, read_kind):
    guard, folder, pair, values = guard_module(tmp_path, monkeypatch)
    original = Path.read_bytes
    def faulty_read(path):
        data = original(path)
        return (b'' if read_kind == 'empty' else data[:-1]) if path == pair[0] else data
    monkeypatch.setattr(Path, 'read_bytes', faulty_read)
    with pytest.raises(OSError, match='Incomplete or empty read'):
        guard.compact(folder)
    assert [original(path) for path in pair] == list(values)
    assert not list(guard.ARCH.glob('*.tar'))
    assert not list(guard.ARCH.glob('*.tmp'))


@pytest.mark.parametrize('content', [b'not gzip', gzip.compress(b'{broken json}', mtime=0)])
def test_corrupt_gzip_or_json_preserves_both_sources(tmp_path, monkeypatch, content):
    guard, folder, pair, values = guard_module(tmp_path, monkeypatch)
    pair[0].write_bytes(content)
    with pytest.raises((OSError, ValueError, EOFError)):
        guard.compact(folder)
    assert pair[0].read_bytes() == content
    assert pair[1].read_bytes() == values[1]
    assert not list(guard.ARCH.glob('*.tar'))


def test_archive_short_read_preserves_sources(tmp_path, monkeypatch):
    guard, folder, pair, values = guard_module(tmp_path, monkeypatch)
    original = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda path: b'' if path.name.endswith('.tar.tmp') else original(path))
    with pytest.raises(OSError, match='Incomplete or empty read'):
        guard.compact(folder)
    assert [original(path) for path in pair] == list(values)
    assert not list(guard.ARCH.glob('*.tar'))


def test_source_changed_after_archive_readback_keeps_entire_pair(tmp_path, monkeypatch):
    guard, folder, pair, values = guard_module(tmp_path, monkeypatch)
    original_verify = guard.verify_archive
    changed = gzip.compress(b'{"request":"changed"}', mtime=0)
    def verify_and_change(path, manifest):
        result = original_verify(path, manifest)
        pair[0].write_bytes(changed)
        return result
    monkeypatch.setattr(guard, 'verify_archive', verify_and_change)
    receipt = guard.compact(folder)
    assert pair[0].read_bytes() == changed and pair[1].read_bytes() == values[1]
    assert receipt['deleted_source_paths'] == []
    assert len(receipt['retained_changed_source_paths']) == 2
    assert receipt['local_readback_verified'] is True


def test_receipt_failure_never_deletes_sources(tmp_path, monkeypatch):
    guard, folder, pair, values = guard_module(tmp_path, monkeypatch)
    replace = guard.os.replace
    def fail_receipt(source, destination):
        if Path(destination).suffix == '.json':
            raise OSError('synthetic receipt failure')
        return replace(source, destination)
    monkeypatch.setattr(guard.os, 'replace', fail_receipt)
    with pytest.raises(OSError, match='synthetic receipt failure'):
        guard.compact(folder)
    assert [path.read_bytes() for path in pair] == list(values)
    assert not list(guard.ARCH.glob('*.json'))


def test_valid_pair_readback_and_remote_receipt_preserved_on_identical_retry(tmp_path, monkeypatch):
    guard, folder, pair, values = guard_module(tmp_path, monkeypatch)
    receipt = guard.compact(folder)
    archive = Path(receipt['archive'])
    assert receipt['archive_bytes'] == archive.stat().st_size
    assert receipt['sha256'] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert guard.verify_archive(archive, receipt['members']) == (receipt['sha256'], receipt['archive_bytes'])
    assert not any(path.exists() for path in pair)
    assert len(receipt['deleted_source_paths']) == 2
    receipt['remote_verified'] = True
    receipt['remote_verification_note'] = 'synthetic checked remote copy'
    receipt_path = archive.with_suffix('.json')
    receipt_path.write_text(json.dumps(receipt))
    for path, content in zip(pair, values):
        path.write_bytes(content)
        os.utime(path, (time.time()-200, time.time()-200))
    retried = guard.compact(folder)
    assert retried['sha256'] == receipt['sha256']
    assert retried['remote_verified'] is True
    assert retried['remote_verification_note'] == receipt['remote_verification_note']
    assert not any(path.exists() for path in pair)
    assert not list(guard.ARCH.glob('*.tmp'))
