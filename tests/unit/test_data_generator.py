"""Tests for the synthetic data room generator."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.testing.data_generator import SyntheticDataRoomGenerator


class TestSyntheticDataRoomGenerator:
    """Tests for SyntheticDataRoomGenerator."""

    def test_generate_creates_directory(self, tmp_path: Path) -> None:
        gen = SyntheticDataRoomGenerator(seed=42)
        result = gen.generate(tmp_path, num_subjects=3)
        assert result.exists()
        assert result.is_dir()
        assert result.name == "data_room"

    def test_deterministic_with_same_seed(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "run_a"
        dir_b = tmp_path / "run_b"
        dir_a.mkdir()
        dir_b.mkdir()

        gen_a = SyntheticDataRoomGenerator(seed=99)
        gen_b = SyntheticDataRoomGenerator(seed=99)
        root_a = gen_a.generate(dir_a, num_subjects=4)
        root_b = gen_b.generate(dir_b, num_subjects=4)

        files_a = sorted(p.relative_to(root_a) for p in root_a.rglob("*.md"))
        files_b = sorted(p.relative_to(root_b) for p in root_b.rglob("*.md"))
        assert files_a == files_b

        # Content must also match
        for rel in files_a:
            assert (root_a / rel).read_text() == (root_b / rel).read_text()

    def test_different_seeds_differ(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "run_a"
        dir_b = tmp_path / "run_b"
        dir_a.mkdir()
        dir_b.mkdir()

        gen_a = SyntheticDataRoomGenerator(seed=1)
        gen_b = SyntheticDataRoomGenerator(seed=2)
        root_a = gen_a.generate(dir_a, num_subjects=5)
        root_b = gen_b.generate(dir_b, num_subjects=5)

        files_a = sorted(p.relative_to(root_a) for p in root_a.rglob("*.md"))
        files_b = sorted(p.relative_to(root_b) for p in root_b.rglob("*.md"))
        # Different seeds should produce different file sets or content
        contents_a = [((root_a / r).read_text()) for r in files_a]
        contents_b = [((root_b / r).read_text()) for r in files_b]
        assert files_a != files_b or contents_a != contents_b

    def test_subject_count_matches(self, tmp_path: Path) -> None:
        gen = SyntheticDataRoomGenerator(seed=42)
        root = gen.generate(tmp_path, num_subjects=5)

        # Count customer directories (exclude _reference)
        customer_dirs: list[Path] = []
        for group_dir in root.iterdir():
            if group_dir.name.startswith("_"):
                continue
            for cust_dir in group_dir.iterdir():
                if cust_dir.is_dir():
                    customer_dirs.append(cust_dir)

        assert len(customer_dirs) == 5

    def test_files_are_markdown(self, tmp_path: Path) -> None:
        gen = SyntheticDataRoomGenerator(seed=42)
        root = gen.generate(tmp_path, num_subjects=3)

        md_files = list(root.rglob("*.md"))
        assert len(md_files) > 0

        # Every generated file in customer dirs must end with .md
        for group_dir in root.iterdir():
            if group_dir.name.startswith("_"):
                continue
            for cust_dir in group_dir.iterdir():
                for f in cust_dir.iterdir():
                    assert f.suffix == ".md", f"Non-markdown file found: {f}"

    def test_reference_folder_exists(self, tmp_path: Path) -> None:
        gen = SyntheticDataRoomGenerator(seed=42)
        root = gen.generate(tmp_path, num_subjects=2)

        ref = root / "_reference"
        assert ref.exists()
        assert ref.is_dir()
        assert (ref / "buyer_overview.md").exists()

    def test_planted_coc_clause(self, tmp_path: Path) -> None:
        gen = SyntheticDataRoomGenerator(seed=42)
        root = gen.generate(tmp_path, num_subjects=5)

        all_text = ""
        for md_file in root.rglob("*.pdf.md"):
            all_text += md_file.read_text()

        assert "change of control" in all_text.lower()

    def test_planted_liability_cap(self, tmp_path: Path) -> None:
        gen = SyntheticDataRoomGenerator(seed=42)
        root = gen.generate(tmp_path, num_subjects=5)

        found = False
        for md_file in root.rglob("*.pdf.md"):
            content = md_file.read_text().lower()
            if "liability" in content and "shall not exceed" in content:
                found = True
                break

        assert found, "No liability cap clause found in any generated document"

    def test_group_structure(self, tmp_path: Path) -> None:
        gen = SyntheticDataRoomGenerator(seed=42)
        root = gen.generate(tmp_path, num_subjects=4)

        groups = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith("_")]
        assert len(groups) == 2
        group_names = sorted(d.name for d in groups)
        assert group_names == ["GroupA", "GroupB"]

        # Both groups have at least one customer
        for g in groups:
            customers = [d for d in g.iterdir() if d.is_dir()]
            assert len(customers) >= 1, f"Group {g.name} has no customers"

    def test_ip_ownership_clause(self, tmp_path: Path) -> None:
        gen = SyntheticDataRoomGenerator(seed=42)
        root = gen.generate(tmp_path, num_subjects=5)

        found = False
        for md_file in root.rglob("*.pdf.md"):
            content = md_file.read_text().lower()
            if "intellectual property" in content:
                found = True
                break

        assert found, "No IP ownership clause found in any generated document"

    def test_invalid_subject_count(self, tmp_path: Path) -> None:
        gen = SyntheticDataRoomGenerator(seed=42)
        with pytest.raises(ValueError, match="num_subjects must be between"):
            gen.generate(tmp_path, num_subjects=0)
        with pytest.raises(ValueError, match="num_subjects must be between"):
            gen.generate(tmp_path, num_subjects=11)

    def test_each_subject_has_two_to_four_files(self, tmp_path: Path) -> None:
        gen = SyntheticDataRoomGenerator(seed=42)
        root = gen.generate(tmp_path, num_subjects=5)

        for group_dir in root.iterdir():
            if group_dir.name.startswith("_"):
                continue
            for cust_dir in group_dir.iterdir():
                files = list(cust_dir.iterdir())
                assert 2 <= len(files) <= 4, f"Customer {cust_dir.name} has {len(files)} files, expected 2-4"
