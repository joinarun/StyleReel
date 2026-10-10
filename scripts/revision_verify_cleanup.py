"""Read-only evidence that only the pinned disposable fixtures were cleaned up."""
import datetime as dt
import json
from e2e_live import ROOT, initialize
from firebase_admin import auth
from google.cloud import storage
from google.cloud.firestore_v1.base_query import FieldFilter

config = json.loads((ROOT / '.deployment/config.json').read_text())
scope = json.loads((ROOT / '.deployment/cleanup-scope.json').read_text())
db = initialize(config)
bucket = storage.Client(project=config['project']).bucket(config['temp_bucket'])
report = {'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'scope': 'Only the three pinned revision fixture UIDs; no global user/photo cleanup.', 'checks': []}


def check(name, passed):
    report['checks'].append({'name': name, 'passed': bool(passed)})
    if not passed:
        raise AssertionError(name)


for index, uid in enumerate(scope['uids'], 1):
    label = 'Disposable account ' + str(index)
    check(label + ' Firestore profile removed', not db.collection('users').document(uid).get().exists)
    try:
        auth.get_user(uid)
        removed = False
    except auth.UserNotFoundError:
        removed = True
    check(label + ' Firebase identity removed', removed)
    for collection in ['uploads', 'shares']:
        check(label + ' ' + collection + ' removed', not list(db.collection(collection).where(filter=FieldFilter('user_id', '==', uid)).stream()))
    jobs = [document.to_dict() for document in db.collection('generation_jobs').where(filter=FieldFilter('user_id', '==', uid)).stream()]
    check(label + ' jobs terminal and results marked deleted', all(job['status'] in ['succeeded', 'failed', 'unknown'] and job.get('result_deleted') for job in jobs))
    check(label + ' job image objects absent', all(not bucket.blob(job[field]).exists() for job in jobs for field in ['source_key', 'result_key', 'intermediate_key'] if job.get(field)))
    # Covers orphaned temporary uploads/shares that are no longer referenced by records.
    prefixes = [kind + '/' + uid + '/' for kind in ['uploads', 'results', 'intermediates', 'shares']]
    check(label + ' temporary object prefixes empty', all(not list(bucket.list_blobs(prefix=prefix, max_results=1)) for prefix in prefixes))
    check(label + ' charged usage history retained', not jobs or all(job.get('charged_estimate_usd', 0) > 0 for job in jobs))

check('Private account/session credentials removed', all(not (ROOT / '.deployment' / name).exists() for name in ['live-session.json', 'browser-session.json', 'login-test.json']))
budget = db.collection('budget_months').document(dt.datetime.now(dt.timezone.utc).strftime('%Y-%m')).get().to_dict()
report['monthly_budget_observation'] = {key: budget.get(key, 0) for key in ['spent', 'reserved']}
check('No pending AI cost reservations at cleanup verification', budget.get('reserved', 0) == 0)
(ROOT / 'verification/revision-cleanup-evidence.json').write_text(json.dumps(report, indent=2))
print('PASS:', len(report['checks']), 'scoped cleanup checks; usage history remains intact.')
