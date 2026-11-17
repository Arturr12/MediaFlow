from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    print('+', subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def find_iscc() -> Path:
    candidates = []
    env_path = os.environ.get('ISCC_PATH')
    if env_path:
        candidates.append(Path(env_path))
    for env_name in ('ProgramFiles', 'ProgramFiles(x86)'):
        base = os.environ.get(env_name)
        if base:
            candidates.extend([
                Path(base) / 'Inno Setup 7' / 'ISCC.exe',
                Path(base) / 'Inno Setup 6' / 'ISCC.exe',
            ])
    from shutil import which
    located = which('ISCC.exe') or which('ISCC')
    if located:
        candidates.insert(0, Path(located))
    for item in candidates:
        if item.is_file():
            return item
    raise FileNotFoundError('No se encontró ISCC.exe. Instala Inno Setup 6 o 7.')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    version = args.version.strip().removeprefix('v')
    if not __import__('re').fullmatch(r'\d+\.\d+\.\d+', version):
        parser.error('Versión no válida; utiliza X.Y.Z.')

    run([sys.executable, str(ROOT / 'tools' / 'set_version.py'), '--version', version])

    for folder in ('build', 'dist', 'payload', 'Output'):
        target = ROOT / folder
        if target.exists():
            shutil.rmtree(target)

    pyinstaller = [
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
        '--name', 'MediaFlow', '--icon', str(ROOT / 'mediaflow.ico'),
        '--add-data', f'{ROOT / "mediaflow.ico"};.',
        '--collect-all', 'yt_dlp', '--collect-all', 'yt_dlp_ejs',
        '--copy-metadata', 'yt-dlp', '--copy-metadata', 'yt-dlp-ejs',
        str(ROOT / 'app.py'),
    ]
    run(pyinstaller)

    source_dir = ROOT / 'dist' / 'MediaFlow'
    if not (source_dir / 'MediaFlow.exe').is_file():
        raise FileNotFoundError('PyInstaller no generó dist/MediaFlow/MediaFlow.exe.')
    payload_dir = ROOT / 'payload' / 'MediaFlow'
    payload_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, payload_dir, dirs_exist_ok=True)
    shutil.copy2(ROOT / 'THIRD_PARTY_NOTICES.txt', payload_dir / 'THIRD_PARTY_NOTICES.txt')

    output_dir = ROOT / 'Output'
    output_dir.mkdir(parents=True, exist_ok=True)
    iscc = find_iscc()
    run([str(iscc), f'/DMyAppVersion={version}', str(ROOT / 'MediaFlow-Setup.iss')])

    installer = output_dir / f'MediaFlow-Setup-{version}.exe'
    if not installer.is_file():
        raise FileNotFoundError(f'Inno Setup no generó {installer.name}.')
    run([
        sys.executable, str(ROOT / 'tools' / 'create_update_manifest.py'),
        '--version', version,
        '--installer', str(installer),
        '--output', str(output_dir / 'mediaflow-update.json'),
        '--notes', str(ROOT / 'RELEASE_NOTES.md'),
    ])
    print('\nRelease assets listos:')
    print(installer)
    print(output_dir / 'mediaflow-update.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
