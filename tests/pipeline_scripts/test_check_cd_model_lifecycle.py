import unittest
from datetime import date

from scripts.check_cd_model_lifecycle import FLASH_LITE_MODEL, lifecycle_warning


class CdModelLifecycleTest(unittest.TestCase):
    def test_warning_begins_one_month_before_retirement(self):
        self.assertIsNone(
            lifecycle_warning(FLASH_LITE_MODEL, today=date(2026, 9, 15))
        )
        warning = lifecycle_warning(FLASH_LITE_MODEL, today=date(2026, 9, 16))
        self.assertIn("2026-10-16", warning)

    def test_other_models_do_not_warn(self):
        self.assertIsNone(
            lifecycle_warning("gemini/replacement", today=date(2027, 1, 1))
        )


if __name__ == "__main__":
    unittest.main()
