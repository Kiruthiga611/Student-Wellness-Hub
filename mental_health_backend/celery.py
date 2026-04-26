"""
Celery application entry point for mental_health_backend.

Fix #12: This file was missing, which caused all scheduled tasks
(commitment reminders, cleanup jobs) to silently never run.

To start the worker:
    celery -A mental_health_backend worker --loglevel=info

To start the beat scheduler (for periodic tasks):
    celery -A mental_health_backend beat --loglevel=info

Both commands must be running alongside Django for scheduled tasks to work.
Requires Redis: pip install redis  (or set CELERY_BROKER_URL in your env)
"""

import os
from celery import Celery

# Tell Celery which Django settings module to use
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mental_health_backend.settings')

app = Celery('mental_health_backend')

# Pull Celery config from Django settings, looking for CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks.py in all INSTALLED_APPS
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Utility task — prints request info. Useful for verifying Celery is running."""
    print(f'Request: {self.request!r}')