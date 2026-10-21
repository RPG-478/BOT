"""/general: コイン・生存確認・ランキング系機能の操作パネル。"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from core.panel_v2 import as_panel_v2, edit_panel_v2
from core import guild_settings, shortcuts
from core.game_guides import GAME_GUIDES, GAME_ORDER


GENERAL_GENRES = {
    "economy": ("コイン・ランキング", "所持状況、送金、コインや bump/up のランキング"),
    "survival": ("生存確認", "追跡、アクティブ頻度、フリーズ、失踪警報"),
    "custom": ("custom", "メッセージで実行するショートカットの登録・編集・削除"),
}
GENERAL_ACTIONS = {
    "economy": [
        ("プレイヤー状況", "status"),
        ("コイン送金", "pay"),
        ("コイン保有ランキング", "coin_leaderboard"),
        ("bump RTAランキング", "bump_leaderboard"),
        ("up RTAランキング", "up_leaderboard"),
    ],
    "survival": [
        ("追跡登録・解除", "fujo_register"),
        ("アクティブ頻度", "fujo_hindo"),
        ("生存確認ランキング", "fujo_ranking"),
        ("フリーズ", "fujo_freeze"),
        ("失踪警報解除", "fujo_panic_disable"),
    ],
    "custom": [("ショートカットを管理", "shortcut_manage")],
}

SHORTCUT_ROOTS = {
    "general": ("/general", [(label, value) for values in GENERAL_ACTIONS.values() for label, value in values if value != "shortcut_manage"]),
    "vc": ("/vc", [("VC参加", "join"), ("VC退出", "leave"), ("VC状態", "status"),
                    ("音楽操作パネル", "music_panel"), ("録音開始", "record_start"), ("録音停止", "record_stop"),
                    ("やまびこ開始", "echo_start"), ("やまびこ停止", "echo_stop"),
                    ("文字起こし開始", "transcribe_start"), ("文字起こし停止", "transcribe_stop"),
                    ("カラオケ開始", "karaoke_start"), ("カラオケ停止", "karaoke_stop"),
                    ("ランダム通話開始", "match_start"), ("ランダム通話終了", "match_stop"),
                    ("グローバルVC開始", "global_start"), ("グローバルVC終了", "global_stop")]),
    "game": ("/game", [("ゲーム開始: " + GAME_GUIDES[game]["name"], "game:" + game) for game in GAME_ORDER]),
    "support": ("/support", [("Muted設定", "muted"), ("匿名つぶやき", "whisper"), ("メッセージ削除", "clear"),
                              ("一括ロール操作", "role_bulk"), ("bump/up状態", "bumprta_status"),
                              ("bump/upオン", "bumprta_on"), ("bump/upオフ", "bumprta_off"),
                              ("絵文字便乗設定", "binjou"), ("VC入退室履歴", "vc_log"),
                              ("メッセージ編集履歴", "message_log"), ("モデレート履歴", "moderation_log"),
                              ("ハニーポット", "honeypot")]),
    "help": ("/help", [("ヘルプを表示", "overview")]),
}


class PayModal(discord.ui.Modal, title="コインを送金"):
    receiver_id = discord.ui.TextInput(label="送金先のユーザーID", max_length=20)
    amount = discord.ui.TextInput(label="送金するAGO", max_length=9)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction):
        try:
            receiver = await self.cog.bot.fetch_user(int(self.receiver_id.value))
            amount = int(self.amount.value)
        except (ValueError, discord.HTTPException):
            return await interaction.response.send_message("ユーザーIDまたは数量が正しくありません。", ephemeral=True)
        await self.cog.bot.get_cog("WalletCog").pay(interaction, receiver, amount)


class GeneralGenreSelect(discord.ui.Select):
    def __init__(self, cog, selected: str | None = None):
        self.cog = cog
        super().__init__(
            placeholder="ジャンルを選択してください",
            options=[discord.SelectOption(label=label, description=description, value=value,
                                          default=value == selected)
                     for value, (label, description) in GENERAL_GENRES.items()],
            row=0,
        )

    async def callback(self, interaction):
        view: GeneralPanel = self.view
        wrapper = view if hasattr(view, "panel") else None
        view = getattr(view, "panel", view)
        view.genre = self.values[0]
        view.action = None
        if wrapper is not None:
            wrapper.refresh()
            return await edit_panel_v2(interaction, wrapper)
        view.refresh()
        return await edit_panel_v2(interaction, as_panel_v2(view))


class GeneralActionSelect(discord.ui.Select):
    def __init__(self, cog, genre: str):
        self.cog = cog
        self.genre = genre
        super().__init__(
            placeholder="機能を選択してください",
            options=[discord.SelectOption(label=label, value=value) for label, value in GENERAL_ACTIONS[genre]],
            row=1,
        )

    async def callback(self, interaction):
        view: GeneralPanel = self.view
        panel = getattr(view, "panel", view)
        panel.action = self.values[0]
        if panel.shortcut_mode:
            if hasattr(view, "_sync"):
                view._sync()
                return await edit_panel_v2(interaction, view)
            return await edit_panel_v2(interaction, as_panel_v2(panel))
        await self.cog.dispatch_general(interaction, self.values[0])


class GeneralPanel(discord.ui.View):
    def __init__(self, cog, genre: str | None = None, shortcut_mode: bool = False, shortcut_item: dict | None = None):
        super().__init__(timeout=300)
        self.cog = cog
        saved = (shortcut_item or {}).get("action", {})
        self.genre = genre or saved.get("genre")
        self.action = saved.get("value")
        self.shortcut_mode = shortcut_mode
        self.shortcut_item = shortcut_item
        self.refresh()

    def refresh(self):
        self.clear_items()
        self.add_item(GeneralGenreSelect(self.cog, self.genre))
        if self.genre:
            self.add_item(GeneralActionSelect(self.cog, self.genre))
        if self.shortcut_mode:
            self.add_item(ShortcutCommitButton())

    def shortcut_action(self):
        if not self.genre or not self.action:
            return None
        return {"root": "general", "genre": self.genre, "value": self.action}

    def embed(self):
        description = "ジャンルを選ぶと、その中の機能を選択できます。"
        if self.genre:
            description = f"**{GENERAL_GENRES[self.genre][0]}** の機能を選択してください。"
        return discord.Embed(title="一般機能", description=description, color=0xFFFFFF)
