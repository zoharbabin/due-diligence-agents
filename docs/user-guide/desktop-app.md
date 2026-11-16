# Desktop App

A window for running reviews without the terminal. It runs the same pipeline as the CLI, on your machine.

## Install

CI builds the installers (`.github/workflows/desktop.yml`) and attaches them to the [GitHub Release](https://github.com/zoharbabin/due-diligence-agents/releases) of a version tag.

| System | File |
|--------|------|
| macOS (Apple Silicon) | `.dmg`. Drag the app to Applications |
| Windows (x64) | `-setup.exe`. Installs for your user, no admin rights |

Release builds are signed. The macOS app is also notarized. The app checks for a newer signed version when it opens and offers to install it.

## First run

1. Open the app. It starts its own local service.
2. **Download the Claude engine.** One click. The app downloads Anthropic's `claude` command line tool and checks it against a fixed digest before use. It is stored under `~/.dd-projects/.cli/` (or `$DD_BASE_DIR/.cli/`). A `claude` already on your `PATH` is used instead.
3. **Paste your Anthropic API key.** The app tests it and stores it in your system keychain. For Bedrock, Vertex or a gateway, set the provider variables before you start the app. See [Model Providers](model-providers.md). To test, replace or remove the key later, open **Settings**.
4. **New project.** Pick the folder with your contracts and run the review.
5. **Optional: tune an agent.** In a project, open **Agents**. Pick one, start from a profile and save. The change applies to that project only and is checked before it is saved. Use **Preview prompt** to see exactly what the agent receives. The safety rules cannot be changed.

## Where things are

| What | Where |
|------|-------|
| Projects, findings, reports | `~/.dd-projects/` (or `$DD_BASE_DIR`). Same as the CLI |
| API key | OS keychain, service `com.zoharbabin.due-diligence-agents` |
| Claude engine | `~/.dd-projects/.cli/<version>/` |

## Security

- The service listens on `127.0.0.1` only. Every request needs a token that is made at each launch and never written to disk.
- The service stops when the app closes, with all of its child processes.
- Your documents stay on your machine. Only the text sent to the model provider you chose leaves it.

## Develop and build

See [`desktop/README.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/desktop/README.md). The API is described in [`dd-agents serve`](cli-reference.md#serve).
