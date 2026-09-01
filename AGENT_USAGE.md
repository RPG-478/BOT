# Agent CLI

`Agent.py` は、リポジトリを調査するための安全なターミナルエージェントです。LLMのキーがなくても、ファイル一覧・読み込み・検索・構文確認を利用できます。

## 基本操作

```bash
python3 Agent.py --help
python3 Agent.py --list
python3 Agent.py --read cogs/agent.py
python3 Agent.py --search GROQ_API_KEY
python3 Agent.py --check
python3 Agent.py "このリポジトリの構成と注意点を要約して"
python3 Agent.py --interactive
```

`GROQ_API_KEY` を設定すると、依頼内容に応じてエージェントが読み取り・検索・検査ツールを選択します。Discord版のモデルは次の環境変数で変更できます。既定値は、計画用が `openai/gpt-oss-20b`、実行用が `openai/gpt-oss-120b`、失敗時のフォールバックが `openai/gpt-oss-20b` です。

```bash
export GROQ_API_KEY="your-key"
export GROQ_PLANNER_MODEL="openai/gpt-oss-20b"
export GROQ_ENGINEER_MODEL="openai/gpt-oss-120b"
export GROQ_MODEL_FALLBACK="openai/gpt-oss-20b"
# Discord版のTPM超過を抑える設定（必要時のみ調整）
export GROQ_PLANNER_MAX_TOKENS="600"
export GROQ_ENGINEER_MAX_TOKENS="1600"
export GROQ_TOOL_RESULT_MAX_CHARS="6000"
python3 Agent.py "Agent.pyの改善点を調べて"
```

Discord版では、モデルへの履歴とツール結果を自動的に圧縮し、TPM制限に近づかないよう出力トークン数も制限しています。413または `rate_limit_exceeded` が発生した場合は、小型モデルへ1回だけフォールバックします。

現在のCLIは意図しない変更やコミットを行いません。作業ディレクトリ外のパス、任意のシェルコマンド、外部へのファイル送信は扱わない設計です。ファイル編集やGitHubへのコミットを追加する場合は、必ず差分確認と明示的な承認を挟む拡張にしてください。

## Discord版との関係

`cogs/agent.py` は既存のDiscordスラッシュコマンドです。GitHub操作には `GITHUB_ACCESS_TOKEN`、LLM操作には `GROQ_API_KEY` が必要です。認証情報はソースコードに書かず、環境変数または `.env` で管理してください。過去にリポジトリへトークンを記録していた場合、そのトークンは無効化して新しいものへ交換してください。
