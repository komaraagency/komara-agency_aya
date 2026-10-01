import os
import tempfile
import unittest
from pathlib import Path


class AyaCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AYA_DATA_DIR"] = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("AYA_DATA_DIR", None)

    def test_storage_and_analytics(self):
        from storage import analytics, init_db, record_event, upsert_lead
        init_db()
        upsert_lead(10, {"name": "Test", "need": "vente", "budget": "100", "timeline": "demain", "stage": "closing"}, 100, "qualified")
        record_event(10, "message")
        self.assertEqual(analytics()["qualified"], 1)
        self.assertEqual(analytics()["messages"], 1)

    def test_payment_is_disabled_without_secret(self):
        from integrations import create_payment_link
        os.environ.pop("STRIPE_SECRET_KEY", None)
        result = create_payment_link("stripe", "telegram", 75, 10, "Bot Telegram")
        self.assertEqual(result["status"], "disabled")

    def test_google_connectors_are_optional(self):
        from integrations import append_google_sheet, create_google_calendar_event
        self.assertEqual(append_google_sheet(["x"])["status"], "disabled")
        self.assertEqual(create_google_calendar_event("x", "2026-10-01T14:00:00+01:00")["status"], "disabled")


if __name__ == "__main__":
    unittest.main()
