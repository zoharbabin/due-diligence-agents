"""Write the Homebrew cask and the winget manifests for a release.

Usage: python desktop/scripts/package_manifests.py <tag> <owner/repo> <assets-dir>

Run after ``updater_manifest.py`` (it needs the final file names). The files are attached to the
release. Submitting them to a tap or to winget-pkgs is a separate, manual step. See RELEASE.md.
"""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

NAME = "due-diligence-agents"
TITLE = "Due Diligence Agents"
WINGET_ID = "zoharbabin.DueDiligenceAgents"
WINGET_SCHEMA = "1.6.0"
DESCRIPTION = "Forensic M&A due diligence on your own machine"
LICENSE = "Apache-2.0"

CASK = """cask "{name}" do
  version "{version}"
  sha256 "{sha256}"

  url "https://github.com/{repo}/releases/download/v#{{version}}/{name}_#{{version}}_aarch64.dmg"
  name "{title}"
  desc "{description}"
  homepage "https://github.com/{repo}"

  livecheck do
    url :url
    strategy :github_latest
  end

  auto_updates true
  depends_on arch: :arm64
  depends_on :macos

  app "{title}.app"

  zap trash: [
    "~/.dd-projects",
    "~/Library/Application Support/com.zoharbabin.due-diligence-agents",
    "~/Library/Logs/com.zoharbabin.due-diligence-agents",
  ]
end
"""

WINGET_VERSION = """PackageIdentifier: {id}
PackageVersion: {version}
DefaultLocale: en-US
ManifestType: version
ManifestVersion: {schema}
"""

WINGET_INSTALLER = """PackageIdentifier: {id}
PackageVersion: {version}
InstallerType: nullsoft
Scope: user
UpgradeBehavior: install
ReleaseDate: {date}
Installers:
  - Architecture: x64
    InstallerUrl: {url}
    InstallerSha256: {sha256}
ManifestType: installer
ManifestVersion: {schema}
"""

WINGET_LOCALE = """PackageIdentifier: {id}
PackageVersion: {version}
PackageLocale: en-US
Publisher: Zohar Babin
PublisherUrl: https://github.com/zoharbabin
PackageName: {title}
PackageUrl: https://github.com/{repo}
License: {license}
LicenseUrl: https://github.com/{repo}/blob/main/LICENSE
ShortDescription: {description}
ReleaseNotesUrl: https://github.com/{repo}/releases/tag/v{version}
ManifestType: defaultLocale
ManifestVersion: {schema}
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _need(directory: Path, name: str) -> Path:
    path = directory / name
    if not path.is_file():
        sys.exit(f"Missing release file: {name}")
    return path


def write(directory: Path, tag: str, repo: str) -> None:
    match = re.fullmatch(r"v(\d+\.\d+\.\d+)", tag)
    if not match:
        sys.exit(f"Not a release tag: {tag!r}")
    version = match.group(1)
    dmg = _need(directory, f"{NAME}_{version}_aarch64.dmg")
    exe = _need(directory, f"{NAME}_{version}_x64-setup.exe")
    common = {"id": WINGET_ID, "version": version, "schema": WINGET_SCHEMA, "repo": repo, "title": TITLE}
    files = {
        f"{NAME}.rb": CASK.format(
            name=NAME, version=version, sha256=_sha256(dmg), repo=repo, title=TITLE, description=DESCRIPTION
        ),
        f"{WINGET_ID}.yaml": WINGET_VERSION.format(**common),
        f"{WINGET_ID}.installer.yaml": WINGET_INSTALLER.format(
            **common,
            date=datetime.now(UTC).strftime("%Y-%m-%d"),
            url=f"https://github.com/{repo}/releases/download/{tag}/{exe.name}",
            sha256=_sha256(exe).upper(),
        ),
        f"{WINGET_ID}.locale.en-US.yaml": WINGET_LOCALE.format(**common, license=LICENSE, description=DESCRIPTION),
    }
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")


def main() -> None:
    write(Path(sys.argv[3]), sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
