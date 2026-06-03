# Troubleshooting

## Exit Codes

| Code | Meaning | What to Do |
|------|---------|------------|
| 0 | Success | Nothing — the pipeline completed normally |
| 1 | Error (invalid config, missing input, unexpected failure) | Check the error message and fix the issue |
| 2 | Quality gate failed (pipeline halted because a quality check did not pass) | See [Blocking Gate Recovery](#blocking-gate-recovery) below |
| 130 | Interrupted by user (Ctrl+C) | Resume with `--resume-from <step>` |

## Common Errors

### API key not set

```
Error: ANTHROPIC_API_KEY environment variable is not set
```

Set the key in your environment or `.env` file:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
# Or create a .env file:
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
```

For AWS Bedrock, set `AWS_PROFILE` and `AWS_REGION` instead.

### Config file not found

```
Error: Config file not found: deal-config.json
```

Provide the correct path to your config file. Generate one with:

```bash
dd-agents init --data-room ./data_room
# Or with AI assistance:
dd-agents auto-config "Buyer" "Target" --data-room ./data_room
```

### Data room path not found

```
Error: Data room path does not exist: ./data_room
```

Check that the `data_room.path` in your config points to an existing directory.
Relative paths are resolved from the current working directory.

### Rate limit / API errors

```
Error: Rate limit exceeded (429)
```

The pipeline automatically retries rate-limited requests. If errors persist:
- Reduce `execution.batch_concurrency` in your config (default: 6)
- Use `--model-profile economy` for lower rate limits on cheaper models
- Check your API plan limits at [console.anthropic.com](https://console.anthropic.com/)

### Command not found

```
zsh: command not found: dd-agents
```

The package isn't installed in your active Python environment. Ensure:

```bash
pip install dd-agents[pdf]
# Verify:
dd-agents version
```

If using a virtual environment, activate it first.

### Memory errors on large data rooms

For data rooms with 500+ files, extraction may require significant memory.

- Reduce `execution.batch_concurrency` to 2-3
- Use incremental mode to process in stages: `--mode incremental`

### Permission errors

```
PermissionError: [Errno 13] Permission denied
```

Ensure you have read access to the data room and write access to the output
directory. The pipeline writes to `{data_room_path}/_dd/`.

## Blocking Gate Recovery

Five pipeline steps are blocking gates that halt on failure. Each has a specific
recovery path:

| Gate | Step | Common Cause | How to Fix |
|------|------|-------------|------------|
| Bulk Extraction | 5 | Corrupted or password-protected files | Remove or replace problem files, then `--resume-from 4` |
| Coverage Gate | 17 | Too few documents per subject | Add missing documents to the data room, then `--resume-from 6` |
| Numerical Audit | 30 | Contradictory financial figures | Review `audit.json` in the run directory, then `--resume-from 30` |
| Full QA Audit | 31 | Quality checks failed (missing citations) | Review `dod_results.json` for specifics, then `--resume-from 31` |
| Post-Generation | 34 | Incomplete report output | Check disk space, then `--resume-from 33` |

Resume after fixing the issue:

```bash
dd-agents run deal-config.json --resume-from <step>
```

## Environment Tuning

The variables most relevant when debugging a failed run:

- `ANTHROPIC_API_KEY` — Anthropic API key (or use `AWS_PROFILE` / `AWS_REGION` for Bedrock)
- `DD_AGENTS_CLI_PATH` — override the auto-detected Claude CLI path when the SDK can't find it

See [`.env.example`](https://github.com/zoharbabin/due-diligence-agents/blob/main/.env.example) for the full set of supported variables, and `grep DD_ src/dd_agents/utils/constants.py` for every `DD_` algorithm-tuning override and its current default.

## Getting Help

- [GitHub Issues](https://github.com/zoharbabin/due-diligence-agents/issues) — bug reports and feature requests
- [CLI Reference](cli-reference.md) — complete command and option reference
- [Running the Pipeline](running-pipeline.md) — detailed pipeline execution guide
