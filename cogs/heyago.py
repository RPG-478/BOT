import discord
from discord.ext import commands
from groq import AsyncGroq
import os
import json

class MultiFunctionalAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
        self.chat_model = "llama-3.1-8b-instant"

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if self.bot.user in message.mentions:
            command_text = message.content.replace(f'<@{self.bot.user.id}>', '').strip()
            
            if not command_text:
                await message.channel.send("用事があれば話しかけてください。")
                return

            async with message.channel.typing():
                try:
                    judge_prompt = (
                        "あなたはDiscordボットの入力を解析する判定システムです。ユーザーの入力が「ボットへの明確なコマンド指示」であるか、単なる「雑談・質問・会話」であるかを厳格に判定してください。\n\n"
                        "利用可能なコマンド一覧:\n"
                        "- ggrks [単語]: Google検索リンクを生成する指示（例：「〜について調べて」「〜を検索して」など、明確な検索要求がある場合のみ）\n"
                        "- join: ボイスチャンネル（VC）に参加・接続する指示\n"
                        "- leave: ボイスチャンネル（VC）から切断・退出する指示\n"
                        "- play [URL/ファイル]: 指定されたYouTubeリンクやファイルを再生する指示\n"
                        "- search [単語]: YouTubeから動画を検索して再生する指示（例：「〜の曲を流して」「〜をかけて」など、明確な再生要求がある場合のみ）\n"
                        "- volume [0.1-2.0]: 音量を設定する指示（例：「音量を1にして」「音量を少し下げて」など、具体的な数値や上下の指示がある場合。具体的な数値がない場合は、0.5や1.5などを推測して指定してください）\n"
                        "- speed [0.5-2.0]: 再生速度を設定する指示（例：「速度を1.5倍にして」など）\n"
                        "- eq [flat/spatial/bass/superbass/vocal/echo/hall/live/rotate]: イコライザーや音響プリセットを設定する指示（例：「ライブ風にして」「低音を強調して」など、明確な設定要求がある場合。単に「昨日ライブに行った」などの会話はコマンドにしないでください）\n"
                        "- panel: 音楽設定パネルを表示する指示\n\n"
                        "判定の注意点:\n"
                        "・単に単語（「ライブ」「検索」など）が含まれているだけでは、コマンド指示とは判定せず「chat」にしてください。\n"
                        "・ユーザーがボットに対して「〜してほしい」「〜を実行して」と明確に要求している場合のみ「command」にしてください。\n"
                        "・コマンドか雑談か少しでも迷った場合は、安全のために必ず「chat」と判定してください。\n\n"
                        "出力は必ず以下のJSONフォーマットのみにしてください。他のテキストは一切含めないでください。\n\n"
                        "コマンド指示と判定した場合:\n"
                        '{"action": "command", "commands": [{"name": "コマンド名", "arg": "引数（必要な場合のみ、不要なら空文字）"}]}'
                        "複数のコマンドが同時に指示された場合は、commandsのリストに複数含めてください。\n\n"
                        "雑談・会話・質問と判定した場合:\n"
                        '{"action": "chat"}'
                    )

                    chat_completion = await self.client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": judge_prompt},
                            {"role": "user", "content": command_text}
                        ],
                        model=self.chat_model,
                        response_format={"type": "json_object"}
                    )
                    
                    result = json.loads(chat_completion.choices[0].message.content)
                    
                    if result.get("action") == "chat":
                        chat_prompt = "あなたはDiscordボットのAIアシスタントです。ユーザーからの話しかけに対して、親しみやすく自然な日本語で返答してください。回答にJSONやコードを含める必要はありません。"
                        chat_response = await self.client.chat.completions.create(
                            messages=[
                                {"role": "system", "content": chat_prompt},
                                {"role": "user", "content": command_text}
                            ],
                            model=self.chat_model
                        )
                        reply_text = chat_response.choices[0].message.content
                        if len(reply_text) > 2000:
                            for i in range(0, len(reply_text), 2000):
                                await message.channel.send(reply_text[i:i+2000])
                        else:
                            await message.channel.send(reply_text)
                    
                    elif result.get("action") == "command":
                        for cmd_info in result.get("commands", []):
                            cmd_name = cmd_info.get("name")
                            cmd_arg = cmd_info.get("arg", "")
                            
                            command = self.bot.get_command(cmd_name)
                            if command:
                                if cmd_arg:
                                    message.content = f"{self.bot.command_prefix}{cmd_name} {cmd_arg}"
                                else:
                                    message.content = f"{self.bot.command_prefix}{cmd_name}"
                                
                                ctx = await self.bot.get_context(message)
                                await self.bot.invoke(ctx)

                except Exception as e:
                    await message.channel.send(f"エラーが発生しました: {e}")

async def setup(bot):
    await bot.add_cog(MultiFunctionalAI(bot))
