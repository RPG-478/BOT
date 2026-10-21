"""サポート系機能を /support に統合する入口。"""
from __future__ import annotations
import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands

from cogs.clear import MAX_CLEAR
from core import guild_settings
from core.panel_v2 import as_panel_v2
logger = logging.getLogger(__name__)
# --- 認証パネル作成機能用に追加 ---
from cogs.auth import get_intro_webhook, sanitize_webhook_name, role_failure_reason

AUTH_SECTION = "auth"
AUTH_MODE_SIMPLE = "simple"
AUTH_MODE_FORM = "form"
AUTH_MAX_QUESTIONS = 5

AUTH_DEFAULT_QUESTIONS = [
    {
        "label": "あだ名はなんですか？(20文字以内)",
        "placeholder": "20文字以内で入力",
        "max_length": 20,
        "style": "short",
        "required": True,
    },
]


def _auth_int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def normalize_auth_questions(value) -> list[dict]:
    if not isinstance(value, list):
        return []

    result: list[dict] = []
    for item in value[:AUTH_MAX_QUESTIONS]:
        if not isinstance(item, dict):
            continue

        label = str(item.get("label") or "").strip()
        if not label:
            continue

        placeholder = str(item.get("placeholder") or "").strip()
        max_length = _auth_int(item.get("max_length")) or 200
        max_length = max(1, min(1000, max_length))

        style_raw = str(item.get("style") or "short").strip().lower()
        style = "paragraph" if style_raw in {"paragraph", "long", "長い"} else "short"

        required = item.get("required", True)
        if not isinstance(required, bool):
            required = True

        result.append(
            {
                "label": label[:45],
                "placeholder": placeholder[:100],
                "max_length": max_length,
                "style": style,
                "required": required,
            }
        )

    return result


def get_auth_settings(store, guild_id: int) -> dict:
    raw = store.get(guild_id, AUTH_SECTION)
    if not isinstance(raw, dict):
        raw = {}

    enabled = raw.get("enabled") if isinstance(raw.get("enabled"), bool) else True

    mode = raw.get("mode")
    if mode not in {AUTH_MODE_SIMPLE, AUTH_MODE_FORM}:
        mode = AUTH_MODE_FORM

    role_id = _auth_int(raw.get("role_id"))
    intro_channel_id = _auth_int(raw.get("intro_channel_id"))
    panel_channel_id = _auth_int(raw.get("panel_channel_id"))

    raw_questions = raw.get("questions")
    if raw_questions is None:
        questions = normalize_auth_questions(AUTH_DEFAULT_QUESTIONS)
    else:
        questions = normalize_auth_questions(raw_questions)

    return {
        "enabled": enabled,
        "mode": mode,
        "role_id": role_id,
        "intro_channel_id": intro_channel_id,
        "panel_channel_id": panel_channel_id,
        "questions": questions,
    }


def auth_role_error(guild: discord.Guild, role: discord.Role | None) -> str | None:
    if role is None:
        return "認証で付与するロールが選択されていません。"

    if role.is_default():
        return "@everyone ロールは認証ロールにできません。"

    if getattr(role, "managed", False):
        return "連携サービスが管理するロールは認証ロールにできません。"

    me = getattr(guild, "me", None)
    permissions = getattr(getattr(me, "guild_permissions", None), "manage_roles", False)
    if me is None or not permissions:
        return "Botに「ロールの管理」権限がありません。"

    if role >= me.top_role:
        return "Botより上位、または同順位のロールは付与できません。"

    return None


async def edit_auth_panel_message(interaction: discord.Interaction, panel):
    """Modal後などでも設定パネルを再描画するための補助。"""
    try:
        await interaction.response.edit_message(
            content=None,
            embed=None,
            attachments=[],
            view=as_panel_v2(panel),
        )
    except discord.HTTPException:
        if interaction.response.is_done():
            await interaction.followup.send(view=as_panel_v2(panel), ephemeral=True)
        else:
            await interaction.response.send_message(view=as_panel_v2(panel), ephemeral=True)

async def edit_interaction_message(interaction: discord.Interaction, **kwargs):
    """未応答なら初回応答で、defer済みなら元の応答を編集する。"""
    if interaction.response.is_done():
        return await interaction.edit_original_response(**kwargs)
    return await interaction.response.edit_message(**kwargs)


async def report_callback_error(interaction: discord.Interaction, context: str):
    """コールバック例外をログに残し、可能ならユーザーにも通知する。"""
    logger.exception("%s", context)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                "処理中にエラーが発生しました。Botのログを確認してください。",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "処理中にエラーが発生しました。Botのログを確認してください。",
                ephemeral=True,
            )
    except discord.HTTPException:
        logger.exception("コールバックのエラー通知にも失敗しました: %s", context)


SUPPORT_ACTIONS = [
    app_commands.Choice(name="Muted設定", value="muted"),
    app_commands.Choice(name="匿名つぶやきパネル", value="whisper"),
    app_commands.Choice(name="Stickyパネル", value="sticky"),
    app_commands.Choice(name="メッセージ削除", value="clear"),
    app_commands.Choice(name="一括ロール付与・剥奪", value="role_bulk"),
    app_commands.Choice(name="bump/up通知・RTA状態", value="bumprta_status"),
    app_commands.Choice(name="bump/up通知・RTAオン", value="bumprta_on"),
    app_commands.Choice(name="bump/up通知・RTAオフ", value="bumprta_off"),
    app_commands.Choice(name="絵文字便乗設定（binjou）", value="binjou"),
    app_commands.Choice(name="抽選（giveaway）", value="giveaway"),
    app_commands.Choice(name="VC入退室履歴", value="vc_log"),
    app_commands.Choice(name="メッセージ編集履歴", value="message_log"),
    app_commands.Choice(name="モデレート履歴（TO/KICK/BAN）", value="moderation_log"),
]

SUPPORT_GENRES = {
    "moderation": ("モデレーション", "Muted、匿名つぶやき、Stickyパネル、メッセージ削除、モデレート履歴"),
    "server": ("サーバー管理", "ロール操作、絵文字便乗、VC履歴、メッセージ編集履歴"),
    "bumprta": ("bump/up・RTA", "通知設定と RTA 状態・ランキング"),
    "event": ("イベント", "抽選の作成"),
}
SUPPORT_ACTIONS_BY_GENRE = {
    "moderation": [(c.name, c.value) for c in (SUPPORT_ACTIONS[0], SUPPORT_ACTIONS[1], SUPPORT_ACTIONS[2], SUPPORT_ACTIONS[3], SUPPORT_ACTIONS[12])],
    "server": [(c.name, c.value) for c in (SUPPORT_ACTIONS[4], SUPPORT_ACTIONS[8], SUPPORT_ACTIONS[10], SUPPORT_ACTIONS[11])],
    "bumprta": [(c.name, c.value) for c in SUPPORT_ACTIONS[5:8]],
    "event": [(SUPPORT_ACTIONS[9].name, SUPPORT_ACTIONS[9].value)],
}

THINKING_SECTION = "thinking_reaction"
BINJOU_SECTION = "binjou"
VC_LOG_SECTION = "vc_log"
MESSAGE_LOG_SECTION = "message_log"
MODERATION_LOG_SECTION = "moderation_log"
STICKY_SECTION = "sticky"
THINKING_EMOJI = discord.PartialEmoji(name="thinking", id=1561695212814995596)
BINJOU_DEFAULTS = {"thinking": True, "thumbsup": True}


def get_sticky_settings(store, guild_id: int) -> dict[str, int | str | bool | None]:
    """Stickyパネル設定。未設定時はオフ・送信先なし・文言なし。"""
    raw = store.get(guild_id, STICKY_SECTION)
    if not isinstance(raw, dict):
        raw = {}
    channel_id = raw.get("channel_id")
    if not isinstance(channel_id, int) or isinstance(channel_id, bool):
        channel_id = None
    message_id = raw.get("message_id")
    if not isinstance(message_id, int) or isinstance(message_id, bool):
        message_id = None
    enabled = raw.get("enabled") if isinstance(raw.get("enabled"), bool) else False
    content = raw.get("content") if isinstance(raw.get("content"), str) else ""
    return {"enabled": enabled, "channel_id": channel_id, "message_id": message_id, "content": content}


def self_clip(value, limit=1024):
    text = str(value or "(内容なし)")
    return text if len(text) <= limit else text[:limit - 1] + "…"


def mention_with_id(user) -> str:
    if user is None:
        return "不明"
    mention = getattr(user, "mention", None) or getattr(user, "name", None) or str(user)
    return f"{mention} (`{getattr(user, 'id', '不明')}`)"


def get_vc_log_settings(store, guild_id: int) -> dict[str, int | bool | None]:
    """VC入退室ログ設定。未設定時はオフ・送信先なし。"""
    raw = store.get(guild_id, VC_LOG_SECTION)
    if not isinstance(raw, dict):
        raw = {}
    enabled = raw.get("enabled") if isinstance(raw.get("enabled"), bool) else False
    channel_id = raw.get("channel_id")
    if not isinstance(channel_id, int) or isinstance(channel_id, bool):
        channel_id = None
    return {"enabled": enabled, "channel_id": channel_id}


def vc_log_embed(member: discord.Member, channel: discord.VoiceChannel, joined: bool) -> discord.Embed:
    action = "入室しました" if joined else "退室しました"
    embed = discord.Embed(
        title="VC入室" if joined else "VC退室",
        description=(
            f"{member.mention} が **{discord.utils.escape_markdown(channel.name)}** "
            f"{'に' if joined else 'から'}{action}。"
        ),
        color=0x2ECC71 if joined else 0xE74C3C,
        timestamp=discord.utils.utcnow(),
    )
    avatar = getattr(member, "display_avatar", None)
    if avatar is not None:
        embed.set_author(name=member.display_name, icon_url=avatar.url)
    return embed


def get_activity_log_settings(store, guild_id: int, section: str) -> dict[str, int | bool | None]:
    """メッセージ・モデレート履歴の共通設定を返す。未設定時はオフ。"""
    raw = store.get(guild_id, section)
    if not isinstance(raw, dict):
        raw = {}
    enabled = raw.get("enabled") if isinstance(raw.get("enabled"), bool) else False
    channel_id = raw.get("channel_id")
    if not isinstance(channel_id, int) or isinstance(channel_id, bool):
        channel_id = None
    settings = {"enabled": enabled, "channel_id": channel_id}
    if section == MODERATION_LOG_SECTION:
        for action in ("timeout", "kick", "ban"):
            key = f"{action}_enabled"
            settings[key] = raw.get(key) if isinstance(raw.get(key), bool) else False
    return settings


class ActivityLogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, parent: "ActivityLogSettingsView"):
        self.parent_view = parent
        super().__init__(
            placeholder="履歴を送るテキストチャンネルを選択",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if not self.parent_view.can_manage(interaction):
            return await interaction.response.send_message("この設定にはサーバー管理権限が必要です。", ephemeral=True)
        await interaction.response.defer()
        try:
            channel = self.values[0]
            await guild_settings.get_store().update(
                interaction.guild_id, self.parent_view.section, channel_id=channel.id
            )
            await self.parent_view.refresh(interaction, "送信先を設定しました。")
        except Exception:
            logger.exception("履歴送信先の更新に失敗しました")
            await interaction.followup.send(
                "送信先の更新に失敗しました。Botのログを確認してください。", ephemeral=True
            )


class ModerationActionToggle(discord.ui.Button):
    def __init__(self, parent: "ActivityLogSettingsView", action: str, label: str, row: int = 2):
        self.parent_view, self.action, self.action_label = parent, action, label
        super().__init__(label=self.button_label(), style=discord.ButtonStyle.secondary, row=row)

    def button_label(self) -> str:
        enabled = self.parent_view.settings.get(f"{self.action}_enabled", False)
        next_state = "オフにする" if enabled else "オンにする"
        return f"{self.action_label}履歴を{next_state}"

    async def callback(self, interaction: discord.Interaction):
        await self.parent_view.toggle_action(interaction, self.action)


class ActivityLogSettingsView(discord.ui.View):
    def __init__(self, cog: "SupportCog", section: str, title: str, description: str, settings: dict):
        super().__init__(timeout=300)
        self.cog, self.section, self.title, self.log_description = cog, section, title, description
        self.settings = settings
        self.add_item(ActivityLogChannelSelect(self))
        if section == MODERATION_LOG_SECTION:
            self.add_item(ModerationActionToggle(self, "timeout", "TO"))
            self.add_item(ModerationActionToggle(self, "kick", "KICK"))
            self.add_item(ModerationActionToggle(self, "ban", "BAN"))

    @staticmethod
    def can_manage(interaction: discord.Interaction) -> bool:
        permissions = getattr(interaction.user, "guild_permissions", None)
        return bool(getattr(permissions, "manage_guild", False) or getattr(permissions, "administrator", False))

    def embed(self, notice: str | None = None) -> discord.Embed:
        channel_id = self.settings.get("channel_id")
        channel_label = f"<#{channel_id}>" if channel_id else "未設定"
        description = f"状態: **{'オン' if self.settings['enabled'] else 'オフ'}**\n送信先: {channel_label}"
        if notice:
            description = f"{notice}\n\n{description}"
        description += f"\n\n{self.log_description}"
        if self.section == MODERATION_LOG_SECTION:
            description += (
                "\n\n個別設定: "
                f"TO {'オン' if self.settings['timeout_enabled'] else 'オフ'} / "
                f"KICK {'オン' if self.settings['kick_enabled'] else 'オフ'} / "
                f"BAN {'オン' if self.settings['ban_enabled'] else 'オフ'}"
            )
        return discord.Embed(title=self.title, description=description, color=0x3498DB)

    async def refresh(self, interaction: discord.Interaction, notice: str | None = None):
        self.settings = get_activity_log_settings(guild_settings.get_store(), interaction.guild_id, self.section)
        for item in self.children:
            if isinstance(item, ModerationActionToggle):
                item.label = item.button_label()
        await edit_interaction_message(interaction, embed=self.embed(notice), view=self)

    async def set_enabled(self, interaction: discord.Interaction, enabled: bool):
        if not self.can_manage(interaction):
            return await interaction.response.send_message("この設定にはサーバー管理権限が必要です。", ephemeral=True)
        if enabled and self.settings.get("channel_id") is None:
            return await interaction.response.send_message("先に履歴を送るテキストチャンネルを選択してください。", ephemeral=True)
        await interaction.response.defer()
        try:
            await guild_settings.get_store().update(interaction.guild_id, self.section, enabled=enabled)
            await self.refresh(interaction, f"履歴を{'オン' if enabled else 'オフ'}にしました。")
        except Exception:
            logger.exception("履歴設定の更新に失敗しました (section=%s)", self.section)
            await interaction.followup.send("設定の更新に失敗しました。Botのログを確認してください。", ephemeral=True)

    async def toggle_action(self, interaction: discord.Interaction, action: str):
        if not self.can_manage(interaction):
            return await interaction.response.send_message("この設定にはサーバー管理権限が必要です。", ephemeral=True)
        key = f"{action}_enabled"
        enabled = not self.settings.get(key, False)
        await interaction.response.defer()
        try:
            await guild_settings.get_store().update(interaction.guild_id, self.section, **{key: enabled})
            await self.refresh(interaction, f"{action.upper()}履歴を{'オン' if enabled else 'オフ'}にしました。")
        except Exception:
            logger.exception("個別モデレート履歴設定の更新に失敗しました (action=%s)", action)
            await interaction.followup.send("設定の更新に失敗しました。Botのログを確認してください。", ephemeral=True)

    @discord.ui.button(label="履歴をオンにする", style=discord.ButtonStyle.success, row=1)
    async def turn_on(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_enabled(interaction, True)

    @discord.ui.button(label="履歴をオフにする", style=discord.ButtonStyle.secondary, row=1)
    async def turn_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_enabled(interaction, False)


class VCLogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, parent: "VCLogSettingsView"):
        self.parent_view = parent
        super().__init__(
            placeholder="履歴を送るテキストチャンネルを選択",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if not self.parent_view.can_manage(interaction):
            return await interaction.response.send_message("この設定にはサーバー管理権限が必要です。", ephemeral=True)
        await interaction.response.defer()
        try:
            channel = self.values[0]
            await guild_settings.get_store().update(interaction.guild_id, VC_LOG_SECTION, channel_id=channel.id)
            await self.parent_view.refresh(interaction, "送信先を設定しました。")
        except Exception:
            logger.exception("VC履歴送信先の更新に失敗しました")
            await interaction.followup.send(
                "送信先の更新に失敗しました。Botのログを確認してください。", ephemeral=True
            )


class VCLogSettingsView(discord.ui.View):
    def __init__(self, cog: "SupportCog", settings: dict):
        super().__init__(timeout=300)
        self.cog = cog
        self.settings = settings
        self.add_item(VCLogChannelSelect(self))

    @staticmethod
    def can_manage(interaction: discord.Interaction) -> bool:
        return bool(getattr(getattr(interaction.user, "guild_permissions", None), "manage_guild", False))

    def embed(self, notice: str | None = None) -> discord.Embed:
        channel_id = self.settings.get("channel_id")
        channel_label = f"<#{channel_id}>" if channel_id else "未設定"
        description = f"状態: **{'オン' if self.settings['enabled'] else 'オフ'}**\n送信先: {channel_label}"
        if notice:
            description = f"{notice}\n\n{description}"
        description += "\n\nVC入室・退出・VC間の移動を記録します。"
        return discord.Embed(title="VC入退室履歴の設定", description=description, color=0x3498DB)

    async def refresh(self, interaction: discord.Interaction, notice: str | None = None):
        self.settings = get_vc_log_settings(guild_settings.get_store(), interaction.guild_id)
        await edit_interaction_message(interaction, embed=self.embed(notice), view=self)

    async def set_enabled(self, interaction: discord.Interaction, enabled: bool):
        if not self.can_manage(interaction):
            return await interaction.response.send_message("この設定にはサーバー管理権限が必要です。", ephemeral=True)
        if enabled and self.settings.get("channel_id") is None:
            return await interaction.response.send_message("先に履歴を送るテキストチャンネルを選択してください。", ephemeral=True)
        await interaction.response.defer()
        try:
            await guild_settings.get_store().update(interaction.guild_id, VC_LOG_SECTION, enabled=enabled)
            await self.refresh(interaction, f"履歴を{'オン' if enabled else 'オフ'}にしました。")
        except Exception:
            logger.exception("VC履歴設定の更新に失敗しました")
            await interaction.followup.send("設定の更新に失敗しました。Botのログを確認してください。", ephemeral=True)

    @discord.ui.button(label="オン", style=discord.ButtonStyle.success, row=1)
    async def turn_on(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_enabled(interaction, True)

    @discord.ui.button(label="オフ", style=discord.ButtonStyle.secondary, row=1)
    async def turn_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_enabled(interaction, False)


class StickyChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, parent: "StickySettingsView"):
        self.parent_view = parent
        super().__init__(
            placeholder="Stickyパネルを置くテキストチャンネルを選択",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if not self.parent_view.can_manage(interaction):
            return await interaction.response.send_message(
                "この設定にはサーバー管理権限が必要です。", ephemeral=True
            )

        await interaction.response.defer()
        try:
            channel = self.values[0]
            old_channel_id = self.parent_view.settings.get("channel_id")
            old_message_id = self.parent_view.settings.get("message_id")
            if old_channel_id and old_message_id and old_channel_id != channel.id:
                old_channel = await self.parent_view.cog._sticky_channel(interaction.guild, old_channel_id)
                if old_channel is not None:
                    try:
                        await (await old_channel.fetch_message(old_message_id)).delete()
                    except discord.NotFound:
                        pass
                    except (discord.Forbidden, discord.HTTPException):
                        logger.warning(
                            "旧Stickyパネルを削除できません (guild=%s message=%s)",
                            interaction.guild_id, old_message_id,
                        )
            await guild_settings.get_store().update(
                interaction.guild_id, STICKY_SECTION, channel_id=channel.id, message_id=None,
            )
            self.parent_view.settings["channel_id"] = channel.id
            self.parent_view.settings["message_id"] = None
            await self.parent_view.refresh(interaction, "Stickyパネルの設置先を設定しました。")
            if self.parent_view.settings.get("enabled") and self.parent_view.settings.get("content"):
                await self.parent_view.cog.send_sticky_panel(interaction.guild, force=True)
        except Exception:
            logger.exception("Stickyパネル設置先の更新に失敗しました")
            await interaction.followup.send(
                "Stickyパネル設置先の更新に失敗しました。Botのログを確認してください。",
                ephemeral=True,
            )


class StickyTextModal(discord.ui.Modal, title="Stickyパネルの文言"):
    def __init__(self, view: "StickySettingsView"):
        super().__init__()
        self.parent_view = view
        self.text = discord.ui.TextInput(
            label="パネルに表示する文言",
            style=discord.TextStyle.paragraph,
            placeholder="例: お問い合わせはこのチャンネルに送信してください。",
            default=view.settings.get("content", "")[:2000],
            max_length=2000,
            required=True,
        )
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.parent_view.can_manage(interaction):
            return await interaction.response.send_message("この設定にはサーバー管理権限が必要です。", ephemeral=True)
        if self.parent_view.settings.get("channel_id") is None:
            return await interaction.response.send_message("先にStickyパネルを置くチャンネルを選択してください。", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await guild_settings.get_store().update(
                interaction.guild_id, STICKY_SECTION, content=self.text.value, enabled=True,
            )
            self.parent_view.settings["content"] = self.text.value
            self.parent_view.settings["enabled"] = True
            await interaction.edit_original_response(content="文言を保存しました。Stickyパネルを送信しています。")
            await self.parent_view.cog.send_sticky_panel(interaction.guild, force=True)
        except Exception:
            logger.exception("Stickyパネル文言の保存・送信に失敗しました")
            try:
                await interaction.edit_original_response(content="文言の保存またはパネル送信に失敗しました。Botのログを確認してください。")
            except discord.HTTPException:
                logger.exception("Sticky文言保存エラーの通知に失敗しました")


class StickySettingsView(discord.ui.View):
    def __init__(self, cog: "SupportCog", settings: dict):
        super().__init__(timeout=300)
        self.cog = cog
        self.settings = settings
        self.add_item(StickyChannelSelect(self))

    @staticmethod
    def can_manage(interaction: discord.Interaction) -> bool:
        permissions = getattr(interaction.user, "guild_permissions", None)
        return bool(getattr(permissions, "manage_guild", False) or getattr(permissions, "administrator", False))

    def embed(self, notice: str | None = None) -> discord.Embed:
        channel_id = self.settings.get("channel_id")
        channel_label = f"<#{channel_id}>" if channel_id else "未設定"
        content = self.settings.get("content") or "未設定"
        if len(content) > 200:
            content = content[:199] + "…"
        description = (
            f"状態: **{'オン' if self.settings.get('enabled') else 'オフ'}**\n"
            f"設置先: {channel_label}\n文言: {content}\n\n"
            "設置先のチャンネルに誰かが投稿すると、直前のStickyパネルを削除して再送信します。"
        )
        if notice:
            description = f"{notice}\n\n{description}"
        return discord.Embed(title="Stickyパネルの設定", description=description, color=0x3498DB)

    async def refresh(self, interaction: discord.Interaction, notice: str | None = None):
        self.settings = get_sticky_settings(guild_settings.get_store(), interaction.guild_id)
        await edit_interaction_message(interaction, embed=self.embed(notice), view=self)

    async def set_enabled(self, interaction: discord.Interaction, enabled: bool):
        if not self.can_manage(interaction):
            return await interaction.response.send_message("この設定にはサーバー管理権限が必要です。", ephemeral=True)
        if enabled and (self.settings.get("channel_id") is None or not self.settings.get("content")):
            return await interaction.response.send_message("先に設置先と文言を設定してください。", ephemeral=True)
        await interaction.response.defer()
        try:
            await guild_settings.get_store().update(interaction.guild_id, STICKY_SECTION, enabled=enabled)
            self.settings["enabled"] = enabled
            notice = "Stickyパネルをオンにしました。" if enabled else "Stickyパネルをオフにしました。"
            await interaction.edit_original_response(embed=self.embed(notice), view=self)
            if enabled:
                await self.cog.send_sticky_panel(interaction.guild, force=True)
        except Exception:
            logger.exception("Stickyパネル有効状態の更新に失敗しました")
            await interaction.followup.send("Sticky設定の更新に失敗しました。Botのログを確認してください。", ephemeral=True)

    @discord.ui.button(label="文言を設定・更新", style=discord.ButtonStyle.primary, row=1)
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.can_manage(interaction):
            return await interaction.response.send_message("この設定にはサーバー管理権限が必要です。", ephemeral=True)
        await interaction.response.send_modal(StickyTextModal(self))

    @discord.ui.button(label="オン", style=discord.ButtonStyle.success, row=1)
    async def turn_on(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_enabled(interaction, True)

    @discord.ui.button(label="オフ", style=discord.ButtonStyle.secondary, row=1)
    async def turn_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_enabled(interaction, False)


def get_binjou_settings(store, guild_id: int) -> dict[str, bool]:
    """binjou設定を既定値と旧thinking設定で補完する。"""
    raw = store.get(guild_id, BINJOU_SECTION)
    old_thinking = store.get(guild_id, THINKING_SECTION).get("enabled")
    thinking = raw.get("thinking")
    if not isinstance(thinking, bool):
        thinking = old_thinking if isinstance(old_thinking, bool) else BINJOU_DEFAULTS["thinking"]
    thumbsup = raw.get("thumbsup")
    if not isinstance(thumbsup, bool):
        thumbsup = BINJOU_DEFAULTS["thumbsup"]
    return {"thinking": thinking, "thumbsup": thumbsup}


class EmojiBinjouView(discord.ui.View):
    def __init__(self, cog: "SupportCog", settings: dict[str, bool]):
        super().__init__(timeout=300)
        self.cog = cog
        self.settings = settings

    async def set_enabled(self, interaction: discord.Interaction, key: str, enabled: bool):
        if not getattr(getattr(interaction.user, "guild_permissions", None), "manage_guild", False):
            return await interaction.response.send_message("この設定にはサーバー管理権限が必要です。", ephemeral=True)
        await interaction.response.defer()
        try:
            await guild_settings.get_store().update(interaction.guild_id, BINJOU_SECTION, **{key: enabled})
            self.settings[key] = enabled
            await interaction.edit_original_response(embed=self.cog.binjou_embed(self.settings), view=self)
        except Exception:
            logger.exception("binjou設定の更新に失敗しました (key=%s)", key)
            await interaction.followup.send("設定の更新に失敗しました。Botのログを確認してください。", ephemeral=True)

    @discord.ui.button(label="<:thinking:1561695212814995596> オン", style=discord.ButtonStyle.success, row=0)
    async def thinking_on(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_enabled(interaction, "thinking", True)

    @discord.ui.button(label="<:thinking:1561695212814995596> オフ", style=discord.ButtonStyle.secondary, row=0)
    async def thinking_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_enabled(interaction, "thinking", False)

    @discord.ui.button(label="👍 オン", style=discord.ButtonStyle.success, row=1)
    async def thumbsup_on(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_enabled(interaction, "thumbsup", True)

    @discord.ui.button(label="👍 オフ", style=discord.ButtonStyle.secondary, row=1)
    async def thumbsup_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_enabled(interaction, "thumbsup", False)


class RoleBulkConfirmView(discord.ui.View):
    def __init__(self, cog: "SupportCog", role: discord.Role, adding: bool, target_mode: str = "humans"):
        super().__init__(timeout=60)
        self.cog = cog
        self.role = role
        self.adding = adding
        self.target_mode = target_mode

    @discord.ui.button(label="実行", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        affected, skipped, failed = await self.cog.bulk_role_update(
            interaction.guild, self.role, self.adding, target_mode=self.target_mode
        )
        action = "付与" if self.adding else "剥奪"
        target_label = {"humans": "人間のみ", "all": "人間＋BOT", "bots": "BOTのみ"}[self.target_mode]
        await interaction.followup.send(
            embed=discord.Embed(
                title=f"ロール一括{action} 完了",
                description=(
                    f"対象ロール: {self.role.mention}\n"
                    f"対象アカウント: **{target_label}**\n"
                    f"{action}: **{affected}人**\n"
                    f"対象外: **{skipped}人**\n"
                    f"失敗: **{failed}人**"
                ),
                color=0x2ECC71 if failed == 0 else 0xE67E22,
            ),
            ephemeral=True,
        )
        self.stop()

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", embed=None, view=None)
        self.stop()


class RoleBulkView(discord.ui.View):
    def __init__(self, cog: "SupportCog", guild: discord.Guild, role: discord.Role | None = None):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.role = role
        self.target_mode = "humans"
        self.add_item(RoleBulkSelect(self))
        self.add_item(RoleTargetSelect(self))

    def description(self) -> str:
        selected = self.role.mention if self.role else "未選択"
        return f"対象ロール: {selected}\n対象アカウント: **{self.target_label()}**\n下のボタンから付与・剥奪を選びます。"

    def target_label(self) -> str:
        return {"humans": "人間のみ", "all": "人間＋BOT", "bots": "BOTのみ"}[self.target_mode]

    def role_error(self) -> str | None:
        """Return a user-facing reason why the selected role cannot be changed."""
        if self.role is None:
            return "先に対象ロールを選択してください。"
        if self.role.is_default():
            return "@everyone ロールは操作できません。"
        if getattr(self.role, "managed", False):
            return "連携サービスが管理するロールは操作できません。"
        me = getattr(self.guild, "me", None)
        permissions = getattr(getattr(me, "guild_permissions", None), "manage_roles", False)
        if me is None or not permissions:
            return "Botに「ロールの管理」権限がありません。"
        if self.role >= me.top_role:
            return "Botより上位、または同順位のロールは操作できません。"
        return None

    async def choose_action(self, interaction: discord.Interaction, adding: bool):
        if error := self.role_error():
            return await interaction.response.send_message(error, ephemeral=True)
        action = "付与" if adding else "剥奪"
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"ロール一括{action}の確認",
                description=(
                    f"{self.role.mention} をサーバーのメンバーに{action}します。\n"
                    f"対象アカウント: **{self.target_label()}**\n"
                    "この操作は取り消せません。"
                ),
                color=0xE74C3C,
            ),
            view=RoleBulkConfirmView(self.cog, self.role, adding, self.target_mode),
            ephemeral=True,
        )

    @discord.ui.button(label="付与", style=discord.ButtonStyle.success, row=2)
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose_action(interaction, True)

    @discord.ui.button(label="剥奪", style=discord.ButtonStyle.danger, row=2)
    async def remove_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose_action(interaction, False)

class RoleTargetSelect(discord.ui.Select):
    def __init__(self, parent: RoleBulkView):
        self.parent_view = parent
        super().__init__(
            placeholder="対象アカウントを選択",
            min_values=1,
            max_values=1,
            row=1,
            options=[
                discord.SelectOption(label="人間のみ", value="humans", default=True),
                discord.SelectOption(label="人間＋BOT", value="all"),
                discord.SelectOption(label="BOTのみ", value="bots"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.target_mode = self.values[0]
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="一括ロール操作",
                description=self.parent_view.description(),
                color=0x3498DB,
            ),
            view=self.parent_view,
        )


class RoleBulkSelect(discord.ui.RoleSelect):
    def __init__(self, parent: RoleBulkView):
        self.parent_view = parent
        super().__init__(placeholder="対象ロールを選択", row=0)

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.role = self.values[0]
        if error := self.parent_view.role_error():
            self.parent_view.role = None
            return await interaction.response.send_message(error, ephemeral=True)
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="一括ロール操作",
                description=self.parent_view.description(),
                color=0x3498DB,
            ),
            view=self.parent_view,
        )


class SupportClearModal(discord.ui.Modal, title="メッセージ削除"):
    amount = discord.ui.TextInput(label=f"削除する件数（1〜{MAX_CLEAR}）", placeholder="例: 10", max_length=3)

    def __init__(self, cog: "SupportCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.amount.value)
        except ValueError:
            return await interaction.response.send_message("件数は整数で入力してください。", ephemeral=True)
        if not 1 <= count <= MAX_CLEAR:
            return await interaction.response.send_message(f"件数は1〜{MAX_CLEAR}で指定してください。", ephemeral=True)
        cog = self.cog.bot.get_cog("ClearCog")
        if cog is None:
            return await self.cog._missing(interaction, "メッセージ削除")
        await cog.clear(interaction, count, None)


class GiveawayModal(discord.ui.Modal, title="抽選を作成"):
    prize = discord.ui.TextInput(label="賞品", max_length=200)
    winners = discord.ui.TextInput(label="当選人数", default="1", max_length=2)
    minutes = discord.ui.TextInput(label="締切までの分数", default="60", max_length=5)
    def __init__(self, cog):
        super().__init__(); self.cog = cog
    async def on_submit(self, interaction):
        if interaction.guild is None or not getattr(interaction.user.guild_permissions, "manage_guild", False):
            return await interaction.response.send_message("抽選の作成にはサーバー管理権限が必要です。", ephemeral=True)
        try:
            winners, minutes = int(self.winners.value), int(self.minutes.value)
        except ValueError:
            return await interaction.response.send_message("当選人数と分数は整数で入力してください。", ephemeral=True)
        giveaway = self.cog.bot.get_cog("GiveawayCog")
        if giveaway is None:
            return await self.cog._missing(interaction, "giveaway")
        await giveaway.giveaway(interaction, self.prize.value, winners, minutes, None, None, 0, None, None)

class SupportGenreSelect(discord.ui.Select):
    def __init__(self, cog: "SupportCog", selected: str | None = None):
        self.cog = cog
        super().__init__(placeholder="ジャンルを選択してください", options=[
            discord.SelectOption(label=label, description=description, value=value, default=value == selected)
            for value, (label, description) in SUPPORT_GENRES.items()
        ], row=0)

    async def callback(self, interaction: discord.Interaction):
        container = self.view
        view: SupportPanelView = getattr(container, "panel", container)

        # Components V2の再構築より先にACKし、3秒の初回応答制限を避ける。
        await interaction.response.defer()
        try:
            view.genre = self.values[0]
            view.action = None
            view.refresh()

            # V2ではLayoutViewを維持して編集する。通常Viewに置き換えない。
            if hasattr(container, "_sync"):
                container._sync()
                await interaction.edit_original_response(view=container)
            else:
                await interaction.edit_original_response(embed=view.embed(), view=view)
        except Exception:
            logger.exception("サポート操作パネルのジャンル更新に失敗しました")
            try:
                await interaction.followup.send(
                    "ジャンルの更新に失敗しました。Botのログを確認してください。",
                    ephemeral=True,
                )
            except discord.HTTPException:
                logger.exception("ジャンル更新エラーの通知にも失敗しました")


class SupportActionSelect(discord.ui.Select):
    def __init__(self, cog: "SupportCog", genre: str):
        self.cog = cog
        super().__init__(placeholder="機能を選択してください", options=[
            discord.SelectOption(label=label, value=value)
            for label, value in SUPPORT_ACTIONS_BY_GENRE[genre]
        ], row=1)

    async def callback(self, interaction: discord.Interaction):
        getattr(self.view, "panel", self.view).action = self.values[0]
        await self.cog.dispatch(interaction, self.values[0])


class SupportPanelView(discord.ui.View):
    def __init__(self, cog: "SupportCog", genre: str | None = None, shortcut_mode: bool = False,
                 shortcut_item: dict | None = None):
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
        self.add_item(SupportGenreSelect(self.cog, self.genre))
        if self.genre:
            self.add_item(SupportActionSelect(self.cog, self.genre))
        if self.shortcut_mode:
            from cogs.general import ShortcutCommitButton
            self.add_item(ShortcutCommitButton())

    def shortcut_action(self):
        if not self.genre or not self.action:
            return None
        return {"root": "support", "genre": self.genre, "value": self.action}

    def embed(self):
        description = "ジャンルを選ぶと、その中の機能を選択できます。"
        if self.genre:
            description = f"**{SUPPORT_GENRES[self.genre][0]}** の機能を選択してください。"
        return discord.Embed(title="サポート操作", description=description, color=0xFFFFFF)


class SupportCog(commands.Cog):
    SUPPORT_REQUIRED_PERMISSIONS = {
        "muted": "manage_roles",
        "whisper": "manage_channels",
        "sticky": "manage_guild",
        "clear": "manage_messages",
        "role_bulk": "manage_roles",
        "binjou": "manage_guild",
        "giveaway": "manage_guild",
        "vc_log": "manage_guild",
        "message_log": "manage_guild",
        "moderation_log": "manage_guild",
    }

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._sticky_locks: dict[int, asyncio.Lock] = {}

    @staticmethod
    def has_support_permission(interaction: discord.Interaction, permission: str) -> bool:
        permissions = getattr(interaction.user, "guild_permissions", None)
        return bool(getattr(permissions, "administrator", False) or getattr(permissions, permission, False))

    async def check_support_permission(self, interaction: discord.Interaction, selected: str) -> bool:
        permission = self.SUPPORT_REQUIRED_PERMISSIONS.get(selected)
        if permission is None or self.has_support_permission(interaction, permission):
            return True
        labels = {
            "manage_guild": "サーバーの管理",
            "manage_roles": "ロールの管理",
            "manage_channels": "チャンネルの管理",
            "manage_messages": "メッセージの管理",
        }
        await interaction.response.send_message(
            f"この機能を使うには「{labels.get(permission, permission)}」権限が必要です。",
            ephemeral=True,
        )
        return False

    async def show_activity_log_settings(
        self, interaction: discord.Interaction, section: str, title: str, description: str
    ):
        if interaction.guild_id is None:
            return await interaction.response.send_message("この設定はサーバー内で利用できます。", ephemeral=True)
        store = guild_settings.get_store()
        await store.ensure_loaded()
        settings = get_activity_log_settings(store, interaction.guild_id, section)
        view = ActivityLogSettingsView(self, section, title, description, settings)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

    async def _activity_target(self, guild: discord.Guild, section: str):
        store = guild_settings.get_store()
        await store.ensure_loaded()
        settings = get_activity_log_settings(store, guild.id, section)
        if not settings["enabled"] or settings["channel_id"] is None:
            return None
        target = self.bot.get_channel(settings["channel_id"])
        if target is None:
            try:
                target = await self.bot.fetch_channel(settings["channel_id"])
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.warning("履歴の送信先を取得できません (guild=%s section=%s)", guild.id, section)
                return None
        if getattr(getattr(target, "guild", None), "id", guild.id) != guild.id:
            logger.warning("履歴の送信先が別サーバーです (guild=%s section=%s)", guild.id, section)
            return None
        return target

    async def _moderation_action_enabled(self, guild: discord.Guild, action: str) -> bool:
        store = guild_settings.get_store()
        await store.ensure_loaded()
        settings = get_activity_log_settings(store, guild.id, MODERATION_LOG_SECTION)
        return bool(settings["enabled"] and settings.get(f"{action}_enabled", False))

    async def _send_activity(self, guild: discord.Guild, section: str, embed: discord.Embed):
        target = await self._activity_target(guild, section)
        if target is None:
            return
        try:
            await target.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("履歴を送信できません (guild=%s section=%s)", guild.id, section)

    @staticmethod
    def _clip(value, limit=1024):
        text = str(value or "(内容なし)")
        return text if len(text) <= limit else text[:limit - 1] + "…"

    @staticmethod
    def message_edit_embed(before: discord.Message, after: discord.Message) -> discord.Embed:
        embed = discord.Embed(title="メッセージ編集", color=0xF1C40F, timestamp=discord.utils.utcnow())
        embed.set_author(name=before.author.display_name, icon_url=before.author.display_avatar.url)
        embed.add_field(name="ユーザー", value=f"{before.author.mention} (`{before.author.id}`)", inline=False)
        embed.add_field(name="チャンネル", value=f"{before.channel.mention} (`{before.channel.id}`)", inline=False)
        embed.add_field(name="編集前", value=self_clip(before.content), inline=False)
        embed.add_field(name="編集後", value=self_clip(after.content), inline=False)
        embed.add_field(name="メッセージ", value=f"[元のメッセージへ]({after.jump_url})", inline=False)
        return embed

    async def _recent_audit_entry(self, guild: discord.Guild, action, target_id: int):
        try:
            async for entry in guild.audit_logs(limit=10, action=action):
                if getattr(getattr(entry, "target", None), "id", None) == target_id:
                    age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                    if -5 <= age <= 60:
                        return entry
        except (discord.Forbidden, discord.HTTPException):
            logger.info("監査ログを取得できません (guild=%s action=%s)", guild.id, action)
        return None

    @staticmethod
    def moderation_embed(title: str, target, entry, detail: str) -> discord.Embed:
        executor = getattr(entry, "user", None) if entry else None
        reason = getattr(entry, "reason", None) if entry else None
        embed = discord.Embed(title=title, color=0xE74C3C, timestamp=discord.utils.utcnow())
        embed.add_field(name="対処したユーザー", value=mention_with_id(executor), inline=True)
        embed.add_field(name="適用されたユーザー", value=mention_with_id(target), inline=True)
        embed.add_field(name="対処詳細", value=SupportCog._clip(detail), inline=False)
        embed.add_field(name="理由", value=SupportCog._clip(reason or "理由なし"), inline=False)
        if executor is not None:
            avatar = getattr(getattr(executor, "display_avatar", None), "url", None)
            embed.set_author(name=getattr(executor, "display_name", str(executor)), icon_url=avatar)
        return embed

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.guild is None or before.author.bot or before.content == after.content:
            return
        await self._send_activity(before.guild, MESSAGE_LOG_SECTION, self.message_edit_embed(before, after))

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # discord.py 2.7 は timed_out_until を使用する。旧版互換のため旧名も見る。
        old_until = getattr(before, "timed_out_until", None)
        if old_until is None:
            old_until = getattr(before, "communication_disabled_until", None)
        new_until = getattr(after, "timed_out_until", None)
        if new_until is None:
            new_until = getattr(after, "communication_disabled_until", None)
        if before.guild is None or old_until == new_until:
            return
        if not await self._moderation_action_enabled(before.guild, "timeout"):
            return
        entry = await self._recent_audit_entry(before.guild, discord.AuditLogAction.member_update, after.id)
        if new_until is not None:
            detail = f"タイムアウト期限: {new_until.isoformat()}"
            title = "タイムアウト（TO）"
        else:
            detail = "タイムアウト解除"
            title = "タイムアウト解除（TO）"
        await self._send_activity(before.guild, MODERATION_LOG_SECTION, self.moderation_embed(title, after, entry, detail))

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.guild is None or member.bot:
            return
        if not await self._moderation_action_enabled(member.guild, "kick"):
            return
        ban_entry = await self._recent_audit_entry(member.guild, discord.AuditLogAction.ban, member.id)
        if ban_entry is not None:
            return
        entry = await self._recent_audit_entry(member.guild, discord.AuditLogAction.kick, member.id)
        if entry is not None:
            await self._send_activity(member.guild, MODERATION_LOG_SECTION, self.moderation_embed("KICK", member, entry, "サーバーからキック"))

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        if not await self._moderation_action_enabled(guild, "ban"):
            return
        entry = await self._recent_audit_entry(guild, discord.AuditLogAction.ban, user.id)
        await self._send_activity(guild, MODERATION_LOG_SECTION, self.moderation_embed("BAN", user, entry, "サーバーからBAN"))

    async def show_vc_log_settings(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            return await interaction.response.send_message("この設定はサーバー内で利用できます。", ephemeral=True)
        store = guild_settings.get_store()
        await store.ensure_loaded()
        settings = get_vc_log_settings(store, interaction.guild_id)
        view = VCLogSettingsView(self, settings)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

    async def show_sticky_settings(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            return await interaction.response.send_message("この設定はサーバー内で利用できます。", ephemeral=True)
        store = guild_settings.get_store()
        await store.ensure_loaded()
        settings = get_sticky_settings(store, interaction.guild_id)
        view = StickySettingsView(self, settings)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

    async def _sticky_channel(self, guild: discord.Guild, channel_id: int):
        target = self.bot.get_channel(channel_id)
        if target is None:
            try:
                target = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.warning("Stickyパネルの送信先を取得できません (guild=%s channel=%s)", guild.id, channel_id)
                return None
        if getattr(getattr(target, "guild", None), "id", guild.id) != guild.id:
            logger.warning("Stickyパネルの送信先が別サーバーです (guild=%s channel=%s)", guild.id, channel_id)
            return None
        return target

    async def send_sticky_panel(self, guild: discord.Guild, *, force: bool = False):
        """現在のStickyパネルを削除して、設定された文言を同じチャンネルへ送る。"""
        store = guild_settings.get_store()
        await store.ensure_loaded()
        settings = get_sticky_settings(store, guild.id)
        if not settings["enabled"] or settings["channel_id"] is None or not settings["content"]:
            return None
        lock = self._sticky_locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            # 競合中に設定が変わっていないか、ロック取得後に読み直す。
            settings = get_sticky_settings(store, guild.id)
            if not settings["enabled"] or settings["channel_id"] is None or not settings["content"]:
                return None
            target = await self._sticky_channel(guild, settings["channel_id"])
            if target is None:
                return None
            old_id = settings.get("message_id")
            if old_id:
                try:
                    old_message = await target.fetch_message(old_id)
                    await old_message.delete()
                except discord.NotFound:
                    pass
                except (discord.Forbidden, discord.HTTPException):
                    logger.warning("Stickyパネルを削除できません (guild=%s message=%s)", guild.id, old_id)
            try:
                panel = await target.send(settings["content"])
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Stickyパネルを送信できません (guild=%s channel=%s)", guild.id, target.id)
                return None
            await store.update(guild.id, STICKY_SECTION, message_id=panel.id)
            return panel

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Botの再送メッセージを無視しないと、Sticky自身が無限に再送される。
        if message.guild is None or getattr(message.author, "bot", False):
            return
        store = guild_settings.get_store()
        await store.ensure_loaded()
        settings = get_sticky_settings(store, message.guild.id)
        if settings["enabled"] and settings["channel_id"] == message.channel.id:
            await self.send_sticky_panel(message.guild)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if member.bot or member.guild is None:
            return
        old_channel = getattr(before, "channel", None)
        new_channel = getattr(after, "channel", None)
        old_id = getattr(old_channel, "id", None)
        new_id = getattr(new_channel, "id", None)
        if old_id == new_id:
            return

        store = guild_settings.get_store()
        await store.ensure_loaded()
        settings = get_vc_log_settings(store, member.guild.id)
        channel_id = settings["channel_id"]
        if not settings["enabled"] or channel_id is None:
            return

        target = self.bot.get_channel(channel_id)
        if target is None:
            try:
                target = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.warning("VC入退室ログの送信先を取得できません (guild=%s channel=%s)", member.guild.id, channel_id)
                return
        if getattr(getattr(target, "guild", None), "id", member.guild.id) != member.guild.id:
            logger.warning("VC入退室ログの送信先が別サーバーです (guild=%s channel=%s)", member.guild.id, channel_id)
            return

        try:
            if old_channel is not None:
                await target.send(embed=vc_log_embed(member, old_channel, joined=False))
            if new_channel is not None:
                await target.send(embed=vc_log_embed(member, new_channel, joined=True))
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("VC入退室ログを送信できません (guild=%s channel=%s)", member.guild.id, channel_id)

    @staticmethod
    def binjou_embed(settings: dict[str, bool]) -> discord.Embed:
        return discord.Embed(
            title="絵文字便乗設定（binjou）",
            description=(
                f"<:thinking:1561695212814995596> → {THINKING_EMOJI}: **{'オン' if settings['thinking'] else 'オフ'}**\n"
                f"👍 → 👍: **{'オン' if settings['thumbsup'] else 'オフ'}**\n\n"
                "各ボタンで個別に切り替えられます。初期設定はどちらもオンです。"
            ),
            color=0x3498DB,
        )

    async def _missing(self, interaction: discord.Interaction, name: str):
        await interaction.response.send_message(
            f"{name}機能が読み込まれていません。", ephemeral=True
        )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == getattr(self.bot.user, "id", None):
            return
        source_emoji = str(payload.emoji)
        if source_emoji not in {"<:thinking:1561695212814995596>", "🤔", "👍", "👍️"}:
            return
        store = guild_settings.get_store()
        await store.ensure_loaded()
        settings = get_binjou_settings(store, payload.guild_id)
        key = "thinking" if source_emoji in {"<:thinking:1561695212814995596>", "🤔"} else "thumbsup"
        if not settings[key]:
            return
        member = getattr(payload, "member", None)
        if member is not None and member.bot:
            return
        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(payload.channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        try:
            message = await channel.fetch_message(payload.message_id)
            mirror_emoji = THINKING_EMOJI if key == "thinking" else "👍"
            if any(str(reaction.emoji) == str(mirror_emoji) and reaction.me for reaction in message.reactions):
                return
            await message.add_reaction(mirror_emoji)
        except discord.HTTPException as exc:
            logger.warning(
                "binjou reaction mirror failed (guild=%s channel=%s message=%s emoji=%s): %s",
                payload.guild_id, payload.channel_id, payload.message_id,
                THINKING_EMOJI if key == "thinking" else "👍", exc,
            )
            return

    async def bulk_role_update(
        self, guild: discord.Guild, role: discord.Role, adding: bool, *, target_mode: str = "humans"
    ):
        """指定した対象モード（人間のみ・人間＋BOT・BOTのみ）へロールを適用する。"""
        me = getattr(guild, "me", None)
        if (
            role is None
            or role.is_default()
            or getattr(role, "managed", False)
            or me is None
            or not getattr(getattr(me, "guild_permissions", None), "manage_roles", False)
            or role >= me.top_role
        ):
            return 0, 0, len(getattr(guild, "members", []))
        if target_mode not in {"humans", "all", "bots"}:
            target_mode = "humans"
        affected = skipped = failed = 0
        for member in guild.members:
            is_bot = bool(getattr(member, "bot", False))
            if (target_mode == "humans" and is_bot) or (target_mode == "bots" and not is_bot):
                skipped += 1
                continue
            has_role = role in getattr(member, "roles", [])
            if (adding and has_role) or (not adding and not has_role):
                skipped += 1
                continue
            try:
                if adding:
                    await member.add_roles(role, reason="/support 一括ロール付与")
                else:
                    await member.remove_roles(role, reason="/support 一括ロール剥奪")
                affected += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1
            except Exception:
                failed += 1
        return affected, skipped, failed

    async def _role_bulk(self, interaction: discord.Interaction, role: discord.Role | None):
        permissions = getattr(interaction.user, "guild_permissions", None)
        if not getattr(permissions, "manage_roles", False) and not getattr(permissions, "administrator", False):
            return await interaction.response.send_message(
                "この操作には「ロールの管理」権限が必要です。", ephemeral=True
            )
        me = interaction.guild.me
        if me is None or not getattr(me.guild_permissions, "manage_roles", False):
            return await interaction.response.send_message(
                "Botに「ロールの管理」権限がありません。", ephemeral=True
            )
        if role is not None and (role.is_default() or getattr(role, "managed", False) or role >= me.top_role):
            return await interaction.response.send_message(
                "Botより上位のロール、または@everyoneは操作できません。", ephemeral=True
            )
        view = RoleBulkView(self, interaction.guild, role)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="一括ロール操作",
                description=view.description(),
                color=0x3498DB,
            ),
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="support", description="サポート機能の操作パネルを表示します")
    @app_commands.guild_only()
    async def support(self, interaction: discord.Interaction):
        view = SupportPanelView(self)
        await interaction.response.send_message(
            view=as_panel_v2(view), ephemeral=True,
        )

    async def dispatch(self, interaction: discord.Interaction, selected: str):
        if not await self.check_support_permission(interaction, selected):
            return
        if selected == "sticky":
            return await self.show_sticky_settings(interaction)
        if selected == "giveaway":
            return await interaction.response.send_modal(GiveawayModal(self))
        if selected == "vc_log":
            return await self.show_vc_log_settings(interaction)
        if selected == "message_log":
            return await self.show_activity_log_settings(
                interaction, MESSAGE_LOG_SECTION, "メッセージ編集履歴の設定",
                "オンにすると、ユーザーのメッセージ編集前後をEmbedで記録します。",
            )
        if selected == "moderation_log":
            return await self.show_activity_log_settings(
                interaction, MODERATION_LOG_SECTION, "モデレート履歴の設定",
                "オンにすると、TO・KICK・BANの実行者、対象者、詳細をEmbedで記録します。",
            )
        if selected == "binjou":
            store = guild_settings.get_store()
            await store.ensure_loaded()
            settings = get_binjou_settings(store, interaction.guild_id)
            return await interaction.response.send_message(
                embed=self.binjou_embed(settings),
                view=EmojiBinjouView(self, settings), ephemeral=True,
            )
        if selected == "role_bulk":
            return await self._role_bulk(interaction, None)
        if selected == "muted":
            cog = self.bot.get_cog("Muted")
            if cog is None:
                return await self._missing(interaction, "Muted")
            return await cog.muted_setting(interaction)
        if selected == "whisper":
            permissions = getattr(interaction, "permissions", None)
            if not getattr(permissions, "manage_channels", False):
                return await interaction.response.send_message("この操作には「チャンネルの管理」権限が必要です。", ephemeral=True)
            cog = self.bot.get_cog("WhisperCog")
            if cog is None:
                return await self._missing(interaction, "匿名つぶやき")
            return await cog.whisper(interaction)
        if selected == "clear":
            return await interaction.response.send_modal(SupportClearModal(self))

        cog = self.bot.get_cog("BumpRta")
        if cog is None:
            return await self._missing(interaction, "bump/up通知・RTA")
        bumprta_action = selected.removeprefix("bumprta_")
        return await cog.bumprta_command(interaction, app_commands.Choice(name=bumprta_action, value=bumprta_action))


async def setup(bot: commands.Bot):
    await bot.add_cog(SupportCog(bot))
