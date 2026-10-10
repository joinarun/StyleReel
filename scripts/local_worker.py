"""Foreground worker for emulator development. External AI calls remain real and billable."""
import time
from app.main import get_services
from app.jobs import TERMINAL

services = get_services()
if not services.env.emulator:
    raise RuntimeError('The development worker requires FIREBASE_AUTH_EMULATOR_HOST. Production uses Cloud Tasks.')
while True:
    for job in services.store.list('generation_jobs'):
        if job['status'] not in TERMINAL:
            services.jobs.process(job['id'])
    services.jobs.maintenance()
    time.sleep(5)
