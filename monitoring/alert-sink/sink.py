"""Alertmanager webhook receiver for local runs: prints one JSON line per alert, so `docker compose logs alert-sink` is the pager."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Sink(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        for a in body.get("alerts", []):
            line = {"receiver": body.get("receiver"), "alertname": a["labels"].get("alertname"), "status": a.get("status"),
                    "severity": a["labels"].get("severity"), "summary": a.get("annotations", {}).get("summary")}
            print(json.dumps(line), flush=True)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):  # one line per alert, not per request
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 9095), Sink).serve_forever()
