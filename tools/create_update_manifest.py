from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the MediaFlow GitHub Releases update manifest.")
    parser.add_argument("--version", required=True)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--notes", type=Path, default=None)
    args = parser.parse_args()

    installer = args.installer.resolve()
    if not installer.is_file() or installer.suffix.lower() != ".exe":
        parser.error(f"Installer not found or not an EXE: {installer}")

    notes = ""
    if args.notes and args.notes.is_file():
        notes = args.notes.read_text(encoding="utf-8").strip()

    manifest = {
        "schema_version": 1,
        "product": "MediaFlow",
        "version": args.version,
        "installer_asset": installer.name,
        "sha256": sha256_file(installer),
        "installer_size": installer.stat().st_size,
        "release_notes": notes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest created: {args.output}")
    print(f"Installer SHA-256: {manifest['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
