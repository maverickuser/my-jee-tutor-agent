import json
import unittest
from io import BytesIO
from unittest.mock import patch

from scripts.garak_agent_adapter import GarakAgentHandler


class GarakAgentAdapterTest(unittest.TestCase):
    def test_garak_payload_disables_artifact_writing(self):
        GarakAgentHandler.image_input = {"image_s3_prefix": "s3://state-bucket/cd-evals-images/"}
        handler = GarakAgentHandler.__new__(GarakAgentHandler)
        handler.path = "/garak"
        body = json.dumps({"text": "probe"}).encode("utf-8")
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = BytesIO(body)

        with (
            patch.object(handler, "_send_json") as send_json,
            patch("jee_tutor.handler.handle_tutor_invocation", return_value={"analysis": "ok"}) as tutor,
        ):
            handler.do_POST()

        tutor.assert_called_once()
        payload = tutor.call_args.args[0]
        self.assertEqual(payload["image_s3_prefix"], "s3://state-bucket/cd-evals-images/")
        self.assertEqual(payload["task"], "probe")
        self.assertFalse(payload["save_analysis_pdf"])
        self.assertNotIn("metadata", payload)
        send_json.assert_called_once_with({"text": "ok"})


if __name__ == "__main__":
    unittest.main()
