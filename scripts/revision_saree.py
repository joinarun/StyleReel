"""One real, quota-accounted saree check using a synthetic casual-clothing photo."""
import datetime as dt
import json
from e2e_live import ROOT, PRIVATE, Acceptance, initialize, save
from app.providers import SAREE_INSTRUCTION

config = json.loads((ROOT / '.deployment/config.json').read_text())
session = json.loads(PRIVATE.read_text())
db = initialize(config)
report = ROOT / 'verification/saree-revision-evidence.json'
run = Acceptance(config, session, db, report=report)
if report.exists():
    run.evidence = json.loads(report.read_text())
    prior = run.evidence.get('generations', [])
    if len(prior) != 1 or prior[0]['status'] != 'succeeded':
        raise SystemExit('A paid submission may already exist; reconcile its outcome without resubmitting.')
    job = run.request('GET', '/api/tryon/jobs/' + prior[0]['job_id'], 'user').json()
    print('Rechecking the existing succeeded saree job; no additional paid call.', flush=True)
else:
    job = run.generate('saree-revision-casual', 'gemini-3-pro-image', 'person.png', ['sample-saree'], configure_model=False)
run.check('Real Google Pro saree generation succeeds', job['status'] == 'succeeded')
snapshot = db.collection('generation_jobs').document(job['id']).get().to_dict()
run.check('Worker used the immutable saree/full-replacement instruction snapshot', SAREE_INSTRUCTION in snapshot.get('render_instructions', []))
run.check('Saree stays marked experimental and uses one image-generation attempt', job.get('experimental') and snapshot['attempts'] == 1)
run.evidence['completed_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
save(report, run.evidence)
print('Saree revision check completed; no global settings were changed.', flush=True)
