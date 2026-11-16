# Release Process

This repo releases by pushing a `v*` tag. `.github/workflows/release.yml` does the rest:
quality gate → PyPI (OIDC) → Docker (GHCR + Docker Hub) → Homebrew formula bump → GitHub Release.

## Prerequisites

- All work lands on `main` via a squash-merged PR (see [CONTRIBUTING.md](CONTRIBUTING.md#pull-request-process)).
- `gh` CLI authenticated with repo write access.
- Local `main` up to date: `git checkout main && git pull --ff-only`.

## Steps

1. **Bump the version** in `pyproject.toml` (`version = "X.Y.Z"`), commit on the feature/release branch
   (not directly on `main`), push, and let CI go green on the PR.
   ```bash
   git commit -am "chore(release): bump version to X.Y.Z"
   git push
   ```
2. **Squash-merge the PR.**
   ```bash
   gh pr merge <N> --squash --delete-branch=false
   ```
   `--delete-branch=false` is deliberate — this repo doesn't auto-delete release branches (see
   `release/v1.17.0`, `discoverability-dx` still on the remote after their releases). Delete manually
   later if you want the cleanup; don't make it part of the release itself.
3. **Sync local `main`.**
   ```bash
   git checkout main && git pull --ff-only
   ```
4. **Tag and push** — this is what triggers `release.yml`.
   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z — <one-line summary>"
   git push origin vX.Y.Z
   ```
5. **Watch the workflow to completion** — don't consider the release done until every job is green.
   ```bash
   gh run watch $(gh run list --workflow=release.yml --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status
   ```
6. **Write real release notes.** The workflow's auto-generated body is a flat `git log --no-merges`
   dump since the last tag — accurate but not useful to a reader. Replace it with a structured,
   per-feature summary (what shipped, why, quality signal), keeping the Install/Docker/Full-Changelog
   footer the workflow already generated:
   ```bash
   gh release edit vX.Y.Z --notes-file /tmp/notes.md
   ```
7. **Re-sync local `main` again.** The release workflow's `update-formula` job pushes a
   "Update Homebrew formula to X.Y.Z" commit back to `main` *after* your tag push — a pull done in
   step 3 will be one commit stale once the workflow finishes.
   ```bash
   git pull --ff-only
   ```
8. **Verify the artifacts actually landed** — the workflow going green means the push commands ran;
   confirm the registries themselves updated (PyPI can lag a few seconds, Docker Hub's REST API can
   lag longer than the push itself):
   ```bash
   curl -sf "https://pypi.org/pypi/dd-agents/X.Y.Z/json" | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])"
   docker manifest inspect zoharbabin/due-diligence-agents:X.Y.Z >/dev/null && echo OK
   ```

## Desktop app

The same `v*` tag also starts [`desktop.yml`](.github/workflows/desktop.yml). It builds the macOS (Apple Silicon) and Windows x64 installers, signs them (Apple Developer ID and notarization, Azure Artifact Signing), signs the update files with the minisign key, and attaches everything to the GitHub Release. Signing secrets are repo secrets. See [`desktop/README.md`](desktop/README.md).

After step 5, also watch `desktop.yml` to green:

```bash
gh run watch $(gh run list --workflow=desktop.yml --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status
```

Then check the Release has these assets: the DMG, the Windows setup `.exe`, a `.sig` next to each update file, `latest.json`, `SHA256SUMS-desktop.txt`, the cask `due-diligence-agents.rb` and the three `zoharbabin.DueDiligenceAgents*.yaml` winget files.

Package managers are a manual step after the Release is verified. Copy `due-diligence-agents.rb` into the `Casks/` folder of your Homebrew tap. For winget, put the three `.yaml` files in `manifests/z/zoharbabin/DueDiligenceAgents/<version>/` of your `winget-pkgs` fork and open a PR. Both manifests point at the signed files of the Release.

Installed apps read `releases/latest/download/latest.json`, and the tag release becomes "Latest" at once. So a tag ships to every installed app. Test before you tag: run `desktop.yml` by hand with **sign** on (`gh workflow run desktop.yml -f sign=true`), install the signed artifacts from that run on a clean macOS and a clean Windows machine, and run one review. Tag only after that.

## Closing issues

**Don't rely on a squash-merge PR body's `Closes #A, #B, #C` to auto-close every listed issue.**
GitHub only parses closing keywords from a squash commit if they survive into the squash commit
message *as GitHub builds it* (the individual commit messages, not the PR description) — a PR body
listing five issues auto-closed only one of them in practice. After merging, check what actually
closed and close the rest explicitly:

```bash
gh api graphql -f query='
  query { repository(owner: "zoharbabin", name: "due-diligence-agents") {
    pullRequest(number: N) { closingIssuesReferences(first: 10) { nodes { number } } }
  } }' --jq '.data.repository.pullRequest.closingIssuesReferences.nodes'

# for anything not in that list:
gh issue close <N> --comment "Resolved by #<PR>, merged into \`main\` at <sha> and released as vX.Y.Z."
```

If the PR closes every open issue in a milestone, close the milestone too — there's no `gh milestone`
subcommand, so use the REST API directly:

```bash
gh api repos/zoharbabin/due-diligence-agents/milestones/<N> -X PATCH -f state=closed
```

## What NOT to do

- Don't bump the version or tag directly on `main` before the PR merges — the bump commit belongs
  in the PR so CI validates it together with the code change.
- Don't tag before the PR's CI is green — the release workflow re-runs the full quality gate anyway,
  but a red PR means you're about to publish something you haven't actually verified.
- Don't hand-write PyPI/Docker/Homebrew publishing steps — they're automated in `release.yml`;
  manual publishing risks drifting from what CI already builds and tests.
- Don't leave the auto-generated release notes as-is for a release with more than a couple of
  commits — a flat commit list doesn't tell a user what changed or why.
