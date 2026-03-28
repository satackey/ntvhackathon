# python_tracker

`uv` で管理する Python 開発環境です。  
このリポジトリでは、動画から飛行機を検出・追跡し、Unity 連携用 JSON とデバッグ動画を生成します。推論結果は動画ごとにキャッシュされ、スキーマ変更時の再出力や時間範囲切り出しを高速に行えます。
また、`--inference-stride` により推論を間引き、間のフレームは bbox を線形補間して負荷を下げられます。
加えて、`streamlit + plotly + opencv` ベースの手動キャリブレーション GUI で、tracking JSON と OpenSky キャッシュを重ねてカメラ姿勢・位置・時刻オフセットを調整できます。

## 前提

- `uv` がインストールされていること
- `PATH` に `uv` が通っていること

`uv` をまだ入れていない場合:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

## 初回セットアップ

このプロジェクトでは、キャッシュと Python 本体の配置先をリポジトリ配下に寄せています。

```bash
export PATH="$HOME/.local/bin:$PATH"
export UV_CACHE_DIR=.uv-cache
export UV_PYTHON_INSTALL_DIR=.uv-python

uv sync --dev
```

実行されること:

- `.python-version` に合わせて Python `3.14.3` を利用
- 必要なら Python 本体を `.uv-python/` に配置
- 仮想環境を `.venv/` に作成
- 開発依存を含めて `uv.lock` に従いインストール

## 基本コマンド

依存同期:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv sync --dev
```

Lint:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run ruff check .
```

テスト:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run pytest
```

トラッキング実行:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run python plane_tracker.py \
  --input input.mp4 \
  --output-json output/plane_tracks.json \
  --output-video output/plane_debug.mp4 \
  --conf 0.25 \
  --device cpu \
  --inference-stride 1
```

時間範囲を切り出して再出力:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run python plane_tracker.py \
  --input input.mp4 \
  --output-json output/plane_tracks.clip.json \
  --output-video output/plane_debug.clip.mp4 \
  --start-time 60 \
  --end-time 90 \
  --conf 0.25 \
  --device cpu \
  --inference-stride 3
```

キャッシュを無視して再計算:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run python plane_tracker.py \
  --input input.mp4 \
  --output-json output/plane_tracks.json \
  --output-video output/plane_debug.mp4 \
  --force-recompute
```

仮想環境の Python 実行:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run python
```

Cesium ベースの OpenSky キャリブレーション Web アプリ:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run python \
  cesium_opensky_calibration.py \
  --video airplane-001-7min.mp4 \
  --tracking-json output/airplane-001-7min.json \
  --opensky-cache output/opensky_cache.json \
  --opensky-credentials-json '/Users/.../credentials.json' \
  --camera-config output/camera_config.json \
  --manual-matches output/manual_matches.json \
  --host 127.0.0.1 \
  --port 8765
```

補足:

- `camera_config.json` がなければ初期位置 `35.55362508260334, 139.7871835937992` を使います
- 既定の初期姿勢は東向き (`azimuth_deg=90`) です
- ブラウザ側では Cesium 地球ビュー上でカメラ位置マーカーを D&D でき、`Alt + drag` で heading / tilt、`Shift + Alt + drag` で roll / FOV を調整できます
- OpenSky はローカル `opensky_cache.json` を優先し、`Fetch OpenSky for current view` を押した時だけ不足区間を追記取得します
- OpenSky 認証は `--opensky-credentials-json`、`--opensky-client-id` + `--opensky-client-secret`、または `--opensky-access-token` を CLI から渡します
- Web UI 内で current OpenSky states、selected aircraft details、track path、cache overview を確認できます
- 旧 `streamlit_opensky_calibration.py` は参考実装として残しています

依存更新:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv lock --upgrade
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv sync --dev
```

## ディレクトリ構成

```text
.
├── pyproject.toml
├── plane_tracker.py
├── uv.lock
├── .python-version
├── src/
│   └── python_tracker/
├── tests/
└── unity/
```

## 補足

- `src/` 配下がアプリケーションコードです
- `tests/` 配下に `pytest` のテストを置きます
- `unity/` 配下に JSON 取り込み用 C# クラスを置いています
- `schemas/plane-tracking.schema.json` に出力 JSON の JSON Schema を置いています
- `schemas/camera_config.schema.json`、`schemas/manual_matches.schema.json`、`schemas/with_flight_info.schema.json` に追加出力の Schema を置いています
- `.plane_tracker_cache/` に動画 SHA256 ベースの推論キャッシュを保存します
- `streamlit_opensky_calibration.py` が Streamlit GUI のエントリポイントです
- キャッシュキーには動画 SHA256、モデル、tracker、conf、`inference_stride` が含まれます
- `.venv/`、`.uv-cache/`、`.uv-python/` は生成物なので Git には含めません
