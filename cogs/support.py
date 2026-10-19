"""サポート系機能を /support に統合する入口。"""
from __future__ import annotations
import logging
import discord
from discord import app_commands
from discord.ext import commands

from cogs.clear import MAX_CLEAR
from core import guild_settings
logger = logging.getLogger(__name__)


SUPPORT_ACTIONS = [
    app_commands.Choice(name="Muted設定", value="muted"),
    app_commands.Choice(name="匿名つぶやきパネル", value="whisper"),
    app_commands.Choice(name="メッセージ削除", value="clear"),
    app_commands.Choice(name="一括ロール付与・剥奪", value="role_bulk"),
    app_commands.Choice(name="bump/up通知・RTA状態", value="bumprta_status"),
    app_commands.Choice(name="bump/up通知・RTAオン", value="bumprta_on"),
    app_commands.Choice(name="bump/up通知・RTAオフ", value="bumprta_off"),
    app_commands.Choice(name="絵文字便乗設定（binjou）", value="binjou"),
    app_commands.Choice(name="抽選（giveaway）", value="giveaway"),
    app_commands.Choice(name="VC入退室履歴", value="vc_log"),
]

SUPPORT_GENRES = {
    "moderation": ("モデレーション", "Muted、匿名つぶやき、メッセージ削除"),
    "server": ("サーバー管理", "ロール操作、絵文字便乗、VC履歴"),
    "bumprta": ("bump/up・RTA", "通知設定と RTA 状態・ランキング"),
    "event": ("イベント", "抽選の作成"),
}
SUPPORT_ACTIONS_BY_GENRE = {
    "moderation": [(c.name, c.value) for c in SUPPORT_ACTIONS[:3]],
    "server": [(c.name, c.value) for c in (SUPPORT_ACTIONS[3], SUPPORT_ACTIONS[7], SUPPORT_ACTIONS[9])],
    "bumprta": [(c.name, c.value) for c in SUPPORT_ACTIONS[4:7]],
    "event": [(SUPPORT_ACTIONS[8].name, SUPPORT_ACTIONS[8].value)],
}

THINKING_SECTION = "thinking_reaction"
BINJOU_SECTION = "binjou"
VC_LOG_SECTION = "vc_log"
THINKING_EMOJI = discord.PartialEmoji(name="thinking", id=1561695212814995596)
BINJOU_DEFAULTS = {"thinking": True, "thumbsup": True}


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
    action = "入りました" if joined else "退出しました"
    embed = discord.Embed(
        title="VC入室" if joined else "VC退出",
        description=f"{member.mention} が **{discord.utils.escape_markdown(channel.name)}** に{action}。",
        color=0x2ECC71 if joined else 0xE74C3C,
        timestamp=discord.utils.utcnow(),
    )
    avatar = getattr(member, "display_avatar", None)
    if avatar is not None:
        embed.set_author(name=member.display_name, icon_url=avatar.url)
    return embed


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
        channel = self.values[0]
        await guild_settings.get_store().update(interaction.guild_id, VC_LOG_SECTION, channel_id=channel.id)
        await self.parent_view.refresh(interaction, "送信先を設定しました。")


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
        description += "\n\nオンにすると、VC入室・退出・VC間の移動を記録します。初期状態はオフです。"
        return discord.Embed(title="VC入退室履歴の設定", description=description, color=0x3498DB)

    async def refresh(self, interaction: discord.Interaction, notice: str | None = None):
        self.settings = get_vc_log_settings(guild_settings.get_store(), interaction.guild_id)
        await interaction.response.edit_message(embed=self.embed(notice), view=self)

    async def set_enabled(self, interaction: discord.Interaction, enabled: bool):
        if not self.can_manage(interaction):
            return await interaction.response.send_message("この設定にはサーバー管理権限が必要です。", ephemeral=True)
        if enabled and self.settings.get("channel_id") is None:
            return await interaction.response.send_message("先に履歴を送るテキストチャンネルを選択してください。", ephemeral=True)
        await guild_settings.get_store().update(interaction.guild_id, VC_LOG_SECTION, enabled=enabled)
        await self.refresh(interaction, f"履歴を{'オン' if enabled else 'オフ'}にしました。")

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
        await guild_settings.get_store().update(interaction.guild_id, BINJOU_SECTION, **{key: enabled})
        self.settings[key] = enabled
        await interaction.response.edit_message(embed=self.cog.binjou_embed(self.settings), view=self)

    @discord.ui.button(label="🤔 オン", style=discord.ButtonStyle.success, row=0)
    async def thinking_on(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_enabled(interaction, "thinking", True)

    @discord.ui.button(label="🤔 オフ", style=discord.ButtonStyle.secondary, row=0)
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

    async def choose_action(self, interaction: discord.Interaction, adding: bool):
        if self.role is None:
            return await interaction.response.send_message("先に対象ロールを選択してください。", ephemeral=True)
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
        view: SupportPanelView = self.view
        view.genre = self.values[0]
        view.refresh()
        await interaction.response.edit_message(embed=view.embed(), view=view)


class SupportActionSelect(discord.ui.Select):
    def __init__(self, cog: "SupportCog", genre: str):
        self.cog = cog
        super().__init__(placeholder="機能を選択してください", options=[
            discord.SelectOption(label=label, value=value)
            for label, value in SUPPORT_ACTIONS_BY_GENRE[genre]
        ], row=1)

    async def callback(self, interaction: discord.Interaction):
        await self.cog.dispatch(interaction, self.values[0])


class SupportPanelView(discord.ui.View):
    def __init__(self, cog: "SupportCog", genre: str | None = None):
        super().__init__(timeout=300)
        self.cog = cog
        self.genre = genre
        self.refresh()

    def refresh(self):
        self.clear_items()
        self.add_item(SupportGenreSelect(self.cog, self.genre))
        if self.genre:
            self.add_item(SupportActionSelect(self.cog, self.genre))

    def embed(self):
        description = "ジャンルを選ぶと、その中の機能を選択できます。"
        if self.genre:
            description = f"**{SUPPORT_GENRES[self.genre][0]}** の機能を選択してください。"
        return discord.Embed(title="サポート操作", description=description, color=0x3498DB)


class SupportCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def show_vc_log_settings(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            return await interaction.response.send_message("この設定はサーバー内で利用できます。", ephemeral=True)
        store = guild_settings.get_store()
        await store.ensure_loaded()
        settings = get_vc_log_settings(store, interaction.guild_id)
        view = VCLogSettingsView(self, settings)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

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
                f"🤔 → {THINKING_EMOJI}: **{'オン' if settings['thinking'] else 'オフ'}**\n"
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
        if source_emoji not in {"🤔", "👍", "👍️"}:
            return
        store = guild_settings.get_store()
        await store.ensure_loaded()
        settings = get_binjou_settings(store, payload.guild_id)
        key = "thinking" if source_emoji == "🤔" else "thumbsup"
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
        if role is not None and (role.is_default() or role >= me.top_role):
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
            embed=view.embed(), view=view, ephemeral=True,
        )

    async def dispatch(self, interaction: discord.Interaction, selected: str):
        if selected == "giveaway":
            return await interaction.response.send_modal(GiveawayModal(self))
        if selected == "vc_log":
            return await self.show_vc_log_settings(interaction)
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
