"""User-owned watchlists and reference notes under ``dd-config/screening/``.

Every deal has its own concerns. A user adds a list of parties to watch
(``kind: watchlist``) or a note the screening agent should read
(``kind: reference``). One folder, one format: YAML front-matter plus markdown.

Errors are collected per file and never raised. The caller treats any error as
a coverage gap, so a broken file can never look like a clean screen.
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from dd_agents.customization.loader import CustomizationError, _split_front_matter
from dd_agents.screening.models import EntryKind, ListEntry

SCREENING_DIR = Path("dd-config") / "screening"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ENTRIES_PER_FILE = 50_000
MAX_TOTAL_ENTRIES = 50_000

_CSV_COLUMNS = {
    "name",
    "type",
    "aliases",
    "birth_years",
    "countries",
    "programs",
    "reason",
    "url",
    "listed_on",
}
_LIST_FIELDS = ("aliases", "birth_years", "countries", "programs")


class _UserEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: EntryKind = "unknown"
    aliases: list[str] = Field(default_factory=list)
    birth_years: list[int] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    programs: list[str] = Field(default_factory=list)
    reason: str = ""
    url: str = ""
    listed_on: str = ""

    @field_validator("listed_on", mode="before")
    @classmethod
    def _date_to_text(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return value


class _FrontMatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", max_length=64)
    kind: Literal["watchlist", "reference"] = "watchlist"
    description: str = ""
    source_url: str = ""
    entries: list[_UserEntry] | None = None
    entries_file: str | None = None


class UserList(BaseModel):
    """One loaded file: a watchlist with entries, or a reference note with a body."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Literal["watchlist", "reference"]
    description: str = ""
    source_url: str = ""
    body: str = ""
    file: str
    entries: list[ListEntry] = Field(default_factory=list)

    @property
    def source_id(self) -> str:
        return f"user:{self.name}"


class UserScreeningConfig(BaseModel):
    """Everything loaded from ``dd-config/screening/``."""

    model_config = ConfigDict(extra="forbid")

    lists: list[UserList] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    file_hashes: dict[str, str] = Field(default_factory=dict)

    def entries(self) -> list[ListEntry]:
        return [e for item in self.lists if item.kind == "watchlist" for e in item.entries]

    def references(self) -> list[UserList]:
        return [item for item in self.lists if item.kind == "reference"]

    def content_hash(self) -> str:
        """Hash of every file read (md and csv). Empty string when there are none."""
        if not self.file_hashes:
            return ""
        digest = hashlib.sha256()
        for name in sorted(self.file_hashes):
            digest.update(f"{name}\0{self.file_hashes[name]}\0".encode())
        return digest.hexdigest()


def _short_validation_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:3]:
        loc = ".".join(str(p) for p in err["loc"])
        parts.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    return "; ".join(parts)


def _split_multi(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(";") if p.strip()]


def _read_limited(path: Path) -> bytes:
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise CustomizationError(f"file is {size} bytes, limit is {MAX_FILE_BYTES}")
    return path.read_bytes()


def _csv_entries(csv_bytes: bytes) -> list[_UserEntry]:
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig")))
    header = reader.fieldnames or []
    if "name" not in header:
        raise CustomizationError("CSV needs a 'name' column")
    unknown = set(header) - _CSV_COLUMNS
    if unknown:
        raise CustomizationError(f"unknown CSV column(s) {sorted(unknown)}. Allowed: {sorted(_CSV_COLUMNS)}")
    rows: list[_UserEntry] = []
    for row in reader:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        if len(rows) >= MAX_ENTRIES_PER_FILE:
            raise CustomizationError(f"more than {MAX_ENTRIES_PER_FILE} entries")
        data: dict[str, Any] = {k: (v or "").strip() for k, v in row.items() if k and k != "name"}
        data["name"] = name
        for key in _LIST_FIELDS:
            data[key] = _split_multi(data.get(key, ""))
        if not data.get("type"):
            data.pop("type", None)
        rows.append(_UserEntry.model_validate(data))
    return rows


def _to_list_entries(list_name: str, items: list[_UserEntry]) -> list[ListEntry]:
    return [
        ListEntry(
            source=f"user:{list_name}",
            uid=f"{list_name}-{idx}",
            name=item.name,
            aliases=item.aliases,
            kind=item.type,
            birth_years=item.birth_years,
            countries=item.countries,
            programs=item.programs,
            url=item.url,
            listed_on=item.listed_on,
            remarks=item.reason,
        )
        for idx, item in enumerate(items, start=1)
    ]


def _load_file(path: Path, folder: Path, hashes: dict[str, str]) -> UserList:
    raw = _read_limited(path)
    hashes[path.name] = hashlib.sha256(raw).hexdigest()
    fm_dict, body = _split_front_matter(raw.decode("utf-8"))
    try:
        fm = _FrontMatter.model_validate(fm_dict)
    except ValidationError as exc:
        raise CustomizationError(_short_validation_error(exc)) from exc

    items: list[_UserEntry] = []
    if fm.kind == "reference":
        if fm.entries is not None or fm.entries_file is not None:
            raise CustomizationError("a reference file cannot have entries")
    else:
        if fm.entries is not None and fm.entries_file is not None:
            raise CustomizationError("use either 'entries' or 'entries_file', not both")
        if fm.entries is not None:
            items = fm.entries
        elif fm.entries_file is not None:
            csv_path = (folder / fm.entries_file).resolve()
            if not csv_path.is_relative_to(folder.resolve()):
                raise CustomizationError("entries_file must stay inside dd-config/screening/")
            if not csv_path.is_file():
                raise CustomizationError(f"entries_file not found: {fm.entries_file}")
            csv_bytes = _read_limited(csv_path)
            hashes[csv_path.name] = hashlib.sha256(csv_bytes).hexdigest()
            items = _csv_entries(csv_bytes)
        if len(items) > MAX_ENTRIES_PER_FILE:
            raise CustomizationError(f"more than {MAX_ENTRIES_PER_FILE} entries")

    return UserList(
        name=fm.name,
        kind=fm.kind,
        description=fm.description,
        source_url=fm.source_url,
        body=body.strip(),
        file=path.name,
        entries=_to_list_entries(fm.name, items),
    )


def load_user_screening(project_dir: Path) -> UserScreeningConfig:
    """Load ``<project_dir>/dd-config/screening/*.md``. Never raises on bad content."""
    folder = project_dir / SCREENING_DIR
    cfg = UserScreeningConfig()
    if not folder.is_dir():
        return cfg

    seen: set[str] = set()
    total = 0
    for path in sorted(folder.glob("*.md")):
        try:
            loaded = _load_file(path, folder, cfg.file_hashes)
        except (CustomizationError, OSError, UnicodeDecodeError, ValueError) as exc:
            cfg.errors.append(f"{path.name}: {exc}")
            continue
        if loaded.name in seen:
            cfg.errors.append(f"{path.name}: duplicate list name '{loaded.name}'")
            continue
        if total + len(loaded.entries) > MAX_TOTAL_ENTRIES:
            cfg.errors.append(f"{path.name}: total entries would exceed {MAX_TOTAL_ENTRIES}")
            continue
        seen.add(loaded.name)
        total += len(loaded.entries)
        cfg.lists.append(loaded)
    return cfg
