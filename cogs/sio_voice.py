"""/voice グループ: ボイスチャンネルを使う機能（参加・退出・録音・やまびこ・文字起こし・カラオケ・
ボイスチェンジャー・ランダム通話・グローバルVC）の入口。

それぞれの処理は各機能の cog にある実装関数（``_xxx_impl``）を呼ぶだけ。
VC を誰が使っているかは core/voice_session.py が持つ。
"""
from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from core.legacy import Responder
from core.voice_session import get_manager, stop_hint

RECORD_ACTIONS = [
    app_commands.Choice(name="開始", value="start"),
    app_commands.Choice(name="停止", value="stop"),
    app_commands.Choice(name="状態", value="status"),
    app_commands.Choice(name="音程解析", value="pitch"),
]
ECHO_ACTIONS = [
    app_commands.Choice(name="開始", value="start"),
    app_commands.Choice(name="遅延変更", value="delay"),
    app_commands.Choice(name="停止", value="stop"),
]
TRANSCRIBE_ACTIONS = [
    app_commands.Choice(name="開始", value="start"),
    app_commands.Choice(name="停止", value="stop"),
]
KARAOKE_ACTIONS = [
    app_commands.Choice(name="開始", value="start"),
    app_commands.Choice(name="採点", value="score"),
    app_commands.Choice(name="終了", value="stop"),
]
CHANGER_ACTIONS = [
    app_commands.Choice(name="開始", value="start"),
    app_commands.Choice(name="停止", value="stop"),
    app_commands.Choice(name="状態", value="status"),
]
MATCH_ACTIONS = [
    app_commands.Choice(name="開始", value="start"),
    app_commands.Choice(name="終了", value="stop"),
]
GLOBAL_ACTIONS = [
    app_commands.Choice(name="参加", value="join"),
    app_commands.Choice(name="退出", value="leave"),
]

# 各機能の cog の名前（クラス名）
COGS = {
    "music": "VoiceCog",
    "record": "RecordingCog",
    "transcribe": "TranscriptionCog",
    "karaoke": "KaraokeCog",
    "changer": "VoiceChangerCog",
    "match": "SaitoRelay",
    "global": "GlobalVCCog",
}


def format_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}時間{minutes}分"
    if minutes:
        return f"{minutes}分{secs}秒"
    return f"{secs}秒"


class VoiceHub(commands.Cog):
    voice_group = app_commands.Group(name="voice", description="ボイスチャンネルの機能（参加・録音・文字起こしなど）", guild_only=True)

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_sessions = get_manager(bot)

    async def _cog(self, interaction: discord.Interaction, key: str):
        cog = self.bot.get_cog(COGS[key])
        if cog is None:
            await Responder(interaction).send("⚠️ この機能はいま読み込まれていません。", ephemeral=True)
        return cog

    # ------------------------------------------------------------ 状態
    def status_embed(self, guild) -> discord.Embed:
        """このサーバーの VC を、どの機能が・誰の操作で使っているか。"""
        session = self.voice_sessions.get(guild.id)
        if session is not None:
            channel = guild.get_channel(session.channel_id) if session.channel_id else None
            channel_text = getattr(channel, "mention", None) or getattr(channel, "name", None) or "不明"
            embed = discord.Embed(title="🔊 ボイスチャンネルの使用状況", color=0x2ECC71)
            embed.add_field(name="機能", value=session.label, inline=True)
            embed.add_field(name="開始した人", value=session.user_name, inline=True)
            embed.add_field(name="チャンネル", value=channel_text, inline=True)
            embed.add_field(name="経過時間", value=format_elapsed(time.time() - session.started_at), inline=True)
            embed.add_field(name="終了するには", value=f"`{stop_hint(session.feature)}`", inline=False)
            embed.set_footer(text="別の機能を始められるのは、開始した人・管理者か、開始した人が VC にいないときです。")
            return embed

        embed = discord.Embed(title="🔇 ボイスチャンネルの使用状況", color=0x95A5A6)
        voice_client = getattr(guild, "voice_client", None)
        if voice_client is not None:
            name = getattr(getattr(voice_client, "channel", None), "name", "不明")
            embed.description = f"Bot は **{name}** に接続していますが、使っている機能の記録がありません。`/voice leave` で退出できます。"
        else:
            embed.description = "いまはどの機能も使っていません。"
        saito = self.bot.get_cog(COGS["match"])
        if saito is not None and any(getattr(r.guild, "id", None) == guild.id for r in getattr(saito, "matching_queue", [])):
            embed.description += "\nランダム通話の相手を探しています（`/voice match action:終了` で取り消し）。"
        return embed

    # ------------------------------------------------------------ サブコマンド
    @voice_group.command(name="join", description="あなたのいるボイスチャンネルに Bot を参加させます")
    async def voice_join(self, interaction: discord.Interaction):
        cog = await self._cog(interaction, "music")
        if cog:
            await cog._join_impl(Responder(interaction))

    @voice_group.command(name="leave", description="Bot をボイスチャンネルから退出させます（使用中の機能も終わります）")
    async def voice_leave(self, interaction: discord.Interaction):
        cog = await self._cog(interaction, "music")
        if cog:
            await cog._leave_impl(Responder(interaction))

    @voice_group.command(name="status", description="ボイスチャンネルをどの機能・誰が使っているかを表示します")
    async def voice_status(self, interaction: discord.Interaction):
        await Responder(interaction).send(embed=self.status_embed(interaction.guild), ephemeral=True)

    @voice_group.command(name="record", description="ボイスチャンネルの録音（開始・停止・状態・音程解析）")
    @app_commands.choices(action=RECORD_ACTIONS)
    @app_commands.describe(action="すること")
    async def voice_record(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        cog = await self._cog(interaction, "record")
        if cog:
            await cog._record_impl(Responder(interaction), action.value)

    @voice_group.command(name="echo", description="やまびこ（話した声を遅れて返す）")
    @app_commands.choices(action=ECHO_ACTIONS)
    @app_commands.describe(action="すること", delay="遅延時間（秒）。開始と遅延変更で使います")
    async def voice_echo(self, interaction: discord.Interaction, action: app_commands.Choice[str],
                         delay: app_commands.Range[float, 0.1, 30.0] = None):
        cog = await self._cog(interaction, "record")
        if cog:
            await cog._echo_impl(Responder(interaction), action.value, delay)

    @voice_group.command(name="transcribe", description="ボイスチャンネルの文字起こし")
    @app_commands.choices(action=TRANSCRIBE_ACTIONS)
    @app_commands.describe(action="すること", channel="文字起こしを送るチャンネル（省略するとこのチャンネル）")
    async def voice_transcribe(self, interaction: discord.Interaction, action: app_commands.Choice[str],
                               channel: discord.TextChannel | None = None):
        cog = await self._cog(interaction, "transcribe")
        if cog:
            await cog._transcribe_impl(Responder(interaction), action.value, channel)

    @voice_group.command(name="karaoke", description="カラオケ（歌詞の字幕と採点）")
    @app_commands.choices(action=KARAOKE_ACTIONS)
    @app_commands.describe(action="すること", lyrics="お題の歌詞（開始のときに入れます）")
    async def voice_karaoke(self, interaction: discord.Interaction, action: app_commands.Choice[str],
                            lyrics: str | None = None):
        cog = await self._cog(interaction, "karaoke")
        if cog:
            await cog._karaoke_impl(Responder(interaction), action.value, lyrics)

    @voice_group.command(name="changer", description="ボイスチェンジャー（動作中に pitch などを付けると設定を変えます）")
    @app_commands.choices(action=CHANGER_ACTIONS)
    @app_commands.describe(action="すること", pitch="ピッチ（半音。例: 4 で高く、-4 で低く）",
                           buffer_ms="目標プリバッファ（ms、20 以上）", max_ms="上限バッファ（ms）")
    async def voice_changer(self, interaction: discord.Interaction, action: app_commands.Choice[str],
                            pitch: app_commands.Range[float, -24.0, 24.0] = None,
                            buffer_ms: app_commands.Range[float, 20.0, 2000.0] = None,
                            max_ms: app_commands.Range[float, 20.0, 4000.0] = None):
        cog = await self._cog(interaction, "changer")
        if cog:
            await cog._changer_impl(Responder(interaction), action.value, pitch=pitch, buffer_ms=buffer_ms, max_ms=max_ms)

    @voice_group.command(name="match", description="ランダム通話（別のサーバーの人とつなぐ）")
    @app_commands.choices(action=MATCH_ACTIONS)
    @app_commands.describe(action="すること")
    async def voice_match(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        cog = await self._cog(interaction, "match")
        if cog:
            await cog._match_impl(Responder(interaction), action.value)

    @voice_group.command(name="global", description="グローバルVC（別のサーバーの同じ名前のルームとつなぐ）")
    @app_commands.choices(action=GLOBAL_ACTIONS)
    @app_commands.describe(action="すること", room="ルーム名（参加のときに入れます）", password="非公開ルームのパスワード")
    async def voice_global(self, interaction: discord.Interaction, action: app_commands.Choice[str],
                           room: str | None = None, password: str | None = None):
        cog = await self._cog(interaction, "global")
        if cog:
            await cog._global_impl(Responder(interaction), action.value, room, password)


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceHub(bot))
