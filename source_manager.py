# -*- coding: utf-8 -*-
"""
フォルダ（データソース）の登録・管理
- プラグイン内部の data/ フォルダは常に自動スキャン
- 外部フォルダはJSON設定ファイルで永続管理
"""

import os
import json

SETTINGS_FILE_NAME = "sources.json"


class SourceManager:
    """
    データソース（フォルダ）の管理クラス。

    sources.json 形式:
    [
        {"path": "/path/to/folder", "kind": "external"}
    ]
    内部フォルダはJSONに保存せず、毎回 data/ を自動スキャンする。
    """

    def __init__(self, plugin_dir: str):
        self.plugin_dir = plugin_dir
        self.internal_root = os.path.join(plugin_dir, "data")
        self.settings_path = os.path.join(plugin_dir, SETTINGS_FILE_NAME)
        os.makedirs(self.internal_root, exist_ok=True)

    # ── ツリー構造取得 ──────────────────────────────────────────────────────────

    def get_tree(self) -> list[dict]:
        """
        ツリーUI用のデータ構造を返す。
        各ルートソースに children リストを持たせ、
        children はそのフォルダ直下のサブフォルダを表す。

        返り値:
        [
          {
            "path": "/abs/path",
            "name": "表示名",
            "kind": "internal" | "external",
            "count": N,           # 直下ラスタ数
            "children": [
              {"path": ..., "name": ..., "count": ..., "direct_count": ...},
              ...
            ]
          },
          ...
        ]
        """
        roots = []

        # 内部ルート
        roots.append(self._make_root(self.internal_root, "data (内部)", "internal"))

        # 外部ルート
        for item in self._load_json():
            path = item.get("path", "")
            if os.path.isdir(path):
                name = os.path.basename(path)
                roots.append(self._make_root(path, name, "external"))

        return roots

    def _make_root(self, path: str, name: str, kind: str) -> dict:
        """ルートフォルダのツリーノードを生成する。"""
        children = []
        try:
            for entry in sorted(os.scandir(path), key=lambda e: e.name.lower()):
                if entry.is_dir():
                    children.append(self._make_child(entry.path))
        except PermissionError:
            pass

        return {
            "path": path,
            "name": name,
            "kind": kind,
            "direct_count": _count_direct(path),   # ルート直下のラスタ数
            "count": _count_tifs(path),             # 再帰合計
            "children": children,
        }

    def _make_child(self, path: str) -> dict:
        """サブフォルダのツリーノードを生成する（再帰的に孫も持つ）。"""
        children = []
        try:
            for entry in sorted(os.scandir(path), key=lambda e: e.name.lower()):
                if entry.is_dir():
                    children.append(self._make_child(entry.path))
        except PermissionError:
            pass

        return {
            "path": path,
            "name": os.path.basename(path),
            "direct_count": _count_direct(path),
            "count": _count_tifs(path),
            "children": children,
        }

    # ── 外部フォルダ追加・削除 ────────────────────────────────────────────────

    def add_external_source(self, folder_path: str) -> bool:
        """外部フォルダを追加。重複は無視。"""
        folder_path = os.path.normpath(folder_path)
        raw = self._load_json()
        paths = [r["path"] for r in raw]
        if folder_path in paths:
            return False
        raw.append({"path": folder_path, "kind": "external"})
        self._save_json(raw)
        return True

    def remove_external_source(self, folder_path: str):
        """外部フォルダを削除。"""
        folder_path = os.path.normpath(folder_path)
        raw = self._load_json()
        raw = [r for r in raw if os.path.normpath(r["path"]) != folder_path]
        self._save_json(raw)

    def get_external_root_paths(self) -> list[str]:
        """登録済み外部フォルダのパス一覧を返す（削除ボタン用）。"""
        return [r["path"] for r in self._load_json() if os.path.isdir(r.get("path", ""))]

    # ── JSON I/O ────────────────────────────────────────────────────────────────

    def _load_json(self) -> list:
        if not os.path.exists(self.settings_path):
            return []
        try:
            with open(self.settings_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_json(self, data: list):
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ── ユーティリティ ────────────────────────────────────────────────────────────

RASTER_EXTS = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".img"}


def _count_direct(folder: str) -> int:
    """フォルダ直下（再帰なし）のラスタファイル数を返す。"""
    try:
        return sum(
            1 for f in os.scandir(folder)
            if f.is_file() and os.path.splitext(f.name)[1].lower() in RASTER_EXTS
        )
    except PermissionError:
        return 0


def _count_tifs(folder: str) -> int:
    """フォルダ以下を再帰的に走査してラスタファイルの総数を返す。"""
    total = 0
    for _dirpath, _dirnames, filenames in os.walk(folder):
        for fname in filenames:
            if os.path.splitext(fname)[1].lower() in RASTER_EXTS:
                total += 1
    return total
