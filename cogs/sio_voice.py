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
from core.panel_v2 import as_panel_v2

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

VOICE_GENRES = {
    "connection": ("VC接続", "参加、退出、現在の使用状況"),
    "music": ("音楽", "音楽操作パネル"),
    "studio": ("録音・音声制作", "録音、やまびこ、文字起こし、カラオケ"),
    "effects": ("音声加工", "ボイスチェンジャー"),
    "community": ("通話ネットワーク", "ランダム通話、グローバルVC"),
}
VOICE_ACTIONS_BY_GENRE = {
    "connection": [("参加", "join"), ("退出", "leave"), ("状態", "status")],
    "music": [("音楽操作パネル", "music_panel")],
    "studio": [(f"録音: {label}", f"record_{value}") for label, value in
                (("開始", "start"), ("停止", "stop"), ("状態", "status"), ("音程解析", "pitch"))] +
               [(f"やまびこ: {label}", f"echo_{value}") for label, value in
                (("開始", "start"), ("停止", "stop"), ("遅延変更", "delay"))] +
               [("文字起こし: 開始", "transcribe_start"), ("文字起こし: 停止", "transcribe_stop"),
                ("カラオケ: 開始", "karaoke_start"), ("カラオケ: 停止", "karaoke_stop"),
                ("カラオケ: 採点", "karaoke_score")],
    "effects": [("開始", "changer_start"), ("停止", "changer_stop"), ("状態/設定", "changer_status")],
    "community": [("ランダム通話: 開始/参加", "match_start"), ("ランダム通話: 終了/退出", "match_stop"),
                   ("グローバルVC: 開始/参加", "global_start"), ("グローバルVC: 終了/退出", "global_stop")],
}

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
        app_commands.Choice(name="音楽操作パネル", value="music_panel"),
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

    @app_commands.command(name="vc", description="音楽・ボイス機能の操作パネルを表示します")
    async def vc(self, interaction: discord.Interaction):
        view = VoicePanelView(self)
        await interaction.response.send_message(view=as_panel_v2(view), ephemeral=True)

    async def dispatch_voice_action(self, interaction: discord.Interaction, value: str,
                    delay: app_commands.Range[float, 0.1, 30.0] | None = None,
                    channel: discord.TextChannel | None = None, lyrics: str | None = None,
                    pitch: app_commands.Range[float, -24.0, 24.0] | None = None,
                    buffer_ms: app_commands.Range[float, 20.0, 2000.0] | None = None,
                    max_ms: app_commands.Range[float, 20.0, 4000.0] | None = None,
                    room: str | None = None, password: str | None = None):
        if value == "music_panel":
            cog = await self._cog(interaction, "music")
            if cog:
                await cog._panel_impl(Responder(interaction))
            return
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


class VoiceGenreSelect(discord.ui.Select):
    def __init__(self, hub: VoiceHub, selected: str | None = None):
        self.hub = hub
        super().__init__(placeholder="ジャンルを選択してください", options=[
            discord.SelectOption(label=label, description=description, value=value, default=value == selected)
            for value, (label, description) in VOICE_GENRES.items()
        ], row=0)

    async def callback(self, interaction: discord.Interaction):
        container = self.view
        view: VoicePanelView = getattr(container, "panel", container)
        view.genre = self.values[0]
        view.action = None
        view.refresh()
        if hasattr(container, "_sync"):
            container._sync()
            return await interaction.response.edit_message(view=container)
        await interaction.response.edit_message(embed=view.embed(), view=view)


class VoiceActionSelect(discord.ui.Select):
    def __init__(self, hub: VoiceHub, genre: str):
        self.hub = hub
        super().__init__(placeholder="機能を選択してください", options=[
            discord.SelectOption(label=label, value=value)
            for label, value in VOICE_ACTIONS_BY_GENRE[genre]
        ], row=1)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        container = self.view
        panel = getattr(container, "panel", container)
        panel.action = value
        if getattr(panel, "shortcut_mode", False):
            if hasattr(container, "_sync"):
                container._sync()
                return await interaction.response.edit_message(view=container)
            return await interaction.response.edit_message(embed=panel.embed(), view=panel)
        if value == "global_start":
            return await interaction.response.send_modal(GlobalRoomModal(self.hub))
        await self.hub.dispatch_voice_action(interaction, value)


class VoicePanelView(discord.ui.View):
    """引数を覚えなくてもボイス機能を選べるジャンル別操作パネル。"""

    def __init__(self, hub: VoiceHub, genre: str | None = None, shortcut_mode: bool = False,
                 shortcut_item: dict | None = None):
        super().__init__(timeout=900)
        self.hub = hub
        saved = (shortcut_item or {}).get("action", {})
        self.genre = genre or saved.get("genre")
        self.action = saved.get("value")
        self.shortcut_mode = shortcut_mode
        self.shortcut_item = shortcut_item
        self.refresh()

    def refresh(self):
        self.clear_items()
        self.add_item(VoiceGenreSelect(self.hub, self.genre))
        if self.genre:
            self.add_item(VoiceActionSelect(self.hub, self.genre))
        if self.shortcut_mode:
            from cogs.general import ShortcutCommitButton
            self.add_item(ShortcutCommitButton())

    def shortcut_action(self):
        if not self.genre or not self.action:
            return None
        return {"root": "vc", "genre": self.genre, "value": self.action}

    def embed(self):
        description = "ジャンルを選ぶと、その中の機能を選択できます。"
        if self.genre:
            description = f"**{VOICE_GENRES[self.genre][0]}** の機能を選択してください。"
        return discord.Embed(title="🔊 VC・音楽機能パネル", description=description, color=0xFFFFFF)


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
