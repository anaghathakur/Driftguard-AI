from __future__ import annotations

from contextlib import suppress
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.app.core.dependencies import get_analysis_repository
from apps.api.app.infrastructure.sqlite_analysis_repository import (
    SQLiteAnalysisRepository,
)
from apps.api.app.main import app


@pytest.fixture
def analysis_repository():
    test_directory = Path.cwd() / ".pytest-data"
    test_directory.mkdir(exist_ok=True)
    database_path = test_directory / f"{uuid4()}.sqlite3"
    repository = SQLiteAnalysisRepository(database_path)
    repository.initialize()
    try:
        yield repository
    finally:
        database_path.unlink(missing_ok=True)
        with suppress(OSError):
            test_directory.rmdir()


@pytest.fixture
def client(analysis_repository) -> TestClient:
    app.dependency_overrides[get_analysis_repository] = lambda: analysis_repository
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.clear()


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
