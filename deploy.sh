#!/bin/bash
# Steam Deck 実機デプロイスクリプト
# 使い方: ./deploy.sh [DECK_IP]
#
# 事前準備（1回だけ）:
#   1. Steam Deck デスクトップモードで: passwd && sudo systemctl enable --now sshd
#   2. Mac側: ssh-copy-id deck@<DECK_IP>
#   3. 環境変数 DECK_PASS にSteam Deckのパスワードを設定（またはスクリプト実行時に入力）

DECK_IP="${1:-192.168.11.38}"
DECK_USER="deck"
DECK="${DECK_USER}@${DECK_IP}"
PLUGIN_NAME="decky-translator"

# sudoパスワード取得
if [ -z "${DECK_PASS}" ]; then
    echo -n "Steam Deck のsudoパスワード: "
    read -rs DECK_PASS
    echo ""
fi

echo "=== Steam Deck デプロイ (${DECK_IP}) ==="

# 1. フロントエンドビルド
echo "[1/3] フロントエンドビルド..."
pnpm run build 2>&1 | tail -1
if [ ! -f dist/index.js ]; then
    echo "エラー: ビルド失敗 (dist/index.js が生成されていません)"
    exit 1
fi
echo "  ビルド成功: dist/index.js"

# 2. SSH接続テスト
echo "[2/3] Steam Deckに接続中..."
if ! ssh -o ConnectTimeout=5 "${DECK}" "echo ok" > /dev/null 2>&1; then
    echo "エラー: Steam Deck (${DECK_IP}) に接続できません"
    echo "  - Deckの電源が入っているか確認"
    echo "  - IPアドレスが正しいか確認"
    echo "  - SSHが有効か確認: sudo systemctl enable --now sshd"
    exit 1
fi

# 3. プラグインファイルを転送 & インストール
echo "[3/3] プラグインを転送・インストール中..."

rsync -azp \
    --exclude='node_modules' \
    --exclude='.git' \
    --exclude='out' \
    --exclude='cli' \
    --exclude='__pycache__' \
    --exclude='.vscode/settings.json' \
    --exclude='mise.toml' \
    --exclude='*.log' \
    --exclude='.env' \
    -e "ssh" \
    ./ "${DECK}:/tmp/${PLUGIN_NAME}-staging/" || { echo "エラー: rsync失敗"; exit 1; }

# echo PASS | sudo -S 方式（公式テンプレートのtasks.jsonと同じ手法）
ssh "${DECK}" "\
    PLUGIN_NAME=${PLUGIN_NAME} && \
    PLUGIN_DIR=/home/deck/homebrew/plugins/\${PLUGIN_NAME} && \
    \
    if [ -d \${PLUGIN_DIR}/bin ]; then \
        echo '${DECK_PASS}' | sudo -S mv \${PLUGIN_DIR}/bin /tmp/\${PLUGIN_NAME}-bin-backup 2>/dev/null; \
    fi && \
    \
    echo '${DECK_PASS}' | sudo -S rm -rf \${PLUGIN_DIR} && \
    echo '${DECK_PASS}' | sudo -S mkdir -m 755 -p \${PLUGIN_DIR} && \
    echo '${DECK_PASS}' | sudo -S cp -r /tmp/\${PLUGIN_NAME}-staging/* \${PLUGIN_DIR}/ && \
    \
    if [ -d /tmp/\${PLUGIN_NAME}-bin-backup ]; then \
        echo '${DECK_PASS}' | sudo -S mv /tmp/\${PLUGIN_NAME}-bin-backup \${PLUGIN_DIR}/bin; \
    fi && \
    \
    echo '${DECK_PASS}' | sudo -S chown -R deck:deck \${PLUGIN_DIR} && \
    echo '${DECK_PASS}' | sudo -S chmod -R 755 \${PLUGIN_DIR} && \
    rm -rf /tmp/\${PLUGIN_NAME}-staging && \
    echo '${DECK_PASS}' | sudo -S systemctl restart plugin_loader && \
    echo 'デプロイ完了: '\${PLUGIN_DIR}" \
|| { echo "エラー: リモート実行失敗"; exit 1; }

echo ""
echo "=== デプロイ成功！ ==="
echo "Steam Deck のゲームモードで ... → Decky → Decky Translator を確認してください"
