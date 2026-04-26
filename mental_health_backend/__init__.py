# mental_health_backend/__init__.py
#
# Fix #12: Import the Celery app here so Django loads it on startup.
# Without this, @shared_task decorators in tasks.py won't connect to the app
# and scheduled tasks will silently never run.
 
from .celery import app as celery_app
 
__all__ = ('celery_app',)
 









