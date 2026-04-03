# UI手動確認チェックリスト

Steam Deckゲームモードで以下を確認する。

## TabTranslation（翻訳設定）

- [ ] provider選択UI（OCR Provider, Translation Provider）が表示されない
- [ ] 表示される入力項目: Gemini API Key, Gemini Model のみ
- [ ] 「Advanced Settings」トグルで Gemini Base URL が表示される
- [ ] API Key フィールドがパスワードマスクされている

## TabPrompts（プロンプト設定）

- [ ] 「共通 Gemini 指示」テキストエリアが表示される
- [ ] ゲーム起動中に「ゲーム別 Gemini 指示」テキストエリアが表示される
- [ ] ファイルパスが表示されている

## 設定マイグレーション

- [ ] 旧設定（llm_*, text_llm_*, vision_llm_*）から gemini_* に正しく移行される
- [ ] gemini_model 未設定時にバリデーションメッセージが出る
- [ ] gemini_api_key 未設定時にバリデーションメッセージが出る
- [ ] gemini_base_url 不正時にバリデーションメッセージが出る

## 翻訳動作

- [ ] テキストなし画像で空配列が正常結果として扱われる
- [ ] 共通promptとゲーム別promptがGemini翻訳に反映される
