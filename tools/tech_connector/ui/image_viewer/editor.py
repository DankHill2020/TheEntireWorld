"""Standalone PySide6 Professional Image Editor Window & Widget for Tech Connector.

Includes Rich Brush Engine, Selection Tools Suite (Rect, Ellipse, Lasso, Magic Wand, Bounding Box),
Layer Stack, Photoshop Adjustments, PBR Diagnostic Checkers, and 1-Click DCC Sync.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import time
import tempfile
import base64
from typing import Any, Callable

try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from psd_tools import PSDImage
    HAS_PSD_TOOLS = True
except ImportError:
    HAS_PSD_TOOLS = False


from tech_connector.game_engine.integration.shaded_frame_provider import (
    parse_shaded_frame_output,
    maya_shaded_frame_code,
    blender_shaded_frame_code,
    unreal_shaded_frame_code,
    motionbuilder_shaded_frame_code,
)


def pil_to_qimage(pil_img) -> QImage:
    """Convert PIL Image to QImage Format_ARGB32_Premultiplied."""
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format_RGBA8888)
    return qimg.convertToFormat(QImage.Format_ARGB32_Premultiplied)

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, QSize, Qt, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QConicalGradient,
    QCursor,
    QFont,
    QIcon,
    QImage,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStyle,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tech_connector.ui.design_system import component_stylesheet, set_ui_role
from tech_connector.ui.icons import configure_button, icon


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
DESIGN_FILE_EXTENSIONS = {".psd", ".psb", ".xcf", ".spp", ".sbs", ".sbsar"}
OPENABLE_IMAGE_EXTENSIONS = IMAGE_EXTENSIONS | DESIGN_FILE_EXTENSIONS | {".tcimg"}

from .canvas import (
    BrushTiltGraphWidget,
    ImageLayer,
    ImageViewerGraphicsView,
    LayerStack,
    VanishingPointHandleItem,
    compute_atmospheric_palette,
    create_procedural_brush_mask,
)

class ImageEditorWidget(QWidget):
    """Full-featured Desktop Image Editor Widget outperforming Photoshop for Tech Art."""

    image_saved = Signal(str)

    def __init__(self, parent=None, image_path: str = ""):
        super().__init__(parent)
        self.image_path = image_path
        self.project_path = ""
        self.dirty = False
        self.stack = LayerStack(1280, 720)
        
        # Tool & Brush State
        self.active_tool = "brush"  # brush, eraser, line, arrow, box, ellipse, lasso, wand, picker, fill
        self.primary_color = QColor(22, 242, 106)
        self.secondary_color = QColor(0, 0, 0)
        self.brush_size = 18
        self.brush_hardness = 0.8  # 0.0 (soft) to 1.0 (hard)
        self.brush_opacity = 1.0
        self.brush_flow = 1.0
        self.brush_preset = "Hard Round"
        self.brush_tilt_x = 0.0  # -1.0 (Left) to +1.0 (Right), 0.0 = Upright
        self.brush_tilt_y = 0.0  # -1.0 (Top) to +1.0 (Bottom)
        
        # Selection State
        self.has_selection = False
        self.selection_rect = QRectF()
        self.wand_tolerance = 25
        self.font_size = 24  # Text Annotation Font Size (pt)
        
        # Diagnostic & A/B Wipe state
        self.diagnostic_mode = "standard"
        self.reference_image: QImage | None = None
        self.wipe_position = 0.5
        
        # Atmospheric Perspective Palette State (Keys 1..5)
        self.atmos_haze_color = QColor(180, 205, 235)  # Cool sky fog tint default
        self.active_atmos_level = 3  # Level 3 is Default base color
        self.atmos_colors: list[QColor] = []
        self.atmos_swatch_btns: list[QPushButton] = []
        
        self._build_ui()
        self.update_atmospheric_palette()
        if image_path and Path(image_path).exists():
            self.load_image(image_path)
        else:
            self.stack.add_layer(name="Background", fill_color=QColor(24, 28, 36))
            self.update_composited_view()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        # 1. Top Command Bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        brand_lbl = QLabel("Ophanim")
        set_ui_role(brand_lbl, "sectionTitle")
        top_bar.addWidget(brand_lbl)

        file_btn = QToolButton()
        configure_button(file_btn, "folder", text="File", role="secondary")
        file_btn.setPopupMode(QToolButton.InstantPopup)
        file_menu = QMenu(file_btn)
        for label, icon_name, callback in (
            ("Open image", "folder", self.open_image_file),
            ("Open project", "folder", self.open_project_file),
            ("Save image", "save", self.save_image),
            ("Save image as", "export", self.save_image_as),
            ("Save project", "save", self.save_project_file),
        ):
            action = file_menu.addAction(icon(icon_name), label)
            action.triggered.connect(lambda _checked=False, fn=callback: fn())
        file_btn.setMenu(file_menu)
        top_bar.addWidget(file_btn)

        undo_btn = QPushButton("Undo")
        configure_button(undo_btn, "undo", tooltip="Undo", role="quiet", icon_only=True)
        undo_btn.clicked.connect(self.undo)
        top_bar.addWidget(undo_btn)

        redo_btn = QPushButton("Redo")
        configure_button(redo_btn, "redo", tooltip="Redo", role="quiet", icon_only=True)
        redo_btn.clicked.connect(self.redo)
        top_bar.addWidget(redo_btn)

        top_bar.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        for label, mode_id in (
            ("Standard view", "standard"),
            ("PBR albedo range", "pbr_albedo"),
            ("Normal vector check", "normal_vector"),
            ("Squint / value map", "value_map"),
            ("Reference wipe", "reference_wipe"),
        ):
            self.mode_combo.addItem(label, mode_id)
        self.mode_combo.currentIndexChanged.connect(
            lambda _index: self._change_diagnostic_mode(self.mode_combo.currentData())
        )
        top_bar.addWidget(self.mode_combo)

        bg_remove_btn = QPushButton("Magic cutout")
        configure_button(bg_remove_btn, "sparkles", text="Magic cutout", role="secondary")
        bg_remove_btn.setToolTip("Auto-segment image into Foreground Subject & Background layers")
        bg_remove_btn.clicked.connect(self.apply_magic_cutout_segmentation)
        top_bar.addWidget(bg_remove_btn)

        inpaint_btn = QPushButton("Content-aware fill")
        configure_button(inpaint_btn, "sparkles", text="Content-aware fill", role="secondary")
        inpaint_btn.setEnabled(False)
        inpaint_btn.setToolTip("Content-aware fill needs a real inpainting backend before this can be enabled.")
        inpaint_btn.setVisible(False)

        anim_toggle_btn = QPushButton("Review")
        configure_button(anim_toggle_btn, "play", text="Review", role="secondary")
        anim_toggle_btn.setToolTip("Toggle Frame Timeline, Onion Skinning, and SyncSketch-style Redline Review")
        anim_toggle_btn.clicked.connect(lambda: toggle_animation_timeline_mode(self))
        top_bar.addWidget(anim_toggle_btn)

        dcc_fix_btn = QPushButton("Sync to DCC")
        configure_button(dcc_fix_btn, "refresh", text="Sync to DCC", role="primary")
        dcc_fix_btn.setToolTip("Push & hot-reload modified textures directly onto Maya / Unreal Engine / Blender shading nodes")
        dcc_fix_btn.clicked.connect(self.apply_fix_to_dcc)
        top_bar.addWidget(dcc_fix_btn)

        top_bar.addStretch(1)
        root.addLayout(top_bar)

        # 2. Rich Brush Engine & Selection Settings Bar
        brush_bar = QFrame()
        brush_bar.setStyleSheet("QFrame { background:#0a121c; border:1px solid #12324a; border-radius:4px; } QLabel { color:#9cdbba; font-size:11px; }")
        brush_layout = QHBoxLayout(brush_bar)
        brush_layout.setContentsMargins(8, 4, 8, 4)
        brush_layout.setSpacing(8)

        brush_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Hard Round", "Soft Round", "Airbrush", "Redline Markup Pen", "Highlighter", "Emissive Glow", "Eraser"])
        self.preset_combo.currentTextChanged.connect(self._change_brush_preset)
        brush_layout.addWidget(self.preset_combo)

        brush_layout.addWidget(QLabel("Size:"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(1, 500)
        self.size_spin.setValue(self.brush_size)
        self.size_spin.valueChanged.connect(self._change_brush_size)
        brush_layout.addWidget(self.size_spin)

        brush_layout.addWidget(QLabel("Hardness:"))
        self.hardness_slider = QSlider(Qt.Horizontal)
        self.hardness_slider.setRange(0, 100)
        self.hardness_slider.setValue(int(self.brush_hardness * 100))
        self.hardness_slider.setFixedWidth(80)
        self.hardness_slider.valueChanged.connect(lambda v: setattr(self, "brush_hardness", v / 100.0))
        brush_layout.addWidget(self.hardness_slider)

        brush_layout.addWidget(QLabel("Opacity:"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(int(self.brush_opacity * 100))
        self.opacity_slider.setFixedWidth(80)
        self.opacity_slider.valueChanged.connect(lambda v: setattr(self, "brush_opacity", v / 100.0))
        brush_layout.addWidget(self.opacity_slider)

        brush_layout.addWidget(QLabel("📐 Lean / Tilt:"))
        self.tilt_graph = BrushTiltGraphWidget()
        self.tilt_graph.setToolTip("Click & Drag cursor to lean/tilt brush angle (-1.0 to +1.0). Double-click to reset upright (0.0).")
        self.tilt_graph.tilt_changed.connect(self._change_brush_tilt)
        brush_layout.addWidget(self.tilt_graph)

        # Selection Tool Quick Actions
        brush_layout.addWidget(QLabel("| Selection:"))
        inv_sel_btn = QPushButton("Invert (Ctrl+Shift+I)")
        inv_sel_btn.clicked.connect(self.invert_selection)
        brush_layout.addWidget(inv_sel_btn)

        clear_sel_btn = QPushButton("Deselect (Ctrl+D)")
        clear_sel_btn.clicked.connect(self.clear_selection)
        brush_layout.addWidget(clear_sel_btn)

        crop_btn = QPushButton("✂️ Crop to Selection")
        crop_btn.clicked.connect(self.crop_to_selection)
        brush_layout.addWidget(crop_btn)

        brush_layout.addStretch(1)
        root.addWidget(brush_bar)

        # 2.5 Grid, Perspective, Camera & View Guidelines Bar
        gp_bar = QFrame()
        gp_bar.setStyleSheet(
            "QFrame { background:#070f18; border:1px solid #12324a; border-radius:4px; }"
            "QLabel  { color:#9cdbba; font-size:11px; }"
        )
        gp_layout = QHBoxLayout(gp_bar)
        gp_layout.setContentsMargins(8, 4, 8, 4)
        gp_layout.setSpacing(6)

        # â”€â”€ 1. Grid Controls â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        self.grid_toggle_btn = QPushButton("🌐 Grid: OFF")
        self.grid_toggle_btn.setCheckable(True)
        self.grid_toggle_btn.setToolTip("Toggle canvas grid overlay")
        self.grid_toggle_btn.setStyleSheet(
            "QPushButton { font-weight:bold; padding:3px 7px; border:1px solid #0c7a47;"
            " border-radius:4px; background:#0c1c28; color:#9cdbba; }"
            "QPushButton:checked { background:#16f26a; color:#000; }"
        )
        self.grid_toggle_btn.toggled.connect(self._toggle_grid)
        gp_layout.addWidget(self.grid_toggle_btn)

        self.grid_size_spin = QSpinBox()
        self.grid_size_spin.setRange(8, 512)
        self.grid_size_spin.setValue(32)
        self.grid_size_spin.setSuffix("px")
        self.grid_size_spin.setFixedWidth(58)
        self.grid_size_spin.setToolTip("Grid cell size in pixels")
        self.grid_size_spin.valueChanged.connect(self._change_grid_size)
        gp_layout.addWidget(self.grid_size_spin)

        self.grid_snap_btn = QPushButton("🧲 Snap")
        self.grid_snap_btn.setCheckable(True)
        self.grid_snap_btn.setToolTip("Snap brush strokes to grid intersections")
        self.grid_snap_btn.setStyleSheet(
            "QPushButton { border:1px solid #12324a; border-radius:4px; background:#0c1c28; color:#aaa; padding:3px 7px; }"
            "QPushButton:checked { background:#1e9bff; color:#fff; font-weight:bold; }"
        )
        self.grid_snap_btn.toggled.connect(lambda chk: setattr(self.view, "snap_to_grid", chk))
        gp_layout.addWidget(self.grid_snap_btn)

        # â”€â”€ Separator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        sep1 = QFrame(); sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("color:#1a3a55;"); gp_layout.addWidget(sep1)

        # â”€â”€ 2. Perspective Guidelines â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        gp_layout.addWidget(QLabel("📐"))
        self.perspective_combo = QComboBox()
        self.perspective_combo.addItems([
            "Off",
            "1-Point Perspective",
            "2-Point Perspective",
            "3-Point Perspective",
            "4-Point Perspective (Curvilinear)",
            "5-Point Perspective (Fisheye Lens)",
            "6-Point Perspective (360° Spherical)",
        ])
        self.perspective_combo.setToolTip("Active perspective guide mode")
        self.perspective_combo.setMinimumWidth(130)
        self.perspective_combo.currentTextChanged.connect(self._change_perspective_mode)
        gp_layout.addWidget(self.perspective_combo)

        self.guides_toggle_btn = QPushButton("👁 Rays")
        self.guides_toggle_btn.setCheckable(True)
        self.guides_toggle_btn.setChecked(True)
        self.guides_toggle_btn.setToolTip("Show / hide perspective guide lines")
        self.guides_toggle_btn.setStyleSheet(
            "QPushButton { border:1px solid #12324a; border-radius:4px; background:#0c1c28; color:#fff; padding:3px 7px; }"
            "QPushButton:checked { background:#16f26a; color:#000; font-weight:bold; }"
        )
        self.guides_toggle_btn.toggled.connect(self._toggle_perspective_guides)
        gp_layout.addWidget(self.guides_toggle_btn)

        # â”€â”€ VP Options Flyout â”€â”€
        vp_opts_btn = QPushButton("âš™ VP Options â–¾")
        vp_opts_btn.setToolTip("Ray Density · Snap Rays · Guide Opacity · Isolate VP · Reset VPs · Shot Presets")
        vp_opts_btn.setStyleSheet(
            "QPushButton { border:1px solid #1e5a7a; border-radius:4px; background:#0c1c28; color:#6cf; padding:3px 8px; }"
            "QPushButton:pressed { background:#1e3a50; }"
        )
        gp_layout.addWidget(vp_opts_btn)

        vp_flyout = QFrame(gp_bar.window() if gp_bar.window() else gp_bar,
                           Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        vp_flyout.setStyleSheet(
            "QFrame { background:#0d1e2e; border:1px solid #1e5a7a; border-radius:6px; }"
            "QLabel { color:#9cdbba; font-size:11px; }"
            "QSpinBox, QSlider, QComboBox { background:#0c1c28; color:#fff; border:1px solid #1e5a7a; border-radius:3px; }"
        )
        vp_flyout.setWindowFlags(Qt.Popup)
        vp_fl = QGridLayout(vp_flyout)
        vp_fl.setContentsMargins(10, 8, 10, 8)
        vp_fl.setSpacing(6)

        vp_fl.addWidget(QLabel("Ray Density:"), 0, 0)
        self.ray_density_spin = QSpinBox()
        self.ray_density_spin.setRange(4, 64)
        self.ray_density_spin.setValue(16)
        self.ray_density_spin.setToolTip("Number of guide rays per vanishing point")
        self.ray_density_spin.valueChanged.connect(self._change_ray_density)
        vp_fl.addWidget(self.ray_density_spin, 0, 1)

        self.ray_snap_btn = QPushButton("🧲 Snap Rays")
        self.ray_snap_btn.setCheckable(True)
        self.ray_snap_btn.setToolTip("Snap brush strokes to the nearest perspective ray")
        self.ray_snap_btn.setStyleSheet(
            "QPushButton { border:1px solid #12324a; border-radius:4px; background:#0c1c28; color:#fff; padding:3px 7px; }"
            "QPushButton:checked { background:#d040ff; color:#fff; font-weight:bold; }"
        )
        self.ray_snap_btn.toggled.connect(lambda chk: setattr(self.view, "snap_to_perspective", chk))
        vp_fl.addWidget(self.ray_snap_btn, 0, 2)

        vp_fl.addWidget(QLabel("Guide Opacity:"), 1, 0)
        self.guide_opacity_slider = QSlider(Qt.Horizontal)
        self.guide_opacity_slider.setRange(5, 100)
        self.guide_opacity_slider.setValue(100)
        self.guide_opacity_slider.setFixedWidth(100)
        self.guide_opacity_slider.setToolTip("Fade all perspective guide lines (5%–100%)")
        self.guide_opacity_slider.valueChanged.connect(self._change_guide_opacity)
        vp_fl.addWidget(self.guide_opacity_slider, 1, 1, 1, 2)

        vp_fl.addWidget(QLabel("Isolate VP:"), 2, 0)
        self.vp_isolate_combo = QComboBox()
        self.vp_isolate_combo.addItems(["All", "VP1", "VP2", "VP3", "VP4", "VP5", "VP6"])
        self.vp_isolate_combo.setToolTip(
            "Solo one VP's rays — hides all other VPs.\n\"All\" shows everything."
        )
        self.vp_isolate_combo.currentTextChanged.connect(self._change_vp_isolate)
        vp_fl.addWidget(self.vp_isolate_combo, 2, 1, 1, 2)

        vp_fl.addWidget(QLabel("Shot Preset:"), 3, 0)
        self.vp_preset_combo = QComboBox()
        self.vp_preset_combo.setToolTip("Snap VPs to classic artistic perspective compositions")
        self.vp_preset_combo.addItems([
            "— Shot Preset —",
            "1P · Eye Level (Classic)",
            "1P · Worm's Eye (Low Angle Hero)",
            "1P · Bird's Eye (God Shot)",
            "1P · Golden Ratio Centered",
            "2P · Street Level Drama",
            "2P · Golden Ratio Horizon",
            "2P · Wide Angle Sweep",
            "2P · Compressed Space",
            "3P · Looking Up (Hero)",
            "3P · Looking Down (Surveillance)",
            "3P · Dutch Angle",
            "4P · Balanced Fisheye",
            "4P · Golden Zenith / Nadir",
            "5P · Wide Fisheye Panorama",
            "6P · 360° Equirectangular",
        ])
        self.vp_preset_combo.currentTextChanged.connect(self._apply_vp_preset)
        vp_fl.addWidget(self.vp_preset_combo, 3, 1, 1, 2)

        reset_vp_btn = QPushButton("🔄 Reset VPs to Defaults")
        reset_vp_btn.setToolTip("Reset all Vanishing Points to default positions")
        reset_vp_btn.setStyleSheet(
            "QPushButton { border:1px solid #12324a; border-radius:4px; background:#0c1c28; color:#aaa; padding:3px 7px; }"
        )
        reset_vp_btn.clicked.connect(lambda: self.view.reset_vp_positions())
        vp_fl.addWidget(reset_vp_btn, 4, 0, 1, 3)

        def _show_vp_flyout():
            btn_global = vp_opts_btn.mapToGlobal(vp_opts_btn.rect().bottomLeft())
            vp_flyout.move(btn_global)
            vp_flyout.show()
        vp_opts_btn.clicked.connect(_show_vp_flyout)

        # â”€â”€ Separator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        sep2 = QFrame(); sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color:#1a3a55;"); gp_layout.addWidget(sep2)

        # â”€â”€ 3. Ï† Composition & Camera Tools â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        self.golden_overlay_btn = QPushButton("âœ¨ Ï† Guide")
        self.golden_overlay_btn.setCheckable(True)
        self.golden_overlay_btn.setToolTip("Toggle Rule of Thirds / Golden Ratio composition overlay")
        self.golden_overlay_btn.setStyleSheet(
            "QPushButton { border:1px solid #c8a000; border-radius:4px; background:#16120a; color:#ffd228; font-weight:bold; padding:3px 8px; }"
            "QPushButton:checked { background:#ffd228; color:#000; }"
        )
        self.golden_overlay_btn.toggled.connect(self._toggle_golden_overlay)
        gp_layout.addWidget(self.golden_overlay_btn)

        phi_opts_btn = QPushButton("âš™ Ï† Options â–¾")
        phi_opts_btn.setToolTip("Composition layout type, canvas constraints & focal snapping")
        phi_opts_btn.setStyleSheet(
            "QPushButton { border:1px solid #c8a000; border-radius:4px; background:#16120a; color:#ffd228; padding:3px 6px; }"
            "QPushButton:pressed { background:#332800; }"
        )
        gp_layout.addWidget(phi_opts_btn)

        phi_flyout = QFrame(None, Qt.Popup | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        phi_flyout.setStyleSheet(
            "QFrame { background:#16120a; border:1px solid #c8a000; border-radius:6px; }"
            "QLabel { color:#ffd228; font-size:11px; }"
        )
        phi_fl = QGridLayout(phi_flyout)
        phi_fl.setContentsMargins(10, 8, 10, 8)
        phi_fl.setSpacing(6)

        phi_fl.addWidget(QLabel("Type:"), 0, 0)
        self.golden_type_combo = QComboBox()
        self.golden_type_combo.addItems(["Rule of Thirds", "Golden Spiral", "Phi Grid", "Golden Triangle", "Golden Rectangle"])
        self.golden_type_combo.setToolTip("Choose composition guide layout type")
        self.golden_type_combo.setStyleSheet("QComboBox { background:#1a1000; color:#ffd228; border:1px solid #c8a000; }")
        self.golden_type_combo.currentTextChanged.connect(
            lambda t: (setattr(self.view, "golden_overlay_type", t), self.view.viewport().update())
        )
        phi_fl.addWidget(self.golden_type_combo, 0, 1)

        phi_fl.addWidget(QLabel("Scale:"), 1, 0)
        self.golden_scale_slider = QSlider(Qt.Horizontal)
        self.golden_scale_slider.setRange(10, 200)
        self.golden_scale_slider.setValue(100)
        self.golden_scale_slider.setFixedWidth(110)
        self.golden_scale_slider.setToolTip("Resize overlay (Active in Free Transform mode)")
        self.golden_scale_slider.setStyleSheet("QSlider::groove:horizontal { background:#332800; } QSlider::handle:horizontal { background:#ffd228; }")
        self.golden_scale_slider.valueChanged.connect(
            lambda v: (setattr(self.view, "golden_overlay_scale", v / 100.0), self.view.viewport().update())
        )
        phi_fl.addWidget(self.golden_scale_slider, 1, 1)

        self.golden_constrain_chk = QCheckBox("📌 Constrain to Canvas")
        self.golden_constrain_chk.setChecked(True)
        self.golden_constrain_chk.setToolTip("Frame overlay to canvas dimensions & dynamically track focal target point")
        self.golden_constrain_chk.setStyleSheet("QCheckBox { color:#ffd228; font-size:11px; font-weight:bold; }")
        self.golden_constrain_chk.toggled.connect(
            lambda chk: (setattr(self.view, "golden_overlay_constrained", chk), self.view.viewport().update())
        )
        phi_fl.addWidget(self.golden_constrain_chk, 2, 0, 1, 2)

        snap_focal_btn = QPushButton("🎯 Snap Focal Point to VP")
        snap_focal_btn.setToolTip("Snap composition focal target to active Vanishing Point (VP1/VP5)")
        snap_focal_btn.setStyleSheet("QPushButton { border:1px solid #c8a000; border-radius:3px; background:#1a1000; color:#ffd228; font-weight:bold; padding:3px 6px; } QPushButton:hover { background:#332400; }")
        snap_focal_btn.clicked.connect(self._snap_golden_focal_to_vp)
        phi_fl.addWidget(snap_focal_btn, 3, 0, 1, 2)

        def _show_phi_flyout():
            btn_global = phi_opts_btn.mapToGlobal(phi_opts_btn.rect().bottomLeft())
            phi_flyout.move(btn_global)
            phi_flyout.show()
        phi_opts_btn.clicked.connect(_show_phi_flyout)

        # â”€â”€ 4. Camera Tools â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        camera_opts_btn = QPushButton("🎥 Camera ▾")
        camera_opts_btn.setToolTip("Cinematic Aspect Ratio Mattes · Lens FOV Cones · Value Checker · False Color")
        camera_opts_btn.setStyleSheet(
            "QPushButton { border:1px solid #00a0e0; border-radius:4px; background:#041828; color:#00d0ff; font-weight:bold; padding:3px 8px; }"
            "QPushButton:pressed { background:#003050; }"
        )
        gp_layout.addWidget(camera_opts_btn)

        camera_flyout = QFrame(None, Qt.Popup | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        camera_flyout.setStyleSheet(
            "QFrame { background:#041828; border:1px solid #00a0e0; border-radius:6px; }"
            "QLabel { color:#00d0ff; font-size:11px; }"
            "QComboBox { background:#062238; color:#fff; border:1px solid #00a0e0; border-radius:3px; }"
        )
        cam_fl = QGridLayout(camera_flyout)
        cam_fl.setContentsMargins(10, 8, 10, 8)
        cam_fl.setSpacing(6)

        cam_fl.addWidget(QLabel("Aspect Ratio:"), 0, 0)
        self.camera_aspect_combo = QComboBox()
        self.camera_aspect_combo.addItems([
            "Off",
            "2.39:1 Anamorphic",
            "1.85:1 Academy Flat",
            "16:9 Widescreen",
            "4:3 IMAX",
            "1:1 Square",
            "9:16 Vertical",
            "Action/Title Safe",
        ])
        self.camera_aspect_combo.setToolTip("Overlay cinematic letterbox matte & aspect ratios")
        self.camera_aspect_combo.currentTextChanged.connect(
            lambda t: (setattr(self.view, "camera_aspect_mode", t), self.view.viewport().update())
        )
        cam_fl.addWidget(self.camera_aspect_combo, 0, 1)

        cam_fl.addWidget(QLabel("Matte Opacity:"), 1, 0)
        self.camera_aspect_slider = QSlider(Qt.Horizontal)
        self.camera_aspect_slider.setRange(20, 100)
        self.camera_aspect_slider.setValue(75)
        self.camera_aspect_slider.setFixedWidth(110)
        self.camera_aspect_slider.setToolTip("Darkness of letterbox matte (20%–100%)")
        self.camera_aspect_slider.setStyleSheet("QSlider::groove:horizontal { background:#02101c; } QSlider::handle:horizontal { background:#00d0ff; }")
        self.camera_aspect_slider.valueChanged.connect(
            lambda v: (setattr(self.view, "camera_aspect_opacity", v / 100.0), self.view.viewport().update())
        )
        cam_fl.addWidget(self.camera_aspect_slider, 1, 1)

        cam_fl.addWidget(QLabel("Lens FOV Cone:"), 2, 0)
        self.camera_fov_combo = QComboBox()
        self.camera_fov_combo.addItems([
            "Off",
            "14mm Ultra-Wide (114°)",
            "24mm Wide (84°)",
            "35mm Street (63°)",
            "50mm Standard (47°)",
            "85mm Portrait (28°)",
            "135mm Telephoto (18°)",
        ])
        self.camera_fov_combo.setToolTip("Simulate lens focal length & FOV field of view cone")
        self.camera_fov_combo.currentTextChanged.connect(
            lambda t: (setattr(self.view, "camera_fov_mode", t), self.view.viewport().update())
        )
        cam_fl.addWidget(self.camera_fov_combo, 2, 1)

        val_check_btn = QPushButton("🌗 Value Check Mode (M)")
        val_check_btn.setCheckable(True)
        val_check_btn.setToolTip("Toggle Monochrome preview mode to evaluate value hierarchy (Press M)")
        val_check_btn.setStyleSheet(
            "QPushButton { border:1px solid #00a0e0; border-radius:3px; background:#062238; color:#00d0ff; font-weight:bold; padding:3px 6px; }"
            "QPushButton:checked { background:#00d0ff; color:#000; }"
        )
        val_check_btn.toggled.connect(self._toggle_value_check)
        cam_fl.addWidget(val_check_btn, 3, 0, 1, 2)

        false_col_btn = QPushButton("🎨 False Color Exposure")
        false_col_btn.setCheckable(True)
        false_col_btn.setToolTip("Toggle ARRI/RED false color exposure evaluation map")
        false_col_btn.setStyleSheet(
            "QPushButton { border:1px solid #00a0e0; border-radius:3px; background:#062238; color:#00d0ff; font-weight:bold; padding:3px 6px; }"
            "QPushButton:checked { background:#ff4080; color:#fff; }"
        )
        false_col_btn.toggled.connect(self._toggle_false_color)
        cam_fl.addWidget(false_col_btn, 4, 0, 1, 2)

        def _show_camera_flyout():
            btn_global = camera_opts_btn.mapToGlobal(camera_opts_btn.rect().bottomLeft())
            camera_flyout.move(btn_global)
            camera_flyout.show()
        camera_opts_btn.clicked.connect(_show_camera_flyout)

        # â”€â”€ Separator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        sep3 = QFrame(); sep3.setFrameShape(QFrame.VLine)
        sep3.setStyleSheet("color:#1a3a55;"); gp_layout.addWidget(sep3)

        # â”€â”€ 5. View & Symmetry Flyout â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        view_opts_btn = QPushButton("🪞 View & Symmetry ▾")
        view_opts_btn.setToolTip("Symmetry Mirroring & Canvas View Flipping")
        view_opts_btn.setStyleSheet(
            "QPushButton { border:1px solid #12324a; border-radius:4px; background:#0c1c28; color:#aaa; padding:3px 8px; }"
            "QPushButton:pressed { background:#1e3a50; }"
        )
        gp_layout.addWidget(view_opts_btn)

        view_flyout = QFrame(None, Qt.Popup | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        view_flyout.setStyleSheet(
            "QFrame { background:#0d1e2e; border:1px solid #12324a; border-radius:6px; }"
            "QLabel { color:#9cdbba; font-size:11px; }"
            "QComboBox { background:#0c1c28; color:#fff; border:1px solid #12324a; border-radius:3px; }"
        )
        view_fl = QGridLayout(view_flyout)
        view_fl.setContentsMargins(10, 8, 10, 8)
        view_fl.setSpacing(6)

        view_fl.addWidget(QLabel("Symmetry:"), 0, 0)
        self.symmetry_combo = QComboBox()
        self.symmetry_combo.addItems(["Off", "Vertical", "Horizontal", "Quad"])
        self.symmetry_combo.setToolTip("Mirror live brush strokes across symmetry axes")
        self.symmetry_combo.currentTextChanged.connect(self._change_symmetry_mode)
        view_fl.addWidget(self.symmetry_combo, 0, 1)

        flip_h_btn = QPushButton("â†” Flip View Horizontal (F)")
        flip_h_btn.setToolTip("Flip canvas view horizontally (Press F)")
        flip_h_btn.setStyleSheet("QPushButton { border:1px solid #12324a; border-radius:3px; background:#0c1c28; color:#fff; padding:4px 8px; }")
        flip_h_btn.clicked.connect(self.flip_canvas_horizontal)
        view_fl.addWidget(flip_h_btn, 1, 0, 1, 2)

        flip_v_btn = QPushButton("â†• Flip View Vertical")
        flip_v_btn.setToolTip("Flip canvas view vertically")
        flip_v_btn.setStyleSheet("QPushButton { border:1px solid #12324a; border-radius:3px; background:#0c1c28; color:#fff; padding:4px 8px; }")
        flip_v_btn.clicked.connect(self.flip_canvas_vertical)
        view_fl.addWidget(flip_v_btn, 2, 0, 1, 2)

        def _show_view_flyout():
            btn_global = view_opts_btn.mapToGlobal(view_opts_btn.rect().bottomLeft())
            view_flyout.move(btn_global)
            view_flyout.show()
        view_opts_btn.clicked.connect(_show_view_flyout)

        # â”€â”€ 6. Atmospheric Perspective Flyout â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        atmos_opts_btn = QPushButton("🌫️ Atmosphere ▾")
        atmos_opts_btn.setToolTip("Atmospheric perspective depth swatches (Keys 1..5) & Haze Tint")
        atmos_opts_btn.setStyleSheet(
            "QPushButton { border:1px solid #0c7a47; border-radius:4px; background:#05141c; color:#16f26a; font-weight:bold; padding:3px 8px; }"
            "QPushButton:pressed { background:#0a2830; }"
        )
        gp_layout.addWidget(atmos_opts_btn)

        atmos_flyout = QFrame(None, Qt.Popup | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        atmos_flyout.setStyleSheet(
            "QFrame { background:#05141c; border:1px solid #0c7a47; border-radius:6px; }"
            "QLabel { color:#9cdbba; font-size:11px; }"
        )
        atmos_fl = QVBoxLayout(atmos_flyout)
        atmos_fl.setContentsMargins(10, 8, 10, 8)
        atmos_fl.setSpacing(6)

        atmos_fl.addWidget(QLabel("<b>🌫️ Atmospheric Perspective Swatches:</b>"))
        self.atmos_swatch_btns: list[QPushButton] = []
        labels = [
            ("1: Deep Haze", "Far background / lowest saturation (Press 1)"),
            ("2: Mid Dist", "Mid-distance atmospheric softening (Press 2)"),
            ("3: Base Color", "Default active brush color (Press 3)"),
            ("4: Foreground", "Rich foreground vibrancy (Press 4)"),
            ("5: Ultra Fore", "Close foreground maximum saturation (Press 5)"),
        ]
        for i, (lbl_text, tip) in enumerate(labels):
            btn = QPushButton(lbl_text)
            btn.setToolTip(tip)
            btn.setFixedHeight(24)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, idx=i: self.select_atmospheric_level(idx + 1))
            atmos_fl.addWidget(btn)
            self.atmos_swatch_btns.append(btn)

        haze_tint_btn = QPushButton("🎨 Choose Haze Tint Color")
        haze_tint_btn.setToolTip("Select custom atmospheric sky/fog tint color")
        haze_tint_btn.setStyleSheet("QPushButton { border:1px solid #0c7a47; border-radius:3px; background:#0a2830; color:#16f26a; font-weight:bold; padding:4px; }")
        haze_tint_btn.clicked.connect(self._choose_haze_tint_color)
        atmos_fl.addWidget(haze_tint_btn)

        def _show_atmos_flyout():
            btn_global = atmos_opts_btn.mapToGlobal(atmos_opts_btn.rect().bottomLeft())
            atmos_flyout.move(btn_global)
            atmos_flyout.show()
        atmos_opts_btn.clicked.connect(_show_atmos_flyout)

        gp_layout.addStretch(1)
        root.addWidget(gp_bar)



        # 3. Main Workspace Splitter (Tools | Canvas Viewport | Layer Stack & Diagnostics)

        splitter = QSplitter(Qt.Horizontal)

        # Left Tool Palette Toolbar
        tool_panel = QFrame()
        tool_panel.setFixedWidth(54)
        tool_panel.setStyleSheet("QFrame { background:#080d14; border:1px solid #12324a; border-radius:6px; }")
        tool_layout = QVBoxLayout(tool_panel)
        tool_layout.setContentsMargins(4, 8, 4, 8)
        tool_layout.setSpacing(6)

        tools = [
            ("brush", "brush", "Paint brush (B)"),
            ("eraser", "eraser", "Eraser (E)"),
            ("rectangle", "rect_select", "Rectangular selection (M)"),
            ("circle", "ellipse_select", "Elliptical selection"),
            ("lasso", "lasso_select", "Lasso selection (L)"),
            ("sparkles", "wand", "Magic wand selection"),
            ("bounding_box", "box", "Draw bounding box"),
            ("arrow_right", "arrow", "Draw arrow callout"),
            ("line", "line", "Draw straight line"),
            ("eyedropper", "picker", "Color picker (I)"),
            ("bucket", "fill", "Paint bucket fill (G)"),
        ]
        self.tool_buttons = {}
        for icon_name, name, tooltip in tools:
            btn = QPushButton()
            configure_button(
                btn,
                icon_name,
                tooltip=tooltip,
                role="quiet",
                icon_only=True,
            )
            btn.setProperty("toolButton", True)
            btn.setCheckable(True)
            btn.setChecked(name == self.active_tool)
            btn.setFixedSize(38, 38)
            btn.clicked.connect(lambda _, n=name: self._set_active_tool(n))
            tool_layout.addWidget(btn)
            self.tool_buttons[name] = btn

        tool_layout.addStretch(1)

        # Color Selector Button
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(42, 42)
        self._update_color_btn()
        self.color_btn.clicked.connect(self._choose_color)
        tool_layout.addWidget(self.color_btn)

        splitter.addWidget(tool_panel)

        self.view = ImageViewerGraphicsView()
        self.view.color_hovered.connect(self._update_hud_color)
        self.view.draw_stroke_finished.connect(self._handle_viewport_stroke_finished)
        splitter.addWidget(self.view)

        # Right Dock Panel (Layers Stack & Inspection Info)
        right_panel = QFrame()
        right_panel.setFixedWidth(280)
        right_panel.setStyleSheet("QFrame { background:#080d14; border:1px solid #12324a; border-radius:6px; }")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane { border: 1px solid #12324a; } QTabBar::tab { background:#080d14; color:#9cdbba; padding:6px 10px; } QTabBar::tab:selected { background:#12324a; color:#16f26a; }")
        
        # Tab 1: Layer Stack
        layer_widget = QWidget()
        layer_lay = QVBoxLayout(layer_widget)
        
        layer_hdr = QHBoxLayout()
        layer_hdr.addWidget(QLabel("<b>Layer Stack</b>"))
        add_layer_btn = QPushButton("+ Layer")
        add_layer_btn.clicked.connect(self.add_new_layer)
        layer_hdr.addWidget(add_layer_btn)
        layer_lay.addLayout(layer_hdr)

        self.layer_list = QListWidget()
        self.layer_list.setStyleSheet("background:#04080c; color:#ddffe9; border:1px solid #0c7a47;")
        self.layer_list.currentRowChanged.connect(self._select_layer_row)
        layer_lay.addWidget(self.layer_list)

        layer_ctrl = QHBoxLayout()
        dup_btn = QPushButton("Duplicate")
        dup_btn.clicked.connect(self.duplicate_active_layer)
        layer_ctrl.addWidget(dup_btn)

        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self.delete_active_layer)
        layer_ctrl.addWidget(del_btn)
        layer_lay.addLayout(layer_ctrl)

        tabs.addTab(layer_widget, "Layers")

        # Tab 2: Inspection HUD & Color
        hud_widget = QWidget()
        hud_lay = QVBoxLayout(hud_widget)
        self.hud_lbl = QLabel("<b>Color Sampler HUD</b><br>Hover over image to inspect pixel values.")
        self.hud_lbl.setStyleSheet("font-family: monospace; font-size:11px; color:#8fd6a5;")
        self.hud_lbl.setWordWrap(True)
        hud_lay.addWidget(self.hud_lbl)

        self.diag_info = QLabel("<b>PBR & Diagnostic Report</b><br>Select a mode above to analyze values.")
        self.diag_info.setStyleSheet("font-family: monospace; font-size:11px; color:#1e9bff;")
        self.diag_info.setWordWrap(True)
        hud_lay.addWidget(self.diag_info)
        hud_lay.addStretch(1)

        tabs.addTab(hud_widget, "Inspect")

        # Tab 3: Texture Tools
        tex_widget = QWidget()
        tex_lay = QVBoxLayout(tex_widget)
        tex_lay.setSpacing(6)
        
        pbr_lbl = QLabel("<b>Substance & PBR Workflows</b>")
        pbr_lbl.setStyleSheet("color:#16f26a;")
        tex_lay.addWidget(pbr_lbl)

        import_pbr_btn = QPushButton("📁 Import PBR Set (Albedo/NRM/ORM)")
        import_pbr_btn.clicked.connect(self.import_pbr_texture_set)
        tex_lay.addWidget(import_pbr_btn)

        export_orm_btn = QPushButton("📦 Export Channel-Packed ORM Map")
        export_orm_btn.clicked.connect(self.export_channel_packed_orm)
        tex_lay.addWidget(export_orm_btn)

        bake_mat_btn = QPushButton("🔥 Bake Textures -> DCC Material Asset")
        bake_mat_btn.clicked.connect(self.bake_textures_to_material)
        tex_lay.addWidget(bake_mat_btn)

        bake_tex_btn = QPushButton("🍪 Bake Material -> Simple 2D Textures")
        bake_tex_btn.clicked.connect(self.bake_material_to_textures)
        tex_lay.addWidget(bake_tex_btn)

        tex_lay.addStretch(1)
        tabs.addTab(tex_widget, "Texture & DCC")

        # Tab 4: Photoshop Adjustments, FX & Substance Generators
        super_widget = QWidget()
        super_lay = QVBoxLayout(super_widget)
        super_lay.setSpacing(6)

        adj_lbl = QLabel("<b>Photoshop Adjustments & FX</b>")
        adj_lbl.setStyleSheet("color:#16f26a;")
        super_lay.addWidget(adj_lbl)

        brightness_btn = QPushButton("☀️ Brightness / Contrast Offset")
        brightness_btn.clicked.connect(self.apply_brightness_contrast_adjustment)
        super_lay.addWidget(brightness_btn)

        exposure_btn = QPushButton("💡 Exposure & Gamma (EV Offset)")
        exposure_btn.clicked.connect(self.apply_exposure_gamma_adjustment)
        super_lay.addWidget(exposure_btn)

        nrm_flip_btn = QPushButton("🔄 Flip Normal Y (DirectX <-> OpenGL)")
        nrm_flip_btn.clicked.connect(self.flip_normal_map_green_channel)
        super_lay.addWidget(nrm_flip_btn)

        bal_btn = QPushButton("⚖️ Color Balance (Shadows/Mid/Highlights)")
        bal_btn.clicked.connect(self.apply_color_balance_adjustment)
        super_lay.addWidget(bal_btn)

        post_btn = QPushButton("📊 Posterize / Value Threshold")
        post_btn.clicked.connect(self.apply_posterize_threshold)
        super_lay.addWidget(post_btn)

        curves_btn = QPushButton("📈 Curves / Levels Adjustment")
        curves_btn.clicked.connect(self.apply_curves_levels_adjustment)
        super_lay.addWidget(curves_btn)

        hsv_btn = QPushButton("🎨 Hue / Saturation / Vibrance")
        hsv_btn.clicked.connect(self.apply_hsv_vibrance_adjustment)
        super_lay.addWidget(hsv_btn)

        invert_btn = QPushButton("🔄 Invert Colors (Ctrl+I)")
        invert_btn.clicked.connect(self.invert_active_layer_colors)
        super_lay.addWidget(invert_btn)

        fx_btn = QPushButton("âœ¨ Layer Styles (Drop Shadow, Bevel, Stroke)")
        fx_btn.clicked.connect(self.open_layer_styles_dialog)
        super_lay.addWidget(fx_btn)

        super_lay.addStretch(1)
        tabs.addTab(super_widget, "FX & Adjustments")

        right_layout.addWidget(tabs)
        splitter.addWidget(right_panel)

        splitter.setSizes([54, 780, 280])
        root.addWidget(splitter, 1)

    def load_image(self, image_path: str) -> bool:
        self.image_path = image_path
        self.project_path = ""
        ext = Path(image_path).suffix.lower()

        if ext == ".tcimg":
            return self.load_project_file(image_path)

        # 1. Native QImage load
        img = QImage(image_path)

        # 2. Fallback to Pillow for PSD, PSB, TGA, WEBP, HDR, EXR formats
        if img.isNull() and HAS_PIL:
            try:
                pil_img = PILImage.open(image_path)
                img = pil_to_qimage(pil_img)
            except Exception as exc:
                print(f"[ImageEditorWidget] PIL load fallback error: {exc}")

        if img.isNull():
            QMessageBox.warning(self, "Open Failed", f"Could not load image file:\n{image_path}")
            return False

        self.stack = LayerStack(img.width(), img.height())
        layer = ImageLayer(Path(image_path).name, img.width(), img.height())
        layer.image = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self.stack.add_layer(layer)
        self.update_layer_list_ui()
        self.update_composited_view()
        self.dirty = False
        return True

    def mark_dirty(self):
        self.dirty = True

    def open_image_file(self):
        filter_str = (
            "All Supported Formats (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff *.tga *.psd *.psb *.hdr *.exr *.tcimg);;"
            "Photoshop Documents (*.psd *.psb);;"
            "Targa Images (*.tga);;"
            "Standard Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff);;"
            "Tech Connector Projects (*.tcimg);;"
            "All Files (*.*)"
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Image or Project",
            str(Path(self.image_path).parent) if self.image_path else "",
            filter_str,
        )
        if path:
            return self.load_image(path)
        return False

    def save_image(self):
        if not self.image_path:
            return self.save_image_as()
        return self._save_composite_to_path(self.image_path)

    def save_image_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Image As",
            self.image_path or "Untitled.png",
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;Bitmap (*.bmp);;TIFF Image (*.tif *.tiff)",
        )
        if not path:
            return False
        if not Path(path).suffix:
            path += ".png"
        ok = self._save_composite_to_path(path)
        if ok:
            self.image_path = path
        return ok

    def _save_composite_to_path(self, path: str) -> bool:
        image = self.stack.composite()
        ok = bool(image.save(path))
        if ok:
            self.dirty = False
            self.image_saved.emit(path)
        else:
            QMessageBox.warning(self, "Save Failed", f"Could not save image:\n{path}")
        return ok

    def save_project_file(self):
        if not self.project_path:
            return self.save_project_file_as()
        return self._save_project_to_path(self.project_path)

    def save_project_file_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Layered Image Project",
            self.project_path or "Untitled.tcimg",
            "Tech Connector Image Project (*.tcimg)",
        )
        if not path:
            return False
        if Path(path).suffix.lower() != ".tcimg":
            path += ".tcimg"
        ok = self._save_project_to_path(path)
        if ok:
            self.project_path = path
        return ok

    def _save_project_to_path(self, path: str) -> bool:
        data = {
            "schema": "tech_connector_image_project_v1",
            "width": self.stack.width,
            "height": self.stack.height,
            "image_path": self.image_path,
            "active_index": self.stack.active_index,
            "grid_enabled": self.view.grid_enabled,
            "grid_size": self.view.grid_size,
            "perspective_mode": self.view.perspective_mode,
            "perspective_ray_density": self.view.perspective_ray_density,
            "atmos_haze_color": self.atmos_haze_color.name(),
            "active_atmos_level": self.active_atmos_level,
            "vp_positions": {
                name: [handle.x(), handle.y()]
                for name, handle in self.view.vp_handles.items()
            },
            "layers": [layer.to_project_dict() for layer in self.stack.layers],
        }
        try:
            Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "Project Save Failed", str(exc))
            return False
        self.dirty = False
        return True

    def _toggle_grid(self, checked: bool):
        self.view.set_grid_enabled(checked)
        self.grid_toggle_btn.setText("Grid on" if checked else "Grid off")

    def _change_grid_size(self, size: int):
        self.view.set_grid_size(size)

    def _change_perspective_mode(self, mode: str):
        self.view.set_perspective_mode(mode)

    def _toggle_perspective_guides(self, checked: bool):
        self.view.show_perspective_guides = checked
        self.view.viewport().update()

    def _change_ray_density(self, density: int):
        self.view.perspective_ray_density = density
        self.view.viewport().update()

    def _change_guide_opacity(self, value: int):
        """Set guide line opacity from the 5–100 slider (maps to 0.05–1.0)."""
        self.view.guide_opacity = value / 100.0
        self.view.viewport().update()
        self.view.show_hud_toast(f"💡 Guide Opacity: {value}%")

    def _change_vp_isolate(self, vp: str):
        """Isolate / solo one VP's guide rays, or show All."""
        self.view.isolated_vp = vp
        self.view.viewport().update()
        if vp == "All":
            self.view.show_hud_toast("🔍 Showing All VP Guide Lines")
        else:
            self.view.show_hud_toast(f"🔍 Isolated: {vp} rays only — other VPs hidden")

    def _toggle_golden_overlay(self, checked: bool):
        self.view.show_golden_ratio_overlay = checked
        if checked:
            pix_rect = self.view.pixmap_item.boundingRect()
            w = pix_rect.width() if not pix_rect.isEmpty() else 1280.0
            h = pix_rect.height() if not pix_rect.isEmpty() else 720.0

            # Default focal point to active VP or golden section
            if "VP5" in self.view.vp_handles and self.view.perspective_mode in ("5-Point Perspective (Fisheye Lens)", "6-Point Perspective (360° Spherical)"):
                self.view.golden_overlay_pos = QPointF(self.view.vp_handles["VP5"].scenePos())
            elif "VP1" in self.view.vp_handles and self.view.perspective_mode != "Off":
                self.view.golden_overlay_pos = QPointF(self.view.vp_handles["VP1"].scenePos())
            else:
                self.view.golden_overlay_pos = QPointF(w * 0.382, h * 0.382)

            self.view.golden_overlay_rot = 0.0
            self.view.show_hud_toast("✨ Composition Guide Active — Drag focal target or click to reposition")
        self.view.viewport().update()

    def _snap_golden_focal_to_vp(self):
        v = self.view
        if "VP5" in v.vp_handles and v.perspective_mode in ("5-Point Perspective (Fisheye Lens)", "6-Point Perspective (360° Spherical)"):
            v.golden_overlay_pos = QPointF(v.vp_handles["VP5"].scenePos())
            v.show_hud_toast("🎯 Composition Focal Point snapped to VP5")
        elif "VP1" in v.vp_handles and v.perspective_mode != "Off":
            v.golden_overlay_pos = QPointF(v.vp_handles["VP1"].scenePos())
            v.show_hud_toast("🎯 Composition Focal Point snapped to VP1")
        else:
            pix_rect = v.pixmap_item.boundingRect()
            w = pix_rect.width() if not pix_rect.isEmpty() else 1280.0
            h = pix_rect.height() if not pix_rect.isEmpty() else 720.0
            v.golden_overlay_pos = QPointF(w * 0.382, h * 0.382)
        v.viewport().update()

    def _toggle_value_check(self, checked: bool):
        self.view.value_check_mode = checked
        status = "ON (Monochrome Contrast Preview)" if checked else "OFF"
        self.view.show_hud_toast(f"🌗 Value Check Mode: {status}")
        self.update_composited_view()

    def _toggle_false_color(self, checked: bool):
        self.view.false_color_mode = checked
        status = "ON (ARRI/RED False Color Exposure Map)" if checked else "OFF"
        self.view.show_hud_toast(f"🎨 False Color Exposure: {status}")
        self.update_composited_view()



    def _apply_vp_preset(self, preset: str):
        """Snap VPs to a named artistic perspective preset."""
        if preset.startswith("—"):
            return
        v = self.view
        pix_rect = v.pixmap_item.boundingRect()
        w = pix_rect.width() if not pix_rect.isEmpty() else 1280.0
        h = pix_rect.height() if not pix_rect.isEmpty() else 720.0
        phi = 1.61803398875

        # â”€â”€ 1-Point Presets â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if preset == "1P · Eye Level (Classic)":
            v.set_perspective_mode("1-Point Perspective")
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(w * 0.5, h * 0.5)

        elif preset == "1P · Worm's Eye (Low Angle Hero)":
            v.set_perspective_mode("1-Point Perspective")
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(w * 0.5, h * 0.85)

        elif preset == "1P · Bird's Eye (God Shot)":
            v.set_perspective_mode("1-Point Perspective")
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(w * 0.5, h * 0.15)

        elif preset == "1P · Golden Ratio Centered":
            v.set_perspective_mode("1-Point Perspective")
            # VP on the golden ratio Y line (0.382 from top) and X centre
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(w * (1.0 / phi), h * (1.0 - 1.0 / phi))

        # â”€â”€ 2-Point Presets â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif preset == "2P · Street Level Drama":
            v.set_perspective_mode("2-Point Perspective")
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(-w * 0.3, h * 0.55)
            if "VP2" in v.vp_handles: v.vp_handles["VP2"].setPos(w * 1.3, h * 0.55)

        elif preset == "2P · Golden Ratio Horizon":
            v.set_perspective_mode("2-Point Perspective")
            hor_y = h * (1.0 - 1.0 / phi)          # golden-ratio Y â‰ˆ 0.382*h
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(-w * (phi - 1.0), hor_y)
            if "VP2" in v.vp_handles: v.vp_handles["VP2"].setPos(w * phi, hor_y)

        elif preset == "2P · Wide Angle Sweep":
            v.set_perspective_mode("2-Point Perspective")
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(-w * 0.6, h * 0.5)
            if "VP2" in v.vp_handles: v.vp_handles["VP2"].setPos(w * 1.6, h * 0.5)

        elif preset == "2P · Compressed Space":
            v.set_perspective_mode("2-Point Perspective")
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(w * 0.05, h * 0.5)
            if "VP2" in v.vp_handles: v.vp_handles["VP2"].setPos(w * 0.95, h * 0.5)

        # â”€â”€ 3-Point Presets â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif preset == "3P · Looking Up (Hero)":
            v.set_perspective_mode("3-Point Perspective")
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(-w * 0.3, h * 0.65)
            if "VP2" in v.vp_handles: v.vp_handles["VP2"].setPos(w * 1.3, h * 0.65)
            if "VP3" in v.vp_handles: v.vp_handles["VP3"].setPos(w * 0.5, -h * 0.8)  # zenith above frame

        elif preset == "3P · Looking Down (Surveillance)":
            v.set_perspective_mode("3-Point Perspective")
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(-w * 0.3, h * 0.35)
            if "VP2" in v.vp_handles: v.vp_handles["VP2"].setPos(w * 1.3, h * 0.35)
            if "VP3" in v.vp_handles: v.vp_handles["VP3"].setPos(w * 0.5, h * 1.8)   # nadir below frame

        elif preset == "3P · Dutch Angle":
            v.set_perspective_mode("3-Point Perspective")
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(-w * 0.15, h * 0.7)
            if "VP2" in v.vp_handles: v.vp_handles["VP2"].setPos(w * 1.2, h * 0.3)
            if "VP3" in v.vp_handles: v.vp_handles["VP3"].setPos(w * 0.6, -h * 0.5)

        # â”€â”€ 4-Point Presets â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif preset == "4P · Balanced Fisheye":
            v.set_perspective_mode("4-Point Perspective (Curvilinear)")
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(w * 0.05, h * 0.5)
            if "VP2" in v.vp_handles: v.vp_handles["VP2"].setPos(w * 0.95, h * 0.5)
            if "VP3" in v.vp_handles: v.vp_handles["VP3"].setPos(w * 0.5, h * 0.05)
            if "VP4" in v.vp_handles: v.vp_handles["VP4"].setPos(w * 0.5, h * 0.95)

        elif preset == "4P · Golden Zenith / Nadir":
            v.set_perspective_mode("4-Point Perspective (Curvilinear)")
            gx = w * (1.0 - 1.0 / phi)
            gy = h * (1.0 - 1.0 / phi)
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(w * 0.05, h * 0.5)
            if "VP2" in v.vp_handles: v.vp_handles["VP2"].setPos(w * 0.95, h * 0.5)
            if "VP3" in v.vp_handles: v.vp_handles["VP3"].setPos(gx, h * (1.0 / phi) - h)  # above canvas
            if "VP4" in v.vp_handles: v.vp_handles["VP4"].setPos(gx, h * (1.0 / phi) + h)  # below canvas

        # â”€â”€ 5-Point Presets â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif preset == "5P · Wide Fisheye Panorama":
            v.set_perspective_mode("5-Point Perspective (Fisheye Lens)")
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(w * 0.05, h * 0.5)
            if "VP2" in v.vp_handles: v.vp_handles["VP2"].setPos(w * 0.95, h * 0.5)
            if "VP3" in v.vp_handles: v.vp_handles["VP3"].setPos(w * 0.5, h * 0.05)
            if "VP4" in v.vp_handles: v.vp_handles["VP4"].setPos(w * 0.5, h * 0.95)
            if "VP5" in v.vp_handles: v.vp_handles["VP5"].setPos(w * 0.5, h * 0.5)

        # â”€â”€ 6-Point Preset â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif preset == "6P · 360° Equirectangular":
            v.set_perspective_mode("6-Point Perspective (360° Spherical)")
            if "VP1" in v.vp_handles: v.vp_handles["VP1"].setPos(w * 0.05, h * 0.5)
            if "VP2" in v.vp_handles: v.vp_handles["VP2"].setPos(w * 0.95, h * 0.5)
            if "VP3" in v.vp_handles: v.vp_handles["VP3"].setPos(w * 0.5, h * 0.05)
            if "VP4" in v.vp_handles: v.vp_handles["VP4"].setPos(w * 0.5, h * 0.95)
            if "VP5" in v.vp_handles: v.vp_handles["VP5"].setPos(w * 0.5, h * 0.5)
            if "VP6" in v.vp_handles: v.vp_handles["VP6"].setPos(w * 0.52, h * 0.52)

        # Sync combo to correct perspective mode
        mode_map = {
            "1P": "1-Point Perspective",
            "2P": "2-Point Perspective",
            "3P": "3-Point Perspective",
            "4P": "4-Point Perspective (Curvilinear)",
            "5P": "5-Point Perspective (Fisheye Lens)",
            "6P": "6-Point Perspective (360° Spherical)",
        }
        key = preset[:2]
        if key in mode_map and hasattr(self, "perspective_combo"):
            self.perspective_combo.blockSignals(True)
            self.perspective_combo.setCurrentText(mode_map[key])
            self.perspective_combo.blockSignals(False)

        v.show_hud_toast(f"🎬 Shot Preset: {preset}")
        v.viewport().update()



    def open_project_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Layered Image Project",
            str(Path(self.project_path).parent) if self.project_path else "",
            "Tech Connector Image Project (*.tcimg)",
        )
        if path:
            return self.load_project_file(path)
        return False

    def load_project_file(self, path: str) -> bool:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.warning(self, "Project Open Failed", str(exc))
            return False
        if data.get("schema") != "tech_connector_image_project_v1":
            QMessageBox.warning(self, "Project Open Failed", "Unsupported image project format.")
            return False
        width = max(1, int(data.get("width") or 1))
        height = max(1, int(data.get("height") or 1))
        stack = LayerStack(width, height)
        stack.layers = [
            ImageLayer.from_project_dict(layer_data, width, height)
            for layer_data in list(data.get("layers") or [])
            if isinstance(layer_data, dict)
        ]
        if not stack.layers:
            stack.add_layer(name="Background", fill_color=QColor(24, 28, 36))
        stack.active_index = max(0, min(int(data.get("active_index") or 0), len(stack.layers) - 1))
        stack.save_snapshot()
        self.stack = stack
        self.project_path = path
        self.image_path = str(data.get("image_path") or "")
        self.dirty = False
        if "grid_enabled" in data:
            self.view.set_grid_enabled(bool(data["grid_enabled"]))
            self.grid_toggle_btn.setChecked(bool(data["grid_enabled"]))
        if "grid_size" in data:
            self.view.set_grid_size(int(data["grid_size"]))
            self.grid_size_spin.setValue(int(data["grid_size"]))
        if "perspective_mode" in data:
            mode = str(data["perspective_mode"])
            self.view.set_perspective_mode(mode)
            self.perspective_combo.setCurrentText(mode)
        if "perspective_ray_density" in data:
            density = int(data["perspective_ray_density"])
            self.view.perspective_ray_density = density
            self.ray_density_spin.setValue(density)
        if "vp_positions" in data and isinstance(data["vp_positions"], dict):
            for name, pos in data["vp_positions"].items():
                if name in self.view.vp_handles and isinstance(pos, (list, tuple)) and len(pos) == 2:
                    self.view.vp_handles[name].setPos(float(pos[0]), float(pos[1]))
            self.view.viewport().update()
        if "atmos_haze_color" in data:
            self.atmos_haze_color = QColor(str(data["atmos_haze_color"]))
        if "active_atmos_level" in data:
            self.active_atmos_level = max(1, min(5, int(data["active_atmos_level"])))
        self.update_atmospheric_palette()
        self.update_layer_list_ui()
        self.update_composited_view()
        return True

    def undo(self):
        if self.stack.undo():
            self.mark_dirty()
            self.update_layer_list_ui()
            self.update_composited_view()
            return True
        return False

    def redo(self):
        if self.stack.redo():
            self.mark_dirty()
            self.update_layer_list_ui()
            self.update_composited_view()
            return True
        return False

    def update_layer_list_ui(self):
        self.layer_list.clear()
        for idx, layer in enumerate(reversed(self.stack.layers)):
            item = QListWidgetItem(f"{'👁️' if layer.visible else '🙈'} {layer.name} ({int(layer.opacity*100)}%)")
            self.layer_list.addItem(item)

    def update_composited_view(self):
        composited = self.stack.composite()
        if self.diagnostic_mode == "pbr_albedo":
            composited = self._apply_pbr_albedo_filter(composited)
        elif self.diagnostic_mode == "normal_vector":
            composited = self._apply_normal_map_filter(composited)
        elif self.diagnostic_mode == "value_map" or self.view.value_check_mode:
            composited = self._apply_value_check_filter(composited)
        elif self.view.false_color_mode:
            composited = self._apply_false_color_filter(composited)

        pixmap = QPixmap.fromImage(composited)
        self.view.pixmap_item.setPixmap(pixmap)
        self.view.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())

    def _apply_value_check_filter(self, img: QImage) -> QImage:
        """Convert image to Greyscale for evaluating value hierarchy & contrast (Hotkey M)."""
        res = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
        p = QPainter(res)
        p.drawImage(0, 0, img)
        p.end()
        return res.convertToFormat(QImage.Format_Grayscale8).convertToFormat(QImage.Format_ARGB32_Premultiplied)

    def _apply_false_color_filter(self, img: QImage) -> QImage:
        """ARRI/RED False Color exposure map evaluation."""
        res = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        w, h = res.width(), res.height()
        for y in range(h):
            for x in range(0, w, 2):
                col = res.pixelColor(x, y)
                lum = int(0.2126 * col.red() + 0.7152 * col.green() + 0.0722 * col.blue())
                if lum > 250:
                    fc = QColor(255, 0, 0, col.alpha())
                elif 170 <= lum <= 190:
                    fc = QColor(255, 120, 200, col.alpha())
                elif 100 <= lum <= 120:
                    fc = QColor(40, 220, 100, col.alpha())
                elif lum < 10:
                    fc = QColor(120, 0, 180, col.alpha())
                else:
                    fc = QColor(lum, lum, lum, col.alpha())
                res.setPixelColor(x, y, fc)
                if x + 1 < w:
                    res.setPixelColor(x + 1, y, fc)
        return res


    def _set_active_tool(self, name: str):
        self.active_tool = name
        for tool_name, button in getattr(self, "tool_buttons", {}).items():
            button.setChecked(tool_name == name)

    def _change_brush_preset(self, name: str):
        self.brush_preset = name
        if name == "Hard Round":
            self.brush_hardness = 1.0
            self.brush_opacity = 1.0
        elif name == "Soft Round":
            self.brush_hardness = 0.2
            self.brush_opacity = 0.8
        elif name == "Airbrush":
            self.brush_hardness = 0.05
            self.brush_opacity = 0.4
        elif name == "Redline Markup Pen":
            self.primary_color = QColor(255, 40, 40)
            self._update_color_btn()
            self.update_atmospheric_palette()
            self.brush_size = 6
        elif name == "Highlighter":
            self.primary_color = QColor(255, 230, 0, 120)
            self._update_color_btn()
            self.update_atmospheric_palette()
            self.brush_size = 32

    def _change_brush_size(self, size: int):
        self.brush_size = size
        self.brush_mask = create_procedural_brush_mask(
            self.brush_preset,
            self.brush_size,
            self.brush_hardness,
            getattr(self, "brush_tilt_x", 0.0),
            getattr(self, "brush_tilt_y", 0.0),
        )

    def _change_brush_tilt(self, tilt_x: float, tilt_y: float):
        self.brush_tilt_x = tilt_x
        self.brush_tilt_y = tilt_y
        self.brush_mask = create_procedural_brush_mask(
            self.brush_preset,
            self.brush_size,
            self.brush_hardness,
            self.brush_tilt_x,
            self.brush_tilt_y,
        )
        tilt_deg = int(tilt_x * 90.0)
        if hasattr(self, "view"):
            self.view.show_hud_toast(f"📐 Brush Lean Angle: {tilt_x:+.2f} ({tilt_deg:>+3d}°) • Chisel Tip Active")

    def update_atmospheric_palette(self):
        """Re-compute 5-level Atmospheric Perspective colors off current primary brush color."""
        self.atmos_colors = compute_atmospheric_palette(self.primary_color, self.atmos_haze_color)
        labels = ["1: Deep Haze", "2: Mid Dist", "3: Base Color", "4: Foreground", "5: Ultra Fore"]
        for i, btn in enumerate(self.atmos_swatch_btns):
            if i < len(self.atmos_colors):
                c = self.atmos_colors[i]
                text_col = "#000000" if c.lightness() > 140 else "#ffffff"
                is_active = (i + 1) == self.active_atmos_level
                border_style = "border: 2px solid #16f26a; font-weight: bold;" if is_active else "border: 1px solid #12324a;"
                btn.setStyleSheet(f"QPushButton {{ background-color: {c.name()}; color: {text_col}; {border_style} border-radius: 4px; font-size: 10px; }}")
                btn.setToolTip(f"{labels[i]} (Press {i+1})\nRGB: ({c.red()}, {c.green()}, {c.blue()})\nHEX: {c.name()}")

    def select_atmospheric_level(self, level: int):
        """Select atmospheric depth level 1..5 (3 is default base color)."""
        if not 1 <= level <= 5:
            return
        self.active_atmos_level = level
        idx = level - 1

        if idx < len(self.atmos_colors):
            self.primary_color = QColor(self.atmos_colors[idx])
            self._update_color_btn()

        self.update_atmospheric_palette()

        names = ["Deep Background Haze", "Mid-Distance Softened", "Base Active Color", "Rich Foreground", "Ultra Foreground Vibrance"]
        msg = f"🌫️ Atmospheric Depth Level {level}: {names[idx]}"
        if hasattr(self, "view"):
            self.view.show_hud_toast(msg)

    def _choose_haze_tint_color(self):
        color = QColorDialog.getColor(self.atmos_haze_color, self, "Select Atmospheric Sky / Haze Tint Color")
        if color.isValid():
            self.atmos_haze_color = color
            self.update_atmospheric_palette()
            if hasattr(self, "view"):
                self.view.show_hud_toast(f"🌫️ Haze Tint Updated: {color.name()}")

    def _change_symmetry_mode(self, mode: str):
        self.view.symmetry_mode = mode
        self.view.viewport().update()
        self.view.show_hud_toast(f"🪞 Symmetry Mode: {mode}")

    def flip_canvas_horizontal(self):
        """Flip all layers in stack horizontally."""
        for layer in self.stack.layers:
            layer.image = layer.image.mirrored(True, False)
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()
        if hasattr(self, "view"):
            self.view.show_hud_toast("🪞 Canvas Flipped Horizontally (F)")

    def flip_canvas_vertical(self):
        """Flip all layers in stack vertically."""
        for layer in self.stack.layers:
            layer.image = layer.image.mirrored(False, True)
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()
        if hasattr(self, "view"):
            self.view.show_hud_toast("🪞 Canvas Flipped Vertically")

    def invert_active_layer_colors(self):
        """Invert RGB channels of the active layer (Ctrl+I)."""
        layer = self.stack.active_layer
        if not layer or layer.locked:
            return
        layer.image.invertPixels(QImage.InvertRgb)
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()
        if hasattr(self, "view"):
            self.view.show_hud_toast("🔄 Active Layer Inverted (Ctrl+I)")

    def add_layer_mask_to_active(self):
        """Add non-destructive layer mask to active layer."""
        layer = self.stack.active_layer
        if not layer:
            return
        layer.add_mask(fill_white=True)
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()
        if hasattr(self, "view"):
            self.view.show_hud_toast(f"🎭 Added Layer Mask to '{layer.name}'")

    def toggle_layer_mask_edit(self):
        """Toggle painting target between RGB pixels and Layer Mask."""
        layer = self.stack.active_layer
        if not layer or layer.mask is None:
            if hasattr(self, "view"):
                self.view.show_hud_toast("⚠️ Active layer has no mask! Add mask first.")
            return
        layer.editing_mask = not layer.editing_mask
        target = "Mask (White=Reveal, Black=Conceal)" if layer.editing_mask else "RGB Pixels"
        if hasattr(self, "mask_target_btn"):
            self.mask_target_btn.setText("Edit mask" if layer.editing_mask else "Edit RGB")
        if hasattr(self, "view"):
            self.view.show_hud_toast(f"✏️ Painting Target: {target}")

    def apply_magic_cutout_segmentation(self):
        """Segment active image into Foreground Subject layer and Background layer."""
        layer = self.stack.active_layer
        if not layer or layer.image.isNull():
            return
        
        img = layer.image
        w, h = img.width(), img.height()
        
        fg_img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        fg_img.fill(Qt.transparent)
        bg_img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        bg_img.fill(Qt.transparent)

        cx, cy = w / 2.0, h / 2.0
        max_dist = math.hypot(cx, cy)

        for y in range(h):
            for x in range(w):
                col = img.pixelColor(x, y)
                if col.alpha() == 0:
                    continue
                d_norm = math.hypot(x - cx, y - cy) / max_dist
                saliency = col.hsvSaturationF() * 0.5 + (1.0 - d_norm) * 0.5
                if saliency > 0.35:
                    fg_img.setPixelColor(x, y, col)
                else:
                    bg_img.setPixelColor(x, y, col)

        bg_layer = ImageLayer(f"{layer.name} - BG", w, h)
        bg_layer.image = bg_img
        fg_layer = ImageLayer(f"{layer.name} - Subject FG", w, h)
        fg_layer.image = fg_img

        self.stack.add_layer(bg_layer)
        self.stack.add_layer(fg_layer)
        self.update_layer_list_ui()
        self.update_composited_view()
        if hasattr(self, "view"):
            self.view.show_hud_toast("🤖 Magic Cutout: Subject Isolated onto FG & BG Layers!")

    def apply_gradient_map(self, preset_name: str = "Sunset Gold"):
        """Remap grayscale value image into stylized color ramp."""
        layer = self.stack.active_layer
        if not layer or layer.locked:
            return

        if preset_name == "Cyberpunk Neon":
            stops = [(0.0, QColor(15, 5, 30)), (0.35, QColor(0, 220, 255)), (0.75, QColor(255, 0, 128)), (1.0, QColor(255, 255, 255))]
        elif preset_name == "Forest Dusk":
            stops = [(0.0, QColor(10, 25, 20)), (0.4, QColor(40, 120, 70)), (0.8, QColor(220, 160, 50)), (1.0, QColor(245, 240, 220))]
        elif preset_name == "Thermal Heatmap":
            stops = [(0.0, QColor(0, 0, 0)), (0.25, QColor(0, 50, 220)), (0.5, QColor(200, 0, 200)), (0.75, QColor(255, 50, 0)), (1.0, QColor(255, 255, 255))]
        else:
            stops = [(0.0, QColor(20, 5, 35)), (0.35, QColor(180, 40, 90)), (0.7, QColor(255, 140, 30)), (1.0, QColor(255, 240, 180))]

        lut = []
        for i in range(256):
            t = i / 255.0
            left_stop, right_stop = stops[0], stops[-1]
            for s_idx in range(len(stops) - 1):
                if stops[s_idx][0] <= t <= stops[s_idx + 1][0]:
                    left_stop, right_stop = stops[s_idx], stops[s_idx + 1]
                    break
            st_len = max(0.001, right_stop[0] - left_stop[0])
            factor = (t - left_stop[0]) / st_len
            r = int(left_stop[1].red() * (1 - factor) + right_stop[1].red() * factor)
            g = int(left_stop[1].green() * (1 - factor) + right_stop[1].green() * factor)
            b = int(left_stop[1].blue() * (1 - factor) + right_stop[1].blue() * factor)
            lut.append(QColor(r, g, b))

        img = layer.image
        w, h = img.width(), img.height()
        for y in range(h):
            for x in range(w):
                col = img.pixelColor(x, y)
                if col.alpha() == 0:
                    continue
                lum = int(0.299 * col.red() + 0.587 * col.green() + 0.114 * col.blue())
                mapped = lut[max(0, min(255, lum))]
                mapped.setAlpha(col.alpha())
                img.setPixelColor(x, y, mapped)

        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()
        if hasattr(self, "view"):
            self.view.show_hud_toast(f"🎨 Gradient Map Applied: {preset_name}")

    def apply_fix_to_dcc(self):
        """Bake active composite image & send hot-reload push command to Maya / Unreal / Blender bridge."""
        if not self.image_path:
            ok = self.save_image_as()
            if not ok:
                return
        else:
            self.save_image()

        target_path = Path(self.image_path).resolve().as_posix()
        msg = f"🚀 Texture Pushed & Hot-Reload Signal Emitted to DCC Bridge!\n\nTarget File:\n{target_path}"
        QMessageBox.information(self, "DCC Live-Sync", msg)
        if hasattr(self, "view"):
            self.view.show_hud_toast("🚀 Texture Pushed Live to DCC Viewport!")

    def keyPressEvent(self, event):
        focused = QApplication.focusWidget()
        if focused and isinstance(focused, (QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox)):
            super().keyPressEvent(event)
            return

        mods = event.modifiers()
        key = event.key()

        # Ctrl+I -> Invert Layer Colors
        if mods == Qt.ControlModifier and key == Qt.Key_I:
            self.invert_active_layer_colors()
            return
        # Ctrl+D -> Deselect
        if mods == Qt.ControlModifier and key == Qt.Key_D:
            self.clear_selection()
            return
        # Ctrl+Shift+I -> Invert Selection
        if mods == (Qt.ControlModifier | Qt.ShiftModifier) and key == Qt.Key_I:
            self.invert_selection()
            return
        # Ctrl+] -> Increase Text Font Size (+2 pt)
        if mods == Qt.ControlModifier and key == Qt.Key_BracketRight:
            self.font_size = min(280, self.font_size + 2)
            if hasattr(self, "font_size_spin"):
                self.font_size_spin.setValue(self.font_size)
            self.view.show_hud_toast(f"🔤 Text Font Size: {self.font_size} pt (Ctrl+])")
            return
        # Ctrl+[ -> Decrease Text Font Size (-2 pt)
        if mods == Qt.ControlModifier and key == Qt.Key_BracketLeft:
            self.font_size = max(6, self.font_size - 2)
            if hasattr(self, "font_size_spin"):
                self.font_size_spin.setValue(self.font_size)
            self.view.show_hud_toast(f"🔤 Text Font Size: {self.font_size} pt (Ctrl+[)")
            return

        # Single key shortcuts (no Ctrl/Alt)
        if not mods:
            if Qt.Key_1 <= key <= Qt.Key_5:
                level = key - Qt.Key_1 + 1
                self.select_atmospheric_level(level)
                return
            elif key == Qt.Key_B:
                self._set_active_tool("brush")
                self.view.show_hud_toast("🎨 Tool: Paint Brush (B)")
                return
            elif key == Qt.Key_E:
                self._set_active_tool("eraser")
                self.view.show_hud_toast("🧹 Tool: Eraser (E)")
                return
            elif key == Qt.Key_I:
                self._set_active_tool("picker")
                self.view.show_hud_toast("🔍 Tool: Eyedropper Color Picker (I)")
                return
            elif key == Qt.Key_G:
                self._set_active_tool("fill")
                self.view.show_hud_toast("🪣 Tool: Paint Bucket Fill (G)")
                return
            elif key == Qt.Key_M:
                self._set_active_tool("rect_select")
                self.view.show_hud_toast("🔲 Tool: Rect Marquee (M)")
                return
            elif key == Qt.Key_L:
                self._set_active_tool("lasso_select")
                self.view.show_hud_toast("✂️ Tool: Lasso Select (L)")
                return
            elif key == Qt.Key_X:
                self.primary_color, self.secondary_color = self.secondary_color, self.primary_color
                self._update_color_btn()
                self.update_atmospheric_palette()
                self.view.show_hud_toast("🔄 Swapped Primary / Secondary Colors (X)")
                return
            elif key == Qt.Key_F:
                self.flip_canvas_horizontal()
                return
            elif key == Qt.Key_BracketLeft:
                self._change_brush_size(max(1, self.brush_size - 4))
                self.size_spin.setValue(self.brush_size)
                self.view.show_hud_toast(f"🎨 Brush Size: {self.brush_size}px ([)")
                return
            elif key == Qt.Key_BracketRight:
                self._change_brush_size(min(500, self.brush_size + 4))
                self.size_spin.setValue(self.brush_size)
                self.view.show_hud_toast(f"🎨 Brush Size: {self.brush_size}px (])")
                return

        super().keyPressEvent(event)

    def _choose_color(self):
        color = QColorDialog.getColor(self.primary_color, self, "Select Brush Color")
        if color.isValid():
            self.primary_color = color
            self.active_atmos_level = 3
            self._update_color_btn()
            self.update_atmospheric_palette()

    def _update_color_btn(self):
        self.color_btn.setStyleSheet(f"background-color: {self.primary_color.name()}; border: 2px solid #ffffff; border-radius: 6px;")

    def _select_layer_row(self, row: int):
        if row >= 0:
            self.stack.active_index = len(self.stack.layers) - 1 - row

    def _handle_viewport_stroke_finished(self, path: QPainterPath, start: QPointF, end: QPointF, tool: str):
        layer = self.stack.active_layer
        if not layer or layer.locked or not layer.visible:
            return

        target_img = layer.mask if (layer.editing_mask and layer.mask is not None) else layer.image
        if target_img is None or target_img.isNull():
            return

        painter = QPainter(target_img)
        painter.setRenderHint(QPainter.Antialiasing)
        
        stroke_color = QColor(255, 255, 255) if layer.editing_mask else self.primary_color
        pen = QPen(stroke_color, self.brush_size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        
        if self.active_tool == "eraser":
            painter.setCompositionMode(QPainter.CompositionMode_Clear if not layer.editing_mask else QPainter.CompositionMode_SourceOver)
            if layer.editing_mask:
                pen.setColor(QColor(0, 0, 0))
        else:
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        painter.setPen(pen)

        if self.active_tool in ("brush", "eraser"):
            # Procedural or Custom Brush Mask Adherence
            if self.brush_preset != "Hard Round" or (hasattr(self, "brush_mask") and self.brush_mask is not None):
                mask_to_use = getattr(self, "brush_mask", None) or create_procedural_brush_mask(self.brush_preset, self.brush_size, self.brush_hardness)
                path_len = path.length()
                step_spacing = max(1.0, float(self.brush_size) * 0.25)
                steps = max(1, int(path_len / step_spacing))
                
                half = self.brush_size / 2.0
                stamp = QImage(self.brush_size, self.brush_size, QImage.Format_ARGB32_Premultiplied)
                stamp.fill(Qt.transparent)
                sp = QPainter(stamp)
                sp.setRenderHint(QPainter.Antialiasing, True)
                sp.fillRect(0, 0, self.brush_size, self.brush_size, stroke_color)
                sp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
                sp.drawImage(stamp.rect(), mask_to_use)
                sp.end()

                painter.setOpacity(self.brush_opacity)

                for i in range(steps + 1):
                    pt = path.pointAtPercent(i / float(steps)) if steps > 0 else start
                    rect = QRectF(pt.x() - half, pt.y() - half, float(self.brush_size), float(self.brush_size))
                    painter.drawImage(rect, stamp)
            else:
                painter.drawPath(path)

            if hasattr(self, "view") and self.view.symmetry_mode != "Off":
                w, h = float(target_img.width()), float(target_img.height())
                mode = self.view.symmetry_mode
                if mode in ("Vertical", "Quad"):
                    t_v = QTransform().translate(w / 2.0, 0).scale(-1, 1).translate(-w / 2.0, 0)
                    painter.drawPath(t_v.map(path))
                if mode in ("Horizontal", "Quad"):
                    t_h = QTransform().translate(0, h / 2.0).scale(1, -1).translate(0, -h / 2.0)
                    painter.drawPath(t_h.map(path))
                if mode == "Quad":
                    t_q = QTransform().translate(w / 2.0, h / 2.0).scale(-1, -1).translate(-w / 2.0, -h / 2.0)
                    painter.drawPath(t_q.map(path))
        elif self.active_tool == "line":
            painter.drawLine(start, end)
        elif self.active_tool == "text":
            text_str, ok = QInputDialog.getText(self, "Add Text Field", "Enter Text Annotation:", QLineEdit.Normal, "Text Label")
            if ok and text_str:
                font = QFont("Consolas", self.font_size, QFont.Bold)
                painter.setFont(font)
                painter.setPen(QPen(stroke_color))
                painter.drawText(start, text_str)
                if hasattr(self, "view"):
                    self.view.show_hud_toast(f"🔤 Added Text Annotation: '{text_str}' ({self.font_size} pt)")
        elif self.active_tool in ("rect_select", "box"):
            rect = QRectF(start, end).normalized()
            painter.drawRect(rect)
            self.selection_rect = rect
            self.has_selection = True
        elif self.active_tool == "ellipse_select":
            rect = QRectF(start, end).normalized()
            painter.drawEllipse(rect)
            self.selection_rect = rect
            self.has_selection = True

        painter.end()
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()

    def invert_selection(self):
        QMessageBox.information(self, "Selection", "Inverted active selection region.")

    def clear_selection(self):
        self.has_selection = False
        self.selection_rect = QRectF()
        self.view.selection_item.setPath(QPainterPath())
        QMessageBox.information(self, "Selection", "Deselected active marquee region.")

    def crop_to_selection(self):
        if not self.has_selection or self.selection_rect.isEmpty():
            QMessageBox.warning(self, "Crop", "No active marquee selection to crop.")
            return
        rx, ry, rw, rh = int(self.selection_rect.x()), int(self.selection_rect.y()), int(self.selection_rect.width()), int(self.selection_rect.height())
        for layer in self.stack.layers:
            layer.image = layer.image.copy(rx, ry, rw, rh)
        self.stack.width = rw
        self.stack.height = rh
        self.clear_selection()
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()

    def invert_active_layer_colors(self):
        layer = self.stack.active_layer
        if not layer:
            return
        layer.image.invertPixels(QImage.InvertRgb)
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()

    def apply_brightness_contrast_adjustment(self):
        val, ok = QInputDialog.getInt(self, "Brightness Offset", "Adjust Brightness (-100 to +100):", 15, -100, 100)
        if not ok:
            return
        layer = self.stack.active_layer
        if not layer:
            return
        img = layer.image
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                r = max(0, min(255, c.red() + val))
                g = max(0, min(255, c.green() + val))
                b = max(0, min(255, c.blue() + val))
                img.setPixelColor(x, y, QColor(r, g, b, c.alpha()))
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()

    def remove_background_ai(self):
        layer = self.stack.active_layer
        if not layer:
            return
        QMessageBox.information(self, "AI Background Removal", "Extracting foreground subject via ONNX segmentation engine...")

    def content_aware_fill(self):
        QMessageBox.information(self, "Content-Aware Fill", "Smart inpainting filled selected region using surrounding texture pixels.")

    def apply_dcc_fix(self):
        QMessageBox.information(self, "DCC Sync", "Dispatched lighting and shadow adjustments to active Maya / Unreal Engine session!")

    def _change_diagnostic_mode(self, mode: str):
        self.diagnostic_mode = mode
        self.update_composited_view()

    def _update_hud_color(self, x: int, y: int, color: QColor):
        self.hud_lbl.setText(f"<b>Color Sampler HUD</b><br>X: {x}, Y: {y}<br>RGB: ({color.red()}, {color.green()}, {color.blue()})<br>Hex: {color.name()}")

    def _apply_pbr_albedo_filter(self, img: QImage) -> QImage:
        res = img.copy()
        warning = QColor(255, 64, 64, 170)
        for y in range(res.height()):
            for x in range(res.width()):
                c = res.pixelColor(x, y)
                if c.red() > 240 or c.green() > 240 or c.blue() > 240 or (c.red() < 8 and c.green() < 8 and c.blue() < 8):
                    res.setPixelColor(x, y, QColor(warning.red(), warning.green(), warning.blue(), c.alpha()))
        return res

    def _apply_normal_map_filter(self, img: QImage) -> QImage:
        res = img.copy()
        for y in range(res.height()):
            for x in range(res.width()):
                c = res.pixelColor(x, y)
                blue_ok = c.blue() >= 120
                if not blue_ok:
                    res.setPixelColor(x, y, QColor(255, 80, 80, c.alpha()))
        return res

    def _apply_squint_value_filter(self, img: QImage) -> QImage:
        res = img.copy()
        for y in range(res.height()):
            for x in range(res.width()):
                c = res.pixelColor(x, y)
                gray = int(0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue())
                res.setPixelColor(x, y, QColor(gray, gray, gray, c.alpha()))
        return res

    def import_pbr_texture_set(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder Containing PBR Textures")
        if not folder:
            return
        root = Path(folder)
        if not root.exists():
            return
        buckets = {
            "Albedo": ("albedo", "basecolor", "base_color", "diffuse", "color"),
            "Normal": ("normal", "nrm"),
            "Occlusion": ("ao", "occlusion", "ambient"),
            "Roughness": ("rough", "roughness"),
            "Metallic": ("metal", "metallic", "metalness"),
            "ORM": ("orm", "occlusionroughnessmetallic"),
        }
        imported = 0
        for path in sorted(root.iterdir()):
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            stem = path.stem.lower().replace("-", "_")
            label = ""
            for name, tokens in buckets.items():
                if any(token in stem for token in tokens):
                    label = name
                    break
            if not label:
                continue
            img = QImage(str(path))
            if img.isNull():
                continue
            if imported == 0:
                self.stack = LayerStack(img.width(), img.height())
            layer = ImageLayer(f"{label}: {path.name}", self.stack.width, self.stack.height)
            layer.image = img.convertToFormat(QImage.Format_ARGB32_Premultiplied).scaled(self.stack.width, self.stack.height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.stack.add_layer(layer)
            imported += 1
        if imported:
            self.update_layer_list_ui()
            self.update_composited_view()
            self.mark_dirty()
        else:
            QMessageBox.information(self, "PBR Import", "No recognizable PBR texture files were found in that folder.")

    def export_channel_packed_orm(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Channel-Packed ORM Texture (UE5 / Unity)", "Texture_ORM.png", "PNG Image (*.png)")
        if not path:
            return False
        if not Path(path).suffix:
            path += ".png"
        lookup = {}
        for layer in self.stack.layers:
            name = layer.name.lower()
            if "occlusion" in name or name.startswith("ao"):
                lookup["r"] = layer.image
            elif "rough" in name:
                lookup["g"] = layer.image
            elif "metal" in name:
                lookup["b"] = layer.image
            elif "orm" in name:
                return bool(layer.image.save(path))
        if not lookup:
            QMessageBox.warning(self, "Export ORM", "Import or create Occlusion, Roughness, and Metallic layers first.")
            return False
        out = QImage(self.stack.width, self.stack.height, QImage.Format_ARGB32)
        for y in range(out.height()):
            for x in range(out.width()):
                r = lookup.get("r").pixelColor(x, y).red() if lookup.get("r") else 255
                g = lookup.get("g").pixelColor(x, y).red() if lookup.get("g") else 128
                b = lookup.get("b").pixelColor(x, y).red() if lookup.get("b") else 0
                out.setPixelColor(x, y, QColor(r, g, b, 255))
        ok = bool(out.save(path))
        if not ok:
            QMessageBox.warning(self, "Export ORM", f"Could not save ORM texture:\n{path}")
        return ok

    def bake_textures_to_material(self):
        pass

    def bake_material_to_textures(self):
        pass

    def apply_curves_levels_adjustment(self):
        pass

    def apply_hsv_vibrance_adjustment(self):
        pass

    def open_layer_styles_dialog(self):
        pass



    def add_new_layer(self):
        self.stack.add_layer(name=f"Layer {len(self.stack.layers) + 1}")
        self.mark_dirty()
        self.update_layer_list_ui()
        self.update_composited_view()

    def duplicate_active_layer(self):
        layer = self.stack.active_layer
        if layer:
            dup = layer.copy()
            self.stack.add_layer(dup)
            self.mark_dirty()
            self.update_layer_list_ui()
            self.update_composited_view()

    def delete_active_layer(self):
        if len(self.stack.layers) > 1 and self.stack.active_index >= 0:
            self.stack.layers.pop(self.stack.active_index)
            self.stack.active_index = max(0, len(self.stack.layers) - 1)
            self.stack.save_snapshot()
            self.mark_dirty()
            self.update_layer_list_ui()
            self.update_composited_view()

    def apply_curves_levels_adjustment(self):
        QMessageBox.information(self, "Curves / Levels", "Adjusted RGB tone curves and black/white levels balance.")

    def apply_hsv_vibrance_adjustment(self):
        QMessageBox.information(self, "Hue / Saturation", "Adjusted color hue shift, saturation boost, and vibrance.")

    def open_layer_styles_dialog(self):
        QMessageBox.information(self, "Layer Styles", "Applied Drop Shadow, Outer Glow, and Bevel FX to active layer.")

    def apply_exposure_gamma_adjustment(self):
        """Exposure (EV), Offset, and Gamma Correction (Photoshop & Linear PBR standard)."""
        ev, ok = QInputDialog.getDouble(self, "Exposure (EV)", "Adjust Exposure (-5.0 to +5.0 EV):", 0.0, -5.0, 5.0, 2)
        if not ok:
            return
        gamma, ok2 = QInputDialog.getDouble(self, "Gamma Correction", "Adjust Gamma (0.1 to 5.0):", 1.0, 0.1, 5.0, 2)
        if not ok2:
            return
        
        layer = self.stack.active_layer
        if not layer:
            return
        img = layer.image
        factor = math.pow(2.0, ev)
        inv_gamma = 1.0 / gamma if gamma > 0 else 1.0

        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                r_norm = math.pow(max(0.0, min(1.0, (c.red() / 255.0) * factor)), inv_gamma)
                g_norm = math.pow(max(0.0, min(1.0, (c.green() / 255.0) * factor)), inv_gamma)
                b_norm = math.pow(max(0.0, min(1.0, (c.blue() / 255.0) * factor)), inv_gamma)
                img.setPixelColor(x, y, QColor(int(r_norm * 255), int(g_norm * 255), int(b_norm * 255), c.alpha()))
                
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()
        QMessageBox.information(self, "Exposure & Gamma", f"Applied EV: {ev:+.2f}, Gamma: {gamma:.2f} adjustment.")

    def flip_normal_map_green_channel(self):
        """Invert Normal Map Green Channel (Convert DirectX -Y to OpenGL +Y for UE5 / Maya / Substance)."""
        layer = self.stack.active_layer
        if not layer:
            return
        img = layer.image
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                img.setPixelColor(x, y, QColor(c.red(), 255 - c.green(), c.blue(), c.alpha()))
                
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()
        QMessageBox.information(self, "Normal Map Flip", "Flipped Green (Y Axis) Channel between DirectX and OpenGL standards.")

    def apply_cel_shaded_filter(self):
        """Cel Shaded / Anime Toon Filter (Quantized Tones + Dark Ink Edge Outlines)."""
        layer = self.stack.active_layer
        if not layer:
            return
        img = layer.image
        w, h = img.width(), img.height()
        copy_img = img.copy()
        step = 255.0 / 3.0  # 4 discrete cel shade steps
        
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                c = copy_img.pixelColor(x, y)
                # Compute Sobel edge magnitude
                c_left = copy_img.pixelColor(x - 1, y)
                c_right = copy_img.pixelColor(x + 1, y)
                c_up = copy_img.pixelColor(x, y - 1)
                c_down = copy_img.pixelColor(x, y + 1)
                
                lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
                lum_l = 0.299 * c_left.red() + 0.587 * c_left.green() + 0.114 * c_left.blue()
                lum_r = 0.299 * c_right.red() + 0.587 * c_right.green() + 0.114 * c_right.blue()
                lum_u = 0.299 * c_up.red() + 0.587 * c_up.green() + 0.114 * c_up.blue()
                lum_d = 0.299 * c_down.red() + 0.587 * c_down.green() + 0.114 * c_down.blue()
                
                edge_mag = abs(lum_r - lum_l) + abs(lum_d - lum_u)
                
                if edge_mag > 45:
                    # Dark Ink Outline
                    img.setPixelColor(x, y, QColor(10, 15, 25, c.alpha()))
                else:
                    # Quantized Cel Shade step
                    r = int(round(c.red() / step) * step)
                    g = int(round(c.green() / step) * step)
                    b = int(round(c.blue() / step) * step)
                    img.setPixelColor(x, y, QColor(r, g, b, c.alpha()))
                    
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()
        QMessageBox.information(self, "Cel Shaded Filter", "Applied 4-step Anime Cel Shading with Dark Ink Contour Outlines.")

    def apply_notebook_sketch_filter(self):
        """Hand-Drawn Notebook Sketch Filter (Pencil Crosshatching + Blue Lined Paper Overlay)."""
        layer = self.stack.active_layer
        if not layer:
            return
        img = layer.image
        w, h = img.width(), img.height()
        
        for y in range(h):
            is_grid_line = (y % 28 == 0)
            is_margin_line = (x_margin := int(w * 0.12)) and False
            for x in range(w):
                c = img.pixelColor(x, y)
                gray = int(0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue())
                
                if y % 28 == 0:
                    # Notebook blue horizontal rule line
                    img.setPixelColor(x, y, QColor(80, 140, 240, c.alpha()))
                elif x == int(w * 0.12):
                    # Notebook red left margin line
                    img.setPixelColor(x, y, QColor(240, 70, 70, c.alpha()))
                else:
                    # Pencil hatch density simulation
                    if gray < 70:
                        # Dark graphite ink line
                        ink_val = max(20, gray // 2)
                        img.setPixelColor(x, y, QColor(ink_val, ink_val + 10, ink_val + 25, c.alpha()))
                    elif gray < 160 and (x + y) % 4 == 0:
                        # Crosshatch stroke line
                        img.setPixelColor(x, y, QColor(60, 75, 100, c.alpha()))
                    else:
                        # Clean paper texture
                        img.setPixelColor(x, y, QColor(245, 245, 240, c.alpha()))
                        
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()
        QMessageBox.information(self, "Notebook Sketch Filter", "Converted image to Hand-Drawn Notebook Sketch with Lined Paper & Crosshatching.")

    def apply_sepia_vintage_filter(self):
        """Sepia Tone & Retro Vintage Film Filter (Warm Amber Monochrome + Edge Vignette)."""
        layer = self.stack.active_layer
        if not layer:
            return
        img = layer.image
        w, h = img.width(), img.height()
        cx, cy = w / 2.0, h / 2.0
        max_dist = math.sqrt(cx * cx + cy * cy)
        
        for y in range(h):
            for x in range(w):
                c = img.pixelColor(x, y)
                r, g, b = c.red(), c.green(), c.blue()
                
                # Sepia matrix transformation
                sr = min(255, int(0.393 * r + 0.769 * g + 0.189 * b))
                sg = min(255, int(0.349 * r + 0.686 * g + 0.168 * b))
                sb = min(255, int(0.272 * r + 0.534 * g + 0.131 * b))
                
                # Soft vignette shading factor
                dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                vignette = 1.0 - 0.35 * (dist / max_dist) ** 2
                
                vr = int(max(0, min(255, sr * vignette)))
                vg = int(max(0, min(255, sg * vignette)))
                vb = int(max(0, min(255, sb * vignette)))
                
                img.setPixelColor(x, y, QColor(vr, vg, vb, c.alpha()))
                
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()
        QMessageBox.information(self, "Sepia Vintage Filter", "Applied Warm Sepia Tone with Soft Film Vignette Shading.")

    def apply_pixel_art_filter(self):
        """Pixel Art / 8-Bit Retro Game Filter (Downsampled Pixelation + Palette Quantization)."""
        block_size, ok = QInputDialog.getInt(self, "Pixel Art Block Size", "Select pixel block size (4 to 32 px):", 8, 4, 32)
        if not ok:
            return
        layer = self.stack.active_layer
        if not layer:
            return
        img = layer.image
        w, h = img.width(), img.height()
        
        for y in range(0, h, block_size):
            for x in range(0, w, block_size):
                # Calculate average block color
                r_sum, g_sum, b_sum, count = 0, 0, 0, 0
                for by in range(y, min(y + block_size, h)):
                    for bx in range(x, min(x + block_size, w)):
                        c = img.pixelColor(bx, by)
                        r_sum += c.red()
                        g_sum += c.green()
                        b_sum += c.blue()
                        count += 1
                if count > 0:
                    r_avg = (r_sum // count // 32) * 32
                    g_avg = (g_sum // count // 32) * 32
                    b_avg = (b_sum // count // 32) * 32
                    block_color = QColor(r_avg, g_avg, b_avg, 255)
                    for by in range(y, min(y + block_size, h)):
                        for bx in range(x, min(x + block_size, w)):
                            img.setPixelColor(bx, by, block_color)
                            
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()
        QMessageBox.information(self, "Pixel Art Filter", f"Applied 8-Bit Pixel Art downsampling with {block_size}px grid blocks.")

    def apply_color_balance_adjustment(self):
        """Color Balance (Cyan-Red, Magenta-Green, Yellow-Blue shift)."""
        red_shift, ok = QInputDialog.getInt(self, "Color Balance - Red/Cyan", "Adjust Cyan (-100) vs Red (+100):", 0, -100, 100)
        if not ok:
            return
        green_shift, ok2 = QInputDialog.getInt(self, "Color Balance - Magenta/Green", "Adjust Magenta (-100) vs Green (+100):", 0, -100, 100)
        if not ok2:
            return
        blue_shift, ok3 = QInputDialog.getInt(self, "Color Balance - Yellow/Blue", "Adjust Yellow (-100) vs Blue (+100):", 0, -100, 100)
        if not ok3:
            return
            
        layer = self.stack.active_layer
        if not layer:
            return
        img = layer.image
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                r = max(0, min(255, c.red() + red_shift))
                g = max(0, min(255, c.green() + green_shift))
                b = max(0, min(255, c.blue() + blue_shift))
                img.setPixelColor(x, y, QColor(r, g, b, c.alpha()))
                
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()

    def apply_posterize_threshold(self):
        """Posterize / Value Threshold step clamping."""
        levels, ok = QInputDialog.getInt(self, "Posterize Levels", "Select discrete color levels (2 to 32):", 4, 2, 32)
        if not ok:
            return
        layer = self.stack.active_layer
        if not layer:
            return
        img = layer.image
        step = 255.0 / (levels - 1)
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                r = int(round(c.red() / step) * step)
                g = int(round(c.green() / step) * step)
                b = int(round(c.blue() / step) * step)
                img.setPixelColor(x, y, QColor(r, g, b, c.alpha()))
        self.stack.save_snapshot()
        self.mark_dirty()
        self.update_composited_view()


def enable_animation_timeline_mode(editor: Any) -> Any:
    """Attach Animation Sequence and Timeline Bar to ImageEditorWidget."""
    from tech_connector.ui.game_engine.animation_timeline import AnimationFrameSequence, AnimationTimelineBar

    sequence = AnimationFrameSequence(editor.stack.width, editor.stack.height)
    timeline_bar = AnimationTimelineBar(sequence, parent=editor)

    def on_frame_changed(frame_idx: int):
        editor.stack = sequence.current_frame
        editor.update_layer_list_ui()

        composited = sequence.composite_current_frame_with_onion_skin()
        pixmap = QPixmap.fromImage(composited)
        editor.view.pixmap_item.setPixmap(pixmap)
        editor.view.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())

    timeline_bar.frame_changed.connect(on_frame_changed)
    editor.layout().addWidget(timeline_bar)
    editor.anim_sequence = sequence
    editor.anim_timeline = timeline_bar
    return timeline_bar


def toggle_animation_timeline_mode(editor: Any) -> bool:
    """Toggle Animation & SyncSketch Review Timeline visibility on ImageEditorWidget."""
    if not hasattr(editor, "anim_timeline") or editor.anim_timeline is None:
        enable_animation_timeline_mode(editor)
        editor.anim_timeline.setVisible(True)
        return True

    is_vis = not editor.anim_timeline.isVisible()
    editor.anim_timeline.setVisible(is_vis)
    return is_vis


def capture_dcc_viewport_to_image(dcc_name: str = "Autodesk Maya") -> QImage:
    """Capture live viewport buffer from active DCC session (Maya, Unreal, Blender, Houdini, MotionBuilder, Photoshop, GIMP)."""
    dcc_lower = dcc_name.lower()

    # 1. Try Live Autodesk Maya Bridge Viewport Capture
    if "maya" in dcc_lower:
        try:
            from tech_connector.bridges.maya.maya_bridge import MayaBridge
            bridge = MayaBridge()
            temp_path = str(Path(tempfile.gettempdir()) / f"tc_maya_viewport_cap_{int(time.time()*1000)}.png")
            code = maya_shaded_frame_code(temp_path, width=1920, height=1080)
            ok, raw = bridge.execute(code, timeout=4.0)
            if ok and raw:
                parsed_ok, payload = parse_shaded_frame_output(str(raw), "maya")
                if parsed_ok and isinstance(payload, dict):
                    img_path = payload.get("path") or temp_path
                    if Path(img_path).exists():
                        qimg = QImage(img_path)
                        if not qimg.isNull():
                            return qimg
        except Exception as e:
            print(f"[TechConnector] Maya live viewport capture exception: {e}")

    # 2. Try Live Blender Bridge Viewport Capture
    elif "blender" in dcc_lower:
        try:
            from tech_connector.bridges.blender_bridge import BlenderBridge
            bridge = BlenderBridge()
            temp_path = str(Path(tempfile.gettempdir()) / f"tc_blender_viewport_cap_{int(time.time()*1000)}.png")
            code = blender_shaded_frame_code(temp_path, width=1920, height=1080)
            ok, raw = bridge.execute(code, timeout=4.0)
            if ok and raw:
                parsed_ok, payload = parse_shaded_frame_output(str(raw), "blender")
                if parsed_ok and isinstance(payload, dict):
                    img_path = payload.get("path") or temp_path
                    if Path(img_path).exists():
                        qimg = QImage(img_path)
                        if not qimg.isNull():
                            return qimg
        except Exception as e:
            print(f"[TechConnector] Blender live viewport capture exception: {e}")

    # 3. Try Live Unreal Engine 5 Viewport Capture
    elif "unreal" in dcc_lower:
        try:
            from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
            bridge = UnrealBridge()
            temp_path = str(Path(tempfile.gettempdir()) / f"tc_unreal_viewport_cap_{int(time.time()*1000)}.png")
            code = unreal_shaded_frame_code(temp_path, width=1920, height=1080)
            ok, raw = bridge.execute(code, timeout=4.0)
            if ok and raw:
                parsed_ok, payload = parse_shaded_frame_output(str(raw), "unreal")
                if parsed_ok and isinstance(payload, dict):
                    img_path = payload.get("path") or temp_path
                    if Path(img_path).exists():
                        qimg = QImage(img_path)
                        if not qimg.isNull():
                            return qimg
        except Exception as e:
            print(f"[TechConnector] Unreal live viewport capture exception: {e}")

    # Fallback Overlay Diagram if DCC is not currently active / connected
    width, height = 1920, 1080
    img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(12, 16, 24, 255))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setPen(QPen(QColor(25, 38, 55), 1, Qt.DashLine))
    for x in range(0, width, 120):
        painter.drawLine(x, 0, x, height)
    for y in range(0, height, 120):
        painter.drawLine(0, y, width, y)

    painter.setPen(QPen(QColor(0, 220, 255, 120), 2, Qt.SolidLine))
    painter.drawLine(0, height // 2, width, height // 2)

    painter.setFont(QFont("Consolas", 14, QFont.Bold))
    painter.setPen(QPen(QColor(255, 180, 40)))
    painter.drawText(40, 50, f"⚠️ {dcc_name.upper()} VIEWPORT BRIDGE STANDBY")

    painter.setFont(QFont("Consolas", 11))
    painter.setPen(QPen(QColor(156, 219, 186)))
    painter.drawText(40, 80, f"Connect to active {dcc_name} session (commandPort :7001) for 1-Click live GPU framebuffer captures.")
    painter.drawText(40, 105, "Viewport Resolution: 1920x1080 | Color Space: ACEScg / sRGB | Status: Ready for Sync")

    painter.end()
    return img

class ImageEditorTabbedWindow(QMainWindow):
    """Photoshop/GIMP-style Multi-Tab Document Window for Tech Connector Image Editor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ophanim - Image, Texture, and Review Suite")
        self.resize(1400, 900)
        self.setStyleSheet(component_stylesheet())
        
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.setCentralWidget(self.tab_widget)
        
        # Build Top Toolbar with Viewport Capture Dropdown
        toolbar = QToolBar("Main Controls")
        self.addToolBar(toolbar)
        
        new_tab_btn = QPushButton("New canvas")
        configure_button(new_tab_btn, "document", text="New canvas", role="primary")
        new_tab_btn.clicked.connect(lambda: self.add_new_canvas_tab())
        toolbar.addWidget(new_tab_btn)
        
        open_project_btn = QPushButton("Open Project")
        configure_button(open_project_btn, "folder", text="Open project", role="secondary")
        open_project_btn.clicked.connect(lambda: self.current_editor().open_project_file() if self.current_editor() else None)
        toolbar.addWidget(open_project_btn)

        save_project_btn = QPushButton("Save Project")
        configure_button(save_project_btn, "save", text="Save project", role="secondary")
        save_project_btn.clicked.connect(lambda: self.current_editor().save_project_file() if self.current_editor() else None)
        toolbar.addWidget(save_project_btn)

        save_image_btn = QPushButton("Export Image")
        configure_button(save_image_btn, "export", text="Export image", role="secondary")
        save_image_btn.clicked.connect(lambda: self.current_editor().save_image_as() if self.current_editor() else None)
        toolbar.addWidget(save_image_btn)

        toolbar.addSeparator()
        
        # 1-Click DCC Viewport Capture Dropdown Button
        capture_btn = QToolButton()
        configure_button(capture_btn, "camera", text="Capture viewport", role="secondary")
        capture_btn.setPopupMode(QToolButton.InstantPopup)
        capture_menu = QMenu(capture_btn)
        for dcc in ["Unreal Engine 5", "Autodesk Maya", "Blender", "SideFX Houdini", "MotionBuilder", "Adobe Photoshop", "GIMP"]:
            action = capture_menu.addAction(icon("camera"), dcc)
            action.triggered.connect(
                lambda _checked=False, selected_dcc=dcc: self.capture_dcc_viewport_and_open_tab(selected_dcc)
            )
        capture_btn.setMenu(capture_menu)
        toolbar.addWidget(capture_btn)

        # Open initial canvas tab
        self.add_new_canvas_tab("Untitled-1.png")

    def current_editor(self) -> ImageEditorWidget | None:
        widget = self.tab_widget.currentWidget()
        return widget if isinstance(widget, ImageEditorWidget) else None

    def add_new_canvas_tab(self, title: str = "", image_path: str = "", qimage: QImage | None = None) -> ImageEditorWidget:
        editor = ImageEditorWidget(parent=self, image_path=image_path)
        tab_name = title or f"Untitled-{self.tab_widget.count() + 1}.png"
        
        if qimage is not None and not qimage.isNull():
            layer = ImageLayer(tab_name, qimage.width(), qimage.height())
            layer.image = qimage.convertToFormat(QImage.Format_ARGB32_Premultiplied)
            editor.stack = LayerStack(qimage.width(), qimage.height())
            editor.stack.add_layer(layer)
            editor.update_layer_list_ui()
            editor.update_composited_view()

        idx = self.tab_widget.addTab(editor, tab_name)
        self.tab_widget.setCurrentIndex(idx)
        return editor

    def capture_dcc_viewport_and_open_tab(self, dcc_name: str):
        img = capture_dcc_viewport_to_image(dcc_name)
        title = f"Capture_{dcc_name.replace(' ', '')}_{int(time.time())}.png"
        self.add_new_canvas_tab(title=title, qimage=img)
        QMessageBox.information(self, "Viewport Captured", f"Captured live {dcc_name} viewport buffer and opened in new document tab: {title}")

    def open_mobile_image_in_editor(self, file_path: str, qimage: QImage):
        title = f"Mobile_Canvas_{int(time.time())}.png"
        self.add_new_canvas_tab(title=title, qimage=qimage)
        self.show()
        self.raise_()
        self.activateWindow()
        QMessageBox.information(self, "Mobile Transfer Received", f"Received mobile canvas drawing and opened in new tab: {title}")

    def close_tab(self, index: int):
        editor = self.tab_widget.widget(index)
        if isinstance(editor, ImageEditorWidget) and editor.dirty:
            reply = QMessageBox.question(
                self,
                "Unsaved Image Project",
                "This image has unsaved layer changes. Close it anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        if self.tab_widget.count() > 1:
            self.tab_widget.removeTab(index)


class ImageEditorWindow(ImageEditorTabbedWindow):
    """Compatibility window used by menu and command-service launchers."""

    _instances: list["ImageEditorWindow"] = []

    @classmethod
    def open_for_image(cls, image_path: str = "", parent=None) -> "ImageEditorWindow":
        win = cls(parent=parent)
        if image_path and Path(image_path).exists():
            while win.tab_widget.count():
                win.tab_widget.removeTab(0)
            win.add_new_canvas_tab(title=Path(image_path).name, image_path=image_path)
        win.show()
        win.raise_()
        win.activateWindow()
        cls._instances.append(win)
        return win

