# python_tracker

`uv` で管理する Python 開発環境です。  
このリポジトリでは、動画から飛行機を検出・追跡し、Unity 連携用 JSON とデバッグ動画を生成します。推論結果は動画ごとにキャッシュされ、スキーマ変更時の再出力や時間範囲切り出しを高速に行えます。

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
  --device cpu
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
  --device cpu
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
- `.plane_tracker_cache/` に動画 SHA256 ベースの推論キャッシュを保存します
- `.venv/`、`.uv-cache/`、`.uv-python/` は生成物なので Git には含めません
