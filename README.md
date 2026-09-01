# Raster Loader - QGISプラグイン v2.0

ポリゴン範囲に交差するGeoTIFFタイルを**複数フォルダから一括検索**してQGISレイヤーに追加します。

---

## インストール

1. `raster_loader/` フォルダごとQGISプラグインフォルダにコピー

   | OS | パス |
   |---|---|
   | Windows | `C:\Users\<ユーザー名>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\` |
   | macOS/Linux | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/` |

2. QGIS → **プラグインの管理とインストール** → 「Raster Loader」を有効化

---

## フォルダ構成

```
raster_loader/
├── data/                  ← 内部フォルダ（サブフォルダごとにデータソース）
│   ├── DEM/               ← data/ 直下のサブフォルダが自動でリストに表示
│   │   ├── tile_001.tif
│   │   └── tile_002.tif
│   ├── 航空写真2023/
│   │   └── photo_001.tif
│   └── 地質図/
│       └── geo_001.tif
├── sources.json           ← 外部フォルダの登録情報（自動生成）
├── __init__.py
└── ...
```

### データの配置ルール
- `data/` 直下にサブフォルダを作り、その中にGeoTIFFを入れる
- サブフォルダ名がそのままデータソース名として表示される
- GeoTIFFを `data/` 直下に直置きした場合は「data」という名前で表示
- 外部フォルダはダイアログから追加・削除可能（`sources.json`に保存）

---

## 使い方

1. QGISにポリゴンレイヤーを読み込む
2. ツールバーの **Raster Loader** ボタンをクリック
3. ダイアログでデータソースにチェックを入れる（複数可）
4. ポリゴンレイヤーを選択
5. **「▶ 選択したソースを一括読み込み」** をクリック
6. 各ソースのうち範囲が交差するタイルがVRTとしてQGISレイヤーに追加される

---

## 仕組み

```
ポリゴンBBox → WGS84変換
       ↓
各ソースフォルダ内の全GeoTIFFと交差判定（GDAL）
       ↓
交差タイルを gdal.BuildVRT で結合
       ↓
QGISラスタレイヤーとして追加（ソースごとに1レイヤー）
```

---

## 注意事項

- GeoTIFFのCRSは任意（WGS84以外も自動変換）
- VRTは一時フォルダに保存（QGIS終了で消えるがGeoTIFFは保持）
- 外部フォルダの登録情報は `sources.json` に永続保存
