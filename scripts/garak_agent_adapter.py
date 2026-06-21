import argparse
import base64
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


class GarakAgentHandler(BaseHTTPRequestHandler):
    image_input: dict[str, str]

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
            from jee_tutor.handler import handle_tutor_invocation

            request = self._read_json()
            prompt = str(request.get("text", ""))
            agent_response = handle_tutor_invocation(
                {
                    **self.image_input,
                    "task": prompt,
                    "save_analysis_pdf": False,
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
    parser = argparse.ArgumentParser(
        description="Expose the tutor agent through garak's REST shape."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--image-folder",
        default="tests/fixtures/image_folder",
        help="Local fixture folder used to build a single image_data_uri for each garak prompt.",
    )
    parser.add_argument(
        "--image-s3-prefix",
        default=None,
        help="S3 prefix containing live eval attempt images. Overrides --image-folder.",
    )
    args = parser.parse_args()

    if args.image_s3_prefix:
        GarakAgentHandler.image_input = {"image_s3_prefix": args.image_s3_prefix}
    else:
        image_folder = Path(args.image_folder).resolve()
        GarakAgentHandler.image_input = {
            "image_data_uri": _first_folder_image_data_uri(image_folder)
        }
    server = ThreadingHTTPServer((args.host, args.port), GarakAgentHandler)
    server.serve_forever()


def _first_folder_image_data_uri(image_folder: Path) -> str:
    supported_formats = {
        ".jpg": "jpeg",
        ".jpeg": "jpeg",
        ".png": "png",
        ".webp": "webp",
    }
    image_paths = sorted(
        path
        for path in image_folder.iterdir()
        if path.is_file() and path.suffix.lower() in supported_formats
    )
    if not image_paths:
        supported = ", ".join(sorted(supported_formats))
        raise ValueError(f"Image folder contains no supported images ({supported}): {image_folder}")

    image_path = image_paths[0]
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    image_format = supported_formats[image_path.suffix.lower()]
    return f"data:image/{image_format};base64,{encoded}"


if __name__ == "__main__":
    main()
