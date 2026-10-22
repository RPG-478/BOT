# `!ai` のプロバイダー切替

AGO BOT は従来の Logfare モデルに加え、DSH Our Free Model の Routing で作った
`combo:<名前>` をチャットモデルとして選べます。各プロバイダーの API キー、
モデルの順番、`fallback` / `round-robin` は DSH 側の Aggregate / Routing で設定します。
AGO BOT に各社のキーを渡す必要はありません。

## 設定

1. AGO BOT から到達できる DSH Our Free Model の Gateway を起動し、Gateway の
   「Connect a client」に表示される Base URL と API キーを確認します。
   同じホストならローカル転送ポート、別ホストなら DSH の明示的な LAN relay と
   **ネットワーク用キー**を使用します。
2. DSH の Aggregate で利用するプロバイダーを登録し、Routing で名前付きの
   `fallback` または `round-robin` チェーンを作ります。料金や無料枠は各社で異なるため、
   チェーンに入れる前にそれぞれの条件を確認してください。
3. AGO BOT の環境変数を設定します。

```dotenv
DSH_GATEWAY_BASE_URL=http://127.0.0.1:8326/v1
DSH_GATEWAY_API_KEY=<Gateway のキー>
DSH_GATEWAY_MODEL=combo:ago-free
```

`DSH_GATEWAY_MODEL` は任意です。設定すると、ユーザー個別の選択がない場合に
そのチェーンを `!ai` の既定値として使います。未設定なら従来どおり Logfare が既定です。
`DSH_GATEWAY_BASE_URL` には `/v1` の有無どちらも指定できます。
ポート番号は DSH 画面で実際に表示された値を使用してください。

設定画面の「デフォルトAIを設定」には、DSH の `/v1/models` が公開する
`combo:` モデルが追加されます。Logfare の画像生成は従来どおりです。
DSH チェーン内のプロバイダー切替は DSH 側が行い、AGO BOT には最終回答が返ります。
チェーン内で回答本文が出た後の障害は別プロバイダーへの切替対象になりません。
