from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# Celery's default prefork pool fails on Python 3.14 (tasks die in fast_trace_task).
# The solo pool is fine for local development; production sets its own pool.
CELERY_WORKER_POOL = 'solo'
