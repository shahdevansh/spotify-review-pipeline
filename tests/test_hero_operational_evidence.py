"""Synthetic-only checks for explicitly selected operational release proofs."""
import json
import zipfile

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
