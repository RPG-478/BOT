# Agent（Discord版）

正式なAgent実装は `cogs/agent.py` です。`main.py` が `cogs` 配下の拡張を読み込み、Discordの `/agent` スラッシュコマンドから実行します。

## 実行設定

```env
GROQ_API_KEY=あなたのGroq_APIキー
GITHUB_ACCESS_TOKEN=あなたのGitHubトークン
GROQ_PLANNER_MODEL=openai/gpt-oss-20b
GROQ_ENGINEER_MODEL=openai/gpt-oss-120b
GROQ_MODEL_FALLBACK=openai/gpt-oss-20b
GROQ_PLANNER_MAX_TOKENS=600
GROQ_ENGINEER_MAX_TOKENS=1600
GROQ_TOOL_RESULT_MAX_CHARS=6000
```

`/agent` の `max_turns` は1〜60を指定でき、省略時は60です。`normal` モードでは、コードを変更した場合に `patch_github_file` または `commit_file_to_github` が実行され、GitHubへのコミット結果を確認します。`dry_run` と `review` では変更・コミットを行いません。

Discord版では、モデルへの履歴とツール結果を自動的に圧縮し、TPM制限に近づかないよう出力トークン数も制限しています。モデルが `print_tree`、`read_github_file` の行範囲、`search_code_in_repo` の `path` を使用しても処理できます。

## 起動

```bash
python3 main.py
```

認証情報はソースコードへ直接書かず、環境変数または `.env` で管理してください。過去にリポジトリへトークンを記録していた場合、そのトークンは無効化して新しいものへ交換してください。
