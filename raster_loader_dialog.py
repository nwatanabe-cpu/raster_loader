# -*- coding: utf-8 -*-
"""
Raster Loader - メインダイアログ

新機能:
  - データソースをQTreeWidgetでツリー表示・サブフォルダ単位でチェック
  - 範囲指定をキャンバス / 任意レイヤーで切り替え可能
"""

import os

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QSizePolicy, QProgressBar,
    QMessageBox, QTextEdit, QFrame, QFileDialog,
    QTreeWidget, QTreeWidgetItem, QRadioButton, QAbstractItemView,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont, QBrush, QColor

from qgis.core import (
    QgsProject,
    QgsMapLayer,
    QgsRasterLayer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
)

from .source_manager import SourceManager
from .loader_worker import LoaderWorker
from .tile_finder import layer_bbox_6676, COMPARE_EPSG


class RasterLoaderDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.src_mgr = SourceManager(self.plugin_dir)
        self.worker = None

        self.setWindowTitle("Raster Loader")
        self.setMinimumWidth(540)
        self.setMinimumHeight(660)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._build_ui()
        self.refresh_sources()
        self.refresh_layers()

    # ── UI構築 ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(14, 14, 14, 10)

        title = QLabel("🗂  Raster Loader")
        f = QFont(); f.setPointSize(13); f.setBold(True)
        title.setFont(f)
        root.addWidget(title)

        sub = QLabel("ポリゴン範囲と交差するラスタタイルを複数フォルダから一括読み込み")
        sub.setStyleSheet("color: gray; font-size: 11px;")
        root.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        root.addWidget(self._build_source_group())
        root.addWidget(self._build_extent_group())

        # 実行・キャンセルボタン行
        run_row = QHBoxLayout()
        self.btn_run = QPushButton("▶  選択したソースを一括読み込み")
        self.btn_run.setFixedHeight(40)
        self.btn_run.setStyleSheet(
            "QPushButton { background:#2e7d32; color:white; font-weight:bold;"
            "border-radius:4px; font-size:13px; }"
            "QPushButton:hover { background:#388e3c; }"
            "QPushButton:disabled { background:#bdbdbd; }"
        )
        self.btn_run.clicked.connect(self.run)
        run_row.addWidget(self.btn_run)

        self.btn_cancel = QPushButton("⛔  キャンセル")
        self.btn_cancel.setFixedHeight(40)
        self.btn_cancel.setFixedWidth(130)
        self.btn_cancel.setStyleSheet(
            "QPushButton { background:#c62828; color:white; font-weight:bold;"
            "border-radius:4px; font-size:13px; }"
            "QPushButton:hover { background:#e53935; }"
            "QPushButton:disabled { background:#bdbdbd; }"
        )
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel)
        run_row.addWidget(self.btn_cancel)
        root.addLayout(run_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        log_group = QGroupBox("ログ")
        log_layout = QVBoxLayout(log_group)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(110)
        self.log_box.setFont(QFont("Courier", 10))
        self.log_box.setStyleSheet("background:#f5f5f5;")
        log_layout.addWidget(self.log_box)
        root.addWidget(log_group)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_close = QPushButton("閉じる")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    # ── データソースグループ（ツリー） ─────────────────────────────────────────

    def _build_source_group(self) -> QGroupBox:
        grp = QGroupBox("データソース")
        layout = QVBoxLayout(grp)
        layout.setSpacing(4)

        hint = QLabel("📁 内部フォルダ  🔗 外部フォルダ  ― サブフォルダ単位でチェック可")
        hint.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(hint)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(200)
        self.tree.setMaximumHeight(280)
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.tree.itemChanged.connect(self._on_tree_item_changed)
        layout.addWidget(self.tree)

        ctrl = QHBoxLayout()
        btn_all = QPushButton("すべて選択")
        btn_all.setFixedHeight(26)
        btn_all.clicked.connect(self._check_all)
        btn_none = QPushButton("すべて解除")
        btn_none.setFixedHeight(26)
        btn_none.clicked.connect(self._check_none)
        ctrl.addWidget(btn_all)
        ctrl.addWidget(btn_none)
        ctrl.addStretch()
        btn_add = QPushButton("＋ 外部フォルダを追加")
        btn_add.setFixedHeight(26)
        btn_add.setStyleSheet(
            "QPushButton { background:#1565c0; color:white; border-radius:3px; padding:0 8px; }"
            "QPushButton:hover { background:#1976d2; }"
        )
        btn_add.clicked.connect(self._add_external)
        ctrl.addWidget(btn_add)
        layout.addLayout(ctrl)

        return grp

    # ── 範囲指定グループ ───────────────────────────────────────────────────────

    def _build_extent_group(self) -> QGroupBox:
        grp = QGroupBox("検索範囲")
        layout = QVBoxLayout(grp)
        layout.setSpacing(6)

        radio_row = QHBoxLayout()
        self.radio_canvas = QRadioButton("🖥  キャンバス範囲")
        self.radio_layer  = QRadioButton("📄  レイヤー範囲")
        self.radio_canvas.setChecked(True)
        radio_row.addWidget(self.radio_canvas)
        radio_row.addWidget(self.radio_layer)
        radio_row.addStretch()
        layout.addLayout(radio_row)

        layer_row = QHBoxLayout()
        self.combo_layer = QComboBox()
        self.combo_layer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layer_row.addWidget(self.combo_layer)
        btn_ref = QPushButton("🔄")
        btn_ref.setFixedWidth(34)
        btn_ref.setToolTip("レイヤー一覧を更新")
        btn_ref.clicked.connect(self.refresh_layers)
        layer_row.addWidget(btn_ref)
        layout.addLayout(layer_row)

        self.radio_canvas.toggled.connect(self._on_mode_changed)
        self._on_mode_changed()

        return grp

    def _on_mode_changed(self):
        self.combo_layer.setEnabled(self.radio_layer.isChecked())

    # ── ツリー操作 ─────────────────────────────────────────────────────────────

    def refresh_sources(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        for root_src in self.src_mgr.get_tree():
            root_item = self._make_tree_item(root_src, is_root=True)
            self.tree.addTopLevelItem(root_item)
            root_item.setExpanded(True)
        self.tree.blockSignals(False)

    def _make_tree_item(self, node: dict, is_root: bool = False) -> QTreeWidgetItem:
        name  = node["name"]
        total = node["count"]
        direct = node.get("direct_count", 0)

        if is_root:
            icon = "📁" if node.get("kind") == "internal" else "🔗"
            label = f"{icon} {name}  [{total} files]"
        else:
            label = f"📂 {name}  [{total} files]"

        item = QTreeWidgetItem([label])
        item.setData(0, Qt.UserRole, node["path"])
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
        item.setCheckState(0, Qt.Checked if total > 0 else Qt.Unchecked)

        if is_root and node.get("kind") == "external":
            item.setForeground(0, QBrush(QColor("#1565c0")))

        # ルート直下に直置きファイルがある場合は専用子ノードを追加
        if is_root and direct > 0:
            di = QTreeWidgetItem([f"  ／ (直下ファイル)  [{direct} files]"])
            di.setData(0, Qt.UserRole, node["path"])
            di.setFlags(di.flags() | Qt.ItemIsUserCheckable)
            di.setCheckState(0, Qt.Checked)
            di.setForeground(0, QBrush(QColor("gray")))
            item.addChild(di)

        for child in node.get("children", []):
            item.addChild(self._make_tree_item(child, is_root=False))

        return item

    def _on_tree_item_changed(self, item: QTreeWidgetItem, col: int):
        """親チェック変更時に子を連動させる。"""
        self.tree.blockSignals(True)
        state = item.checkState(0)
        if state != Qt.PartiallyChecked:
            self._set_children_check(item, state)
        self.tree.blockSignals(False)

    def _set_children_check(self, item: QTreeWidgetItem, state):
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            self._set_children_check(child, state)

    def _check_all(self):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            top.setCheckState(0, Qt.Checked)
            self._set_children_check(top, Qt.Checked)
        self.tree.blockSignals(False)

    def _check_none(self):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            top.setCheckState(0, Qt.Unchecked)
            self._set_children_check(top, Qt.Unchecked)
        self.tree.blockSignals(False)

    def _collect_checked_paths(self) -> list[dict]:
        """チェックされた末端フォルダのパスを重複なく収集する。"""
        result = []
        seen = set()
        self._walk_checked(self.tree.invisibleRootItem(), result, seen)
        return result

    def _walk_checked(self, item: QTreeWidgetItem, result: list, seen: set):
        for i in range(item.childCount()):
            child = item.child(i)
            if child.checkState(0) not in (Qt.Checked, Qt.PartiallyChecked):
                continue
            if child.childCount() == 0:
                path = child.data(0, Qt.UserRole)
                if path and path not in seen:
                    seen.add(path)
                    name = child.text(0).split("  [")[0].strip().lstrip("📂／ ")
                    result.append({"path": path, "name": name})
            else:
                self._walk_checked(child, result, seen)

    # ── 外部フォルダ追加 ──────────────────────────────────────────────────────

    def _add_external(self):
        folder = QFileDialog.getExistingDirectory(
            self, "フォルダを選択", "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if not folder:
            return
        if not self.src_mgr.add_external_source(folder):
            QMessageBox.information(self, "情報", "そのフォルダはすでに登録されています。")
        self.refresh_sources()

    # ── レイヤー一覧 ──────────────────────────────────────────────────────────

    def refresh_layers(self):
        self.combo_layer.clear()
        layers = list(QgsProject.instance().mapLayers().values())
        if not layers:
            self.combo_layer.addItem("（レイヤーが見つかりません）")
        else:
            for lyr in layers:
                icon = "🟦" if lyr.type() == QgsMapLayer.RasterLayer else "🟩"
                self.combo_layer.addItem(f"{icon} {lyr.name()}", lyr.id())

    # ── BBox取得（メインスレッド） ────────────────────────────────────────────

    def _get_bbox(self):
        if self.radio_canvas.isChecked():
            canvas = self.iface.mapCanvas()
            extent = canvas.extent()
            src_crs = canvas.mapSettings().destinationCrs()
            dst_crs = QgsCoordinateReferenceSystem(f"EPSG:{COMPARE_EPSG}")
            if src_crs == dst_crs:
                return extent
            tr = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
            return tr.transformBoundingBox(extent)
        else:
            layer_id = self.combo_layer.currentData()
            if not layer_id:
                return None
            lyr = QgsProject.instance().mapLayer(layer_id)
            return layer_bbox_6676(lyr) if lyr else None

    # ── 実行 ─────────────────────────────────────────────────────────────────

    def run(self):
        sources = self._collect_checked_paths()
        if not sources:
            QMessageBox.warning(self, "警告", "1つ以上のフォルダにチェックを入れてください。")
            return

        if self.radio_layer.isChecked() and not self.combo_layer.currentData():
            QMessageBox.warning(self, "警告", "レイヤーを選択してください。")
            return

        bbox = self._get_bbox()
        if bbox is None:
            QMessageBox.critical(self, "エラー", "範囲の取得に失敗しました。")
            return

        self._set_running(True)
        self.log_box.clear()
        self._log(f"対象フォルダ: {len(sources)} 件")
        self._log(
            f"BBox (EPSG:{COMPARE_EPSG}): "
            f"X {bbox.xMinimum():.1f}〜{bbox.xMaximum():.1f} / "
            f"Y {bbox.yMinimum():.1f}〜{bbox.yMaximum():.1f}"
        )

        self.worker = LoaderWorker(sources, bbox)
        self.worker.progress.connect(self._log)
        self.worker.source_done.connect(self._on_source_done)
        self.worker.source_skipped.connect(self._on_source_skipped)
        self.worker.all_done.connect(self._on_all_done)
        self.worker.start()

    # ── レイヤー追加・グループ管理 ────────────────────────────────────────────

    def _get_or_create_group(self):
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup("ラスタ")
        if group is None:
            group = root.insertGroup(0, "ラスタ")
        return group

    def _on_source_done(self, name: str, file_paths: list):
        if self.radio_canvas.isChecked():
            scope = "キャンバス"
        else:
            scope = self.combo_layer.currentText().lstrip("🟦🟩 ")

        parent_group = self._get_or_create_group()
        sub_name = f"{name}  ({scope})"
        sub_group = parent_group.findGroup(sub_name) or parent_group.addGroup(sub_name)

        added = 0
        for fpath in file_paths:
            layer_name = os.path.splitext(os.path.basename(fpath))[0]
            rl = QgsRasterLayer(fpath, layer_name)
            if rl.isValid():
                QgsProject.instance().addMapLayer(rl, False)
                sub_group.addLayer(rl)
                added += 1
            else:
                self._log(f"  ⚠ 読み込み失敗: {os.path.basename(fpath)}")

        self._log(f"  ✅ {added} レイヤーを「ラスタ > {sub_name}」に追加")
        if added:
            self.iface.messageBar().pushSuccess(
                "Raster Loader", f"{added} レイヤー追加 → ラスタ > {sub_name}"
            )

    def _on_source_skipped(self, name: str, reason: str):
        self.iface.messageBar().pushWarning(
            "Raster Loader", f"スキップ: {name} — {reason}"
        )

    def _on_all_done(self):
        self._set_running(False)
        self._log("\n✅ すべての処理が完了しました。")

    def _cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)
            self._log("⛔ キャンセル要求を送信しました...")

    def _set_running(self, running: bool):
        self.btn_run.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        self.progress.setVisible(running)

    def _log(self, msg: str):
        self.log_box.append(msg)
        self.log_box.verticalScrollBar().setValue(
            self.log_box.verticalScrollBar().maximum()
        )
