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
from collections import OrderedDict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from fastapi import Depends, FastAPI, HTTPException, Request, Security  # type: ignore[import-not-found]
    from fastapi.middleware.cors import CORSMiddleware  # type: ignore[import-not-found]
    from fastapi.responses import JSONResponse  # type: ignore[import-not-found]
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # type: ignore[import-not-found]
    from pydantic import BaseModel, Field

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

# ---------------------------------------------------------------------------
# Bounded dict for in-memory state (prevents unbounded memory growth)
# ---------------------------------------------------------------------------

_MAX_WEBHOOKS: int = 100
_MAX_RUN_STATUS: int = 1_000


class _BoundedDict(OrderedDict[str, Any]):
    """OrderedDict that evicts the oldest entry when capacity is exceeded."""

    def __init__(self, max_size: int, *args: Any, **kwargs: Any) -> None:
        self._max_size = max_size
        super().__init__(*args, **kwargs)

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        while len(self) > self._max_size:
            self.popitem(last=False)


if HAS_FASTAPI:
    app = FastAPI(
        title="DD Agents API",
        description="REST API for forensic M&A due diligence pipeline",
        version="1.0.0",
    )
    security = HTTPBearer()

    # --- CORS middleware ---
    _cors_origins = os.environ.get("DD_CORS_ORIGINS", "").strip()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins.split(",") if _cors_origins else [],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # --- Global exception handler (sanitize error messages) ---
    @app.exception_handler(Exception)  # type: ignore[misc, untyped-decorator]
    async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error: %s", exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

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

        question: str = Field(max_length=10_000, description="Question text (max 10K chars)")
        run_dir: str = Field(max_length=1_000, description="Path to pipeline run directory")

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

    _webhooks: _BoundedDict = _BoundedDict(_MAX_WEBHOOKS)
    _run_status: _BoundedDict = _BoundedDict(_MAX_RUN_STATUS)

    # ---------------------------------------------------------------------------
    # Path validation (prevent directory traversal)
    # ---------------------------------------------------------------------------

    def _get_runs_base_dir() -> Path:
        """Return the base directory that run_dir paths must reside under."""
        return Path(os.environ.get("DD_RUNS_DIR", os.getcwd())).resolve()

    def _validate_path(user_path: str) -> Path:
        """Resolve a user-provided path and reject traversal attempts.

        The resolved path must fall under the configured runs base
        directory (``DD_RUNS_DIR`` env var, defaults to cwd).
        """
        resolved = Path(user_path).resolve()
        base = _get_runs_base_dir()
        if not resolved.is_relative_to(base):
            raise HTTPException(
                status_code=400,
                detail="Path traversal not allowed: path must be under the runs directory",
            )
        return resolved

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
        config_path = _validate_path(request.config_path)
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
        result: RunStatusResponse = _run_status[run_id]
        return result

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

        merged_dir = _validate_path(run_dir) / "findings" / "merged"
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
            index = indexer.index_report(_validate_path(request.run_dir))
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
            logger.exception("Query failed: %s", exc)
            raise HTTPException(status_code=500, detail="Query processing failed") from exc

    # --- Webhook endpoints ---

    @app.post("/api/v1/webhooks", response_model=WebhookConfig)  # type: ignore[misc, untyped-decorator]
    def register_webhook(
        config: WebhookConfig,
        _api_key: str = Depends(verify_api_key),
    ) -> WebhookConfig:
        """Register a webhook for pipeline events."""
        # Validate webhook URL to prevent SSRF
        from dd_agents.net_safety import UnsafeURLError, validate_url

        try:
            validate_url(config.url)
        except UnsafeURLError as exc:
            raise HTTPException(status_code=400, detail=f"Unsafe webhook URL: {exc}") from exc

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
