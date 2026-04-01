# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random

class WordWolf(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.game_running = False
        self.players = []
        self.wolf = None
        self.player_words = {}
        self.word_pairs = [
            ("リンゴ", "ナシ"), ("焼肉", "すき焼き"), ("シャンプー", "リンス"),
            ("学校", "塾"), ("スマホ", "パソコン"), ("海", "プール"),
            ("マクドナルド", "モスバーガー"), ("うどん", "そば")
        ]

    @app_commands.command(name="wordwolf", description="ワードウルフを開始します（ホスト用）")
    async def wordwolf(self, interaction: discord.Interaction):
        if self.game_running:
            await interaction.response.send_message("既にゲームが進行中です。", ephemeral=True)
            return

        self.game_running = True
        self.players = []
        self.player_words = {}
        
        # 参加募集フェーズ
        join_view = JoinView(self)
        await interaction.response.send_message(
            "🐺 **ワードウルフ参加者募集中！**\n1分以内に【参加】ボタンを押してください。", 
            view=join_view
        )
        
        await asyncio.sleep(60)
        join_view.stop()
        
        if len(self.players) < 3:
            await interaction.channel.send("人数不足（3人以上必要）のため中止します。")
            self.game_running = False
            return

        # ワード選定と割り当て
        common, wolf_w = random.choice(self.word_pairs)
        if random.random() > 0.5:
            common, wolf_w = wolf_w, common
            
        self.wolf = random.choice(self.players)
        for p in self.players:
            self.player_words[p.id] = wolf_w if p == self.wolf else common

        # ワード確認フェーズ（ボタンを表示）
        check_view = CheckWordView(self)
        await interaction.channel.send(
            f"**募集終了！** 参加者: {', '.join([p.display_name for p in self.players])}\n"
            "下のボタンを押して、自分だけのワードを確認してください（本人にしか見えません）。",
            view=check_view
        )

    @app_commands.command(name="challenge", description="ウルフを指名します（失敗すると自分がミュート）")
    async def challenge(self, interaction: discord.Interaction, target: discord.Member):
        if not self.game_running or interaction.user not in self.players:
            await interaction.response.send_message("ゲームに参加していないか、開始されていません。", ephemeral=True)
            return

        role = discord.utils.get(interaction.guild.roles, name="muted")
        if not role:
            await interaction.response.send_message("サーバーに `muted` ロールがありません。", ephemeral=True)
            return

        if target == self.wolf:
            await interaction.response.send_message(f"✅ **成功！** {target.mention} がウルフでした。")
            punished = target
            self.game_running = False
        else:
            await interaction.response.send_message(f"❌ **失敗！** {interaction.user.mention} は誤認逮捕で脱落です。")
            punished = interaction.user

        # ミュート処理
        try:
            await punished.add_roles(role)
            await interaction.channel.send(f"{punished.mention} を1分間ミュートします。")
            await asyncio.sleep(60)
            await punished.remove_roles(role)
            await interaction.channel.send(f"{punished.mention} の解除完了。")
        except:
            await interaction.channel.send("権限エラーでミュートできませんでした。")

# --- UI Components ---

class JoinView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.button(label="参加", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.cog.players:
            self.cog.players.append(interaction.user)
            await interaction.response.send_message("参加を受け付けました。", ephemeral=True)
        else:
            await interaction.response.send_message("既に参加しています。", ephemeral=True)

class CheckWordView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None) # ゲーム中は消えないように
        self.cog = cog

    @discord.ui.button(label="自分のワードを確認", style=discord.ButtonStyle.secondary)
    async def check(self, interaction: discord.Interaction, button: discord.ui.Button):
        word = self.cog.player_words.get(interaction.user.id)
        if word:
            await interaction.response.send_message(f"あなたのワードは【**{word}**】です。", ephemeral=True)
        else:
            await interaction.response.send_message("あなたはプレイヤーではありません。", ephemeral=True)

async def setup(bot):
    await bot.add_cog(WordWolf(bot))
