"""
Tests for the visitor counter Cloud Function.

Run from the backend/ directory:
    pytest -v
"""
import importlib
import json
import sys
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def main_module(tmp_path, monkeypatch):
    """Reload main.py with its data file pointed at a throwaway tmp
    path, so tests never touch (or depend on) the real counter file."""
    import main as main_module

    importlib.reload(main_module)
    monkeypatch.setattr(main_module, "DATA_FILE", tmp_path / "visitor_count.json")
    monkeypatch.setattr(main_module, "store", main_module.LocalCounterStore(tmp_path / "visitor_count.json"))
    return main_module


@pytest.fixture
def app():
    return Flask(__name__)


def test_first_request_starts_count_at_one(main_module, app):
    with app.test_request_context("/", method="POST"):
        from flask import request
        body, status, headers = main_module.visitor_count(request)
        assert status == 200
        assert json.loads(body.get_data())["count"] == 1


def test_count_increments_on_each_call(main_module, app):
    with app.test_request_context("/", method="POST"):
        from flask import request
        main_module.visitor_count(request)
        _, status, _ = main_module.visitor_count(request)
    with app.test_request_context("/", method="POST"):
        from flask import request
        body, status, _ = main_module.visitor_count(request)
        assert json.loads(body.get_data())["count"] == 3


def test_cors_headers_present_on_post(main_module, app):
    with app.test_request_context("/", method="POST", headers={"Origin": "http://localhost:5500"}):
        from flask import request
        _, _, headers = main_module.visitor_count(request)
        assert headers["Access-Control-Allow-Origin"] == "http://localhost:5500"


def test_options_preflight_returns_204(main_module, app):
    with app.test_request_context("/", method="OPTIONS"):
        from flask import request
        body, status, headers = main_module.visitor_count(request)
        assert status == 204
        assert "Access-Control-Allow-Methods" in headers


def test_get_method_not_allowed(main_module, app):
    with app.test_request_context("/", method="GET"):
        from flask import request
        _, status, _ = main_module.visitor_count(request)
        assert status == 405
