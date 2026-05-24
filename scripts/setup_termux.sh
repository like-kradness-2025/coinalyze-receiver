#!/data/data/com.termux/files/usr/bin/bash
#
# setup_termux.sh — coinalyze-receiver Termux セットアップスクリプト
#
# pandas/numpy をソースビルドせず、プリコンパイル済みパッケージで
# インストールするための前処理を行います。
#
# 使い方:
#   bash scripts/setup_termux.sh
#
set -euo pipefail

echo "=== coinalyze-receiver Termux セットアップ ==="
echo ""

# ---- 1. TUR リポジトリ（プリコンパイル済み Python パッケージ） ----
if ! pkg list-installed 2>/dev/null | grep -q '^tur-repo'; then
    echo "[1/4] TUR リポジトリを追加中..."
    pkg install -y tur-repo
else
    echo "[1/4] TUR リポジトリ: 済"
fi

# ---- 2. パッケージリスト更新 ----
echo "[2/4] パッケージリスト更新中..."
pkg update -y

# ---- 3. pandas + numpy（プリコンパイル済み、ソースビルド不要） ----
echo "[3/4] pandas/numpy をプリコンパイル済みパッケージでインストール中..."
pkg install -y python-numpy python-pandas

echo ""
echo "[3/4] 完了: numpy + pandas はプリコンパイル済みパッケージとして導入済み"
echo "       pip install 時に再ビルドされることはありません"

# ---- 4. coinalyze-receiver 本体を pip install ----
echo ""
echo "[4/4] coinalyze-receiver をインストール中..."
cd "$(dirname "$0")/.."
if ! pip install -e . --no-build-isolation 2>&1; then
    echo "⚠️  pip install に失敗しました。上記のエラーを確認してください。" >&2
    exit 1
fi

echo ""
echo "=== セットアップ完了 ==="
echo ""
echo "次のコマンドで動作確認:"
echo "  coinalyze-receiver --list-markets"
echo ""
echo ".env に COINALYZE_API_KEY を設定してください:"
echo "  cp .env.example .env"
echo "  # 編集して API キーを追加"
