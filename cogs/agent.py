import json
import discord
from discord.ext import commands
from github import Github, GithubException
import google.generativeai as genai

GEMINI_API_KEY = "AQ.Ab8RN6LqsTEvK4h4ZW0u-Ni7qdxbytjUuXEJaZLDV3JG0Anygg"
GITHUB_ACCESS_TOKEN = "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"

github_client = Github(GITHUB_ACCESS_TOKEN)

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

FUNCTION_MAP = {
    "commit_file_to_github": commit_file_to_github
}

class AgentCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            tools=[commit_file_to_github]
        )

    @commands.command(name="agent")
    async def agent_command(self, ctx, *, prompt: str):
        status_embed = discord.Embed(
            title="Agent Processing",
            description="思考中...",
            color=discord.Color.blue()
        )
        status_message = await ctx.send(embed=status_embed)

        chat = self.model.start_chat(enable_automatic_function_calling=False)
        
        try:
            response = chat.send_message(prompt)
            logs = []

            while True:
                function_call = None
                if response.candidates and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if part.function_call:
                            function_call = part.function_call
                            break

                if not function_call:
                    final_text = response.text
                    status_embed.color = discord.Color.green()
                    status_embed.title = "Processing Complete"
                    status_embed.description = "\n".join(logs) if logs else "処理が完了しました。"
                    await status_message.edit(embed=status_embed)
                    
                    if len(final_text) > 2000:
                        for chunk in [final_text[i:i+1900] for i in range(0, len(final_text), 1900)]:
                            await ctx.send(chunk)
                    else:
                        await ctx.send(final_text)
                    break

                func_name = function_call.name
                func_args = dict(function_call.args)
                
                log_entry = f"**実行ツール:** `{func_name}`\n```json\n{json.dumps(func_args, ensure_ascii=False, indent=2)}\n```"
                logs.append(log_entry)
                
                status_embed.description = "\n".join(logs) + "\n\n*ツールを実行中...*"
                await status_message.edit(embed=status_embed)

                if func_name in FUNCTION_MAP:
                    result = FUNCTION_MAP[func_name](**func_args)
                else:
                    result = f"Error: Function {func_name} is not mapped."

                logs.append(f"**実行結果:** `{result}`\n---")
                status_embed.description = "\n".join(logs) + "\n\n*次の思考中...*"
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

        except Exception as e:
            status_embed.color = discord.Color.red()
            status_embed.title = "Error"
            status_embed.description = f"エラーが発生しました:\n```\n{str(e)}\n```"
            await status_message.edit(embed=status_embed)

async def setup(bot):
    await bot.add_cog(AgentCog(bot))
