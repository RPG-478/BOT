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
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GITHUB_ACCESS_TOKEN = "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"
github_client = Github(GITHUB_ACCESS_TOKEN) if GITHUB_ACCESS_TOKEN else None
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# Groqのモデルはアカウント・時期により利用可否が変わるため、環境変数で上書き可能にする。
PLANNER_MODEL = os.getenv("GROQ_PLANNER_MODEL", "openai/gpt-oss-20b")
ENGINEER_MODEL = os.getenv("GROQ_ENGINEER_MODEL", "openai/gpt-oss-120b")
MODEL_FALLBACK = os.getenv("GROQ_MODEL_FALLBACK", "openai/gpt-oss-20b")
# 無料/On-Demand枠のTPM超過を避けるため、既定の生成量を小さくする。
PLANNER_MAX_TOKENS = int(os.getenv("GROQ_PLANNER_MAX_TOKENS", "600"))
ENGINEER_MAX_TOKENS = int(os.getenv("GROQ_ENGINEER_MAX_TOKENS", "1600"))
TOOL_RESULT_MAX_CHARS = int(os.getenv("GROQ_TOOL_RESULT_MAX_CHARS", "6000"))
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

def _trim_for_llm(value: object, limit: int = TOOL_RESULT_MAX_CHARS) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "\\n…(長すぎるため省略)"

def _groq_completion(**kwargs):
    """一時的な429/5xx/413を短時間だけ再試行する。"""
    last_error = None
    for attempt in range(3):
        try:
            return groq_client.chat.completions.create(**kwargs)
        except Exception as error:
            last_error = error
            error_text = str(error).lower()
            retryable = any(marker in error_text for marker in ("rate_limit", "429", "500", "502", "503", "timeout"))
            if not retryable or attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise last_error

def _message_to_dict(message: object) -> dict:
    """Groq SDKのPydanticメッセージをAPIへ渡せる辞書へ変換する。"""
    if hasattr(message, "model_dump"):
        data = message.model_dump(exclude_none=True)
    elif isinstance(message, dict):
        data = dict(message)
    else:
        data = {"role": getattr(message, "role", "assistant"), "content": getattr(message, "content", None)}
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            data["tool_calls"] = [
                call.model_dump(exclude_none=True) if hasattr(call, "model_dump") else call
                for call in tool_calls
            ]
    if data.get("content") is None:
        data["content"] = ""
    return data

def _compact_messages(messages: list[dict], keep_last: int = 8) -> list[dict]:
    """モデルへ送る履歴を圧縮し、TPM超過を抑える。"""
    normalized = [_message_to_dict(message) for message in messages]
    if len(normalized) <= keep_last + 2:
        return normalized
    head = normalized[:2]
    tail = normalized[-keep_last:]
    compacted = head + [{**message, "content": _trim_for_llm(message.get("content", ""), 3500)} for message in tail]
    return compacted

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

    def mark_next_in_progress(self, channel_id: int) -> str:
        if channel_id in self.plans:
            for task in self.plans[channel_id]:
                if task["status"] == "未着手":
                    task["status"] = "進行中"
                    break
        return self.get_formatted_plan(channel_id)
    def mark_progress_for_tool(self, channel_id: int, tool_name: str) -> str:
        if channel_id not in self.plans:
            return self.get_formatted_plan(channel_id)
        keywords = {
            "read_github_file": "調査", "list_repository_files": "調査", "print_tree": "調査",
            "search_code_in_repo": "調査", "check_python_syntax": "検証",
            "patch_github_file": "実装", "commit_file_to_github": "コミット",
        }
        for task in self.plans[channel_id]:
            if task["status"] == "進行中" and keywords.get(tool_name, "") in task["task"]:
                task["status"] = "完了"
                break
        return self.mark_next_in_progress(channel_id)
    def update_status(self, channel_id: int, task_id: int, status: str) -> str:
        if channel_id in self.plans:
            for t in self.plans[channel_id]:
                if t["id"] == task_id:
                    t["status"] = status
                    break
        return self.get_formatted_plan(channel_id)

    def has_plan(self, channel_id: int) -> bool:
        return bool(self.plans.get(channel_id))
    def get_formatted_plan(self, channel_id: int) -> str:
        if channel_id not in self.plans or not self.plans[channel_id]:
            return "計画なし"
        formatted = "【現在のタスク計画】\n"
        for t in self.plans[channel_id]:
            symbol = "▶" if t["status"] == "進行中" else "✓" if t["status"] == "完了" else "×" if t["status"] == "失敗" else "•"
            formatted += f"{symbol} {t['id']}. [{t['status']}] {t['task']}\n"
        return formatted

task_mgr = TaskManager()

def build_default_plan(mode: str) -> list[str]:
    """モデルが計画ツールを呼ばない場合にも表示できる最低限の実行計画。"""
    if mode == "review":
        return ["対象ファイルと構成を調査", "問題箇所を再現・分析", "修正案と影響範囲を整理", "レビュー結果を報告"]
    if mode == "dry_run":
        return ["対象ファイルと要件を確認", "変更案を設計", "構文・影響を検証", "実施手順を報告"]
    return ["対象ファイルと要件を確認", "必要な変更を実装", "構文・動作を検証", "GitHubへコミット", "結果を報告"]

def print_tree(repo_name: str, path: str = "", depth: int = 2, branch: str = "main") -> str:
    """リポジトリのツリーを表示する互換ツール。"""
    try:
        depth = max(0, min(int(depth), 6))
        repo = github_client.get_repo(repo_name)
        root = repo.get_contents(path, ref=branch)
        if not isinstance(root, list):
            root = [root]
        lines = []
        def walk(items, level):
            for item in sorted(items, key=lambda entry: (entry.type != "dir", entry.path)):
                prefix = "  " * level + ("└── " if level else "")
                lines.append(f"{prefix}{item.path}")
                if item.type == "dir" and level < depth:
                    children = repo.get_contents(item.path, ref=branch)
                    walk(children if isinstance(children, list) else [children], level + 1)
        walk(root, 0)
        return "\n".join(lines) or "指定されたパスは空です。"
    except Exception as e:
        return f"ツリー取得失敗: {str(e)}"

def list_repository_files(repo_name: str, path: str = "", branch: str = "main") -> str:
    try:
        repo = github_client.get_repo(repo_name)
        contents = repo.get_contents(path, ref=branch)
        files = [f"[{'DIR' if c.type == 'dir' else 'FILE'}] {c.path}" for c in contents]
        return "\n".join(files) if files else "指定されたパスは空です。"
    except Exception as e:
        return f"ファイル一覧取得失敗: {str(e)}"

def read_github_file(
    repo_name: str,
    file_path: str,
    branch: str = "main",
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
) -> str:
    """GitHubファイルを読み込む。line_start/line_endは1始まりの行番号。"""
    try:
        if line_start is not None and line_start < 1:
            return "ファイル読み込み失敗: line_startは1以上で指定してください。"
        if line_end is not None and line_end < 1:
            return "ファイル読み込み失敗: line_endは1以上で指定してください。"
        if line_start is not None and line_end is not None and line_start > line_end:
            return "ファイル読み込み失敗: line_startはline_end以下にしてください。"
        repo = github_client.get_repo(repo_name)
        content = repo.get_contents(file_path, ref=branch).decoded_content.decode("utf-8")
        if line_start is None and line_end is None:
            return content[:20000] + ("\\n…(長すぎるため省略)" if len(content) > 20000 else "")
        lines = content.splitlines()
        start = (line_start or 1) - 1
        end = line_end or len(lines)
        selected = lines[start:end]
        return "\\n".join(f"{start + index + 1}: {line}" for index, line in enumerate(selected)) or "指定範囲に行がありません。"
    except Exception as e:
        return f"ファイル読み込み失敗: {str(e)}"

def search_code_in_repo(repo_name: str, query: str, path: str = "") -> str:
    """GitHubコード検索。pathは任意のディレクトリ絞り込みに対応する。"""
    try:
        search_query = f"{query} repo:{repo_name}"
        if path:
            search_query += f" path:{path.strip().strip('/') }"
        results = github_client.search_code(search_query)
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

def create_task_plan(tasks: list[str]) -> str:
    return "計画が設定されました。"

FUNCTION_MAP = {
    "print_tree": print_tree,
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
    "create_task_plan": create_task_plan
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
            "name": "print_tree",
            "description": "GitHubリポジトリのファイルツリーを表示します。pathとdepthは省略可能です。",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_name": {"type": "string"},
                    "path": {"type": "string"},
                    "depth": {"type": "integer", "minimum": 0, "maximum": 6},
                    "branch": {"type": "string"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_repository_files",
            "description": "リポジトリ内のファイル一覧を取得します。",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_name": {"type": "string"},
                    "path": {"type": "string"},
                    "branch": {"type": "string"}
                },
                "required": ["repo_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_github_file",
            "description": "GitHub上のファイルを読み込みます。",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_name": {"type": "string"},
                    "file_path": {"type": "string"},
                    "branch": {"type": "string"},
                    "line_start": {"type": "integer", "description": "開始行（1始まり、省略可）"},
                    "line_end": {"type": "integer", "description": "終了行（含む、省略可）"}
                },
                "required": ["repo_name", "file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_code_in_repo",
            "description": "リポジトリ内をコード検索します。",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_name": {"type": "string"},
                    "query": {"type": "string"},
                    "path": {"type": "string", "description": "検索対象ディレクトリ（省略可）"}
                },
                "required": ["repo_name", "query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_github_issue",
            "description": "GitHubのIssue情報を取得します。",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_name": {"type": "string"},
                    "issue_number": {"type": "integer"}
                },
                "required": ["repo_name", "issue_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "patch_github_file",
            "description": "既存のGitHubファイルを部分置換して更新します。",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_name": {"type": "string"},
                    "file_path": {"type": "string"},
                    "target_code": {"type": "string"},
                    "replacement_code": {"type": "string"},
                    "commit_message": {"type": "string"},
                    "branch": {"type": "string"}
                },
                "required": ["repo_name", "file_path", "target_code", "replacement_code", "commit_message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "commit_file_to_github",
            "description": "GitHubにファイルを新規または更新コミットします。",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_name": {"type": "string"},
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                    "commit_message": {"type": "string"},
                    "branch": {"type": "string"}
                },
                "required": ["repo_name", "file_path", "content", "commit_message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Web検索を行います。",
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
            "name": "fetch_web_page_text",
            "description": "Webページのテキストを取得します。",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_python_syntax",
            "description": "Pythonコードの構文チェックを行います。",
            "parameters": {
                "type": "object",
                "properties": {"code_string": {"type": "string"}},
                "required": ["code_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python_code",
            "description": "Pythonコードを実行します。",
            "parameters": {
                "type": "object",
                "properties": {"code_string": {"type": "string"}},
                "required": ["code_string"]
            }
        }
    }
]

SYSTEM_INSTRUCTION_GROQ_PLANNER = """
あなたは超高速なフロント・プランニングエージェントです。
ユーザーの依頼を実行可能な3〜7個の具体的な手順へ分解してください。
必ずcreate_task_planツールを1回呼び出し、tasks配列に計画を渡してください。
計画を作らずに回答を終了してはいけません。
"""

SYSTEM_INSTRUCTION_GROQ_ENGINEER = """
あなたは高度なメインエンジニアエージェントです。
必ずタスクを調査・検証してから結論を出してください。
動作モードがnormalで自動コミット許可がTrueの場合、コード変更を行ったら必ず
patch_github_fileまたはcommit_file_to_githubを実行し、その戻り値で成功を確認してください。
コミットツールを実行していないのに「コミットした」「変更を反映した」と報告してはいけません。
dry_runまたはreviewではファイル変更・コミットを行わず、提案やレビュー結果だけを返してください。
"""

class AgentCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_edit_time = {}

    def render_progress(self, embed, target_repo, branch, mode, phase, turn_count, max_turns, logs, commit_done=False):
        """進捗をDiscord Embedの固定フィールドへ描画する。"""
        completed = min(turn_count, max_turns)
        bar_size = 12
        filled = int((completed / max_turns) * bar_size) if max_turns else 0
        progress_bar = "█" * filled + "░" * (bar_size - filled)
        embed.description = f"**フェーズ:** {phase}\n`{progress_bar}` {completed}/{max_turns} steps"
        embed.clear_fields()
        embed.add_field(name="対象", value=f"`{target_repo}`\nブランチ: `{branch}`\nモード: `{mode}`", inline=True)
        embed.add_field(name="状態", value=f"{phase}\nGitHubコミット: {'実行済み' if commit_done else '未実行'}", inline=True)
        recent = "\n".join(logs[-3:]) if logs else "まだツール操作はありません。"
        embed.add_field(name="直近の操作", value=_trim_for_llm(recent, 1000), inline=False)

    async def safe_edit_embed(self, message, embed, min_interval=2.0):
        now = time.time()
        msg_id = message.id
        if msg_id in self.last_edit_time:
            elapsed = now - self.last_edit_time[msg_id]
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
        try:
            # Discord Embedの各上限と全体上限（6000文字）を超えないよう整形する。
            if embed.title:
                embed.title = embed.title[:256]
            if embed.description:
                embed.description = embed.description[:4096]
            for field in embed.fields:
                field.name = (field.name or "")[:256]
                field.value = (field.value or "")[:1024]
            if embed.footer and embed.footer.text:
                embed.set_footer(text=embed.footer.text[:2048], icon_url=embed.footer.icon_url)
            if embed.author and embed.author.name:
                embed.set_author(name=embed.author.name[:256], url=embed.author.url, icon_url=embed.author.icon_url)
            total = len(embed.title or "") + len(embed.description or "")
            total += sum(len(field.name or "") + len(field.value or "") for field in embed.fields)
            total += len(embed.footer.text or "") if embed.footer else 0
            total += len(embed.author.name or "") if embed.author else 0
            if total > 6000 and embed.description:
                allowed = max(0, 6000 - (total - len(embed.description)))
                embed.description = embed.description[:allowed]
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

    @app_commands.command(name="agent", description="Groq単体で自律タスクを実行させます")
    @app_commands.describe(
        prompt="実行したいタスクの内容",
        repo_name="対象のGitHubリポジトリ (例: owner/repo)",
        branch="対象Gitブランチ (デフォルト: main)",
        mode="動作モード (normal: 通常実行, dry_run: 修正案のみ提示, review: コードレビューのみ)",
        auto_commit="ファイル編集後に自動コミットするか (デフォルト: True)",
        issue_number="関連するGitHub Issue番号",
        max_turns="最大ループ試行回数 (1-60, デフォルト: 60)",
        verbose="詳細な思考ログを表示するか (デフォルト: True)"
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
        max_turns: app_commands.Range[int, 1, 60] = 60,
        verbose: bool = True
    ):
        if groq_client is None:
            await interaction.response.send_message("GROQ_API_KEYが未設定のためAgentコマンドを利用できません。環境変数を設定してください。", ephemeral=True)
            return
        if github_client is None and (repo_name or DEFAULT_REPO_NAME):
            await interaction.response.send_message("GITHUB_ACCESS_TOKENが未設定のためGitHub操作を利用できません。環境変数を設定してください。", ephemeral=True)
            return
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
            title="Agent Active (Groq Planner)",
            description=(
                f"**リポジトリ:** `{target_repo}` (`{branch}`)\n"
                f"**モード:** `{mode}` | **コミット:** `{effective_auto_commit}`\n\n"
                f"[Phase 1] 高速モデルによるタスク分析・計画策定中..."
            ),
            color=discord.Color.purple()
        )
        status_message = await interaction.followup.send(embed=status_embed)

        planner_messages = [
            {"role": "system", "content": SYSTEM_INSTRUCTION_GROQ_PLANNER},
            {"role": "user", "content": full_prompt}
        ]

        try:
            plan_response = _groq_completion(
                model=PLANNER_MODEL,
                messages=_compact_messages(planner_messages),
                tools=GROQ_TOOLS_SCHEMA,
                tool_choice="auto",
                max_tokens=PLANNER_MAX_TOKENS
            )
            
            planner_msg = plan_response.choices[0].message
            if planner_msg.tool_calls:
                for tc in planner_msg.tool_calls:
                    if tc.function.name == "create_task_plan":
                        args = json.loads(tc.function.arguments)
                        tasks = [str(task).strip() for task in args.get("tasks", []) if str(task).strip()]
                        if tasks:
                            task_mgr.set_plan(channel_id, tasks[:7])
            if not task_mgr.has_plan(channel_id):
                task_mgr.set_plan(channel_id, build_default_plan(mode))

            plan_context = task_mgr.get_formatted_plan(channel_id)
            full_prompt_with_plan = f"{full_prompt}\\n\\n【確定した実行計画】\\n{plan_context}"
            status_embed.title = "Agent Active (Groq Engineer)"
            status_embed.color = discord.Color.blue()
            
            engineer_messages = [
                {"role": "system", "content": SYSTEM_INSTRUCTION_GROQ_ENGINEER},
                {"role": "user", "content": full_prompt_with_plan}
            ]

            logs = ["計画策定が完了しました。実行フェーズへ移行します。"]
            commit_actions = []
            completed_tools = set()
            repeated_calls = {}
            commit_reminders = 0
            fallback_used = False
            current_model = ENGINEER_MODEL
            turn_count = 0
            self.render_progress(status_embed, target_repo, branch, mode, "実行準備完了", turn_count, max_turns, logs)
            status_embed.add_field(name="計画", value=_trim_for_llm(task_mgr.get_formatted_plan(channel_id), 1000), inline=False)
            await self.safe_edit_embed(status_message, status_embed)

            while turn_count < max_turns:
                if not task_mgr.active_tasks.get(channel_id, False):
                    await interaction.followup.send("ユーザーによって処理が中断されました。")
                    return

                turn_count += 1

                try:
                    response = _groq_completion(
                        model=current_model,
                        messages=_compact_messages(engineer_messages),
                        tools=GROQ_TOOLS_SCHEMA,
                        tool_choice="auto",
                        max_tokens=ENGINEER_MAX_TOKENS if current_model == ENGINEER_MODEL else 800
                    )
                except Exception as model_error:
                    error_text = str(model_error)
                    retryable_model_error = any(marker in error_text for marker in (
                        "model_not_found", "does not exist", "do not have access",
                        "rate_limit_exceeded", "Request too large", "413", "TPM",
                        "tool_use_failed", "invalid_request_error"
                    ))
                    if not fallback_used and current_model != MODEL_FALLBACK and retryable_model_error:
                        fallback_used = True
                        current_model = MODEL_FALLBACK
                        logs.append(f"モデルエラーを検出。計画と履歴を保持したまま `{MODEL_FALLBACK}` へ切替")
                        self.render_progress(status_embed, target_repo, branch, mode, "フォールバックへ切替・処理継続", turn_count, max_turns, logs, bool(commit_actions))
                        status_embed.add_field(name="計画", value=_trim_for_llm(task_mgr.get_formatted_plan(channel_id), 1000), inline=False)
                        await self.safe_edit_embed(status_message, status_embed)
                        continue
                    raise

                response_message = response.choices[0].message
                engineer_messages.append(_message_to_dict(response_message))

                if not response_message.tool_calls:
                    final_text = response_message.content or "タスクが完了しました。"
                    commit_done = bool(commit_actions)
                    if effective_auto_commit and mode == "normal" and not commit_done and commit_reminders < 2:
                        commit_reminders += 1
                        logs.append(f"コミット確認を再要求 ({commit_reminders}/2)")
                        engineer_messages.append({"role": "user", "content": "完了判定の前に実変更を確認してください。normalモードで変更が必要だった場合は、必ずpatch_github_fileまたはcommit_file_to_githubを実行し、成功結果を確認してから完了してください。変更不要なら、その理由を明記してください。"})
                        self.render_progress(status_embed, target_repo, branch, mode, "コミット確認・再検証中", turn_count, max_turns, logs, commit_done)
                        status_embed.add_field(name="計画", value=_trim_for_llm(task_mgr.get_formatted_plan(channel_id), 1000), inline=False)
                        await self.safe_edit_embed(status_message, status_embed)
                        continue
                    if effective_auto_commit and mode == "normal" and not commit_done:
                        final_text += "\\n\\n注意: コミットツールが実行されていないため、GitHubへの変更コミットはありません。"
                    status_embed.color = discord.Color.green() if (not effective_auto_commit or mode != "normal" or commit_done) else discord.Color.gold()
                    status_embed.title = "Task Completed" if (not effective_auto_commit or mode != "normal" or commit_done) else "Task Completed (No Commit)"
                    self.render_progress(status_embed, target_repo, branch, mode, "完了", turn_count, max_turns, logs, commit_done)
                    status_embed.add_field(name="計画", value=_trim_for_llm(task_mgr.get_formatted_plan(channel_id), 1000), inline=False)
                    await self.safe_edit_embed(status_message, status_embed)

                    if len(final_text) > 1900:
                        for chunk in [final_text[i:i+1900] for i in range(0, len(final_text), 1900)]:
                            await interaction.followup.send(chunk)
                    else:
                        await interaction.followup.send(final_text)
                    return

                for tool_call in response_message.tool_calls:
                    func_name = tool_call.function.name
                    func_args = json.loads(tool_call.function.arguments)

                    call_key = json.dumps({"name": func_name, "args": func_args}, ensure_ascii=False, sort_keys=True)
                    repeated_calls[call_key] = repeated_calls.get(call_key, 0) + 1
                    if repeated_calls[call_key] >= 3:
                        result = "同じツール呼び出しが3回続いたため停止しました。別の調査方法、より狭いpath、またはline_start/line_endを指定してください。"
                        logs.append(f"**Loop guard:** `{func_name}` の重複呼び出しを停止")
                        task_mgr.update_status(channel_id, 1, "失敗")
                    elif func_name == "create_task_plan":
                        plan_str = task_mgr.set_plan(channel_id, func_args.get("tasks", []))
                        logs.append(f"**計画立案:**\n```\n{plan_str}\n```")
                        result = plan_str
                    else:
                        if func_name in {"print_tree", "list_repository_files", "read_github_file", "search_code_in_repo", "patch_github_file", "commit_file_to_github", "get_github_issue"}:
                            func_args.setdefault("repo_name", target_repo)
                            func_args.setdefault("branch", branch)
                        if func_name in FUNCTION_MAP:
                            task_mgr.mark_progress_for_tool(channel_id, func_name)
                            result = FUNCTION_MAP[func_name](**func_args)
                            if func_name in {"patch_github_file", "commit_file_to_github"}:
                                result_text = str(result)
                                if any(marker in result_text for marker in ("コミットしました", "更新コミットしました", "新規作成コミットしました")):
                                    commit_actions.append({"tool": func_name, "result": result_text})
                                    completed_tools.add(func_name)
                        else:
                            result = f"未登録のツールです: {func_name}。利用可能なツールを使って再試行してください。"
                        logs.append(f"**Action:** `{func_name}`")

                    self.render_progress(status_embed, target_repo, branch, mode, f"ツール実行中: {func_name}", turn_count, max_turns, logs, bool(commit_actions))
                    status_embed.add_field(name="計画", value=_trim_for_llm(task_mgr.get_formatted_plan(channel_id), 1000), inline=False)
                    await self.safe_edit_embed(status_message, status_embed)

                    engineer_messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": func_name,
                        "content": _trim_for_llm(result)
                    })

            status_embed.color = discord.Color.gold()
            status_embed.title = "Max Turns Reached"
            self.render_progress(status_embed, target_repo, branch, mode, "最大ステップ数に到達", turn_count, max_turns, logs, bool(commit_actions))
            status_embed.add_field(name="計画", value=_trim_for_llm(task_mgr.get_formatted_plan(channel_id), 1000), inline=False)
            await self.safe_edit_embed(status_message, status_embed)

        except Exception as e:
            # モデルが廃止・権限外の場合は、安定した小型モデルで一度だけ再試行する。
            error_text = str(e)
            if ("model_not_found" in error_text or "does not exist" in error_text or "do not have access" in error_text
                    or "rate_limit_exceeded" in error_text or "Request too large" in error_text
                    or "413" in error_text or "TPM" in error_text):
                try:
                    status_embed.title = "Model fallback"
                    status_embed.description = f"Planner初期化エラーのため `{MODEL_FALLBACK}` で計画を再構成します。"
                    await self.safe_edit_embed(status_message, status_embed)
                    fallback_messages = [
                        {"role": "system", "content": SYSTEM_INSTRUCTION_GROQ_ENGINEER},
                        {"role": "user", "content": _trim_for_llm(full_prompt, 5000)}
                    ]
                    fallback_response = _groq_completion(
                        model=MODEL_FALLBACK,
                        messages=_compact_messages(fallback_messages),
                        tools=GROQ_TOOLS_SCHEMA,
                        tool_choice="auto",
                        max_tokens=800
                    )
                    fallback_text = fallback_response.choices[0].message.content or "フォールバックモデルで処理が完了しました。"
                    status_embed.color = discord.Color.green()
                    status_embed.title = "Task Completed (Fallback Model)"
                    status_embed.description = f"使用モデル: `{MODEL_FALLBACK}`"
                    await self.safe_edit_embed(status_message, status_embed)
                    await interaction.followup.send(fallback_text[:1900])
                    return
                except Exception as fallback_error:
                    error_text = f"初回: {error_text}\nフォールバック: {fallback_error}"
            status_embed.color = discord.Color.red()
            status_embed.title = "Error"
            status_embed.description = f"エラーにより処理停止:\n```\n{error_text[:1800]}\n```"
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
