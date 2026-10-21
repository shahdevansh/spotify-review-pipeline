"""Offline regression tests; no deployed API or model requests."""
import copy
import csv
import gzip
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlsplit

SPEC = importlib.util.spec_from_file_location('reconcile_hero_publication', Path(__file__).resolve().parents[1] / 'tools/reconcile_hero_publication.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def write_csv(path, rows, fields):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


class Fixture:
    def __init__(self, root, compressed=False):
        self.root = root
        self.rows = []
        for index in range(103):
            row = dict(review_id=f'r-{index:03}', review_text='Music interrupted\n音楽 🎵' if index < 101 else 'Love music' if index == 101 else '',
                       review_rating='2', review_likes='0', app_version='1.0', review_timestamp='2026-01-01',
                       status='completed' if index < 102 else 'quarantined')
            if index < 102:
                row.update(topic='playback', intent='complaint' if index < 101 else 'praise', severity=3, sentiment=-.5,
                           entities=[], evidence_quote=row['review_text'], needs_review=False, label_config='fixture-v1',
                           provider='fixture', model='fixture', confidence=.8)
                if index == 1: row['cache_source_id'] = 'r-000'
            else:
                row['reason'] = 'empty_text'
            row['source_sha256'] = m.source_hash(row)
            self.rows.append(row)
        self.summary = dict(run_id='fixture-run', input_count=103, completed=102, quarantined=1, pending=0)
        self.expectations = dict(input_count=103, completed=102, quarantined=1, pending=0,
                                 total_rows=120, nonempty_rows=119, empty_rows=1, audited=20)
        self.evaluation = dict(n=20, verified_count=20, failed=0, ground_truth=False,
                               comparison_type='independent_model_agreement')
        for field in ('topic', 'intent', 'severity'):
            self.evaluation[field] = dict(matches=20, denominator=20, agreement=1.)
        seed = 'fixture-audit-v1'
        eligible = sorted(self.rows[:102], key=lambda r: m.hashlib.sha256(f"{seed}:{r['review_id']}".encode()).digest())[:20]
        verification = [dict(review_id=r['review_id'], status='completed', blind=True, differences={}, seed=seed,
                             sampling_method='seeded_sha256_without_replacement') for r in eligible]
        self.issues = [dict(issue_id='issue-a', name='Playback', description='Evidence'), dict(issue_id='issue-b', name='Other playback', description='Evidence')]
        self.ranking = [dict(rank=1, issue_id='issue-a', complaint_count=60, severity_sum=180, mean_severity='3.000000', priority_score=180),
                        dict(rank=2, issue_id='issue-b', complaint_count=41, severity_sum=123, mean_severity='3.000000', priority_score=123)]
        self.membership = [dict(review_id=r['review_id'], issue_id='issue-a' if i < 60 else 'issue-b') for i, r in enumerate(self.rows[:101])]
        self.claims = [dict(claim_id='claim-a', issue_id='issue-a', metric='severity_sum', value='180')]
        self.recommendations = {'priority_issue_id': 'issue-a', 'recommendations': [{'title': 'Improve playback', 'claim_ids': ['claim-a']}], 'alternatives': []}
        self.ingestion = {'counts': {'records': 120, 'empty_review_text': 1}}
        for name, value in [('run_summary.json', self.summary), ('evaluation.json', self.evaluation), ('issues.json', self.issues),
                            ('recommendations.json', self.recommendations), ('ingestion.json', self.ingestion)]:
            (root / name).write_text(json.dumps(value))
        for name, rows in [('records.jsonl', self.rows), ('verification.jsonl', verification)]:
            body = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)
            if compressed:
                with gzip.open(root / (name + '.gz'), 'wt', encoding='utf-8') as stream: stream.write(body)
            else:
                (root / name).write_text(body)
        write_csv(root / 'ranking.csv', self.ranking, list(self.ranking[0]))
        write_csv(root / 'membership.csv', self.membership, list(self.membership[0]))
        write_csv(root / 'claims.csv', self.claims, list(self.claims[0]))

    def expected(self):
        return m.load_expected(self.root, self.root / 'ingestion.json', self.expectations, sample_size=6)


class FakeClient:
    base_url = 'https://fixture.invalid'
    def __init__(self, fixture, mutation=None):
        self.fixture = fixture; self.mutation = mutation
        self.requests = self.retries = self.bytes = 0
        self.paths = []; self.lock = threading.Lock(); self.overviews = 0
        self.rows = {r['review_id']: m.public_record(r) for r in fixture.rows}

    def get(self, path):
        with self.lock:
            self.requests += 1; self.paths.append(path)
        parts = urlsplit(path)
        if parts.path == '/api/overview':
            self.overviews += 1
            body = dict(status='ready', run={**self.fixture.summary, 'imported_rows': 103},
                        source=dict(total_rows=120, nonempty_rows=119, empty_rows=1), evaluation=self.fixture.evaluation,
                        claims=self.fixture.claims, storage={'bytes': 20000})
        elif parts.path == '/api/issues':
            body = dict(status='ready', run_id='fixture-run', issues=[{**row, **self.fixture.issues[i], 'mean_severity': 3.0} for i, row in enumerate(self.fixture.ranking)])
        elif parts.path == '/api/recommendations':
            body = dict(status='ready', run_id='fixture-run', document=self.fixture.recommendations)
        elif parts.path.startswith('/api/reviews/'):
            body = dict(status='ready', run_id='fixture-run', review=self.rows[unquote(parts.path.rsplit('/', 1)[1])])
        else:
            issue_id = unquote(parts.path.split('/')[3]); offset = int(parse_qs(parts.query).get('cursor', ['0'])[0])
            members = [item['review_id'] for item in self.fixture.membership if item['issue_id'] == issue_id]
            body = dict(status='ready', run_id='fixture-run', issue_id=issue_id,
                        reviews=[self.rows[rid] for rid in members[offset:offset + 50]],
                        next_cursor=str(offset + 50) if offset + 50 < len(members) else None)
        body = copy.deepcopy(body)
        if self.mutation: self.mutation(path, body, self)
        return body


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='spotify-reconcile-')
        self.root = Path(self.directory.name)
    def tearDown(self):
        self.directory.cleanup()
    def make(self, mutation=None, compressed=False):
        fixture = Fixture(self.root, compressed)
        expected = fixture.expected(); client = FakeClient(fixture, mutation)
        return fixture, expected, client
    def test_all_members_and_details_pass_gzip(self):
        _, expected, client = self.make(compressed=True)
        report = m.reconcile(expected, client)
        self.assertEqual(report['status'], 'pass', report)
        self.assertEqual(sum(row['observed_unique_members'] for row in report['issue_pagination']), 101)
        self.assertEqual(sum(row['pages'] for row in report['issue_pagination']), 3)
        self.assertEqual(set(report['sample_categories']), {'original', 'alias', 'quarantined'})
    def test_plain_exports_pass(self):
        _, expected, client = self.make()
        self.assertEqual(m.reconcile(expected, client)['status'], 'pass')
    def test_old_run_fails_before_pagination(self):
        def mutate(path, body, client):
            if path == '/api/overview': body['run']['run_id'] = 'old-pilot'
        _, expected, client = self.make(mutate)
        report = m.reconcile(expected, client)
        self.assertEqual(report['status'], 'fail')
        self.assertEqual(client.paths, ['/api/overview'])
    def test_missing_duplicate_members_are_detected(self):
        def mutate(path, body, client):
            if '/issue-a/reviews?cursor=' in path: body['reviews'][0] = copy.deepcopy(client.rows['r-000'])
        _, expected, client = self.make(mutate)
        report = m.reconcile(expected, client)
        issue = next(row for row in report['issue_pagination'] if row['issue_id'] == 'issue-a')
        self.assertFalse(issue['passed'])
        self.assertEqual(issue['errors']['missing_member'], 1)
        self.assertEqual(issue['errors']['duplicate_id'], 1)
    def test_returned_source_and_provenance_mismatch(self):
        def mutate(path, body, client):
            if path == '/api/issues/issue-b/reviews':
                body['reviews'][0]['review_text'] = 'tampered'
                body['reviews'][1]['provenance']['model'] = 'substituted'
        _, expected, client = self.make(mutate)
        report = m.reconcile(expected, client)
        issue = next(row for row in report['issue_pagination'] if row['issue_id'] == 'issue-b')
        self.assertEqual(issue['errors']['record_mismatch'], 2)
        self.assertEqual(issue['errors']['source_hash_mismatch'], 1)
    def test_rank_and_six_decimal_mean_are_exact(self):
        def mutate(path, body, client):
            if path == '/api/issues': body['issues'][0]['mean_severity'] = 3.000001
        _, expected, client = self.make(mutate)
        self.assertFalse(m.reconcile(expected, client)['checks']['ranking'])
    def test_claim_and_recommendation_changes_fail(self):
        def mutate(path, body, client):
            if path == '/api/overview': body['claims'][0]['value'] = '181'
            if path == '/api/recommendations': body['document']['priority_issue_id'] = 'issue-b'
        _, expected, client = self.make(mutate)
        report = m.reconcile(expected, client)
        self.assertFalse(report['checks']['claims']); self.assertFalse(report['checks']['recommendations'])
    def test_quarantine_detail_change_fails(self):
        def mutate(path, body, client):
            if path == '/api/reviews/r-102': body['review']['reason'] = 'wrong reason'
        _, expected, client = self.make(mutate)
        self.assertFalse(m.reconcile(expected, client)['checks']['review_details_and_provenance'])
    def test_cursor_loop_fails_bounded(self):
        def mutate(path, body, client):
            if path.startswith('/api/issues/issue-a/reviews'): body['next_cursor'] = '0'
        _, expected, client = self.make(mutate)
        report = m.reconcile(expected, client)
        self.assertFalse(report['checks']['complete_issue_pagination'])
        self.assertLess(client.requests, 25)
    def test_run_switch_is_detected(self):
        def mutate(path, body, client):
            if path == '/api/overview' and client.overviews > 1: body['run']['run_id'] = 'replacement'
        _, expected, client = self.make(mutate)
        self.assertFalse(m.reconcile(expected, client)['checks']['run_stayed_current'])
    def test_local_hash_corruption_rejected(self):
        fixture = Fixture(self.root)
        path = self.root / 'records.jsonl'; rows = list(m.read_jsonl(path)); rows[0]['review_text'] = 'corrupt'
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaisesRegex(ValueError, 'source hash'): fixture.expected()
    def test_audit_count_and_seeded_ids_are_verified(self):
        fixture = Fixture(self.root)
        path = self.root / 'verification.jsonl'; rows = list(m.read_jsonl(path)); rows[1]['review_id'] = rows[0]['review_id']
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaisesRegex(ValueError, 'audit'): fixture.expected()
    def test_numeric_normalization_preserves_types(self):
        self.assertEqual(m.digest({'x': 3}), m.digest({'x': 3.0}))
        self.assertEqual(m.digest({'x': -0.0}), m.digest({'x': 0}))
        self.assertNotEqual(m.digest({'x': True}), m.digest({'x': 1}))
        self.assertNotEqual(m.digest({'x': '3'}), m.digest({'x': 3}))
    def test_http_503_retries_then_success(self):
        client = m.APIClient('https://fixture.invalid', attempts=2)
        error = HTTPError('https://fixture.invalid/api/overview', 503, 'warming', {}, None)
        response = io.BytesIO(b'{"status":"ready"}')
        with patch.object(m, 'urlopen', side_effect=[error, response]) as mocked, patch.object(m.time, 'sleep'):
            self.assertEqual(client.get('/api/overview'), {'status': 'ready'})
        self.assertEqual((client.requests, client.retries), (2, 1))
        self.assertTrue(all(call.args[0].get_method() == 'GET' for call in mocked.call_args_list))
    def test_credential_urls_rejected(self):
        with self.assertRaises(ValueError): m.APIClient('https://user:secret@fixture.invalid')


if __name__ == '__main__':
    unittest.main()
