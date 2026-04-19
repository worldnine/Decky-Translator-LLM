#!/bin/bash
# Gemini モデル切り替えスクリプト
# 使い方: ./scripts/set-model.sh <model-name> [DECK_IP]
#
# 例:
#   ./scripts/set-model.sh gemini-2.5-flash-lite
#   ./scripts/set-model.sh gemini-2.5-flash
#   ./scripts/set-model.sh gemini-3.1-flash-lite-preview 192.168.11.38
#
# 事前準備:
#   - ssh-copy-id deck@<DECK_IP> 済みであること
#   - 環境変数 DECK_PASS で sudo パスワードを渡すか、対話入力する

set -euo pipefail

MODEL="${1:-}"
DECK_IP="${2:-192.168.11.38}"
DECK_USER="deck"
DECK="${DECK_USER}@${DECK_IP}"
PLUGIN_DIR_NAME="decky-translator-llm"
SETTINGS_FILE_NAME="decky-translator-settings.json"
SETTINGS_PATH="/home/deck/homebrew/settings/${PLUGIN_DIR_NAME}/${SETTINGS_FILE_NAME}"

if [ -z "${MODEL}" ]; then
    echo "使い方: $0 <model-name> [DECK_IP]"
    echo ""
    echo "例:"
    echo "  $0 gemini-2.5-flash-lite"
    echo "  $0 gemini-2.5-flash"
    echo "  $0 gemini-3.1-flash-lite-preview"
    exit 1
fi

# sudo パスワード取得（plugin_loader 再起動に必要）
if [ -z "${DECK_PASS:-}" ]; then
    echo -n "Steam Deck のsudoパスワード: "
    read -rs DECK_PASS
    echo ""
fi

echo "=== モデル切り替え: ${MODEL} (${DECK_IP}) ==="

# 1. SSH 接続テスト
echo "[1/3] Steam Deckに接続中..."
if ! ssh -o ConnectTimeout=5 "${DECK}" "echo ok" > /dev/null 2>&1; then
    echo "エラー: Steam Deck (${DECK_IP}) に接続できません"
    exit 1
fi

# 2. 設定ファイルの gemini_model を書き換え（Python で JSON を安全に編集）
echo "[2/3] gemini_model を書き換え中..."
ssh "${DECK}" "MODEL='${MODEL}' SETTINGS_PATH='${SETTINGS_PATH}' python3 -c '
import json, os, sys
p = os.environ[\"SETTINGS_PATH\"]
m = os.environ[\"MODEL\"]
if not os.path.exists(p):
    sys.exit(f\"設定ファイルが存在しません: {p}\")
with open(p) as f:
    d = json.load(f)
old = d.get(\"gemini_model\", \"(未設定)\")
d[\"gemini_model\"] = m
with open(p, \"w\") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
print(f\"  {old} -> {m}\")
'" || { echo "エラー: 設定書き換え失敗"; exit 1; }

# 3. plugin_loader 再起動（メモリ上の設定を反映させるため）
echo "[3/3] plugin_loader を再起動中..."
ssh "${DECK}" "echo '${DECK_PASS}' | sudo -S systemctl restart plugin_loader 2>&1 | grep -v '\[sudo\] password' || true" \
|| { echo "エラー: plugin_loader 再起動失敗"; exit 1; }

echo ""
echo "=== モデル切り替え完了: ${MODEL} ==="
echo "Steam Deck の Decky を開いて動作確認してください"
