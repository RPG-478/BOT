import discord
from discord.ext import commands
from groq import AsyncGroq
import os

class AIChat(commands.Cog):
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
                    chat_completion = await self.client.chat.completions.create(
                        messages=[
                            {"role": "user", "content": command_text}
                        ],
                        model=self.chat_model,
                    )
                    response_text = chat_completion.choices[0].message.content
                    
                    if len(response_text) > 2000:
                        for i in range(0, len(response_text), 2000):
                            await message.channel.send(response_text[i:i+2000])
                    else:
                        await message.channel.send(response_text)
                except Exception as e:
                    await message.channel.send(f"エラーが発生しました: {e}")

async def setup(bot):
    await bot.add_cog(AIChat(bot))
