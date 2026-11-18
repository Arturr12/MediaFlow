from __future__ import annotations

import os
import re
import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
import threading
import urllib.request
import uuid
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, QSize, Signal, QSignalBlocker, QSettings
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap, QColor, QPainter, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QInputDialog,
    QMenu,
    QProgressDialog,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QSizePolicy,
)

from updater import UpdateCheckWorker, UpdateDownloadWorker
from update_core import validate_repository_name

APP_NAME = "MediaFlow"
APP_VERSION = "0.5.3"
DEFAULT_UPDATE_REPOSITORY = "Arturr12/MediaFlow"
BASE_OUTPUT = Path.home() / "Videos" / APP_NAME
DEFAULT_DOWNLOADS = BASE_OUTPUT / "Descargados"
DEFAULT_CONVERTED = BASE_OUTPUT / "Convertidos"
SUPPORTED_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".mpeg", ".mpg", ".m4v", ".3gp", ".mp3", ".wav", ".m4a",
    ".aac", ".flac", ".ogg", ".opus",
}
OUTPUT_FORMATS = ["MP4", "MPG", "AVI", "MKV", "MP3"]
AUDIO_OUTPUT_FORMATS = ["MP3", "FLAC", "WAV", "M4A", "AAC", "OGG", "OPUS"]
AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".alac"}
MUSIC_OUTPUT_DIR = BASE_OUTPUT / "Musica"
QUALITY_OPTIONS = ["Mejor disponible", "1080p", "720p", "480p", "360p", "Solo audio"]
VIDEO_RESOLUTION_OPTIONS = ["Original", "1080p", "720p", "480p", "360p"]
VIDEO_COMPRESSION_OPTIONS = ["Alta", "Equilibrada", "Compacta", "Muy compacta"]
VIDEO_QUALITY_SETTINGS = {
    "Alta": {"crf": 20, "mpeg_q": 3, "audio_kbps": 192, "fat32_gib": 3.70},
    "Equilibrada": {"crf": 23, "mpeg_q": 5, "audio_kbps": 160, "fat32_gib": 3.40},
    "Compacta": {"crf": 27, "mpeg_q": 7, "audio_kbps": 128, "fat32_gib": 3.00},
    "Muy compacta": {"crf": 30, "mpeg_q": 9, "audio_kbps": 96, "fat32_gib": 2.60},
}
FAT32_MAX_FILE_BYTES = (4 * 1024 ** 3) - 1


QUALITY_FORMATS = {
    "Mejor disponible": "bv*+ba/b",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
    "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]/best",
    "Solo audio": "bestaudio/best",
}


def resource_path(relative_path: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


def _find_winget_package_executable(package_id: str, executable: str) -> str | None:
    """Find an executable installed per-user by WinGet without relying on stale PATH."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    package_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
    if not package_root.is_dir():
        return None
    try:
        package_dirs = sorted(package_root.glob(f"{package_id}_*"), reverse=True)
        for package_dir in package_dirs:
            try:
                for candidate in package_dir.rglob(executable):
                    if candidate.is_file():
                        return str(candidate)
            except (OSError, PermissionError):
                continue
    except (OSError, PermissionError):
        return None
    return None


def find_ffmpeg() -> str | None:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
        candidates.extend([app_dir / "ffmpeg.exe", app_dir / "bin" / "ffmpeg.exe"])
        bundle_dir = Path(getattr(sys, "_MEIPASS", app_dir))
        candidates.extend([bundle_dir / "ffmpeg.exe", bundle_dir / "bin" / "ffmpeg.exe"])
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    # Check PATH first, then the per-user WinGet package location. The latter
    # matters when dependencies were installed by the setup program just before
    # MediaFlow was launched, because the current process may have an old PATH.
    located = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    return located or _find_winget_package_executable("Gyan.FFmpeg.Essentials", "ffmpeg.exe")


def find_ffprobe() -> str | None:
    """Find ffprobe next to the selected FFmpeg executable or on PATH."""
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        sibling = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if sibling.is_file():
            return str(sibling)
    located = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if located:
        return located
    return _find_winget_package_executable(
        "Gyan.FFmpeg.Essentials", "ffprobe.exe" if os.name == "nt" else "ffprobe"
    )


def find_deno() -> str | None:
    located = shutil.which("deno") or shutil.which("deno.exe")
    if located:
        return located

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        link_path = Path(local_app_data) / "Microsoft" / "WinGet" / "Links" / "deno.exe"
        if link_path.is_file():
            return str(link_path)
    winget_path = _find_winget_package_executable("DenoLand.Deno", "deno.exe")
    if winget_path:
        return winget_path

    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        deno_path = Path(user_profile) / ".deno" / "bin" / "deno.exe"
        if deno_path.is_file():
            return str(deno_path)
    return None


def safe_output_stem(stem: str, max_length: int = 110) -> str:
    """Return a Windows-safe filename stem for titles supplied by remote sites."""
    value = str(stem or "").strip()
    value = "".join("_" if ord(char) < 32 or char in '<>:"/\\\\|?*' else char for char in value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    value = value[:max_length].rstrip(" .")
    if not value:
        value = "MediaFlow"
    # Windows reserves these names even when an extension is appended.
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
    if value.split(".", 1)[0].upper() in reserved:
        value = f"_{value}"
    return value


def unique_output_path(folder: Path, stem: str, extension: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    safe_stem = safe_output_stem(stem)
    safe_extension = re.sub(r"[^a-zA-Z0-9]", "", str(extension or "mp4")).lower() or "mp4"
    candidate = folder / f"{safe_stem}_MediaFlow.{safe_extension}"
    counter = 2
    while candidate.exists():
        candidate = folder / f"{safe_stem}_MediaFlow_{counter}.{safe_extension}"
        counter += 1
    return candidate


def human_speed(value: float | None) -> str:
    if not value or value < 0:
        return "—"
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return "—"


def human_eta(seconds: int | float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {secs:02d} s"
    return f"{secs} s"


def human_file_size(size: int) -> str:
    """Format a byte count using binary units."""
    value = float(max(0, size))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return "—"


def _probe_duration(source: Path) -> float | None:
    """Read duration without loading media into memory."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(source),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            value = float((result.stdout or "").strip())
            return value if value > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def _format_clock(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "tiempo desconocido"
    whole = int(seconds)
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _center_crop_pixmap(pixmap: QPixmap, size: QSize) -> QPixmap:
    """Scale and center-crop a thumbnail to the exact display dimensions."""
    if pixmap.isNull():
        return QPixmap()
    scaled = pixmap.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = max(0, (scaled.width() - size.width()) // 2)
    y = max(0, (scaled.height() - size.height()) // 2)
    return scaled.copy(x, y, size.width(), size.height())


def _placeholder_pixmap(size: QSize, label: str = "VIDEO") -> QPixmap:
    """Create a visible placeholder while a real preview is being prepared."""
    pixmap = QPixmap(size)
    pixmap.fill(QColor("#17283d"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#67e8f9"))
    painter.drawRoundedRect(1, 1, size.width() - 2, size.height() - 2, 7, 7)
    painter.setPen(QColor("#c7f9ff"))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, label)
    painter.end()
    return pixmap


def _thumbnail_cache_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else (Path.home() / ".local" / "share")
    return base / "MediaFlow" / "Thumbnails"


class OperationCancelled(Exception):
    """Raised when the user cancels an active MediaFlow operation."""


class ElidedLabel(QLabel):
    """QLabel that keeps the full value for tooltips and ellides its visible text.

    Unlike CSS text-overflow, native QLabel does not provide a one-line
    ellipsis option. This small widget applies the equivalent using Qt's
    font metrics whenever its width changes.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._full_text = ""
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = str(text or "")
        super().setToolTip(self._full_text)
        self._apply_elision()

    def fullText(self) -> str:  # noqa: N802
        return self._full_text

    def _apply_elision(self) -> None:
        available = max(0, self.contentsRect().width())
        if available <= 0:
            QLabel.setText(self, "")
            return
        metrics = QFontMetrics(self.font())
        visible = metrics.elidedText(self._full_text, Qt.ElideRight, available)
        QLabel.setText(self, visible)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_elision()


class ConversionRowWidget(QWidget):
    """Compact conversion row with individual progress and no thumbnail."""

    def __init__(self, list_widget: QListWidget, item: QListWidgetItem, source: Path, output_format: str):
        super().__init__()
        self.list_widget, self.item, self.source = list_widget, item, source
        self.setFixedHeight(82)
        self.setObjectName("conversionRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 7, 12, 7)
        root.setSpacing(12)
        details = QVBoxLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(3)
        self.title_label = ElidedLabel(source.name)
        self.title_label.setObjectName("conversionFileTitle")
        self.title_label.setMinimumHeight(18)
        details.addWidget(self.title_label)
        try:
            size = human_file_size(source.stat().st_size)
        except OSError:
            size = "Tamaño no disponible"
        self.details_label = ElidedLabel(f"{size}  ·  {source.parent}")
        self.details_label.setObjectName("conversionFileDetails")
        self.details_label.setMinimumHeight(16)
        details.addWidget(self.details_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("En espera")
        self.progress_bar.setFixedHeight(13)
        details.addWidget(self.progress_bar)
        self.status_label = ElidedLabel("Listo para convertir")
        self.status_label.setObjectName("conversionFileStatus")
        self.status_label.setMinimumHeight(15)
        details.addWidget(self.status_label)
        root.addLayout(details, 1)
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setObjectName("rowSeparator")
        separator.setFixedWidth(1)
        root.addWidget(separator, 0, Qt.AlignVCenter)
        fmt = QVBoxLayout()
        fmt.setContentsMargins(2, 0, 2, 0)
        fmt.setSpacing(4)
        caption = QLabel("FORMATO DE SALIDA")
        caption.setObjectName("fieldCaption")
        fmt.addWidget(caption)
        self.format_combo = QComboBox()
        self.format_combo.addItems(OUTPUT_FORMATS)
        self.format_combo.setCurrentText(output_format)
        self.format_combo.setMinimumWidth(104)
        self.format_combo.setMaximumWidth(118)
        self.format_combo.setFixedHeight(34)
        self.format_combo.currentTextChanged.connect(self._format_changed)
        fmt.addWidget(self.format_combo)
        root.addLayout(fmt)

    def sizeHint(self) -> QSize:
        return QSize(0, 82)

    def _format_changed(self, value: str) -> None:
        self.item.setData(Qt.UserRole + 2, value)
        row = self.list_widget.row(self.item)
        if row >= 0:
            self.list_widget.setCurrentRow(row)

    def set_thumbnail(self, thumbnail_path: str) -> None:
        return

    def set_format(self, value: str) -> None:
        blocker = QSignalBlocker(self.format_combo)
        self.format_combo.setCurrentText(value)
        del blocker
        self.item.setData(Qt.UserRole + 2, value)

    def set_status(self, value: str, tooltip: str | None = None) -> None:
        self.status_label.setText(value)
        if tooltip:
            self.status_label.setToolTip(tooltip)

    def set_progress(self, percent: int | None, message: str = "") -> None:
        if percent is not None:
            value = max(0, min(100, int(percent)))
            self.progress_bar.setValue(value)
            self.progress_bar.setFormat(f"{value}%")
        if message:
            self.set_status(message)

    def set_selected_look(self, selected: bool) -> None:
        self.setProperty("selectedRow", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            row = self.list_widget.row(self.item)
            if row >= 0:
                if event.modifiers() & Qt.ControlModifier:
                    self.item.setSelected(not self.item.isSelected())
                    self.list_widget.setCurrentRow(row)
                else:
                    self.list_widget.setCurrentItem(self.item)
            event.accept()
            return
        super().mousePressEvent(event)


class DownloadQueueCell(QWidget):
    """Single, contained thumbnail/title cell for the activity table.

    The QTableWidgetItem in column 0 is intentionally kept text-empty and is
    used only for row selection/task identity. All visible title text belongs
    to this widget, preventing Qt from painting the same title underneath it.
    """

    THUMBNAIL_SIZE = QSize(96, 54)

    def __init__(self, title: str, placeholder_label: str = "VIDEO"):
        super().__init__()
        self.setObjectName("downloadQueueCell")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setToolTip(title)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 10, 4)
        row.setSpacing(10)

        self.thumbnail = QLabel()
        self.thumbnail.setObjectName("queueThumbnail")
        self.thumbnail.setFixedSize(self.THUMBNAIL_SIZE)
        self.thumbnail.setAlignment(Qt.AlignCenter)
        self.thumbnail.setPixmap(_placeholder_pixmap(self.THUMBNAIL_SIZE, placeholder_label))
        self.thumbnail.setStyleSheet(
            "background:#172033; border:1px solid #303d55; border-radius:7px;"
        )
        self.thumbnail.setScaledContents(False)
        self.thumbnail.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        row.addWidget(self.thumbnail, 0, Qt.AlignVCenter)

        # A real QWidget container gives the labels a measurable, shrinkable
        # width. Adding a bare nested layout can otherwise retain a large
        # size hint and make long titles push into the thumbnail/neighbor cells.
        details_host = QWidget(self)
        details_host.setObjectName("queueTextContainer")
        details_host.setMinimumWidth(0)
        details_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        details = QVBoxLayout(details_host)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(4)

        self.title_label = ElidedLabel(title)
        self.title_label.setObjectName("queueFileTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setMinimumWidth(0)
        self.title_label.setFixedHeight(20)
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.title_label.setToolTip(title)
        details.addWidget(self.title_label, 0)

        self.subtitle_label = ElidedLabel("Esperando información del video…")
        self.subtitle_label.setObjectName("queueFileSubtitle")
        self.subtitle_label.setWordWrap(False)
        self.subtitle_label.setMinimumWidth(0)
        self.subtitle_label.setFixedHeight(18)
        self.subtitle_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        details.addWidget(self.subtitle_label, 0)

        row.addWidget(details_host, 1, Qt.AlignVCenter)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)
        self.title_label.setToolTip(title)
        self.setToolTip(title)

    def set_subtitle(self, subtitle: str) -> None:
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setToolTip(subtitle)

    def set_thumbnail_bytes(self, data: bytes) -> None:
        if not data:
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            cropped = _center_crop_pixmap(pixmap, self.THUMBNAIL_SIZE)
            if not cropped.isNull():
                self.thumbnail.setPixmap(cropped)



def convert_media(
    source: Path,
    destination: Path,
    output_format: str,
    progress_callback: Callable[[int | None, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    resolution: str = "Original",
    quality: str = "Equilibrada",
    fat32_mode: bool = False,
    audio_bitrate_kbps: int | None = None,
) -> None:
    """Convert with selectable resolution/quality and an optional FAT32-aware two-pass encode.

    Normal mode uses CRF/quantizer quality levels. FAT32 mode uses two-pass
    bitrate targeting, calculated from source duration, so the resulting file
    aims to remain below a conservative per-file size. The target is an estimate,
    not a mathematical guarantee; the completed file size is checked afterward.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("No encuentro FFmpeg. Instálalo y vuelve a abrir MediaFlow.")
    if not source.is_file():
        raise FileNotFoundError(f"No encuentro el archivo de origen: {source}")

    source = source.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fmt = output_format.lower()
    quality = quality if quality in VIDEO_QUALITY_SETTINGS else "Equilibrada"
    quality_settings = VIDEO_QUALITY_SETTINGS[quality]
    duration = _probe_duration(source)
    is_audio_output = fmt in {value.lower() for value in AUDIO_OUTPUT_FORMATS}
    use_fat32_target = bool(fat32_mode and not is_audio_output)

    base = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(source)]
    progress_args = ["-progress", "pipe:1", "-stats_period", "1", "-nostats"]
    audio_bitrate = int(quality_settings["audio_kbps"])

    selected_audio_bitrate = max(32, min(512, int(audio_bitrate_kbps or audio_bitrate)))
    if is_audio_output:
        video_args: list[str] = ["-map", "0:a:0", "-map_metadata", "0"]
        if fmt in ("mp3", "flac", "m4a"):
            video_args += ["-map", "0:v:m:attached_pic?"]
        format_args: list[str] = []
        if fmt == "mp3":
            audio_args = ["-c:a", "libmp3lame", "-b:a", f"{selected_audio_bitrate}k", "-c:v", "copy", "-id3v2_version", "3"]
        elif fmt == "flac":
            audio_args = ["-c:a", "flac", "-compression_level", "8", "-c:v", "copy"]
        elif fmt == "wav":
            audio_args = ["-c:a", "pcm_s16le"]
        elif fmt == "m4a":
            audio_args = ["-c:a", "aac", "-b:a", f"{selected_audio_bitrate}k", "-c:v", "copy"]
        elif fmt == "aac":
            audio_args = ["-c:a", "aac", "-b:a", f"{selected_audio_bitrate}k"]
            format_args = ["-f", "adts"]
        elif fmt == "ogg":
            audio_args = ["-c:a", "libvorbis", "-q:a", "5"]
        elif fmt == "opus":
            audio_args = ["-c:a", "libopus", "-b:a", f"{selected_audio_bitrate}k"]
    elif fmt in ("mp4", "mkv", "mpg", "avi"):
        video_args = ["-map", "0:v:0", "-sn", "-dn", "-threads", "0"]
        audio_args = ["-map", "0:a:0?", "-c:a"]
        if fmt in ("mp4", "mkv"):
            video_args += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
            audio_args += ["aac", "-b:a", f"{audio_bitrate}k"]
            format_args = ["-movflags", "+faststart"] if fmt == "mp4" else ["-f", "matroska"]
        elif fmt == "mpg":
            video_args += ["-c:v", "mpeg2video", "-pix_fmt", "yuv420p"]
            audio_args += ["mp2", "-b:a", f"{audio_bitrate}k"]
            format_args = ["-f", "mpeg"]
        else:  # AVI
            video_args += ["-c:v", "mpeg4", "-pix_fmt", "yuv420p"]
            audio_args += ["libmp3lame", "-b:a", f"{audio_bitrate}k"]
            format_args = ["-f", "avi"]
    else:
        raise ValueError("Formato de salida no admitido.")

    if not is_audio_output and resolution != "Original":
        try:
            max_height = int(resolution.lower().replace("p", ""))
        except ValueError:
            max_height = 0
        if max_height in (1080, 720, 480, 360):
            # Keep aspect ratio and never upscale a source smaller than the selected cap.
            video_args += ["-vf", f"scale=-2:min({max_height}\\,ih)"]

    # Normal quality mode: CRF for H.264, quantizer for MPEG-2/MPEG-4.
    if not is_audio_output:
        if fmt in ("mp4", "mkv"):
            video_quality_args = ["-crf", str(quality_settings["crf"])]
        elif fmt in ("mpg", "avi"):
            video_quality_args = ["-q:v", str(quality_settings["mpeg_q"])]
        else:
            video_quality_args = []
    else:
        video_quality_args = []

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if os.name == "nt":
        creationflags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)

    stderr_file = tempfile.TemporaryFile(mode="w+b")
    process = None
    started = time.monotonic()
    last_seconds = 0.0

    def run_stage(command: list[str], stage_name: str, offset: int, span: int) -> None:
        nonlocal process, last_seconds
        stderr_file.seek(0)
        stderr_file.truncate(0)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        current_block: dict[str, str] = {}
        assert process.stdout is not None
        for raw_line in process.stdout:
            if cancel_check is not None and cancel_check():
                raise OperationCancelled("Conversión cancelada por el usuario.")
            line = raw_line.strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            current_block[key] = value
            if key == "progress":
                raw_time = current_block.get("out_time_us") or current_block.get("out_time_ms")
                if raw_time and raw_time not in ("N/A", "-1"):
                    try:
                        last_seconds = max(0.0, int(raw_time) / 1_000_000)
                    except ValueError:
                        pass
                elif current_block.get("out_time"):
                    try:
                        hh, mm, ss = current_block["out_time"].split(":")
                        last_seconds = int(hh) * 3600 + int(mm) * 60 + float(ss)
                    except (ValueError, TypeError):
                        pass

                if progress_callback:
                    if duration:
                        fraction = min(1.0, max(0.0, last_seconds / duration))
                        percent = min(99, max(0, offset + int(span * fraction)))
                        detail = f"{_format_clock(last_seconds)} de {_format_clock(duration)}"
                        label = f"{stage_name} · {detail}"
                    else:
                        percent = None
                        elapsed = int(time.monotonic() - started)
                        label = f"{stage_name} · {int(elapsed)} s transcurridos"
                    if value == "end":
                        percent = offset + span
                        label = f"{stage_name} · etapa finalizada"
                    progress_callback(percent, label)
                current_block.clear()

        return_code = process.wait()
        if cancel_check is not None and cancel_check():
            raise OperationCancelled("Conversión cancelada por el usuario.")
        if return_code != 0:
            stderr_file.flush()
            stderr_file.seek(max(0, stderr_file.tell() - 12000))
            details = stderr_file.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                (details[-5000:] + f"\\nArchivo de origen: {source}\\nArchivo de salida: {command[-1]}")
                if details else f"FFmpeg terminó con código {return_code}.\\nOrigen: {source}\\nSalida: {command[-1]}"
            )

    try:
        if use_fat32_target:
            if not duration or duration <= 0:
                raise RuntimeError(
                    "No pude detectar la duración del video para calcular el tamaño FAT32. "
                    "Desactiva la optimización FAT32 o vuelve a comprobar el archivo."
                )
            if is_audio_output:
                raise RuntimeError("La optimización FAT32 no se aplica a archivos de audio.")

            target_gib = float(quality_settings["fat32_gib"])
            target_bytes = int(target_gib * (1024 ** 3))
            # Keep additional headroom for container overhead and rate-control variance.
            total_budget_bps = int((target_bytes * 8 / duration) * 0.94)
            audio_bps = audio_bitrate * 1000
            video_bps = total_budget_bps - audio_bps
            max_video_rate = {"mp4": 40_000_000, "mkv": 40_000_000, "mpg": 15_000_000, "avi": 20_000_000}[fmt]
            video_bps = min(video_bps, max_video_rate)
            if video_bps < 150_000:
                raise RuntimeError(
                    "El video es demasiado largo para el objetivo FAT32 con este perfil. "
                    "Prueba 360p o 'Muy compacta', o divide el video en partes."
                )
            peak_rate = min(max_video_rate, max(video_bps + 150_000, int(video_bps * 1.20)))
            bitrate_args = [
                "-b:v", str(video_bps),
                "-maxrate", str(peak_rate),
                "-bufsize", str(max(video_bps * 2, 1_000_000)),
            ]
            with tempfile.TemporaryDirectory(prefix="mediaflow-fat32-") as temp_dir:
                passlog = str(Path(temp_dir) / "mediaflow-pass")
                first_pass = (
                    base + video_args + bitrate_args
                    + ["-pass", "1", "-passlogfile", passlog, "-an"]
                    + progress_args + ["-f", "null", os.devnull]
                )
                second_pass = (
                    base + video_args + bitrate_args
                    + ["-pass", "2", "-passlogfile", passlog]
                    + audio_args + ["-max_muxing_queue_size", "4096"]
                    + format_args + progress_args + [str(destination)]
                )
                run_stage(first_pass, "Pasada 1/2 · analizando video", 0, 45)
                run_stage(second_pass, "Pasada 2/2 · creando archivo", 45, 55)
        else:
            command = (
                base + video_args + video_quality_args + audio_args
                + ["-max_muxing_queue_size", "4096"] + format_args
                + progress_args + [str(destination)]
            )
            run_stage(command, "Convirtiendo", 0, 100)

        if cancel_check is not None and cancel_check():
            raise OperationCancelled("Conversión cancelada por el usuario.")
        if not destination.is_file() or destination.stat().st_size == 0:
            raise RuntimeError("FFmpeg terminó, pero no generó un archivo de salida válido.")
        if progress_callback:
            if use_fat32_target:
                actual_size = destination.stat().st_size
                if actual_size > FAT32_MAX_FILE_BYTES:
                    progress_callback(100, f"Conversión terminada, pero {human_file_size(actual_size)} supera el límite FAT32.")
                else:
                    progress_callback(100, f"Conversión completada · {human_file_size(actual_size)} · compatible con FAT32.")
            else:
                progress_callback(100, f"Conversión completada · {human_file_size(destination.stat().st_size)}")
    except Exception:
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=4)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=4)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        try:
            if destination.exists():
                destination.unlink()
        except OSError:
            pass
        raise
    finally:
        stderr_file.close()


class DropTarget(QWidget):
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime.hasUrls() and any(url.isLocalFile() for url in mime.urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class FolderScanWorker(QThread):
    found = Signal(list)
    scanError = Signal(str)

    def __init__(self, roots: list[Path], recursive: bool = True):
        super().__init__()
        self.roots = roots
        self.recursive = recursive

    def run(self) -> None:
        found: list[str] = []
        seen: set[str] = set()
        errors: list[str] = []
        for root in self.roots:
            try:
                if root.is_file():
                    candidates = [root]
                elif root.is_dir():
                    candidates = root.rglob("*") if self.recursive else root.iterdir()
                else:
                    continue
                for candidate in candidates:
                    try:
                        if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTENSIONS:
                            key = str(candidate.resolve()).casefold()
                            if key not in seen:
                                seen.add(key)
                                found.append(str(candidate))
                    except (OSError, PermissionError):
                        continue
            except (OSError, PermissionError) as exc:
                errors.append(f"{root}: {exc}")
        self.found.emit(found)
        if errors:
            self.scanError.emit("\n".join(errors[:5]))


class DownloadWorker(QThread):
    metadata = Signal(str, str, bytes)
    progress = Signal(str, int, str, str, str)
    succeeded = Signal(str, str)
    failed = Signal(str, str)
    cancelled = Signal(str, str)

    def __init__(self, task: dict, output_dir: Path, converted_dir: Path):
        super().__init__()
        self.task = task
        self.output_dir = output_dir
        self.converted_dir = converted_dir

    def _progress_hook(self, data: dict) -> None:
        if self.isInterruptionRequested():
            raise OperationCancelled("Descarga cancelada por el usuario.")
        task_id = self.task["id"]
        if data.get("status") == "downloading":
            downloaded = data.get("downloaded_bytes", 0) or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            percent = int(downloaded * 100 / total) if total else 0
            self.progress.emit(
                task_id,
                max(0, min(99, percent)),
                human_speed(data.get("speed")),
                human_eta(data.get("eta")),
                "Descargando",
            )
        elif data.get("status") == "finished":
            self.progress.emit(task_id, 100, "—", "—", "Preparando archivo")

    def run(self) -> None:
        task_id = self.task["id"]
        source: Path | None = None
        try:
            # yt-dlp enables Deno by default for YouTube's JavaScript challenge
            # solver. Add WinGet's per-user install folder to this process PATH,
            # because the installer may have installed it moments ago.
            deno_path = find_deno()
            if deno_path:
                deno_dir = str(Path(deno_path).parent)
                current_path = os.environ.get("PATH", "")
                if deno_dir.lower() not in current_path.lower().split(os.pathsep):
                    os.environ["PATH"] = deno_dir + os.pathsep + current_path

            from yt_dlp import YoutubeDL

            self.output_dir.mkdir(parents=True, exist_ok=True)
            quality = self.task["quality"]
            output_format = self.task["output_format"].lower()
            auto_convert = self.task["auto_convert"]
            if quality == "Solo audio" or output_format == "mp3":
                format_selector = "bestaudio/best"
            else:
                format_selector = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["Mejor disponible"])

            merge_format = "mkv" if auto_convert else output_format
            options = {
                "format": format_selector,
                "outtmpl": str(self.output_dir / "%(title).160B [%(id)s].%(ext)s"),
                "noplaylist": True,
                "windowsfilenames": True,
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [self._progress_hook],
                "merge_output_format": merge_format if merge_format in ("mp4", "mkv") else "mkv",
                "retries": 3,
                "fragment_retries": 3,
                "socket_timeout": 30,
            }
            if self.task["rate_kbps"] > 0:
                options["ratelimit"] = self.task["rate_kbps"] * 1024
            ffmpeg_path = find_ffmpeg()
            if ffmpeg_path:
                options["ffmpeg_location"] = str(Path(ffmpeg_path).parent)

            with YoutubeDL(options) as ydl:
                # Reuse the preview metadata when it has already been fetched
                # for the queue thumbnail. If the user starts immediately,
                # fall back to the normal extraction path.
                info = self.task.pop("preview_info", None)
                if not isinstance(info, dict):
                    info = ydl.extract_info(self.task["url"], download=False)
                if self.isInterruptionRequested():
                    raise OperationCancelled("Descarga cancelada por el usuario.")
                if not isinstance(info, dict):
                    raise RuntimeError("El sitio no devolvió información válida del contenido.")
                title = str(info.get("title") or self.task["url"])
                self.task["media_id"] = str(info.get("id") or "")
                if title:
                    thumbnail_bytes = self.task.get("preview_thumbnail", b"")
                    if not thumbnail_bytes:
                        thumbnail_bytes = DownloadPreviewWorker._thumbnail_bytes(info, ydl)
                    self.metadata.emit(task_id, title, thumbnail_bytes or b"")
                if self.isInterruptionRequested():
                    raise OperationCancelled("Descarga cancelada por el usuario.")
                result_info = ydl.process_ie_result(info, download=True)
                prepared = Path(ydl.prepare_filename(result_info))

            if self.isInterruptionRequested():
                raise OperationCancelled("Descarga cancelada por el usuario.")
            source = self._find_downloaded_file(result_info, prepared, self.output_dir)
            if source is None:
                raise RuntimeError(f"No localicé el archivo descargado en: {self.output_dir}")

            if auto_convert:
                destination = unique_output_path(self.converted_dir, source.stem, output_format)
                self.progress.emit(task_id, 0, "FFmpeg", "—", f"Convirtiendo a {output_format.upper()}")
                def report_conversion(percent: int | None, detail: str) -> None:
                    shown = 0 if percent is None else percent
                    self.progress.emit(task_id, shown, "FFmpeg", "—", f"Convirtiendo · {detail}")
                convert_media(
                    source, destination, output_format, report_conversion,
                    cancel_check=self.isInterruptionRequested,
                )
                final_path = destination
            else:
                final_path = source

            if self.isInterruptionRequested():
                raise OperationCancelled("Proceso cancelado por el usuario.")
            self.succeeded.emit(task_id, str(final_path))
        except Exception as exc:
            if self.isInterruptionRequested() or isinstance(exc, OperationCancelled):
                self._remove_partial_downloads()
                source_note = (
                    " El video original descargado se conserva en Descargados."
                    if self.task.get("auto_convert") and source is not None and source.is_file()
                    else ""
                )
                self.cancelled.emit(task_id, "Proceso cancelado por el usuario." + source_note)
            else:
                self.failed.emit(task_id, str(exc))

    def _remove_partial_downloads(self) -> None:
        """Remove only temporary fragments created for this task; keep completed source files."""
        media_id = str(self.task.get("media_id") or "")
        # When extraction was interrupted before metadata was available, do not
        # attempt a broad folder cleanup: it could remove another download.
        if not media_id:
            return
        try:
            for candidate in self.output_dir.iterdir():
                name = candidate.name
                if f"[{media_id}]" not in name:
                    continue
                lower = name.lower()
                if candidate.is_file() and (lower.endswith((".part", ".ytdl", ".temp")) or ".part-frag" in lower):
                    try:
                        candidate.unlink()
                    except OSError:
                        pass
        except OSError:
            pass

    @staticmethod
    def _find_downloaded_file(info: dict, prepared_path: Path, output_dir: Path) -> Path | None:
        candidates: list[Path] = [
            prepared_path,
            prepared_path.with_suffix(".mkv"),
            prepared_path.with_suffix(".webm"),
            prepared_path.with_suffix(".mp4"),
        ]
        for key in ("filepath", "_filename"):
            value = info.get(key)
            if value:
                candidates.append(Path(value))
        for item in info.get("requested_downloads") or []:
            if isinstance(item, dict):
                for key in ("filepath", "_filename"):
                    value = item.get(key)
                    if value:
                        candidates.append(Path(value))
        for path in reversed(candidates):
            if path.is_file():
                return path
        media_id = info.get("id")
        if media_id:
            matches = sorted(
                output_dir.glob(f"*{media_id}*"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for path in matches:
                if path.is_file() and not path.name.endswith((".part", ".ytdl")):
                    return path
        return None


class ThumbnailWorker(QThread):
    """Create cached still-frame previews for local video files off the UI thread."""
    thumbnailReady = Signal(str, str)

    AUDIO_ONLY_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}

    def __init__(self, sources: list[Path]):
        super().__init__()
        self.sources = list(sources)

    def run(self) -> None:
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return
        try:
            cache_dir = _thumbnail_cache_directory()
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        for source in self.sources:
            if self.isInterruptionRequested():
                break
            try:
                if source.suffix.lower() in self.AUDIO_ONLY_EXTENSIONS or not source.is_file():
                    continue
                stat = source.stat()
                identity = f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
                digest = hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:24]
                thumbnail = cache_dir / f"{digest}.jpg"
                if thumbnail.is_file() and thumbnail.stat().st_size > 0:
                    self.thumbnailReady.emit(str(source), str(thumbnail))
                    continue

                temp_thumbnail = cache_dir / f"{digest}.tmp.jpg"
                generated = False
                # Fast input seeking is suitable for long files. Retry at the
                # beginning for clips shorter than the first seek position.
                for seek_seconds in ("2", "0"):
                    if self.isInterruptionRequested():
                        break
                    command = [
                        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-ss", seek_seconds, "-i", str(source), "-an", "-frames:v", "1",
                        "-vf", "scale=144:81:force_original_aspect_ratio=decrease,"
                        "pad=144:81:(ow-iw)/2:(oh-ih)/2",
                        "-q:v", "5", str(temp_thumbnail),
                    ]
                    try:
                        result = subprocess.run(
                            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=12, check=False, creationflags=creationflags,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        continue
                    if result.returncode == 0 and temp_thumbnail.is_file() and temp_thumbnail.stat().st_size > 0:
                        try:
                            temp_thumbnail.replace(thumbnail)
                            generated = True
                            break
                        except OSError:
                            pass
                try:
                    if temp_thumbnail.exists():
                        temp_thumbnail.unlink()
                except OSError:
                    pass
                if generated:
                    self.thumbnailReady.emit(str(source), str(thumbnail))
            except (OSError, PermissionError, ValueError):
                continue




class PlaylistSelectionDialog(QDialog):
    """Let the user choose individual entries from a detected playlist."""

    def __init__(self, entries: list[dict], selected_video_id: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Seleccionar videos de la lista")
        self.setMinimumSize(680, 520)
        self.entries = [entry for entry in entries if isinstance(entry, dict)]
        layout = QVBoxLayout(self)
        heading = QLabel("Se detectó una lista de reproducción")
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)
        note = QLabel("El video del enlace aparece marcado inicialmente. Marca los demás videos que quieras agregar a la cola.")
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        actions = QHBoxLayout()
        select_all = QPushButton("Seleccionar todos")
        select_none = QPushButton("Desmarcar todos")
        actions.addWidget(select_all)
        actions.addWidget(select_none)
        actions.addStretch(1)
        self.count_label = QLabel()
        self.count_label.setObjectName("countPill")
        actions.addWidget(self.count_label)
        layout.addLayout(actions)

        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(112, 63))
        self.list_widget.setSpacing(3)
        layout.addWidget(self.list_widget, 1)
        first_checked = False
        for entry in self.entries:
            title = str(entry.get("title") or entry.get("id") or "Video sin título")
            duration = _format_clock(entry.get("duration"))
            item = QListWidgetItem(title + "   ·   " + duration)
            item.setToolTip(str(entry.get("webpage_url") or entry.get("url") or title))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            entry_id = str(entry.get("id") or "")
            is_current = bool(selected_video_id and entry_id == selected_video_id)
            if is_current and not first_checked:
                item.setCheckState(Qt.Checked)
                first_checked = True
            else:
                item.setCheckState(Qt.Unchecked)
            thumb = entry.get("_mediaflow_thumbnail")
            if isinstance(thumb, bytes) and thumb:
                pixmap = QPixmap()
                if pixmap.loadFromData(thumb):
                    item.setIcon(QIcon(_center_crop_pixmap(pixmap, QSize(112, 63))))
            self.list_widget.addItem(item)
        if self.entries and not first_checked:
            self.list_widget.item(0).setCheckState(Qt.Checked)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancelar")
        accept = QPushButton("Agregar seleccionados")
        accept.setObjectName("primaryButton")
        buttons.addWidget(cancel)
        buttons.addWidget(accept)
        layout.addLayout(buttons)
        select_all.clicked.connect(lambda: self._set_all(Qt.Checked))
        select_none.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        cancel.clicked.connect(self.reject)
        accept.clicked.connect(self.accept)
        self.list_widget.itemChanged.connect(self._update_count)
        self._update_count()

    def _set_all(self, state) -> None:
        for index in range(self.list_widget.count()):
            self.list_widget.item(index).setCheckState(state)

    def _update_count(self, *_args) -> None:
        selected = sum(
            self.list_widget.item(index).checkState() == Qt.Checked
            for index in range(self.list_widget.count())
        )
        self.count_label.setText(f"{selected} seleccionados")

    def selected_entries(self) -> list[dict]:
        return [
            self.entries[index]
            for index in range(min(len(self.entries), self.list_widget.count()))
            if self.list_widget.item(index).checkState() == Qt.Checked
        ]




class AudioCoverWorker(QThread):
    """Extract embedded album artwork without blocking the music workspace."""
    coverReady = Signal(str, bytes)

    def __init__(self, sources: list[Path]):
        super().__init__()
        self.sources = list(sources)

    def run(self) -> None:
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return
        cache_dir = _thumbnail_cache_directory()
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        for source in self.sources:
            if self.isInterruptionRequested():
                break
            try:
                stat = source.stat()
                identity = f"audio-cover|{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
                digest = hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:24]
                cover = cache_dir / f"{digest}.jpg"
                if not cover.is_file():
                    result = subprocess.run(
                        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                         "-map", "0:v:0", "-frames:v", "1", "-q:v", "3", str(cover)],
                        capture_output=True, timeout=20,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    if result.returncode != 0 or not cover.is_file() or cover.stat().st_size == 0:
                        cover.unlink(missing_ok=True)
                        continue
                data = cover.read_bytes()
                if data:
                    self.coverReady.emit(str(source), data)
            except (OSError, subprocess.SubprocessError):
                continue


class DownloadPreviewWorker(QThread):
    """Fetch video title and thumbnail before a queued download starts."""
    ready = Signal(str, str, bytes, object)
    failed = Signal(str, str)

    def __init__(self, task_id: str, url: str):
        super().__init__()
        self.task_id = task_id
        self.url = url

    @staticmethod
    def _thumbnail_bytes(info: dict, ydl=None) -> bytes:
        candidates: list[str] = []
        primary = info.get("thumbnail")
        if isinstance(primary, str) and primary:
            candidates.append(primary)
        thumbnails = [
            item for item in (info.get("thumbnails") or [])
            if isinstance(item, dict) and isinstance(item.get("url"), str) and item["url"]
        ]
        thumbnails.sort(
            key=lambda item: (
                int(item.get("preference") or 0),
                int(item.get("width") or 0) * int(item.get("height") or 0),
            ),
            reverse=True,
        )
        candidates.extend(item["url"] for item in thumbnails)
        seen: set[str] = set()
        for thumb_url in candidates:
            if thumb_url in seen:
                continue
            seen.add(thumb_url)
            try:
                request = urllib.request.Request(
                    thumb_url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"},
                )
                if ydl is not None:
                    # yt-dlp's opener uses its own configured socket timeout.
                    with ydl.urlopen(request) as response:
                        data = response.read(4 * 1024 * 1024 + 1)
                else:
                    with urllib.request.urlopen(request, timeout=15) as response:
                        data = response.read(4 * 1024 * 1024 + 1)
                if data and len(data) <= 4 * 1024 * 1024:
                    return data
            except Exception:
                continue
        return b""

    def run(self) -> None:
        try:
            deno_path = find_deno()
            if deno_path:
                deno_dir = str(Path(deno_path).parent)
                current_path = os.environ.get("PATH", "")
                if deno_dir.lower() not in current_path.lower().split(os.pathsep):
                    os.environ["PATH"] = deno_dir + os.pathsep + current_path
            from yt_dlp import YoutubeDL

            options = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": False,
                "skip_download": True,
                "cachedir": False,
                "socket_timeout": 25,
                "retries": 2,
                "extractor_retries": 3,
                "file_access_retries": 2,
                "http_headers": {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
                    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
                },
            }
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(self.url, download=False)
                if self.isInterruptionRequested():
                    return
                if not isinstance(info, dict):
                    raise RuntimeError("YouTube no devolvió información del video. Comprueba que el enlace sea público y válido.")
                if info.get("_type") == "playlist":
                    entries = [entry for entry in (info.get("entries") or []) if isinstance(entry, dict)]
                    # Hydrate entries that yt-dlp returned as flat playlist items.
                    hydrated: list[dict] = []
                    for entry in entries[:60]:
                        if self.isInterruptionRequested():
                            return
                        current = entry
                        if not current.get("title") or not current.get("thumbnail"):
                            entry_url = current.get("webpage_url") or current.get("url")
                            if entry_url and str(entry_url).startswith(("http://", "https://")):
                                try:
                                    detailed = ydl.extract_info(str(entry_url), download=False)
                                    if isinstance(detailed, dict):
                                        current = {**current, **detailed}
                                except Exception:
                                    pass
                        current["_mediaflow_thumbnail"] = self._thumbnail_bytes(current, ydl)
                        hydrated.append(current)
                    info["entries"] = hydrated + entries[len(hydrated):]
                    title = str(info.get("title") or "Lista de reproducción")
                    thumb_data = b""
                else:
                    title = str(info.get("title") or info.get("id") or self.url)
                    thumb_data = self._thumbnail_bytes(info, ydl)
            if self.isInterruptionRequested():
                return
            self.ready.emit(self.task_id, title, thumb_data, info)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(self.task_id, f"No se pudo analizar el enlace de YouTube: {exc}")


class MusicUrlDownloadWorker(QThread):
    progress = Signal(int, str)
    succeeded = Signal(str)
    failed = Signal(str)
    cancelled = Signal(str)

    def __init__(self, url: str, output_dir: Path, output_format: str, bitrate: int):
        super().__init__()
        self.url, self.output_dir = url, output_dir
        self.output_format, self.bitrate = output_format.lower(), int(bitrate)

    def _progress_hook(self, data: dict) -> None:
        if self.isInterruptionRequested():
            raise OperationCancelled("Descarga cancelada por el usuario.")
        if data.get("status") == "downloading":
            downloaded = data.get("downloaded_bytes", 0) or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            pct = int(downloaded * 75 / total) if total else 5
            self.progress.emit(max(0, min(75, pct)), "Descargando audio de YouTube…")
        elif data.get("status") == "finished":
            self.progress.emit(78, "Audio recibido; preparando conversión…")

    def run(self) -> None:
        temp_dir = Path(tempfile.mkdtemp(prefix="mediaflow-audio-"))
        source = None
        try:
            deno = find_deno()
            if deno:
                deno_dir = str(Path(deno).parent)
                current = os.environ.get("PATH", "")
                if deno_dir.lower() not in current.lower().split(os.pathsep):
                    os.environ["PATH"] = deno_dir + os.pathsep + current
            from yt_dlp import YoutubeDL
            self.output_dir.mkdir(parents=True, exist_ok=True)
            temp_dir.mkdir(parents=True, exist_ok=True)
            options = {
                "format": "bestaudio/best",
                "outtmpl": str(temp_dir / "%(title).150B [%(id)s].%(ext)s"),
                "noplaylist": True, "windowsfilenames": True,
                "quiet": True, "no_warnings": True,
                "progress_hooks": [self._progress_hook],
                "retries": 3, "fragment_retries": 3, "socket_timeout": 30,
            }
            ffmpeg = find_ffmpeg()
            if ffmpeg:
                options["ffmpeg_location"] = str(Path(ffmpeg).parent)
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(self.url, download=True)
                if self.isInterruptionRequested():
                    raise OperationCancelled("Descarga cancelada.")
                if not isinstance(info, dict):
                    raise RuntimeError("YouTube no devolvió información válida.")
                prepared = Path(ydl.prepare_filename(info))
                candidates = [prepared] + [prepared.with_suffix(ext) for ext in (".webm", ".m4a", ".mp4", ".opus", ".mp3")]
                vid = str(info.get("id") or "")
                if vid:
                    candidates += [p for p in temp_dir.glob(f"*[{vid}]*") if p.is_file()]
                source = next((p for p in candidates if p.is_file() and p.stat().st_size), None)
                if source is None:
                    raise RuntimeError("No localicé el audio descargado.")
                title = str(info.get("title") or source.stem)
            if self.isInterruptionRequested():
                raise OperationCancelled("Descarga cancelada.")
            destination = unique_output_path(self.output_dir, title, self.output_format)
            self.progress.emit(80, f"Convirtiendo a {self.output_format.upper()} · {self.bitrate} kbps…")
            def report(pct, detail):
                shown = 80 if pct is None else 80 + int(max(0, min(100, pct)) * .19)
                self.progress.emit(min(99, shown), f"Convirtiendo audio · {detail}")
            convert_media(source, destination, self.output_format, report,
                          cancel_check=self.isInterruptionRequested,
                          audio_bitrate_kbps=self.bitrate)
            try:
                source.unlink()
            except OSError:
                pass
            self.progress.emit(100, "Descarga y conversión completadas.")
            self.succeeded.emit(str(destination))
        except Exception as exc:
            if self.isInterruptionRequested() or isinstance(exc, OperationCancelled):
                if source and source.exists():
                    try: source.unlink()
                    except OSError: pass
                self.cancelled.emit("Descarga de música cancelada.")
            else:
                self.failed.emit(str(exc))
        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except OSError:
                pass


class ConvertWorker(QThread):
    progress = Signal(int, str)
    fileProgress = Signal(str, int, str)
    succeeded = Signal(str)
    failed = Signal(str)
    cancelled = Signal(str)
    fileCancelled = Signal(str)
    fileSucceeded = Signal(str, str)
    fileFailed = Signal(str, str)

    def __init__(self, jobs: list[tuple[Path, str, str, str, bool]], output_dir: Path, audio_bitrate_kbps: int | None = None):
        super().__init__()
        self.jobs = [
            (Path(source), str(output_format).lower(), str(resolution), str(quality), bool(fat32_mode))
            for source, output_format, resolution, quality, fat32_mode in jobs
        ]
        self.output_dir = output_dir
        self.audio_bitrate_kbps = audio_bitrate_kbps
        self._cancel_lock = threading.Lock()
        self._cancelled_paths: set[str] = set()
        self._finished_paths: set[str] = set()
        self._current_source_key: str | None = None
        self._cancel_current_event = threading.Event()

    @staticmethod
    def _path_key(source: Path) -> str:
        try:
            return os.path.normcase(str(source.resolve()))
        except OSError:
            return os.path.normcase(str(source.absolute()))

    def cancel_paths(self, paths: list[Path]) -> int:
        """Cancel only selected files; other items in the conversion batch continue."""
        keys = {self._path_key(path) for path in paths}
        with self._cancel_lock:
            new_keys = keys - self._finished_paths
            self._cancelled_paths.update(new_keys)
            if self._current_source_key in new_keys:
                self._cancel_current_event.set()
            return len(new_keys)

    def _is_path_cancelled(self, source: Path) -> bool:
        key = self._path_key(source)
        with self._cancel_lock:
            return key in self._cancelled_paths or (
                self._current_source_key == key and self._cancel_current_event.is_set()
            )

    def _mark_path_finished(self, source: Path) -> None:
        key = self._path_key(source)
        with self._cancel_lock:
            self._finished_paths.add(key)
            if self._current_source_key == key:
                self._current_source_key = None
                self._cancel_current_event.clear()

    def run(self) -> None:
        errors: list[str] = []
        results: list[str] = []
        total = max(len(self.jobs), 1)
        was_cancelled_all = False
        for index, (source, output_format, resolution, quality, fat32_mode) in enumerate(self.jobs, start=1):
            if self.isInterruptionRequested():
                was_cancelled_all = True
                break

            key = self._path_key(source)
            with self._cancel_lock:
                self._current_source_key = key
                self._cancel_current_event.clear()
                already_cancelled = key in self._cancelled_paths
            if already_cancelled:
                self.fileCancelled.emit(str(source))
                self._mark_path_finished(source)
                self.progress.emit(int(index * 100 / total), f"Archivo omitido por cancelación: {source.name}")
                continue

            self.progress.emit(int((index - 1) * 100 / total), f"Preparando {index} de {total}: {source.name}")
            try:
                destination = unique_output_path(self.output_dir, source.stem, output_format)

                def report_file_progress(percent: int | None, detail: str) -> None:
                    overall = int((index - 1) * 100 / total) if percent is None else int(((index - 1) + (percent / 100)) * 100 / total)
                    shown = min(99, max(0, int(percent or 0)))
                    self.fileProgress.emit(str(source), shown, detail)
                    self.progress.emit(
                        min(99, max(0, overall)),
                        f"Archivo {index}/{total}: {source.name} · {detail}",
                    )

                convert_media(
                    source, destination, output_format, report_file_progress,
                    cancel_check=lambda: self.isInterruptionRequested() or self._is_path_cancelled(source),
                    resolution=resolution,
                    quality=quality,
                    fat32_mode=fat32_mode,
                    audio_bitrate_kbps=self.audio_bitrate_kbps,
                )
                results.append(str(destination))
                self.fileSucceeded.emit(str(source), str(destination))
                self._mark_path_finished(source)
            except OperationCancelled:
                self._mark_path_finished(source)
                if self.isInterruptionRequested():
                    was_cancelled_all = True
                    break
                self.fileCancelled.emit(str(source))
                continue
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")
                self.fileFailed.emit(str(source), str(exc))
                self._mark_path_finished(source)

            if self.isInterruptionRequested():
                was_cancelled_all = True
                break
            self.progress.emit(int(index * 100 / total), f"Procesados {index} de {total}")

        self.succeeded.emit("\n".join(results))
        if errors:
            self.failed.emit("\n\n".join(errors[:8]))
        if was_cancelled_all or self.isInterruptionRequested():
            completed = len(results)
            failed_count = len(errors)
            remaining = max(0, len(self.jobs) - completed - failed_count)
            self.cancelled.emit(
                f"Lote cancelado. Convertidos: {completed}; con error: {failed_count}; "
                f"no procesados: {remaining}. Los archivos terminados se conservaron."
            )


class MediaFlowWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"MediaFlow {APP_VERSION}")
        self.setMinimumSize(1080, 720)
        self.resize(1380, 900)
        self.tasks: dict[str, dict] = {}
        self.task_rows: dict[str, int] = {}
        self.download_cells: dict[str, DownloadQueueCell] = {}
        self.download_format_editors: dict[str, QComboBox] = {}
        self.download_progress_bars: dict[str, QProgressBar] = {}
        self.active_worker: DownloadWorker | None = None
        self.preview_worker: DownloadPreviewWorker | None = None
        self.preview_queue: list[str] = []
        self.download_queue_started = False
        self.conversion_worker: ConvertWorker | None = None
        self.music_worker: ConvertWorker | None = None
        self.music_download_worker: MusicUrlDownloadWorker | None = None
        self.music_files: list[Path] = []
        self.music_items_by_path: dict[str, QListWidgetItem] = {}
        self.music_cover_worker: AudioCoverWorker | None = None
        self.music_cover_pending: list[Path] = []
        self.folder_scan_worker: FolderScanWorker | None = None
        self.thumbnail_worker: ThumbnailWorker | None = None
        self.thumbnail_pending: list[Path] = []
        self.file_items_by_path: dict[str, QListWidgetItem] = {}
        self.conversion_rows_by_path: dict[str, ConversionRowWidget] = {}
        self.selected_files: list[Path] = []

        # GitHub Releases updater state. Repository configuration is stored per-user
        # in QSettings and is deliberately not hard-coded into the public installer.
        self.settings = QSettings("MediaFlow", "MediaFlow")
        # The public GitHub repository is preconfigured for every new installation.
        # Existing user overrides are preserved.
        if not str(self.settings.value("updates/github_repo", "") or "").strip():
            self.settings.setValue("updates/github_repo", DEFAULT_UPDATE_REPOSITORY)
            self.settings.sync()
        self.update_check_worker = None
        self.update_download_worker = None
        self.update_progress_dialog = None
        self.latest_update_info: dict | None = None
        self.pending_update_info: dict | None = None
        self.pending_update_path: Path | None = None
        self._update_check_manual = False
        self._load_pending_update()

        DEFAULT_DOWNLOADS.mkdir(parents=True, exist_ok=True)
        DEFAULT_CONVERTED.mkdir(parents=True, exist_ok=True)
        self._build_ui()
        self._refresh_summary()
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(6 * 60 * 60 * 1000)
        self.update_timer.timeout.connect(self._maybe_auto_check_for_updates)
        self.update_timer.start()
        QTimer.singleShot(3500, self._maybe_auto_check_for_updates)

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("appRoot")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(18, 14, 18, 10)
        outer.setSpacing(9)

        # Brand/header: MediaFlow remains the product name; the visual language
        # follows the modern dark FluxConvert reference while keeping Qt workers.
        header = QHBoxLayout()
        header.setSpacing(12)
        logo = QLabel("M")
        logo.setObjectName("logoMark")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(42, 42)
        header.addWidget(logo)
        brand = QVBoxLayout()
        brand.setContentsMargins(0, 0, 0, 0)
        brand.setSpacing(2)
        title = QLabel("MediaFlow")
        title.setObjectName("appTitle")
        subtitle = QLabel("DESCARGAS Y CONVERSIÓN MULTIMEDIA")
        subtitle.setObjectName("appSubtitle")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand)
        header.addStretch(1)

        nav_group = QFrame()
        nav_group.setObjectName("navGroup")
        nav_layout = QHBoxLayout(nav_group)
        nav_layout.setContentsMargins(4, 4, 4, 4)
        nav_layout.setSpacing(3)
        self.download_nav_button = QPushButton("↓  Descargar")
        self.download_nav_button.setObjectName("navButton")
        self.download_nav_button.setCheckable(True)
        self.download_nav_button.setChecked(True)
        self.music_nav_button = QPushButton("♫  Música")
        self.music_nav_button.setObjectName("navButton")
        self.music_nav_button.setCheckable(True)
        self.convert_nav_button = QPushButton("▣  Convertir local")
        self.convert_nav_button.setObjectName("navButton")
        self.convert_nav_button.setCheckable(True)
        nav_layout.addWidget(self.download_nav_button)
        nav_layout.addWidget(self.music_nav_button)
        nav_layout.addWidget(self.convert_nav_button)
        header.addWidget(nav_group, 0, Qt.AlignVCenter)
        header.addStretch(1)

        self.engine_label = QLabel(self._engine_status())
        self.engine_label.setObjectName("engineBadge")
        header.addWidget(self.engine_label)
        open_downloads = QPushButton("📁  Descargas")
        open_downloads.setObjectName("quietButton")
        open_downloads.clicked.connect(lambda: self._open_folder(Path(self.download_path_label.text()) if hasattr(self, "download_path_label") else DEFAULT_DOWNLOADS))
        header.addWidget(open_downloads)
        open_converted = QPushButton("📂  Convertidos")
        open_converted.setObjectName("quietButton")
        open_converted.clicked.connect(lambda: self._open_folder(DEFAULT_CONVERTED))
        header.addWidget(open_converted)

        self.updates_button = QPushButton("↻  Actualizaciones")
        self.updates_button.setObjectName("quietButton")
        self.updates_menu = QMenu(self)
        self.updates_menu.addAction("Buscar actualizaciones…", lambda: self._check_for_updates(manual=True))
        self.updates_menu.addAction("Configurar repositorio de GitHub…", self._configure_update_repository)
        self.updates_menu.addSeparator()
        self.pending_update_action = self.updates_menu.addAction(
            "Instalar actualización descargada", lambda: self._install_pending_update()
        )
        self.updates_menu.aboutToShow.connect(self._refresh_updates_menu)
        self.updates_button.setMenu(self.updates_menu)
        self.updates_button.setToolTip("Buscar, configurar o instalar actualizaciones de MediaFlow")
        header.addWidget(self.updates_button)
        outer.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        self.tabs.addTab(self._build_download_page(), "Descargar")
        self.tabs.addTab(self._build_music_page(), "Música")
        self.tabs.addTab(self._build_convert_page(), "Convertir local")
        self.tabs.tabBar().hide()
        self.download_nav_button.clicked.connect(lambda: self.tabs.setCurrentIndex(0))
        self.music_nav_button.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        self.convert_nav_button.clicked.connect(lambda: self.tabs.setCurrentIndex(2))
        self.tabs.currentChanged.connect(self._sync_navigation_buttons)
        outer.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        drop_hint = QLabel("ARRASTRA VIDEOS O CARPETAS A «CONVERTIR LOCAL» PARA AÑADIRLOS A LA COLA")
        drop_hint.setObjectName("footerHint")
        footer.addWidget(drop_hint)
        footer.addStretch(1)
        version = QLabel(f"MEDIAFLOW  ·  VERSIÓN {APP_VERSION}")
        version.setObjectName("versionLabel")
        footer.addWidget(version)
        outer.addLayout(footer)
        self.setStyleSheet(STYLE)

    def _sync_navigation_buttons(self, index: int) -> None:
        self.download_nav_button.setChecked(index == 0)
        self.music_nav_button.setChecked(index == 1)
        self.convert_nav_button.setChecked(index == 2)

    # ------------------------------------------------------------------
    # GitHub Releases updater
    # ------------------------------------------------------------------
    @staticmethod
    def _updates_directory() -> Path:
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        folder = root / "MediaFlow" / "Updates"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    @staticmethod
    def _pending_update_metadata_path() -> Path:
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        return root / "MediaFlow" / "Updates" / "pending-update.json"

    def _load_pending_update(self) -> None:
        metadata_path = self._pending_update_metadata_path()
        try:
            if not metadata_path.is_file():
                return
            import json
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            installer_path = Path(str(metadata.get("installer_path", ""))).resolve()
            expected_sha = str(metadata.get("sha256", "")).lower()
            info = metadata.get("update_info") or {}
            pending_version = str(info.get("version", "")).strip()
            if pending_version:
                from update_core import version_tuple
                if version_tuple(pending_version) <= version_tuple(APP_VERSION):
                    installer_path.unlink(missing_ok=True)
                    metadata_path.unlink(missing_ok=True)
                    return
            if not installer_path.is_file() or len(expected_sha) != 64:
                return
            digest = hashlib.sha256()
            with installer_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected_sha:
                installer_path.unlink(missing_ok=True)
                metadata_path.unlink(missing_ok=True)
                return
            self.pending_update_path = installer_path
            self.pending_update_info = info
        except Exception:
            # A damaged cache must never prevent MediaFlow from opening.
            self.pending_update_path = None
            self.pending_update_info = None

    def _save_pending_update(self, installer_path: Path, info: dict) -> None:
        import json
        metadata_path = self._pending_update_metadata_path()
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "installer_path": str(installer_path),
            "sha256": str(info.get("sha256", "")).lower(),
            "update_info": info,
        }
        temporary = metadata_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(metadata_path)
        self.pending_update_path = installer_path
        self.pending_update_info = dict(info)

    def _refresh_updates_menu(self) -> None:
        self.pending_update_action.setEnabled(
            bool(self.pending_update_path and self.pending_update_path.is_file())
        )

    def _configure_update_repository(self) -> None:
        current = str(self.settings.value("updates/github_repo", "") or "")
        entered, accepted = QInputDialog.getText(
            self,
            "Repositorio de actualizaciones",
            "Escribe el repositorio público de GitHub en formato propietario/repositorio:\n\nEjemplo: tu-cuenta/MediaFlow",
            text=current,
        )
        if not accepted:
            return
        entered = entered.strip()
        if entered.startswith("https://github.com/"):
            from urllib.parse import urlparse
            parsed = urlparse(entered)
            if parsed.hostname != "github.com":
                QMessageBox.warning(self, "Repositorio no válido", "Solo se admiten repositorios de github.com.")
                return
            entered = parsed.path.strip("/").removesuffix(".git")
        if not validate_repository_name(entered):
            QMessageBox.warning(
                self,
                "Repositorio no válido",
                "Utiliza el formato propietario/repositorio, por ejemplo tu-cuenta/MediaFlow.",
            )
            return
        self.settings.setValue("updates/github_repo", entered)
        self.settings.sync()
        QMessageBox.information(
            self,
            "Repositorio guardado",
            f"MediaFlow buscará las versiones publicadas en:\nhttps://github.com/{entered}/releases",
        )
        self._check_for_updates(manual=True)

    def _maybe_auto_check_for_updates(self) -> None:
        repository = str(self.settings.value("updates/github_repo", "") or "").strip()
        if not repository or not validate_repository_name(repository):
            return
        last_check = int(self.settings.value("updates/last_check", 0) or 0)
        # Avoid a network request on every launch. Manual checks always bypass this interval.
        if int(time.time()) - last_check < 6 * 60 * 60:
            return
        self._check_for_updates(manual=False)

    def _check_for_updates(self, manual: bool = False) -> None:
        if self.update_check_worker is not None and self.update_check_worker.isRunning():
            if manual:
                QMessageBox.information(self, "Actualizaciones", "Ya se está comprobando si hay actualizaciones.")
            return
        repository = str(self.settings.value("updates/github_repo", "") or "").strip()
        if not repository:
            if manual:
                self._configure_update_repository()
            return
        if not validate_repository_name(repository):
            if manual:
                QMessageBox.warning(self, "Repositorio no válido", "Configura el repositorio con el formato propietario/repositorio.")
            return

        self._update_check_manual = manual
        self.settings.setValue("updates/last_check", int(time.time()))
        self.settings.sync()
        self.updates_button.setEnabled(False)
        self.updates_button.setText("↻  Buscando…")
        self.update_check_worker = UpdateCheckWorker(repository, APP_VERSION, self)
        self.update_check_worker.update_available.connect(self._on_update_available)
        self.update_check_worker.up_to_date.connect(self._on_updates_up_to_date)
        self.update_check_worker.failed.connect(self._on_update_check_failed)
        self.update_check_worker.finished.connect(self._on_update_check_finished)
        self.update_check_worker.start()

    def _on_update_check_finished(self) -> None:
        self.updates_button.setEnabled(True)
        self.updates_button.setText("↻  Actualizaciones")
        worker = self.update_check_worker
        self.update_check_worker = None
        if worker is not None:
            worker.deleteLater()

    def _on_updates_up_to_date(self) -> None:
        if self._update_check_manual:
            QMessageBox.information(self, "MediaFlow está actualizado", f"Ya estás utilizando MediaFlow {APP_VERSION}.")

    def _on_update_check_failed(self, message: str) -> None:
        if self._update_check_manual:
            QMessageBox.warning(self, "No se pudo comprobar", message)

    def _operations_are_running(self) -> bool:
        workers = (
            self.active_worker,
            self.preview_worker,
            self.conversion_worker,
            self.folder_scan_worker,
            self.thumbnail_worker,
        )
        return any(worker is not None and worker.isRunning() for worker in workers)

    def _on_update_available(self, info: dict) -> None:
        self.latest_update_info = dict(info)
        notes = str(info.get("release_notes") or "Esta versión incluye mejoras y correcciones.").strip()
        if len(notes) > 1800:
            notes = notes[:1800].rstrip() + "…"
        message = QMessageBox(self)
        message.setWindowTitle("Actualización de MediaFlow")
        message.setIcon(QMessageBox.Information)
        message.setText(f"Hay una nueva versión disponible: MediaFlow {info.get('version', '')}")
        message.setInformativeText(
            f"Versión instalada: {APP_VERSION}\n\nNovedades:\n{notes}\n\n"
            "MediaFlow descargará el instalador y verificará su huella SHA-256 antes de ejecutarlo."
        )
        update_now = message.addButton("Actualizar ahora", QMessageBox.AcceptRole)
        message.addButton("Más tarde", QMessageBox.RejectRole)
        message.exec()
        if message.clickedButton() == update_now:
            if self._operations_are_running():
                QMessageBox.information(
                    self,
                    "Procesos en curso",
                    "Hay descargas, conversiones o análisis activos. Termínalos o cancélalos y vuelve a elegir «Buscar actualizaciones». MediaFlow no interrumpirá tus trabajos.",
                )
                return
            self._download_update(info)

    def _download_update(self, info: dict) -> None:
        destination = self._updates_directory()
        self.update_progress_dialog = QProgressDialog(
            "Descargando la actualización de MediaFlow…",
            "Cancelar",
            0,
            100,
            self,
        )
        self.update_progress_dialog.setWindowTitle("Actualización de MediaFlow")
        self.update_progress_dialog.setWindowModality(Qt.WindowModal)
        self.update_progress_dialog.setMinimumDuration(0)
        self.update_progress_dialog.setAutoClose(False)
        self.update_progress_dialog.setValue(0)
        self.update_download_worker = UpdateDownloadWorker(info, destination, self)
        self.update_download_worker.progress.connect(self.update_progress_dialog.setValue)
        self.update_download_worker.completed.connect(self._on_update_download_completed)
        self.update_download_worker.failed.connect(self._on_update_download_failed)
        self.update_download_worker.cancelled.connect(self._on_update_download_cancelled)
        self.update_download_worker.finished.connect(self._on_update_download_finished)
        self.update_progress_dialog.canceled.connect(self.update_download_worker.requestInterruption)
        self.update_progress_dialog.show()
        self.update_download_worker.start()

    def _finish_update_download_ui(self) -> None:
        if self.update_progress_dialog is not None:
            self.update_progress_dialog.close()
            self.update_progress_dialog.deleteLater()
            self.update_progress_dialog = None

    def _on_update_download_completed(self, raw_path: str) -> None:
        self._finish_update_download_ui()
        if not self.latest_update_info:
            return
        path = Path(raw_path)
        self._save_pending_update(path, self.latest_update_info)
        answer = QMessageBox.question(
            self,
            "Actualización verificada",
            f"MediaFlow {self.latest_update_info.get('version')} se descargó y su SHA-256 coincide.\n\n"
            "¿Quieres cerrar MediaFlow, instalar la actualización y volver a abrir la aplicación ahora?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self._install_pending_update(ask_confirmation=False)
        else:
            QMessageBox.information(
                self,
                "Actualización lista",
                "La actualización quedó descargada y verificada. Puedes instalarla después desde el menú «Actualizaciones».",
            )

    def _on_update_download_failed(self, message: str) -> None:
        self._finish_update_download_ui()
        QMessageBox.critical(self, "Error al descargar actualización", message)

    def _on_update_download_cancelled(self) -> None:
        self._finish_update_download_ui()
        QMessageBox.information(self, "Descarga cancelada", "La descarga de la actualización fue cancelada. MediaFlow no se modificó.")

    def _on_update_download_finished(self) -> None:
        worker = self.update_download_worker
        self.update_download_worker = None
        if worker is not None:
            worker.deleteLater()

    def _install_pending_update(self, ask_confirmation: bool = True) -> None:
        path = self.pending_update_path
        if path is None or not path.is_file():
            QMessageBox.information(self, "Sin actualización descargada", "Primero busca y descarga una actualización disponible.")
            return
        if self._operations_are_running():
            QMessageBox.information(
                self,
                "Procesos en curso",
                "Para proteger tus archivos, termina o cancela las descargas y conversiones antes de instalar la actualización.",
            )
            return
        if not getattr(sys, "frozen", False):
            QMessageBox.information(
                self,
                "Modo de prueba",
                "La actualización ya está descargada y verificada. Como estás ejecutando el código fuente, abre manualmente el instalador desde esta ubicación:\n\n"
                f"{path}",
            )
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
            return

        app_dir = Path(sys.executable).resolve().parent
        helper = app_dir / "support" / "Install-Update.ps1"
        if not helper.is_file():
            QMessageBox.critical(
                self,
                "Falta el asistente de actualización",
                "No se encontró support\\Install-Update.ps1 en la instalación. Reinstala MediaFlow con un instalador que incluya el actualizador.",
            )
            return

        if ask_confirmation:
            confirm = QMessageBox.question(
                self,
                "Instalar actualización",
                f"Se instalará MediaFlow {self.pending_update_info.get('version', '')}.\n"
                "La aplicación se cerrará y volverá a abrirse cuando termine la instalación.\n\n¿Continuar?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if confirm != QMessageBox.Yes:
                return

        try:
            command = [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                "-File", str(helper),
                "-InstallerPath", str(path),
                "-ProcessId", str(os.getpid()),
                "-AppExePath", str(Path(sys.executable).resolve()),
            ]
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(command, cwd=str(app_dir), creationflags=creation_flags, close_fds=True)
            QApplication.instance().quit()
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo iniciar la actualización", str(exc))

    def _build_download_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 9, 2, 2)
        layout.setSpacing(9)

        intro = QHBoxLayout()
        intro_text = QVBoxLayout()
        intro_text.setSpacing(2)
        heading = QLabel("Descargar contenido")
        heading.setObjectName("pageTitle")
        intro_text.addWidget(heading)
        description = QLabel("Pega un enlace, configura el formato y administra tus tareas desde una sola cola.")
        description.setObjectName("mutedLabel")
        intro_text.addWidget(description)
        intro.addLayout(intro_text)
        intro.addStretch(1)
        self.queue_summary = QLabel("0 elementos")
        self.queue_summary.setObjectName("countPill")
        intro.addWidget(self.queue_summary, 0, Qt.AlignVCenter)
        layout.addLayout(intro)

        # Hero card: URL input and the format/quality controls live together.
        form_card = QFrame()
        form_card.setObjectName("surfaceCard")
        form = QVBoxLayout(form_card)
        form.setContentsMargins(16, 13, 16, 12)
        form.setSpacing(9)
        form_header = QHBoxLayout()
        form_title = QLabel("Nueva descarga")
        form_title.setObjectName("cardTitle")
        form_header.addWidget(form_title)
        form_header.addStretch(1)
        url_hint = QLabel("Enlaces de contenido que tengas permiso para guardar")
        url_hint.setObjectName("finePrint")
        form_header.addWidget(url_hint)
        form.addLayout(form_header)

        url_row = QHBoxLayout()
        url_row.setSpacing(9)
        self.url_input = QLineEdit()
        self.url_input.setObjectName("heroUrlInput")
        self.url_input.setPlaceholderText("🔗  Pega el enlace del video o audio aquí…")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.returnPressed.connect(self._add_download)
        url_row.addWidget(self.url_input, 1)
        paste_button = QPushButton("Pegar")
        paste_button.setObjectName("secondaryAccentButton")
        paste_button.clicked.connect(self._paste_download_url)
        url_row.addWidget(paste_button)
        form.addLayout(url_row)

        controls = QGridLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setHorizontalSpacing(12)
        controls.setVerticalSpacing(8)
        controls.setColumnStretch(0, 1)
        controls.setColumnStretch(1, 1)

        format_box = QVBoxLayout()
        format_box.setSpacing(4)
        format_box.addWidget(self._small_label("FORMATO FINAL"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(OUTPUT_FORMATS)
        self.format_combo.setCurrentText("MPG")
        self.format_combo.setMinimumWidth(112)
        format_box.addWidget(self.format_combo)
        controls.addLayout(format_box, 0, 0)

        quality_box = QVBoxLayout()
        quality_box.setSpacing(4)
        quality_box.addWidget(self._small_label("CALIDAD"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(QUALITY_OPTIONS)
        self.quality_combo.setCurrentText("Mejor disponible")
        self.quality_combo.setMinimumWidth(160)
        quality_box.addWidget(self.quality_combo)
        controls.addLayout(quality_box, 0, 1)

        speed_box = QVBoxLayout()
        speed_box.setSpacing(4)
        speed_box.addWidget(self._small_label("LÍMITE DE VELOCIDAD"))
        self.speed_limit = QSpinBox()
        self.speed_limit.setRange(0, 102400)
        self.speed_limit.setValue(0)
        self.speed_limit.setSingleStep(256)
        self.speed_limit.setSuffix(" KB/s")
        self.speed_limit.setMinimumWidth(130)
        speed_box.addWidget(self.speed_limit)
        controls.addLayout(speed_box, 1, 0)

        options = QVBoxLayout()
        options.setSpacing(4)
        options.addWidget(self._small_label("PROCESAMIENTO"))
        self.auto_convert = QCheckBox("Convertir automáticamente al formato elegido")
        self.auto_convert.setChecked(True)
        options.addWidget(self.auto_convert)
        controls.addLayout(options, 1, 1)

        download_action_row = QHBoxLayout()
        download_action_row.addStretch(1)
        self.download_add_button = QPushButton("⌕  Procesar video")
        self.download_add_button.setObjectName("primaryButton")
        self.download_add_button.setMinimumHeight(40)
        self.download_add_button.setMinimumWidth(190)
        self.download_add_button.clicked.connect(self._add_download)
        download_action_row.addWidget(self.download_add_button)
        controls.addLayout(download_action_row, 2, 0, 1, 2)
        form.addLayout(controls)

        path_row = QHBoxLayout()
        path_icon = QLabel("📁")
        path_row.addWidget(path_icon)
        self.download_path_label = QLabel(str(DEFAULT_DOWNLOADS))
        self.download_path_label.setObjectName("pathValue")
        self.download_path_label.setWordWrap(False)
        self.download_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_row.addWidget(self.download_path_label, 1)
        choose_folder = QPushButton("Cambiar carpeta")
        choose_folder.setObjectName("quietButton")
        choose_folder.clicked.connect(self._choose_download_folder)
        path_row.addWidget(choose_folder)
        form.addLayout(path_row)
        layout.addWidget(form_card)

        summary = QHBoxLayout()
        summary.setSpacing(8)
        self.total_card, self.total_value = self._metric_card("EN COLA", "0")
        self.done_card, self.done_value = self._metric_card("COMPLETADAS", "0")
        self.active_card, self.active_value = self._metric_card("EN PROCESO", "0")
        summary.addWidget(self.total_card, 1)
        summary.addWidget(self.done_card, 1)
        summary.addWidget(self.active_card, 1)
        layout.addLayout(summary)

        queue_card = QFrame()
        queue_card.setObjectName("surfaceCard")
        queue_layout = QVBoxLayout(queue_card)
        queue_layout.setContentsMargins(13, 11, 13, 11)
        queue_layout.setSpacing(8)
        qhead = QHBoxLayout()
        qtitle = QLabel("Cola de actividad")
        qtitle.setObjectName("cardTitle")
        qhead.addWidget(qtitle)
        qhead.addStretch(1)
        queue_note = QLabel("Miniatura · título · duración · formato · progreso")
        queue_note.setObjectName("finePrint")
        qhead.addWidget(queue_note)
        queue_layout.addLayout(qhead)

        self.queue_table = QTableWidget(0, 7)
        self.queue_table.setObjectName("queueTable")
        self.queue_table.setHorizontalHeaderLabels(["VIDEO", "CALIDAD", "FORMATO", "PROGRESO", "VELOCIDAD", "RESTANTE", "ESTADO"])
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.queue_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.queue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.setShowGrid(False)
        self.queue_table.setAlternatingRowColors(False)
        self.queue_table.setIconSize(QSize(104, 60))
        self.queue_table.setWordWrap(False)
        header = self.queue_table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setMinimumSectionSize(68)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 96), (2, 92), (3, 108), (4, 92), (5, 78), (6, 98)):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            self.queue_table.setColumnWidth(col, width)
            self.queue_table.model().setHeaderData(
                col, Qt.Horizontal, Qt.AlignCenter | Qt.AlignVCenter, Qt.TextAlignmentRole
            )
        self.queue_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.queue_table.setMinimumHeight(258)
        queue_layout.addWidget(self.queue_table, 1)

        controls_row = QHBoxLayout()
        self.start_queue_button = QPushButton("↓  Iniciar descarga")
        self.start_queue_button.setObjectName("primaryButton")
        self.start_queue_button.clicked.connect(self._start_download_queue)
        controls_row.addWidget(self.start_queue_button)
        self.cancel_download_button = QPushButton("✕  Cancelar seleccionadas")
        self.cancel_download_button.setObjectName("dangerButton")
        self.cancel_download_button.setToolTip("Selecciona una o varias filas de la cola para cancelar esas descargas sin detener las demás.")
        self.cancel_download_button.clicked.connect(self._cancel_selected_downloads)
        controls_row.addWidget(self.cancel_download_button)
        remove_button = QPushButton("Quitar seleccionados")
        remove_button.clicked.connect(self._remove_selected_tasks)
        controls_row.addWidget(remove_button)
        clear_button = QPushButton("Limpiar completadas")
        clear_button.clicked.connect(self._clear_completed)
        controls_row.addWidget(clear_button)
        controls_row.addStretch(1)
        queue_layout.addLayout(controls_row)
        self.queue_status = QLabel("Agrega un enlace para crear tu cola. Puedes seleccionar varias tareas y cancelarlas sin cerrar MediaFlow.")
        self.queue_status.setObjectName("mutedLabel")
        self.queue_status.setWordWrap(True)
        queue_layout.addWidget(self.queue_status)
        layout.addWidget(queue_card, 1)
        return page


    def _build_music_page(self) -> QWidget:
        page = DropTarget()
        page.filesDropped.connect(self._handle_music_dropped_files)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 9, 2, 2)
        layout.setSpacing(10)
        intro = QHBoxLayout()
        intro_text = QVBoxLayout()
        heading = QLabel("Música y audio")
        heading.setObjectName("pageTitle")
        intro_text.addWidget(heading)
        description = QLabel("Convierte tus archivos de audio a formatos de alta calidad. Los archivos originales no se modifican.")
        description.setObjectName("mutedLabel")
        intro_text.addWidget(description)
        intro.addLayout(intro_text)
        intro.addStretch(1)
        self.music_count = QLabel("0 archivos")
        self.music_count.setObjectName("countPill")
        intro.addWidget(self.music_count)
        layout.addLayout(intro)
        card = QFrame()
        card.setObjectName("surfaceCard")
        body = QVBoxLayout(card)
        body.setContentsMargins(15, 13, 15, 13)
        body.setSpacing(9)
        title = QLabel("Biblioteca de trabajo")
        title.setObjectName("cardTitle")
        body.addWidget(title)
        url_row = QHBoxLayout()
        self.music_url_input = QLineEdit()
        self.music_url_input.setPlaceholderText("Pega aquí un enlace de YouTube para descargar su audio…")
        self.music_url_input.setClearButtonEnabled(True)
        self.music_url_input.returnPressed.connect(self._start_music_url_download)
        url_row.addWidget(self.music_url_input, 1)
        paste_music = QPushButton("Pegar")
        paste_music.clicked.connect(self._paste_music_url)
        url_row.addWidget(paste_music)
        self.music_url_download_button = QPushButton("↓ Descargar audio")
        self.music_url_download_button.setObjectName("secondaryAccentButton")
        self.music_url_download_button.clicked.connect(self._start_music_url_download)
        url_row.addWidget(self.music_url_download_button)
        body.addLayout(url_row)
        self.music_list = QListWidget()
        self.music_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.music_list.setMinimumHeight(260)
        self.music_list.setAlternatingRowColors(True)
        self.music_list.setIconSize(QSize(56, 56))
        body.addWidget(self.music_list, 1)
        file_actions = QHBoxLayout()
        add_files = QPushButton("＋ Agregar archivos")
        add_files.clicked.connect(self._choose_music_files)
        file_actions.addWidget(add_files)
        remove_files = QPushButton("Quitar seleccionados")
        remove_files.clicked.connect(self._remove_music_files)
        file_actions.addWidget(remove_files)
        clear_files = QPushButton("Limpiar lista")
        clear_files.clicked.connect(self._clear_music_files)
        file_actions.addWidget(clear_files)
        file_actions.addStretch(1)
        body.addLayout(file_actions)
        settings = QGridLayout()
        settings.addWidget(self._small_label("FORMATO DE SALIDA"), 0, 0)
        self.music_format = QComboBox()
        self.music_format.addItems(AUDIO_OUTPUT_FORMATS)
        self.music_format.setCurrentText("MP3")
        settings.addWidget(self.music_format, 1, 0)
        settings.addWidget(self._small_label("CALIDAD / BITRATE"), 0, 1)
        self.music_bitrate = QComboBox()
        self.music_bitrate.addItems(["96 kbps", "128 kbps", "192 kbps", "256 kbps", "320 kbps"])
        self.music_bitrate.setCurrentText("320 kbps")
        settings.addWidget(self.music_bitrate, 1, 1)
        settings.addWidget(self._small_label("CARPETA DE DESTINO"), 0, 2)
        destination_row = QHBoxLayout()
        self.music_destination = QLineEdit(str(MUSIC_OUTPUT_DIR))
        self.music_destination.setReadOnly(True)
        destination_row.addWidget(self.music_destination, 1)
        choose_destination = QPushButton("Cambiar")
        choose_destination.clicked.connect(self._choose_music_destination)
        destination_row.addWidget(choose_destination)
        settings.addLayout(destination_row, 1, 2)
        settings.setColumnStretch(2, 2)
        body.addLayout(settings)
        actions = QHBoxLayout()
        self.music_convert_button = QPushButton("♫  CONVERTIR AUDIO")
        self.music_convert_button.setObjectName("primaryButton")
        self.music_convert_button.clicked.connect(self._start_music_conversion)
        actions.addWidget(self.music_convert_button)
        self.music_open_button = QPushButton("Abrir carpeta")
        self.music_open_button.clicked.connect(lambda: self._open_folder(Path(self.music_destination.text())))
        actions.addWidget(self.music_open_button)
        actions.addStretch(1)
        body.addLayout(actions)
        self.music_progress = QProgressBar()
        self.music_progress.setValue(0)
        body.addWidget(self.music_progress)
        self.music_status = QLabel("Pega un enlace de YouTube o agrega archivos de audio propios. Elige formato y calidad antes de comenzar.")
        self.music_status.setObjectName("mutedLabel")
        self.music_status.setWordWrap(True)
        body.addWidget(self.music_status)
        layout.addWidget(card, 1)
        return page

    def _paste_music_url(self) -> None:
        self.music_url_input.setText(QApplication.clipboard().text().strip())

    def _start_music_url_download(self) -> None:
        if self.music_download_worker is not None and self.music_download_worker.isRunning():
            return
        url = self.music_url_input.text().strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            QMessageBox.warning(self, "Enlace no válido", "Pega un enlace completo de YouTube.")
            return
        if not any(host in parsed.netloc.lower() for host in ("youtube.com", "youtu.be", "youtube-nocookie.com")):
            QMessageBox.warning(self, "Sitio no compatible", "Esta función acepta enlaces de YouTube.")
            return
        if not find_ffmpeg():
            QMessageBox.warning(self, "FFmpeg no detectado", "Instala FFmpeg y vuelve a abrir MediaFlow.")
            return
        fmt = self.music_format.currentText().lower()
        bitrate = int(self.music_bitrate.currentText().split()[0])
        self.music_url_download_button.setEnabled(False)
        self.music_format.setEnabled(False)
        self.music_bitrate.setEnabled(False)
        self.music_progress.setValue(0)
        self.music_status.setText(f"Descargando audio · {fmt.upper()} · {bitrate} kbps.")
        worker = MusicUrlDownloadWorker(url, Path(self.music_destination.text()), fmt, bitrate)
        self.music_download_worker = worker
        worker.progress.connect(self._music_url_progress)
        worker.succeeded.connect(self._music_url_succeeded)
        worker.failed.connect(self._music_url_failed)
        worker.cancelled.connect(self._music_url_cancelled)
        worker.finished.connect(self._music_url_finished)
        worker.start()

    def _music_url_progress(self, percent: int, message: str) -> None:
        self.music_progress.setValue(percent)
        self.music_status.setText(message)

    def _music_url_succeeded(self, path: str) -> None:
        self.music_progress.setValue(100)
        self.music_status.setText(f"Audio guardado: {Path(path).name}\nCarpeta: {self.music_destination.text()}")

    def _music_url_failed(self, message: str) -> None:
        self.music_status.setText("No se pudo descargar el audio: " + message[:1200])

    def _music_url_cancelled(self, message: str) -> None:
        self.music_status.setText(message)

    def _music_url_finished(self) -> None:
        worker = self.music_download_worker
        self.music_download_worker = None
        if worker is not None:
            worker.deleteLater()
        self.music_url_download_button.setEnabled(True)
        self.music_format.setEnabled(True)
        self.music_bitrate.setEnabled(True)

    def _choose_music_files(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(
            self, "Seleccionar archivos de audio", str(Path.home()),
            "Archivos de audio (*.mp3 *.flac *.wav *.m4a *.aac *.ogg *.opus *.wma *.aiff *.alac);;Todos los archivos (*.*)"
        )
        self._add_music_paths([Path(name) for name in names])

    def _handle_music_dropped_files(self, raw_paths: list[str]) -> None:
        self._add_music_paths([Path(raw) for raw in raw_paths])

    def _add_music_paths(self, paths: list[Path]) -> None:
        added = 0
        newly_added: list[Path] = []
        known = {str(path.resolve()).casefold() for path in self.music_files}
        for path in paths:
            candidates = []
            if path.is_dir():
                try:
                    candidates = [item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in AUDIO_EXTENSIONS]
                except OSError:
                    candidates = []
            elif path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                candidates = [path]
            for candidate in candidates:
                try:
                    key = str(candidate.resolve()).casefold()
                    if key in known:
                        continue
                    self.music_files.append(candidate)
                    item = QListWidgetItem(f"{candidate.name}    ·    {human_file_size(candidate.stat().st_size)}")
                    item.setToolTip(str(candidate))
                    item.setIcon(QIcon(_placeholder_pixmap(QSize(56, 56), "♫")))
                    self.music_list.addItem(item)
                    self.music_items_by_path[key] = item
                    newly_added.append(candidate)
                    known.add(key)
                    added += 1
                except OSError:
                    continue
        self.music_count.setText(f"{len(self.music_files)} archivos")
        if added:
            self.music_status.setText(f"Se agregaron {added} archivo(s) de audio. Buscando portadas incrustadas…")
            self.music_cover_pending.extend(newly_added)
            self._start_music_cover_worker()

    def _remove_music_files(self) -> None:
        for index in sorted({item.row() for item in self.music_list.selectedIndexes()}, reverse=True):
            item = self.music_list.takeItem(index)
            if 0 <= index < len(self.music_files):
                path = self.music_files.pop(index)
                self.music_items_by_path.pop(str(path.resolve()).casefold(), None)
        self.music_count.setText(f"{len(self.music_files)} archivos")

    def _clear_music_files(self) -> None:
        if self.music_worker is not None and self.music_worker.isRunning():
            return
        self.music_files.clear()
        self.music_list.clear()
        self.music_items_by_path.clear()
        self.music_cover_pending.clear()
        self.music_count.setText("0 archivos")
        self.music_progress.setValue(0)
        self.music_status.setText("Lista vacía.")


    def _start_music_cover_worker(self) -> None:
        if self.music_cover_worker is not None and self.music_cover_worker.isRunning():
            return
        if not self.music_cover_pending:
            return
        batch = self.music_cover_pending
        self.music_cover_pending = []
        worker = AudioCoverWorker(batch)
        self.music_cover_worker = worker
        worker.coverReady.connect(self._on_music_cover_ready)
        worker.finished.connect(self._music_cover_worker_finished)
        worker.start()

    def _on_music_cover_ready(self, raw_path: str, image_bytes: bytes) -> None:
        key = str(Path(raw_path).resolve()).casefold()
        item = self.music_items_by_path.get(key)
        if item is None:
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(image_bytes):
            item.setIcon(QIcon(_center_crop_pixmap(pixmap, QSize(56, 56))))
            item.setToolTip(raw_path + "\nPortada incrustada disponible")

    def _music_cover_worker_finished(self) -> None:
        worker = self.music_cover_worker
        self.music_cover_worker = None
        if worker is not None:
            worker.deleteLater()
        if self.music_cover_pending:
            QTimer.singleShot(100, self._start_music_cover_worker)

    def _choose_music_destination(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Carpeta de salida para música", self.music_destination.text())
        if folder:
            self.music_destination.setText(folder)

    def _start_music_conversion(self) -> None:
        if self.music_worker is not None and self.music_worker.isRunning():
            return
        if not self.music_files:
            QMessageBox.information(self, "No hay archivos", "Agrega archivos de audio antes de convertir.")
            return
        if not find_ffmpeg():
            QMessageBox.warning(self, "FFmpeg no detectado", "Instala FFmpeg y vuelve a abrir MediaFlow.")
            return
        bitrate = int(self.music_bitrate.currentText().split()[0])
        output_format = self.music_format.currentText().lower()
        jobs = [(source, output_format, "Original", "Alta", False) for source in self.music_files]
        self.music_convert_button.setEnabled(False)
        self.music_format.setEnabled(False)
        self.music_bitrate.setEnabled(False)
        self.music_progress.setValue(0)
        self.music_worker = ConvertWorker(jobs, Path(self.music_destination.text()), audio_bitrate_kbps=bitrate)
        self.music_worker.progress.connect(self._music_progress)
        self.music_worker.succeeded.connect(self._music_succeeded)
        self.music_worker.failed.connect(self._music_failed)
        self.music_worker.cancelled.connect(self._music_cancelled)
        self.music_worker.finished.connect(self._music_conversion_finished)
        self.music_status.setText(f"Convirtiendo {len(jobs)} archivo(s) a {output_format.upper()} · {bitrate} kbps.")
        self.music_worker.start()

    def _music_progress(self, percent: int, message: str) -> None:
        self.music_progress.setValue(percent)
        self.music_status.setText(message)

    def _music_succeeded(self, results: str) -> None:
        count = len([line for line in results.splitlines() if line.strip()])
        if count:
            self.music_status.setText(f"Conversión terminada: {count} archivo(s). Destino: {self.music_destination.text()}")

    def _music_failed(self, message: str) -> None:
        self.music_status.setText("Algunos archivos no pudieron convertirse: " + message[:1200])

    def _music_cancelled(self, message: str) -> None:
        self.music_status.setText(message)

    def _music_conversion_finished(self) -> None:
        worker = self.music_worker
        self.music_worker = None
        if worker is not None:
            worker.deleteLater()
        self.music_convert_button.setEnabled(True)
        self.music_format.setEnabled(True)
        self.music_bitrate.setEnabled(True)

    def _build_convert_page(self) -> QWidget:
        page = DropTarget()
        page.filesDropped.connect(self._handle_dropped_files)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 9, 2, 2)
        layout.setSpacing(9)

        intro = QHBoxLayout()
        intro_text = QVBoxLayout()
        intro_text.setSpacing(2)
        header = QLabel("Convertir archivos locales")
        header.setObjectName("pageTitle")
        intro_text.addWidget(header)
        sub = QLabel("Agrega archivos o carpetas completas y sigue el avance individual de cada conversión.")
        sub.setObjectName("mutedLabel")
        intro_text.addWidget(sub)
        intro.addLayout(intro_text)
        intro.addStretch(1)
        self.convert_count = QLabel("0 archivos")
        self.convert_count.setObjectName("countPill")
        intro.addWidget(self.convert_count, 0, Qt.AlignVCenter)
        layout.addLayout(intro)

        drop_card = QFrame()
        drop_card.setObjectName("dropCard")
        drop_card.setMaximumHeight(92)
        drop_layout = QHBoxLayout(drop_card)
        drop_layout.setContentsMargins(18, 13, 18, 13)
        drop_layout.setSpacing(16)
        drop_icon = QLabel("⇩")
        drop_icon.setObjectName("dropIcon")
        drop_layout.addWidget(drop_icon)
        drop_text = QVBoxLayout()
        drop_text.setSpacing(3)
        drop_title = QLabel("Arrastra videos, audios o carpetas aquí")
        drop_title.setObjectName("dropTitle")
        drop_text.addWidget(drop_title)
        drop_help = QLabel("MP4 · MPG · AVI · MKV · MOV · MP3 · WAV · Carpetas y subcarpetas")
        drop_help.setObjectName("mutedLabel")
        drop_text.addWidget(drop_help)
        drop_layout.addLayout(drop_text, 1)
        drop_hint = QLabel("SOLTAR PARA AÑADIR")
        drop_hint.setObjectName("dropHint")
        drop_layout.addWidget(drop_hint)
        layout.addWidget(drop_card)

        file_card = QFrame()
        file_card.setObjectName("surfaceCard")
        file_layout = QVBoxLayout(file_card)
        file_layout.setContentsMargins(13, 11, 13, 11)
        file_layout.setSpacing(8)
        file_header = QHBoxLayout()
        file_label = QLabel("Archivos para convertir")
        file_label.setObjectName("cardTitle")
        file_header.addWidget(file_label)
        file_header.addStretch(1)
        thumb_hint = QLabel("Cada archivo muestra su propia barra de progreso y formato")
        thumb_hint.setObjectName("finePrint")
        file_header.addWidget(thumb_hint)
        file_layout.addLayout(file_header)

        self.file_list = QListWidget()
        self.file_list.setObjectName("conversionList")
        self.file_list.setMinimumHeight(220)
        self.file_list.setIconSize(QSize(1, 1))
        self.file_list.setSpacing(5)
        self.file_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.file_list.setUniformItemSizes(False)
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.itemSelectionChanged.connect(self._on_conversion_selection_changed)
        file_layout.addWidget(self.file_list, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(7)
        self.browse_files_button = QPushButton("＋  Buscar archivos")
        self.browse_files_button.clicked.connect(self._choose_source_files)
        buttons.addWidget(self.browse_files_button)
        self.browse_folder_button = QPushButton("▣  Agregar carpeta")
        self.browse_folder_button.clicked.connect(self._choose_source_folder)
        buttons.addWidget(self.browse_folder_button)
        remove = QPushButton("Quitar seleccionados")
        remove.clicked.connect(self._remove_selected_files)
        buttons.addWidget(remove)
        self.cancel_selected_conversion_button = QPushButton("✕  Cancelar seleccionados")
        self.cancel_selected_conversion_button.setObjectName("dangerButton")
        self.cancel_selected_conversion_button.setToolTip("Durante un lote activo, cancela solo los archivos seleccionados y continúa con los demás.")
        self.cancel_selected_conversion_button.setEnabled(False)
        self.cancel_selected_conversion_button.clicked.connect(self._cancel_selected_conversions)
        buttons.addWidget(self.cancel_selected_conversion_button)
        clear = QPushButton("Vaciar lista")
        clear.clicked.connect(self._clear_files)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        file_layout.addLayout(buttons)

        # Conversion quality profile: applied to the whole batch while the
        # output format can still be changed individually in each file row.
        profile_card = QFrame()
        profile_card.setObjectName("profileCard")
        profile_layout = QGridLayout(profile_card)
        profile_layout.setContentsMargins(12, 9, 12, 9)
        profile_layout.setHorizontalSpacing(12)
        profile_layout.setVerticalSpacing(5)

        resolution_caption = QLabel("RESOLUCIÓN MÁXIMA")
        resolution_caption.setObjectName("fieldCaption")
        profile_layout.addWidget(resolution_caption, 0, 0)
        quality_caption = QLabel("CALIDAD / COMPRESIÓN")
        quality_caption.setObjectName("fieldCaption")
        profile_layout.addWidget(quality_caption, 0, 1)

        self.convert_resolution = QComboBox()
        self.convert_resolution.addItems(VIDEO_RESOLUTION_OPTIONS)
        self.convert_resolution.setCurrentText("Original")
        self.convert_resolution.setToolTip("Reduce la resolución máxima sin aumentar videos que ya tengan menor resolución.")
        profile_layout.addWidget(self.convert_resolution, 1, 0)

        self.convert_quality = QComboBox()
        self.convert_quality.addItems(VIDEO_COMPRESSION_OPTIONS)
        self.convert_quality.setCurrentText("Equilibrada")
        self.convert_quality.setToolTip("Alta conserva más detalle y genera archivos mayores; Compacta y Muy compacta reducen el tamaño.")
        profile_layout.addWidget(self.convert_quality, 1, 1)

        self.fat32_mode = QCheckBox("Optimizar para memorias FAT32 (objetivo de hasta 3.7 GiB por video)")
        self.fat32_mode.setToolTip(
            "Activa codificación de dos pasadas con bitrate calculado por duración. "
            "Es un objetivo conservador, no una garantía matemática del tamaño final."
        )
        profile_layout.addWidget(self.fat32_mode, 2, 0, 1, 2)

        self.convert_profile_hint = QLabel(
            "Los ajustes de resolución y compresión se aplican a todo el lote. "
            "El formato sigue siendo editable en cada fila."
        )
        self.convert_profile_hint.setObjectName("profileHint")
        self.convert_profile_hint.setWordWrap(True)
        profile_layout.addWidget(self.convert_profile_hint, 3, 0, 1, 2)
        self.fat32_mode.toggled.connect(self._update_fat32_profile_hint)
        self.convert_quality.currentTextChanged.connect(self._update_fat32_profile_hint)
        file_layout.addWidget(profile_card)

        secondary_options = QHBoxLayout()
        self.include_subfolders = QCheckBox("Incluir también las subcarpetas")
        self.include_subfolders.setChecked(True)
        secondary_options.addWidget(self.include_subfolders)
        secondary_options.addSpacing(12)
        secondary_options.addWidget(QLabel("FORMATO POR DEFECTO"))
        self.convert_format = QComboBox()
        self.convert_format.addItems(OUTPUT_FORMATS)
        self.convert_format.setCurrentText("MPG")
        self.convert_format.setFixedWidth(104)
        secondary_options.addWidget(self.convert_format)
        apply_format_button = QPushButton("Aplicar a seleccionados")
        apply_format_button.setObjectName("quietButton")
        apply_format_button.setToolTip("Cambia el formato de salida de todas las filas seleccionadas.")
        apply_format_button.clicked.connect(self._apply_format_to_selected)
        secondary_options.addWidget(apply_format_button)
        secondary_options.addStretch(1)
        self.convert_button = QPushButton("✂  Convertir archivos")
        self.convert_button.setObjectName("primaryButton")
        self.convert_button.clicked.connect(self._start_conversion)
        secondary_options.addWidget(self.convert_button)
        self.cancel_conversion_button = QPushButton("Cancelar todo el lote")
        self.cancel_conversion_button.setObjectName("dangerButton")
        self.cancel_conversion_button.setToolTip("Detiene el archivo que se está convirtiendo y omite el resto del lote.")
        self.cancel_conversion_button.setEnabled(False)
        self.cancel_conversion_button.clicked.connect(self._cancel_conversion_batch)
        secondary_options.addWidget(self.cancel_conversion_button)
        file_layout.addLayout(secondary_options)
        self.convert_progress = QProgressBar()
        self.convert_progress.setValue(0)
        file_layout.addWidget(self.convert_progress)
        self.convert_status = QLabel(f"Los archivos se guardarán en: {DEFAULT_CONVERTED}")
        self.convert_status.setObjectName("mutedLabel")
        self.convert_status.setWordWrap(True)
        file_layout.addWidget(self.convert_status)
        layout.addWidget(file_card, 1)
        return page

    def _metric_card(self, label: str, value: str) -> tuple[QFrame, QLabel]:
        """Compact horizontal metric pill; keeps queue stats secondary to the work list."""
        card = QFrame()
        card.setObjectName("metricCard")
        card.setMaximumHeight(42)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 5, 12, 5)
        layout.setSpacing(10)
        caption = QLabel(label)
        caption.setObjectName("metricCaption")
        number = QLabel(value)
        number.setObjectName("metricValue")
        layout.addWidget(caption)
        layout.addStretch(1)
        layout.addWidget(number)
        return card, number

    @staticmethod
    def _small_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldCaption")
        return label

    def _engine_status(self) -> str:
        return "● FFmpeg listo" if find_ffmpeg() else "● FFmpeg no detectado"

    def _choose_download_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de descargas", str(DEFAULT_DOWNLOADS))
        if folder:
            self.download_path_label.setText(folder)

    def _open_folder(self, folder: Path) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve()))):
                raise RuntimeError("Windows no pudo abrir la carpeta.")
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo abrir la carpeta", str(exc))

    def _paste_download_url(self) -> None:
        clipboard_text = QApplication.clipboard().text().strip()
        if not clipboard_text:
            self.queue_status.setText("El portapapeles está vacío. Copia un enlace y vuelve a pulsar Pegar.")
            return
        self.url_input.setText(clipboard_text)
        self.url_input.setFocus()

    def _add_download(self) -> None:
        url = self.url_input.text().strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            QMessageBox.warning(self, "Enlace no válido", "Pega un enlace web completo que comience con http:// o https://.")
            return
        output_format = self.format_combo.currentText()
        auto_convert = self.auto_convert.isChecked()
        if not auto_convert and output_format in ("MPG", "AVI", "MP3"):
            QMessageBox.information(
                self,
                "Conversión necesaria",
                f"Para generar {output_format}, activa 'Convertir al formato elegido al terminar'.",
            )
            return
        quality = self.quality_combo.currentText()
        if quality == "Solo audio" and output_format != "MP3":
            QMessageBox.information(self, "Formato de audio", "Has elegido 'Solo audio'. Selecciona MP3 como formato final.")
            return

        task_id = uuid.uuid4().hex[:10]
        task = {
            "id": task_id,
            "url": url,
            "title": parsed.netloc,
            "quality": quality,
            "output_format": output_format,
            "auto_convert": auto_convert,
            "rate_kbps": self.speed_limit.value(),
            "status": "Procesando información",
            "path": "",
            "duration": None,
        }
        self.tasks[task_id] = task
        row = self.queue_table.rowCount()
        self.queue_table.insertRow(row)
        # Keep the backing item visually empty: column 0 is rendered only by
        # DownloadQueueCell. Painting text in both places caused the title to
        # appear duplicated/overlapped beneath the thumbnail widget.
        title_item = QTableWidgetItem("")
        title_item.setData(Qt.UserRole, task_id)
        title_item.setToolTip(url)
        title_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.queue_table.setItem(row, 0, title_item)
        download_cell = DownloadQueueCell(
            f"{parsed.netloc} · analizando video…",
            "AUDIO" if quality == "Solo audio" else "VIDEO",
        )
        download_cell.set_subtitle(f"{quality}  ·  {output_format}  ·  Procesando información…")
        self.queue_table.setCellWidget(row, 0, download_cell)
        self.download_cells[task_id] = download_cell
        quality_item = QTableWidgetItem(quality)
        quality_item.setTextAlignment(Qt.AlignCenter)
        self.queue_table.setItem(row, 1, quality_item)
        format_editor = QComboBox()
        format_editor.addItems(OUTPUT_FORMATS)
        format_editor.setCurrentText(output_format)
        format_editor.setFixedSize(82, 34)
        format_editor.setToolTip("Puedes corregir el formato de esta descarga mientras siga pendiente.")
        format_editor.currentTextChanged.connect(
            lambda value, current_task_id=task_id: self._change_download_format(current_task_id, value)
        )
        format_host = QWidget()
        format_host_layout = QHBoxLayout(format_host)
        format_host_layout.setContentsMargins(2, 0, 2, 0)
        format_host_layout.setSpacing(0)
        format_host_layout.addStretch(1)
        format_host_layout.addWidget(format_editor, 0, Qt.AlignVCenter)
        format_host_layout.addStretch(1)
        self.queue_table.setCellWidget(row, 2, format_host)
        self.download_format_editors[task_id] = format_editor

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setFormat("%p%")
        progress.setFixedHeight(14)
        progress.setMinimumWidth(78)
        progress_host = QWidget()
        progress_host_layout = QHBoxLayout(progress_host)
        progress_host_layout.setContentsMargins(5, 0, 5, 0)
        progress_host_layout.setSpacing(0)
        progress_host_layout.addWidget(progress, 1, Qt.AlignVCenter)
        self.queue_table.setCellWidget(row, 3, progress_host)
        self.download_progress_bars[task_id] = progress
        for column, value in ((4, "—"), (5, "—"), (6, "Procesando")):
            cell_item = QTableWidgetItem(value)
            cell_item.setTextAlignment(Qt.AlignCenter)
            self.queue_table.setItem(row, column, cell_item)
        self.queue_table.setRowHeight(row, 72)
        self.task_rows[task_id] = row
        self.url_input.clear()
        self.queue_status.setText(f"Procesando información del video: título, miniatura y duración. Formato final: {output_format}.")
        self._refresh_summary()
        self.preview_queue.append(task_id)
        self._start_next_download_preview()

    def _change_download_format(self, task_id: str, output_format: str) -> None:
        task = self.tasks.get(task_id)
        if not task:
            return
        if task.get("status") != "Pendiente":
            row = self.task_rows.get(task_id)
            editor = self.download_format_editors.get(task_id)
            if isinstance(editor, QComboBox):
                blocker = QSignalBlocker(editor)
                editor.setCurrentText(task.get("output_format", "MPG"))
                del blocker
            return
        if task.get("quality") == "Solo audio" and output_format != "MP3":
            row = self.task_rows.get(task_id)
            editor = self.download_format_editors.get(task_id)
            if isinstance(editor, QComboBox):
                blocker = QSignalBlocker(editor)
                editor.setCurrentText("MP3")
                del blocker
            self.queue_status.setText("Para una descarga de solo audio, el formato final debe ser MP3.")
            return
        if not task.get("auto_convert") and output_format in ("MPG", "AVI", "MP3"):
            row = self.task_rows.get(task_id)
            editor = self.download_format_editors.get(task_id)
            if isinstance(editor, QComboBox):
                blocker = QSignalBlocker(editor)
                editor.setCurrentText(task.get("output_format", "MP4"))
                del blocker
            self.queue_status.setText(f"Activa la conversión automática para generar {output_format}.")
            return
        task["output_format"] = output_format
        cell = self.download_cells.get(task_id)
        if cell is not None:
            cell.set_subtitle(f"{task.get('quality', 'Mejor disponible')}  ·  {output_format}  ·  Pendiente")
        self.queue_status.setText(f"Formato de salida actualizado a {output_format} para esta descarga.")

    def _start_next_download_preview(self) -> None:
        if self.preview_worker is not None and self.preview_worker.isRunning():
            return
        while self.preview_queue:
            task_id = self.preview_queue.pop(0)
            task = self.tasks.get(task_id)
            if not task or task.get("status") in ("Cancelada", "Error"):
                continue
            worker = DownloadPreviewWorker(task_id, task["url"])
            self.preview_worker = worker
            worker.ready.connect(self._on_download_preview_ready)
            worker.failed.connect(self._on_download_preview_failed)
            worker.finished.connect(self._on_download_preview_finished)
            worker.start()
            return

    def _on_download_preview_ready(self, task_id: str, title: str, image_bytes: bytes, info: object) -> None:
        task = self.tasks.get(task_id)
        row = self.task_rows.get(task_id)
        if task is None or row is None:
            return
        if isinstance(info, dict) and info.get("_type") == "playlist":
            entries = [entry for entry in (info.get("entries") or []) if isinstance(entry, dict)]
            parsed_url = urlparse(task.get("url", ""))
            selected_id = parse_qs(parsed_url.query).get("v", [""])[0]
            if not selected_id and parsed_url.netloc.lower().endswith("youtu.be"):
                selected_id = parsed_url.path.strip("/").split("/")[0]
            dialog = PlaylistSelectionDialog(entries, selected_id, self)
            dialog.setWindowTitle(f"MediaFlow · {title}")
            chosen = dialog.exec()
            # Replace the temporary parent row with one queue item per selected video.
            self.queue_table.removeRow(row)
            self.tasks.pop(task_id, None)
            self.task_rows.pop(task_id, None)
            self.download_cells.pop(task_id, None)
            self.download_format_editors.pop(task_id, None)
            self.download_progress_bars.pop(task_id, None)
            self._reindex_rows()
            if chosen == QDialog.Accepted:
                selected_entries = dialog.selected_entries()
                added = 0
                for entry in selected_entries:
                    video_url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
                    if not video_url.startswith(("http://", "https://")):
                        entry_id = str(entry.get("id") or "").strip()
                        if entry_id and str(entry.get("ie_key") or "").lower() in ("youtube", "youtubeplaylist"):
                            video_url = f"https://www.youtube.com/watch?v={entry_id}"
                    if not video_url:
                        continue
                    self.url_input.setText(video_url)
                    self._add_download()
                    added += 1
                self.queue_status.setText(
                    f"Se agregaron {added} videos seleccionados de «{title}» a la cola."
                    if added else "No se agregaron videos: no se encontraron enlaces individuales válidos."
                )
            else:
                self.queue_status.setText("Selección de lista cancelada; no se agregó ningún video.")
            self._refresh_summary()
            return
        if isinstance(info, dict):
            task["preview_info"] = info
        task["preview_thumbnail"] = image_bytes or b""
        item = self.queue_table.item(row, 0)
        task["title"] = title
        duration = info.get("duration") if isinstance(info, dict) else None
        try:
            task["duration"] = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            task["duration"] = None
        if item:
            item.setToolTip(task["url"] + ("\nMiniatura disponible" if image_bytes else "\nEl sitio no proporcionó miniatura."))
        cell = self.download_cells.get(task_id)
        if cell is not None:
            cell.set_title(title)
            duration_label = _format_clock(task.get("duration"))
            cell.set_subtitle(f"{duration_label}  ·  {task.get('quality', 'Mejor disponible')}  ·  {task.get('output_format', 'MPG')}  ·  Listo para descargar")
            cell.set_thumbnail_bytes(image_bytes)
        self._set_task_status(task_id, "Pendiente")
        self.queue_status.setText(f"Video procesado: {title}. Ya puedes agregar más enlaces o iniciar la descarga.")
        self._refresh_summary()

    def _on_download_preview_failed(self, task_id: str, message: str) -> None:
        row = self.task_rows.get(task_id)
        if row is None:
            return
        item = self.queue_table.item(row, 0)
        if item:
            item.setToolTip(self.tasks.get(task_id, {}).get("url", "") + "\nNo se pudo obtener la vista previa: " + message[:800])
        cell = self.download_cells.get(task_id)
        if cell is not None:
            task = self.tasks.get(task_id, {})
            cell.set_subtitle(f"{task.get('quality', 'Mejor disponible')}  ·  {task.get('output_format', 'MPG')}  ·  Miniatura no disponible")
        self._set_task_status(task_id, "Error")
        self.queue_status.setText("No se pudo procesar este enlace. Revisa el detalle del error en la fila e inténtalo de nuevo.")
        self._refresh_summary()

    def _on_download_preview_finished(self) -> None:
        if self.preview_worker is not None:
            self.preview_worker.deleteLater()
            self.preview_worker = None
        QTimer.singleShot(100, self._start_next_download_preview)

    def _start_download_queue(self) -> None:
        processing = any(task.get("status") == "Procesando información" for task in self.tasks.values())
        if processing:
            self.queue_status.setText("Espera a que termine el procesamiento de todos los enlaces antes de iniciar la descarga.")
            return
        if not any(task.get("status") == "Pendiente" for task in self.tasks.values()):
            self.queue_status.setText("Primero procesa uno o varios videos para agregarlos a la cola.")
            return
        if not find_ffmpeg():
            QMessageBox.warning(self, "FFmpeg no detectado", "Instala FFmpeg y vuelve a abrir MediaFlow para iniciar las descargas y conversiones.")
            return
        self.download_queue_started = True
        self._start_next_download()

    def _start_next_download(self) -> None:
        if not self.download_queue_started:
            return
        if self.active_worker is not None and self.active_worker.isRunning():
            return
        pending = next((task for task in self.tasks.values() if task["status"] == "Pendiente"), None)
        if pending is None:
            self.queue_status.setText("La cola terminó. Puedes procesar más enlaces cuando quieras.")
            self.download_queue_started = False
            self._refresh_summary()
            return
        self.start_queue_button.setEnabled(True)
        pending["status"] = "Preparando"
        self._set_task_status(pending["id"], "Preparando")
        self.queue_status.setText("Conectando con el sitio y preparando la descarga…")
        self.active_worker = DownloadWorker(pending, Path(self.download_path_label.text()), DEFAULT_CONVERTED)
        self.active_worker.metadata.connect(self._on_download_metadata)
        self.active_worker.progress.connect(self._on_download_progress)
        self.active_worker.succeeded.connect(self._on_download_succeeded)
        self.active_worker.failed.connect(self._on_download_failed)
        self.active_worker.cancelled.connect(self._on_download_cancelled)
        self.active_worker.finished.connect(self._on_download_worker_finished)
        self.active_worker.start()
        self._refresh_summary()

    def _on_download_metadata(self, task_id: str, title: str, image_bytes: bytes) -> None:
        row = self.task_rows.get(task_id)
        if row is None:
            return
        item = self.queue_table.item(row, 0)
        task = self.tasks.get(task_id)
        if task is not None:
            task["title"] = title
        if item:
            item.setToolTip(self.tasks[task_id]["url"])
        cell = self.download_cells.get(task_id)
        if cell is not None:
            cell.set_title(title)
            cell.set_thumbnail_bytes(image_bytes)
            duration_label = _format_clock(self.tasks[task_id].get("duration")) if self.tasks[task_id].get("duration") is not None else "Duración no disponible"
            cell.set_subtitle(f"{duration_label}  ·  {self.tasks[task_id].get('quality', 'Mejor disponible')}  ·  {self.tasks[task_id].get('output_format', 'MPG')}  ·  Descargando")

    def _on_download_progress(self, task_id: str, percent: int, speed: str, eta: str, state: str) -> None:
        row = self.task_rows.get(task_id)
        if row is None:
            return
        bar = self.download_progress_bars.get(task_id)
        if bar is not None:
            bar.setValue(percent)
        self.queue_table.item(row, 4).setText(speed)
        self.queue_table.item(row, 5).setText(eta)
        if self.tasks.get(task_id, {}).get("status") == "Cancelando…":
            self.queue_status.setText("Cancelación solicitada; esperando a que el proceso cierre de forma segura…")
        else:
            self._set_task_status(task_id, state)
            title = self.tasks.get(task_id, {}).get("title") or self.tasks.get(task_id, {}).get("url", "Descarga")
            self.queue_status.setText(f"{state}: {title}")
        self._refresh_summary()

    def _set_task_status(self, task_id: str, status: str) -> None:
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = status
        row = self.task_rows.get(task_id)
        if row is not None and self.queue_table.item(row, 6):
            self.queue_table.item(row, 6).setText(status)
        cell = self.download_cells.get(task_id)
        if cell is not None:
            task = self.tasks.get(task_id, {})
            duration_label = _format_clock(task.get("duration")) if task.get("duration") is not None else "Duración pendiente"
            cell.set_subtitle(f"{duration_label}  ·  {task.get('quality', 'Mejor disponible')}  ·  {task.get('output_format', 'MPG')}  ·  {status}")
        if row is not None:
            format_editor = self.download_format_editors.get(task_id)
            if format_editor is not None:
                format_editor.setEnabled(status == "Pendiente")

    def _on_download_succeeded(self, task_id: str, path: str) -> None:
        if task_id in self.tasks:
            self.tasks[task_id]["path"] = path
        row = self.task_rows.get(task_id)
        if row is not None:
            bar = self.download_progress_bars.get(task_id)
            if bar is not None:
                bar.setValue(100)
            self.queue_table.item(row, 4).setText("—")
            self.queue_table.item(row, 5).setText("—")
            self.queue_table.item(row, 0).setToolTip(path)
        self._set_task_status(task_id, "Completado")
        self.queue_status.setText(f"Archivo guardado: {path}")
        self._refresh_summary()

    def _on_download_failed(self, task_id: str, message: str) -> None:
        self._set_task_status(task_id, "Error")
        row = self.task_rows.get(task_id)
        if row is not None:
            self.queue_table.item(row, 6).setToolTip(message)
            self.queue_table.item(row, 0).setToolTip(self.tasks[task_id]["url"] + "\n\n" + message)
        self.queue_status.setText(f"Error en una descarga: {message[:220]}")
        self._refresh_summary()

    def _on_download_cancelled(self, task_id: str, message: str) -> None:
        self._set_task_status(task_id, "Cancelada")
        row = self.task_rows.get(task_id)
        if row is not None:
            self.queue_table.item(row, 6).setToolTip(message)
            self.queue_table.item(row, 0).setToolTip(self.tasks[task_id]["url"] + "\n\n" + message)
            self.queue_table.item(row, 4).setText("—")
            self.queue_table.item(row, 5).setText("—")
        self.queue_status.setText(message)
        self._refresh_summary()

    def _on_download_worker_finished(self) -> None:
        if self.active_worker is not None:
            self.active_worker.deleteLater()
            self.active_worker = None
        self._refresh_summary()
        if self.download_queue_started:
            QTimer.singleShot(200, self._start_next_download)

    def _cancel_selected_downloads(self) -> None:
        rows = sorted({index.row() for index in self.queue_table.selectionModel().selectedRows()})
        if not rows:
            QMessageBox.information(self, "Selecciona una descarga", "Selecciona en la cola la descarga o las descargas que deseas cancelar.")
            return

        active_id = self.active_worker.task["id"] if self.active_worker is not None and self.active_worker.isRunning() else None
        cancelled_pending = 0
        active_requested = False
        for row in rows:
            item = self.queue_table.item(row, 0)
            if item is None:
                continue
            task_id = item.data(Qt.UserRole)
            task = self.tasks.get(task_id)
            if not task:
                continue
            status = task.get("status")
            if status == "Pendiente":
                self._set_task_status(task_id, "Cancelada")
                cancelled_pending += 1
            elif task_id == active_id and status in ("Preparando", "Descargando", "Convirtiendo", "Cancelando…"):
                self.active_worker.requestInterruption()
                self._set_task_status(task_id, "Cancelando…")
                active_requested = True

        self._refresh_summary()
        if active_requested and cancelled_pending:
            self.queue_status.setText(f"Cancelación solicitada para el proceso activo; {cancelled_pending} descarga(s) pendiente(s) cancelada(s).")
        elif active_requested:
            self.queue_status.setText("Cancelación solicitada. MediaFlow detendrá este proceso y continuará con la siguiente descarga no cancelada.")
        elif cancelled_pending:
            self.queue_status.setText(f"Se cancelaron {cancelled_pending} descarga(s) pendientes. Los demás elementos no se modificaron.")
        else:
            self.queue_status.setText("Selecciona una descarga pendiente o la descarga activa para cancelarla.")

    def _remove_selected_tasks(self) -> None:
        rows = sorted({index.row() for index in self.queue_table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            item = self.queue_table.item(row, 0)
            if not item:
                continue
            task_id = item.data(Qt.UserRole)
            task = self.tasks.get(task_id)
            if task and task["status"] in ("Preparando", "Descargando", "Convirtiendo", "Cancelando…"):
                continue
            self.queue_table.removeRow(row)
            self.tasks.pop(task_id, None)
            self.task_rows.pop(task_id, None)
            self.download_cells.pop(task_id, None)
            self.download_format_editors.pop(task_id, None)
            self.download_progress_bars.pop(task_id, None)
        self._reindex_rows()
        self._refresh_summary()

    def _clear_completed(self) -> None:
        for row in reversed(range(self.queue_table.rowCount())):
            item = self.queue_table.item(row, 0)
            if not item:
                continue
            task_id = item.data(Qt.UserRole)
            task = self.tasks.get(task_id)
            if task and task["status"] in ("Completado", "Error", "Cancelada"):
                self.queue_table.removeRow(row)
                self.tasks.pop(task_id, None)
                self.task_rows.pop(task_id, None)
                self.download_cells.pop(task_id, None)
                self.download_format_editors.pop(task_id, None)
                self.download_progress_bars.pop(task_id, None)
        self._reindex_rows()
        self._refresh_summary()

    def _reindex_rows(self) -> None:
        self.task_rows.clear()
        for row in range(self.queue_table.rowCount()):
            item = self.queue_table.item(row, 0)
            if item:
                self.task_rows[item.data(Qt.UserRole)] = row

    def _refresh_summary(self) -> None:
        if not hasattr(self, "total_value"):
            return
        values = list(self.tasks.values())
        completed = sum(1 for task in values if task["status"] == "Completado")
        active = sum(1 for task in values if task["status"] in ("Procesando información", "Preparando", "Descargando", "Convirtiendo", "Cancelando…"))
        self.total_value.setText(str(len(values)))
        self.done_value.setText(str(completed))
        self.active_value.setText(str(active))
        self.queue_summary.setText(f"{len(values)} elementos")
        ready = any(task["status"] == "Pendiente" for task in values)
        processing = any(task["status"] == "Procesando información" for task in values)
        running = self.active_worker is not None and self.active_worker.isRunning()
        self.start_queue_button.setEnabled(ready and not processing and not running)

    def _choose_source_files(self) -> None:
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar archivos multimedia",
            str(Path.home()),
            "Archivos multimedia (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.mpeg *.mpg *.m4v *.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus);;Todos los archivos (*.*)",
        )
        if filenames:
            self._scan_and_add_paths([Path(name) for name in filenames])

    def _choose_source_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta con videos o audios", str(Path.home()))
        if folder:
            self._scan_and_add_paths([Path(folder)])

    def _scan_and_add_paths(self, paths: list[Path]) -> None:
        if self.folder_scan_worker is not None and self.folder_scan_worker.isRunning():
            QMessageBox.information(self, "Análisis en curso", "Espera a que termine el análisis de la carpeta actual.")
            return
        recursive = bool(self.include_subfolders.isChecked()) if hasattr(self, "include_subfolders") else True
        self.browse_files_button.setEnabled(False)
        self.browse_folder_button.setEnabled(False)
        self.convert_status.setText("Analizando archivos y carpetas en segundo plano…")
        self.folder_scan_worker = FolderScanWorker(paths, recursive)
        self.folder_scan_worker.found.connect(self._on_folder_scan_found)
        self.folder_scan_worker.scanError.connect(self._on_folder_scan_error)
        self.folder_scan_worker.finished.connect(self._on_folder_scan_finished)
        self.folder_scan_worker.start()

    def _on_folder_scan_found(self, raw_paths: list) -> None:
        paths = [Path(raw) for raw in raw_paths]
        before = len(self.selected_files)
        self._set_selected_files(paths)
        added = len(self.selected_files) - before
        if added:
            self.convert_status.setText(f"Se agregaron {added} archivo(s). Total: {len(self.selected_files)}. Las miniaturas se están generando en segundo plano.")
        else:
            self.convert_status.setText("No se encontraron archivos multimedia nuevos en la selección.")
        if self.selected_files:
            self.tabs.setCurrentIndex(1)

    def _on_folder_scan_error(self, message: str) -> None:
        self.convert_status.setText("El análisis terminó con algunas carpetas no accesibles.")
        QMessageBox.information(self, "Carpetas omitidas", message)

    def _on_folder_scan_finished(self) -> None:
        self.browse_files_button.setEnabled(True)
        self.browse_folder_button.setEnabled(True)
        if self.folder_scan_worker is not None:
            self.folder_scan_worker.deleteLater()
            self.folder_scan_worker = None

    def _set_selected_files(self, paths: list[Path]) -> None:
        existing = {str(path.resolve()).casefold() for path in self.selected_files}
        newly_added: list[Path] = []
        for path in paths:
            try:
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    key = str(path.resolve()).casefold()
                    if key not in existing:
                        self.selected_files.append(path)
                        existing.add(key)
                        try:
                            size = path.stat().st_size
                            size_text = f" · {size / (1024 ** 3):.2f} GB" if size >= 1024 ** 3 else f" · {size / (1024 ** 2):.0f} MB"
                        except OSError:
                            size_text = ""
                        item = QListWidgetItem(path.name)
                        item.setToolTip(str(path))
                        item.setData(Qt.UserRole, str(path))
                        item.setData(Qt.UserRole + 2, self.convert_format.currentText())
                        item.setSizeHint(QSize(0, 82))
                        self.file_list.addItem(item)
                        self.file_items_by_path[key] = item
                        row_widget = ConversionRowWidget(
                            self.file_list, item, path, self.convert_format.currentText()
                        )
                        row_widget.details_label.setText(f"{size_text.lstrip(' · ')}  ·  {path.parent}" if size_text else str(path.parent))
                        row_widget.details_label.setToolTip(str(path))
                        self.file_list.setItemWidget(item, row_widget)
                        self.conversion_rows_by_path[key] = row_widget
                        newly_added.append(path)
            except (OSError, PermissionError):
                continue
        self.convert_count.setText(f"{len(self.selected_files)} archivos")
        # La sección Convertir ya no genera miniaturas.

    def _queue_thumbnail_generation(self, paths: list[Path]) -> None:
        known = {str(path.resolve()).casefold() for path in self.thumbnail_pending}
        for path in paths:
            key = str(path.resolve()).casefold()
            if key not in known:
                self.thumbnail_pending.append(path)
                known.add(key)
        self._start_thumbnail_worker()

    def _start_thumbnail_worker(self) -> None:
        if self.thumbnail_worker is not None and self.thumbnail_worker.isRunning():
            return
        if not self.thumbnail_pending:
            return
        batch = self.thumbnail_pending
        self.thumbnail_pending = []
        self.thumbnail_worker = ThumbnailWorker(batch)
        self.thumbnail_worker.thumbnailReady.connect(self._on_thumbnail_ready)
        self.thumbnail_worker.finished.connect(self._on_thumbnail_worker_finished)
        self.thumbnail_worker.start()

    def _on_thumbnail_ready(self, source_path: str, thumbnail_path: str) -> None:
        key = str(Path(source_path).resolve()).casefold()
        row_widget = self.conversion_rows_by_path.get(key)
        if row_widget is None:
            return
        row_widget.set_thumbnail(thumbnail_path)

    def _on_thumbnail_worker_finished(self) -> None:
        worker = self.thumbnail_worker
        self.thumbnail_worker = None
        if worker is not None:
            worker.deleteLater()
        if self.thumbnail_pending:
            QTimer.singleShot(100, self._start_thumbnail_worker)

    def _handle_dropped_files(self, raw_paths: list[str]) -> None:
        paths = [Path(raw) for raw in raw_paths]
        candidates = [path for path in paths if path.is_file() or path.is_dir()]
        if not candidates:
            QMessageBox.information(self, "Formato no reconocido", "Suelta archivos multimedia o carpetas que contengan archivos compatibles.")
            return
        self._scan_and_add_paths(candidates)

    def _update_fat32_profile_hint(self, *_args) -> None:
        if not hasattr(self, "convert_profile_hint"):
            return
        quality = self.convert_quality.currentText() if hasattr(self, "convert_quality") else "Equilibrada"
        if self.fat32_mode.isChecked():
            target = VIDEO_QUALITY_SETTINGS.get(quality, VIDEO_QUALITY_SETTINGS["Equilibrada"])["fat32_gib"]
            self.convert_profile_hint.setText(
                f"FAT32: máximo 4 GiB − 1 byte por archivo. MediaFlow usará dos pasadas y apuntará a "
                f"aprox. {target:.1f} GiB con el perfil {quality}. El tamaño final depende del video y debe comprobarse."
            )
        else:
            self.convert_profile_hint.setText(
                "Los ajustes de resolución y compresión se aplican a todo el lote. "
                "El formato sigue siendo editable en cada fila. Para FAT32, activa la casilla y usa 720p o 480p en videos largos."
            )

    def _update_conversion_controls(self) -> None:
        running = self.conversion_worker is not None and self.conversion_worker.isRunning()
        selected = bool(self.file_list.selectedItems()) if hasattr(self, "file_list") else False
        if hasattr(self, "cancel_selected_conversion_button"):
            self.cancel_selected_conversion_button.setEnabled(running and selected)

    def _on_conversion_selection_changed(self) -> None:
        for row_widget in self.conversion_rows_by_path.values():
            row_widget.set_selected_look(row_widget.item.isSelected())
        self._update_conversion_controls()

    def _apply_format_to_selected(self) -> None:
        selected = self.file_list.selectedItems()
        if not selected:
            QMessageBox.information(
                self,
                "Selecciona videos",
                "Selecciona una o varias filas y vuelve a pulsar 'Aplicar a seleccionados'.",
            )
            return
        output_format = self.convert_format.currentText()
        for item in selected:
            try:
                key = str(Path(item.data(Qt.UserRole)).resolve()).casefold()
            except (TypeError, OSError):
                continue
            row_widget = self.conversion_rows_by_path.get(key)
            if row_widget is not None:
                row_widget.set_format(output_format)
                row_widget.set_status(f"Formato asignado · {output_format}")
        self.convert_status.setText(
            f"Se asignó {output_format} a {len(selected)} archivo(s). También puedes cambiar cada formato directamente en su fila."
        )

    def _cancel_selected_conversions(self) -> None:
        worker = self.conversion_worker
        if worker is None or not worker.isRunning():
            return
        paths: list[Path] = []
        for item in self.file_list.selectedItems():
            try:
                paths.append(Path(item.data(Qt.UserRole)))
            except (TypeError, ValueError):
                continue
        if not paths:
            return
        count = worker.cancel_paths(paths)
        if count:
            self.convert_status.setText(
                f"Se solicitó cancelar {count} archivo(s) seleccionado(s). "
                "Los demás archivos del lote continuarán."
            )
        else:
            self.convert_status.setText("Los archivos seleccionados ya terminaron o no están pendientes de conversión.")

    def _on_conversion_file_progress(self, raw_path: str, percent: int, detail: str) -> None:
        key = str(Path(raw_path).resolve()).casefold()
        row_widget = self.conversion_rows_by_path.get(key)
        if row_widget is not None:
            row_widget.set_progress(percent, f"Convirtiendo · {detail}")

    def _on_conversion_file_cancelled(self, raw_path: str) -> None:
        key = str(Path(raw_path).resolve()).casefold()
        item = self.file_items_by_path.get(key)
        if item is not None:
            item.setToolTip(f"{raw_path}\nCancelada para este lote. Puedes volver a incluirla en un lote nuevo.")
            item.setData(Qt.UserRole + 1, "cancelled")
        row_widget = self.conversion_rows_by_path.get(key)
        if row_widget is not None:
            row_widget.set_progress(0, "Cancelada")
            row_widget.progress_bar.setFormat("Cancelada")

    def _on_conversion_file_succeeded(self, raw_source: str, raw_destination: str) -> None:
        key = str(Path(raw_source).resolve()).casefold()
        item = self.file_items_by_path.get(key)
        if item is not None:
            item.setToolTip(f"Origen: {raw_source}\nResultado: {raw_destination}")
            item.setData(Qt.UserRole + 1, "completed")
        row_widget = self.conversion_rows_by_path.get(key)
        if row_widget is not None:
            destination = Path(raw_destination)
            try:
                size = destination.stat().st_size
                size_text = human_file_size(size)
            except OSError:
                size = 0
                size_text = "tamaño desconocido"
            if self.fat32_mode.isChecked() and destination.suffix.lower() != ".mp3":
                if size > FAT32_MAX_FILE_BYTES:
                    status = f"Completado · {size_text} · supera FAT32"
                    tooltip = f"{raw_destination}\nEl archivo supera el límite de un archivo FAT32. Elige un perfil más compacto o divide el video."
                else:
                    status = f"Completado · {size_text} · FAT32"
                    tooltip = f"{raw_destination}\nEl tamaño está por debajo del límite FAT32."
            else:
                status = f"Completado · {size_text} · {destination.suffix[1:].upper()}"
                tooltip = raw_destination
            row_widget.set_progress(100, status)
            row_widget.set_status(status, tooltip)

    def _on_conversion_file_failed(self, raw_source: str, message: str) -> None:
        key = str(Path(raw_source).resolve()).casefold()
        row_widget = self.conversion_rows_by_path.get(key)
        if row_widget is not None:
            row_widget.set_status("Error de conversión", message)
            row_widget.progress_bar.setFormat("Error")

    def _remove_selected_files(self) -> None:
        if self.conversion_worker is not None and self.conversion_worker.isRunning():
            QMessageBox.information(self, "Conversión en curso", "Para detener archivos durante la conversión, usa 'Cancelar seleccionados'.")
            return
        rows = sorted({index.row() for index in self.file_list.selectedIndexes()}, reverse=True)
        for row in rows:
            item = self.file_list.takeItem(row)
            if item is not None:
                try:
                    key = str(Path(item.data(Qt.UserRole)).resolve()).casefold()
                    self.file_items_by_path.pop(key, None)
                    self.conversion_rows_by_path.pop(key, None)
                except (TypeError, OSError):
                    pass
        self._sync_selected_files()

    def _clear_files(self) -> None:
        if (self.conversion_worker and self.conversion_worker.isRunning()) or (self.folder_scan_worker and self.folder_scan_worker.isRunning()):
            return
        self.file_list.clear()
        self.selected_files.clear()
        self.file_items_by_path.clear()
        self.conversion_rows_by_path.clear()
        self.thumbnail_pending.clear()
        self.convert_count.setText("0 archivos")
        self.convert_progress.setValue(0)
        self.convert_status.setText("Lista vacía.")

    def _sync_selected_files(self) -> None:
        self.selected_files = [Path(self.file_list.item(i).data(Qt.UserRole)) for i in range(self.file_list.count())]
        self.file_items_by_path = {
            str(path.resolve()).casefold(): self.file_list.item(index)
            for index, path in enumerate(self.selected_files)
        }
        self.convert_count.setText(f"{len(self.selected_files)} archivos")

    def _start_conversion(self) -> None:
        if self.conversion_worker is not None and self.conversion_worker.isRunning():
            return
        if not self.selected_files:
            QMessageBox.information(self, "No hay archivos", "Primero selecciona o arrastra uno o varios archivos.")
            return
        if not find_ffmpeg():
            QMessageBox.warning(self, "FFmpeg no detectado", "Instala FFmpeg y vuelve a abrir MediaFlow.")
            return
        jobs: list[tuple[Path, str, str, str, bool]] = []
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            source = Path(item.data(Qt.UserRole))
            output_format = str(item.data(Qt.UserRole + 2) or self.convert_format.currentText()).upper()
            if output_format not in OUTPUT_FORMATS:
                output_format = self.convert_format.currentText()
                item.setData(Qt.UserRole + 2, output_format)
            jobs.append((
                source,
                output_format,
                self.convert_resolution.currentText(),
                self.convert_quality.currentText(),
                bool(self.fat32_mode.isChecked() and output_format != "MP3"),
            ))

        resolution = self.convert_resolution.currentText()
        compression = self.convert_quality.currentText()
        fat32_enabled = self.fat32_mode.isChecked()

        self.convert_button.setEnabled(False)
        self.cancel_conversion_button.setEnabled(True)
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            item.setData(Qt.UserRole + 1, None)
            source = Path(item.data(Qt.UserRole))
            item.setToolTip(str(source))
            row_widget = self.conversion_rows_by_path.get(str(source.resolve()).casefold())
            if row_widget is not None:
                row_widget.progress_bar.setValue(0)
                row_widget.progress_bar.setFormat("En cola")
                row_widget.set_status(
                    f"En cola · {item.data(Qt.UserRole + 2) or self.convert_format.currentText()} · "
                    f"{resolution} · {compression}" + (" · FAT32" if fat32_enabled and (item.data(Qt.UserRole + 2) or self.convert_format.currentText()) != "MP3" else "")
                )
                row_widget.format_combo.setEnabled(False)
        self.convert_format.setEnabled(False)
        self.convert_resolution.setEnabled(False)
        self.convert_quality.setEnabled(False)
        self.fat32_mode.setEnabled(False)
        self.convert_progress.setValue(0)
        self.convert_progress.setFormat("%p%")
        profile_note = f"{resolution} · {compression}" + (" · objetivo FAT32" if fat32_enabled else "")
        self.convert_status.setText(f"Convirtiendo {len(self.selected_files)} archivo(s) · Perfil: {profile_note}. Puedes cancelar el lote sin cerrar MediaFlow.")
        self.conversion_worker = ConvertWorker(jobs, DEFAULT_CONVERTED)
        self.conversion_worker.progress.connect(self._conversion_progress)
        self.conversion_worker.fileProgress.connect(self._on_conversion_file_progress)
        self.conversion_worker.succeeded.connect(self._conversion_succeeded)
        self.conversion_worker.failed.connect(self._conversion_failed)
        self.conversion_worker.cancelled.connect(self._conversion_cancelled)
        self.conversion_worker.fileCancelled.connect(self._on_conversion_file_cancelled)
        self.conversion_worker.fileSucceeded.connect(self._on_conversion_file_succeeded)
        self.conversion_worker.fileFailed.connect(self._on_conversion_file_failed)
        self.conversion_worker.finished.connect(self._conversion_finished)
        self.conversion_worker.start()
        self._update_conversion_controls()

    def _cancel_conversion_batch(self) -> None:
        if self.conversion_worker is None or not self.conversion_worker.isRunning():
            return
        self.cancel_conversion_button.setEnabled(False)
        self.convert_status.setText("Cancelando la conversión actual… FFmpeg está cerrando el proceso y eliminando el archivo incompleto.")
        self.conversion_worker.requestInterruption()

    def _conversion_cancelled(self, message: str) -> None:
        self.convert_status.setText(message + f"\nCarpeta de resultados: {DEFAULT_CONVERTED}")
        self.convert_progress.setFormat("Cancelada")

    def _conversion_progress(self, percent: int, message: str) -> None:
        self.convert_progress.setValue(percent)
        self.convert_status.setText(message)

    def _conversion_succeeded(self, results: str) -> None:
        paths = [path for path in results.splitlines() if path]
        if paths:
            self.convert_status.setText(f"Se crearon {len(paths)} archivo(s).\nCarpeta: {DEFAULT_CONVERTED}\nÚltimo archivo: {paths[-1]}")
        else:
            self.convert_status.setText("No se generaron archivos.")

    def _conversion_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Algunas conversiones fallaron", message)

    def _conversion_finished(self) -> None:
        self.convert_button.setEnabled(True)
        self.convert_format.setEnabled(True)
        self.convert_resolution.setEnabled(True)
        self.convert_quality.setEnabled(True)
        self.fat32_mode.setEnabled(True)
        self.cancel_conversion_button.setEnabled(False)
        self.cancel_selected_conversion_button.setEnabled(False)
        for row_widget in self.conversion_rows_by_path.values():
            row_widget.format_combo.setEnabled(True)
        if self.conversion_worker is not None:
            self.conversion_worker.deleteLater()
            self.conversion_worker = None
        if self.convert_progress.format() != "Cancelada":
            self.convert_status.setText(self.convert_status.text() + "\nConversión finalizada.")

    def closeEvent(self, event) -> None:  # noqa: N802
        active = self.active_worker and self.active_worker.isRunning()
        previewing = self.preview_worker and self.preview_worker.isRunning()
        converting = self.conversion_worker and self.conversion_worker.isRunning()
        scanning = self.folder_scan_worker and self.folder_scan_worker.isRunning()
        thumbnailing = self.thumbnail_worker and self.thumbnail_worker.isRunning()
        musicing = self.music_worker and self.music_worker.isRunning()
        music_downloading = self.music_download_worker and self.music_download_worker.isRunning()
        covering = self.music_cover_worker and self.music_cover_worker.isRunning()
        if active or previewing or converting or musicing or music_downloading or covering or scanning or thumbnailing:
            answer = QMessageBox.question(
                self,
                "Procesos activos",
                "Hay una descarga, consulta de miniaturas, conversión o análisis de archivos en marcha. ¿Seguro que quieres cerrar MediaFlow?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            if active and self.active_worker is not None:
                self.active_worker.requestInterruption()
                self.active_worker.wait(8000)
            if previewing and self.preview_worker is not None:
                self.preview_worker.requestInterruption()
                self.preview_worker.wait(25000)
            if converting and self.conversion_worker is not None:
                self.conversion_worker.requestInterruption()
                self.conversion_worker.wait(8000)
            if musicing and self.music_worker is not None:
                self.music_worker.requestInterruption()
                self.music_worker.wait(8000)
            if music_downloading and self.music_download_worker is not None:
                self.music_download_worker.requestInterruption()
                self.music_download_worker.wait(25000)
            if covering and self.music_cover_worker is not None:
                self.music_cover_worker.requestInterruption()
                self.music_cover_worker.wait(8000)
            if thumbnailing and self.thumbnail_worker is not None:
                self.thumbnail_worker.requestInterruption()
                self.thumbnail_worker.wait(25000)
        event.accept()


STYLE = """
QMainWindow, QWidget#appRoot { background: #030712; color: #e5e7eb; font-family: Segoe UI; font-size: 9pt; }
QWidget { color: #e5e7eb; font-family: Segoe UI; }
QLabel#logoMark { background: #2563eb; color: #ffffff; border-radius: 13px; font-size: 20pt; font-weight: 800; }
QLabel#appTitle { color: #f9fafb; font-size: 19pt; font-weight: 750; }
QLabel#appSubtitle { color: #6b7280; font-size: 6.8pt; font-weight: 650; }
QLabel#engineBadge { color: #86efac; background: #10251c; border: 1px solid #1f5137; border-radius: 11px; padding: 8px 11px; font-weight: 650; }
QLabel#footerHint, QLabel#versionLabel { color: #4b5563; font-size: 7.5pt; font-weight: 700; }
QFrame#surfaceCard, QFrame#profileCard { background: #111827; border: 1px solid #263244; border-radius: 13px; }
QFrame#metricCard { background: #0f1726; border: 1px solid #202c3e; border-radius: 10px; }
QLabel#metricCaption { color: #9ca3af; font-size: 7pt; font-weight: 700; }
QLabel#metricValue { color: #f9fafb; font-size: 11pt; font-weight: 750; }
QLabel#cardTitle, QLabel#pageTitle { color: #f9fafb; font-size: 14pt; font-weight: 700; }
QLabel#fieldCaption { color: #9ca3af; font-size: 7pt; font-weight: 750; letter-spacing: .4px; }
QLabel#pathValue { color: #9ca3af; font-size: 8pt; }
QLabel#finePrint { color: #6b7280; font-size: 8pt; }
QLabel#profileHint { color: #9ca3af; font-size: 7.6pt; padding-top: 1px; }
QLabel#mutedLabel { color: #9ca3af; }
QLabel#countPill { color: #bfdbfe; background: #172554; border: 1px solid #1e40af; border-radius: 10px; padding: 7px 11px; font-weight: 650; }
QLabel#dropIcon { color: #60a5fa; font-size: 26pt; font-weight: 300; }
QLabel#dropTitle { color: #eff6ff; font-size: 11pt; font-weight: 650; }
QLabel#dropHint { color: #60a5fa; background: #172554; border: 1px solid #1d4ed8; border-radius: 8px; padding: 8px 10px; font-size: 7.5pt; font-weight: 750; }
QLabel#conversionFileTitle { color: #f3f4f6; font-size: 9.5pt; font-weight: 700; }
QLabel#conversionFileDetails { color: #9ca3af; font-size: 7.8pt; }
QLabel#conversionFileStatus { color: #60a5fa; font-size: 7.8pt; font-weight: 600; }
QLabel#queueFileTitle { color: #f3f4f6; font-size: 8.8pt; font-weight: 650; }
QLabel#queueFileSubtitle { color: #9ca3af; font-size: 7.7pt; }
QFrame#rowSeparator { color: #263244; background: #263244; max-width: 1px; }
QFrame#dropCard { background: #0b1930; border: 1px dashed #315a9a; border-radius: 14px; }
QLineEdit, QComboBox, QSpinBox { background: #0b1220; color: #f3f4f6; border: 1px solid #374151; border-radius: 8px; padding: 6px 8px; min-height: 20px; selection-background-color: #2563eb; }
QTableWidget QComboBox { padding: 3px 6px; min-height: 18px; border-radius: 7px; }
QLineEdit#heroUrlInput { background: #0b1220; border: 1px solid #374151; border-radius: 10px; padding: 12px 14px; font-size: 10pt; min-height: 24px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #3b82f6; }
QComboBox QAbstractItemView { background: #111827; color: #f3f4f6; selection-background-color: #1d4ed8; border: 1px solid #374151; }
QCheckBox { color: #d1d5db; spacing: 8px; padding: 3px 0; }
QCheckBox::indicator { width: 17px; height: 17px; }
QCheckBox::indicator:unchecked { background: #0b1220; border: 1px solid #4b5563; border-radius: 4px; }
QCheckBox::indicator:checked { background: #2563eb; border: 1px solid #3b82f6; border-radius: 4px; }
QPushButton { background: #1f2937; color: #e5e7eb; border: 1px solid #374151; border-radius: 8px; padding: 8px 12px; font-weight: 600; }
QPushButton:hover { background: #273449; border-color: #4b5563; }
QPushButton:pressed { background: #111827; }
QPushButton:disabled { color: #6b7280; background: #111827; border-color: #263244; }
QPushButton#primaryButton { background: #2563eb; color: #ffffff; border: 1px solid #3b82f6; padding: 10px 16px; font-size: 9pt; font-weight: 750; }
QPushButton#primaryButton:hover { background: #1d4ed8; }
QPushButton#secondaryAccentButton { background: #1d4ed8; color: #ffffff; border: 1px solid #2563eb; padding: 10px 16px; }
QPushButton#secondaryAccentButton:hover { background: #2563eb; }
QPushButton#dangerButton { background: #2a1720; color: #fda4af; border: 1px solid #713044; }
QPushButton#dangerButton:hover { background: #3b1725; border-color: #9f3450; }
QPushButton#quietButton { background: #111827; border-color: #303b4d; }
QFrame#navGroup { background: #111827; border: 1px solid #273244; border-radius: 21px; }
QPushButton#navButton { background: transparent; color: #9ca3af; border: 1px solid transparent; border-radius: 17px; padding: 8px 17px; font-weight: 650; }
QPushButton#navButton:hover:!checked { background: #1f2937; color: #f3f4f6; }
QPushButton#navButton:checked { background: #2563eb; color: #ffffff; border-color: #3b82f6; }
QTabWidget::pane { border: 1px solid #263244; border-radius: 14px; top: -1px; background: #070d19; }
QTableWidget, QListWidget { background: #0b1220; alternate-background-color: #0d1627; color: #e5e7eb; border: 1px solid #263244; border-radius: 10px; padding: 4px; outline: 0; }
QTableWidget::item, QListWidget::item { padding: 2px 4px; border: none; }
QTableWidget::item:selected, QListWidget::item:selected { background: #172554; color: #eff6ff; }
QListWidget::item { border: 1px solid transparent; border-radius: 10px; padding: 1px; }
QListWidget::item:selected { background: #172554; border: 1px solid #3b82f6; }
QWidget#conversionRow { background: #111827; border: 1px solid #273244; border-radius: 9px; }
QWidget#conversionRow[selectedRow="true"] { background: #172554; border: 1px solid #3b82f6; }
QHeaderView::section { background: #111827; color: #9ca3af; border: none; border-bottom: 1px solid #273244; padding: 7px 6px; font-size: 7pt; font-weight: 750; }
QProgressBar { background: #1f2937; color: #e5e7eb; border: 1px solid #374151; border-radius: 6px; min-height: 12px; max-height: 14px; text-align: center; font-size: 7.5pt; }
QProgressBar::chunk { background: #3b82f6; border-radius: 5px; }
QScrollBar:vertical { background: #0b1220; width: 11px; margin: 4px 2px 4px 2px; border-radius: 5px; }
QScrollBar::handle:vertical { background: #374151; min-height: 28px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #4b5563; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
"""



def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(f"{APP_NAME} {APP_VERSION}")
    icon_path = resource_path("mediaflow.ico")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MediaFlowWindow()
    if icon_path.is_file():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
