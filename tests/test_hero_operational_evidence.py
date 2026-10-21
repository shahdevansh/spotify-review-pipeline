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
