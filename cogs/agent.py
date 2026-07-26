import os
import json
import discord
from discord.ext import commands
from google import genai
from google.genai import types
from github import Github, GithubException
from dotenv import load_dotenv

load_dotenv()

# =========================================================
# 実行を許可するDiscordユーザーIDのリスト
# 例: [123456789012345678, 987654321098765432]
# 環境変数 ALLOWED_USER_IDS="123456789,987654321" からも自動読み込みします
# =========================================================
ALLOWED_USER_IDS = [1320705325686587408]

# ここに自分のDiscordユーザーID（数値）を直接書き込んでも構いません
# ALLOWED_USER_IDS.append(123456789012345678)


def is_authorized_user():
    """実行ユーザーの制限チェック"""
    async def predicate(ctx: commands.Context):
        # Botのオーナー（作成者）または指定ユーザーリストに含まれていれば許可
        if await ctx.bot.is_owner(ctx.author) or ctx.author.id in ALLOWED_USER_IDS:
            return True
        
        await ctx.send("❌ **権限エラー:** このコマンドを実行する権限がありません。")
        return False
    return commands.check(predicate)


class AIAgentCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.repo_name = os.getenv("GITHUB_REPO")

    def _get_gemini_client(self):
        # OSの環境変数等から GEMINI_API_KEY を取得
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("OS環境変数に `GEMINI_API_KEY` が設定されていません。")
        return genai.Client(api_key=api_key)

    def _fetch_entire_repository(self, repo) -> str:
        """リポジトリ内の主要テキストファイルの中身を取得して1つにまとめる"""
        ignore_dirs = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "env", "node_modules", ".github"}
        target_extensions = (".py", ".txt", ".json", ".md", ".yml", ".yaml", ".sh")

        repo_context = []
        contents = repo.get_contents("")

        while contents:
            file_content = contents.pop(0)
            if file_content.type == "dir":
                if file_content.name not in ignore_dirs:
                    contents.extend(repo.get_contents(file_content.path))
            elif file_content.name.endswith(target_extensions):
                try:
                    text = file_content.decoded_content.decode("utf-8")
                    repo_context.append(f"=== FILE: {file_content.path} ===\n{text}\n")
                except Exception:
                    continue

        return "\n".join(repo_context)

    @commands.command(name="ai")
    @is_authorized_user()
    async def ai_dev(self, ctx: commands.Context, *, instruction: str):
        async with ctx.typing():
            try:
                # Geminiクライアントの初期化
                gemini_client = self._get_gemini_client()
                
                # GitHubクライアントの初期化
                github_client = Github(self.github_token)
                repo = github_client.get_repo(self.repo_name)

                # リポジトリ全体のソースコードを取得
                full_repo_code = self._fetch_entire_repository(repo)

                system_instruction = (
                    "あなたはGitHubリポジトリ全体を正確に理解して開発を行うフルスタックAIエンジニアです。"
                    "提供された全リポジトリのコードと構成を分析し、ユーザーの指示を達成するためのコード変更・追加を行ってください。\n"
                    "複数ファイルの編集や新規作成に対応できます。"
                    "出力は解説などを含めず、必ず以下のJSONフォーマットのみを返してください。\n"
                    "フォーマット:\n"
                    "{\n"
                    '  "commit_message": "コミットメッセージ",\n'
                    '  "changes": [\n'
                    '    {\n'
                    '      "file_path": "対象ファイルのパス",\n'
                    '      "content": "変更または新規作成後のファイル全文"\n'
                    '    }\n'
                    '  ]\n'
                    "}"
                )

                prompt = (
                    f"以下は現在のGitHubリポジトリ全体のソースコードです:\n\n"
                    f"{full_repo_code}\n\n"
                    f"指示: {instruction}"
                )

                response = gemini_client.models.generate_content(
                    model="gemini-3.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json"
                    )
                )

                result = json.loads(response.text)
                commit_msg = result.get("commit_message", "AI auto commit")
                changes = result.get("changes", [])

                if not changes:
                    await ctx.send("変更対象のファイルがありませんでした。")
                    return

                processed_files = []

                # GitHubへ順次コミット＆プッシュ
                for change in changes:
                    target_path = change["file_path"]
                    new_content = change["content"]

                    try:
                        current_file = repo.get_contents(target_path)
                        repo.update_file(
                            path=target_path,
                            message=f"[AI] {commit_msg}",
                            content=new_content,
                            sha=current_file.sha
                        )
                        processed_files.append(f"更新: `{target_path}`")
                    except GithubException:
                        repo.create_file(
                            path=target_path,
                            message=f"[AI] {commit_msg}",
                            content=new_content
                        )
                        processed_files.append(f"作成: `{target_path}`")

                embed = discord.Embed(
                    title="AI開発タスク完了",
                    color=discord.Color.green()
                )
                embed.add_field(name="コミットメッセージ", value=f"`{commit_msg}`", inline=False)
                embed.add_field(name="反映ファイル", value="\n".join(processed_files), inline=False)

                await ctx.send(embed=embed)

            except Exception as e:
                embed = discord.Embed(
                    title="エラーが発生しました",
                    description=f"```\n{str(e)}\n```",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(AIAgentCog(bot))
