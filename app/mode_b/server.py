"""Standalone no-Flask HTTP server for the Mode B dashboard.

Save as app/mode_b/server.py and run from the project root:
    python -m app.mode_b.server --self-test
    python -m app.mode_b.server --host 127.0.0.1 --port 8765

The live dispatch services are initialized lazily on the first emergency-submit
request, not when the module is imported or when the dashboard is opened.
This avoids loading the large road graph for self-tests or static-page visits.
Mode A files are not modified.
"""
from __future__ import annotations

import argparse
import json
import math
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HTML_FILE = PROJECT_ROOT / "templates" / "mode_b" / "index.html"
CSS_FILE = PROJECT_ROOT / "static" / "mode_b" / "dashboard.css"
JS_FILE = PROJECT_ROOT / "static" / "mode_b" / "dashboard.js"
MAX_BODY_BYTES = 1_000_000


class ModeBState:
    """Lazily owns one live workflow and one compact-routed Mode B service."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.live_service: Any = None
        self.mode_b_service: Any = None
        self.recommendations: dict[str, dict[str, Any]] = {}
        self.initialization_error: str | None = None

    @property
    def initialized(self) -> bool:
        return self.live_service is not None and self.mode_b_service is not None

    def get_services(self) -> tuple[Any, Any]:
        with self._lock:
            if self.initialized:
                return self.live_service, self.mode_b_service
            if self.initialization_error:
                raise RuntimeError(self.initialization_error)
            try:
                # Imports are intentionally lazy: --self-test and GET / do not
                # initialize the large live dispatch graph.
                from app.live_dispatch_service import LiveDispatchService
                from app.mode_b.compact_mode_b_service import CompactModeBDispatchService

                live_service = LiveDispatchService()
                mode_b_service = CompactModeBDispatchService(live_service)
                self.live_service = live_service
                self.mode_b_service = mode_b_service
                return live_service, mode_b_service
            except Exception as exc:
                self.initialization_error = f"{type(exc).__name__}: {exc}"
                raise RuntimeError(
                    "Mode B live services could not be initialized. "
                    "No dispatch was performed. Details: " + self.initialization_error
                ) from exc


STATE = ModeBState()


def json_safe(value: Any) -> Any:
    """Convert common Python containers and non-finite floats to strict JSON."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    # NumPy scalar values may appear in optional metrics; avoid importing NumPy
    # solely for serialization.
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    return str(value)


def route_api_path(path: str) -> tuple[str, str | None] | None:
    """Map a URL path to an operation, useful for simple routing tests."""
    if path == "/api/health":
        return ("health", None)
    if path == "/api/emergencies":
        return ("submit", None)
    parts = [unquote(part) for part in path.strip("/").split("/")]
    if len(parts) == 3 and parts[:2] == ["api", "recommend"] and parts[2]:
        return ("recommend", parts[2])
    if len(parts) == 3 and parts[:2] == ["api", "dispatch"] and parts[2]:
        return ("dispatch", parts[2])
    return None


class ModeBRequestHandler(BaseHTTPRequestHandler):
    server_version = "ModeBStdlib/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep the console concise; requests remain visible during debugging.
        print("[ModeB] " + (fmt % args))

    def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Mapping[str, Any]) -> None:
        body = json.dumps(json_safe(payload), ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", body)

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            raise ValueError("Invalid Content-Length header.") from None
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError(f"Request body must be at most {MAX_BODY_BYTES} bytes.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Request body must contain valid UTF-8 JSON.") from None
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object.")
        return data

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/":
            self._serve_file(HTML_FILE, "text/html; charset=utf-8")
            return
        if path == "/assets/dashboard.css":
            self._serve_file(CSS_FILE, "text/css; charset=utf-8")
            return
        if path == "/assets/dashboard.js":
            self._serve_file(JS_FILE, "text/javascript; charset=utf-8")
            return
        if path == "/api/health":
            self._send_json(200, {
                "status": "ok",
                "backend": "python-standard-library-http.server",
                "live_initialized": STATE.initialized,
                "note": "Live dispatch services initialize on the first emergency submission.",
            })
            return
        self._send_json(404, {"status": "error", "message": "Not found."})

    def _serve_file(self, file_path: Path, content_type: str) -> None:
        try:
            content = file_path.read_bytes()
        except FileNotFoundError:
            self._send_json(404, {
                "status": "error",
                "message": f"Required Mode B file is missing: {file_path.relative_to(PROJECT_ROOT)}",
            })
            return
        self._send_bytes(200, content_type, content)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        operation = route_api_path(path)
        if operation is None or operation[0] == "health":
            self._send_json(404, {"status": "error", "message": "Unknown API endpoint."})
            return
        try:
            with STATE._lock:
                if operation[0] == "submit":
                    self._handle_submit()
                elif operation[0] == "recommend":
                    self._handle_recommend(str(operation[1]))
                elif operation[0] == "dispatch":
                    self._handle_dispatch(str(operation[1]))
        except ValueError as exc:
            self._send_json(400, {"status": "error", "message": str(exc)})
        except RuntimeError as exc:
            self._send_json(503, {"status": "error", "message": str(exc)})
        except Exception as exc:
            # Full traceback goes to the local server console, not the browser.
            traceback.print_exc()
            self._send_json(500, {
                "status": "error",
                "message": f"Mode B request failed: {type(exc).__name__}: {exc}",
            })

    def _handle_submit(self) -> None:
        data = self._read_json()
        required = ("latitude", "longitude", "severity", "condition", "required_facility", "patient_location")
        missing = [name for name in required if name not in data or data[name] in (None, "")]
        if missing:
            self._send_json(400, {
                "status": "error",
                "message": "Missing required emergency fields.",
                "missing_fields": missing,
            })
            return
        try:
            latitude = float(data["latitude"])
            longitude = float(data["longitude"])
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Latitude and longitude must be numeric.") from None
        if not (math.isfinite(latitude) and -90 <= latitude <= 90):
            raise ValueError("Latitude must be between -90 and 90.")
        if not (math.isfinite(longitude) and -180 <= longitude <= 180):
            raise ValueError("Longitude must be between -180 and 180.")

        live_service, _mode_b_service = STATE.get_services()
        emergency = live_service.submit_emergency(
            latitude=latitude,
            longitude=longitude,
            severity=str(data["severity"]).strip(),
            condition=str(data["condition"]).strip(),
            required_facility=str(data["required_facility"]).strip(),
            patient_location=str(data["patient_location"]).strip(),
            area_address=str(data.get("area_address") or "Live Emergency Location").strip(),
            patient_id=data.get("patient_id"),
            request_time=data.get("request_time"),
        )
        self._send_json(201, {"status": "success", "emergency": emergency})

    def _handle_recommend(self, emergency_id: str) -> None:
        _live_service, mode_b_service = STATE.get_services()
        result = mode_b_service.recommend(emergency_id)
        if result.get("status") != "Recommended":
            message = str(result.get("message") or result.get("status") or "No recommendation available.")
            self._send_json(409, {"status": "error", "message": message, "recommendation": result})
            return
        STATE.recommendations[emergency_id] = dict(result)
        self._send_json(200, {"status": "success", "recommendation": result})

    def _handle_dispatch(self, emergency_id: str) -> None:
        if emergency_id not in STATE.recommendations:
            self._send_json(409, {
                "status": "error",
                "message": "Request a Mode B recommendation before dispatching.",
            })
            return
        _live_service, mode_b_service = STATE.get_services()
        result = mode_b_service.dispatch_emergency(emergency_id)
        committed = (
            result.get("status") == "Dispatched"
            and result.get("mode_b_selection_committed") is True
        )
        if not committed:
            status = 409 if result.get("status") in {
                "Emergency Not Found", "Emergency Already Dispatched",
                "Higher Priority Emergency Pending", "No Feasible Candidate",
            } else 500
            self._send_json(status, {
                "status": "error",
                "message": str(result.get("message") or result.get("status") or "Dispatch was not committed."),
                "dispatch": result,
            })
            return

        # Retain the map payload from the reviewed recommendation for the UI.
        previous = STATE.recommendations.get(emergency_id, {})
        for key in ("map_locations", "map_routes", "map_route_status", "map_route_error"):
            if key in previous:
                result[key] = previous[key]
        self._send_json(200, {"status": "success", "dispatch": result})


def _self_test() -> None:
    assert route_api_path("/api/health") == ("health", None)
    assert route_api_path("/api/emergencies") == ("submit", None)
    assert route_api_path("/api/recommend/LIVE-123") == ("recommend", "LIVE-123")
    assert route_api_path("/api/dispatch/LIVE-123") == ("dispatch", "LIVE-123")
    assert route_api_path("/api/recommend/a%2Fb") == ("recommend", "a/b")
    assert route_api_path("/api/no-such-route") is None
    safe = json_safe({"finite": 1.5, "bad": float("nan"), "nested": [float("inf"), 3]})
    assert safe == {"finite": 1.5, "bad": None, "nested": [None, 3]}, safe
    # Do not read static files or import the live dispatch service in a self-test.
    assert not STATE.initialized
    print("Mode B no-Flask server self-test passed.")
    print("Verified: URL routing, JSON input sanitization, lazy service initialization.")
    print("No Flask, live dispatch service, datasets, or Tamil Nadu graph were loaded.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Run safe server helper tests only")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: local computer only)")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port (default: 8765)")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    if not (1 <= args.port <= 65535):
        parser.error("--port must be between 1 and 65535")
    server = ThreadingHTTPServer((args.host, args.port), ModeBRequestHandler)
    print("Mode B standalone HTTP server (no Flask)")
    print(f"Dashboard: http://{args.host}:{args.port}/")
    print("The live workflow initializes only after an emergency is submitted.")
    print("Press Ctrl+C to stop the server.")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping Mode B server...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
