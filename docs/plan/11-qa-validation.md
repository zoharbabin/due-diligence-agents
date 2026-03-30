# 11 -- QA and Validation (Audit Gates, 30 DoD Checks, Numerical Validation)

All validation is fail-closed. The Reporting Lead runs every QA check before finalizing the report. Any failure blocks the report. Numbers are validated by counting, not by LLM reasoning.

---

## 5-Layer Numerical Validation

Every number that appears in the final Excel report or any generated summary MUST have a provenance record. This prevents the class of errors where counts shift between report versions, totals do not add up, or numbers are carried forward from stale analysis.

### Numerical Manifest

Before Excel generation, build `{RUN_DIR}/numerical_manifest.json`. The manifest MUST use the exact schema below -- a `"numbers"` array of individually traceable entries. Do NOT produce a simplified summary object (e.g., `{"total_customers": 34, "total_findings": 601}`). Such flat summaries lack source traceability, derivation formulas, and cross-checks, and will fail Layer 1 validation.

```python
# src/dd_agents/validation/numerical_manifest.py

from pydantic import BaseModel, Field

class ManifestEntry(BaseModel):
    """One traceable number in the numerical manifest."""
    id: str                                  # N001, N002, etc.
    label: str                               # human-readable name
    value: int | float                       # the number
    source_file: str                         # path to source data
    derivation: str                          # how value was computed
    used_in: list[str]                       # where value appears in Excel/audit
    cross_check: str = ""                    # optional cross-check formula
    verified: bool = False                   # set True after Layer 2 passes

class NumericalManifest(BaseModel):
    manifest_version: str = "1.0"
    generated_at: str                        # ISO-8601
    numbers: list[ManifestEntry]

    def get(self, entry_id: str) -> ManifestEntry | None:
        for n in self.numbers:
            if n.id == entry_id:
                return n
        return None
```

### Minimum Required Entries (N001-N010)

These 10 entries are REQUIRED. Additional entries (N011+) are encouraged for any number that appears in the Excel report.

| ID | Label | Derivation | Used In |
|----|-------|-----------|---------|
| N001 | `total_customers` | `COUNT(rows)` in `customers.csv` | Summary sheet, `audit.json.summary.total_customers` |
| N002 | `total_files` | `wc -l files.txt` minus exempt files | Summary sheet, `audit.json.summary.total_files` |
| N003 | `total_findings` | `SUM(len(findings[]))` across all merged JSONs, EXCLUDING `domain_reviewed_no_issues` entries | Summary sheet total row, `audit.json.summary.total_findings` |
| N004 | `findings_p0` | `COUNT(findings where severity='P0')` across all merged JSONs | Summary sheet P0 column, Wolf_Pack sheet row count |
| N005 | `findings_p1` | `COUNT(findings where severity='P1')` across all merged JSONs | Summary sheet P1 column, Wolf_Pack sheet row count |
| N006 | `findings_p2` | `COUNT(findings where severity='P2')` across all merged JSONs | Summary sheet P2 column |
| N007 | `findings_p3` | `COUNT(findings where severity='P3' AND category != 'domain_reviewed_no_issues')` across all merged JSONs | Summary sheet P3 column |
| N008 | `clean_result_count` | `COUNT(findings where category='domain_reviewed_no_issues')` across all merged JSONs | `audit.json.summary.clean_result_count` |
| N009 | `total_gaps` | `COUNT(gap objects)` across all merged gap JSONs | Missing_Docs_Gaps sheet row count, `audit.json.summary.total_gaps` |
| N010 | `total_reference_files` | `len(files[])` in `reference_files.json` | Reference_Files_Index sheet row count |

### Counting Convention

`total_findings` (N003) EXCLUDES `domain_reviewed_no_issues` entries. These are P3 clean-result markers, not substantive findings. The `findings_by_severity` breakdown counts them under P3, but they are excluded from the headline `total_findings` number.

The invariant:
```
total_findings = P0 + P1 + P2 + (P3 minus clean_result_count)
total_findings = N004 + N005 + N006 + N007
N007 = (all P3 findings) - N008
```

### Manifest JSON Structure

```json
{
  "manifest_version": "1.0",
  "generated_at": "2025-02-18T14:30:00Z",
  "numbers": [
    {
      "id": "N001",
      "label": "total_customers",
      "value": 183,
      "source_file": "_dd/forensic-dd/inventory/customers.csv",
      "derivation": "COUNT(rows) in customers.csv",
      "used_in": ["Summary sheet", "audit.json.summary.total_customers"],
      "verified": true
    },
    {
      "id": "N002",
      "label": "total_files",
      "value": 431,
      "source_file": "_dd/forensic-dd/inventory/files.txt",
      "derivation": "wc -l files.txt minus exempt files",
      "used_in": ["Summary sheet", "audit.json.summary.total_files"],
      "verified": true
    },
    {
      "id": "N003",
      "label": "total_findings",
      "value": 412,
      "source_file": "{RUN_DIR}/findings/merged/*.json",
      "derivation": "SUM(len(findings[])) across all merged customer JSONs, EXCLUDING domain_reviewed_no_issues entries",
      "used_in": ["Summary sheet total row", "audit.json.summary.total_findings"],
      "cross_check": "P0(3) + P1(24) + P2(89) + P3_substantive(296) = 412. P3_total(308) - clean_result_count(12) = 296.",
      "verified": true
    },
    {
      "id": "N004",
      "label": "findings_p0",
      "value": 3,
      "source_file": "{RUN_DIR}/findings/merged/*.json",
      "derivation": "COUNT(findings where severity='P0') across all merged JSONs",
      "used_in": ["Summary sheet P0 column", "Wolf_Pack sheet row count"],
      "verified": true
    },
    {
      "id": "N005",
      "label": "findings_p1",
      "value": 24,
      "source_file": "{RUN_DIR}/findings/merged/*.json",
      "derivation": "COUNT(findings where severity='P1') across all merged JSONs",
      "used_in": ["Summary sheet P1 column", "Wolf_Pack sheet row count"],
      "verified": true
    },
    {
      "id": "N006",
      "label": "findings_p2",
      "value": 89,
      "source_file": "{RUN_DIR}/findings/merged/*.json",
      "derivation": "COUNT(findings where severity='P2') across all merged JSONs",
      "used_in": ["Summary sheet P2 column"],
      "verified": true
    },
    {
      "id": "N007",
      "label": "findings_p3",
      "value": 296,
      "source_file": "{RUN_DIR}/findings/merged/*.json",
      "derivation": "COUNT(findings where severity='P3' AND category != 'domain_reviewed_no_issues') across all merged JSONs",
      "used_in": ["Summary sheet P3 column"],
      "verified": true
    },
    {
      "id": "N008",
      "label": "clean_result_count",
      "value": 12,
      "source_file": "{RUN_DIR}/findings/merged/*.json",
      "derivation": "COUNT(findings where category='domain_reviewed_no_issues') across all merged JSONs",
      "used_in": ["audit.json.summary.clean_result_count"],
      "verified": true
    },
    {
      "id": "N009",
      "label": "total_gaps",
      "value": 67,
      "source_file": "{RUN_DIR}/findings/merged/gaps/*.json",
      "derivation": "COUNT(gap objects) across all merged gap JSONs",
      "used_in": ["Missing_Docs_Gaps sheet row count", "audit.json.summary.total_gaps"],
      "verified": true
    },
    {
      "id": "N010",
      "label": "total_reference_files",
      "value": 12,
      "source_file": "_dd/forensic-dd/inventory/reference_files.json",
      "derivation": "len(files[]) in reference_files.json",
      "used_in": ["Reference_Files_Index sheet row count"],
      "verified": true
    }
  ]
}
```

**Additional recommended entries** (N011+): `active_customers_count` (if incremental mode), per-severity gap counts, per-agent finding counts, `governance_resolved_pct`, extraction success rate. Any number used in the Excel Summary sheet or _Metadata sheet SHOULD have a manifest entry.

---

## 5 Validation Layers

### Layer 1 -- Source Traceability

Every number must trace to a specific file and derivation method. No "calculated in memory" or "from previous analysis" is acceptable. The source file must exist and be re-readable.

```python
# src/dd_agents/validation/layers.py

class Layer1Validator:
    """Source Traceability: every number maps to a file that exists."""

    def validate(self, manifest: NumericalManifest) -> LayerResult:
        failures = []
        for entry in manifest.numbers:
            # Check source_file exists (resolve {RUN_DIR} first)
            resolved_path = self._resolve_path(entry.source_file)
            if not self._source_exists(resolved_path):
                failures.append(
                    f"{entry.id} ({entry.label}): source_file "
                    f"'{entry.source_file}' does not exist"
                )
            if not entry.derivation:
                failures.append(
                    f"{entry.id} ({entry.label}): missing derivation"
                )
        return LayerResult(layer=1, passed=len(failures) == 0, failures=failures)
```

### Layer 2 -- Arithmetic Verification

All computed numbers must be re-derived from their source:

```python
class Layer2Validator:
    """Arithmetic Verification: re-derive every number from source."""

    def validate(self, manifest: NumericalManifest) -> LayerResult:
        failures = []
        for entry in manifest.numbers:
            rederived = self._rederive(entry)
            if rederived != entry.value:
                failures.append(
                    f"{entry.id} ({entry.label}): manifest={entry.value}, "
                    f"rederived={rederived}. Using rederived value."
                )
                entry.value = rederived  # fix in place
            entry.verified = True
        return LayerResult(layer=2, passed=len(failures) == 0, failures=failures)

    def _rederive(self, entry: ManifestEntry) -> int | float:
        """Re-execute the derivation against the source file."""
        match entry.id:
            case "N001":
                return self._count_csv_rows("customers.csv")
            case "N002":
                return self._count_file_lines("files.txt")
            case "N003":
                return self._count_findings(exclude_clean=True)
            case "N004":
                return self._count_findings_by_severity("P0")
            case "N005":
                return self._count_findings_by_severity("P1")
            case "N006":
                return self._count_findings_by_severity("P2")
            case "N007":
                return self._count_findings_by_severity("P3", exclude_clean=True)
            case "N008":
                return self._count_clean_results()
            case "N009":
                return self._count_gaps()
            case "N010":
                return self._count_reference_files()
            case _:
                # Layer 2 uses agent-specific rederivation logic, not a
                # generic function. Each agent type (Finance, Legal,
                # Commercial, ProductTech) has domain-specific rederivation
                # rules. For example, Finance rederives contract values by
                # summing line items; Legal rederives clause counts by
                # counting extracted clauses. The rederivation functions
                # are defined in validation/numerical_audit.py.
                return self._generic_rederive(entry)
```

### Layer 3 -- Cross-Source Consistency

Numbers that appear in multiple sources must agree. Cross-check against RAW source files, NOT against `audit.json` (which is produced AFTER the numerical audit at pipeline step 28).

**counts.json schema**: `{"total_customers": int, "total_files": int, "files_by_type": {ext: count}, "customers_by_file_count": {customer: count}, "extraction_stats": {"success": int, "failure": int, "skipped": int}}`. Generated during inventory (step 6) and stored in the FRESH tier at `_dd/forensic-dd/inventory/counts.json`.

```python
class Layer3Validator:
    """Cross-Source Consistency: numbers across files must agree."""

    CROSS_CHECKS = [
        # (description, source_a derivation, source_b derivation)
        (
            "customers.csv row count == counts.json.total_customers",
            lambda s: s.count_csv_rows("customers.csv"),
            lambda s: s.read_json("counts.json")["total_customers"],
        ),
        (
            "sum(files_by_group) == total_files in counts.json",
            lambda s: sum(s.read_json("counts.json")["files_by_group"].values()),
            lambda s: s.read_json("counts.json")["total_files"],
        ),
        (
            "gap JSONs priority counts == manifest gap totals",
            lambda s: s.count_gaps(),
            lambda s: s.manifest_value("N009"),
        ),
        (
            "sum(agent manifest files_processed) covers files.txt",
            lambda s: s.union_agent_files_processed(),
            lambda s: s.count_file_lines("files.txt"),
        ),
        (
            "sum(per-customer finding counts) == manifest total_findings",
            lambda s: s.count_findings(exclude_clean=True),
            lambda s: s.manifest_value("N003"),
        ),
    ]

    def validate(self, manifest: NumericalManifest) -> LayerResult:
        failures = []
        for desc, fn_a, fn_b in self.CROSS_CHECKS:
            val_a = fn_a(self)
            val_b = fn_b(self)
            if val_a != val_b:
                failures.append(f"{desc}: {val_a} != {val_b}")
        return LayerResult(layer=3, passed=len(failures) == 0, failures=failures)
```

### Layer 4 -- Cross-Format Parity (Post-Generation Only)

The same number appearing in Excel, JSON, and text summary must be identical. This layer runs AFTER Excel generation (pipeline step 31).

```python
class Layer4Validator:
    """Cross-Format Parity: Excel cells match manifest values."""

    # Spot-check at least 5 key cells
    SPOT_CHECKS = [
        ("Summary", "TOTALS", "Findings Count", "N003"),
        ("Summary", "TOTALS", "P0", "N004"),
        ("Summary", "TOTALS", "P1", "N005"),
        ("Summary", "TOTALS", "Gaps Count", "N009"),
        ("Reference_Files_Index", None, "row_count", "N010"),
    ]

    def validate(
        self, manifest: NumericalManifest, workbook_path: Path
    ) -> LayerResult:
        import openpyxl
        wb = openpyxl.load_workbook(workbook_path, data_only=True)
        failures = []

        for sheet_name, row_key, col_name, manifest_id in self.SPOT_CHECKS:
            if sheet_name not in wb.sheetnames:
                continue
            excel_val = self._read_cell(wb[sheet_name], row_key, col_name)
            manifest_val = manifest.get(manifest_id)
            if manifest_val and excel_val != manifest_val.value:
                failures.append(
                    f"{sheet_name}.{col_name}: Excel={excel_val}, "
                    f"manifest={manifest_val.value}"
                )

        # Also verify post-generation cross-source parity:
        # numerical_manifest.findings_by_severity == audit.json.summary.findings_by_severity
        # numerical_manifest.total_gaps == audit.json.summary.gaps_by_priority total
        # (audit.json exists at this point -- written at step 28, before Excel at step 30)

        return LayerResult(layer=4, passed=len(failures) == 0, failures=failures)
```

### Layer 5 -- Semantic Reasonableness

Flag numbers that are implausible:

```python
class Layer5Validator:
    """Semantic Reasonableness: flag implausible numbers."""

    def validate(
        self, manifest: NumericalManifest, prior_manifest: NumericalManifest | None
    ) -> LayerResult:
        failures = []

        n003 = manifest.get("N003")
        n004 = manifest.get("N004")

        # P0 count cannot exceed total findings
        if n003 and n004 and n004.value > n003.value:
            failures.append("P0 findings count > total findings count")

        # Customer count change >20% between runs without data room changes
        if prior_manifest:
            prior_n001 = prior_manifest.get("N001")
            curr_n001 = manifest.get("N001")
            if prior_n001 and curr_n001:
                pct_change = abs(curr_n001.value - prior_n001.value) / max(prior_n001.value, 1)
                if pct_change > 0.20:
                    failures.append(
                        f"Customer count changed by {pct_change:.0%} "
                        f"({prior_n001.value} -> {curr_n001.value})"
                    )

        # File count = 0 for a customer with a directory
        # (checked per-customer during merge)

        # Gap count decreased between runs
        if prior_manifest:
            prior_n009 = prior_manifest.get("N009")
            curr_n009 = manifest.get("N009")
            if prior_n009 and curr_n009 and curr_n009.value < prior_n009.value:
                failures.append(
                    f"Gap count decreased ({prior_n009.value} -> {curr_n009.value}). "
                    f"Gaps should only increase or stay same unless data added."
                )

        # ARR values negative or exceed configurable threshold
        # (checked per-customer during reconciliation)

        return LayerResult(layer=5, passed=len(failures) == 0, failures=failures)
```

---

## Audit Gate

The numerical audit is a BLOCKING gate between analysis completion and Excel generation. It runs at pipeline step 27.

When the numerical audit gate blocks, the Reporting Lead agent is responsible for resolution. The Reporting Lead receives the audit failure details and must either (1) correct the numerical inconsistency in the findings, or (2) add an explicit `numerical_override` annotation with justification. The pipeline re-runs the numerical audit after correction.

### Gate Protocol

```
1. Build {RUN_DIR}/numerical_manifest.json with all numbers to be used in Excel
2. Run Layers 1, 2, 3, and 5 (NOT Layer 4 -- it requires Excel to exist)
3. If ANY layer fails:
   a. Log failures to {RUN_DIR}/numerical_audit_failures.json
   b. Fix the source (re-derive, re-count, resolve discrepancy)
   c. Re-run validation (Layers 1, 2, 3, 5)
4. Only when Layers 1-3 and 5 all pass: proceed to Excel generation
5. After Excel generation (step 31): run Layer 4 (cross-format parity) as final check
   - If Layer 4 fails: fix generation script and re-generate Excel, then re-check
```

### Deterministic Validation Rule

Numbers MUST be validated using deterministic methods: counting rows, summing columns, re-running queries. Do NOT use LLM reasoning to validate LLM-generated numbers. This creates circular validation. When in doubt, re-count from source files.

**Circular validation mitigation**: Layer 2 rederivation uses structured extraction (regex + arithmetic) where possible, falling back to LLM rederivation only for complex calculations. When LLM rederivation is used, it operates on the source document directly (not on the agent's findings), providing an independent computation path.

```python
# src/dd_agents/validation/audit_gate.py

class NumericalAuditGate:
    """Blocking gate: must pass before Excel generation."""

    def __init__(self, run_dir: Path, prior_run_dir: Path | None = None):
        self.run_dir = run_dir
        self.prior_run_dir = prior_run_dir
        self.l1 = Layer1Validator(run_dir)
        self.l2 = Layer2Validator(run_dir)
        self.l3 = Layer3Validator(run_dir)
        self.l5 = Layer5Validator()

    async def validate_pre_generation(
        self, manifest: NumericalManifest
    ) -> AuditGateResult:
        """Run Layers 1-3, 5. BLOCKING -- must pass before Excel."""
        prior_manifest = self._load_prior_manifest()

        results = [
            self.l1.validate(manifest),
            self.l2.validate(manifest),
            self.l3.validate(manifest),
            self.l5.validate(manifest, prior_manifest),
        ]

        all_passed = all(r.passed for r in results)
        if not all_passed:
            # Log failures
            self._write_failures(results)
            # Attempt auto-fix (Layer 2 re-derives in place)
            # Re-run after fix
            results_retry = [
                self.l1.validate(manifest),
                self.l2.validate(manifest),
                self.l3.validate(manifest),
                self.l5.validate(manifest, prior_manifest),
            ]
            all_passed = all(r.passed for r in results_retry)

        return AuditGateResult(
            passed=all_passed,
            layer_results={r.layer: r for r in results},
        )

    async def validate_post_generation(
        self, manifest: NumericalManifest, workbook_path: Path
    ) -> AuditGateResult:
        """Run Layer 4 after Excel exists."""
        l4 = Layer4Validator()
        result = l4.validate(manifest, workbook_path)
        return AuditGateResult(
            passed=result.passed,
            layer_results={4: result},
        )
```

---

## QA Checks (Section 8)

The Reporting Lead runs ALL QA checks before finalizing. This is fail-closed -- any failure blocks the report.

### 8a. Agent Manifest Reconciliation

Verify all 4 agent manifests (`{RUN_DIR}/findings/{agent}/coverage_manifest.json`):
- `customers_assigned == customers_processed == TOTAL` customer count
- `files_assigned == files_processed`
- Every customer status: `"complete"`

```python
# src/dd_agents/validation/qa_checks.py

class ManifestReconciliationCheck:
    """QA 8a: Agent manifests match expected counts."""
    DOD_CHECKS = [3]

    def run(self, state: PipelineState) -> CheckResult:
        details = {}
        for agent in AGENT_NAMES:
            manifest_path = (
                state.run_dir / "findings" / agent / "coverage_manifest.json"
            )
            manifest = json.loads(manifest_path.read_text())
            assigned = manifest["customers_assigned"]
            processed = manifest["customers_processed"]
            match = assigned == processed == state.total_customers
            details[agent] = {
                "customers_assigned": assigned,
                "customers_processed": processed,
                "match": match,
            }
        all_match = all(d["match"] for d in details.values())
        return CheckResult(
            name="agent_manifest_reconciliation",
            passed=all_match,
            dod_checks=self.DOD_CHECKS,
            details=details,
        )
```

### 8b. File Coverage Audit

Every file in `files.txt` must appear in at least one agent manifest. Write `{RUN_DIR}/file_coverage.json`.

```python
class FileCoverageCheck:
    """QA 8b: Every file in files.txt covered by at least one agent."""
    DOD_CHECKS = [2, 10]

    def run(self, state: PipelineState) -> CheckResult:
        all_files = self._read_files_txt()
        file_to_agents: dict[str, list[str]] = {f: [] for f in all_files}

        for agent in AGENT_NAMES:
            manifest = self._read_manifest(agent)
            for f in manifest.get("files_processed", []):
                if f in file_to_agents:
                    file_to_agents[f].append(agent)

        uncovered = [f for f, agents in file_to_agents.items() if not agents]

        result = {
            "total_files": len(all_files),
            "covered_files": len(all_files) - len(uncovered),
            "uncovered_files": uncovered,
            "coverage_pct": (len(all_files) - len(uncovered)) / max(len(all_files), 1),
            "file_to_agents": file_to_agents,
            "reference_files_covered": self._check_reference_coverage(file_to_agents),
        }

        # Write file_coverage.json
        self._write_file_coverage(result)

        return CheckResult(
            name="file_coverage",
            passed=len(uncovered) == 0,
            dod_checks=self.DOD_CHECKS,
            details=result,
        )
```

### 8b2. Audit Log Verification

All 4 specialists AND the Reporting Lead MUST produce non-empty `audit_log.jsonl`. Missing audit logs are a QA failure.

For each audit log, spot-check at least 3 entries to verify required fields per `audit-entry.schema.json`: `ts` (ISO-8601), `agent`, `skill` (must be "forensic-dd"), `action`, `target`, `result`. Any entry missing `agent` or `skill` fields is a QA warning (the Reporting Lead should repair by adding the correct values based on the log's directory path).

```python
class AuditLogCheck:
    """QA 8b2: All agents have non-empty audit_log.jsonl."""
    DOD_CHECKS = [11]

    REQUIRED_LOGS = ["legal", "finance", "commercial", "producttech", "reporting_lead"]

    def run(self, state: PipelineState) -> CheckResult:
        agents_with_logs = []
        missing_logs = []

        for agent in self.REQUIRED_LOGS:
            log_path = state.run_dir / "audit" / agent / "audit_log.jsonl"
            if log_path.exists() and log_path.stat().st_size > 0:
                agents_with_logs.append(agent)
                self._spot_check_entries(log_path, agent)
            else:
                missing_logs.append(agent)

        return CheckResult(
            name="audit_logs",
            passed=len(missing_logs) == 0,
            dod_checks=self.DOD_CHECKS,
            details={
                "agents_with_logs": agents_with_logs,
                "missing_logs": missing_logs,
            },
        )
```

### 8c. Customer Coverage Audit

Every customer must have output from ALL 4 agents (Legal AND Finance AND Commercial AND ProductTech).

```python
class CustomerCoverageCheck:
    """QA 8c: Every customer has all 4 agent outputs."""
    DOD_CHECKS = [1]

    def run(self, state: PipelineState) -> CheckResult:
        missing_outputs = []
        for customer in state.customer_safe_names:
            for agent in AGENT_NAMES:
                path = state.run_dir / "findings" / agent / f"{customer}.json"
                if not path.exists():
                    missing_outputs.append({"customer": customer, "agent": agent})

        return CheckResult(
            name="customer_coverage",
            passed=len(missing_outputs) == 0,
            dod_checks=self.DOD_CHECKS,
            details={
                "total_customers": state.total_customers,
                "customers_with_all_4_agents": (
                    state.total_customers - len({m["customer"] for m in missing_outputs})
                ),
                "missing_outputs": missing_outputs,
            },
        )
```

### 8d. Governance Completeness Audit

Every `file_header.governed_by` must be one of: valid file path, `"SELF"`, or `"UNRESOLVED"` with a corresponding gap.

```python
class GovernanceCompletenessCheck:
    """QA 8d: Governance resolved for all files or explicit gaps."""
    DOD_CHECKS = [4]

    def run(self, state: PipelineState) -> CheckResult:
        unresolved_count = 0
        unresolved_with_gaps = 0

        for customer_file in (state.run_dir / "findings" / "merged").glob("*.json"):
            data = json.loads(customer_file.read_text())
            graph = data.get("governance_graph", {})
            for file_path, gov_info in graph.items():
                governed_by = gov_info.get("governed_by", "UNRESOLVED")
                if governed_by == "UNRESOLVED":
                    unresolved_count += 1
                    if self._has_corresponding_gap(customer_file.stem, file_path, state):
                        unresolved_with_gaps += 1

        return CheckResult(
            name="governance_completeness",
            passed=unresolved_count == unresolved_with_gaps,
            dod_checks=self.DOD_CHECKS,
            details={
                "unresolved_count": unresolved_count,
                "unresolved_with_gaps": unresolved_with_gaps,
            },
        )
```

### 8e. Citation Integrity Audit

Every finding must have `citation.filename` in `files.txt` and non-empty `exact_quote`.

Sample at least 10% of findings (minimum 20). Every sampled finding must have `citation.source_path` in `files.txt` and non-empty `exact_quote` for P0/P1.

```python
class CitationIntegrityCheck:
    """QA 8e: Citations point to real files with exact quotes."""
    DOD_CHECKS = [5]

    def run(self, state: PipelineState) -> CheckResult:
        all_files = set(self._read_files_txt())
        all_findings = self._load_all_merged_findings()
        sample_size = max(20, len(all_findings) // 10)
        sample = random.sample(all_findings, min(sample_size, len(all_findings)))

        failures = []
        for finding in sample:
            for cit in finding.get("citations", []):
                if cit.get("source_path") not in all_files:
                    failures.append({
                        "finding_id": finding.get("id"),
                        "citation_file": cit.get("source_path"),
                        "error": "source_path not in files.txt",
                    })
                if finding.get("severity") in ("P0", "P1"):
                    if not cit.get("exact_quote"):
                        failures.append({
                            "finding_id": finding.get("id"),
                            "error": "P0/P1 finding missing exact_quote",
                        })

        return CheckResult(
            name="citation_integrity",
            passed=len(failures) == 0,
            dod_checks=self.DOD_CHECKS,
            details={
                "total_findings_checked": len(sample),
                "failures": failures,
            },
        )
```

### 8f. Gap Completeness Audit

Run expected contract pack checklist for every customer. Log any missing items not already tracked.

```python
class GapCompletenessCheck:
    """QA 8f: Expected docs checked, ghost customers logged."""
    DOD_CHECKS = [6, 9]

    def run(self, state: PipelineState) -> CheckResult:
        referenced_missing = self._check_referenced_missing_docs(state)
        ghost_customers = self._check_ghost_customers(state)

        return CheckResult(
            name="gap_completeness",
            passed=referenced_missing and ghost_customers["count"] == ghost_customers["logged"],
            dod_checks=self.DOD_CHECKS,
            details={
                "referenced_missing_docs_logged": referenced_missing,
                "ghost_customers_logged": ghost_customers["count"] == ghost_customers["logged"],
                "ghost_count": ghost_customers["count"],
            },
        )
```

### 8g. Cross-Reference Completeness Audit

Every reference file processed by at least one agent. Ghost customer gaps (P0) logged. Phantom contract gaps logged. Data_Reconciliation sheet populated.

```python
class CrossReferenceCheck:
    """QA 8g: Reference files processed, reconciliation complete."""
    DOD_CHECKS = [7, 8]

    def run(self, state: PipelineState) -> CheckResult:
        cross_patterns = self._verify_cross_customer_patterns(state)
        reconciliation = self._verify_reconciliation_complete(state)
        phantom_count = self._count_phantom_gaps(state)

        return CheckResult(
            name="cross_reference_completeness",
            passed=cross_patterns and reconciliation,
            dod_checks=self.DOD_CHECKS,
            details={
                "cross_customer_patterns_checked": cross_patterns,
                "reconciliation_complete": reconciliation,
                "phantom_count": phantom_count,
            },
        )
```

### 8g2. Domain Coverage Validation

Every enabled analysis domain MUST have at least one finding OR a `domain_reviewed_no_issues` entry for every customer.

Coverage < 100% triggers a gap finding listing uncovered domains.

Domain coverage percentage = `domains_with_output / total_enabled_domains` per customer.

**Category validation** (warn-not-block): For each finding, verify its `category` appears in at least one enabled domain's `expected_finding_categories`. Log a warning (not a QA failure) for any finding using an unexpected category.

```python
class DomainCoverageCheck:
    """QA 8g2: Every domain has findings or clean-result per customer."""
    DOD_CHECKS = [12]

    def run(self, state: PipelineState) -> CheckResult:
        customers_missing = []
        category_warnings = []

        for customer in state.customer_safe_names:
            merged = self._load_merged(customer)
            findings = merged.get("findings", [])
            covered_domains = set()
            for f in findings:
                covered_domains.add(f.get("agent"))
                # Category validation (warn, not block)
                if f.get("category") not in self.expected_categories:
                    category_warnings.append(
                        f"{customer}: unexpected category '{f.get('category')}'"
                    )

            if covered_domains != self.enabled_domains:
                missing = self.enabled_domains - covered_domains
                customers_missing.append({
                    "customer": customer,
                    "missing_domains": list(missing),
                })

        coverage = 1.0 - (len(customers_missing) / max(len(state.customer_safe_names), 1))

        return CheckResult(
            name="domain_coverage",
            passed=len(customers_missing) == 0,
            dod_checks=self.DOD_CHECKS,
            details={
                "coverage_pct": coverage,
                "customers_with_missing_domains": customers_missing,
                "category_warnings": category_warnings,
            },
        )
```

### 8h. Consolidated Audit Output

Write `{RUN_DIR}/audit.json`. This is the master audit record. Each check maps to one or more DoD items from section 9. Any missing check means `audit_passed: false`.

```json
{
  "audit_passed": true,
  "timestamp": "ISO-8601",
  "run_id": "20250218_143000",
  "checks": {
    "agent_manifest_reconciliation": {
      "passed": true,
      "dod_checks": [3],
      "details": {
        "legal": {"customers_assigned": 34, "customers_processed": 34, "match": true},
        "finance": {"customers_assigned": 34, "customers_processed": 34, "match": true},
        "commercial": {"customers_assigned": 34, "customers_processed": 34, "match": true},
        "producttech": {"customers_assigned": 34, "customers_processed": 34, "match": true}
      }
    },
    "customer_coverage": {
      "passed": true,
      "dod_checks": [1],
      "total_customers": 34,
      "customers_with_all_4_agents": 34,
      "missing_outputs": [],
      "_rule": "EVERY customer MUST have a {customer_safe_name}.json from ALL 4 agents. passed=false if ANY customer lacks ANY agent output."
    },
    "file_coverage": {
      "passed": true,
      "dod_checks": [2, 10],
      "total_files": 431,
      "covered_files": 431,
      "uncovered_files": [],
      "reference_files_covered": true
    },
    "governance_completeness": {
      "passed": true,
      "dod_checks": [4],
      "unresolved_count": 0,
      "unresolved_with_gaps": 0
    },
    "citation_integrity": {
      "passed": true,
      "dod_checks": [5],
      "total_findings_checked": 50,
      "failures": [],
      "_rule": "Sample at least 10% of findings (minimum 20). Every sampled finding must have citation.source_path in files.txt and non-empty exact_quote for P0/P1."
    },
    "gap_completeness": {
      "passed": true,
      "dod_checks": [6, 9],
      "referenced_missing_docs_logged": true,
      "ghost_customers_logged": true,
      "ghost_count": 0
    },
    "cross_reference_completeness": {
      "passed": true,
      "dod_checks": [7, 8],
      "cross_customer_patterns_checked": true,
      "reconciliation_complete": true,
      "phantom_count": 0
    },
    "domain_coverage": {
      "passed": true,
      "dod_checks": [12],
      "coverage_pct": 1.0,
      "customers_with_missing_domains": [],
      "category_warnings": []
    },
    "audit_logs": {
      "passed": true,
      "dod_checks": [11],
      "agents_with_logs": ["legal", "finance", "commercial", "producttech", "reporting_lead"],
      "missing_logs": [],
      "_rule": "ALL 4 specialist agents AND reporting_lead MUST have non-empty audit_log.jsonl."
    },
    "extraction_quality": {
      "passed": true,
      "dod_checks": [19],
      "total_non_plaintext": 400,
      "entries_in_extraction_quality": 400,
      "unreadable_without_gap": 0
    },
    "merge_dedup": {
      "passed": true,
      "dod_checks": [13],
      "merged_customer_count": 34,
      "total_merged_findings": 412
    },
    "report_sheets": {
      "passed": true,
      "dod_checks": [14],
      "required_sheets_present": true,
      "missing_sheets": []
    },
    "entity_resolution": {
      "passed": true,
      "dod_checks": [16],
      "unmatched_with_aliases": 0
    },
    "numerical_manifest": {
      "passed": true,
      "dod_checks": [17],
      "all_layers_validated": true
    },
    "contract_date_reconciliation": {
      "passed": true,
      "dod_checks": [18],
      "applicable": true,
      "reconciliation_file_exists": true,
      "_rule": "Only checked if deal-config.json has source_of_truth.customer_database. Set applicable=false and passed=true if not applicable."
    },
    "report_consistency": {
      "passed": true,
      "dod_checks": [28, 29, 30],
      "schema_driven_generation": true,
      "schema_validation_passed": true,
      "report_diff_populated": true,
      "_rule": "Check 28: Excel generated from report_schema.json. Check 29: post-generation schema validation passed. Check 30: report_diff.json exists if prior run and diff enabled (set to true if no prior run)."
    }
  },
  "summary": {
    "total_customers": 34,
    "total_files": 431,
    "total_findings": 412,
    "total_gaps": 67,
    "findings_by_severity": {"P0": 3, "P1": 24, "P2": 89, "P3": 296},
    "gaps_by_priority": {"P0": 5, "P1": 18, "P2": 32, "P3": 12},
    "clean_result_count": 12,
    "agents_producing_gaps": ["legal", "finance", "commercial", "producttech"]
  }
}
```

**Conditional checks** added to `audit.json` only when applicable:

| Check Section | DoD Items | Condition |
|--------------|-----------|-----------|
| Judge quality checks | 20, 21, 22, 23 | `judge.enabled` in deal-config |
| Incremental mode checks | 24, 25, 26, 27 | `execution_mode == "incremental"` |
| Contract date reconciliation | 18 | `source_of_truth.customer_database` exists (otherwise `applicable: false`) |
| Report diff | 30 | Set to `true` if no prior run exists |

All other checks (DoD 1-17, 19, 28-29) are ALWAYS required.

### 8i. Numerical Audit

Run the 5-layer numerical validation framework (see above). Build `{RUN_DIR}/numerical_manifest.json`. This is a BLOCKING gate -- must pass Layers 1-3, 5 before generating Excel. Run Layer 4 after generation.

### 8i2. Extraction Quality Completeness

Verify `_dd/forensic-dd/index/extraction_quality.json` has an entry for every non-plaintext file in `files.txt`. Any file without an extraction entry is a QA warning (may indicate silently skipped extraction). Cross-check: every file in `extraction_quality.json` with `method: "failed"` must have a corresponding gap with `gap_type: "Unreadable"`.

```python
class ExtractionQualityCheck:
    """QA 8i2: Extraction quality log covers all non-plaintext files."""
    DOD_CHECKS = [19]

    def run(self, state: PipelineState) -> CheckResult:
        eq_data = json.loads(self.extraction_quality_path.read_text())
        eq_files = {e["file_path"] for e in eq_data}
        non_plaintext = self._get_non_plaintext_files()

        missing_entries = non_plaintext - eq_files
        failed_entries = [
            e for e in eq_data if e.get("method") == "failed"
        ]
        unreadable_without_gap = 0
        for entry in failed_entries:
            if not self._has_unreadable_gap(entry["file_path"], state):
                unreadable_without_gap += 1

        return CheckResult(
            name="extraction_quality",
            passed=unreadable_without_gap == 0,
            dod_checks=self.DOD_CHECKS,
            details={
                "total_non_plaintext": len(non_plaintext),
                "entries_in_extraction_quality": len(eq_files),
                "unreadable_without_gap": unreadable_without_gap,
            },
        )
```

### 8j. Judge Quality Gate (Conditional: judge.enabled)

Verify `{RUN_DIR}/judge/quality_scores.json` exists and contains `spot_checks` array and `contradictions` array (embedded in the single file per `quality-score.schema.json`). Check `overall_quality >= threshold`. Verify all contradictions resolved. Include Judge scores in Summary and Wolf_Pack sheets.

```python
class JudgeQualityCheck:
    """QA 8j: Judge quality scores meet threshold."""
    DOD_CHECKS = [20, 21, 22, 23]
    CONDITIONAL = True  # only if judge.enabled

    def run(self, state: PipelineState) -> CheckResult:
        path = state.run_dir / "judge" / "quality_scores.json"
        if not path.exists():
            return CheckResult(name="judge_quality", passed=False,
                             dod_checks=self.DOD_CHECKS,
                             details={"error": "quality_scores.json missing"})

        qs = json.loads(path.read_text())

        # DoD 20: quality_scores.json exists with valid scores for all 4 agents
        agents_scored = set(qs.get("agent_scores", {}).keys())
        all_agents_scored = agents_scored == {"legal", "finance", "commercial", "producttech"}

        # DoD 21: All P0 findings spot-checked (100% sampling)
        spot_checks = qs.get("spot_checks", [])
        p0_checks = [sc for sc in spot_checks if sc.get("severity") == "P0"]

        # DoD 22: All agents >= threshold OR quality caveats attached
        threshold = state.deal_config.get("judge", {}).get("threshold", 70)
        below_threshold = []
        for agent, scores in qs.get("agent_scores", {}).items():
            if scores.get("overall", 0) < threshold:
                below_threshold.append(agent)

        # DoD 23: All contradictions resolved
        contradictions = qs.get("contradictions", [])
        unresolved = [c for c in contradictions if not c.get("resolved")]

        return CheckResult(
            name="judge_quality",
            passed=(all_agents_scored and len(unresolved) == 0),
            dod_checks=self.DOD_CHECKS,
            details={
                "all_agents_scored": all_agents_scored,
                "p0_spot_checks": len(p0_checks),
                "below_threshold": below_threshold,
                "unresolved_contradictions": len(unresolved),
            },
        )
```

### 8k. Report Schema Validation

After Excel generation, validate output against `report_schema.json`: all sheets exist, columns match, sort orders correct, conditional formatting applied.

```python
class ReportSchemaCheck:
    """QA 8k: Excel output matches report_schema.json."""
    DOD_CHECKS = [28, 29, 30]

    def run(self, state: PipelineState, schema: ReportSchema) -> CheckResult:
        # Check 28: Excel generated from report_schema.json
        schema_driven = self._verify_build_script_loads_schema(state)

        # Check 29: Post-generation schema validation
        validator = SchemaValidator(schema, self._get_excel_path(state))
        validation = validator.validate(self._get_activation_context(state))

        # Check 30: Report diff
        diff_populated = True
        if state.prior_run_id:
            diff_path = state.run_dir / "report_diff.json"
            diff_populated = diff_path.exists()
        # If no prior run, set to true

        return CheckResult(
            name="report_consistency",
            passed=(schema_driven and validation.passed and diff_populated),
            dod_checks=self.DOD_CHECKS,
            details={
                "schema_driven_generation": schema_driven,
                "schema_validation_passed": validation.passed,
                "report_diff_populated": diff_populated,
            },
        )
```

---

## 30 Definition of Done Checks

Every applicable check must pass before the report is finalized. If ANY fails, DO NOT FINALIZE. Output audit failures and specific missing items.

### Core Analysis (1-12) -- ALWAYS REQUIRED

| # | Check | Description | QA Section | audit.json Key |
|---|-------|-------------|-----------|----------------|
| 1 | Customer outputs complete | `customers_missing_outputs[]` is empty -- every customer has output from ALL 4 agents | 8c | `customer_coverage` |
| 2 | File coverage complete | `files_uncovered[]` is empty (includes both customer files AND reference files) | 8b | `file_coverage` |
| 3 | Agent manifests valid | All 4 agent manifests show `customers_assigned == customers_processed == TOTAL` count (or scoped count if incremental) | 8a | `agent_manifest_reconciliation` |
| 4 | Governance resolved | Every customer has governance resolved for all files OR explicit gaps | 8d | `governance_completeness` |
| 5 | Citations valid | Every finding has a citation with non-empty `exact_quote` pointing to a real file | 8e | `citation_integrity` |
| 6 | Gaps tracked | Every referenced-but-missing document is logged as a gap | 8f | `gap_completeness` |
| 7 | Cross-customer patterns | Cross-customer pattern check has run | 8g | `cross_reference_completeness` |
| 8 | Cross-reference reconciliation | Completed for ALL customers with reference data | 8g | `cross_reference_completeness` |
| 9 | Ghost customers | All ghost customers logged as P0 gaps | 8f | `gap_completeness` |
| 10 | Reference files processed | All reference files processed by at least one agent | 8b | `file_coverage` |
| 11 | Audit logs exist | All 4 specialist audit logs AND Reporting Lead audit log exist at `{RUN_DIR}/audit/{agent}/audit_log.jsonl` | 8b2 | `audit_logs` |
| 12 | Domain coverage | Every enabled analysis domain has findings OR `domain_reviewed_no_issues` entry for every customer | 8g2 | `domain_coverage` |

### Reporting and Audit (13-19) -- ALWAYS REQUIRED

| # | Check | Description | QA Section | audit.json Key |
|---|-------|-------------|-----------|----------------|
| 13 | Merge/dedup complete | Reporting Lead merged and deduplicated findings from all 4 agents per customer | 8h | `merge_dedup` |
| 14 | Excel sheets populated | Excel contains ALL required sheets (Summary, Wolf_Pack, Missing_Docs_Gaps, Data_Reconciliation, etc.) | 8h | `report_sheets` |
| 15 | audit.json valid | `{RUN_DIR}/audit.json` exists with `audit_passed: true` | 8h | (self-referential) |
| 16 | Entity resolution log | Entity resolution log exists with zero unmatched entities that have aliases available | 8h | `entity_resolution` |
| 17 | Numerical manifest valid | Numerical manifest exists with all layers validated | 8i | `numerical_manifest` |
| 18 | Contract dates reconciled | If `customer_database` exists: contract date reconciliation completed | 8h | `contract_date_reconciliation` |
| 19 | Extraction quality | Extraction quality log exists, covers all non-plaintext files, and zero unreadable files unless logged as gaps | 8i2 | `extraction_quality` |

### Judge Quality (20-23) -- CONDITIONAL: only if judge.enabled

| # | Check | Description | QA Section | audit.json Key |
|---|-------|-------------|-----------|----------------|
| 20 | Quality scores exist | `{RUN_DIR}/judge/quality_scores.json` exists with valid scores for all 4 agents | 8j | `judge_quality` |
| 21 | P0 spot-checked | All P0 findings spot-checked by Judge (100% sampling) | 8j | `judge_quality` |
| 22 | Threshold met or caveats | All agents >= threshold OR quality caveats attached | 8j | `judge_quality` |
| 23 | Contradictions resolved | All contradictions resolved -- zero unresolved | 8j | `judge_quality` |

### Incremental Mode (24-27) -- CONDITIONAL: only if execution_mode="incremental"

| # | Check | Description | QA Section | audit.json Key |
|---|-------|-------------|-----------|----------------|
| 24 | Classification exists | `{RUN_DIR}/classification.json` exists with valid status for every customer | -- | `incremental_classification` |
| 25 | Carried-forward metadata | Every carried-forward finding has `_carried_forward: true` and `_original_run_id` | -- | `incremental_carry_forward` |
| 26 | Run history updated | `_dd/run_history.json` updated with current run | -- | `incremental_run_history` |
| 27 | Prior run archived | Prior run data archived intact, `{RUN_DIR}/metadata.json` finalized with `file_checksums` | -- | `incremental_archive` |

### Report Consistency (28-30) -- ALWAYS REQUIRED

| # | Check | Description | QA Section | audit.json Key |
|---|-------|-------------|-----------|----------------|
| 28 | Schema-driven generation | Excel generated from `report_schema.json` via `build_report.py` | 8k | `report_consistency` |
| 29 | Schema validation passed | All sheets, columns, sort orders match | 8k | `report_consistency` |
| 30 | Report diff | If prior run exists and diff enabled: `report_diff.json` exists and Run_Diff sheet populated (set to `true` if no prior run) | 8k | `report_consistency` |

---

## QA Runner

The QA runner executes all checks and produces `audit.json`.

```python
# src/dd_agents/validation/qa_runner.py

class QARunner:
    """Runs all QA checks and writes audit.json."""

    def __init__(self, run_dir: Path, deal_config: dict, state: PipelineState):
        self.run_dir = run_dir
        self.deal_config = deal_config
        self.state = state

    ALWAYS_CHECKS = [
        ManifestReconciliationCheck,       # 8a -> DoD 3
        FileCoverageCheck,                  # 8b -> DoD 2, 10
        AuditLogCheck,                      # 8b2 -> DoD 11
        CustomerCoverageCheck,              # 8c -> DoD 1
        GovernanceCompletenessCheck,        # 8d -> DoD 4
        CitationIntegrityCheck,             # 8e -> DoD 5
        GapCompletenessCheck,               # 8f -> DoD 6, 9
        CrossReferenceCheck,                # 8g -> DoD 7, 8
        DomainCoverageCheck,                # 8g2 -> DoD 12
        ExtractionQualityCheck,             # 8i2 -> DoD 19
        MergeDedupCheck,                    # -> DoD 13
        ReportSheetsCheck,                  # -> DoD 14
        EntityResolutionCheck,              # -> DoD 16
        NumericalManifestCheck,             # 8i -> DoD 17
        ReportSchemaCheck,                  # 8k -> DoD 28, 29, 30
    ]

    CONDITIONAL_CHECKS = {
        "judge": [JudgeQualityCheck],                          # DoD 20-23
        "incremental": [IncrementalClassificationCheck,        # DoD 24
                        IncrementalCarryForwardCheck,           # DoD 25
                        IncrementalRunHistoryCheck,             # DoD 26
                        IncrementalArchiveCheck],               # DoD 27
        "contract_dates": [ContractDateReconciliationCheck],    # DoD 18
    }

    async def run_all_checks(self) -> AuditResult:
        checks = {}

        # Always-required checks
        for check_cls in self.ALWAYS_CHECKS:
            check = check_cls(self.run_dir, self.state)
            result = check.run(self.state)
            checks[result.name] = result.to_dict()

        # Conditional: Judge (DoD 20-23)
        if self.deal_config.get("judge", {}).get("enabled", False):
            for check_cls in self.CONDITIONAL_CHECKS["judge"]:
                check = check_cls(self.run_dir, self.state)
                result = check.run(self.state)
                checks[result.name] = result.to_dict()

        # Conditional: Incremental (DoD 24-27)
        if self.state.execution_mode == "incremental":
            for check_cls in self.CONDITIONAL_CHECKS["incremental"]:
                check = check_cls(self.run_dir, self.state)
                result = check.run(self.state)
                checks[result.name] = result.to_dict()

        # Conditional: Contract dates (DoD 18)
        has_db = bool(
            self.deal_config
            .get("source_of_truth", {})
            .get("customer_database")
        )
        if has_db:
            for check_cls in self.CONDITIONAL_CHECKS["contract_dates"]:
                check = check_cls(self.run_dir, self.state)
                result = check.run(self.state)
                checks[result.name] = result.to_dict()
        else:
            checks["contract_date_reconciliation"] = {
                "passed": True,
                "dod_checks": [18],
                "applicable": False,
                "reconciliation_file_exists": False,
                "_rule": "Not applicable -- no source_of_truth.customer_database in deal-config.",
            }

        # Build audit.json
        audit_passed = all(
            c.get("passed", False) for c in checks.values()
        )

        audit = {
            "audit_passed": audit_passed,
            "timestamp": datetime.utcnow().isoformat(),
            "run_id": self.state.run_id,
            "checks": checks,
            "summary": self._build_summary(),
        }

        audit_path = self.run_dir / "audit.json"
        audit_path.write_text(json.dumps(audit, indent=2))

        return AuditResult(audit_passed=audit_passed, checks=checks)

    def _build_summary(self) -> dict:
        """Build summary section from numerical manifest."""
        manifest = self._load_manifest()
        return {
            "total_customers": manifest.get("N001").value,
            "total_files": manifest.get("N002").value,
            "total_findings": manifest.get("N003").value,
            "total_gaps": manifest.get("N009").value,
            "findings_by_severity": {
                "P0": manifest.get("N004").value,
                "P1": manifest.get("N005").value,
                "P2": manifest.get("N006").value,
                "P3": manifest.get("N007").value,
            },
            "gaps_by_priority": self._count_gaps_by_priority(),
            "clean_result_count": manifest.get("N008").value,
            "agents_producing_gaps": self._agents_with_gaps(),
        }
```

---

## DoD-to-audit.json Traceability Matrix

Every DoD check maps to an `audit.json` check section. This ensures the audit output is the complete record of compliance.

| DoD # | audit.json Check Key | Conditional? |
|-------|---------------------|-------------|
| 1 | `customer_coverage` | No |
| 2 | `file_coverage` | No |
| 3 | `agent_manifest_reconciliation` | No |
| 4 | `governance_completeness` | No |
| 5 | `citation_integrity` | No |
| 6 | `gap_completeness` | No |
| 7 | `cross_reference_completeness` | No |
| 8 | `cross_reference_completeness` | No |
| 9 | `gap_completeness` | No |
| 10 | `file_coverage` | No |
| 11 | `audit_logs` | No |
| 12 | `domain_coverage` | No |
| 13 | `merge_dedup` | No |
| 14 | `report_sheets` | No |
| 15 | (self-referential: `audit.json` existence) | No |
| 16 | `entity_resolution` | No |
| 17 | `numerical_manifest` | No |
| 18 | `contract_date_reconciliation` | Yes: `source_of_truth.customer_database` |
| 19 | `extraction_quality` | No |
| 20 | `judge_quality` | Yes: `judge.enabled` |
| 21 | `judge_quality` | Yes: `judge.enabled` |
| 22 | `judge_quality` | Yes: `judge.enabled` |
| 23 | `judge_quality` | Yes: `judge.enabled` |
| 24 | `incremental_classification` | Yes: `execution_mode == "incremental"` |
| 25 | `incremental_carry_forward` | Yes: `execution_mode == "incremental"` |
| 26 | `incremental_run_history` | Yes: `execution_mode == "incremental"` |
| 27 | `incremental_archive` | Yes: `execution_mode == "incremental"` |
| 28 | `report_consistency` | No |
| 29 | `report_consistency` | No |
| 30 | `report_consistency` | No (set to `true` if no prior run) |

---

## Validation Pipeline Integration

The validation checks integrate into the main pipeline at specific steps:

| Pipeline Step | Validation Action | Blocking? |
|---------------|------------------|-----------|
| 17 | Customer coverage gate (per-agent file count) | Yes |
| 26 | Build numerical manifest | -- |
| 27 | Numerical audit Layers 1-3, 5 | Yes |
| 28 | Full QA audit (all 8a-8k checks) | Yes |
| 30 | Excel generation | -- |
| 31 | Post-generation validation: schema check + Layer 4 | Yes |

```python
# src/dd_agents/validation/__init__.py

from .numerical_manifest import NumericalManifest, ManifestEntry, NumericalManifestBuilder
from .layers import (
    Layer1Validator,
    Layer2Validator,
    Layer3Validator,
    Layer4Validator,
    Layer5Validator,
)
from .audit_gate import NumericalAuditGate
from .qa_runner import QARunner
from .qa_checks import (
    ManifestReconciliationCheck,
    FileCoverageCheck,
    AuditLogCheck,
    CustomerCoverageCheck,
    GovernanceCompletenessCheck,
    CitationIntegrityCheck,
    GapCompletenessCheck,
    CrossReferenceCheck,
    DomainCoverageCheck,
    ExtractionQualityCheck,
    JudgeQualityCheck,
    ReportSchemaCheck,
)
```
