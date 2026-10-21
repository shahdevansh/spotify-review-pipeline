"""Synthetic-only checks for explicitly selected operational release proofs."""
import json
import hashlib
import zipfile
import pytest

from test_hero_gzip_tools import prepare_package_fixture

OPTIONAL = (
    "audit-timeout-stop.json", "audit-timeout-repair.json", "operational-final.json",
    "audit-timeout-timing-and-budget.json", "audit-timeout-shutdown-audit.json",
    "audit-timeout-post-restart-timing.json",
)


def test_package_includes_only_explicit_operational_proofs(tmp_path, monkeypatch):
    hero, base = prepare_package_fixture(tmp_path, monkeypatch)
    expected = {}
    for name in OPTIONAL:
        expected[name] = json.dumps({"synthetic": True, "proof": name}).encode()
        (base / name).write_bytes(expected[name])
    (base / "audit-timeout-unapproved.json").write_text('{"private_synthetic": true}')
    private = base / "audit-timeout-private"
    private.mkdir()
    (private / "annotations.json").write_text('{"private_synthetic": true}')
    with zipfile.ZipFile(hero.package_evidence()) as archive:
        assert all(archive.read(name) == data for name, data in expected.items())
        assert "audit-timeout-unapproved.json" not in archive.namelist()
        assert not any(name.startswith("audit-timeout-private/") for name in archive.namelist())


def test_package_allows_optional_operational_proofs_to_be_absent(tmp_path, monkeypatch):
    hero, base = prepare_package_fixture(tmp_path, monkeypatch)
    with zipfile.ZipFile(hero.package_evidence()) as archive:
        assert all(name not in archive.namelist() for name in OPTIONAL)
        assert "checker.json" in archive.namelist()
        assert "editorial-review.json" not in archive.namelist()
        assert not any(name.startswith("editorial-review/") for name in archive.namelist())


def test_package_preserves_editorial_review_evidence_and_required_roots(tmp_path, monkeypatch):
    hero, base = prepare_package_fixture(tmp_path, monkeypatch)
    out = base / "run"
    editorial = out / "editorial-review"
    editorial.mkdir()
    manifest = b'{"synthetic":true,"production_labels_unchanged":true}'
    (out / "editorial-review.json").write_bytes(manifest)
    originals = {"original-issues.json": b'{"synthetic_original":"issues"}',
                 "original-recommendations.json": b'{"synthetic_original":"recommendations"}',
                 "original-memo.md": b"Synthetic original memo\n",
                 "correction-evidence.json": b'{"synthetic_correction":true}'}
    for name, data in originals.items():
        (editorial / name).write_bytes(data)
    (out / "editorial-private.json").write_text('{"synthetic_excluded":true}')
    with zipfile.ZipFile(hero.package_evidence()) as archive:
        assert archive.read("editorial-review.json") == manifest
        assert all(archive.read("editorial-review/" + name) == data for name, data in originals.items())
        assert "editorial-private.json" not in archive.namelist()
        for prefix in ("grading/", "cost/", "evals/", "recovery/"):
            assert any(name.startswith(prefix) for name in archive.namelist())
        assert "handoffs/memo.output.json" in archive.namelist()
        assert "memo.md" in archive.namelist()


def test_resident_proof_mapping_preserves_originals_and_records_provenance(tmp_path, monkeypatch):
    hero, base = prepare_package_fixture(tmp_path, monkeypatch)
    cache = tmp_path / "runtime-evidence/final-publication-optionals"
    cache.mkdir(parents=True)
    artifacts = {}
    expected = {}
    for name in ("admission-performance-proof.json", "operational-performance.json"):
        raw = json.dumps({"synthetic_frozen": name}).encode()
        (cache / name).write_bytes(raw)
        expected[name] = raw
        artifacts[name] = {"action": "resident_snapshot", "size_bytes": len(raw),
                           "sha256": hashlib.sha256(raw).hexdigest(),
                           "selected_source": "evals/hero-pilot/" + name}
        (base / name).symlink_to(cache / name)
    artifacts["runtime-upgrade-60000.json"] = {"action": "omitted", "reason": hero.OPTIONAL_OMISSION_REASON}
    manifest = {"schema_version": "final-publication-availability-v1", "status": "ready", "artifacts": artifacts}
    (cache / "manifest.json").write_text(json.dumps(manifest))
    with zipfile.ZipFile(hero.package_evidence()) as archive:
        assert all(archive.read(name) == raw for name, raw in expected.items())
        assert "runtime-upgrade-60000.json" not in archive.namelist()
        assert json.loads(archive.read("publication-artifact-availability.json")) == manifest
    assert all((base / name).is_symlink() for name in expected)
    (cache / "admission-performance-proof.json").write_text("corrupt")
    with pytest.raises(RuntimeError, match="snapshot integrity"):
        hero.package_evidence()


def test_availability_manifest_cannot_omit_required_evidence(tmp_path, monkeypatch):
    hero, base = prepare_package_fixture(tmp_path, monkeypatch)
    cache = tmp_path / "runtime-evidence/final-publication-optionals"
    cache.mkdir(parents=True)
    (cache / "manifest.json").write_text(json.dumps({"schema_version": "final-publication-availability-v1", "status": "ready",
        "artifacts": {"checker.json": {"action": "omitted", "reason": "synthetic prohibited omission"}}}))
    with pytest.raises(RuntimeError, match="omit protected evidence"):
        hero.package_evidence()


def test_explicit_final_validation_and_business_audit_paths(tmp_path, monkeypatch):
    hero, base = prepare_package_fixture(tmp_path, monkeypatch)
    validation = base / "final-validation"
    validation.mkdir()
    (validation / "offline-validation.json").write_text('{"synthetic_pass":true}')
    public = tmp_path / "evals/hero"
    public.mkdir(parents=True)
    for name in ("business-audit.json", "business-audit.md", "editorial-review.json"):
        (public / name).write_text("synthetic " + name)
    (public / "private-unapproved.json").write_text('{"synthetic_excluded":true}')
    with zipfile.ZipFile(hero.package_evidence()) as archive:
        names = archive.namelist()
        assert "validation/offline-validation.json" in names
        assert all("evals/hero/" + name in names for name in ("business-audit.json", "business-audit.md", "editorial-review.json"))
        assert "evals/hero/private-unapproved.json" not in names
        assert names.count("evals/hero/evaluation.json") == 1
        assert all(any(name.startswith(prefix) for name in names) for prefix in ("grading/", "cost/", "evals/", "recovery/"))


def test_availability_manifest_rejects_unexpected_names(tmp_path, monkeypatch):
    hero, base = prepare_package_fixture(tmp_path, monkeypatch)
    cache = tmp_path / "runtime-evidence/final-publication-optionals"
    cache.mkdir(parents=True)
    (cache / "manifest.json").write_text(json.dumps({"schema_version": "final-publication-availability-v1", "status": "ready",
        "artifacts": {"unapproved.json": {"action": "omitted", "reason": "not allowed"}}}))
    with pytest.raises(RuntimeError, match="Unexpected names"):
        hero.package_evidence()


@pytest.mark.parametrize('kind', ['unknown_file','nested_file','symlink'])
def test_validation_directory_rejects_unapproved_contents(tmp_path, monkeypatch, kind):
    hero, base = prepare_package_fixture(tmp_path, monkeypatch)
    validation=base/'final-validation';validation.mkdir()
    if kind=='unknown_file':(validation/'private-labels.json').write_text('synthetic private')
    elif kind=='nested_file':
        (validation/'private').mkdir();(validation/'private'/'manifest.json').write_text('synthetic private')
    else:(validation/'manifest.json').symlink_to(base/'checker.json')
    with pytest.raises(RuntimeError,match='Unexpected file, directory or symlink'):
        hero.package_evidence()


@pytest.mark.parametrize('location', ['root','artifact','validation','notes'])
def test_availability_rejects_arbitrary_metadata_payloads(tmp_path, monkeypatch, location):
    hero, base = prepare_package_fixture(tmp_path, monkeypatch)
    value={'schema_version':'final-publication-availability-v1','status':'ready','artifacts':{},'final_validation':{}}
    if location=='root':value['private_annotations']={'synthetic':'private'}
    elif location=='artifact':value['artifacts']['projection.json']={'action':'resident_snapshot','size_bytes':1,'sha256':'a'*64,'private_annotations':{}}
    elif location=='validation':value['final_validation']['manifest.json']={'size_bytes':1,'sha256':'a'*64,'private_annotations':{}}
    else:value['notes']=['arbitrary unreviewed private payload']
    with pytest.raises(RuntimeError,match='Unexpected'):
        hero.validate_publication_availability(value)


@pytest.mark.parametrize('name',['private-labels.json','../manifest.json','private/manifest.json'])
def test_availability_rejects_unapproved_validation_paths(tmp_path, monkeypatch, name):
    hero, base=prepare_package_fixture(tmp_path,monkeypatch)
    value={'schema_version':'final-publication-availability-v1','status':'ready','artifacts':{},
           'final_validation':{name:{'size_bytes':1,'sha256':'a'*64}}}
    with pytest.raises(RuntimeError,match='Unexpected final validation filenames'):
        hero.validate_publication_availability(value)
