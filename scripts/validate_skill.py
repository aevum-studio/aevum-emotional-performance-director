#!/usr/bin/env python3
"""Offline structural validation for the AEVUM Codex skill."""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "aevum-emotional-performance-director"
ARCHIVE = ROOT / "dist" / "aevum-emotional-performance-director.zip"
EXPECTED_NAME = "aevum-emotional-performance-director"
ALLOWED_TOP_LEVEL = {"SKILL.md", "agents", "references", "scripts", "assets"}
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class ValidationError(Exception):
    pass


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        raise ValidationError("SKILL.md must begin with YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValidationError("SKILL.md frontmatter is not closed")
    values: dict[str, str] = {}
    for raw_line in text[4:end].splitlines():
        if not raw_line.strip() or raw_line.startswith((" ", "\t")):
            continue
        if ":" not in raw_line:
            raise ValidationError(f"invalid frontmatter line: {raw_line}")
        key, value = raw_line.split(":", 1)
        values[key.strip()] = value.strip().strip('"\'')
    return values


def validate_links(skill_dir: Path, text: str) -> list[str]:
    errors: list[str] = []
    for target in LINK_PATTERN.findall(text):
        if "://" in target or target.startswith("#"):
            continue
        clean = target.split("#", 1)[0]
        path = (skill_dir / clean).resolve()
        try:
            path.relative_to(skill_dir.resolve())
        except ValueError:
            errors.append(f"link escapes skill directory: {target}")
            continue
        if not path.is_file():
            errors.append(f"missing linked file: {target}")
    return errors


def validate_skill(skill_dir: Path = SKILL_DIR) -> list[str]:
    errors: list[str] = []
    manifest = skill_dir / "SKILL.md"
    if not manifest.is_file():
        return ["missing SKILL.md"]
    text = manifest.read_text(encoding="utf-8")
    try:
        metadata = parse_frontmatter(text)
    except ValidationError as exc:
        return [str(exc)]
    if metadata.get("name") != EXPECTED_NAME:
        errors.append(f"frontmatter name must be {EXPECTED_NAME!r}")
    description = metadata.get("description", "")
    if not description:
        errors.append("frontmatter description is required")
    if len(description) > 1024:
        errors.append("frontmatter description is too long")
    if skill_dir.name != EXPECTED_NAME:
        errors.append("skill folder name must match frontmatter name")
    unexpected = {p.name for p in skill_dir.iterdir()} - ALLOWED_TOP_LEVEL
    if unexpected:
        errors.append(f"unexpected top-level skill entries: {sorted(unexpected)}")
    manifests = [p for p in skill_dir.rglob("*") if p.is_file() and p.name.lower() == "skill.md"]
    if len(manifests) != 1:
        errors.append(f"expected exactly one SKILL.md, found {len(manifests)}")
    errors.extend(validate_links(skill_dir, text))
    for path in skill_dir.rglob("*"):
        if path.is_symlink():
            errors.append(f"symbolic links are not allowed: {path.relative_to(skill_dir)}")
        if path.is_file() and path.stat().st_size > 25 * 1024 * 1024:
            errors.append(f"file exceeds 25 MiB: {path.relative_to(skill_dir)}")
    if len([p for p in skill_dir.rglob("*") if p.is_file()]) > 500:
        errors.append("skill contains more than 500 files")
    return errors


def validate_archive(archive: Path = ARCHIVE) -> list[str]:
    if not archive.is_file():
        return ["missing installable ZIP"]
    errors: list[str] = []
    with zipfile.ZipFile(archive) as bundle:
        bad = bundle.testzip()
        if bad:
            errors.append(f"corrupt ZIP member: {bad}")
        names = [PurePosixPath(info.filename) for info in bundle.infolist() if info.filename]
        roots = {name.parts[0] for name in names if name.parts}
        if roots != {EXPECTED_NAME}:
            errors.append(f"ZIP must contain one top-level folder named {EXPECTED_NAME}")
        for name in names:
            if name.is_absolute() or ".." in name.parts:
                errors.append(f"unsafe ZIP path: {name}")
        manifest = PurePosixPath(EXPECTED_NAME) / "SKILL.md"
        if manifest not in names:
            errors.append("ZIP does not contain the required SKILL.md")
    if archive.stat().st_size > 50 * 1024 * 1024:
        errors.append("ZIP exceeds 50 MiB")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", type=Path, default=SKILL_DIR)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    args = parser.parse_args()
    errors = validate_skill(args.skill_dir) + validate_archive(args.archive)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Skill source and installable ZIP are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
