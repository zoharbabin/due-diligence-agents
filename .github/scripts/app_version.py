"""Print the app version: the tag without its leading "v", or the pyproject version.

Usage: python .github/scripts/app_version.py <ref-name>
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ref = sys.argv[1] if len(sys.argv) > 1 else ""
match = re.fullmatch(r"v(\d+\.\d+\.\d+)", ref)
if match:
    print(match.group(1))
else:
    project = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8"))
    print(project["project"]["version"])
