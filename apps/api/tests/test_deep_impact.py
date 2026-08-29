from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from apps.api.app.core.exceptions import DriftGuardError
from apps.api.app.domain.repository import RepositoryScan, ScannedSourceFile
from apps.api.app.infrastructure.firestore_analysis_repository import (
    FirestoreAnalysisRepository,
)
from apps.api.app.infrastructure.sqlite_analysis_repository import SQLiteAnalysisRepository
from apps.api.app.infrastructure.sqlite_monitor_repository import SQLiteMonitorRepository
from apps.api.app.migration.context import MigrationContext, build_prompt
from apps.api.app.monitoring.service import ApiMonitorService, MonitorCheckService
from apps.api.app.monitoring.specification_source import RemoteSpecification
from apps.api.app.openapi.differ import ContractDiffer
from apps.api.app.openapi.normalizer import normalize_openapi
from apps.api.app.reports.pdf_report import build_analysis_pdf
from apps.api.app.repository.code_analyzer import RepositoryCodeAnalyzer
from apps.api.app.repository.github_source import GitHubRepositoryArchive
from apps.api.app.repository.matcher import ApiImpactMatcher
from apps.api.app.risk.classifier import RiskClassifier
from apps.api.app.schemas.impact import (
    ChangeImpact,
    ImpactAnalysisKind,
    ImpactMatch,
    ImpactTraceRelation,
    ImpactTraceStep,
    MatchConfidence,
    MatchKind,
)
from apps.api.app.schemas.monitor import MonitorCreateRequest
from apps.api.app.services.analysis_pipeline import AnalysisPipelineService
from apps.api.app.services.comparison import SpecificationComparisonService
from apps.api.app.services.report_service import build_analysis_report


def changed_spec(base_spec, clone):
    new = clone(base_spec)
    operation = next(iter(new["paths"].values()))["post"]
    schema = operation["requestBody"]["content"]
    schema = schema["application/json"]["schema"]
    schema["properties"]["customer_id"] = {"type": "string"}
    schema["required"].append("customer_id")
    return new


def scan(files: dict[str, str]) -> RepositoryScan:
    return RepositoryScan(
        archive_sha256="0" * 64,
        archive_entries=len(files),
        files=tuple(
            ScannedSourceFile(path=path, content=content, size_bytes=len(content))
            for path, content in sorted(files.items())
        ),
        skipped_files=0,
        skipped_reasons={},
    )


def matches_for(base_spec, new_spec, files, *, depth=3, max_symbols=10_000, max_edges=25_000):
    old_contract = normalize_openapi(base_spec)
    new_contract = normalize_openapi(new_spec)
    changes = ContractDiffer().compare(old_contract, new_contract)
    result = ApiImpactMatcher(
        max_impact_depth=depth,
        max_symbols=max_symbols,
        max_edges=max_edges,
    ).analyze(changes, scan(files), old_contract, new_contract)
    return result.impacts[0].matches, result.code_analysis


def test_python_direct_wrapper_and_multilevel_transitive_trace(base_spec, clone):
    files = {
        "demo/payments.py": """
import requests

def create_payment(payload):
    return requests.post(f"{BASE_URL}/payments", json=payload)
""",
        "demo/checkout.py": """
from payments import create_payment

def checkout(order):
    return create_payment({"amount": order.total})
""",
        "demo/orders.py": """
from checkout import checkout

def submit_order(order):
    return checkout(order)
""",
    }

    matches, summary = matches_for(base_spec, changed_spec(base_spec, clone), files)

    by_depth = {match.impact_depth: match for match in matches}
    assert set(by_depth) == {0, 1, 2}
    assert by_depth[0].symbol.endswith("payments.create_payment")
    assert by_depth[0].analysis_kind.value == "direct"
    assert by_depth[1].symbol.endswith("checkout.checkout")
    assert by_depth[1].match_kind.value == "wrapper"
    assert by_depth[2].symbol.endswith("orders.submit_order")
    assert by_depth[2].match_kind.value == "transitive_call"
    assert [step.symbol.rsplit(".", 1)[-1] for step in by_depth[2].trace] == [
        "create_payment",
        "checkout",
        "submit_order",
    ]
    assert summary.symbols_discovered == 3
    assert summary.call_edges_resolved == 2
    assert summary.direct_api_anchors == 1
    assert summary.transitive_matches == 2


def test_python_constants_concatenation_and_namespaced_import(base_spec, clone):
    files = {
        "demo/payments.py": """
import httpx
BASE = "/api"
PAYMENTS = BASE + "/payments"

def create_payment(payload):
    return httpx.post(PAYMENTS, json=payload)
""",
        "demo/checkout.py": """
import payments

def checkout(payload):
    return payments.create_payment(payload)
""",
    }
    base_spec["paths"]["/api/payments"] = base_spec["paths"].pop("/payments")
    new = changed_spec(base_spec, clone)

    matches, _ = matches_for(base_spec, new, files)

    assert [(match.impact_depth, match.symbol.rsplit(".", 1)[-1]) for match in matches] == [
        (0, "create_payment"),
        (1, "checkout"),
    ]


def test_python_cycle_and_depth_limit_do_not_over_propagate(base_spec, clone):
    files = {
        "demo/payments.py": """
import requests
from checkout import checkout
def create_payment(payload):
    checkout(payload)
    return requests.post("/payments", json=payload)
""",
        "demo/checkout.py": """
from payments import create_payment
def checkout(payload):
    return create_payment(payload)
""",
        "demo/orders.py": """
from checkout import checkout
def submit_order(order):
    return checkout(order)
""",
    }

    matches, _ = matches_for(base_spec, changed_spec(base_spec, clone), files, depth=1)

    assert {match.impact_depth for match in matches} == {0, 1}
    assert len([match for match in matches if match.impact_depth == 1]) == 1


def test_python_ambiguous_names_dynamic_paths_and_parser_failure_fall_back(
    base_spec,
    clone,
):
    files = {
        "demo/broken.py": 'def broken(:\n    requests.post("/payments")\n',
        "demo/dynamic.py": """
def dynamic(client, payment_id):
    return client.post(build_path(payment_id))
""",
        "demo/one.py": "def create(payload):\n    return payload\n",
        "demo/two.py": "def create(payload):\n    return payload\n",
        "demo/unrelated.py": "def caller(value):\n    return create(value)\n",
    }

    matches, summary = matches_for(base_spec, changed_spec(base_spec, clone), files)

    assert len(matches) == 1
    assert matches[0].file_path == "demo/broken.py"
    assert matches[0].analysis_kind.value == "lexical"
    assert summary.parser_failures == 1
    assert summary.parser_failure_files == ["demo/broken.py"]


def test_javascript_typescript_direct_and_multilevel_import_chain(base_spec, clone):
    files = {
        "demo/payments.ts": """
import axios from "axios";
const BASE = "";
export function createPayment(payload) {
  return axios.post(`${BASE}/payments`, payload);
}
""",
        "demo/checkout.ts": """
import { createPayment } from "./payments";
export function checkout(order) {
  return createPayment({ amount: order.total });
}
""",
        "demo/orders.ts": """
import { checkout } from "./checkout";
export function submitOrder(order) {
  return checkout(order);
}
""",
    }

    matches, summary = matches_for(base_spec, changed_spec(base_spec, clone), files)

    by_depth = {match.impact_depth: match for match in matches}
    assert set(by_depth) == {0, 1, 2}
    assert by_depth[0].symbol.endswith("payments.createPayment")
    assert by_depth[1].symbol.endswith("checkout.checkout")
    assert by_depth[2].symbol.endswith("orders.submitOrder")
    assert all(match.language == "typescript" for match in matches), [
        match.model_dump(mode="json") for match in matches
    ]
    assert summary.call_edges_resolved == 2


def test_javascript_fetch_request_constants_and_namespace_import(base_spec, clone):
    files = {
        "demo/payments.js": """
const PATH = "/payments";
export function createPayment(payload) {
  return fetch(PATH, { method: "POST", body: payload });
}
""",
        "demo/checkout.js": """
import * as payments from "./payments";
export function checkout(payload) {
  return payments.createPayment(payload);
}
""",
        "demo/request.ts": """
export function send(client, payload) {
  return client.request({ method: "POST", url: "/payments", data: payload });
}
""",
    }

    matches, _ = matches_for(base_spec, changed_spec(base_spec, clone), files)

    assert all(match.symbol for match in matches), [
        match.model_dump(mode="json") for match in matches
    ]
    symbols = {(match.impact_depth, match.symbol.rsplit(".", 1)[-1]) for match in matches}
    assert (0, "createPayment") in symbols
    assert (1, "checkout") in symbols
    assert (0, "send") in symbols


def test_javascript_cycle_dynamic_path_and_unsupported_language_fallback(base_spec, clone):
    files = {
        "demo/a.ts": """
import { b } from "./b";
export function a(client, value) {
  b(value);
  return client.post(makePath(value));
}
""",
        "demo/b.ts": """
import { a } from "./a";
export function b(value) { return a(value); }
""",
        "demo/Client.java": 'client.post("/payments");',
    }

    matches, _ = matches_for(base_spec, changed_spec(base_spec, clone), files)

    assert len(matches) == 1
    assert matches[0].file_path == "demo/Client.java"
    assert matches[0].analysis_kind.value == "lexical"


def test_semantic_and_lexical_direct_match_is_deduplicated_deterministically(
    base_spec,
    clone,
):
    files = {
        "demo/client.py": 'def pay(client):\n    return client.post("/payments")\n',
    }

    first, _ = matches_for(base_spec, changed_spec(base_spec, clone), files)
    second, _ = matches_for(base_spec, changed_spec(base_spec, clone), files)

    assert first == second
    assert len(first) == 1
    assert first[0].analysis_kind.value == "direct"
    assert first[0].match_kind.value == "path_and_method"
    assert first[0].trace[0].relation.value == "direct_api_usage"


def test_code_graph_symbol_and_edge_limits_fail_safely():
    repository = scan(
        {
            "demo/client.py": "def one():\n    two()\ndef two():\n    return None\n",
        }
    )

    with pytest.raises(DriftGuardError) as symbol_error:
        RepositoryCodeAnalyzer(max_symbols=1).analyze(repository)
    with pytest.raises(DriftGuardError) as edge_error:
        RepositoryCodeAnalyzer(max_edges=1).analyze(
            scan(
                {
                    "demo/client.py": (
                        "def one():\n    two()\n    three()\n"
                        "def two():\n    return None\n"
                        "def three():\n    return None\n"
                    )
                }
            )
        )

    assert symbol_error.value.code == "repository_code_analysis_limit_exceeded"
    assert edge_error.value.details == {"limit": "graph_edges", "maximum": 1}


def repository_zip(files: dict[str, str]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return output.getvalue()


def remote_spec(value: dict) -> RemoteSpecification:
    content = json.dumps(value, sort_keys=True).encode()
    return RemoteSpecification(
        source_url="https://api.example.com/openapi.json",
        filename="openapi.json",
        content_type="application/json",
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def test_deep_matches_persist_and_render_in_json_pdf_and_monitoring(
    analysis_repository,
    base_spec,
    clone,
):
    new = changed_spec(base_spec, clone)
    archive = repository_zip(
        {
            "demo/payments.py": (
                "import requests\n"
                "def create_payment(payload):\n"
                '    return requests.post("/payments", json=payload)\n'
            ),
            "demo/checkout.py": (
                "from payments import create_payment\n"
                "def checkout(order):\n"
                "    return create_payment(order)\n"
            ),
            "demo/orders.py": (
                "from checkout import checkout\n"
                "def submit_order(order):\n"
                "    return checkout(order)\n"
            ),
        }
    )
    pipeline = AnalysisPipelineService(
        analysis_repository,
        RiskClassifier("missing.joblib", "missing.json"),
    )

    class Source:
        def __init__(self):
            self.current = remote_spec(base_spec)

        async def fetch(self, _url):
            return self.current

    class GitHub:
        async def fetch(self, _url, ref=None):
            return GitHubRepositoryArchive(
                owner="example",
                repository="demo",
                ref=ref,
                filename="demo.zip",
                content=archive,
            )

    monitor_repository = SQLiteMonitorRepository(analysis_repository.database_path)
    monitor_repository.initialize()
    source = Source()
    monitor_service = ApiMonitorService(monitor_repository, source)
    check_service = MonitorCheckService(
        monitor_repository,
        source,
        GitHub(),
        pipeline,
    )

    created = asyncio.run(
        monitor_service.create(
            MonitorCreateRequest(
                name="Deep impact monitor",
                specification_url="https://api.example.com/openapi.json",
                repository_url="https://github.com/example/demo",
                check_interval_minutes=60,
            )
        )
    )
    source.current = remote_spec(new)
    checked = asyncio.run(check_service.check(created.monitor_id))
    assert checked.status.value == "changed"
    assert checked.analysis_id is not None

    stored_matches = pipeline.get_matches(checked.analysis_id)
    assert [match.impact_depth for match in stored_matches] == [0, 1, 2]
    assert stored_matches[2].trace[-1].symbol.endswith("orders.submit_order")
    report = build_analysis_report(pipeline, checked.analysis_id)
    assert report.summary.direct_matches == 1
    assert report.summary.transitive_matches == 2
    assert report.summary.max_impact_depth == 2
    assert "submit_order" in report.model_dump_json()
    pdf = build_analysis_pdf(report)
    assert pdf.startswith(b"%PDF-")
    assert len(pipeline.get_risk_predictions(checked.analysis_id)) == 1
    assert len(pipeline.get_migration_recommendations(checked.analysis_id)) == 1
    change = pipeline.get_changes(checked.analysis_id)[0]
    risk = pipeline.get_risk_predictions(checked.analysis_id)[0]
    impact = ChangeImpact(
        change_id=change.change_id,
        path=change.path,
        method=change.method,
        matches=[
            ImpactMatch.model_validate(match.model_dump(exclude={"change_id"}))
            for match in stored_matches
        ],
    )
    prompt = json.loads(
        build_prompt(
            MigrationContext(
                analysis_id=checked.analysis_id,
                change=change,
                impact=impact,
                risk=risk,
            )
        ).user_prompt
    )
    included = prompt["repository_impact"]["included_matches"]
    assert included[2]["impact_depth"] == 2
    assert included[2]["impact_trace"][-1]["symbol"].endswith("orders.submit_order")


def test_sqlite_additively_migrates_historical_match_rows(analysis_repository):
    database_path = analysis_repository.database_path.parent / f"legacy-{uuid4()}.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE repository_matches (
            match_id INTEGER PRIMARY KEY,
            analysis_id TEXT NOT NULL,
            change_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            line INTEGER NOT NULL,
            column_number INTEGER NOT NULL,
            match_kind TEXT NOT NULL,
            confidence TEXT NOT NULL,
            evidence TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO repository_matches (
            match_id, analysis_id, change_id, ordinal, file_path,
            line, column_number, match_kind, confidence, evidence
        ) VALUES (1, 'analysis-old', 'change-old', 1, 'client.py',
                  4, 8, 'path_and_method', 'high', '/payments')
        """
    )
    connection.commit()
    connection.close()

    try:
        repository = SQLiteAnalysisRepository(database_path)
        repository.initialize()
        connection = sqlite3.connect(database_path)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(repository_matches)")}
        connection.close()
        assert {
            "symbol",
            "language",
            "impact_depth",
            "analysis_kind",
            "trace_json",
        } <= columns
        historical = repository.get_matches("analysis-old")[0]
        assert historical.analysis_kind == "lexical"
        assert historical.impact_depth == 0
        assert historical.trace == ()
    finally:
        database_path.unlink(missing_ok=True)


def test_firestore_round_trips_deep_match_fields(base_spec, clone):
    class Reference:
        def __init__(self, path):
            self.path = path

        def collection(self, name):
            return Collection((*self.path, name))

    class Collection:
        def __init__(self, path, snapshots=None):
            self.path = path
            self.snapshots = snapshots or []

        def document(self, name):
            return Reference((*self.path, name))

        def order_by(self, _field):
            return self

        def stream(self):
            return self.snapshots

    class Snapshot:
        def __init__(self, data):
            self.data = data

        def to_dict(self):
            return self.data

    class CapturingFirestore(FirestoreAnalysisRepository):
        def __init__(self):
            self._analyses = Collection(("analyses",))
            self.writes = []

        def _commit_sets(self, writes):
            self.writes.extend(writes)

        def _finalize_success(self, **_kwargs):
            return None

    old_content = json.dumps(base_spec, sort_keys=True).encode()
    new_spec = changed_spec(base_spec, clone)
    new_content = json.dumps(new_spec, sort_keys=True).encode()
    comparison = SpecificationComparisonService().compare_contracts(
        old_contract=normalize_openapi(base_spec),
        old_content=old_content,
        new_contract=normalize_openapi(new_spec),
        new_content=new_content,
    )
    change = comparison.changes[0]
    trace = [
        ImpactTraceStep(
            file_path="payments.py",
            symbol="payments.create_payment",
            relation=ImpactTraceRelation.DIRECT_API_USAGE,
            line=4,
            column=12,
            evidence='requests.post("/payments")',
        )
    ]
    match = ImpactMatch(
        file_path="payments.py",
        line=4,
        column=12,
        match_kind=MatchKind.DIRECT_SEMANTIC,
        confidence=MatchConfidence.HIGH,
        evidence='requests.post("/payments")',
        symbol="payments.create_payment",
        language="python",
        impact_depth=0,
        analysis_kind=ImpactAnalysisKind.DIRECT,
        trace=trace,
    )
    repository = CapturingFirestore()
    repository.save_success(
        analysis_id="analysis-1",
        comparison=comparison,
        repository_summary=None,
        impact_summary=None,
        impacts=[
            ChangeImpact(
                change_id=change.change_id,
                path=change.path,
                method=change.method,
                matches=[match],
            )
        ],
        risk_predictions=[],
        migration_recommendations=[],
        stage_id=1,
        completed_at=datetime.now(UTC),
        duration_ms=1,
    )
    match_data = next(data for reference, data in repository.writes if "matches" in reference.path)
    assert match_data["symbol"] == "payments.create_payment"
    assert match_data["analysis_kind"] == "direct"
    assert match_data["trace"][0]["relation"] == "direct_api_usage"

    match_data["match_ordinal"] = 1
    reader = object.__new__(FirestoreAnalysisRepository)
    matches_collection = Collection(("matches",), [Snapshot(match_data)])

    class AnalysesCollection(Collection):
        def document(self, _name):
            class AnalysisReference(Reference):
                def collection(self, _collection_name):
                    return matches_collection

            return AnalysisReference(("analyses", "analysis-1"))

    reader._analyses = AnalysesCollection(("analyses",))
    stored = reader.get_matches("analysis-1")[0]
    assert stored.symbol == "payments.create_payment"
    assert stored.analysis_kind == "direct"
    assert stored.trace[0]["relation"] == "direct_api_usage"
