from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from teren_oi.analyzer import AnalysisError


class StreamlitStatusTests(unittest.TestCase):
    def test_failed_ai_never_becomes_success_after_changing_checkbox(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-only-key"}), patch(
            "teren_oi.analyzer.analyze_with_metadata", side_effect=AnalysisError("Проверочная ошибка API")
        ) as model:
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
            next(b for b in app.button if "демо-комплект" in b.label).click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["ai_status"], "failed")
            model.assert_called_once()
            self.assertTrue(any("ошибкой" in item.value for item in app.info))
            self.assertFalse(any("AI не обнаружил" in item.value for item in app.success))
            app.checkbox(key="use_ai").uncheck().run()
            self.assertEqual(app.session_state["ai_status"], "failed")
            self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
