"""Fast cached thumbnails for the project Assets workspace."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImageReader, QPainter, QPen, QPixmap

from tech_connector.game_engine.assets import AssetTypeDescriptor


class AssetThumbnailService:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, int, int, str], QIcon] = {}

    def icon(self, path: str | Path, descriptor: AssetTypeDescriptor, *, size: int = 44) -> QIcon:
        source = Path(path)
        try:
            modified = int(source.stat().st_mtime_ns)
        except OSError:
            modified = 0
        key = (str(source).casefold(), modified, int(size), descriptor.type_id)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        icon = self._image_icon(source, size) if descriptor.previewer_id in {"image", "video"} else QIcon()
        if icon.isNull():
            icon = self._type_icon(descriptor, size)
        self._cache[key] = icon
        return icon

    @staticmethod
    def _image_icon(path: Path, size: int) -> QIcon:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        reader.setScaledSize(QSize(size * 2, size * 2))
        image = reader.read()
        if image.isNull():
            return QIcon()
        canvas = QPixmap(size, size)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        scaled = QPixmap.fromImage(image).scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = (scaled.width() - size) // 2
        y = (scaled.height() - size) // 2
        painter.drawPixmap(0, 0, scaled, x, y, size, size)
        painter.setPen(QPen(QColor(255, 255, 255, 55), 1))
        painter.drawRoundedRect(QRectF(0.5, 0.5, size - 1.0, size - 1.0), 5, 5)
        painter.end()
        return QIcon(canvas)

    @staticmethod
    def _type_icon(descriptor: AssetTypeDescriptor, size: int) -> QIcon:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        color = QColor(descriptor.color)
        painter.setBrush(color.darker(180))
        painter.setPen(QPen(color.lighter(125), 1))
        painter.drawRoundedRect(QRectF(1.0, 1.0, size - 2.0, size - 2.0), 7, 7)
        initials = "".join(word[0] for word in descriptor.display_name.split()[:2]).upper()
        painter.setPen(QColor("#f2f8fc"))
        painter.setFont(QFont("Segoe UI", max(8, int(size * 0.26)), QFont.DemiBold))
        painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, initials or "A")
        painter.end()
        return QIcon(pixmap)

