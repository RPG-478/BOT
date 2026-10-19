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
    app_commands.Choice(name="🤔リアクション便乗設定", value="thinking_reaction"),
]

THINKING_SECTION = "thinking_reaction"
THINKING_EMOJI = discord.PartialEmoji(name="thinking", id=1561695212814995596)


class ThinkingReactionView(discord.ui.View):
    def __init__(self, cog: "SupportCog", enabled: bool):
        super().__init__(timeout=300)
        self.cog = cog
        self.enabled = enabled

    async def set_enabled(self, interaction: discord.Interaction, enabled: bool):
        if not getattr(getattr(interaction.user, "guild_permissions", None), "manage_guild", False):
            return await interaction.response.send_message("この設定にはサーバー管理権限が必要です。", ephemeral=True)
        await guild_settings.get_store().update(interaction.guild_id, THINKING_SECTION, enabled=enabled)
        self.enabled = enabled
        label = "オン" if enabled else "オフ"
        await interaction.response.edit_message(
            embed=discord.Embed(title="🤔リアクション便乗", description=f"現在の設定: **{label}**\n🤔へのリアクションに {THINKING_EMOJI} を追加します。", color=0x3498DB),
            view=self,
        )

    @discord.ui.button(label="オン", style=discord.ButtonStyle.success)
    async def enable_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_enabled(interaction, True)

    @discord.ui.button(label="オフ", style=discord.ButtonStyle.secondary)
    async def disable_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_enabled(interaction, False)


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


class SupportActionSelect(discord.ui.Select):
    def __init__(self, cog: "SupportCog"):
        self.cog = cog
        options = [discord.SelectOption(label=c.name, value=c.value) for c in SUPPORT_ACTIONS]
        super().__init__(placeholder="操作を選択してください", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await self.cog.dispatch(interaction, self.values[0])


class SupportPanelView(discord.ui.View):
    def __init__(self, cog: "SupportCog"):
        super().__init__(timeout=300)
        self.add_item(SupportActionSelect(cog))


class SupportCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _missing(self, interaction: discord.Interaction, name: str):
        await interaction.response.send_message(
            f"{name}機能が読み込まれていません。", ephemeral=True
        )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == getattr(self.bot.user, "id", None):
            return
        if str(payload.emoji) != "🤔":
            return
        store = guild_settings.get_store()
        await store.ensure_loaded()
        if not store.get(payload.guild_id, THINKING_SECTION).get("enabled", True):
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
            if any(str(reaction.emoji) == str(THINKING_EMOJI) and reaction.me for reaction in message.reactions):
                return
            await message.add_reaction(THINKING_EMOJI)
        except discord.HTTPException as exc:
            logger.warning(
                "thinking reaction mirror failed (guild=%s channel=%s message=%s emoji=%s): %s",
                payload.guild_id, payload.channel_id, payload.message_id, THINKING_EMOJI, exc,
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
        await interaction.response.send_message(
            embed=discord.Embed(title="サポート操作", description="下のメニューから操作を選択してください。", color=0x3498DB),
            view=SupportPanelView(self), ephemeral=True,
        )

    async def dispatch(self, interaction: discord.Interaction, selected: str):
        if selected == "thinking_reaction":
            store = guild_settings.get_store()
            await store.ensure_loaded()
            enabled = store.get(interaction.guild_id, THINKING_SECTION).get("enabled", True)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title="🤔リアクション便乗",
                    description=f"現在の設定: **{'オン' if enabled else 'オフ'}**\n🤔へのリアクションに {THINKING_EMOJI} を追加します。",
                    color=0x3498DB,
                ),
                view=ThinkingReactionView(self, enabled), ephemeral=True,
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
