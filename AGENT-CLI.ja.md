# Decky Agent CLI

外部 AI やスクリプトから Steam Deck の画面を読み取るための CLI。

## セットアップ

Decky Translator プラグインに同梱。追加インストール不要。

```bash
# Steam Deck に SSH で接続
ssh deck@<DECK_IP>

# プラグインディレクトリに移動
cd ~/homebrew/plugins/decky-translator-llm

# 動作確認
python3 decky-agent-cli capabilities --json
```

## セキュリティ

Agent CLI はデフォルトで **無効** です。\
使用するには、Decky Translator の設定画面で **Agent CLI** トグルを ON にしてください。\
無効のままでは CLI の操作、通知、RPC 呼び出しがすべて拒否されます。

## サブコマンド

### `capture` — スクリーンショット取得

```bash
python3 decky-agent-cli capture \
  --purpose "攻略支援: 画面確認" \
  --json
```

| オプション        | 必須  | 説明                                                            |
| ------------ | --- | ------------------------------------------------------------- |
| `--purpose`  | Yes | 取得目的（通知に表示）                                                   |
| `--app-name` | No  | アプリ名（ファイル名に使用）                                                |
| `--notify`   | No  | 通知モード: `dot` / `thumbnail` / `message` (default: `thumbnail`) |
| `--json`     | No  | JSON 形式で出力                                                    |

返却例:

```json
{
  "ok": true,
  "action": "capture",
  "purpose": "攻略支援: 画面確認",
  "captured_at": "2026-04-04T21:15:10+09:00",
  "image": {
    "path": "/tmp/decky-translator/Game_2026-04-04_21-15-10_abc12345.png",
    "base64": "data:image/png;base64,..."
  }
}
```

### `translate` — 画面翻訳

```bash
python3 decky-agent-cli translate \
  --purpose "攻略支援: UI翻訳" \
  --target ja \
  --json
```

| オプション       | 必須  | 説明                           |
| ----------- | --- | ---------------------------- |
| `--purpose` | Yes | 取得目的                         |
| `--target`  | No  | 翻訳先言語コード (default: 設定値)      |
| `--input`   | No  | 入力言語コード (default: auto)      |
| `--notify`  | No  | 通知モード (default: `thumbnail`) |

### `describe` — 画面説明（攻略支援）

```bash
python3 decky-agent-cli describe \
  --purpose "攻略支援: 会話確認" \
  --prompt "次の目的を教えて" \
  --json
```

| オプション       | 必須  | 説明                           |
| ----------- | --- | ---------------------------- |
| `--purpose` | Yes | 取得目的                         |
| `--prompt`  | No  | 追加の指示プロンプト                   |
| `--notify`  | No  | 通知モード (default: `thumbnail`) |

返却例:

```json
{
  "ok": true,
  "action": "describe",
  "description": {
    "summary": "洋館の廊下。中央にシャンデリア。",
    "objectives": ["北東の塔へ向かう"],
    "ui": ["HP 320/450"],
    "notable_text": ["open only in the event of my death"]
  }
}
```

### `game` — ゲーム情報

```bash
python3 decky-agent-cli game --json
```

### `prompt` — プロンプトの読み書き

```bash
# 共通プロンプト取得（テキストそのまま出力）
python3 decky-agent-cli prompt get

# 共通プロンプト取得（JSON）
python3 decky-agent-cli prompt get --json

# 共通プロンプト設定
python3 decky-agent-cli prompt set --content "近くのテキスト行をグループ化..."

# stdin から設定（長いプロンプト向き）
cat my-prompt.txt | python3 decky-agent-cli prompt set --stdin

# ゲーム別プロンプト取得
python3 decky-agent-cli prompt get --app-id 12345

# ゲーム別プロンプト設定
python3 decky-agent-cli prompt set --app-id 12345 --stdin < game-prompt.txt
```

| オプション         | 必須  | 説明                       |
| ------------- | --- | ------------------------ |
| `get` / `set` | Yes | 実行するアクション                |
| `--app-id`    | No  | ゲームの App ID（省略時は共通プロンプト） |
| `--content`   | No  | プロンプト内容（`set` 時）         |
| `--stdin`     | No  | stdin から内容を読む（`set` 時）   |

### `history` — 翻訳履歴

```bash
# 直近の翻訳履歴
python3 decky-agent-cli history recent --app-id 1569580 --json

# キーワード検索
python3 decky-agent-cli history search --app-id 1569580 --keyword "西棟" --json

# 履歴のあるゲーム一覧
python3 decky-agent-cli history games --json
```

| オプション       | 必須                    | 説明                        |
| ----------- | --------------------- | ------------------------- |
| `recent` / `search` / `games` | Yes | 実行するアクション |
| `--app-id`  | recent/search 時       | ゲームの App ID               |
| `--keyword` | search 時              | 検索キーワード                   |
| `--limit`   | No                    | 取得件数 (default: 20)        |

### `pin` — ピン履歴

```bash
# ピン保存（スクショ→保存→Gemini解析）
python3 decky-agent-cli pin capture --app-id 1569580 --app-name "Blue Prince" --json

# 直近のピン一覧
python3 decky-agent-cli pin recent --app-id 1569580 --json

# キーワード検索
python3 decky-agent-cli pin search --app-id 1569580 --keyword "WEST WING" --json

# 1件の詳細表示
python3 decky-agent-cli pin show --app-id 1569580 --pin-id <PIN_ID> --json

# 1件の削除（--confirm 必須）
python3 decky-agent-cli pin delete --app-id 1569580 --pin-id <PIN_ID> --confirm --json
```

| オプション       | 必須                   | 説明                      |
| ----------- | -------------------- | ----------------------- |
| `capture` / `recent` / `search` / `show` / `delete` | Yes | 実行するアクション |
| `--app-id`  | Yes                  | ゲームの App ID             |
| `--app-name` | capture 時            | アプリ名                    |
| `--keyword` | search 時             | 検索キーワード                 |
| `--pin-id`  | show/delete 時        | ピン ID                   |
| `--confirm` | delete 時             | 削除確認                    |

### `logs` — ログ管理

```bash
# 翻訳・ピン両方の件数/サイズ表示
python3 decky-agent-cli logs status --app-id 1569580 --json

# 翻訳履歴を削除（--confirm 必須）
python3 decky-agent-cli logs clear-translation --app-id 1569580 --confirm --json

# ピン履歴を削除
python3 decky-agent-cli logs clear-pins --app-id 1569580 --confirm --json

# 両方削除
python3 decky-agent-cli logs clear-all --app-id 1569580 --confirm --json
```

| オプション       | 必須  | 説明                      |
| ----------- | --- | ----------------------- |
| `status` / `clear-translation` / `clear-pins` / `clear-all` | Yes | 実行するアクション |
| `--app-id`  | Yes | ゲームの App ID             |
| `--confirm` | clear 系 | 削除確認                    |

### `capabilities` — 利用可能コマンド一覧

```bash
python3 decky-agent-cli capabilities --json
```

## 通知モード

CLI 実行時に `--notify` で Steam Deck 画面上の通知表示を制御できます。

| モード         | 表示           | 用途               |
| ----------- | ------------ | ---------------- |
| `dot`       | 赤い丸のみ        | 最小限の存在通知         |
| `thumbnail` | スクショサムネイル    | 何が撮られたか確認（デフォルト） |
| `message`   | purpose テキスト | なぜ撮られたか確認        |

通知は Decky プラグインが起動している場合のみ表示されます。\
プラグイン未起動時は通知なしで CLI は正常動作します。

## SSH 経由の運用

```bash
# Tailscale 経由
ssh deck@steamdeck "cd ~/homebrew/plugins/decky-translator-llm && \
  python3 decky-agent-cli describe --purpose '攻略支援: 状況確認' --json"

# ローカルネットワーク経由
ssh deck@<DECK_IP> "cd ~/homebrew/plugins/decky-translator-llm && \
  python3 decky-agent-cli capture --purpose '画面確認' --json"
```

## エラー

失敗時も `--json` で構造化エラーを返します。

```json
{
  "ok": false,
  "action": "describe",
  "error": {
    "code": "capture_failed",
    "message": "スクリーンショット取得に失敗しました"
  }
}
```

| 終了コード | 意味       |
| ----- | -------- |
| 0     | 成功       |
| 1     | 実行時エラー   |
| 2     | 引数エラー    |
| 3     | 設定・通信エラー |

## データ操作について

Agent CLI はゲーム操作やシステム変更は行いませんが、プラグインの **保存データの生成・削除** を行います。

- `pin capture`: スクリーンショットとメタデータを永続保存
- `pin delete`: ピンレコードの論理削除
- `logs clear-*`: 翻訳履歴・ピン履歴の物理削除

削除系コマンドには `--confirm` フラグが必須です。