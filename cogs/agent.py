import json
import ast
import discord
from discord.ext import commands
from github import Github, GithubException
import google.generativeai as genai

GEMINI_API_KEY = "AQ.Ab8RN6LqsTEvK4h4ZW0u-Ni7qdxbytjUuXEJaZLDV3JG0Anygg"
GITHUB_ACCESS_TOKEN = "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"

github_client = Github(GITHUB_ACCESS_TOKEN)

# --- 許可されたユーザーのみ実行可能にするデコレータ ---
ALLOWED_USER_ID = 1320705325686587408

def is_authorized_user():
    async def predicate(ctx):
        return ctx.author.id == ALLOWED_USER_ID
    return commands.check(predicate)

# --- エージェント用の各種ツール定義 ---

def list_repository_files(repo_name: str, path: str = "", branch: str = "main") -> str:
    try:
        repo = github_client.get_repo(repo_name)
        contents = repo.get_contents(path, ref=branch)
        files = []
        for content in contents:
            file_type = "DIR" if content.type == "dir" else "FILE"
            files.append(f"[{file_type}] {content.path}")
        return "\n".join(files) if files else "指定されたパスは空です。"
    except Exception as e:
        return f"ファイル一覧取得失敗: {str(e)}"

def read_github_file(repo_name: str, file_path: str, branch: str = "main") -> str:
    try:
        repo = github_client.get_repo(repo_name)
        file_content = repo.get_contents(file_path, ref=branch)
        return file_content.decoded_content.decode("utf-8")
    except Exception as e:
        return f"ファイル読み込み失敗: {str(e)}"

def check_python_syntax(code_string: str) -> str:
    try:
        ast.parse(code_string)
        return "構文チェック結果: エラーなし (Python Syntax OK)"
    except SyntaxError as e:
        return f"構文エラー検出: 行 {e.lineno}, 列 {e.offset}: {e.msg}\n該当コード箇所: {e.text}"

def commit_file_to_github(repo_name: str, file_path: str, content: str, commit_message: str, branch: str = "main") -> str:
    try:
        repo = github_client.get_repo(repo_name)
        try:
            existing_file = repo.get_contents(file_path, ref=branch)
            repo.update_file(
                path=file_path,
                message=commit_message,
                content=content,
                sha=existing_file.sha,
                branch=branch
            )
            return f"ファイル '{file_path}' を更新してコミットしました。"
        except GithubException as e:
            if e.status == 404:
                repo.create_file(
                    path=file_path,
                    message=commit_message,
                    content=content,
                    branch=branch
                )
                return f"ファイル '{file_path}' を新規作成してコミットしました。"
            else:
                raise e
    except Exception as e:
        return f"コミット失敗: {str(e)}"

TOOLS = [
    list_repository_files,
    read_github_file,
    check_python_syntax,
    commit_file_to_github
]

FUNCTION_MAP = {
    "list_repository_files": list_repository_files,
    "read_github_file": read_github_file,
    "check_python_syntax": check_python_syntax,
    "commit_file_to_github": commit_file_to_github
}

SYSTEM_INSTRUCTION = """
あなたは高い自律性と粘り強さを持ったソフトウェアエンジニアエージェントです。
目的を達成するために、自ら思考し、以下の能力を駆使して粘り強く解決策を実行してください。

1. **探索**: リポジトリ構造が分からない場合は `list_repository_files` や `read_github_file` を使い、自発的にコードを調査・取得してください。
2. **検証**: Pythonコードを作成・修正した際は、コミットする前に必ず `check_python_syntax` を使って構文エラー（バグ）がないかを検証してください。
3. **試行錯誤**: エラーが検出されたり失敗した場合は、妥協せず原因を分析し、修正案を考えて再実行・再検証を行ってください。
4. **適用**: バグがないことを確認できたら `commit_file_to_github` で変更をコミットしてください。
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
        status_embed = discord.Embed(
            title="Autonomous Agent Active",
            description="思考および戦略策定中...",
            color=discord.Color.blue()
        )
        status_message = await ctx.send(embed=status_embed)

        chat = self.model.start_chat(enable_automatic_function_calling=False)
        
        try:
            response = chat.send_message(prompt)
            logs = []
            max_turns = 15
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
                    status_embed.description = f"**総ステップ数:** {turn_count}\n\n" + ("\n".join(logs[-10:]) if logs else "処理が完了しました。")
                    await status_message.edit(embed=status_embed)
                    
                    if len(final_text) > 2000:
                        for chunk in [final_text[i:i+1900] for i in range(0, len(final_text), 1900)]:
                            await ctx.send(chunk)
                    else:
                        await ctx.send(final_text)
                    return

                func_name = function_call.name
                func_args = dict(function_call.args)
                
                log_entry = f"**Step {turn_count} - Tool:** `{func_name}`\n```json\n{json.dumps(func_args, ensure_ascii=False, indent=2)}\n```"
                logs.append(log_entry)
                
                status_embed.description = "\n".join(logs[-6:]) + f"\n\n*実行中... (Step {turn_count}/{max_turns})*"
                await status_message.edit(embed=status_embed)

                if func_name in FUNCTION_MAP:
                    result = FUNCTION_MAP[func_name](**func_args)
                else:
                    result = f"Error: Function {func_name} is not defined."

                result_snippet = str(result)[:300] + ("..." if len(str(result)) > 300 else "")
                logs.append(f"**Result:** `{result_snippet}`\n---")
                
                status_embed.description = "\n".join(logs[-6:]) + f"\n\n*次のアクションを思考中...*"
                await status_message.edit(embed=status_embed)

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
