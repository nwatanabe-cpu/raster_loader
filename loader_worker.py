# -*- coding: utf-8 -*-
"""
バックグラウンド処理ワーカー

【スレッド安全の原則】
QGISオブジェクト（QgsCoordinateTransform等）はメインスレッド専用。
workerにはBBox変換済みの QgsRectangle のみ渡し、
ファイルI/O（GDAL）だけをスレッド内で行う。
"""

import os

from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis.core import QgsRectangle

from .tile_finder import find_intersecting_tiles, log


class LoaderWorker(QThread):
    """
    選択されたソースを順次検索し、交差ファイルのパスをシグナルで返す。

    シグナル:
      progress(str)                         ログ文字列
      source_done(str, list[str])           (source_name, [file_path, ...])
      source_skipped(str, str)              (source_name, reason)
      all_done()
    """
    progress = pyqtSignal(str)
    source_done = pyqtSignal(str, list)    # list = list[str]
    source_skipped = pyqtSignal(str, str)
    all_done = pyqtSignal()

    def __init__(self, sources: list[dict], bbox_6676: QgsRectangle):
        super().__init__()
        self.sources = sources
        self.bbox = bbox_6676
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            for i, src in enumerate(self.sources):
                if self._cancelled:
                    self.progress.emit("⛔ キャンセルされました")
                    break

                name = src["name"]
                folder = src["path"]
                self.progress.emit(f"\n[{i+1}/{len(self.sources)}] 検索中: {name}")

                try:
                    matched = find_intersecting_tiles(folder, self.bbox)
                except Exception as e:
                    self.progress.emit(f"  ❌ タイル検索エラー: {e}")
                    self.source_skipped.emit(name, f"検索エラー: {e}")
                    continue

                if self._cancelled:
                    self.progress.emit("⛔ キャンセルされました")
                    break

                if not matched:
                    self.progress.emit("  → 交差ラスタなし（スキップ）")
                    self.source_skipped.emit(name, "交差ラスタなし")
                    continue

                self.progress.emit(f"  → {len(matched)} ファイルヒット")
                self.source_done.emit(name, matched)

        except Exception as e:
            self.progress.emit(f"❌ 予期しないエラー: {e}")
        finally:
            self.all_done.emit()
