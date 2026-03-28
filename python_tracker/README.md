# python_tracker

`uv` で管理する Python 開発環境です。  
このリポジトリでは、動画から飛行機を検出・追跡し、Unity 連携用 JSON とデバッグ動画を生成します。推論結果は動画ごとにキャッシュされ、スキーマ変更時の再出力や時間範囲切り出しを高速に行えます。
また、`--inference-stride` により推論を間引き、間のフレームは bbox を線形補間して負荷を下げられます。

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

FR24 連携つきで実行:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run python plane_tracker.py \
  --input airplane-001-7min.mp4 \
  --output-json output/plane_tracks.fr24.json \
  --output-video output/plane_debug.fr24.mp4 \
  --fr24-recording-start "2026-03-28 12:53:05" \
  --fr24-timezone Asia/Tokyo \
  --camera-lat 35.55362240541361 \
  --camera-lon 139.78716594923188 \
  --camera-bearing 90 \
  --camera-horizontal-fov 60 \
  --fr24-search-radius-km 25 \
  --inference-stride 3
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
- `.plane_tracker_cache/` に動画 SHA256 ベースの推論キャッシュを保存します
- FR24 の historical API 応答も `.plane_tracker_cache/fr24/` に保存され、同じ timestamp+bounds の再実行では API quota を再消費しません
- FR24 の track 調査結果は `.plane_tracker_cache/fr24_tracks/` に保存され、同じ clip / `track_id` / matching 条件の再実行では API を再問い合わせしません
- キャッシュキーには動画 SHA256、モデル、tracker、conf、`inference_stride` が含まれます
- `.venv/`、`.uv-cache/`、`.uv-python/` は生成物なので Git には含めません
- FR24 連携では起動時に `.env` を読み込み、`FLIGHTRADAR24_API_KEY` または `FR24_API_TOKEN` を環境変数として利用します
- FR24 連携は各 `track_id` の存続区間の中盤だけを調べます。クリップ先頭から末尾まで存在する常在 `track_id` は調査対象から除外します
- `429 Too Many Requests` を受けた場合は `Retry-After` を優先して待機し、未指定時は指数バックオフで再試行します
- FR24 連携はカメラの水平 FOV を使って方位と bbox の横位置を照合する近似マッチです。厳密な三次元再投影ではありません
