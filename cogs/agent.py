import json
import ast
import sys
import io
import asyncio
import contextlib
import discord
from discord.ext import commands
from github import Github, GithubException
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

GEMINI_API_KEY = "AQ.Ab8RN6LqsTEvK4h4ZW0u-Ni7qdxbytjUuXEJaZLDV3JG0Anygg"
GITHUB_ACCESS_TOKEN = "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"

github_client = Github(GITHUB_ACCESS_TOKEN)

ALLOWED_USER_ID = 1320705325686587408

def is_authorized_user():
    async def predicate(ctx):
        return ctx.author.id == ALLOWED_USER_ID
    return commands.check(predicate)

# --- タスク管理・スケジューリングツール ---

GLOBAL_TASK_PLAN = []

def create_task_plan(tasks: list[str]) -> str:
    global GLOBAL_TASK_PLAN
    GLOBAL_TASK_PLAN = [{"id": i + 1, "task": task, "status": "未着手"} for i, task in enumerate(tasks)]
    
    formatted = "【作成されたタスク計画】\n"
    for t in GLOBAL_TASK_PLAN:
        formatted += f"{t['id']}. [{t['status']}] {t['task']}\n"
    return formatted

def update_task_status(task_id: int, status: str) -> str:
    global GLOBAL_TASK_PLAN
    for t in GLOBAL_TASK_PLAN:
        if t["id"] == task_id:
            t["status"] = status
            break
    
    formatted = "【現在の進捗状況】\n"
    for t in GLOBAL_TASK_PLAN:
        formatted += f"{t['id']}. [{t['status']}] {t['task']}\n"
    return formatted

def wait_seconds(seconds: int) -> str:
    # 実行制御用のダミー関数 (実際の非同期待機はCogメインループ側で行う)
    return f"{seconds}秒間のタイマーをセットしました。"

# --- GitHub 関連ツール ---

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

def commit_file_to_github(repo_name: str, file_path: str, content: str, commit_message: str, branch: str = "main") -> str:
    try:
        repo = github_client.get_repo(repo_name)
        try:
            existing_file = repo.get_contents(file_path, ref=branch)
            repo.update_file(path=file_path, message=commit_message, content=content, sha=existing_file.sha, branch=branch)
            return f"ファイル '{file_path}' を更新してコミットしました。"
        except GithubException as e:
            if e.status == 404:
                repo.create_file(path=file_path, message=commit_message, content=content, branch=branch)
                return f"ファイル '{file_path}' を新規作成してコミットしました。"
            else:
                raise e
    except Exception as e:
        return f"コミット失敗: {str(e)}"

def delete_github_file(repo_name: str, file_path: str, commit_message: str, branch: str = "main") -> str:
    try:
        repo = github_client.get_repo(repo_name)
        file_to_delete = repo.get_contents(file_path, ref=branch)
        repo.delete_file(path=file_path, message=commit_message, sha=file_to_delete.sha, branch=branch)
        return f"ファイル '{file_path}' を削除しました。"
    except Exception as e:
        return f"ファイル削除失敗: {str(e)}"

def create_github_branch(repo_name: str, new_branch: str, source_branch: str = "main") -> str:
    try:
        repo = github_client.get_repo(repo_name)
        source_ref = repo.get_git_ref(f"heads/{source_branch}")
        repo.create_git_ref(f"refs/heads/{new_branch}", source_ref.object.sha)
        return f"ブランチ '{new_branch}' を作成しました。"
    except Exception as e:
        return f"ブランチ作成失敗: {str(e)}"

# --- Web 検索 & 閲覧ツール ---

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

# --- コード検証 & 実行ツール ---

def check_python_syntax(code_string: str) -> str:
    try:
        ast.parse(code_string)
        return "構文チェック結果: エラーなし (Python Syntax OK)"
    except SyntaxError as e:
        return f"構文エラー検出: 行 {e.lineno}, 列 {e.offset}: {e.msg}\n該当コード箇所: {e.text}"

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

TOOLS = [
    create_task_plan,
    update_task_status,
    wait_seconds,
    list_repository_files,
    read_github_file,
    search_code_in_repo,
    commit_file_to_github,
    delete_github_file,
    create_github_branch,
    search_web,
    fetch_web_page_text,
    check_python_syntax,
    execute_python_code
]

FUNCTION_MAP = {
    "create_task_plan": create_task_plan,
    "update_task_status": update_task_status,
    "wait_seconds": wait_seconds,
    "list_repository_files": list_repository_files,
    "read_github_file": read_github_file,
    "search_code_in_repo": search_code_in_repo,
    "commit_file_to_github": commit_file_to_github,
    "delete_github_file": delete_github_file,
    "create_github_branch": create_github_branch,
    "search_web": search_web,
    "fetch_web_page_text": fetch_web_page_text,
    "check_python_syntax": check_python_syntax,
    "execute_python_code": execute_python_code
}

SYSTEM_INSTRUCTION = """
あなたはManusクラスの自律型ソフトウェアエンジニアエージェントです。

【動作ルール】
1. **計画の自動策定**: 
   複雑な指示を受けた場合、作業に入る前に**必ず** `create_task_plan` を呼び出し、タスクをサブタスクに分解して計画を立ててください。
2. **進捗追跡**: 
   各ステップの作業を開始/完了する度に `update_task_status` を呼び出し、状態（「進行中」「完了」「失敗」）を更新してください。
3. **検証と試行錯誤**:
   コード作成時は必ず `check_python_syntax` と `execute_python_code` で動作テストを行い、エラーが発生した場合は `search_web` などで自力で解決策を探してください。
4. **待機制御**:
   一定時間の待機や同期が必要な場合は `wait_seconds` を利用してください。
"""

class AgentCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            tools=TOOLS,
            system_instruction=SYSTEM_INSTRUCTION
        )

    @commands.command(name="agent")
    @is_authorized_user()
    async def agent_command(self, ctx, *, prompt: str):
        global GLOBAL_TASK_PLAN
        GLOBAL_TASK_PLAN = []

        status_embed = discord.Embed(
            title="Autonomous Agent Active",
            description="タスク分析および計画策定中...",
            color=discord.Color.blue()
        )
        status_message = await ctx.send(embed=status_embed)

        chat = self.model.start_chat(enable_automatic_function_calling=False)
        
        try:
            response = chat.send_message(prompt)
            logs = []
            max_turns = 25
            turn_count = 0

            while turn_count < max_turns:
                turn_count += 1
                function_call = None
                
                if response.candidates and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if part.function_call:
                            function_call = part.function_call
                            break

                if not function_call:
                    final_text = response.text
                    status_embed.color = discord.Color.green()
                    status_embed.title = "Task Completed"
                    
                    plan_summary = ""
                    if GLOBAL_TASK_PLAN:
                        plan_summary = "**【最終計画状況】**\n" + "\n".join([f"{t['id']}. [{t['status']}] {t['task']}" for t in GLOBAL_TASK_PLAN]) + "\n\n"

                    status_embed.description = plan_summary + ("\n".join(logs[-6:]) if logs else "処理が完了しました。")
                    await status_message.edit(embed=status_embed)
                    
                    if len(final_text) > 2000:
                        for chunk in [final_text[i:i+1900] for i in range(0, len(final_text), 1900)]:
                            await ctx.send(chunk)
                    else:
                        await ctx.send(final_text)
                    return

                func_name = function_call.name
                func_args = dict(function_call.args)
                
                # タイマー機能の実装処理
                if func_name == "wait_seconds":
                    sec = int(func_args.get("seconds", 1))
                    logs.append(f"**Step {turn_count} - Wait:** `{sec}秒間スリープ中...`\n---")
                    status_embed.description = "\n".join(logs[-6:])
                    await status_message.edit(embed=status_embed)
                    await asyncio.sleep(sec)
                    result = f"{sec}秒間の待機が完了しました。"
                else:
                    log_entry = f"**Step {turn_count} - Tool:** `{func_name}`\n```json\n{json.dumps(func_args, ensure_ascii=False, indent=2)}\n```"
                    logs.append(log_entry)
                    
                    plan_view = ""
                    if GLOBAL_TASK_PLAN:
                        plan_view = "【タスク進捗】\n" + "\n".join([f"{'▶' if t['status']=='進行中' else '✓' if t['status']=='完了' else '•'} {t['task']}" for t in GLOBAL_TASK_PLAN]) + "\n\n"

                    status_embed.description = plan_view + "\n".join(logs[-4:]) + f"\n\n*実行中... (Step {turn_count}/{max_turns})*"
                    await status_message.edit(embed=status_embed)

                    if func_name in FUNCTION_MAP:
                        result = FUNCTION_MAP[func_name](**func_args)
                    else:
                        result = f"Error: Function {func_name} is not defined."

                result_snippet = str(result)[:300] + ("..." if len(str(result)) > 300 else "")
                logs.append(f"**Result:** `{result_snippet}`\n---")
                
                response = chat.send_message(
                    genai.protos.Content(
                        parts=[
                            genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(
                                    name=func_name,
                                    response={"result": result}
                                )
                            )
                        ]
                    )
                )

            status_embed.color = discord.Color.gold()
            status_embed.title = "Step Limit Reached"
            status_embed.description = f"最大試行回数 ({max_turns} 回) に達したため、処理を中断しました。"
            await status_message.edit(embed=status_embed)

        except Exception as e:
            status_embed.color = discord.Color.red()
            status_embed.title = "Error"
            status_embed.description = f"エラーが発生しました:\n```\n{str(e)}\n```"
            await status_message.edit(embed=status_embed)

    @agent_command.error
    async def agent_command_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            await ctx.send("このコマンドを実行する権限がありません。")

async def setup(bot):
    await bot.add_cog(AgentCog(bot))
