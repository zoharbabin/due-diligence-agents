"""Stand-in for ``dd-agents run`` used by the UI end-to-end tests.

It writes the same files the real pipeline writes (events.jsonl, merged findings,
the ``latest`` link, an HTML report) without calling any LLM. A data room whose
folder name contains "slow" waits long enough for the cancel test.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from dd_agents.orchestrator.events import RunEventLog

STEPS = ["05_bulk_extraction", "12_specialist_agents", "28_merge", "35_report"]
FINDINGS = [
    ("f1", "P0", "change_of_control", "Change of control needs consent", "legal"),
    ("f2", "P1", "termination", "Termination for convenience", "legal"),
    ("f3", "P2", "pricing", "Price increase clause", "finance"),
    ("f4", "P3", "other", "Minor notice period", "commercial"),
]


def main() -> int:
    room = Path.cwd()
    pause = 30.0 if "slow" in room.name else 0.3
    base = room / "_dd" / "forensic-dd"
    log = RunEventLog(base / "events.jsonl")
    log.reset()
    runs_dir = base / "runs"
    second = runs_dir.is_dir() and any(p.is_dir() and not p.is_symlink() for p in runs_dir.iterdir())
    rid = "20260102_000000" if second else "20260101_000000"
    log.emit("run_started", run_id=rid, total_steps=len(STEPS))
    for n, step in enumerate(STEPS, 1):
        log.emit("step_started", run_id=rid, step=step, step_number=n)
        if step.startswith("12"):
            log.emit("agent_started", run_id=rid, step=step, step_number=n, agent="legal", total_subjects=2)
            time.sleep(pause)
            log.emit("agent_progress", run_id=rid, agent="legal", subjects_done=1, total_subjects=2)
            time.sleep(pause)
            log.emit(
                "agent_completed", run_id=rid, agent="legal", ok=True, subjects_done=2, total_subjects=2, cost_usd=0.4
            )
        else:
            time.sleep(pause)
        log.emit(
            "step_completed",
            run_id=rid,
            step=step,
            step_number=n,
            completed_steps=n,
            total_steps=len(STEPS),
            total_cost_usd=0.4 * n,
        )
    run_dir = base / "runs" / rid
    merged = run_dir / "findings" / "merged"
    merged.mkdir(parents=True)
    findings = FINDINGS
    if second:
        # A later review: one finding resolved, one escalated, one new.
        findings = [
            ("f1", "P0", "change_of_control", "Change of control needs consent", "legal"),
            ("f2", "P0", "termination", "Termination for convenience", "legal"),
            ("f4", "P3", "other", "Minor notice period", "commercial"),
            ("f5", "P1", "data_privacy", "Missing data processing terms", "legal"),
        ]
    items = [
        {
            "id": i,
            "severity": sev,
            "category": cat,
            "title": title,
            "description": f"{title}. See the cited clause.",
            "citations": [
                {"source_path": "contracts/msa.pdf", "exact_quote": "Either party may terminate.", "page": "3"}
            ],
            "confidence": "high",
            "agent": agent,
            "analysis_unit": "Subject A",
        }
        for i, sev, cat, title, agent in findings
    ]
    (merged / "subject_a.json").write_text(
        json.dumps({"subject": "Subject A", "subject_safe_name": "subject_a", "findings": items})
    )
    (run_dir / "report").mkdir()
    (run_dir / "report" / "dd_report.html").write_text("<html><body><h1 id='r'>Fake report</h1></body></html>")
    latest = base / "runs" / "latest"
    latest.unlink(missing_ok=True)
    latest.symlink_to(rid)
    log.emit("run_completed", run_id=rid, exit_code=0, dod_passed=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
