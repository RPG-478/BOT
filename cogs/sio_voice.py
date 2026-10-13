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

CONNECTION_ACTIONS = [
    app_commands.Choice(name="参加", value="join"),
    app_commands.Choice(name="退出", value="leave"),
    app_commands.Choice(name="状態", value="status"),
]
STUDIO_FEATURES = [
    app_commands.Choice(name="録音", value="record"),
    app_commands.Choice(name="やまびこ", value="echo"),
    app_commands.Choice(name="文字起こし", value="transcribe"),
    app_commands.Choice(name="カラオケ", value="karaoke"),
]
STUDIO_ACTIONS = [
    app_commands.Choice(name="開始", value="start"),
    app_commands.Choice(name="停止/終了", value="stop"),
    app_commands.Choice(name="状態", value="status"),
    app_commands.Choice(name="音程解析", value="pitch"),
    app_commands.Choice(name="遅延変更", value="delay"),
    app_commands.Choice(name="採点", value="score"),
]
EFFECT_ACTIONS = [
    app_commands.Choice(name="開始", value="start"),
    app_commands.Choice(name="停止", value="stop"),
    app_commands.Choice(name="状態/設定変更", value="status"),
]
COMMUNITY_NETWORKS = [
    app_commands.Choice(name="ランダム通話", value="match"),
    app_commands.Choice(name="グローバルVC", value="global"),
]
COMMUNITY_ACTIONS = [
    app_commands.Choice(name="開始/参加", value="start"),
    app_commands.Choice(name="終了/退出", value="stop"),
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
            embed.description = f"Bot は **{name}** に接続していますが、使っている機能の記録がありません。`/voice connection action:退出` で退出できます。"
        else:
            embed.description = "いまはどの機能も使っていません。"
        saito = self.bot.get_cog(COGS["match"])
        if saito is not None and any(getattr(r.guild, "id", None) == guild.id for r in getattr(saito, "matching_queue", [])):
            embed.description += "\nランダム通話の相手を探しています（`/voice community network:ランダム通話 action:終了/退出` で取り消し）。"
        return embed

    # ------------------------------------------------------------ 統合サブコマンド
    @voice_group.command(name="connection", description="BotのVC参加・退出・利用状況")
    @app_commands.choices(action=CONNECTION_ACTIONS)
    @app_commands.describe(action="参加・退出・状態確認")
    async def voice_connection(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        if action.value == "status":
            return await Responder(interaction).send(embed=self.status_embed(interaction.guild), ephemeral=True)
        cog = await self._cog(interaction, "music")
        if cog:
            if action.value == "join":
                await cog._join_impl(Responder(interaction))
            else:
                await cog._leave_impl(Responder(interaction))

    @voice_group.command(name="studio", description="録音・やまびこ・文字起こし・カラオケを操作")
    @app_commands.choices(feature=STUDIO_FEATURES, action=STUDIO_ACTIONS)
    @app_commands.describe(feature="操作する機能", action="実行する操作", delay="やまびこの遅延秒数",
                           channel="文字起こしの送り先（省略時は現在のチャンネル）", lyrics="カラオケ開始時のお題歌詞")
    async def voice_studio(self, interaction: discord.Interaction, feature: app_commands.Choice[str],
                           action: app_commands.Choice[str],
                           delay: app_commands.Range[float, 0.1, 30.0] | None = None,
                           channel: discord.TextChannel | None = None, lyrics: str | None = None):
        key = feature.value
        valid = {
            "record": {"start", "stop", "status", "pitch"},
            "echo": {"start", "stop", "delay"},
            "transcribe": {"start", "stop"},
            "karaoke": {"start", "stop", "score"},
        }
        if action.value not in valid[key]:
            return await interaction.response.send_message("この機能では選択した操作を利用できません。機能と操作の組み合わせを確認してください。", ephemeral=True)
        cog_key = "record" if key == "echo" else key
        cog = await self._cog(interaction, cog_key)
        if not cog:
            return
        responder = Responder(interaction)
        if key == "record":
            await cog._record_impl(responder, action.value)
        elif key == "echo":
            await cog._echo_impl(responder, action.value, delay)
        elif key == "transcribe":
            await cog._transcribe_impl(responder, action.value, channel)
        else:
            await cog._karaoke_impl(responder, action.value, lyrics)

    @voice_group.command(name="effects", description="ボイスチェンジャーの開始・停止・設定")
    @app_commands.choices(action=EFFECT_ACTIONS)
    @app_commands.describe(action="実行する操作", pitch="ピッチ（半音）", buffer_ms="目標プリバッファms", max_ms="上限バッファms")
    async def voice_effects(self, interaction: discord.Interaction, action: app_commands.Choice[str],
                            pitch: app_commands.Range[float, -24.0, 24.0] | None = None,
                            buffer_ms: app_commands.Range[float, 20.0, 2000.0] | None = None,
                            max_ms: app_commands.Range[float, 20.0, 4000.0] | None = None):
        cog = await self._cog(interaction, "changer")
        if cog:
            await cog._changer_impl(Responder(interaction), action.value, pitch=pitch, buffer_ms=buffer_ms, max_ms=max_ms)

    @voice_group.command(name="community", description="ランダム通話・グローバルVCを操作")
    @app_commands.choices(network=COMMUNITY_NETWORKS, action=COMMUNITY_ACTIONS)
    @app_commands.describe(network="接続する機能", action="開始/参加または終了/退出", room="グローバルVCのルーム名", password="非公開ルームのパスワード")
    async def voice_community(self, interaction: discord.Interaction, network: app_commands.Choice[str],
                              action: app_commands.Choice[str], room: str | None = None,
                              password: str | None = None):
        if network.value == "match":
            cog = await self._cog(interaction, "match")
            mapped = "start" if action.value == "start" else "stop"
            if cog:
                await cog._match_impl(Responder(interaction), mapped)
        else:
            cog = await self._cog(interaction, "global")
            mapped = "join" if action.value == "start" else "leave"
            if cog:
                await cog._global_impl(Responder(interaction), mapped, room, password)


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceHub(bot))
