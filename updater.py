"""PySide worker threads for MediaFlow's GitHub Releases updater."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from update_core import download_verified_installer, fetch_latest_update


class UpdateCheckWorker(QThread):
    update_available = Signal(dict)
    up_to_date = Signal()
    failed = Signal(str)

    def __init__(self, repository: str, current_version: str, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.current_version = current_version

    def run(self) -> None:
        try:
            info = fetch_latest_update(self.repository, self.current_version)
            if info is None:
                self.up_to_date.emit()
            else:
                self.update_available.emit(info.to_dict())
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateDownloadWorker(QThread):
    progress = Signal(int)
    completed = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, update_info: dict, destination: Path, parent=None):
        super().__init__(parent)
        self.update_info = dict(update_info)
        self.destination = Path(destination)

    def run(self) -> None:
        try:
            path = download_verified_installer(
                self.update_info,
                self.destination,
                progress_callback=self.progress.emit,
                cancel_callback=self.isInterruptionRequested,
            )
            self.completed.emit(str(path))
        except InterruptedError:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
