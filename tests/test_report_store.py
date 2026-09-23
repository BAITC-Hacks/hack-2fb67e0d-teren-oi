import unittest
from unittest.mock import patch

from teren_oi.report_store import ReportStore


class ReportStoreTests(unittest.TestCase):
    def test_expiry_and_capacity(self):
        store = ReportStore(ttl_seconds=60, max_reports=2, max_chars=10)
        with patch("teren_oi.report_store.monotonic", return_value=0):
            first = store.put("12345")
            second = store.put("67890")
            self.assertEqual(store.get(first), "12345")
            third = store.put("abc")
            self.assertIsNone(store.get(first))
            self.assertEqual(store.get(second), "67890")
        with patch("teren_oi.report_store.monotonic", return_value=60):
            self.assertIsNone(store.get(second))
            self.assertIsNone(store.get(third))
