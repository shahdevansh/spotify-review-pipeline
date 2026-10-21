#!/usr/bin/env python3
"""Read-only reconciliation of the published API against saved hero evidence.

Uses only the Python standard library. Does not load credentials, annotations,
models, or the database. An old/unavailable published run fails before pagination.
Plain and gzip JSONL exports are supported without creating decompressed copies.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import gzip
import hashlib
import heapq
import json
import math
from pathlib import Path
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

SOURCE_FIELDS = ('review_id', 'review_text', 'review_rating', 'review_likes', 'app_version', 'review_timestamp')
REVIEW_FIELDS = (*SOURCE_FIELDS, 'source_sha256', 'status', 'reason', 'topic', 'intent', 'sentiment',
                 'severity', 'entities', 'evidence_quote', 'needs_review', 'label_config', 'cache_source_id', 'provenance')
PROVENANCE_FIELDS = ('model', 'provider', 'route', 'confidence', 'topic_confidence', 'intent_confidence',
                    'severity_confidence', 'request_id', 'fallback_reason', 'classifier_provider', 'classifier_model',
                    'fallback_used', 'uncertainty_score', 'review_reasons', 'confidence_source',
                    'review_flag_interpretation', 'initial_prediction')
DEFAULT_EXPECTATIONS = dict(input_count=200013, completed=200000, quarantined=13, pending=0,
                            total_rows=660622, nonempty_rows=660609, empty_rows=13, audited=40000)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True, allow_nan=False)


def source_hash(record: dict) -> str:
    values = [record[field] for field in SOURCE_FIELDS]
    if not all(isinstance(value, str) for value in values):
        raise ValueError('Source fields must remain original strings')
    return hashlib.sha256(canonical(values).encode()).hexdigest()


def normalized(value: Any) -> Any:
    # JSON/pg may render integral floats as integers. Compare numeric value, while
    # preserving the distinction between a number, a string, a boolean, and null.
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError('Nonfinite JSON number')
        return {'$numeric': '0' if number == 0 else str(number.normalize())}
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(normalized(value)).encode()).hexdigest()


def public_record(record: dict) -> dict:
    projected = {field: record.get(field) for field in REVIEW_FIELDS}
    projected['entities'] = record.get('entities', [])
    projected['provenance'] = {key: record[key] for key in PROVENANCE_FIELDS if key in record}
    return projected


def jsonl_path(path: Path) -> Path:
    if path.exists():
        return path
    alternative = Path(str(path) + '.gz')
    if alternative.exists():
        return alternative
    raise FileNotFoundError(path)


def read_jsonl(path: Path):
    path = jsonl_path(path)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def profile_counts(value: dict) -> dict:
    source = value.get('profile', value)
    source = {**source, **source.get('counts', {})}
    aliases = {
        'total_rows': ('total_rows', 'row_count', 'rows', 'total_records', 'input_count', 'records'),
        'nonempty_rows': ('nonempty_rows', 'nonempty_texts', 'nonempty_review_count'),
        'empty_rows': ('empty_rows', 'empty_texts', 'empty_review_count', 'empty_text_count', 'empty_review_text'),
    }
    result = {}
    for target, keys in aliases.items():
        raw = next((source[key] for key in keys if key in source), None)
        result[target] = int(raw) if raw is not None else None
    if result['nonempty_rows'] is None and None not in (result['total_rows'], result['empty_rows']):
        result['nonempty_rows'] = result['total_rows'] - result['empty_rows']
    return result


def load_expected(run_dir: Path, ingestion_report: Path, expectations: dict, sample_size: int = 12) -> dict:
    summary = json.loads((run_dir / 'run_summary.json').read_text())
    evaluation = json.loads((run_dir / 'evaluation.json').read_text())
    profile = profile_counts(json.loads(ingestion_report.read_text()))
    for key in ('input_count', 'completed', 'quarantined', 'pending'):
        if summary.get(key) != expectations[key]:
            raise ValueError(f'Saved summary {key} does not meet required {expectations[key]}')
    if profile != {key: expectations[key] for key in profile}:
        raise ValueError('Saved full-source counts do not match required counts')
    if evaluation.get('n') != expectations['audited'] or evaluation.get('verified_count') != expectations['audited']:
        raise ValueError('Saved independent evaluation does not meet required audit count')
    if evaluation.get('failed') != 0 or evaluation.get('ground_truth') is not False:
        raise ValueError('Saved evaluation must disclose model comparison and zero unresolved audits')
    if evaluation.get('comparison_type') != 'independent_model_agreement':
        raise ValueError('Saved evaluation is not the independent model-agreement report')
    records = {}
    samples = {}
    category_samples = {}
    counts = Counter()
    sample_heap = []
    for record in read_jsonl(run_dir / 'records.jsonl'):
        review_id = record['review_id']
        if review_id in records or source_hash(record) != record['source_sha256']:
            raise ValueError('Duplicate review ID or changed original source hash in saved records')
        projected = public_record(record)
        records[review_id] = (digest(projected), record['status'], record.get('intent'), record.get('severity'))
        counts[record['status']] += 1
        category = 'quarantined' if record['status'] == 'quarantined' else 'alias' if record.get('cache_source_id') else 'original'
        if category not in category_samples:
            category_samples[category] = review_id
            samples[review_id] = projected
        seed = int(hashlib.sha256(('publication-v1:' + review_id).encode()).hexdigest(), 16)
        if sample_size and (len(sample_heap) < sample_size or seed < -sample_heap[0][0]):
            if len(sample_heap) == sample_size:
                _, evicted = heapq.heappop(sample_heap)
                if evicted not in category_samples.values():
                    samples.pop(evicted, None)
            heapq.heappush(sample_heap, (-seed, review_id))
            samples[review_id] = projected
    if len(records) != summary['input_count'] or any(counts[key] != expectations[key] for key in ('completed', 'quarantined', 'pending')):
        raise ValueError('Saved record identities/statuses do not reconcile to summary')
    # An alias must resolve directly to a saved original with the same published
    # labels; detailed alias-source equality is rechecked on the detail endpoint.
    for record in list(samples.values()):
        source_id = record.get('cache_source_id')
        if source_id and source_id not in records:
            raise ValueError('Sample alias has no saved source')
    wanted_sources = {r['cache_source_id'] for r in samples.values() if r.get('cache_source_id')}
    if wanted_sources:
        for record in read_jsonl(run_dir / 'records.jsonl'):
            if record['review_id'] in wanted_sources:
                samples[record['review_id']] = public_record(record)
    audited_ids = set(); audit_matches = Counter(); audit_seed = None
    for entry in read_jsonl(run_dir / 'verification.jsonl'):
        review_id = entry.get('review_id')
        if (review_id not in records or review_id in audited_ids or records[review_id][1] != 'completed'
                or entry.get('status') != 'completed' or entry.get('blind') is not True
                or entry.get('sampling_method') != 'seeded_sha256_without_replacement'):
            raise ValueError('Saved independent audit has duplicate, foreign, unresolved, or nonblind records')
        seed = entry.get('seed')
        if not isinstance(seed, str) or (audit_seed is not None and seed != audit_seed):
            raise ValueError('Independent audit sampling seed is missing or inconsistent')
        audit_seed = seed; audited_ids.add(review_id)
        for field in ('topic', 'intent', 'severity'):
            if field not in entry['differences'] and 'enrichment_status' not in entry['differences']:
                audit_matches[field] += 1
    if len(audited_ids) != expectations['audited']:
        raise ValueError('Independent audit export count does not match required original IDs')
    seeded_ids = sorted((rid for rid, (_, status, _, _) in records.items() if status == 'completed'),
                        key=lambda rid: hashlib.sha256(f'{audit_seed}:{rid}'.encode()).digest())[:expectations['audited']]
    if set(seeded_ids) != audited_ids:
        raise ValueError('Independent audit IDs do not reproduce the seeded sample')
    for field in ('topic', 'intent', 'severity'):
        metric = evaluation.get(field, {})
        if (metric.get('matches') != audit_matches[field] or metric.get('denominator') != len(audited_ids)
                or metric.get('agreement') != audit_matches[field] / len(audited_ids)):
            raise ValueError('Independent audit metrics do not reproduce from saved comparisons')
    raw_issues = json.loads((run_dir / 'issues.json').read_text())
    if isinstance(raw_issues, dict):
        raw_issues = raw_issues['issues']
    descriptions = {issue['issue_id']: issue for issue in raw_issues}
    issues = []
    for row in read_csv(run_dir / 'ranking.csv'):
        detail = descriptions.get(row['issue_id'], {})
        issues.append({**{key: row[key] for key in ('issue_id', 'mean_severity')},
                       **{key: int(row[key]) for key in ('rank', 'complaint_count', 'severity_sum', 'priority_score')},
                       'name': detail.get('name') or detail.get('title') or row['issue_id'],
                       'description': detail.get('description') or detail.get('summary') or ''})
    issues.sort(key=lambda item: item['rank'])
    if len({item['issue_id'] for item in issues}) != len(issues):
        raise ValueError('Duplicate ranked issues')
    memberships = {item['issue_id']: set() for item in issues}
    member_ids = set()
    severity_sums = Counter()
    for member in read_csv(run_dir / 'membership.csv'):
        review_id, issue_id = member['review_id'], member['issue_id']
        if review_id in member_ids or review_id not in records or issue_id not in memberships:
            raise ValueError('Invalid or duplicate saved issue membership')
        _, status, intent, severity = records[review_id]
        if status != 'completed' or intent not in ('complaint', 'cancellation'):
            raise ValueError('Saved issue contains a non-complaint/cancellation record')
        memberships[issue_id].add(review_id)
        member_ids.add(review_id)
        severity_sums[issue_id] += severity
    expected_members = {review_id for review_id, (_, status, intent, _) in records.items()
                        if status == 'completed' and intent in ('complaint', 'cancellation')}
    if member_ids != expected_members:
        raise ValueError('Saved membership fails complete complaint/cancellation coverage')
    expected_order = sorted(issues, key=lambda item: (-item['priority_score'], item['issue_id']))
    if [item['issue_id'] for item in issues] != [item['issue_id'] for item in expected_order]:
        raise ValueError('Saved ranking order is not baseline score descending / issue ID ascending')
    for rank, issue in enumerate(issues, 1):
        count = len(memberships[issue['issue_id']]); total = severity_sums[issue['issue_id']]
        mean = (Decimal(total) / count if count else Decimal(0)).quantize(Decimal('.000001'), rounding=ROUND_HALF_UP)
        if (issue['rank'], issue['complaint_count'], issue['severity_sum'], issue['priority_score'], Decimal(issue['mean_severity'])) != (rank, count, total, total, mean):
            raise ValueError('Saved issue ranking does not reproduce from records')
    return dict(run_id=summary['run_id'], summary=summary, evaluation=evaluation, profile=profile,
                records=records, samples=samples, category_samples=category_samples, issues=issues,
                membership=memberships, claims=sorted(read_csv(run_dir / 'claims.csv'), key=lambda row: row['claim_id']),
                recommendations=json.loads((run_dir / 'recommendations.json').read_text()), expectations=expectations)


class APIClient:
    """Unauthenticated GET requests, bounded retries for cold starts/transient errors."""
    def __init__(self, base_url: str, timeout: float = 30, attempts: int = 4):
        parsed = urlsplit(base_url)
        if parsed.scheme not in ('https', 'http') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Use an HTTP(S) base URL without credentials, query, or fragment')
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.attempts = attempts
        self.lock = threading.Lock()
        self.requests = self.retries = self.bytes = 0

    def get(self, path: str) -> dict:
        if not path.startswith('/api/'):
            raise ValueError('Only public API reads are supported')
        for attempt in range(self.attempts):
            with self.lock:
                self.requests += 1
            try:
                request = Request(self.base_url + path, headers={'Accept': 'application/json', 'User-Agent': 'spotify-publication-reconciliation/1'}, method='GET')
                with urlopen(request, timeout=self.timeout) as response:
                    body = response.read(16_000_001)
                    if len(body) > 16_000_000:
                        raise ValueError('API response exceeds bounded 16 MB limit')
                    with self.lock:
                        self.bytes += len(body)
                    value = json.loads(body)
                    if not isinstance(value, dict):
                        raise ValueError('API response is not a JSON object')
                    return value
            except HTTPError as error:
                transient = error.code in (408, 429, 500, 502, 503, 504)
                error.close()
                if not transient or attempt + 1 == self.attempts:
                    raise RuntimeError(f'API GET returned HTTP {error.code}') from None
            except (URLError, TimeoutError, ConnectionError):
                if attempt + 1 == self.attempts:
                    raise RuntimeError('API GET exhausted transient transport retries') from None
            with self.lock:
                self.retries += 1
            time.sleep(min(8, 2 ** attempt))
        raise RuntimeError('API retry loop exhausted')


def compare_issues(actual: list, expected: list) -> bool:
    if not isinstance(actual, list) or len(actual) != len(expected):
        return False
    for left, right in zip(actual, expected):
        if not isinstance(left, dict):
            return False
        for field in ('issue_id', 'name', 'description', 'rank', 'complaint_count', 'severity_sum', 'priority_score'):
            if left.get(field) != right[field]:
                return False
        try:
            if Decimal(str(left.get('mean_severity'))) != Decimal(right['mean_severity']):
                return False
        except (ValueError, ArithmeticError):
            return False
    return True


def reconcile(expected: dict, client: APIClient, concurrency: int = 4) -> dict:
    started = time.monotonic()
    report = {'status': 'fail', 'schema_version': 'publication-reconciliation-v1',
              'checked_at': datetime.now(timezone.utc).isoformat(), 'base_url': client.base_url,
              'run_id': expected['run_id'], 'checks': {}, 'errors': [], 'issue_pagination': [],
              'method': 'Unauthenticated read-only API comparison to saved artifacts; every issue member checked, deterministic detail sample.',
              'limitations': ['Model audit agreement is not human accuracy.',
                              'Non-issue review detail endpoints are sampled; overview counts cover all imported records.']}
    checks = report['checks']
    try:
        overview = client.get('/api/overview')
        run = overview.get('run') or {}
        checks['published_run_identity'] = overview.get('status') == 'ready' and run.get('run_id') == expected['run_id']
        checks['selected_counts'] = all(run.get(key) == expected['expectations'][key] for key in ('input_count', 'completed', 'quarantined', 'pending')) and run.get('imported_rows') == expected['expectations']['input_count']
        checks['source_counts'] = all((overview.get('source') or {}).get(key) == expected['profile'][key] for key in expected['profile'])
        checks['independent_audit'] = digest(overview.get('evaluation')) == digest(expected['evaluation'])
        storage = overview.get('storage') or {}
        checks['storage_under_700mb'] = isinstance(storage.get('bytes'), (int, float)) and 0 < storage['bytes'] <= 700_000_000
        checks['claims'] = digest(overview.get('claims')) == digest(expected['claims'])
        # Do not traverse an old pilot or a run switched between publication steps.
        if not all(checks[key] for key in ('published_run_identity', 'selected_counts', 'source_counts', 'independent_audit')):
            report['errors'].append('Published overview does not match final saved run; stopped before evidence pagination.')
            return report
        issues = client.get('/api/issues')
        checks['ranking'] = issues.get('run_id') == expected['run_id'] and compare_issues(issues.get('issues'), expected['issues'])
        recommendations = client.get('/api/recommendations')
        checks['recommendations'] = recommendations.get('run_id') == expected['run_id'] and digest(recommendations.get('document')) == digest(expected['recommendations'])

        def walk_issue(issue):
            issue_id = issue['issue_id']; wanted = expected['membership'][issue_id]
            seen = set(); cursors = set(); cursor = None; last = None; pages = 0
            errors = Counter(); examples = []
            max_pages = max(1, math.ceil(len(wanted) / 50)) + 1
            while True:
                path = '/api/issues/' + quote(issue_id, safe='') + '/reviews'
                if cursor is not None:
                    path += '?' + urlencode({'cursor': cursor})
                page = client.get(path); pages += 1
                if page.get('run_id') != expected['run_id'] or page.get('issue_id') != issue_id or page.get('status') != 'ready':
                    raise ValueError('Issue page run/issue identity or status mismatch')
                rows = page.get('reviews')
                if not isinstance(rows, list) or len(rows) > 50:
                    raise ValueError('Issue page violates API list/page-size contract')
                for row in rows:
                    review_id = row.get('review_id')
                    if not isinstance(review_id, str):
                        raise ValueError('Issue page contains a missing/invalid review ID')
                    kinds = []
                    if review_id in seen: kinds.append('duplicate_id')
                    if last is not None and review_id.encode() <= last.encode(): kinds.append('nonascending_id')
                    if review_id not in wanted: kinds.append('foreign_member')
                    if review_id not in expected['records'] or digest(row) != expected['records'][review_id][0]: kinds.append('record_mismatch')
                    if source_hash(row) != row.get('source_sha256'): kinds.append('source_hash_mismatch')
                    seen.add(review_id); last = review_id
                    errors.update(kinds)
                    if kinds and len(examples) < 10: examples.append({'review_id': review_id, 'errors': kinds})
                cursor = page.get('next_cursor')
                if cursor is None:
                    break
                if not isinstance(cursor, str) or not cursor or cursor in cursors or not rows or pages >= max_pages:
                    raise ValueError('Invalid, repeated, empty, or excessive pagination cursor')
                cursors.add(cursor)
            missing = wanted - seen
            errors['missing_member'] += len(missing)
            return {'issue_id': issue_id, 'pages': pages, 'expected_members': len(wanted), 'observed_unique_members': len(seen),
                    'passed': not any(errors.values()), 'errors': {key: value for key, value in errors.items() if value},
                    'examples': examples, 'missing_id_examples': sorted(missing)[:10]}

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(walk_issue, issue): issue['issue_id'] for issue in expected['issues']}
            for future in as_completed(futures):
                try:
                    report['issue_pagination'].append(future.result())
                except Exception as error:
                    report['issue_pagination'].append({'issue_id': futures[future], 'passed': False, 'error': str(error)[:400]})
        report['issue_pagination'].sort(key=lambda item: item['issue_id'])
        checks['complete_issue_pagination'] = all(item['passed'] for item in report['issue_pagination']) and len(report['issue_pagination']) == len(expected['issues'])
        sample_results = []
        for review_id, saved in sorted(expected['samples'].items()):
            response = client.get('/api/reviews/' + quote(review_id, safe=''))
            actual = response.get('review')
            passed = response.get('status') == 'ready' and response.get('run_id') == expected['run_id'] and digest(actual) == digest(saved)
            if passed:
                passed = source_hash(actual) == actual['source_sha256']
            sample_results.append({'review_id': review_id, 'passed': passed})
        report['review_detail_samples'] = sample_results
        report['sample_categories'] = expected['category_samples']
        checks['review_details_and_provenance'] = all(item['passed'] for item in sample_results)
        # Re-fetch overview to detect a concurrent run switch across separate GET transactions.
        ending = client.get('/api/overview')
        checks['run_stayed_current'] = all(digest(ending.get(key)) == digest(overview.get(key)) for key in ('status', 'run', 'source', 'evaluation', 'claims'))
        report['status'] = 'pass' if all(checks.values()) else 'fail'
    except Exception as error:
        report['errors'].append(str(error)[:600])
    finally:
        report['duration_seconds'] = round(time.monotonic() - started, 3)
        report['http'] = {'requests': client.requests, 'retries': client.retries, 'response_bytes': client.bytes,
                          'maximum_concurrency': concurrency, 'authentication': 'none', 'methods': ['GET']}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--ingestion-report', type=Path, required=True)
    parser.add_argument('--base-url', default='https://spotify-review-observatory.vercel.app')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--concurrency', type=int, default=4)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--attempts', type=int, default=4)
    parser.add_argument('--sample-size', type=int, default=12)
    for key, value in DEFAULT_EXPECTATIONS.items():
        parser.add_argument('--expect-' + key.replace('_', '-'), type=int, default=value)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 4 or not 1 <= args.attempts <= 6 or not 1 <= args.timeout <= 60 or not 0 <= args.sample_size <= 100:
        parser.error('Use concurrency 1..4, attempts 1..6, timeout 1..60, sample size 0..100')
    expectations = {key: getattr(args, 'expect_' + key) for key in DEFAULT_EXPECTATIONS}
    if any(value < 0 for value in expectations.values()) or not expectations['audited']:
        parser.error('Expected counts must be nonnegative; audited count must be positive')
    try:
        expected = load_expected(args.run_dir, args.ingestion_report, expectations, args.sample_size)
        client = APIClient(args.base_url, timeout=args.timeout, attempts=args.attempts)
        report = reconcile(expected, client, args.concurrency)
    except Exception as error:
        report = {'status': 'fail', 'schema_version': 'publication-reconciliation-v1', 'errors': [str(error)[:600]], 'phase': 'load_saved_evidence'}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + '.tmp')
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(args.out)
    print(json.dumps({'status': report['status'], 'report': str(args.out), 'http': report.get('http')}))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
