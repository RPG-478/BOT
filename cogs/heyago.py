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
                    system_prompt = (
                        "You are an AI assistant for a Discord bot. Analyze the user's input and determine if it matches any bot commands or if it is a general chat.\n"
                        "Available commands:\n"
                        "- ggrks [word]: Google search link\n"
                        "- join: Join voice channel\n"
                        "- leave: Leave voice channel\n"
                        "- play [url/file]: Play audio\n"
                        "- search [word]: Search and play from YouTube\n"
                        "- volume [0.1-2.0]: Set volume. If user says 'lower' or 'higher' without specific number, guess an appropriate value (e.g., 0.5 or 1.5)\n"
                        "- speed [0.5-2.0]: Set playback speed\n"
                        "- eq [flat/spatial/bass/superbass/vocal/echo/hall/live/rotate]: Set equalizer preset\n"
                        "- panel: Show music control panel\n\n"
                        "Respond ONLY with a JSON object.\n"
                        "Format for commands:\n"
                        '{"action": "command", "commands": [{"name": "command_name", "arg": "argument_string"}]}'
                        "If multiple commands are needed, include them in the commands list.\n"
                        "Format for general chat:\n"
                        '{"action": "chat", "reply": "your response in Japanese"}'
                    )

                    chat_completion = await self.client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": command_text}
                        ],
                        model=self.chat_model,
                        response_format={"type": "json_object"}
                    )
                    
                    result = json.loads(chat_completion.choices[0].message.content)
                    
                    if result.get("action") == "chat":
                        reply_text = result.get("reply", "")
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
