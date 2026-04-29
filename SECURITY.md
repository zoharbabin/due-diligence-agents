# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT open a public GitHub issue** for security vulnerabilities.
2. Email the maintainers with details of the vulnerability.
3. Include steps to reproduce, potential impact, and any suggested fixes.

We will acknowledge receipt within 48 hours and aim to provide a fix or mitigation within 7 days for critical issues.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x     | Yes       |
| < 1.0   | No        |

## Security Considerations

This tool processes potentially sensitive M&A documents. Key security measures:

- **Local execution** — all analysis runs on your machine. No data is sent to third parties except the configured LLM API (Anthropic or AWS Bedrock).
- **No telemetry** — the tool does not phone home or collect usage data.
- **Bash guard** — shell command execution is restricted to prevent injection.
- **SSRF prevention** — external URL fetching is limited to document-referenced URLs with legal keyword patterns.
- **No persistent credentials** — API keys are read from environment variables or `.env` files, never stored in output artifacts.

## Data Handling

- Extracted text and findings are stored locally in the `_dd/` directory.
- No data room content is included in source code, tests, or commits.
- The tool does not modify files in your data room — it only reads them.
