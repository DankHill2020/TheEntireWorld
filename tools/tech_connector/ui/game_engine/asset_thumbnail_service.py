"""Fast cached thumbnails for the project Assets workspace."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImageReader, QPainter, QPen, QPixmap

from tech_connector.game_engine.assets import AssetTypeDescriptor


class AssetThumbnailService:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, int, int, str, tuple[str, ...]], QIcon] = {}

    def icon(
        self, path: str | Path, descriptor: AssetTypeDescriptor, *, size: int = 44,
        badges: tuple[str, ...] = (),
    ) -> QIcon:
        source = Path(path)
        try:
            modified = int(source.stat().st_mtime_ns)
        except OSError:
            modified = 0
        normalized_badges = tuple(str(value) for value in badges if str(value))
        key = (str(source).casefold(), modified, int(size), descriptor.type_id, normalized_badges)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        icon = self._image_icon(source, size) if descriptor.previewer_id in {"image", "video"} else QIcon()
        if icon.isNull():
            icon = self._type_icon(descriptor, size)
        if normalized_badges:
            icon = self._badge_icon(icon, normalized_badges, size)
        self._cache[key] = icon
        return icon

    def invalidate(self, path: str | Path | None = None) -> None:
        """Drop one source thumbnail or the complete cache after reimport/cook."""

        if path is None:
            self._cache.clear()
            return
        target = str(Path(path)).casefold()
        self._cache = {key: value for key, value in self._cache.items() if key[0] != target}

    @staticmethod
    def _badge_icon(icon: QIcon, badges: tuple[str, ...], size: int) -> QIcon:
        pixmap = icon.pixmap(size, size)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        state = badges[0] if badges else ""
        cook = badges[1] if len(badges) > 1 else ""
        color = {"authored": "#62d6ff", "imported": "#ffca63", "source": "#9aa7b3"}.get(state, "#9aa7b3")
        painter.setBrush(QColor(color)); painter.setPen(QPen(QColor("#071018"), 1))
        painter.drawEllipse(QRectF(2, size - 12, 10, 10))
        if cook == "cooked":
            painter.setBrush(QColor("#69f0ae"))
            painter.drawEllipse(QRectF(size - 12, size - 12, 10, 10))
        painter.end()
        return QIcon(pixmap)

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

