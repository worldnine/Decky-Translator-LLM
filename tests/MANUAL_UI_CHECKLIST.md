# UI手動確認チェックリスト

Steam Deckゲームモードで以下を確認する。

## TabTranslation（翻訳設定）

- [ ] 表示される入力項目: Gemini API Key, Gemini Model のみ
- [ ] 「Advanced Settings」トグルで Gemini Base URL が表示される
- [ ] API Key フィールドがパスワードマスクされている
- [ ] 旧provider選択UI（OCR Provider, Translation Provider）が表示されない

## TabPrompts（プロンプト設定）

- [ ] 「共通 Gemini 指示」テキストエリアが表示される
- [ ] ゲーム起動中に「ゲーム別 Gemini 指示」テキストエリアが表示される
- [ ] ファイルパスが表示されている

## 設定マイグレーション

- [ ] 旧設定（llm_*, text_llm_*, vision_llm_*）から gemini_* に正しく移行される
- [ ] gemini_model 未設定時にバリデーションメッセージが出る
- [ ] gemini_api_key 未設定時にバリデーションメッセージが出る

## 翻訳動作

- [ ] vision_translate でテキスト検出+翻訳が正常に動作する
- [ ] テキストなし画像で空配列が正常結果として扱われる
- [ ] 共通promptとゲーム別promptがGemini翻訳に反映される

## クリーンアップ後の確認

- [ ] 旧RPC（recognize_text, translate_text）呼び出し時にdeprecated警告がログに出る
- [ ] get_provider_status が Gemini専用の情報（model, base_url, api_key_set）を返す
- [ ] 初期化ログに旧provider名（RapidOCR, FreeGoogle等）が表示されない
