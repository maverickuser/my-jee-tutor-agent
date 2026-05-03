import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


class GarakAgentHandler(BaseHTTPRequestHandler):
    image_folder: str

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        self._send_json({"status": "ok"})

    def do_POST(self) -> None:
        if self.path != "/garak":
            self.send_error(404)
            return

        try:
            from agentcore_handler import handle_tutor_invocation

            request = self._read_json()
            prompt = str(request.get("text", ""))
            agent_response = handle_tutor_invocation(
                {
                    "image_folder": self.image_folder,
                    "question_context": prompt,
                    "metadata": {"source": "garak"},
                    "tags": ["garak", "cd-security-scan"],
                }
            )
        except Exception as exc:
            self._send_json({"text": f"adapter error: {exc}"}, status=500)
            return

        if "analysis" in agent_response:
            self._send_json({"text": agent_response["analysis"]})
            return

        error = agent_response.get("error", "Agent returned an error.")
        details = agent_response.get("details", [])
        self._send_json({"text": " ".join([error, *details]).strip()})

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("GARAK_ADAPTER_DEBUG") == "1":
            super().log_message(format, *args)

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}
        return json.loads(raw_body.decode("utf-8"))

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Expose the tutor agent through garak's REST shape.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--image-folder",
        default="tests/fixtures/image_folder",
        help="Folder of sample attempt images supplied with each garak prompt.",
    )
    args = parser.parse_args()

    image_folder = Path(args.image_folder).resolve()
    GarakAgentHandler.image_folder = str(image_folder)
    server = ThreadingHTTPServer((args.host, args.port), GarakAgentHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
