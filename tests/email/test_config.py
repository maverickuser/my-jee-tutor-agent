import os
import unittest
from unittest.mock import patch

from jee_tutor.email.config import EmailConfig


class EmailConfigTest(unittest.TestCase):
    def test_from_env_normalizes_blank_optional_values(self):
        with patch.dict(
            os.environ,
            {
                "EMAIL_FROM_ADDRESS": "  analysis@example.com  ",
                "EMAIL_SUBJECT_TEMPLATE": "  Report  ",
                "EMAIL_BODY_TEMPLATE": "  <p>Hi</p>  ",
                "EMAIL_REGION": "   ",
                "EMAIL_DELIVERY_PROVIDER": "  ",
                "EMAIL_DELIVERY_FUNCTION_ARN": "  ",
            },
            clear=False,
        ):
            config = EmailConfig.from_env()

        self.assertEqual(config.from_address, "analysis@example.com")
        self.assertEqual(config.subject_template, "Report")
        self.assertEqual(config.body_template, "<p>Hi</p>")
        self.assertIsNone(config.region)
        self.assertEqual(config.delivery_provider, "lambda")
        self.assertIsNone(config.delivery_function_arn)

    def test_validate_reports_missing_required_fields_and_lambda_arn(self):
        config = EmailConfig(
            from_address="",
            subject_template="",
            body_template="",
            delivery_provider="lambda",
            delivery_function_arn=None,
        )

        errors = config.validate(require_delivery_function=True)

        self.assertEqual(
            errors,
            [
                "EMAIL_FROM_ADDRESS is required.",
                "EMAIL_SUBJECT_TEMPLATE is required.",
                "EMAIL_BODY_TEMPLATE is required.",
                "EMAIL_DELIVERY_FUNCTION_ARN is required when using lambda delivery.",
            ],
        )

    def test_validate_skips_lambda_arn_when_provider_is_not_lambda(self):
        config = EmailConfig(
            from_address="analysis@example.com",
            subject_template="Report",
            body_template="<p>Hi</p>",
            delivery_provider="ses",
            delivery_function_arn=None,
        )

        errors = config.validate(require_delivery_function=True)

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
