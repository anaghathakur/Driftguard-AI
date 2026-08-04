from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def base_spec() -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/payments": {
                "post": {
                    "summary": "Create payment",
                    "parameters": [
                        {
                            "name": "trace_id",
                            "in": "header",
                            "required": False,
                            "schema": {"type": "string"},
                        }
                    ],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["amount"],
                                    "properties": {
                                        "amount": {"type": "integer"},
                                        "currency": {
                                            "type": "string",
                                            "enum": ["INR", "USD"],
                                        },
                                    },
                                }
                            }
                        }
                    },
                    "responses": {
                        "201": {
                            "description": "Created",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "status": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }


@pytest.fixture
def clone():
    return deepcopy

