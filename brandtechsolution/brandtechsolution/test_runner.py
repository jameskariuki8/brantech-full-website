"""Test runner that starts every test with an empty cache.

The test cache is one locmem store for the whole run, while the database is
rolled back after each test. Rate-limit counters live in the cache, so without
this they pile up across tests: the sixth test to post /signup/ from the test
client's address gets a 429 and fails for reasons that depend on test order.
"""
import unittest

from django.core.cache import caches
from django.test.runner import DiscoverRunner


class _ClearingResult(unittest.TextTestResult):
    def startTest(self, test):
        for cache in caches.all():
            cache.clear()
        super().startTest(test)


class CacheClearingRunner(DiscoverRunner):
    def get_resultclass(self):
        # A debug or pdb result class wins; those runs are about one test.
        return super().get_resultclass() or _ClearingResult
