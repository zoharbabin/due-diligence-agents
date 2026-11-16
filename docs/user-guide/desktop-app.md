# Desktop App

A window for running reviews without the terminal. It runs the same pipeline as the CLI, on your machine.

## Install

CI builds the installers (`.github/workflows/desktop.yml`) and attaches them to the [GitHub Release](https://github.com/zoharbabin/due-diligence-agents/releases) of a version tag.

| System | File |
|--------|------|
| macOS (Apple Silicon) | `.dmg`. Drag the app to Applications |
| Windows (x64) | `-setup.exe`. Installs for your user, no admin rights |

On macOS you can also use Homebrew:

```bash
brew install --cask zoharbabin/due-diligence-agents/due-diligence-agents
```

Homebrew 7 asks you to trust a third-party tap first. Run the `brew trust` command it prints.

Release builds are signed. The macOS app is also notarized. The app checks for a newer signed version when it opens and offers to install it.

## First run

1. Open the app. It starts its own local service.
2. **Download the Claude engine.** One click. The app downloads Anthropic's `claude` command line tool and checks it against a fixed digest before use. It is stored under `~/.dd-projects/.cli/` (or `$DD_BASE_DIR/.cli/`). A `claude` already on your `PATH` is used instead.
3. **Paste your Anthropic API key.** The app tests it and stores it in your system keychain. For Bedrock, Vertex or a gateway, set the provider variables before you start the app. See [Model Providers](model-providers.md). To test, replace or remove the key later, open **Settings**.
4. **New project.** Pick the folder with your contracts and run the review.
5. **Ask questions.** Open **Ask** after a review. Answers come from the findings of the latest review and its documents. Each question calls the model and costs money. The page shows the session cost against its limit. **New conversation** ends the session. A newer review starts a new session.
6. **Optional: tune an agent.** In a project, open **Agents**. Pick one, start from a profile and save. The change applies to that project only and is checked before it is saved. Use **Preview prompt** to see exactly what the agent receives. The safety rules cannot be changed.
7. **Compare reviews.** After a second review, open **Compare** to see new, resolved and escalated findings. It uses the same engine as `dd-agents diff`.
8. **See what happened.** Open **History** for a list of reviews and questions, newest first, with findings, cost and entities. You can filter by type.
9. **Screen a name.** Open **Screening** and press **Update lists** to download the official US, UK and EU sanctions lists (needs the internet, stored on your computer). Then check one company or person. Results are possible matches for a person to review. No match is not a clearance. It uses the same engine as `dd-agents screening`. See [screening](screening.md).
10. **Let the model draft the setup.** In **Settings**, save the buyer and target names, then press **Suggest a setup**. The model reads your folder and file names and drafts the configuration. This costs money. The draft opens in the editor and is not saved until you press **Save**. It uses the same steps as `dd-agents auto-config`.

## Where things are

| What | Where |
|------|-------|
| Projects, findings, reports | `~/.dd-projects/` (or `$DD_BASE_DIR`). Same as the CLI |
| API key | OS keychain, service `com.zoharbabin.due-diligence-agents` |
| Claude engine | `~/.dd-projects/.cli/<version>/` |
| Service log (errors from the last launch, replaced at each launch) | macOS: `~/Library/Logs/com.zoharbabin.due-diligence-agents/service.log`. Windows: `%LOCALAPPDATA%\com.zoharbabin.due-diligence-agents\logs\service.log` |

## Security

- The service listens on `127.0.0.1` only. Every request needs a token that is made at each launch and never written to disk.
- Opening the app a second time shows the open window. It does not start a second service.
- The service stops when the app closes, with all of its child processes.
- Your documents stay on your machine. Only the text sent to the model provider you chose leaves it.

## Develop and build

See [`desktop/README.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/desktop/README.md). The API is described in [`dd-agents serve`](cli-reference.md#serve).
