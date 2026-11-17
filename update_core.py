"""GitHub Releases update discovery and verified installer download (stdlib only)."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

PRODUCT_NAME = "MediaFlow"
MANIFEST_ASSET_NAME = "mediaflow-update.json"
API_VERSION = "2022-11-28"
USER_AGENT = "MediaFlow-Updater/1.0"


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag_name: str
    release_url: str
    release_notes: str
    installer_name: str
    installer_url: str
    sha256: str
    installer_size: int

    def to_dict(self) -> dict:
        return asdict(self)


def validate_repository_name(value: str) -> bool:
    """Accept a public GitHub repository in owner/name form only."""
    if not isinstance(value, str) or value.count("/") != 1:
        return False
    owner, repo = value.strip().split("/", 1)
    pattern = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
    repo_pattern = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
    return bool(pattern.fullmatch(owner) and repo_pattern.fullmatch(repo) and repo not in {".", ".."})


def version_tuple(value: str) -> tuple[int, int, int, int]:
    """Parse stable dotted versions such as 0.4.4 or v1.2.3. Prereleases are rejected."""
    text = str(value or "").strip()
    if text[:1].lower() == "v":
        text = text[1:]
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not match:
        raise ValueError(f"Version non supportee: {value!r}")
    parts = [int(part or 0) for part in match.groups()]
    return tuple(parts)  # type: ignore[return-value]


def is_newer_version(candidate: str, current: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def _json_request(url: str, *, max_bytes: int = 1024 * 1024) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "api.github.com":
        raise ValueError("La consulta de actualizaciones debe usar api.github.com por HTTPS.")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError("No se encontró una versión publicada en ese repositorio.") from exc
        if exc.code == 403:
            raise RuntimeError("GitHub limitó temporalmente las consultas. Inténtalo más tarde.") from exc
        raise RuntimeError(f"GitHub respondió con HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No se pudo conectar con GitHub: {exc.reason}") from exc
    if len(payload) > max_bytes:
        raise RuntimeError("La respuesta de GitHub supera el tamaño permitido.")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("GitHub devolvió una respuesta JSON no válida.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("La respuesta de GitHub no tiene el formato esperado.")
    return data


def _download_small_json(url: str, *, max_bytes: int = 256 * 1024) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "release-assets.githubusercontent.com"}:
        raise ValueError("La URL del manifiesto no pertenece a GitHub.")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            final_url = urlparse(response.geturl())
            if final_url.scheme != "https" or not (
                final_url.hostname == "github.com" or
                (final_url.hostname or "").endswith(".githubusercontent.com")
            ):
                raise ValueError("La descarga del manifiesto redirigió a un dominio no permitido.")
            raw = response.read(max_bytes + 1)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No se pudo descargar el manifiesto de la versión: {exc.reason}") from exc
    if len(raw) > max_bytes:
        raise RuntimeError("El manifiesto de actualización es demasiado grande.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("El manifiesto de actualización no contiene JSON válido.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("El manifiesto de actualización tiene un formato incorrecto.")
    return data


def fetch_latest_update(repository: str, current_version: str) -> UpdateInfo | None:
    """Return validated latest update metadata, or None if already current."""
    repository = str(repository or "").strip()
    if not validate_repository_name(repository):
        raise ValueError("Indica el repositorio público de GitHub con el formato propietario/repositorio.")

    release = _json_request(f"https://api.github.com/repos/{repository}/releases/latest")
    if release.get("draft") or release.get("prerelease"):
        raise RuntimeError("La versión más reciente no es una publicación estable.")
    tag_name = str(release.get("tag_name") or "").strip()
    release_version = tag_name[1:] if tag_name.lower().startswith("v") else tag_name
    release_version_tuple = version_tuple(release_version)
    current_tuple = version_tuple(current_version)
    if release_version_tuple <= current_tuple:
        return None

    assets = release.get("assets") or []
    assets_by_name = {str(item.get("name")): item for item in assets if isinstance(item, dict)}
    manifest_asset = assets_by_name.get(MANIFEST_ASSET_NAME)
    if not manifest_asset:
        raise RuntimeError(f"La publicación no incluye el archivo {MANIFEST_ASSET_NAME}.")
    manifest_url = str(manifest_asset.get("browser_download_url") or "")
    manifest = _download_small_json(manifest_url)

    if manifest.get("product") != PRODUCT_NAME:
        raise RuntimeError("El manifiesto no pertenece a MediaFlow.")
    manifest_version = str(manifest.get("version") or "").strip()
    if version_tuple(manifest_version) != release_version_tuple:
        raise RuntimeError("La versión del manifiesto no coincide con la etiqueta de GitHub.")

    installer_name = str(manifest.get("installer_asset") or "").strip()
    if not installer_name or Path(installer_name).name != installer_name or not installer_name.lower().endswith(".exe"):
        raise RuntimeError("El nombre del instalador en el manifiesto no es válido.")
    installer_asset = assets_by_name.get(installer_name)
    if not installer_asset:
        raise RuntimeError(f"La publicación no contiene el instalador {installer_name}.")
    installer_url = str(installer_asset.get("browser_download_url") or "")
    parsed_url = urlparse(installer_url)
    if parsed_url.scheme != "https" or parsed_url.hostname != "github.com":
        raise RuntimeError("La URL del instalador no es una descarga oficial de GitHub.")

    expected_sha = str(manifest.get("sha256") or "").lower().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise RuntimeError("El manifiesto no contiene una huella SHA-256 válida.")

    release_url = str(release.get("html_url") or "")
    if not release_url.startswith("https://github.com/"):
        raise RuntimeError("La dirección de la publicación no es válida.")

    return UpdateInfo(
        version=manifest_version,
        tag_name=tag_name,
        release_url=release_url,
        release_notes=str(release.get("body") or manifest.get("release_notes") or "").strip(),
        installer_name=installer_name,
        installer_url=installer_url,
        sha256=expected_sha,
        installer_size=int(installer_asset.get("size") or 0),
    )


def download_verified_installer(
    info: dict,
    destination: Path,
    *,
    progress_callback: Callable[[int], None] | None = None,
    cancel_callback: Callable[[], bool] | None = None,
) -> Path:
    """Stream the installer to disk and verify its manifest SHA-256 before use."""
    installer_name = str(info.get("installer_name") or "")
    if not installer_name or Path(installer_name).name != installer_name:
        raise ValueError("Nombre de archivo de actualización no válido.")
    url = str(info.get("installer_url") or "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError("La descarga del instalador debe proceder de GitHub por HTTPS.")
    expected_sha = str(info.get("sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("La huella SHA-256 del instalador no es válida.")

    destination.mkdir(parents=True, exist_ok=True)
    final_path = destination / installer_name
    partial_path = destination / (installer_name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"})
    digest = hashlib.sha256()
    received = 0
    total = int(info.get("installer_size") or 0)

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            final_url = urlparse(response.geturl())
            if final_url.scheme != "https" or not (
                final_url.hostname == "github.com" or
                (final_url.hostname or "").endswith(".githubusercontent.com")
            ):
                raise ValueError("La descarga redirigió a un dominio no permitido.")
            header_total = response.headers.get("Content-Length")
            if header_total and header_total.isdigit():
                total = int(header_total)
            with partial_path.open("wb") as output:
                while True:
                    if cancel_callback and cancel_callback():
                        raise InterruptedError("La descarga de la actualización fue cancelada.")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if progress_callback and total > 0:
                        progress_callback(min(100, int(received * 100 / total)))
        actual_sha = digest.hexdigest()
        if actual_sha != expected_sha:
            raise RuntimeError("La verificación SHA-256 falló. El instalador descargado no coincide con el manifiesto.")
        if received < 1024 * 1024:
            raise RuntimeError("El archivo descargado es demasiado pequeño para ser un instalador válido.")
        partial_path.replace(final_path)
        if progress_callback:
            progress_callback(100)
        return final_path
    except Exception:
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
