"""Reconcile saved pilot artifacts with the public API and read-only PostgreSQL.

Default is offline preflight. --live adds reads only; this program cannot import
or modify a run, call a model, or change account settings.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from spotify_pipeline.database import load_run, SOURCE_FIELDS  # noqa: E402

TABLES = ('spotify_runs', 'spotify_reviews', 'spotify_issues', 'spotify_membership',
          'spotify_claims', 'spotify_recommendations', 'spotify_evaluation_reports')
CLASSIFICATION = ('topic','intent','sentiment','severity','entities','evidence_quote',
                  'needs_review','label_config','cache_source_id')


def check(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def compare_record(expected: dict, actual: dict):
    for field in (*SOURCE_FIELDS, 'source_sha256', 'status'):
        check(actual.get(field) == expected.get(field), f'Review {expected["review_id"]}: {field} mismatch')
    fields = CLASSIFICATION if expected['status'] == 'completed' else ('reason', 'label_config')
    for field in fields:
        check(actual.get(field) == expected.get(field), f'Review {expected["review_id"]}: {field} mismatch')
    for key in ('classifier_provider','classifier_model','fallback_used','uncertainty_score','review_reasons',
                'confidence_source','review_flag_interpretation','initial_prediction'):
        if key in expected:
            check(actual.get('provenance', {}).get(key) == expected[key], f'Review {expected["review_id"]}: {key} provenance mismatch')


def verify(args):
    run_dir = Path(args.run)
    evaluation = Path(args.evaluation) if args.evaluation else run_dir / 'evals/verifier_report.json'
    check(evaluation.exists(), 'Saved independent-verifier report is required for pilot publication.')
    bundle = load_run(run_dir, ingestion_report=args.ingestion, evaluation_path=evaluation)
    summary = bundle.summary
    check(summary['input_count'] == args.expected_count, 'Unexpected selected input count.')
    check(summary['completed'] == args.expected_count, 'The pilot is not fully classified; do not publish as complete.')
    check(summary.get('pending', 0) == 0, 'Pending input records remain.')
    check(bundle.recommendations is not None, 'Recommendations are not ready.')
    check(bundle.source_profile is not None, 'Full-source profile is missing.')
    check(bundle.evaluation.get('verified_count') == args.expected_count, 'Independent verifier did not cover the complete learning sample.')
    check(bundle.evaluation.get('ground_truth') is False, 'Pilot model comparison must not be presented as human accuracy.')
    records = {record['review_id']: record for record in bundle.records}
    expected_membership = defaultdict(set)
    for member in bundle.membership:
        expected_membership[member['issue_id']].add(member['review_id'])
    report = {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'mode': 'live_read_only' if args.live else 'offline_preflight',
        'run_id': bundle.run_id,
        'expected_count': args.expected_count,
        'source_rows': bundle.source_profile['total_rows'],
        'completed': summary['completed'],
        'quarantined': summary['quarantined'],
        'issues': len(bundle.issues),
        'claims': len(bundle.claims),
        'membership_rows': len(bundle.membership),
        'human_accuracy_claimed': False,
        'mutations_performed': False,
        'artifact_sha256': {
            name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
            for name in ('records.jsonl','ranking.csv','claims.csv','membership.csv','recommendations.json','run_summary.json')
        },
    }
    if not args.live:
        report['status'] = 'ready_for_authorized_import'
        return report

    import httpx
    import psycopg
    from psycopg.rows import dict_row
    from dotenv import dotenv_values

    reader_url = dotenv_values(ROOT / '.env').get('DATABASE_READONLY_URL')
    check(bool(reader_url), 'Dedicated DATABASE_READONLY_URL is required for live reconciliation.')
    api_requests = []
    with httpx.Client(base_url=args.base_url.rstrip('/'), timeout=30, follow_redirects=False) as client:
        def get(path: str, expected_status=200):
            response = client.get(path)
            api_requests.append({'path': path.split('?')[0], 'http_status': response.status_code})
            check(response.status_code == expected_status, f'{path.split("?")[0]} returned HTTP {response.status_code}, expected {expected_status}')
            check('application/json' in response.headers.get('content-type', ''), 'API did not return JSON.')
            payload = response.json()
            if expected_status == 200:
                check(payload.get('status') == 'ready', f'{path.split("?")[0]} is not ready.')
                if payload.get('run_id') is not None:
                    check(payload['run_id'] == bundle.run_id, 'API current run changed during verification.')
            return payload

        overview = get('/api/overview')
        check(overview['run']['run_id'] == bundle.run_id, 'Published run does not match saved run.')
        check(overview['scope'] == 'pilot', 'A 1,000-review pilot must be labeled as pilot scope.')
        for key in ('input_count','completed','quarantined','unique_texts','cache_hits','requests','attempts',
                    'api_cost_usd','api_cost_complete','label_config','model_settings','limitations'):
            if key in summary:
                check(overview['run'].get(key) == summary[key], f'Overview {key} mismatch.')
        check(not {'input_path','cache_path'} & set(overview['run']), 'Public overview leaked local run paths.')
        check(overview['source'] == bundle.source_profile, 'Full-source counts/profile mismatch.')
        check(overview['evaluation'] == bundle.evaluation, 'Published evaluation does not match saved report.')
        expected_claims = sorted(bundle.claims, key=lambda row: row['claim_id'])
        check(overview['claims'] == expected_claims, 'Published claims differ from saved calculations.')

        actual_issues = get('/api/issues')['issues']
        check(len(actual_issues) == len(bundle.issues), 'Issue count mismatch.')
        for expected, actual in zip(sorted(bundle.issues,key=lambda row:row['rank']), actual_issues):
            for key in ('issue_id','name','description','rank','complaint_count','severity_sum','priority_score'):
                check(actual[key] == expected[key], f'Ranking field {key} mismatch.')
            check(Decimal(str(actual['mean_severity'])).quantize(Decimal('0.000001')) == expected['mean_severity'], 'Mean severity rounding mismatch.')

        pages, paginated_records, first_cursor = 0, 0, None
        for issue in actual_issues:
            issue_id, seen, cursor = issue['issue_id'], [], None
            while True:
                path = f'/api/issues/{quote(issue_id,safe="")}/reviews'
                if cursor:
                    path += '?cursor=' + quote(cursor,safe='')
                page = get(path)
                pages += 1
                check(page['issue_id'] == issue_id, 'Issue page identity mismatch.')
                check(len(page['reviews']) <= 50, 'Review page exceeded its 50-row cap.')
                for actual in page['reviews']:
                    check(actual['review_id'] in records, 'Page contains an unknown review ID.')
                    compare_record(records[actual['review_id']], actual)
                    seen.append(actual['review_id'])
                paginated_records += len(page['reviews'])
                cursor = page['next_cursor']
                if cursor and first_cursor is None:
                    first_cursor = (issue_id,cursor)
                check(len(seen) <= len(expected_membership[issue_id]), 'Pagination repeated or introduced review records.')
                if not cursor:
                    break
            check(len(seen) == len(set(seen)), 'Pagination duplicated review IDs.')
            check(set(seen) == expected_membership[issue_id], 'Pagination omitted or introduced issue membership.')
            check(seen == sorted(seen,key=lambda value:value.encode('utf-8')), 'Review pagination order is unstable.')

        samples = set(sorted(records,key=lambda rid:hashlib.sha256(('dashboard-reconciliation-v1:'+rid).encode()).digest())[:12])
        for record in records.values():
            if record.get('cache_source_id'):
                samples.update((record['review_id'],record['cache_source_id']))
                break
        for predicate in (lambda r:r.get('needs_review'),lambda r:r['status']=='quarantined'):
            hit = next((record['review_id'] for record in records.values() if predicate(record)),None)
            if hit:
                samples.add(hit)
        for review_id in sorted(samples):
            detail = get('/api/reviews/' + quote(review_id,safe=''))
            compare_record(records[review_id], detail['review'])
        check(get('/api/recommendations')['document'] == bundle.recommendations, 'Recommendation document mismatch.')
        get('/api/issues/issue-playback/reviews?cursor=bad%25cursor',400)
        get('/api/reviews/definitely-not-a-source-review',404)
        stale = base64.urlsafe_b64encode(json.dumps({'run_id':'synthetic-stale-cursor-not-data','issue_id':actual_issues[0]['issue_id'],'review_id':'cursor-only'}).encode()).decode().rstrip('=') if actual_issues else None
        if stale:
            get('/api/issues/'+quote(actual_issues[0]['issue_id'],safe='')+'/reviews?cursor='+stale,409)
        if first_cursor and len(actual_issues) > 1:
            other = next(issue['issue_id'] for issue in actual_issues if issue['issue_id'] != first_cursor[0])
            get('/api/issues/'+quote(other,safe='')+'/reviews?cursor='+first_cursor[1],400)
        check(get('/api/overview')['run']['run_id'] == bundle.run_id, 'Current run changed during API verification.')

    with psycopg.connect(reader_url, connect_timeout=20,row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
            cursor.execute("SET LOCAL statement_timeout='15000ms'")
            cursor.execute('SELECT run_id FROM spotify_runs WHERE is_current')
            check(cursor.fetchall() == [{'run_id':bundle.run_id}], 'Database current run mismatch.')
            cursor.execute('SELECT * FROM spotify_reviews WHERE run_id=%s',(bundle.run_id,))
            stored = cursor.fetchall()
            check(len(stored) == len(records), 'Database review count mismatch.')
            for record in stored:
                check(record['review_id'] in records,'Database contains a foreign review ID.')
                compare_record(records[record['review_id']],record)
            cursor.execute('SELECT issue_id,review_id FROM spotify_membership WHERE run_id=%s',(bundle.run_id,))
            membership = cursor.fetchall()
            check({(row['issue_id'],row['review_id']) for row in membership} == {(row['issue_id'],row['review_id']) for row in bundle.membership}, 'Database membership mismatch.')
            cursor.execute("SELECT COALESCE(SUM(pg_total_relation_size(c.oid)),0)::bigint AS bytes FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relkind='r' AND c.relname = ANY(%s)",(list(TABLES),))
            db_storage = cursor.fetchone()['bytes']
            cursor.execute("SELECT pg_database_size(current_database()) AS bytes, current_setting('default_transaction_read_only') AS reader_default")
            database = cursor.fetchone()
            check(database['reader_default']=='on','Dedicated reader is not read-only by default.')

    api_storage = overview['storage']['bytes']
    projected = math.ceil(api_storage * 210_000 / args.expected_count)
    check(overview['storage']['projected_bytes_210k'] == projected,'API storage projection calculation mismatch.')
    conservative_projection = math.ceil(max(api_storage,db_storage) * 210_000 / args.expected_count)
    report.update({
        'status':'passed', 'api_requests':api_requests,
        'review_pages_checked':pages,'paginated_review_records_checked':paginated_records,
        'review_detail_ids_checked':sorted(samples),'database_records_checked':len(stored),
        'api_app_storage_bytes':api_storage,'database_app_storage_bytes':db_storage,
        'total_database_bytes':database['bytes'],'projected_bytes_210k':conservative_projection,
        'storage_gate_bytes':700_000_000,'storage_gate_passed':conservative_projection < 700_000_000,
        'storage_projection_limitations':'Linear pilot projection; includes retained historical runs. Refresh at 10,000 reviews before scaling.',
        'neon_sleep_recovery':'Not claimed by this check; verify after at least five minutes of database inactivity.',
    })
    if not report['storage_gate_passed']:
        report.update(status='failed',reason='Conservative storage projection exceeds the 700 MB expansion gate.')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',default=str(ROOT/'runs/pilot/1000'))
    parser.add_argument('--ingestion',default=str(ROOT/'data/ingestion_report.json'))
    parser.add_argument('--evaluation')
    parser.add_argument('--expected-count',type=int,default=1000)
    parser.add_argument('--base-url',default='https://spotify-review-observatory.vercel.app')
    parser.add_argument('--live',action='store_true',help='Read-only public API and PostgreSQL reconciliation; never imports data.')
    parser.add_argument('--output')
    args=parser.parse_args()
    try:
        result=verify(args)
    except AssertionError as exc:
        result={'status':'failed','reason':str(exc),'mutations_performed':False}
    except Exception as exc:
        result={'status':'failed','error_type':type(exc).__name__,'sqlstate':getattr(exc,'sqlstate',None),'mutations_performed':False}
    rendered=json.dumps(result,indent=2,ensure_ascii=False)+'\n'
    if args.output:
        output=Path(args.output)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(rendered,encoding='utf-8')
    print(rendered,end='')
    raise SystemExit(1 if result['status']=='failed' else 0)
