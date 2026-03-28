# python_tracker

`uv` で管理する Python 開発環境です。  
このリポジトリでは Python 本体、仮想環境、依存ロックを `uv` でまとめて管理します。

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

仮想環境の Python 実行:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run python
```

パッケージ追加:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv add requests
```

開発用パッケージ追加:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv add --dev ipython
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
├── uv.lock
├── .python-version
├── src/
│   └── python_tracker/
└── tests/
```

## 補足

- `src/` 配下がアプリケーションコードです
- `tests/` 配下に `pytest` のテストを置きます
- `.venv/`、`.uv-cache/`、`.uv-python/` は生成物なので Git には含めません
