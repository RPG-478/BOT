import os
import json
import ast
import io
import asyncio
import contextlib
import time
from typing import Optional, Literal
import discord
from discord import app_commands
from discord.ext import commands
from github import Github, GithubException
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GEMINI_API_KEY = "AQ.Ab8RN6LqsTEvK4h4ZW0u-Ni7qdxbytjUuXEJaZLDV3JG0Anygg"
GITHUB_ACCESS_TOKEN = "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"

github_client = Github(GITHUB_ACCESS_TOKEN)
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

ALLOWED_USER_ID = 1320705325686587408
DEFAULT_REPO_NAME = "owner/default-repo"

def is_authorized_user(interaction: discord.Interaction) -> bool:
    return interaction.user.id == ALLOWED_USER_ID

class TaskManager:
    def __init__(self):
        self.plans = {}
        self.active_tasks = {}

    def set_plan(self, channel_id: int, tasks: list[str]) -> str:
        self.plans[channel_id] = [{"id": i + 1, "task": task, "status": "未着手"} for i, task in enumerate(tasks)]
        return self.get_formatted_plan(channel_id)

    def update_status(self, channel_id: int, task_id: int, status: str) -> str:
        if channel_id in self.plans:
            for t in self.plans[channel_id]:
                if t["id"] == task_id:
                    t["status"] = status
                    break
        return self.get_formatted_plan(channel_id)

    def get_formatted_plan(self, channel_id: int) -> str:
        if channel_id not in self.plans or not self.plans[channel_id]:
            return "計画なし"
        formatted = "【現在のタスク計画】\n"
        for t in self.plans[channel_id]:
            symbol = "▶" if t["status"] == "進行中" else "✓" if t["status"] == "完了" else "×" if t["status"] == "失敗" else "•"
            formatted += f"{symbol} {t['id']}. [{t['status']}] {t['task']}\n"
        return formatted

task_mgr = TaskManager()

def list_repository_files(repo_name: str, path: str = "", branch: str = "main") -> str:
    try:
        repo = github_client.get_repo(repo_name)
        contents = repo.get_contents(path, ref=branch)
        files = [f"[{'DIR' if c.type == 'dir' else 'FILE'}] {c.path}" for c in contents]
        return "\n".join(files) if files else "指定されたパスは空です。"
    except Exception as e:
        return f"ファイル一覧取得失敗: {str(e)}"

def read_github_file(repo_name: str, file_path: str, branch: str = "main") -> str:
    try:
        repo = github_client.get_repo(repo_name)
        return repo.get_contents(file_path, ref=branch).decoded_content.decode("utf-8")
    except Exception as e:
        return f"ファイル読み込み失敗: {str(e)}"

def search_code_in_repo(repo_name: str, query: str) -> str:
    try:
        results = github_client.search_code(f"{query} repo:{repo_name}")
        matches = [f"ファイル: {f.path}" for f in results[:10]]
        return "\n".join(matches) if matches else "該当するコードは見つかりませんでした。"
    except Exception as e:
        return f"コード検索失敗: {str(e)}"

def get_github_issue(repo_name: str, issue_number: int) -> str:
    try:
        repo = github_client.get_repo(repo_name)
        issue = repo.get_issue(number=issue_number)
        return f"Issue #{issue.number}: {issue.title}\nStatus: {issue.state}\nBody:\n{issue.body}"
    except Exception as e:
        return f"Issue取得失敗: {str(e)}"

def check_python_syntax(code_string: str) -> str:
    try:
        ast.parse(code_string)
        return "構文チェック結果: エラーなし (Python Syntax OK)"
    except SyntaxError as e:
        return f"構文エラー検出: 行 {e.lineno}, 列 {e.offset}: {e.msg}\n該当コード箇所: {e.text}"

def patch_github_file(repo_name: str, file_path: str, target_code: str, replacement_code: str, commit_message: str, branch: str = "main") -> str:
    try:
        repo = github_client.get_repo(repo_name)
        existing_file = repo.get_contents(file_path, ref=branch)
        current_content = existing_file.decoded_content.decode("utf-8")

        if target_code in current_content:
            new_content = current_content.replace(target_code, replacement_code, 1)
        else:
            lines_current = current_content.splitlines()
            lines_target = target_code.strip().splitlines()
            
            matched_start = -1
            for i in range(len(lines_current) - len(lines_target) + 1):
                match = True
                for j in range(len(lines_target)):
                    if lines_current[i + j].strip() != lines_target[j].strip():
                        match = False
                        break
                if match:
                    matched_start = i
                    break
            
            if matched_start != -1:
                lines_replacement = replacement_code.splitlines()
                lines_current[matched_start:matched_start + len(lines_target)] = lines_replacement
                new_content = "\n".join(lines_current)
            else:
                return f"エラー: 置換対象コード(target_code)が '{file_path}' 内で見つかりません。"

        if file_path.endswith(".py"):
            syntax_result = check_python_syntax(new_content)
            if "構文エラー検出" in syntax_result:
                return f"パッチ適用失敗（構文エラー検知）:\n{syntax_result}\n修正案を再考してください。"

        repo.update_file(path=file_path, message=commit_message, content=new_content, sha=existing_file.sha, branch=branch)
        return f"ファイル '{file_path}' の指定部分を差分更新してコミットしました。"
    except Exception as e:
        return f"パッチ適用失敗: {str(e)}"

def commit_file_to_github(repo_name: str, file_path: str, content: str, commit_message: str, branch: str = "main") -> str:
    try:
        repo = github_client.get_repo(repo_name)
        if file_path.endswith(".py"):
            syntax_result = check_python_syntax(content)
            if "構文エラー検出" in syntax_result:
                return f"コミット中断（構文エラー）:\n{syntax_result}"

        try:
            existing_file = repo.get_contents(file_path, ref=branch)
            repo.update_file(path=file_path, message=commit_message, content=content, sha=existing_file.sha, branch=branch)
            return f"ファイル '{file_path}' を更新コミットしました。"
        except GithubException as e:
            if e.status == 404:
                repo.create_file(path=file_path, message=commit_message, content=content, branch=branch)
                return f"ファイル '{file_path}' を新規作成コミットしました。"
            else:
                raise e
    except Exception as e:
        return f"コミット失敗: {str(e)}"

def search_web(query: str) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return "検索結果が見つかりませんでした。"
        output = [f"タイトル: {r.get('title')}\nURL: {r.get('href')}\n概要: {r.get('body')}\n---" for r in results]
        return "\n".join(output)
    except Exception as e:
        return f"Web検索エラー: {str(e)}"

def fetch_web_page_text(url: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for script in soup(["script", "style"]):
            script.extract()
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        cleaned_text = "\n".join(lines)
        return cleaned_text[:3000] + ("\n...(以下省略)" if len(cleaned_text) > 3000 else "")
    except Exception as e:
        return f"Webページ取得エラー: {str(e)}"

def execute_python_code(code_string: str) -> str:
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    global_vars = {"__name__": "__main__"}
    try:
        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
            exec(code_string, global_vars)
        output = stdout_capture.getvalue()
        errors = stderr_capture.getvalue()
        result = ""
        if output:
            result += f"【標準出力】\n{output}\n"
        if errors:
            result += f"【標準エラー出力】\n{errors}\n"
        return result if result else "コード実行完了（出力なし）"
    except Exception as e:
        return f"実行時エラー (Runtime Error):\n{type(e).__name__}: {str(e)}"

def delegate_heavy_task_to_gemini(summary_of_executed_steps: str, instructions_for_gemini: str) -> str:
    return f"【Gemini引継ぎ要求】\n要約:\n{summary_of_executed_steps}\n指示:\n{instructions_for_gemini}"

GEMINI_TOOLS = [
    list_repository_files, read_github_file, search_code_in_repo, get_github_issue,
    commit_file_to_github, patch_github_file,
    search_web, fetch_web_page_text, check_python_syntax, execute_python_code
]

FUNCTION_MAP = {
    "list_repository_files": list_repository_files,
    "read_github_file": read_github_file,
    "search_code_in_repo": search_code_in_repo,
    "get_github_issue": get_github_issue,
    "commit_file_to_github": commit_file_to_github,
    "patch_github_file": patch_github_file,
    "search_web": search_web,
    "fetch_web_page_text": fetch_web_page_text,
    "check_python_syntax": check_python_syntax,
    "execute_python_code": execute_python_code,
    "delegate_heavy_task_to_gemini": delegate_heavy_task_to_gemini
}

GROQ_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "create_task_plan",
            "description": "タスクリストを作成して計画を立てます。",
            "parameters": {
                "type": "object",
                "properties": {"tasks": {"type": "array", "items": {"type": "string"}}},
                "required": ["tasks"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "DuckDuckGoでWeb検索を行います。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_heavy_task_to_gemini",
            "description": "コード修正や長時間推論が必要なタスクをGeminiに委任します。",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary_of_executed_steps": {"type": "string", "description": "調査結果や進行状態の要約"},
                    "instructions_for_gemini": {"type": "string", "description": "Geminiへの具体的な指示"}
                },
                "required": ["summary_of_executed_steps", "instructions_for_gemini"]
            }
        }
    }
]

SYSTEM_INSTRUCTION_GROQ = """
あなたは自律型フロントエージェント（Groq）です。
【行動指針】
1. 思考プロセスとして、何を行うべきかを明確に意識してください。
2. 最初に `create_task_plan` でタスクを細分化・計画立案してください。
3. 初期調査（Web検索等）を行ったら、その結果と「次に何をすべきか」の思考を含めて `delegate_heavy_task_to_gemini` でGeminiへ引き継いでください。
"""

SYSTEM_INSTRUCTION_GEMINI = """
あなたはManus級の思考・完遂能力を持つメインエンジニアエージェント（Gemini 3.5 Flash）です。

【思考と行動の自律サイクル (ReAct Framework)】
各ステップで必ず以下の思考プロセスを内部展開して行動してください：
- **Thought (思考)**: 現在の状況、ツールの実行結果、次に必要な検証や実装手順についての推論。
- **Action (行動)**: 目的達成のために最適と判断したツールの実行。
- **Observation (観察)**: ツール結果の確認と不具合時の自己修復思考。

【開発・制約ルール】
- GitHubを操作する関数を呼ぶ際は、特に指示がない限りプロンプトで指定された `repo_name` と `branch` を使用してください。
- 動作モード(mode)の遵守:
  - `dry_run`: ファイル変更・コミット関数(`patch_github_file`, `commit_file_to_github`)を一切呼び出さず、変更計画と修正コード案の提示にとどめてください。
  - `review`: コードの分析・検証のみを行い、改善点やコードレビュー結果を出力してください。
  - `normal`: 指示通りコード修正・パッチ適用を行ってください。
- 自動コミット(auto_commit)が False の場合も、GitHubへの書き込み関数は使用せず、コード変更案を直接テキスト出力してください。
"""

class AgentCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        genai.configure(api_key=GEMINI_API_KEY)
        self.gemini_model = genai.GenerativeModel(
            model_name="gemini-3.5-flash",
            tools=GEMINI_TOOLS,
            system_instruction=SYSTEM_INSTRUCTION_GEMINI
        )
        self.last_edit_time = {}

    async def safe_edit_embed(self, message, embed, min_interval=2.0):
        now = time.time()
        msg_id = message.id
        if msg_id in self.last_edit_time:
            elapsed = now - self.last_edit_time[msg_id]
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
        try:
            if embed.description and len(embed.description) > 3900:
                embed.description = embed.description[-3900:]
            await message.edit(embed=embed)
            self.last_edit_time[msg_id] = time.time()
        except Exception:
            pass

    @app_commands.command(name="agent_stop", description="実行中のエージェントタスクを停止します")
    @app_commands.check(is_authorized_user)
    async def agent_stop_command(self, interaction: discord.Interaction):
        channel_id = interaction.channel.id
        if task_mgr.active_tasks.get(channel_id, False):
            task_mgr.active_tasks[channel_id] = False
            await interaction.response.send_message("実行中のエージェントタスクに停止シグナルを送信しました。")
        else:
            await interaction.response.send_message("現在実行中のタスクはありません。", ephemeral=True)

    @app_commands.command(name="agent", description="エージェントに自律タスクを実行させます")
    @app_commands.describe(
        prompt="実行したいタスクの内容",
        repo_name="対象のGitHubリポジトリ (例: owner/repo)",
        branch="対象Gitブランチ (デフォルト: main)",
        mode="動作モード (normal: 通常実行, dry_run: 修正案のみ提示, review: コードレビューのみ)",
        auto_commit="ファイル編集後に自動コミットするか (デフォルト: True)",
        issue_number="関連するGitHub Issue番号",
        max_turns="Geminiの最大ループ試行回数 (1-30, デフォルト: 20)",
        verbose="詳細な思考ログ(Thought)を表示するか (デフォルト: True)"
    )
    @app_commands.check(is_authorized_user)
    async def agent_command(
        self,
        interaction: discord.Interaction,
        prompt: str,
        repo_name: Optional[str] = None,
        branch: str = "main",
        mode: Literal["normal", "dry_run", "review"] = "normal",
        auto_commit: bool = True,
        issue_number: Optional[int] = None,
        max_turns: app_commands.Range[int, 1, 30] = 20,
        verbose: bool = True
    ):
        await interaction.response.defer()
        
        channel_id = interaction.channel.id
        task_mgr.active_tasks[channel_id] = True

        target_repo = repo_name or DEFAULT_REPO_NAME
        effective_auto_commit = auto_commit if mode == "normal" else False

        context_header = (
            f"【タスク設定情報】\n"
            f"- 対象リポジトリ: {target_repo}\n"
            f"- 対象ブランチ: {branch}\n"
            f"- 動作モード: {mode}\n"
            f"- 自動コミット許可: {effective_auto_commit}\n"
        )
        if issue_number:
            context_header += f"- 関連Issue: #{issue_number}\n"

        full_prompt = f"{context_header}\n【指示内容】\n{prompt}"

        status_embed = discord.Embed(
            title="Agent Active",
            description=(
                f"**リポジトリ:** `{target_repo}` (`{branch}`)\n"
                f"**モード:** `{mode}` | **コミット:** `{effective_auto_commit}`\n\n"
                f"[Phase 1: Groq] タスク分析・計画策定中..."
            ),
            color=discord.Color.purple()
        )
        status_message = await interaction.followup.send(embed=status_embed)

        messages = [
            {"role": "system", "content": SYSTEM_INSTRUCTION_GROQ},
            {"role": "user", "content": full_prompt}
        ]

        logs = []
        handoff_requested = False
        gemini_summary = ""
        gemini_instruction = ""

        try:
            for turn in range(1, 6):
                if not task_mgr.active_tasks.get(channel_id, False):
                    await interaction.followup.send("ユーザーによって処理が中断されました。")
                    return

                response = groq_client.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    messages=messages,
                    tools=GROQ_TOOLS_SCHEMA,
                    tool_choice="auto"
                )

                response_message = response.choices[0].message
                messages.append(response_message)

                if not response_message.tool_calls:
                    final_text = response_message.content or "完了しました。"
                    status_embed.color = discord.Color.green()
                    status_embed.title = "Task Completed (Groq)"
                    await self.safe_edit_embed(status_message, status_embed)
                    await interaction.followup.send(final_text[:1900])
                    return

                for tool_call in response_message.tool_calls:
                    func_name = tool_call.function.name
                    func_args = json.loads(tool_call.function.arguments)

                    if func_name == "create_task_plan":
                        plan_str = task_mgr.set_plan(channel_id, func_args.get("tasks", []))
                        logs.append(f"**計画立案:**\n```\n{plan_str}\n```")
                        result = plan_str
                    elif func_name == "delegate_heavy_task_to_gemini":
                        handoff_requested = True
                        gemini_summary = func_args.get("summary_of_executed_steps", "")
                        gemini_instruction = func_args.get("instructions_for_gemini", full_prompt)
                        logs.append("**Geminiへ引き継ぎ実行**")
                        result = "引き継ぎ了解"
                    else:
                        result = FUNCTION_MAP[func_name](**func_args) if func_name in FUNCTION_MAP else "不明な関数"
                        logs.append(f"**Groq Tool:** `{func_name}`")

                    status_embed.description = (
                        f"**リポジトリ:** `{target_repo}` (`{branch}`)\n\n"
                        + task_mgr.get_formatted_plan(channel_id) + "\n\n"
                        + "\n".join(logs[-3:])
                    )
                    await self.safe_edit_embed(status_message, status_embed)

                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": func_name,
                        "content": str(result)
                    })

                if handoff_requested:
                    break

            if not handoff_requested:
                gemini_summary = "初期解析完了"
                gemini_instruction = full_prompt

            status_embed.title = "Agent Active (Gemini 3.5 Flash)"
            status_embed.color = discord.Color.blue()
            await self.safe_edit_embed(status_message, status_embed)

            chat = self.gemini_model.start_chat(enable_automatic_function_calling=False)
            
            handoff_prompt = (
                f"{context_header}\n"
                f"現在の計画:\n{task_mgr.get_formatted_plan(channel_id)}\n\n"
                f"これまでの進捗要約:\n{gemini_summary}\n\n"
                f"実行指示:\n{gemini_instruction}\n\n"
                f"思考(Thought)を展開した上で、必要なアクションを開始してください。"
            )

            response = chat.send_message(handoff_prompt)
            turn_count = 0

            while turn_count < max_turns:
                if not task_mgr.active_tasks.get(channel_id, False):
                    await interaction.followup.send("ユーザーによって処理が中断されました。")
                    return

                turn_count += 1
                function_call = None

                if response.candidates and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if part.text:
                            thought_text = part.text.strip()
                            if thought_text and verbose:
                                logs.append(f"**Thought:** {thought_text[:150]}...")
                        if part.function_call:
                            function_call = part.function_call

                if not function_call:
                    final_text = response.text or "タスクが完了しました。"
                    status_embed.color = discord.Color.green()
                    status_embed.title = "Task Completed"
                    status_embed.description = (
                        f"**リポジトリ:** `{target_repo}` (`{branch}`)\n\n"
                        + task_mgr.get_formatted_plan(channel_id) + "\n\n"
                        f"**全工程が完了しました。 (試行回数: {turn_count}/{max_turns})**"
                    )
                    await self.safe_edit_embed(status_message, status_embed)

                    if len(final_text) > 1900:
                        for chunk in [final_text[i:i+1900] for i in range(0, len(final_text), 1900)]:
                            await interaction.followup.send(chunk)
                    else:
                        await interaction.followup.send(final_text)
                    return

                func_name = function_call.name
                func_args = dict(function_call.args)

                logs.append(f"**Action:** `{func_name}`")
                status_embed.description = (
                    f"**リポジトリ:** `{target_repo}` (`{branch}`)\n"
                    f"**Step:** {turn_count}/{max_turns}\n\n"
                    + task_mgr.get_formatted_plan(channel_id) + "\n\n"
                    + "\n".join(logs[-4:])
                )
                await self.safe_edit_embed(status_message, status_embed)

                result = FUNCTION_MAP[func_name](**func_args) if func_name in FUNCTION_MAP else f"Error: {func_name} undefined"

                response = chat.send_message({
                    "role": "function",
                    "parts": [{
                        "function_response": {
                            "name": func_name,
                            "response": {"result": str(result)}
                        }
                    }]
                })

            status_embed.color = discord.Color.gold()
            status_embed.title = "Max Turns Reached"
            status_embed.description = f"設定された最大ターン数 ({max_turns}) に達したため処理を中断しました。"
            await self.safe_edit_embed(status_message, status_embed)

        except Exception as e:
            status_embed.color = discord.Color.red()
            status_embed.title = "Error"
            status_embed.description = f"エラーにより処理停止:\n```\n{str(e)[:1800]}\n```"
            await self.safe_edit_embed(status_message, status_embed)
        finally:
            task_mgr.active_tasks[channel_id] = False

    @agent_command.error
    @agent_stop_command.error
    async def agent_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            if interaction.response.is_done():
                await interaction.followup.send("このコマンドを実行する権限がありません。", ephemeral=True)
            else:
                await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AgentCog(bot))
