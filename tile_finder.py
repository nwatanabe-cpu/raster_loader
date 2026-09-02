# -*- coding: utf-8 -*-
"""
ラスタタイル検索・VRT生成ロジック
比較基準CRS: EPSG:6676（JGD2011 / Japan Plane Rectangular CS XIV）に統一
"""

import os
import glob
from osgeo import gdal, osr

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
    QgsMessageLog,
    Qgis,
)

LOG_TAG = "Raster Loader"

# 比較に使う基準CRS（ここを変えれば別EPSGにも対応）
COMPARE_EPSG = 6676


def log(msg, level=Qgis.Info):
    QgsMessageLog.logMessage(msg, LOG_TAG, level)


# ── BBox取得（EPSG:6676統一） ──────────────────────────────────────────────────

def _epsg6676_srs() -> osr.SpatialReference:
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(COMPARE_EPSG)
    # GDAL 3系はデフォルトで軸順がlatlon順になるため明示的にXY順に固定
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def layer_bbox_6676(layer) -> QgsRectangle:
    """
    QgsVectorLayerのBBoxをEPSG:6676に変換して返す。
    レイヤーがすでにEPSG:6676なら変換しない。
    """
    src_crs = layer.crs()
    dst_crs = QgsCoordinateReferenceSystem(f"EPSG:{COMPARE_EPSG}")
    if src_crs == dst_crs:
        return layer.extent()
    tr = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
    return tr.transformBoundingBox(layer.extent())


# ── タイル検索 ────────────────────────────────────────────────────────────────

# 対応ラスタ拡張子とそれに対応するワールドファイル拡張子のマップ
RASTER_EXTS = {
    ".tif":  [".tfw", ".tifw", ".wld"],
    ".tiff": [".tfw", ".tifw", ".wld"],
    ".jpg":  [".jgw", ".jpgw", ".wld"],
    ".jpeg": [".jgw", ".jpgw", ".wld"],
    ".png":  [".pgw", ".pngw", ".wld"],
    ".img":  [".wld"],
}


def _has_worldfile(raster_path: str) -> bool:
    """ラスタに対応するワールドファイルが存在するか確認する。"""
    base, ext = os.path.splitext(raster_path)
    ext_lower = ext.lower()
    for wext in RASTER_EXTS.get(ext_lower, []):
        if os.path.exists(base + wext) or os.path.exists(base + wext.upper()):
            return True
    return False


def collect_all_rasters(folder: str) -> list[str]:
    """
    folder以下をすべて再帰走査してラスタファイルのパス一覧を返す。
    - GeoTIFF: そのまま収集
    - JPG/PNG等: 対応するワールドファイルが存在するものだけ収集
    """
    result = []
    for dirpath, _dirnames, filenames in os.walk(folder):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in RASTER_EXTS:
                continue
            fpath = os.path.join(dirpath, fname)
            # GeoTIFFはワールドファイル不要（CRS埋め込み前提）
            if ext in (".tif", ".tiff"):
                result.append(fpath)
            else:
                # JPG等はワールドファイルがある場合のみ
                if _has_worldfile(fpath):
                    result.append(fpath)
    return result


def get_raster_bbox_6676(path: str) -> tuple | None:
    """
    ラスタ（GeoTIFF・ワールドファイル付きJPG等）のBBoxを
    EPSG:6676（X_min, Y_min, X_max, Y_max）で返す。失敗時None。
    """
    ds = gdal.Open(path)
    if ds is None:
        return None

    gt = ds.GetGeoTransform()
    # ジオトランスフォームが単位行列（地理情報なし）の場合はスキップ
    if gt == (0.0, 1.0, 0.0, 0.0, 0.0, 1.0):
        ds = None
        return None

    cols, rows = ds.RasterXSize, ds.RasterYSize
    x_min = gt[0]
    y_max = gt[3]
    x_max = gt[0] + cols * gt[1]
    y_min = gt[3] + rows * gt[5]

    src_srs = osr.SpatialReference()
    proj = ds.GetProjection()
    ds = None

    dst_srs = _epsg6676_srs()

    if proj:
        src_srs.ImportFromWkt(proj)
        src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    else:
        # ワールドファイル付きJPG等はCRS未定義のことが多い → EPSG:6676と仮定
        src_srs = dst_srs

    if src_srs.GetAuthorityCode(None) == str(COMPARE_EPSG):
        return (x_min, y_min, x_max, y_max)

    try:
        tr = osr.CoordinateTransformation(src_srs, dst_srs)
        corners_src = [
            (x_min, y_min), (x_min, y_max),
            (x_max, y_min), (x_max, y_max),
        ]
        xs, ys = [], []
        for cx, cy in corners_src:
            pt = tr.TransformPoint(cx, cy)
            xs.append(pt[0])
            ys.append(pt[1])
        return (min(xs), min(ys), max(xs), max(ys))
    except Exception as e:
        log(f"CRS変換失敗 ({os.path.basename(path)}): {e}", Qgis.Warning)
        return None


def find_intersecting_tiles(folder: str, poly_bbox: QgsRectangle) -> list[str]:
    """
    folder以下（サブフォルダ含む・何階層でも）のラスタのうち
    poly_bbox（EPSG:6676）と交差するものをすべて返す。
    対象: GeoTIFF + ワールドファイル付きJPG/PNG
    GDALエラーは個別ファイル単位で握りつぶし処理継続。
    """
    all_rasters = collect_all_rasters(folder)

    if not all_rasters:
        log(f"対応ラスタなし（サブフォルダ含む）: {folder}", Qgis.Warning)
        return []

    log(f"  総ラスタ数（サブフォルダ含む）: {len(all_rasters)} ファイル")

    px0 = poly_bbox.xMinimum()
    py0 = poly_bbox.yMinimum()
    px1 = poly_bbox.xMaximum()
    py1 = poly_bbox.yMaximum()

    log(f"  ポリゴンBBox (EPSG:{COMPARE_EPSG}): "
        f"X {px0:.1f}〜{px1:.1f} / Y {py0:.1f}〜{py1:.1f}")

    gdal.PushErrorHandler('CPLQuietErrorHandler')
    matched = []
    skip_count = 0
    try:
        for raster in all_rasters:
            gdal.ErrorReset()
            try:
                bbox = get_raster_bbox_6676(raster)
            except Exception:
                skip_count += 1
                continue

            if bbox is None:
                skip_count += 1
                continue

            tx0, ty0, tx1, ty1 = bbox
            rel = os.path.relpath(raster, folder)
            if tx1 > px0 and tx0 < px1 and ty1 > py0 and ty0 < py1:
                matched.append(raster)
                log(f"  ✓ ヒット: {rel}")
            else:
                log(f"  　範囲外: {rel} "
                    f"[X {tx0:.1f}〜{tx1:.1f} / Y {ty0:.1f}〜{ty1:.1f}]")
    finally:
        gdal.PopErrorHandler()

    if skip_count:
        log(f"  ⚠ {skip_count} ファイルをスキップ（地理情報なし・破損等）", Qgis.Warning)

    return matched


# ── VRT生成 ───────────────────────────────────────────────────────────────────

def build_vrt(tile_paths: list[str], output_vrt: str) -> bool:
    """複数タイルをVRTに結合する。"""
    if not tile_paths:
        return False
    options = gdal.BuildVRTOptions(resampleAlg='nearest')
    vrt_ds = gdal.BuildVRT(output_vrt, tile_paths, options=options)
    if vrt_ds is None:
        log("VRT生成失敗", Qgis.Critical)
        return False
    vrt_ds.FlushCache()
    vrt_ds = None
    log(f"VRT生成: {output_vrt}")
    return True
