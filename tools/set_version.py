from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding='utf-8')
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f'No se encontró exactamente una referencia para actualizar en {path.name}.')
    path.write_text(updated, encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description='Actualiza las referencias de versión de MediaFlow.')
    parser.add_argument('--version', required=True, help='Versión estable X.Y.Z')
    args = parser.parse_args()
    version = args.version.strip().removeprefix('v')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        parser.error('La versión debe tener el formato X.Y.Z, por ejemplo 0.4.5.')

    replace_once(ROOT / 'app.py', r'^APP_VERSION\s*=\s*"[^"]+"\s*$', f'APP_VERSION = "{version}"')
    replace_once(ROOT / 'MediaFlow-Setup.iss', r'^\s*#define MyAppVersion "[^"]+"$', f'#define MyAppVersion "{version}"')
    (ROOT / 'VERSION.txt').write_text(f'MediaFlow {version}\n', encoding='utf-8')
    print(f'MediaFlow version updated to {version}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
