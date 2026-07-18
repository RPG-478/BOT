import discord
from discord.ext import commands
from groq import AsyncGroq
import os
import json

class AdaptiveAI(commands.Cog):
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
                    mode_info = await self._determine_mode(command_text)
                    await self._dispatch_mode(message, command_text, mode_info)
                except Exception as e:
                    await message.channel.send(f"エラーが発生しました: {e}")

    async def _determine_mode(self, text):
        judge_prompt = (
            "ユーザーの入力文の文脈から、どのモードで処理すべきかを厳格に判定してください。\n\n"
            "【モード一覧】\n"
            "- command: ボットの既存機能（BGM操作、音量、速度、EQ、Google検索など）への明確な指示・要求である場合\n"
            "- chat: 単なる雑談、挨拶、一般的な質問、あるいは明確なコマンド指示ではない場合\n\n"
            "出力は必ず以下のJSONフォーマットのみにしてください。\n"
            '{"mode": "command_または_chat"}'
        )

        chat_completion = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": judge_prompt},
                {"role": "user", "content": text}
            ],
            model=self.chat_model,
            response_format={"type": "json_object"}
        )
        return json.loads(chat_completion.choices[0].message.content)

    async def _dispatch_mode(self, message, text, mode_info):
        mode = mode_info.get("mode")

        if mode == "command":
            await self._handle_command_mode(message, text)
        elif mode == "chat":
            await self._handle_chat_mode(message, text)
        else:
            await self._handle_chat_mode(message, text)

    async def _handle_command_mode(self, message, text):
        prompt = (
            "入力文から実行すべきコマンドと引数を抽出してください。\n"
            "利用可能なコマンド: ggrks, join, leave, play, search, volume, speed, eq, panel\n\n"
            "出力JSONフォーマット:\n"
            '{"commands": [{"name": "コマンド名", "arg": "引数（不要なら空文字）"}]}'
        )
        chat_completion = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ],
            model=self.chat_model,
            response_format={"type": "json_object"}
        )
        result = json.loads(chat_completion.choices[0].message.content)

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

    async def _handle_chat_mode(self, message, text):
        prompt = "あなたはDiscordボットのAIアシスタントです。ユーザーからの話しかけに対して、親しみやすく自然な日本語で返答してください。"
        chat_response = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ],
            model=self.chat_model
        )
        reply_text = chat_response.choices[0].message.content
        
        if len(reply_text) > 2000:
            for i in range(0, len(reply_text), 2000):
                await message.channel.send(reply_text[i:i+2000])
        else:
            await message.channel.send(reply_text)

async def setup(bot):
    await bot.add_cog(AdaptiveAI(bot))
