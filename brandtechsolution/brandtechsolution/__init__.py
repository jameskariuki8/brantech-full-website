"""Project package.

Importing the Celery app here is what makes @shared_task work everywhere:
Django loads this package before any app, so the default app is already
registered by the time a tasks.py is imported.
"""
from brandtechsolution.celery import app as celery_app

__all__ = ("celery_app",)
