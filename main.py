"""
Visitor counter API.

Written as a Google Cloud Functions (2nd gen) HTTP function using the
`functions-framework` package. That means this exact file runs locally
AND deploys to GCP unchanged — there is no "local version" vs
"cloud version" to keep in sync.

Local run:
    functions-framework --target=visitor_count --port=8080 --debug

Cloud deploy (see README.md for full command):
    gcloud functions deploy visitor-count \
        --gen2 --runtime=python312 --trigger-http \
        --entry-point=visitor_count --allow-unauthenticated

Storage:
    Locally, the count is persisted to backend/data/visitor_count.json
    so it survives restarts. In the cloud, swap `LocalCounterStore` for
    `FirestoreCounterStore` (stubbed below) — the request-handling code
    does not need to change.
"""

import json
import os
import threading
from pathlib import Path

import functions_framework
from flask import jsonify

# --------------------------------------------------------------------
# CORS
#
# Cloud Functions do not have Nginx/API Gateway CORS handling by
# default, so headers are set explicitly on every response, following
# Google's own documented pattern for HTTP functions. This also covers
# the browser's CORS preflight (OPTIONS) request.
# --------------------------------------------------------------------
ALLOWED_ORIGINS = {
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "null",  # allows opening index.html directly as a file:// URL
}


def _cors_headers(origin: str) -> dict:
    allow_origin = origin if origin in ALLOWED_ORIGINS else "*"
    return {
        "Access-Control-Allow-Origin": allow_origin,
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "3600",
    }


# --------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------
class LocalCounterStore:
    """Persists the visitor count to a local JSON file. Thread-safe
    enough for local dev use (functions-framework's dev server)."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(0)

    def _read(self) -> int:
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)["count"]

    def _write(self, count: int) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"count": count}, f)

    def increment(self) -> int:
        with self.lock:
            count = self._read() + 1
            self._write(count)
            return count


from google.cloud import firestore

class FirestoreCounterStore:
    def __init__(self, collection="counters", doc_id="resume_visits"):
        self.client = firestore.Client()
        self.doc_ref = self.client.collection(collection).document(doc_id)

    def increment(self) -> int:
        @firestore.transactional
        def _bump(transaction):
            snapshot = self.doc_ref.get(transaction=transaction)
            current = snapshot.get("count") if snapshot.exists else 0
            new_count = current + 1
            transaction.set(self.doc_ref, {"count": new_count})
            return new_count
        return _bump(self.client.transaction())
    
    pass


DATA_FILE = Path(__file__).parent / "data" / "visitor_count.json"
# replace this line near the bottom of the file:
# store = LocalCounterStore(DATA_FILE)
store = FirestoreCounterStore()


# --------------------------------------------------------------------
# HTTP entry point
# --------------------------------------------------------------------
@functions_framework.http
def visitor_count(request):
    origin = request.headers.get("Origin", "")
    headers = _cors_headers(origin)

    # Browser CORS preflight
    if request.method == "OPTIONS":
        return ("", 204, headers)

    if request.method != "POST":
        return (jsonify(error="Method not allowed. Use POST."), 405, headers)

    new_count = store.increment()
    return (jsonify(count=new_count), 200, headers)
