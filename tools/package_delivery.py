"""Plan or build the reviewed BookBridge delivery without copying private runtime.

Default: print the selection only. --build creates a NEW stage and ZIP.
Existing targets are never deleted or overwritten. Use --extra-evidence-dir for
new passing evidence folders. Directory arguments are relative to phase3/.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import zipfile

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
STAGE_NAME = "Abgabe_BookBridge_GitHub"
ZIP_NAME = "Abgabe_BookBridge_GitHub.zip"
FIXED_ZIP_TIME = (2026, 11, 2, 12, 0, 0)
PHASE_MAP = {
    "Phase 1": "01_Konzeptionsphase",
    "Phase 2": "02_Erarbeitungs_Reflexionsphase",
    "phase3": "03_Finalisierungsphase",
}
BLOCK_DIRS = {
    ".runtime", ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", "tmp", "temp",
    "scratch", "qa", "docx-qa", "rendered", "renders", "previews", "preview",
}
BLOCK_SUFFIX = {
    ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".pyc", ".pyo",
    ".wbk", ".bak", ".tmp", ".temp", ".log", ".sha256", ".sha512", ".md5",
    ".pem", ".key", ".pfx", ".p12", ".env",
}
BLOCK_NAMES = {"owner.json", "config.json", "postmaster.pid", "pg_version", "pg_hba.conf", "pgpass.conf", ".env"}
REQUIRED_DOCS = (
    "BookBridge_Phase3_Abschlussbericht.pdf", "BookBridge_Abstract.pdf",
    "BookBridge_Gesamtdokumentation.pdf", "BookBridge_Repository_und_Abgabe.pdf",
)
PHASE2_EVIDENCE_FILES = {
    "artifact_review.json", "backup_verification.json", "installer_verification.json",
    "delivery_verification.json", "schema_verification.json", "test-report.json",
    "clean-install-console.txt", "integration-test-console.txt", "installer-console.txt",
    "Q01_copy_book_owner.csv", "Q02_loan_copy_borrower.csv", "Q03_payment_loan_confirmer.csv",
}
PHASE3_EVIDENCE_DIRS = {"release-verification-20261020", "release-tests", "browser-20261020", "release-tests-20261021"}
PHASE3_EVIDENCE_FILES = {
    "native-dependencies-verification.json", "phase2-source-preservation.json",
    "runtime-migration08-verification.json", "runtime-migration09-verification.json",
    "runtime-verification.json", "runtime-relocation-20261021.json",
    "verified-metadata-20261021.json", "native-runtime-verification-20261021.json",
    "sql-master-verification-20261021.json",
    "document-verification-20261021.json", "document-verification-20261102.json",
    "github-publication-20261102.json",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def blocked(relative: Path) -> bool:
    return (
        any(part.lower() in BLOCK_DIRS for part in relative.parts)
        or relative.suffix.lower() in BLOCK_SUFFIX
        or relative.name.lower() in BLOCK_NAMES
        or relative.name.startswith("~$")
        or any(part.startswith(".") and part not in {".gitignore", ".gitattributes"} for part in relative.parts)
        or relative.name == "SHA256SUMS.txt"
    )


def phase_dir(root: Path, canonical_name: str) -> Path:
    """Accept both the source-project and extracted delivery layout."""
    source = root / canonical_name
    delivered = root / PHASE_MAP[canonical_name]
    return source if source.is_dir() else delivered


def read_selection(root: Path, extras: list[str]) -> tuple[list[dict], list[str]]:
    items = []
    extra_dirs = set()
    for value in extras:
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Extra evidence must be relative to phase3/evidence.")
        if relative.parts and relative.parts[0] == "evidence":
            relative = Path(*relative.parts[1:])
        if len(relative.parts) != 1 or blocked(relative):
            raise ValueError("Extra evidence must name one reviewed evidence directory.")
        extra_dirs.add(relative.as_posix())
    # Latest release has priority. Older release is retained because README
    # describes it explicitly and its stable synthetic exports remain useful.
    if (phase_dir(root, "phase3") / "evidence/release-verification-20261021").is_dir():
        extra_dirs.add("release-verification-20261021")
    for source_phase, destination_phase in PHASE_MAP.items():
        phase_root = phase_dir(root, source_phase)
        if not phase_root.is_dir():
            raise ValueError(f"Missing phase directory: {source_phase}")
        for source in sorted(phase_root.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(phase_root)
            if blocked(relative) or source.is_symlink():
                continue
            top = relative.parts[0]
            if source_phase == "Phase 1":
                include = top in {"design", "pictures", "README.md"} or (len(relative.parts) == 1 and source.suffix.lower() in {".docx", ".pdf"})
            elif source_phase == "Phase 2":
                include = top in {"database", "design", "docs", "pictures", "screenshots", "scripts", "sql", "tests", "README.md"}
                if top == "evidence":
                    include = (len(relative.parts) == 2 and relative.name in PHASE2_EVIDENCE_FILES) or (len(relative.parts) >= 3 and relative.parts[1] in {"tables", "recheck-20261019"})
            else:
                include = top in {"backend", "database", "docs", "frontend", "scripts", "tests", "README.md", "requirements.txt", "run.py", "BookBridge starten.cmd", ".gitignore"}
                if top == "evidence":
                    include = (len(relative.parts) == 2 and relative.name in PHASE3_EVIDENCE_FILES) or (len(relative.parts) >= 3 and relative.parts[1] in PHASE3_EVIDENCE_DIRS | extra_dirs)
            if include:
                transform = "phase2-shared-package-checksums" if source_phase == "Phase 2" and relative.as_posix() == "README.md" else None
                items.append({"source": source, "destination": (Path(destination_phase) / relative).as_posix(), "transform": transform})
    readme = root / "README.md"
    if not readme.is_file():
        raise ValueError("Project README.md is required.")
    items.append({"source": readme, "destination": "README.md", "transform": "delivery-relative-links"})
    tools = root / "tools/package_delivery.py"
    if tools.is_file():
        items.append({"source": tools, "destination": "tools/package_delivery.py", "transform": None})
    for name in (".gitignore", ".gitattributes", "tools/refresh_publication.py"):
        extra = root / name
        if extra.is_file():
            items.append({"source": extra, "destination": name, "transform": None})
    phase3_root = phase_dir(root, "phase3")
    missing = [f"phase3/docs/{name}" for name in REQUIRED_DOCS if not (phase3_root / "docs" / name).is_file()]
    missing += [f"phase3/evidence/{value}" for value in extra_dirs if not (phase3_root / "evidence" / value).is_dir()]
    if not tools.is_file():
        missing.append("tools/package_delivery.py")
    return sorted(items, key=lambda item: item["destination"]), missing


def payload(item: dict) -> bytes:
    raw = item["source"].read_bytes()
    if item["transform"] == "delivery-relative-links":
        # Keep the original working-tree README untouched. Only staged links
        # must resolve to the assignment's three delivery folders.
        text = raw.decode("utf-8-sig")
        text = text.replace("](" + "phase3/", "](" + PHASE_MAP["phase3"] + "/")
        raw = text.encode("utf-8")
    elif item["transform"] == "phase2-shared-package-checksums":
        text = raw.decode("utf-8-sig")
        note = "Im gemeinsamen Abgabepaket aller drei Phasen gelten die Prüfsummen und das MANIFEST im übergeordneten Hauptordner; das frühere Einzelarchiv wird dort nicht zusätzlich eingebettet."
        anchor = "`SHA256SUMS.txt` und `BookBridge_Phase2.zip.sha256` ermöglichen den Vergleich der gelieferten Dateien und des ZIP-Archivs."
        if note not in text:
            if anchor not in text:
                raise ValueError("Phase 2 README checksum sentence not found; original remains unchanged.")
            text = text.replace(anchor, anchor + " " + note, 1)
        raw = text.encode("utf-8")
    return raw


def known_private_values(root: Path) -> list[bytes]:
    values = set()
    for name in ("owner.json", "config.json"):
        source = phase_dir(root, "phase3") / ".runtime" / name
        if not source.is_file():
            continue
        try:
            record = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise ValueError("Cannot inspect private local configuration for leak checking.") from None
        for key, value in record.items():
            if not isinstance(value, str):
                continue
            if "password" in key.lower() and len(value) >= 16:
                values.add(value.encode())
            if key == "database_dsn":
                match = re.search(r"(?:^|\s)password=(?:'([^']+)'|([^\s]+))", value)
                if match:
                    value = match[1] or match[2]
                    if len(value) >= 16:
                        values.add(value.encode())
    return sorted(values)


def content_parts(raw: bytes, suffix: str):
    yield raw
    if suffix in {".docx", ".pptx", ".xlsx"}:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for name in archive.namelist():
                if name.endswith((".xml", ".rels", ".txt")):
                    yield archive.read(name)


def validate(items: list[dict], root: Path, missing: list[str]) -> dict:
    known = known_private_values(root)
    leaks, unsafe, failures = [], [], []
    destinations = [item["destination"] for item in items]
    if len(destinations) != len(set(destinations)):
        failures.append("duplicate_destinations")
    for item in items:
        relative = Path(item["destination"])
        if blocked(relative) or ".." in relative.parts or relative.is_absolute():
            unsafe.append(relative.as_posix())
        raw = payload(item)
        parts = list(content_parts(raw, relative.suffix.lower()))
        if any(value in part for value in known for part in parts):
            leaks.append(relative.as_posix())
        # Reject accidentally selected failed historical reports. Text test logs
        # may mention expected rejected actions, so only inspect JSON statuses.
        if "evidence" in relative.parts and relative.suffix.lower() == ".json":
            record = json.loads(raw.decode("utf-8-sig"))
            def has_failure(value):
                if isinstance(value, dict):
                    return value.get("status") in {"failed", "error"} or value.get("failed", 0) not in (0, False, None) or any(has_failure(v) for v in value.values())
                return isinstance(value, list) and any(has_failure(v) for v in value)
            if has_failure(record):
                failures.append(relative.as_posix())
    phase3 = PHASE_MAP["phase3"]
    missing += [f"{phase3}/{name}" for name in ("database/BookBridge_Gesamt.sql", "README.md", "scripts/setup.ps1", "run.py") if f"{phase3}/{name}" not in destinations]
    required_prior = [
        f'{PHASE_MAP["Phase 1"]}/BookBridge_Anforderungsspezifikation_v2.pdf',
        f'{PHASE_MAP["Phase 1"]}/BookBridge_Beschreibung_Arbeit_Arbeitsschritte_v2.pdf',
        f'{PHASE_MAP["Phase 1"]}/BookBridge_Datenwoerterbuch_v2.pdf',
        f'{PHASE_MAP["Phase 1"]}/design/bookbridge-model-v2.json',
        f'{PHASE_MAP["Phase 2"]}/docs/BookBridge_Phase2_Praesentation.pdf',
        f'{PHASE_MAP["Phase 2"]}/docs/BookBridge_Phase2_Praesentation.pptx',
        f'{PHASE_MAP["Phase 2"]}/docs/BookBridge_Phase2_Umsetzung.pdf',
        f'{PHASE_MAP["Phase 2"]}/database/bookbridge_phase2.dump',
        f'{PHASE_MAP["Phase 2"]}/evidence/recheck-20261019/test-report.json',
        f'{PHASE_MAP["Phase 2"]}/screenshots/manifest.json',
    ]
    missing += [name for name in required_prior if name not in destinations]
    screenshot_count = sum(name.startswith(PHASE_MAP["Phase 2"] + "/screenshots/") and name.endswith(".png") for name in destinations)
    if screenshot_count != 21:
        failures.append("phase2_expected_21_screenshots")
    deck_path = phase_dir(root, "Phase 2") / "docs/BookBridge_Phase2_Praesentation.pptx"
    slide_count = 0
    if deck_path.is_file():
        with zipfile.ZipFile(deck_path) as deck:
            slide_count = sum(bool(re.fullmatch(r"ppt/slides/slide\d+\.xml", name)) for name in deck.namelist())
        if slide_count != 32:
            failures.append("phase2_expected_32_slides")
    expected_migrations = [f"database/phase2/{name}" for name in ("01_schema.sql", "02_integrity.sql", "03_workflows.sql", "04_seed.sql", "06_access.sql")]
    expected_migrations += [f"database/{name}" for name in ("07_application.sql", "08_application_editing.sql", "09_deferred_validation.sql")]
    for name in expected_migrations:
        if f"{phase3}/{name}" not in destinations:
            missing.append(f"{phase3}/{name}")
    source_mapping = {item["destination"]: item for item in items}
    readme_item = source_mapping["README.md"]
    relative_links = []
    invalid_links = []
    for target in re.findall(r"\]\(([^)]+)\)", payload(readme_item).decode("utf-8")):
        target = target.strip("<>").split("#", 1)[0]
        if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
            continue
        relative_links.append(target)
        if target not in destinations:
            invalid_links.append(target)
    if invalid_links:
        failures.append("unresolved_staged_root_readme_links")
    preservation = {}
    for name in ("01_schema.sql", "02_integrity.sql", "03_workflows.sql", "04_seed.sql", "05_queries.sql", "06_access.sql"):
        one = source_mapping.get(f'{PHASE_MAP["Phase 2"]}/sql/{name}')
        two = source_mapping.get(f"{phase3}/database/phase2/{name}")
        preservation[name] = bool(one and two and payload(one) == payload(two))
    if not all(preservation.values()):
        failures.append("phase2_sql_preservation")
    check = {
        "status": "passed" if not (missing or unsafe or leaks or failures) else "blocked",
        "scope": "Source selection, artifact coverage and private-runtime exclusion; not a replacement for application tests.",
        "file_count_before_generated_manifests": len(items),
        "phase_file_counts": dict(sorted(Counter(PurePosixPath(item["destination"]).parts[0] for item in items).items())),
        "eight_migration_sources": expected_migrations,
        "all_phase2_sql_preserved_byte_for_byte": preservation,
        "phase2_slide_count": slide_count,
        "phase2_original_screenshot_count": screenshot_count,
        "staged_root_readme_links": relative_links,
        "unresolved_staged_root_readme_links": invalid_links,
        "missing_required_files": sorted(set(missing)),
        "unsafe_paths": unsafe,
        "known_local_secret_leaks": leaks,
        "known_password_values_checked": len(known),
        "secret_check": "Known local password values are scanned when a private local configuration is available; runtime/config files are excluded by path. Publication refresh may additionally scan an explicit private source without copying it.",
        "failed_evidence_or_selection_checks": failures,
        "excluded": {"directories": sorted(BLOCK_DIRS), "suffixes": sorted(BLOCK_SUFFIX), "names": sorted(BLOCK_NAMES), "obsolete_phase3": ["verification-20261020", "backend-diagnostic-20261020", "backend-fixed-20261020", "final-verification-20261020"]},
        "personal_steps_pending": ["Add actual identity and apply assignment filenames if required for the final portal upload."],
        "mycampus_declaration": "Completed according to project owner on 2026-11-02.",
    }
    return check


def build(root: Path, stage: Path, archive: Path, items: list[dict], check: dict) -> dict:
    if check["status"] != "passed":
        raise ValueError("Package checks are blocked; no delivery created.")
    if stage.exists() or archive.exists() or archive.with_suffix(".zip.sha256").exists():
        raise ValueError("A target already exists. Nothing is overwritten or deleted; choose new --stage/--zip.")
    if stage.parent.resolve() != root.resolve() or archive.parent.resolve() != root.resolve():
        raise ValueError("Delivery stage and archive must be direct children of the authoritative project root.")
    stage.mkdir()
    manifest_entries = []
    for item in items:
        raw = payload(item)
        target = stage / item["destination"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        manifest_entries.append({"path": item["destination"], "source": item["source"].relative_to(root).as_posix(), "bytes": len(raw), "sha256": sha(raw), "source_sha256": sha(item["source"].read_bytes()), "transformation": item["transform"]})
    (stage / "MANIFEST.json").write_bytes(json_bytes({
        "project": "BookBridge", "delivery_date": "2026-11-02", "source_files": manifest_entries,
        "generated_files": ["MANIFEST.json", "PACKAGE_CHECK.json", "SHA256SUMS.txt"],
        "manifest_scope": "Every selected source including README. Generated files cannot contain their own hash; SHA256SUMS includes both JSON records and excludes only itself. ZIP checksum is external.",
    }))
    (stage / "PACKAGE_CHECK.json").write_bytes(json_bytes(check))
    staged_files = sorted(p for p in stage.rglob("*") if p.is_file())
    digest_lines = [f"{sha(p.read_bytes())}  {p.relative_to(stage).as_posix()}" for p in staged_files]
    (stage / "SHA256SUMS.txt").write_text("\n".join(digest_lines) + "\n", encoding="utf-8", newline="\n")
    staged_files.append(stage / "SHA256SUMS.txt")
    staged_files.sort()
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for source in staged_files:
            name = f"{stage.name}/{source.relative_to(stage).as_posix()}"
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            output.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    digest = sha(archive.read_bytes())
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8", newline="\n")
    with zipfile.ZipFile(archive) as verified:
        if verified.testzip() is not None or len(verified.namelist()) != len(staged_files):
            raise RuntimeError("Archive integrity/count verification failed.")
        for source in staged_files:
            name = f"{stage.name}/{source.relative_to(stage).as_posix()}"
            if verified.read(name) != source.read_bytes():
                raise RuntimeError("Archive differs from the stage.")
    return {"stage": str(stage), "zip": str(archive), "files": len(staged_files), "zip_bytes": archive.stat().st_size, "zip_sha256": digest, "archive_integrity": "passed", "source_files": len(items)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--extra-evidence-dir", action="append", default=[])
    parser.add_argument("--inventory-out", type=Path)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    items, missing = read_selection(root, args.extra_evidence_dir)
    check = validate(items, root, missing)
    result = {"selection": check, "source_bytes": sum(len(payload(item)) for item in items)}
    if args.build:
        result["delivery"] = build(root, args.stage or root / STAGE_NAME, args.zip or root / ZIP_NAME, items, check)
    if args.inventory_out:
        args.inventory_out.parent.mkdir(parents=True, exist_ok=True)
        args.inventory_out.write_bytes(json_bytes({**result, "selected_paths": [item["destination"] for item in items]}))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if check["status"] == "passed" else 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise SystemExit(f"Delivery stopped safely: {error}") from None
