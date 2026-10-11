from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import uuid
from fastapi import HTTPException
from .infrastructure import now
from .models import Settings, TryOnRequest
from .providers import ProviderError, estimate, reported_cost_usd, render_instructions, garment_contact_sheet
from .images import normalize_image

TERMINAL = {'succeeded', 'failed', 'unknown'}


def owned(store, collection, identifier, uid):
    value = store.get(collection, identifier)
    if not value or value.get('user_id') != uid:
        raise HTTPException(404, 'Not found.')
    return value


def public_job(job: dict):
    keys = ['id', 'status', 'workflow', 'created_at', 'error', 'garment_names', 'expected_calls', 'estimated_cost_usd', 'experimental']
    value = {k: job[k] for k in keys if k in job}
    ai = job.get('settings', {}).get('ai', {})
    if ai.get('provider'):
        value['provider'] = ai['provider']
        value['provider_label'] = job.get('provider_label') or {'google': 'Google Gemini', 'fashn': 'FASHN', 'pruna': 'Pruna'}.get(ai['provider'], ai['provider'])
    if ai.get('model'):
        value['model'] = ai['model']
    if job.get('result_key') and not job.get('result_deleted') and job.get('result_expires_at', now()) > now():
        value['result_url'] = f'/api/tryon/results/{job["id"]}'
    return value


class JobService:
    def __init__(self, store, objects, tasks, providers):
        self.store, self.objects, self.tasks, self.providers = store, objects, tasks, providers

    def settings(self):
        data = self.store.get('application_settings', 'main') or {}
        return Settings.model_validate({k: v for k, v in data.items() if k != 'id'})

    def submit(self, uid: str, request: TryOnRequest, workflow: str):
        settings = self.settings()
        idem = hashlib.sha256(f'{uid}:{request.idempotency_key}'.encode()).hexdigest()
        fingerprint = hashlib.sha256(f'{workflow}:{request.upload_id}:{",".join(request.garment_ids)}'.encode()).hexdigest()
        existing = self.store.get('idempotency', idem)
        if existing:
            if existing['fingerprint'] != fingerprint:
                raise HTTPException(409, 'This idempotency key was already used with different inputs.')
            return self.store.get('generation_jobs', existing['job_id'])
        upload = owned(self.store, 'uploads', request.upload_id, uid)
        if upload.get('expires_at', now()) <= now() or upload.get('deleted') or upload.get('consumed'):
            raise HTTPException(410, 'Photo expired or was already used. Upload it again.')
        if upload['purpose'] != ('holding' if workflow == 'holding' else 'person') or not upload.get('consent'):
            raise HTTPException(400, 'Upload a suitable photo and consent to processing.')
        info = next(p for p in self.providers.info(settings) if p['id'] == settings.ai.provider)
        if not info['configured'] or info['status'] == 'terms_unconfirmed':
            raise HTTPException(503, 'The selected provider is unavailable or its privacy terms remain unconfirmed.')
        if settings.ai.model not in info['models']:
            raise HTTPException(400, 'The selected model is not supported by this provider.')
        if workflow == 'holding' and not info['supports_holding']:
            raise HTTPException(400, 'This provider does not support held-garment photos.')
        garments = []
        if workflow == 'catalog':
            if not 1 <= len(request.garment_ids) <= 2 or len(set(request.garment_ids)) != len(request.garment_ids):
                raise HTTPException(400, 'Select one garment or one upper and one lower garment.')
            for garment_id in request.garment_ids:
                garment = self.store.get('garments', garment_id)
                if not garment or not garment.get('active'):
                    raise HTTPException(400, 'A selected garment is unavailable.')
                category = self.store.get('categories', garment['category_id'])
                if not category:
                    raise HTTPException(400, 'A garment category is unavailable.')
                keys = list(garment.get('image_keys') or ([garment['image_key']] if garment.get('image_key') else []))
                if not keys:
                    raise HTTPException(400, 'A selected garment has no reference photos.')
                garments.append({**garment, 'image_keys': keys, 'slot': category['slot'], 'experimental': bool(category.get('experimental'))})
            if len(garments) == 2 and {g['slot'] for g in garments} != {'upper', 'lower'}:
                raise HTTPException(400, 'Two garments must be one upper and one lower garment.')
            garments.sort(key=lambda g: 0 if g['slot'] == 'upper' else 1)
        elif request.garment_ids:
            raise HTTPException(400, 'Held-garment processing does not use catalog references.')
        groups = [{'garment_id': garment['id'], 'image_keys': list(garment['image_keys'])} for garment in garments]
        reference_count = sum(len(group['image_keys']) for group in groups)
        calls, cost = estimate(settings, len(garments), workflow, reference_count=reference_count)
        job_id = uuid.uuid4().hex
        created = now()
        job = {'id': job_id, 'user_id': uid, 'upload_id': upload['id'], 'source_key': upload['key'], 'garments': garments,
               'garment_names': [g['name'] for g in garments], 'garment_reference_groups': groups,
               'reference_count': reference_count, 'workflow': workflow, 'status': 'queued', 'stage': 'ready',
               'created_at': created, 'updated_at': created, 'expected_calls': calls, 'estimated_cost_usd': cost,
               'settings': settings.model_dump(), 'attempts': 0, 'step': 0, 'preflight_done': False,
               'enqueue_state': 'pending', 'budget_month': created.strftime('%Y-%m'), 'expires_at': created + timedelta(hours=24)}
        job['result_cleanup_pending'] = False
        job['experimental'] = workflow == 'holding' or any(g.get('experimental') for g in garments)
        job['render_instructions'] = render_instructions(garments, workflow)
        job['provider_label'] = info['label']
        limits = settings.rate_limits
        day, month = created.strftime('%Y-%m-%d'), created.strftime('%Y-%m')

        def reserve(tx):
            duplicate = tx.get('idempotency', idem)
            if duplicate:
                if duplicate['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'Idempotency key conflict.')
                return tx.get('generation_jobs', duplicate['job_id'])
            user = tx.get('users', uid)
            if not user or not user.get('active') or user.get('must_change_password'):
                raise HTTPException(403, 'This account is unavailable.')
            source = tx.get('uploads', upload['id'])
            if not source or source.get('consumed') or source.get('deleted'):
                raise HTTPException(409, 'This source photo is already in use.')
            u = tx.get('quota_users', uid) or {}
            g = tx.get('quota_global', 'main') or {}
            budget = tx.get('budget_months', month) or {'reserved': 0.0, 'spent': 0.0}
            recent = [stamp for stamp in u.get('recent_calls', []) if stamp > created - timedelta(seconds=limits.window_seconds)]
            if u.get('active_job'):
                active = tx.get('generation_jobs', u['active_job'])
                if active and active['status'] not in TERMINAL:
                    raise HTTPException(429, 'One generation is already running.', headers={'Retry-After': '15'})
            if len(recent) + calls > limits.max_calls:
                retry = max(1, int((min(recent) + timedelta(seconds=limits.window_seconds) - created).total_seconds()) + 1) if recent else limits.window_seconds
                raise HTTPException(429, f'This workflow needs {calls} AI calls. Your current call limit has been reached.', headers={'Retry-After': str(retry)})
            user_daily = u.get('daily_calls', 0) if u.get('day') == day else 0
            global_daily = g.get('daily_calls', 0) if g.get('day') == day else 0
            if user_daily + calls > limits.daily_user_calls or global_daily + calls > limits.daily_global_calls:
                raise HTTPException(429, 'Daily AI usage limit reached.', headers={'Retry-After': '3600'})
            if budget['reserved'] + budget['spent'] + cost > limits.monthly_budget_usd + 1e-8:
                raise HTTPException(429, 'Monthly estimated AI spending ceiling reached.', headers={'Retry-After': '3600'})
            tx.set('quota_users', uid, {**u, 'recent_calls': recent + [created] * calls, 'day': day, 'daily_calls': user_daily + calls, 'active_job': job_id})
            tx.set('quota_global', 'main', {'day': day, 'daily_calls': global_daily + calls})
            tx.set('budget_months', month, {**budget, 'reserved': round(budget['reserved'] + cost, 6)})
            tx.set('uploads', upload['id'], {**source, 'consumed': True})
            tx.set('idempotency', idem, {'job_id': job_id, 'fingerprint': fingerprint, 'user_id': uid, 'created_at': created})
            tx.set('generation_jobs', job_id, job)
            return job

        try:
            reserved = self.store.atomic(reserve)
        except HTTPException as exc:
            if exc.status_code == 429:
                self.event(uid, 'rejected', workflow=workflow, error_category='quota')
            raise
        if reserved['id'] == job_id:
            self.event(uid, 'generation', job_id=job_id, workflow=workflow, provider=settings.ai.provider, model=settings.ai.model)
            self.enqueue(job_id)
        return reserved

    def event(self, uid, event, **values):
        event_id = uuid.uuid4().hex
        self.store.set('usage_events', event_id, {'user_id': uid, 'event': event, 'created_at': now(), **values})

    def enqueue(self, job_id: str, delay: int = 0):
        # Reserve the outbox marker before enqueue. A crash is recovered after five minutes.
        def marker(tx):
            job = tx.get('generation_jobs', job_id)
            if not job or job['status'] in TERMINAL:
                return False
            tx.set('generation_jobs', job_id, {**job, 'enqueue_state': 'dispatching', 'last_enqueued_at': now()})
            return True
        if not self.store.atomic(marker):
            return
        try:
            self.tasks.enqueue(job_id, delay)
        except Exception:
            self._update(job_id, enqueue_state='pending')
            return
        self._update(job_id, enqueue_state='enqueued')

    def _update(self, job_id: str, **values):
        def update(tx):
            job = tx.get('generation_jobs', job_id)
            if job:
                tx.set('generation_jobs', job_id, {**job, **values, 'updated_at': now()})
        self.store.atomic(update)

    def claim(self, job_id: str):
        def operation(tx):
            job = tx.get('generation_jobs', job_id)
            if not job or job['status'] in TERMINAL:
                return None
            if job.get('lease_until', datetime.min.replace(tzinfo=timezone.utc)) > now():
                return None
            if job.get('stage') == 'submitting' and not job.get('prediction_id'):
                return {**job, 'abandoned_submission': True}
            job = {**job, 'status': 'processing', 'lease_until': now() + timedelta(seconds=job['settings']['ai']['timeout_seconds'] + 60), 'enqueue_state': 'handled'}
            tx.set('generation_jobs', job_id, job)
            return job
        return self.store.atomic(operation)

    def finish(self, job: dict, status: str, error: str | None = None, image: bytes | None = None):
        result_key = None
        if image:
            normalized = normalize_image(image, max_bytes=30 * 1024 * 1024)
            result_key = f'results/{job["user_id"]}/{job["id"]}-{uuid.uuid4().hex}.jpg'
            self.objects.put('temp', result_key, normalized.data)
        # Conservative accounting: charge reservation fraction for submitted attempts, not uncalled phases.
        costs = job.get('call_costs', {})
        submitted = min(job.get('attempts', 0), job['expected_calls'])
        if job['workflow'] == 'holding':
            stage_estimates = [0.02, max(0, job['estimated_cost_usd'] - 0.02)]
        else:
            stage_estimates = [job['estimated_cost_usd'] / job['expected_calls']] * job['expected_calls']
        charged = round(sum(costs.values()) + sum(stage_estimates[i] for i in range(submitted) if str(i + 1) not in costs), 6)
        if status == 'unknown':
            charged = job['estimated_cost_usd']
        finished = now()
        def finalize(tx):
            current = tx.get('generation_jobs', job['id'])
            profile = tx.get('users', job['user_id'])
            quota = tx.get('quota_users', job['user_id']) or {}
            budget = tx.get('budget_months', job['budget_month']) or {'reserved': job['estimated_cost_usd'], 'spent': 0}
            upload = tx.get('uploads', job['upload_id'])
            if current['status'] in TERMINAL:
                return False
            final_status = status if profile and profile.get('active') else 'failed'
            final_key = result_key if final_status == 'succeeded' and not current.get('result_deleted') else None
            final_error = error if final_status == status else 'The account was deactivated during generation.'
            tx.set('usage_events', job['id'] + '-completed', {'user_id': job['user_id'], 'event': 'completed', 'created_at': finished, 'job_id': job['id'], 'status': final_status, 'workflow': job['workflow'], 'provider': job['settings']['ai']['provider'], 'model': job['settings']['ai']['model'], 'estimated_cost_usd': charged, 'reserved_cost_usd': job['estimated_cost_usd'], 'duration_seconds': (finished - job['created_at']).total_seconds(), 'error_category': 'unknown_outcome' if final_status == 'unknown' else ('provider' if final_error else None)})
            tx.set('generation_jobs', job['id'], {**current, 'status': final_status, 'error': final_error, 'result_key': final_key, 'result_cleanup_pending': bool(final_key), 'result_expires_at': finished + timedelta(hours=24), 'completed_at': finished, 'charged_estimate_usd': charged, 'lease_until': finished, 'enqueue_state': 'done'})
            if quota.get('active_job') == job['id']:
                tx.set('quota_users', job['user_id'], {**quota, 'active_job': None})
            tx.set('budget_months', job['budget_month'], {**budget, 'reserved': max(0, round(budget['reserved'] - job['estimated_cost_usd'], 6)), 'spent': round(budget['spent'] + charged, 6)})
            if upload:
                tx.set('uploads', job['upload_id'], {**upload, 'deleted': True})
            return {'status': final_status, 'result_key': final_key}
        outcome = self.store.atomic(finalize)
        if outcome:
            if result_key and outcome['result_key'] != result_key:
                self.objects.delete('temp', result_key)
            status = outcome['status']
            # Cleanup failures stay discoverable to maintenance through deleted upload metadata.
            self.objects.delete('temp', job['source_key'])
            source = self.store.get('uploads', job['upload_id'])
            if source:
                self.store.set('uploads', job['upload_id'], {**source, 'cleanup_pending': False})
            if job.get('intermediate_key'):
                self.objects.delete('temp', job['intermediate_key'])


        elif result_key:
            self.objects.delete('temp', result_key)

    def _begin_call(self, job: dict):
        limits = Settings.model_validate(job['settings']).rate_limits
        def call(tx):
            quota = tx.get('quota_users', job['user_id']) or {}
            profile = tx.get('users', job['user_id'])
            if not profile or not profile.get('active'):
                raise ProviderError('The account was deactivated.')
            recent = [t for t in quota.get('actual_call_times', []) if t > now() - timedelta(seconds=limits.window_seconds)]
            if len(recent) >= limits.max_calls:
                return False
            current = tx.get('generation_jobs', job['id'])
            if current['status'] in TERMINAL:
                raise ProviderError('The generation was cancelled.')
            tx.set('generation_jobs', job['id'], {**current, 'lease_until': now() + timedelta(seconds=job['settings']['ai']['timeout_seconds'] + 60)})
            tx.set('quota_users', job['user_id'], {**quota, 'actual_call_times': recent + [now()]})
            return True
        if not self.store.atomic(call):
            self._update(job['id'], lease_until=now(), stage='ready')
            self.enqueue(job['id'], delay=limits.window_seconds)
            return False
        return True

    def _record_cost(self, job: dict, usage: dict, model: str | None = None):
        amount = reported_cost_usd(Settings.model_validate(job['settings']), usage, model)
        if amount is not None:
            costs = {**job.get('call_costs', {}), str(job['attempts']): amount}
            job['call_costs'] = costs
            self._update(job['id'], call_costs=costs)

    def process(self, job_id: str):
        job = self.claim(job_id)
        if not job:
            return
        if job.get('abandoned_submission'):
            self.finish(job, 'unknown', 'The worker stopped during provider submission. The request will not be repeated because it may have been billed.')
            return
        if now() - job['created_at'] > timedelta(minutes=20) and not job.get('prediction_id'):
            self.finish(job, 'failed', 'This queued generation expired before it could be processed. Upload a new photo.')
            return
        user = self.store.get('users', job['user_id'])
        if not user or not user.get('active'):
            self.finish(job, 'failed', 'The account was deactivated.')
            return
        settings = Settings.model_validate(job['settings'])
        try:
            provider = self.providers.get(settings.ai.provider)
            if job.get('prediction_id'):
                if now() - job['created_at'] > timedelta(minutes=20):
                    self.finish(job, 'unknown', 'The provider did not finish within the polling window. This request will not be resubmitted.')
                    return
                result = provider.poll(job['prediction_id'], settings)
                if result.status == 'processing':
                    self._update(job_id, lease_until=now(), stage='polling')
                    self.enqueue(job_id, delay=10)
                    return
                if result.status == 'failed':
                    self.finish(job, 'failed', result.error or 'The provider could not generate an image.')
                    return
                self._record_cost(job, result.usage)
                self.event(job['user_id'], 'provider_result', job_id=job_id, provider=settings.ai.provider, model=settings.ai.model, reported_usage=result.usage)
            else:
                source = self.objects.get('temp', job.get('intermediate_key') or job['source_key'])
                if job['workflow'] == 'holding' and not job.get('preflight_done'):
                    if not self._begin_call(job):
                        return
                    job['attempts'] += 1
                    self._update(job_id, stage='submitting', attempts=job['attempts'])
                    self.event(job['user_id'], 'provider_call', job_id=job_id, provider='google', model='gemini-3.8-flash', workflow='holding', estimated_cost_usd=0.02)
                    suitable, guidance, usage = provider.preflight(source, settings)
                    self._record_cost(job, usage, 'gemini-3.8-flash')
                    self.event(job['user_id'], 'provider_result', job_id=job_id, provider='google', model='gemini-3.8-flash', reported_usage=usage, workflow='holding')
                    if not suitable:
                        self.finish(job, 'failed', guidance)
                        return
                    job['preflight_done'] = True
                    # Preflight and image editing use separate durable task deliveries,
                    # so two configured timeouts never exceed Cloud Tasks' deadline.
                    self._update(job_id, preflight_done=True, stage='ready', lease_until=now())
                    self.enqueue(job_id)
                    return
                # Read only the immutable reference keys captured at submission; changes
                # to catalog labels/photos must not silently alter an accepted generation.
                groups = job.get('garment_reference_groups')
                if groups is None:  # Jobs accepted by older releases used one image per garment.
                    groups = [{'garment_id': g.get('id'), 'image_keys': list(g.get('image_keys') or [g['image_key']])} for g in job['garments']]
                instructions = job.get('render_instructions', render_instructions(job['garments'], job['workflow']))
                if settings.ai.provider == 'fashn':
                    group = groups[job['step']]
                    views = [self.objects.get('catalog', key) for key in group['image_keys']]
                    references = [garment_contact_sheet(views)]
                    # FASHN still receives exactly one garment in each sequential call.
                    instructions = render_instructions([{**job['garments'][job['step']], 'image_keys': ['contact-sheet']}], job['workflow'])
                    if len(views) > 1:
                        instructions.append('GARMENT REFERENCE 1 is a multi-view sheet of ONE garment. '
                                            'Use all panels together for its appearance; do not copy the sheet layout '
                                            'or any reference model into the finished photograph.')
                else:
                    references = [self.objects.get('catalog', key) for group in groups for key in group['image_keys']]
                if not self._begin_call(job):
                    return
                job['attempts'] += 1
                self._update(job_id, stage='submitting', attempts=job['attempts'])
                self.event(job['user_id'], 'provider_call', job_id=job_id, provider=settings.ai.provider, model=settings.ai.model, workflow=job['workflow'], estimated_cost_usd=job['estimated_cost_usd'] / job['expected_calls'])
                result = provider.submit(source, references, settings, job['workflow'], instructions)
                if result.prediction_id:
                    job['prediction_id'] = result.prediction_id
                    self._update(job_id, prediction_id=result.prediction_id, stage='polling', lease_until=now())
                    self.enqueue(job_id, delay=10)
                    return
                self._record_cost(job, result.usage)
                self.event(job['user_id'], 'provider_result', job_id=job_id, provider=settings.ai.provider, model=settings.ai.model, reported_usage=result.usage)
            if settings.ai.provider == 'fashn' and job['step'] + 1 < len(job['garments']):
                image = normalize_image(result.image, max_bytes=30 * 1024 * 1024).data
                intermediate = f'intermediate/{job["user_id"]}/{job_id}.jpg'
                self.objects.put('temp', intermediate, image)
                self._update(job_id, intermediate_key=intermediate, step=job['step'] + 1, prediction_id=None, stage='ready', lease_until=now())
                self.enqueue(job_id)
                return
            self.finish(job, 'succeeded', image=result.image)
        except ProviderError as exc:
            if job.get('prediction_id') and not exc.ambiguous:
                # Status reads are safe to retry. Never repeat submission.
                self._update(job_id, lease_until=now(), stage='polling')
                self.enqueue(job_id, delay=30)
            else:
                self.finish(job, 'unknown' if exc.ambiguous else 'failed', str(exc))
        except Exception:
            # Keep the submitting marker for crash recovery. Read/storage failures before submission fail safely.
            current = self.store.get('generation_jobs', job_id)
            if current.get('stage') == 'submitting':
                self.finish(job, 'unknown', 'The provider outcome could not be confirmed. This request will not be repeated.')
            else:
                self.finish(job, 'failed', 'The generation could not complete. Please try again.')

    def maintenance(self):
        moment = now()
        counts = {'jobs_recovered': 0, 'objects_deleted': 0}
        # Equality-indexed active/pending sets keep five-minute scans bounded by
        # live objects, rather than reading every historical job and upload.
        active_jobs = self.store.list('generation_jobs', {'status': 'queued'}) + self.store.list('generation_jobs', {'status': 'processing'})
        for job in active_jobs:
            if job['status'] not in TERMINAL:
                if job.get('lease_until', moment) > moment:
                    continue
                if job.get('stage') == 'submitting' and not job.get('prediction_id'):
                    self.finish(job, 'unknown', 'An interrupted submission has an unknown billing outcome and will not be retried.')
                elif moment - job['created_at'] > timedelta(minutes=20) and not job.get('prediction_id'):
                    self.finish(job, 'failed', 'This generation expired before provider submission.')
                elif moment - job.get('last_enqueued_at', job['created_at']) > timedelta(minutes=5) or job.get('enqueue_state') == 'pending':
                    self.enqueue(job['id'])
                    counts['jobs_recovered'] += 1
        for job in self.store.list('generation_jobs', {'result_cleanup_pending': True}):
            if job.get('result_key') and (job.get('result_deleted') or job.get('result_expires_at', moment) <= moment):
                self.objects.delete('temp', job['result_key'])
                self._update(job['id'], result_deleted=True, result_cleanup_pending=False)
                counts['objects_deleted'] += 1
        for upload in self.store.list('uploads', {'cleanup_pending': True}):
            if upload.get('deleted') or upload.get('expires_at', moment) <= moment:
                self.objects.delete('temp', upload['key'])
                self.store.set('uploads', upload['id'], {**upload, 'deleted': True, 'cleanup_pending': False})
                counts['objects_deleted'] += 1
        for share in self.store.list('shares'):
            if share.get('revoked') or share['expires_at'] <= moment:
                self.objects.delete('temp', share['key'])
                self.store.delete('shares', share['id'])
                counts['objects_deleted'] += 1
        return counts
