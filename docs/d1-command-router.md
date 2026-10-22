# ローカルD1によるBOT機能代理実行

これはAIチャット機能とは別の機能です。BlockRun APIやLogfareは使いません。`d1_test.py`と同じローカルD1サービス、既定では`http://127.0.0.1:8082/v1/systemone`へ`state`と`questions`を送り、D1の`choice`判定に従って既存パネルの機能アクションを実行します。

## `.env`

```dotenv
D1_COMMAND_ROUTER_ENABLED=true
D1_ENDPOINT=http://127.0.0.1:8082/v1/systemone
D1_COMMAND_TIMEOUT=30
D1_COMMAND_RETRIES=1
```

D1が停止している場合の自動起動は行いません。必要なら既存の所有者専用コマンドを使います。

```text
!d1ping
```

## ユーザー設定

初期状態は無効かつ許可機能なしです。個別のDiscordコマンドではなく、既存パネルの機能アクションを許可します。

```text
!d1tools status
!d1tools allow vc:join
!d1tools allow vc:status
!d1tools allow general:status
!d1tools prompt 依頼が明確な場合だけ選び、判断できなければnoneを返す
!d1tools on
```

VCジャンルの安全な機能をまとめて許可する場合は、`!d1tools allow vc`と指定できます。例えば「VCに入って」とメンションすると、D1は許可済みの`vc:join`を選び、既存のVC参加処理を実行します。

その後、BOTへのメンションで依頼します。

```text
@BOT ステータスを確認して
```

## 安全な失敗動作

D1のHTTPエラー、タイムアウト、JSON形式不正、`answers`や`choice`の欠落、許可リスト外の選択、実行対象が不明な場合は、機能を実行しません。Logfare、BlockRun、別AIへのフォールバックも行いません。

実行は既存のショートカット用機能ディスパッチャーを再利用します。したがって、VC参加、VC退出、VC状態、一般のステータスなど、すでにパネルから実行できる機能単位へ接続できます。引数入力や確認モーダルが必要な機能、送金・削除・権限操作、AI系機能は代理実行対象から除外しています。
