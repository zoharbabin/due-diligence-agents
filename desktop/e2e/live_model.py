"""Live smoke test against the real model. Manual: it calls your provider and costs money.

Usage: python desktop/e2e/live_model.py [--skip-run]
Starts the real `dd-agents serve` on a temp data folder (nothing in ~/.dd-projects is touched),
then drives it over HTTP like the desktop app: provider probe, create project, suggest a setup,
save it, run a small review (economy models, quick scan), read findings, ask one question.
Needs provider credentials in the environment (see docs/user-guide/model-providers.md).
Stdlib only. Exits non-zero on the first failed step.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TOKEN = secrets.token_urlsafe(24)
CONTRACTS = {
    "Subject A/msa.txt": (
        "MASTER SERVICES AGREEMENT between Subject A (Customer) and Target Co (Supplier).\n"
        "Term: 3 years from 1 January 2024, renewing automatically for 1-year terms "
        "unless either party gives 90 days notice.\n"
        "Change of control: Customer may terminate on 30 days notice if Supplier undergoes a change of control.\n"
        "Liability cap: Supplier liability is limited to fees paid in the prior 12 months. "
        "Annual fees: USD 1,200,000.\n"
    ),
    "Subject B/license.txt": (
        "SOFTWARE LICENSE between Subject B (Licensee) and Target Co (Licensor).\n"
        "Licence is non-assignable without Licensor's written consent. Governing law: Delaware.\n"
        "Exclusivity: Licensor shall not license the product to competitors of Licensee in the Territory.\n"
        "Annual fees: USD 300,000. Term: 2 years from 1 March 2025.\n"
    ),
}


def step(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def call(base: str, method: str, path: str, body: Any = None, timeout: float = 120) -> Any:
    req = urllib.request.Request(
        f"{base}/api{path}",
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"FAIL {method} {path}: HTTP {exc.code} {exc.read().decode()[:400]}") from exc


def call_raw(base: str, path: str) -> bytes:
    req = urllib.request.Request(f"{base}/api{path}", headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=60) as res:
        data: bytes = res.read()
        return data


def wait(label: str, poll: Any, done: Any, limit: float) -> Any:
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        state = poll()
        if done(state):
            return state
        time.sleep(3)
    raise SystemExit(f"FAIL {label}: not finished after {limit:.0f}s")


def main() -> None:
    skip_run = "--skip-run" in sys.argv
    work = Path(tempfile.mkdtemp(prefix="dd-live-"))
    room = work / "room"
    for rel, text in CONTRACTS.items():
        (room / rel).parent.mkdir(parents=True, exist_ok=True)
        (room / rel).write_text(text, encoding="utf-8")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "DD_BASE_DIR": str(work / "base"), "DD_API_TOKEN": TOKEN}
    log = (work / "server.log").open("w")
    server = subprocess.Popen(
        [sys.executable, "-m", "dd_agents", "serve", "--port", str(port)],
        env=env,
        stdout=log,
        stderr=log,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        wait("server start", lambda: _up(base), bool, 30)
        step(f"server up on {port}, data in {work}")

        doc = call(base, "GET", "/doctor")
        step(f"provider={doc['provider']} credential={doc['credential_present']} cli={doc['cli']['found']}")
        if not doc["ready"]:
            raise SystemExit("FAIL provider is not ready. Set credentials first")
        probe = call(base, "POST", "/doctor/probe", timeout=180)
        step(f"probe: {probe}")
        if not probe.get("ok"):
            raise SystemExit("FAIL probe")

        project = call(base, "POST", "/projects", {"name": "Live Smoke", "data_room": str(room)})
        slug = project["slug"]
        base_cfg = {
            "config_version": "1.0.0",
            "buyer": {"name": "Buyer Co"},
            "target": {"name": "Target Co"},
            "deal": {"type": "acquisition", "focus_areas": ["change_of_control_clauses"]},
        }
        call(base, "PUT", f"/projects/{slug}/config", base_cfg)
        step(f"project {slug} created")

        call(base, "POST", f"/projects/{slug}/config/suggest")
        step("suggest started")
        draft = wait(
            "suggest",
            lambda: call(base, "GET", f"/projects/{slug}/config/suggest"),
            lambda r: r["state"] in ("done", "error"),
            700,
        )
        if draft["state"] != "done":
            raise SystemExit(f"FAIL suggest: {draft.get('error')}")
        check = call(base, "POST", "/config/validate", draft["config"])
        step(f"draft valid={check['valid']} subjects={len(draft['config'].get('entity_aliases', {}))}")
        if not check["valid"]:
            raise SystemExit(f"FAIL draft is invalid: {check}")
        call(base, "PUT", f"/projects/{slug}/config", draft["config"])
        step("draft saved")
        if skip_run:
            step("OK (run skipped)")
            return

        call(
            base,
            "POST",
            f"/projects/{slug}/run",
            {"quick_scan": True, "no_knowledge": True, "no_narrative": True, "model_profile": "economy"},
        )
        step("run started")
        state = wait(
            "run",
            lambda: call(base, "GET", f"/projects/{slug}/run"),
            lambda r: r["status"] != "running",
            3000,
        )
        step(f"run finished: {state['status']}")
        if state["status"] != "completed":
            raise SystemExit(f"FAIL run: {state}")
        runs = call(base, "GET", f"/projects/{slug}/runs")
        if not (runs and runs[0]["has_findings"] and runs[0]["reports"]):
            raise SystemExit(f"FAIL run left no findings or reports: {runs}")
        findings = call(base, "GET", f"/projects/{slug}/findings")
        step(f"findings={findings['total']} severities={findings['facets']['severity']} reports={runs[0]['reports']}")
        if findings["total"] < 1:
            raise SystemExit("FAIL the review found nothing in contracts that contain change of control terms")
        report = call_raw(base, f"/projects/{slug}/runs/{runs[0]['run_id']}/report/html")
        if b"<html" not in report[:2000].lower():
            raise SystemExit("FAIL the HTML report is not HTML")
        step(f"html report downloaded ({len(report)} bytes)")
        history = call(base, "GET", f"/projects/{slug}/history")
        step(f"history: {history if not isinstance(history, list) else len(history)}")

        step("asking one question")
        req = urllib.request.Request(
            f"{base}/api/projects/{slug}/chat",
            method="POST",
            data=json.dumps(
                {"question": "Which contracts can the customer terminate on a change of control?"}
            ).encode(),
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as res:
            stream = res.read().decode()
        if "event: done" not in stream:
            raise SystemExit(f"FAIL ask: {stream[-400:]}")
        step("answer received")
        step("OK")
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
        step(f"server log: {work / 'server.log'}")


def _up(base: str) -> bool:
    try:
        urllib.request.urlopen(
            urllib.request.Request(f"{base}/api/health", headers={"Authorization": f"Bearer {TOKEN}"}), timeout=2
        )
        return True
    except (urllib.error.URLError, ConnectionError, OSError):
        return False


if __name__ == "__main__":
    main()
