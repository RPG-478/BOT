# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import random
from groq import Groq
from dotenv import load_dotenv
import asyncio

load_dotenv()

class SelfRedefiningAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled_channels = {}
        # チャンネルごとの現在の「システムプロンプト」を保持
        self.current_prompts = {}
        
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        # 最初の起動時だけ使うデフォルトプロンプト
        self.default_prompt = "あなたは、受け取った言葉に対して短く返答する存在です。"

    @commands.command(name="oo")
    async def toggle_oo(self, ctx):
        """モードのオンオフ切り替え"""
        channel_id = ctx.channel.id
        current_status = self.enabled_channels.get(channel_id, False)
        new_status = not current_status
        self.enabled_channels[channel_id] = new_status
        
        # オンにした時、プロンプトを初期化
        if new_status:
            self.current_prompts[channel_id] = self.default_prompt
        
        status_text = "起動（自己再定義モード）" if new_status else "停止"
        await ctx.send(f"プロトコル始動。現在の定義を **{status_text}** しました。")

    @commands.command(name="status")
    async def check_status(self, ctx):
        """現在のシステムプロンプト（AIの定義）を表示する"""
        channel_id = ctx.channel.id
        if not self.enabled_channels.get(channel_id, False):
            await ctx.send("現在、このチャンネルでAIは停止しています。")
            return
            
        current_p = self.current_prompts.get(channel_id, self.default_prompt)
        
        # Discordの文字数制限対策をしつつ表示
        embed = discord.Embed(title="現在のAI定義（System Prompt）", color=0x00ff00)
        embed.description = f"```\n{current_p}\n```"
        embed.set_footer(text="次回のAIはこの文字列を『唯一の規範』として動作します。")
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user or message.author.bot:
            return
        if not self.enabled_channels.get(message.channel.id, False):
            return
        if message.content.startswith(self.bot.command_prefix):
            return

        # 10%の確率判定
        if random.random() >= 0.1:
            return

        channel_id = message.channel.id
        if channel_id not in self.current_prompts:
            self.current_prompts[channel_id] = self.default_prompt

        async with message.channel.typing():
            try:
                active_prompt = self.current_prompts[channel_id]
                
                loop = asyncio.get_event_loop()
                response = await asyncio.wait_for(
                    loop.run_in_executor(None, self._get_groq_response, message.content, active_prompt),
                    timeout=10.0
                )
                
                if response and response.strip():
                    # AIの発言そのものを、次回のシステムプロンプトとして「完全入れ替え」
                    self.current_prompts[channel_id] = response
                    
                    await message.reply(
                        response,
                        allowed_mentions=discord.AllowedMentions.none()
                    )
            except asyncio.TimeoutError:
                print("Groq Timeout: プロンプトが短すぎて崩壊しました。")
            except Exception as e:
                print(f"Groq Error: {e}")

    def _get_groq_response(self, user_text, system_p):
        """現在の system_p (前回のアウトプット) をプロンプトとして使用"""
        completion = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_p},
                {"role": "user", "content": user_text}
            ],
            temperature=1.2,
            max_tokens=150 # 少し余裕を持たせて入れ替わりを豊かに
        )
        return completion.choices[0].message.content

async def setup(bot):
    await bot.add_cog(SelfRedefiningAI(bot))
