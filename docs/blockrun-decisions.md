# BlockRun Decisions API

この機能は通常の有料BlockRun LLMではなく、無料のBlockRun Decisions APIを使います。Decisions APIは`gpt-6-luna`へTyped Judgmentを送り、ツールを使うか、どの許可ツールを使うかを判定します。判定後のツール実行はBOT側で行います。

## `.env`

BlockRunのAPIキーを取得して、次を追記します。

```dotenv
BLOCKRUN_API_KEY=ここにBlockRunのAPIキー
BLOCKRUN_MENTION_ENABLED=true
```

`BLOCKRUN_MENTION_ENABLED=true`にすると、既存のGeminiメンション応答は停止し、BlockRunメンションCogが担当します。APIキーがない状態では有料決済やウォレット署名は発生しません。

## インストールと起動

```bash
cd ~/BOT
python3 -m pip install -r requirements.txt
python3 main.py
```

## ユーザー別設定

Discord上で次を実行します。

```text
!blockrun on
!blockrun tools web_search
!blockrun prompt 最新情報を優先し、回答には参照URLを含める
```

その後、次のようにメンションします。

```text
@AGO BOT OpenAIの最新モデルについて調べて
```

Decisions APIが外部ツール不要と判定した場合はそのまま既存のLogfare AIで回答し、`web_search`が必要と判定した場合はWeb検索結果を取得してから既存のLogfare AIで回答します。

現在許可できるツールは安全な公開Web検索のみです。将来ツールを追加する場合は、ツール定義・実行関数・`ALLOWED_TOOLS`を同時に追加してください。

## 注意

Decisions APIは無料ですが、BlockRun APIキーごとの時間単位制限があります。通常の`openai/gpt-6-luna`チャットAPI（x402）は別サービスで有料のため、この機能では使用していません。
