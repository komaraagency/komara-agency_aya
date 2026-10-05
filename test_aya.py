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
        from storage import analytics, conversation_state, init_db, record_event, upsert_lead
        init_db()
        state = {"name": "Test", "need": "vente", "budget": "100", "timeline": "demain", "stage": "qualification", "last_question": "pain"}
        upsert_lead(10, state, 100, "qualified")
        record_event(10, "message")
        self.assertEqual(analytics()["qualified"], 1)
        self.assertEqual(analytics()["messages"], 1)
        self.assertEqual(conversation_state(10)["last_question"], "pain")

    def test_payment_is_disabled_without_secret(self):
        from integrations import create_payment_link
        os.environ.pop("STRIPE_SECRET_KEY", None)
        result = create_payment_link("stripe", "telegram", 75, 10, "Bot Telegram")
        self.assertEqual(result["status"], "disabled")

    def test_google_connectors_are_optional(self):
        from integrations import append_google_sheet, create_google_calendar_event
        self.assertEqual(append_google_sheet(["x"])["status"], "disabled")
        self.assertEqual(create_google_calendar_event("x", "2026-10-01T14:00:00+01:00")["status"], "disabled")

    def test_understanding_pipeline_has_six_layers(self):
        from understanding import understand
        frame = understand("Je veux un bot WhatsApp, budget 150 euros, urgent")
        self.assertEqual(frame.entities["channel"], "whatsapp")
        self.assertEqual(frame.entities["budget"], "150 euros")
        self.assertEqual(frame.intent, "pricing")
        self.assertIn("keyword_whatsapp", frame.numeric_features)
        self.assertGreaterEqual(frame.confidence, 0.35)

    def test_conversation_uses_understanding_entities(self):
        from actions import conversation_step, new_conversation_state
        state = new_conversation_state()
        state = conversation_step("bonjour", state)["state"]
        result = conversation_step("Je vends des vêtements sur WhatsApp, budget 150 euros demain", state)
        self.assertEqual(result["state"]["budget"], "150 euros")
        self.assertEqual(result["state"]["timeline"], "je vends des vêtements sur whatsapp, budget 150 euros demain")
        self.assertIn("understanding", result)


if __name__ == "__main__":
    unittest.main()
