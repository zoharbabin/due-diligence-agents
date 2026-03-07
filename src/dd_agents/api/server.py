"""FastAPI REST API for DD pipeline (Issue #133).

Provides endpoints to:
- Trigger pipeline runs
- Check run status
- Retrieve reports and findings
- Query findings with natural language
- Manage webhooks

Requires ``pip install fastapi uvicorn`` (optional dependency).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from fastapi import Depends, FastAPI, HTTPException, Security  # type: ignore[import-not-found]
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # type: ignore[import-not-found]
    from pydantic import BaseModel, Field

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

if HAS_FASTAPI:
    app = FastAPI(
        title="DD Agents API",
        description="REST API for forensic M&A due diligence pipeline",
        version="1.0.0",
    )
    security = HTTPBearer()

    # ---------------------------------------------------------------------------
    # Auth
    # ---------------------------------------------------------------------------

    def _get_api_key() -> str:
        return os.environ.get("DD_API_KEY", "")

    _security_dep = Security(security)

    def verify_api_key(credentials: HTTPAuthorizationCredentials = _security_dep) -> str:  # noqa: B008
        """Verify the API key from the Authorization header."""
        expected = _get_api_key()
        if not expected:
            raise HTTPException(status_code=500, detail="DD_API_KEY not configured")
        if not secrets.compare_digest(credentials.credentials, expected):
            raise HTTPException(status_code=401, detail="Invalid API key")
        return str(credentials.credentials)

    # ---------------------------------------------------------------------------
    # Request/Response Models
    # ---------------------------------------------------------------------------

    class PipelineRunRequest(BaseModel):
        """Request to trigger a pipeline run."""

        config_path: str = Field(description="Path to deal-config.json")
        mode: str = Field(default="full", description="full or incremental")
        quick_scan: bool = Field(default=False, description="Quick red-flag scan only")

    class PipelineRunResponse(BaseModel):
        """Response after triggering a pipeline run."""

        run_id: str = Field(description="Unique run identifier")
        status: str = Field(description="Pipeline status")
        message: str = Field(default="")

    class RunStatusResponse(BaseModel):
        """Pipeline run status."""

        run_id: str
        status: str
        current_step: int = 0
        total_steps: int = 35
        completed_steps: int = 0
        errors: list[str] = Field(default_factory=list)

    class FindingsResponse(BaseModel):
        """Findings from a completed run."""

        total: int = 0
        by_severity: dict[str, int] = Field(default_factory=dict)
        findings: list[dict[str, Any]] = Field(default_factory=list)

    class QueryRequest(BaseModel):
        """Natural language query."""

        question: str
        run_dir: str = Field(description="Path to pipeline run directory")

    class QueryResponse(BaseModel):
        """Query response."""

        answer: str
        confidence: str = "medium"
        sources: list[dict[str, Any]] = Field(default_factory=list)

    class WebhookConfig(BaseModel):
        """Webhook configuration."""

        id: str = Field(default="")
        url: str = Field(description="Webhook URL")
        events: list[str] = Field(
            default_factory=lambda: ["run.completed", "run.failed"],
            description="Events to subscribe to",
        )
        secret: str = Field(default="", description="Shared secret for HMAC verification")
        active: bool = Field(default=True)

    # ---------------------------------------------------------------------------
    # In-memory state (for webhook configs)
    # ---------------------------------------------------------------------------

    _webhooks: dict[str, WebhookConfig] = {}
    _run_status: dict[str, RunStatusResponse] = {}

    # ---------------------------------------------------------------------------
    # Endpoints
    # ---------------------------------------------------------------------------

    @app.get("/health")  # type: ignore[misc, untyped-decorator]
    def health_check() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok", "service": "dd-agents-api"}

    @app.post("/api/v1/runs", response_model=PipelineRunResponse)  # type: ignore[misc, untyped-decorator]
    def trigger_run(
        request: PipelineRunRequest,
        _api_key: str = Depends(verify_api_key),
    ) -> PipelineRunResponse:
        """Trigger a new pipeline run."""
        config_path = Path(request.config_path)
        if not config_path.exists():
            raise HTTPException(status_code=404, detail=f"Config not found: {request.config_path}")

        run_id = f"api_{secrets.token_hex(8)}"

        _run_status[run_id] = RunStatusResponse(
            run_id=run_id,
            status="queued",
            total_steps=35,
        )

        return PipelineRunResponse(
            run_id=run_id,
            status="queued",
            message=f"Pipeline run queued. Mode: {request.mode}",
        )

    @app.get("/api/v1/runs/{run_id}/status", response_model=RunStatusResponse)  # type: ignore[misc, untyped-decorator]
    def get_run_status(
        run_id: str,
        _api_key: str = Depends(verify_api_key),
    ) -> RunStatusResponse:
        """Get the status of a pipeline run."""
        if run_id not in _run_status:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return _run_status[run_id]

    @app.get("/api/v1/runs/{run_id}/findings", response_model=FindingsResponse)  # type: ignore[misc, untyped-decorator]
    def get_findings(
        run_id: str,
        run_dir: str = "",
        severity: str | None = None,
        _api_key: str = Depends(verify_api_key),
    ) -> FindingsResponse:
        """Retrieve findings from a completed run."""
        if not run_dir:
            raise HTTPException(status_code=400, detail="run_dir query parameter required")

        merged_dir = Path(run_dir) / "findings" / "merged"
        if not merged_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"Findings not found at {merged_dir}")

        findings: list[dict[str, Any]] = []
        by_severity: dict[str, int] = {}

        for f in sorted(merged_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                customer_findings = data.get("findings", [])
                for finding in customer_findings:
                    sev = finding.get("severity", "P3")
                    by_severity[sev] = by_severity.get(sev, 0) + 1
                    if severity and sev != severity:
                        continue
                    findings.append(finding)
            except Exception:
                continue

        return FindingsResponse(
            total=len(findings),
            by_severity=by_severity,
            findings=findings[:500],  # Cap response size
        )

    @app.post("/api/v1/query", response_model=QueryResponse)  # type: ignore[misc, untyped-decorator]
    async def query_findings(
        request: QueryRequest,
        _api_key: str = Depends(verify_api_key),
    ) -> QueryResponse:
        """Query findings with natural language."""
        try:
            from dd_agents.query.engine import QueryEngine
            from dd_agents.query.indexer import FindingIndexer

            indexer = FindingIndexer()
            index = indexer.index_report(Path(request.run_dir))
            engine = QueryEngine(index)
            result = await engine.query(request.question)
            return QueryResponse(
                answer=result.answer,
                confidence=result.confidence,
                sources=result.sources,
            )
        except ImportError as exc:
            raise HTTPException(status_code=501, detail="Query module not available") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # --- Webhook endpoints ---

    @app.post("/api/v1/webhooks", response_model=WebhookConfig)  # type: ignore[misc, untyped-decorator]
    def register_webhook(
        config: WebhookConfig,
        _api_key: str = Depends(verify_api_key),
    ) -> WebhookConfig:
        """Register a webhook for pipeline events."""
        if not config.id:
            config.id = f"wh_{secrets.token_hex(6)}"
        _webhooks[config.id] = config
        return config

    @app.get("/api/v1/webhooks", response_model=list[WebhookConfig])  # type: ignore[misc, untyped-decorator]
    def list_webhooks(
        _api_key: str = Depends(verify_api_key),
    ) -> list[WebhookConfig]:
        """List registered webhooks."""
        return list(_webhooks.values())

    @app.delete("/api/v1/webhooks/{webhook_id}")  # type: ignore[misc, untyped-decorator]
    def delete_webhook(
        webhook_id: str,
        _api_key: str = Depends(verify_api_key),
    ) -> dict[str, str]:
        """Remove a webhook."""
        if webhook_id not in _webhooks:
            raise HTTPException(status_code=404, detail="Webhook not found")
        del _webhooks[webhook_id]
        return {"status": "deleted", "id": webhook_id}

else:
    # Stub when FastAPI is not installed
    app = None  # type: ignore[assignment]
