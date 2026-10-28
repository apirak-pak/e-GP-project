"""Small, credential-free network journal for startup diagnostics."""
from __future__ import annotations

import re
import time
from urllib.parse import urlsplit


def public_address(url: str) -> dict:
    parts = urlsplit(url)
    path = parts.path
    if parts.hostname != "process5.gprocurement.go.th":
        path = "[external path omitted]"
    elif not (re.fullmatch(r"/[\w./-]+\.(?:js|css|woff2?|png|ico|html)", path)
              or path == "/egp-agpc01-web/announcement"
              or path in ("/egp-oann10-service/pb/a-egp-allt-project/announcement",
                          "/egp-oann10-service/pb/a-egp-allt-project/announcement/csv")):
        path = "/" + path.strip("/").split("/")[0] + "/[dynamic path omitted]"
    return {"host": parts.hostname, "path": path}


class NetworkJournal:
    def __init__(self):
        self.pending = {}
        self.responses = []
        self.failures = []
        self.console_categories = []

    def request(self, request):
        self.pending[request] = (time.monotonic(), {**public_address(request.url), "kind": request.resource_type})

    def response(self, response):
        if len(self.responses) < 100:
            self.responses.append({**public_address(response.url), "kind": response.request.resource_type,
                                   "status": response.status})

    def finished(self, request):
        self.pending.pop(request, None)

    def failed(self, request):
        self.finished(request)
        if len(self.failures) < 20:
            code = re.search(r"net::ERR_[A-Z0-9_]+", request.failure or "")
            self.failures.append({**public_address(request.url), "kind": request.resource_type,
                                  "failure": code.group(0) if code else "request_failed"})

    def console(self, message):
        if message.type != "error" or len(self.console_categories) >= 20:
            return
        text = message.text
        categories = ("ChunkLoadError", "Content Security Policy", "Failed to fetch", "ERR_", "CORS")
        self.console_categories.append(next((label for label in categories if label in text), "other_error"))

    def snapshot(self):
        return {"responses": self.responses, "failures": self.failures,
                "pending": [{**info, "elapsed_seconds": round(time.monotonic() - started, 1)}
                            for started, info in list(self.pending.values())[:20]],
                "console_error_categories": self.console_categories}
