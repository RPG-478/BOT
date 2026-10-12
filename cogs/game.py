# -*- coding: utf-8 -*-
"""/game: パーティーゲーム（人狼・ワードウルフ・UNO・ダウト・NGワード・お題しりとり）の入口。

ゲームを選ぶと、人数の目安・所要時間と「ルール」「募集する」ボタンが出る。
募集は各ゲームの cog の ``start_recruit(interaction)`` をそのまま呼ぶので、個別のコマンド
（/jinrou・/wordwolf・/uno_start・!doubt）と同じ流れになる。案内文は core/game_guides.py。
"""
import discord
from discord import app_commands
from discord.ext import commands

from core import party_ranking
from core.game_guides import GAME_GUIDES, GAME_ORDER, guide_for_discord

HUB_COLOR = 0xFFFFFF

# ゲーム id → 募集を担当する cog のクラス名（bot.get_cog で探す）
GAME_COGS = {
    "jinrou": "JinrouCog",
    "wordwolf": "CustomWordWolf",
    "uno": "Uno",
    "doubt": "Doubt",
    "ngword": "NGWord",
    "shiritori": "OdaiShiritori",
}

# 勝利数を記録しているゲーム（ここだけ「ランキング」ボタンを出す）
RANKED_GAMES = {"ngword", "shiritori"}

WORDWOLF_LISTS = [("standard", "標準"), ("starail", "崩壊：スターレイル"), ("genshin", "原神")]


def hub_embed() -> discord.Embed:
    embed = discord.Embed(
        title="パーティーゲーム",
        description="遊びたいゲームを下のメニューから選んでください。\nルールの確認と、このチャンネルでの募集ができます。",
        color=HUB_COLOR,
    )
    for game_id in GAME_ORDER:
        guide = GAME_GUIDES[game_id]
        embed.add_field(
            name=guide["name"],
            value=f"{guide['summary']}\n👥 {guide['players']}　⏱ {guide['duration']}",
            inline=False,
        )
    return embed


def detail_embed(game_id: str) -> discord.Embed:
    guide = GAME_GUIDES[game_id]
    embed = discord.Embed(title=guide["name"], description=guide["summary"], color=HUB_COLOR)
    embed.add_field(name="人数の目安", value=guide["players"], inline=True)
    embed.add_field(name="所要時間", value=guide["duration"], inline=True)
    embed.set_footer(text="「募集する」を押すと、このチャンネルで参加者の募集が始まります。")
    return embed


def rules_embed(game_id: str) -> discord.Embed:
    guide = GAME_GUIDES[game_id]
    embed = discord.Embed(title=f"{guide['name']} のルール", description=guide_for_discord(game_id), color=HUB_COLOR)
    embed.add_field(name="人数の目安", value=guide["players"], inline=True)
    embed.add_field(name="所要時間", value=guide["duration"], inline=True)
    embed.add_field(name="個別コマンド", value=" / ".join(f"`{c}`" for c in guide["commands"]), inline=False)
    return embed


async def ranking_embed(guild_id, game_id: str) -> discord.Embed:
    """このサーバーの勝利数ランキング（上位10人）。"""
    guide = GAME_GUIDES[game_id]
    rows = await party_ranking.shared().top(guild_id, game_id, limit=10) if guild_id else []
    if rows:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = [f"{medals.get(i, f'{i}.')} <@{uid}> — {wins}勝" for i, (uid, wins) in enumerate(rows, 1)]
        text = "\n".join(lines)
    else:
        text = "まだ記録がありません。"
    embed = discord.Embed(title=f"{guide['name']} のサーバーランキング", description=text, color=HUB_COLOR)
    embed.set_footer(text="勝利数の上位10人です。")
    return embed


class GameSelect(discord.ui.Select):
    def __init__(self, selected: str = None):
        options = [
            discord.SelectOption(
                label=GAME_GUIDES[g]["name"],
                value=g,
                description=f"{GAME_GUIDES[g]['players']}・{GAME_GUIDES[g]['duration']}"[:100],
                default=(g == selected),
            )
            for g in GAME_ORDER
        ]
        super().__init__(placeholder="ゲームを選ぶ", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        game_id = self.values[0]
        await interaction.response.edit_message(embed=detail_embed(game_id), view=GameDetailView(self.view.cog, game_id))


class GameHubView(discord.ui.View):
    """/game の最初の画面"""
    def __init__(self, cog):
        super().__init__(timeout=600)
        self.cog = cog
        self.add_item(GameSelect())


class WordlistSelect(discord.ui.Select):
    def __init__(self, selected: str):
        options = [discord.SelectOption(label=f"お題: {name}", value=value, default=(value == selected))
                   for value, name in WORDWOLF_LISTS]
        super().__init__(placeholder="お題のリスト", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        self.view.wordlist = self.values[0]
        for option in self.options:
            option.default = option.value == self.view.wordlist
        await interaction.response.edit_message(view=self.view)


# NGワードの設定（cogs/ngword.py の TIME_CHOICES / MODES と同じ値）
NG_TIME_CHOICES = (3, 5, 10)
NG_MODES = (("word", "ワードモード（NGは言葉）"), ("char", "一文字モード（NGはひらがな1文字）"))


class NGTimeSelect(discord.ui.Select):
    def __init__(self, selected: int):
        options = [discord.SelectOption(label=f"制限時間: {m}分", value=str(m), default=(m == selected))
                   for m in NG_TIME_CHOICES]
        super().__init__(placeholder="制限時間", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        self.view.ng_minutes = int(self.values[0])
        for option in self.options:
            option.default = option.value == self.values[0]
        await interaction.response.edit_message(view=self.view)


class NGModeSelect(discord.ui.Select):
    def __init__(self, selected: str):
        options = [discord.SelectOption(label=label, value=value, default=(value == selected))
                   for value, label in NG_MODES]
        super().__init__(placeholder="モード", options=options, row=3)

    async def callback(self, interaction: discord.Interaction):
        self.view.ng_mode = self.values[0]
        for option in self.options:
            option.default = option.value == self.values[0]
        await interaction.response.edit_message(view=self.view)


class GameDetailView(discord.ui.View):
    """ゲームを選んだ後の画面（ルール・募集する・戻る）"""
    def __init__(self, cog, game_id: str):
        super().__init__(timeout=600)
        self.cog = cog
        self.game_id = game_id
        self.wordlist = "standard"
        self.ng_minutes, self.ng_mode = 3, "word"
        if game_id == "ngword":
            self.add_item(NGTimeSelect(self.ng_minutes))
            self.add_item(NGModeSelect(self.ng_mode))
        self.add_item(GameSelect(selected=game_id))
        if game_id == "wordwolf":
            self.add_item(WordlistSelect(self.wordlist))
        if game_id not in RANKED_GAMES and not party_ranking.is_ranked(game_id):
            self.remove_item(self.ranking)

    @discord.ui.button(label="ルール", style=discord.ButtonStyle.secondary, row=2)
    async def rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=rules_embed(self.game_id), ephemeral=True)

    @discord.ui.button(label="募集する", style=discord.ButtonStyle.success, row=2)
    async def recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.start_game(interaction, self.game_id, wordlist=self.wordlist,
                                  ng_minutes=self.ng_minutes, ng_mode=self.ng_mode)

    @discord.ui.button(label="ランキング", style=discord.ButtonStyle.primary, row=2)
    async def ranking(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=await ranking_embed(interaction.guild_id, self.game_id),
                                                ephemeral=True)

    @discord.ui.button(label="戻る", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=hub_embed(), view=GameHubView(self.cog))


class GameHub(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="game", description="パーティーゲーム（人狼・ワードウルフ・UNO・ダウト・NGワード・お題しりとり）のルール確認と募集")
    async def game(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=hub_embed(), view=GameHubView(self), ephemeral=True)

    async def start_game(self, interaction: discord.Interaction, game_id: str, **options):
        """各ゲームの cog の募集処理を呼ぶ。cog が読み込まれていなければその旨を返す。"""
        cog = self.bot.get_cog(GAME_COGS[game_id])
        if cog is None or not hasattr(cog, "start_recruit"):
            name = GAME_GUIDES[game_id]["name"]
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"{name} は現在利用できません。", color=HUB_COLOR), ephemeral=True)
        if game_id == "ngword":
            return await cog.start_recruit(interaction, minutes=options.get("ng_minutes") or 3,
                                           mode=options.get("ng_mode") or "word")
        if game_id == "wordwolf":
            return await cog.start_recruit(interaction, options.get("wordlist") or "standard")
        return await cog.start_recruit(interaction)


async def setup(bot):
    await bot.add_cog(GameHub(bot))
