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
    VOICE_ACTIONS = [
        app_commands.Choice(name="VC参加", value="join"), app_commands.Choice(name="VC退出", value="leave"),
        app_commands.Choice(name="VC状態", value="status"),
        *[app_commands.Choice(name=f"録音: {label}", value=f"record_{value}") for label, value in
          (("開始", "start"), ("停止", "stop"), ("状態", "status"), ("音程解析", "pitch"))],
        *[app_commands.Choice(name=f"やまびこ: {label}", value=f"echo_{value}") for label, value in
          (("開始", "start"), ("停止", "stop"), ("遅延変更", "delay"))],
        app_commands.Choice(name="文字起こし: 開始", value="transcribe_start"),
        app_commands.Choice(name="文字起こし: 停止", value="transcribe_stop"),
        app_commands.Choice(name="カラオケ: 開始", value="karaoke_start"),
        app_commands.Choice(name="カラオケ: 停止", value="karaoke_stop"),
        app_commands.Choice(name="カラオケ: 採点", value="karaoke_score"),
        app_commands.Choice(name="ボイスチェンジャー: 開始", value="changer_start"),
        app_commands.Choice(name="ボイスチェンジャー: 停止", value="changer_stop"),
        app_commands.Choice(name="ボイスチェンジャー: 状態/設定", value="changer_status"),
        app_commands.Choice(name="ランダム通話: 開始/参加", value="match_start"),
        app_commands.Choice(name="ランダム通話: 終了/退出", value="match_stop"),
        app_commands.Choice(name="グローバルVC: 開始/参加", value="global_start"),
        app_commands.Choice(name="グローバルVC: 終了/退出", value="global_stop"),
    ]

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
            embed.description = f"Bot は **{name}** に接続していますが、使っている機能の記録がありません。`/voice` のパネルから退出できます。"
        else:
            embed.description = "いまはどの機能も使っていません。"
        saito = self.bot.get_cog(COGS["match"])
        if saito is not None and any(getattr(r.guild, "id", None) == guild.id for r in getattr(saito, "matching_queue", [])):
            embed.description += "\nランダム通話の相手を探しています（`/voice` のパネルから取り消し）。"
        return embed

    # ------------------------------------------------------------ 統合サブコマンド
    async def voice_connection(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        if action.value == "status":
            return await Responder(interaction).send(embed=self.status_embed(interaction.guild), ephemeral=True)
        cog = await self._cog(interaction, "music")
        if cog:
            if action.value == "join":
                await cog._join_impl(Responder(interaction))
            else:
                await cog._leave_impl(Responder(interaction))

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

    async def voice_effects(self, interaction: discord.Interaction, action: app_commands.Choice[str],
                            pitch: app_commands.Range[float, -24.0, 24.0] | None = None,
                            buffer_ms: app_commands.Range[float, 20.0, 2000.0] | None = None,
                            max_ms: app_commands.Range[float, 20.0, 4000.0] | None = None):
        cog = await self._cog(interaction, "changer")
        if cog:
            await cog._changer_impl(Responder(interaction), action.value, pitch=pitch, buffer_ms=buffer_ms, max_ms=max_ms)

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

    @app_commands.command(name="voice", description="ボイス機能の操作パネルを表示します")
    async def voice(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔊 ボイス機能パネル",
            description="下のメニューから参加・録音・文字起こし・音声加工・通話を選択してください。",
            color=0x3498DB,
        )
        await interaction.response.send_message(embed=embed, view=VoicePanelView(self), ephemeral=True)

    async def dispatch_voice_action(self, interaction: discord.Interaction, value: str,
                    delay: app_commands.Range[float, 0.1, 30.0] | None = None,
                    channel: discord.TextChannel | None = None, lyrics: str | None = None,
                    pitch: app_commands.Range[float, -24.0, 24.0] | None = None,
                    buffer_ms: app_commands.Range[float, 20.0, 2000.0] | None = None,
                    max_ms: app_commands.Range[float, 20.0, 4000.0] | None = None,
                    room: str | None = None, password: str | None = None):
        if value in {"join", "leave", "status"}:
            return await self.voice_connection(interaction, app_commands.Choice(name=value, value=value))
        if "_" not in value:
            return await Responder(interaction).send("操作を選択してください。", ephemeral=True)
        key, operation = value.rsplit("_", 1)
        if key in {"record", "echo", "transcribe", "karaoke"}:
            return await self.voice_studio(
                interaction, app_commands.Choice(name=key, value=key),
                app_commands.Choice(name=operation, value=operation), delay, channel, lyrics)
        if key == "changer":
            return await self.voice_effects(
                interaction, app_commands.Choice(name=operation, value=operation), pitch, buffer_ms, max_ms)
        return await self.voice_community(
            interaction, app_commands.Choice(name=key, value=key),
            app_commands.Choice(name=operation, value=operation), room, password)


class VoicePanelView(discord.ui.View):
    """引数を覚えなくてもボイス機能を選べる操作パネル。"""

    def __init__(self, hub: VoiceHub):
        super().__init__(timeout=900)
        self.hub = hub
        self.add_item(self.ActionSelect(hub))

    class ActionSelect(discord.ui.Select):
        def __init__(self, hub: VoiceHub):
            self.hub = hub
            options = [
                discord.SelectOption(label=choice.name, value=choice.value)
                for choice in hub.VOICE_ACTIONS
            ]
            super().__init__(placeholder="🔊 ボイス操作を選択してください", options=options)

        async def callback(self, interaction: discord.Interaction):
            if self.values[0] == "global_start":
                return await interaction.response.send_modal(GlobalRoomModal(self.hub))
            await self.hub.dispatch_voice_action(interaction, self.values[0])


class GlobalRoomModal(discord.ui.Modal, title="グローバルVCに参加"):
    room = discord.ui.TextInput(label="ルーム名", placeholder="参加するルーム名", max_length=100)
    password = discord.ui.TextInput(label="パスワード（任意）", required=False, max_length=100)

    def __init__(self, hub: VoiceHub):
        super().__init__()
        self.hub = hub

    async def on_submit(self, interaction: discord.Interaction):
        await self.hub.dispatch_voice_action(
            interaction, "global_start", room=self.room.value, password=self.password.value or None
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceHub(bot))
