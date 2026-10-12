"""サーバーに入ったときのあいさつと、管理者向けの初期設定ウィザード（/setup）。

/setup は 1 ステップずつ設定する（どのステップも飛ばせる。もう一度実行すると今の設定が表示される）。
  1. 認証: 付けるロール・自己紹介チャンネル・フォームの有効/無効（cogs/auth.py が使う）
  2. グローバルチャット: このチャンネルをつなぐ / 外す（cogs/globalchat.py の保存先をそのまま使う）
  3. ミュート管理ロール: muted.py が設定を保存できる場合だけ表示する
  4. 国づくり: 参加する/しない・お知らせチャンネル・通知の量（core.guild_settings.nation_settings で読める）
  5. まとめ: 設定内容と、機能ごとに Bot に足りない権限
設定は core/guild_settings.py（Supabase の bot_kv。使えないときはローカルの JSON）に保存する。
"""
from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.command_catalog import permission_label
from core.guild_settings import NATION_SECTION, NOTIFY_ALL, NOTIFY_LEVELS, NOTIFY_MAJOR, get_store, nation_settings

logger = logging.getLogger(__name__)

EMBED_COLOR = 0x5865F2


# ---------------------------------------------------------------- あいさつ
def can_post(channel, me) -> bool:
    if channel is None or me is None:
        return False
    perms = channel.permissions_for(me)
    return bool(perms.view_channel and perms.send_messages and perms.embed_links)


def pick_welcome_channel(guild):
    """システムチャンネル → 上から順のテキストチャンネルのうち、Bot が書き込める最初のもの。なければ None。"""
    me = getattr(guild, "me", None)
    system = getattr(guild, "system_channel", None)
    if can_post(system, me):
        return system
    for channel in sorted(getattr(guild, "text_channels", []), key=lambda c: (getattr(c, "position", 0), c.id)):
        if can_post(channel, me):
            return channel
    return None


def welcome_embed(bot_name: str = "AGOBOT") -> discord.Embed:
    embed = discord.Embed(
        title=f"👋 {bot_name} を追加してくれてありがとう！",
        description=(
            "ゲーム・音楽・録音・グローバルチャットなど、サーバーをにぎやかにする Bot です。\n\n"
            "📖 `/help` … できることの一覧と使い方\n"
            "🎮 `/game` … みんなで遊べるゲーム\n"
            "🛠️ `/setup` … 管理者向けの初期設定（認証・グローバルチャット・権限の確認）"
        ),
        color=EMBED_COLOR,
    )
    return embed


# ---------------------------------------------------------------- 権限チェック
def _missing(perms, names) -> list[str]:
    return [name for name in names if not getattr(perms, name, False)]


def check_permissions(guild, channel, *, auth: dict, global_channel_ids=(), mute_supported: bool = True,
                      nation: Optional[dict] = None) -> list[dict]:
    """機能ごとに、Bot に足りない権限を調べる。

    戻り値: [{"label": 機能名, "missing": [権限名(日本語)], "notes": [補足], "skipped": 未設定で確認しなかったか}]
    """
    me = guild.me
    guild_perms = me.guild_permissions
    results = []

    def add(label, missing=(), notes=(), skipped=False):
        results.append({
            "label": label,
            "missing": [permission_label(name) for name in missing],
            "notes": list(notes),
            "skipped": skipped,
        })

    # 基本（このチャンネル）
    add("基本（このチャンネル）", _missing(channel.permissions_for(me), ["view_channel", "send_messages", "embed_links"]))

    # 認証
    role = guild.get_role(auth["role_id"]) if auth.get("role_id") else None
    if not auth.get("enabled", True):
        add("認証", skipped=True, notes=["フォームは停止中です"])
    elif role is None:
        add("認証", skipped=True, notes=["付けるロールが未設定です"])
    else:
        missing = _missing(guild_perms, ["manage_roles"])
        notes = []
        if role >= me.top_role:
            notes.append(f"Bot のロールを「{role.name}」より上に移動してください")
        intro = guild.get_channel(auth["intro_channel_id"]) if auth.get("intro_channel_id") else None
        if intro is None:
            notes.append("自己紹介チャンネルが未設定です（自己紹介は投稿されません）")
        else:
            for name in _missing(intro.permissions_for(me), ["view_channel", "manage_webhooks"]):
                if name not in missing:
                    missing.append(name)
        add("認証", missing, notes)

    # グローバルチャット
    channels = [c for c in (guild.get_channel(cid) for cid in global_channel_ids) if c is not None]
    if not channels:
        add("グローバルチャット", skipped=True, notes=["つないでいるチャンネルはありません"])
    else:
        missing = []
        for c in channels:
            for name in _missing(c.permissions_for(me), ["view_channel", "manage_webhooks", "add_reactions"]):
                if name not in missing:
                    missing.append(name)
        add("グローバルチャット", missing)

    # ミュート
    if mute_supported:
        add("ミュート（/muted）", _missing(guild_perms, ["manage_roles", "manage_channels"]))

    # 国づくり
    if nation is not None:
        target = guild.get_channel(nation["channel_id"]) if nation.get("channel_id") else None
        if not nation.get("enabled", True):
            add("国づくり", skipped=True, notes=["参加していません"])
        elif target is None:
            add("国づくり", skipped=True, notes=["お知らせチャンネルが未設定です"])
        else:
            add("国づくり", _missing(target.permissions_for(me), ["view_channel", "send_messages", "embed_links"]))

    # ボイス
    add("ボイス・音楽", _missing(guild_perms, ["connect", "speak"]))
    return results


def format_permission_report(results: list[dict]) -> str:
    lines = []
    for r in results:
        if r["skipped"]:
            lines.append(f"➖ **{r['label']}**: 確認していません（{'・'.join(r['notes'])}）")
        elif r["missing"] or r["notes"]:
            parts = []
            if r["missing"]:
                parts.append("足りない権限: " + "、".join(r["missing"]))
            parts.extend(r["notes"])
            lines.append(f"❌ **{r['label']}**: " + " / ".join(parts))
        else:
            lines.append(f"✅ **{r['label']}**: OK")
    return "\n".join(lines)


# ---------------------------------------------------------------- ウィザード
class SetupWizard(discord.ui.View):
    def __init__(self, cog: "ServerSetup", guild, channel, user_id: int):
        super().__init__(timeout=600)
        self.cog, self.guild, self.channel, self.user_id = cog, guild, channel, user_id
        self.steps = ["auth", "global"] + (["mute"] if cog.mute_cog() is not None else []) + ["nation", "summary"]
        self.index = 0
        self.build()

    @property
    def step(self) -> str:
        return self.steps[self.index]

    # ---- 状態
    def auth(self) -> dict:
        from cogs.auth import auth_settings
        return auth_settings(self.guild.id)

    def global_channel_ids(self) -> list[int]:
        cog = self.cog.globalchat_cog()
        if cog is None:
            return []
        ids = []
        for cid in cog.active_channels:
            if self.guild.get_channel(cid) is not None:
                ids.append(cid)
        return ids

    def nation(self) -> dict:
        return nation_settings(self.guild.id)

    # ---- 変更（どれもすぐ保存する）
    async def set_nation(self, **values) -> dict:
        return await get_store().update(self.guild.id, NATION_SECTION, **values)

    async def set_auth(self, **values) -> dict:
        return await get_store().update(self.guild.id, "auth", **values)

    def set_global(self, connect: bool) -> bool:
        cog = self.cog.globalchat_cog()
        if cog is None:
            return False
        if connect:
            cog.active_channels.add(self.channel.id)
        else:
            cog.active_channels.discard(self.channel.id)
        cog.save_channels()
        return True

    async def set_mute_role(self, role) -> bool:
        cog = self.cog.mute_cog()
        if cog is None:
            return False
        if role is None:
            cog.admin_roles.pop(self.guild.id, None)
        else:
            cog.admin_roles[self.guild.id] = role.id
        await cog.save(self.guild.id)
        return True

    # ---- 表示
    def _role_text(self, role_id) -> str:
        role = self.guild.get_role(role_id) if role_id else None
        return role.mention if role else "未設定"

    def _channel_text(self, channel_id) -> str:
        channel = self.guild.get_channel(channel_id) if channel_id else None
        return channel.mention if channel else "未設定"

    def embed(self) -> discord.Embed:
        number = f"ステップ {self.index + 1}/{len(self.steps)}"
        if self.step == "auth":
            a = self.auth()
            embed = discord.Embed(title=f"🛠️ 初期設定 {number}: 認証", color=EMBED_COLOR, description=(
                "新しく来た人がフォームに答えると、ロールを付けて自己紹介を投稿します。\n"
                "下のメニューで選ぶとすぐ保存されます。使わないときは「次へ」で飛ばせます。"
            ))
            embed.add_field(name="フォーム", value="有効" if a["enabled"] else "停止中")
            embed.add_field(name="付けるロール", value=self._role_text(a["role_id"]))
            embed.add_field(name="自己紹介チャンネル", value=self._channel_text(a["intro_channel_id"]))
        elif self.step == "global":
            cog = self.cog.globalchat_cog()
            connected = cog is not None and self.channel.id in cog.active_channels
            embed = discord.Embed(title=f"🛠️ 初期設定 {number}: グローバルチャット", color=EMBED_COLOR, description=(
                "つないだチャンネルの発言が、ほかのサーバーのつないだチャンネルにも届きます。"
            ))
            if cog is None:
                embed.add_field(name="状態", value="グローバルチャットの機能が読み込まれていません")
            else:
                embed.add_field(name=f"#{getattr(self.channel, 'name', 'このチャンネル')}", value="つないでいます" if connected else "つないでいません")
                others = [cid for cid in self.global_channel_ids() if cid != self.channel.id]
                if others:
                    embed.add_field(name="このサーバーのほかのチャンネル", value=" ".join(f"<#{cid}>" for cid in others))
        elif self.step == "mute":
            cog = self.cog.mute_cog()
            embed = discord.Embed(title=f"🛠️ 初期設定 {number}: ミュート管理ロール", color=EMBED_COLOR, description=(
                "`/muted` でメンバーをミュートできるロールです（サーバー管理者はいつでも使えます）。"
            ))
            embed.add_field(name="管理ロール", value=self._role_text(cog.admin_roles.get(self.guild.id) if cog else None))
        elif self.step == "nation":
            n = self.nation()
            embed = discord.Embed(title=f"🛠️ 初期設定 {number}: 国づくり", color=EMBED_COLOR, description=(
                "`/nation` の国づくりゲームに、このサーバーで参加するかと、お知らせの送り先を決めます。"
            ))
            embed.add_field(name="参加", value="する" if n["enabled"] else "しない")
            embed.add_field(name="お知らせチャンネル", value=self._channel_text(n["channel_id"]))
            embed.add_field(name="通知", value=NOTIFY_LEVELS[n["notify"]])
        else:
            a = self.auth()
            embed = discord.Embed(title=f"🛠️ 初期設定 {number}: まとめ", color=EMBED_COLOR)
            embed.add_field(name="認証", value=(
                f"フォーム: {'有効' if a['enabled'] else '停止中'} / ロール: {self._role_text(a['role_id'])} / "
                f"自己紹介: {self._channel_text(a['intro_channel_id'])}"
            ), inline=False)
            ids = self.global_channel_ids()
            embed.add_field(name="グローバルチャット", value=" ".join(f"<#{cid}>" for cid in ids) or "なし", inline=False)
            mute = self.cog.mute_cog()
            if mute is not None:
                embed.add_field(name="ミュート管理ロール", value=self._role_text(mute.admin_roles.get(self.guild.id)), inline=False)
            n = self.nation()
            embed.add_field(name="国づくり", value=(
                f"参加: {'する' if n['enabled'] else 'しない'} / お知らせ: {self._channel_text(n['channel_id'])} / "
                f"通知: {NOTIFY_LEVELS[n['notify']]}"
            ) if n["enabled"] else "参加しない", inline=False)
            report = format_permission_report(self.permission_results())
            embed.add_field(name="Bot の権限チェック", value=report[:1024], inline=False)
            embed.set_footer(text="足りない権限は「サーバー設定 → ロール」で Bot のロールに付けてください。")
        return embed

    def permission_results(self) -> list[dict]:
        return check_permissions(self.guild, self.channel, auth=self.auth(),
                                 global_channel_ids=self.global_channel_ids(),
                                 mute_supported=self.cog.mute_cog() is not None,
                                 nation=self.nation())

    # ---- 部品
    def build(self) -> None:
        self.clear_items()
        if self.step == "auth":
            a = self.auth()
            role = self.guild.get_role(a["role_id"]) if a["role_id"] else None
            role_select = discord.ui.RoleSelect(placeholder="認証で付けるロールを選ぶ", row=0,
                                                default_values=[discord.Object(id=role.id, type=discord.Role)] if role else [])
            role_select.callback = lambda i: self.on_auth_role(i, role_select)
            self.add_item(role_select)
            intro = self.guild.get_channel(a["intro_channel_id"]) if a["intro_channel_id"] else None
            channel_select = discord.ui.ChannelSelect(placeholder="自己紹介を投稿するチャンネルを選ぶ", row=1,
                                                      channel_types=[discord.ChannelType.text],
                                                      default_values=[discord.Object(id=intro.id, type=discord.TextChannel)] if intro else [])
            channel_select.callback = lambda i: self.on_auth_channel(i, channel_select)
            self.add_item(channel_select)
            self._button("フォームを停止する" if a["enabled"] else "フォームを有効にする",
                         discord.ButtonStyle.secondary, self.on_auth_toggle, row=2)
            self._button("このチャンネルに認証パネルを送る", discord.ButtonStyle.success, self.on_send_panel, row=2)
        elif self.step == "global":
            cog = self.cog.globalchat_cog()
            if cog is not None:
                connected = self.channel.id in cog.active_channels
                self._button("このチャンネルを外す" if connected else "このチャンネルをつなぐ",
                             discord.ButtonStyle.danger if connected else discord.ButtonStyle.success,
                             self.on_global_toggle, row=0)
        elif self.step == "mute":
            cog = self.cog.mute_cog()
            current = self.guild.get_role(cog.admin_roles.get(self.guild.id)) if cog and cog.admin_roles.get(self.guild.id) else None
            select = discord.ui.RoleSelect(placeholder="ミュートを管理できるロールを選ぶ", row=0,
                                           default_values=[discord.Object(id=current.id, type=discord.Role)] if current else [])
            select.callback = lambda i: self.on_mute_role(i, select)
            self.add_item(select)
        elif self.step == "nation":
            n = self.nation()
            self._button("参加をやめる" if n["enabled"] else "参加する",
                         discord.ButtonStyle.danger if n["enabled"] else discord.ButtonStyle.success,
                         self.on_nation_toggle, row=0)
            current = self.guild.get_channel(n["channel_id"]) if n["channel_id"] else None
            channel_select = discord.ui.ChannelSelect(placeholder="国づくりのお知らせチャンネルを選ぶ", row=1,
                                                      channel_types=[discord.ChannelType.text],
                                                      default_values=[discord.Object(id=current.id, type=discord.TextChannel)] if current else [])
            channel_select.callback = lambda i: self.on_nation_channel(i, channel_select)
            self.add_item(channel_select)
            for level, label in NOTIFY_LEVELS.items():
                self._button(f"通知: {label}", discord.ButtonStyle.primary if n["notify"] == level else discord.ButtonStyle.secondary,
                             (lambda lv: lambda i: self.on_nation_notify(i, lv))(level), row=2)

        if self.index > 0:
            self._button("戻る", discord.ButtonStyle.secondary, self.on_back, row=4)
        if self.step != "summary":
            self._button("次へ（スキップ）", discord.ButtonStyle.primary, self.on_next, row=4)
        else:
            self._button("完了", discord.ButtonStyle.success, self.on_finish, row=4)

    def _button(self, label, style, handler, row):
        button = discord.ui.Button(label=label, style=style, row=row)
        button.callback = handler
        self.add_item(button)

    async def refresh(self, interaction: discord.Interaction, note: Optional[str] = None) -> None:
        self.build()
        embed = self.embed()
        if note:
            embed.description = f"{note}\n\n{embed.description or ''}".strip()
        await interaction.response.edit_message(embed=embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("この設定画面は `/setup` を実行した人だけが操作できます。", ephemeral=True)
            return False
        return True

    # ---- 操作
    async def on_next(self, interaction):
        self.index = min(self.index + 1, len(self.steps) - 1)
        await self.refresh(interaction)

    async def on_back(self, interaction):
        self.index = max(self.index - 1, 0)
        await self.refresh(interaction)

    async def on_finish(self, interaction):
        self.stop()
        embed = self.embed()
        embed.title = "✅ 初期設定を保存しました"
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_auth_role(self, interaction, select):
        role = select.values[0] if select.values else None
        await self.set_auth(role_id=role.id if role else None)
        await self.refresh(interaction, f"✅ 認証で付けるロールを {role.mention if role else '未設定'} にしました。")

    async def on_auth_channel(self, interaction, select):
        channel = select.values[0] if select.values else None
        await self.set_auth(intro_channel_id=channel.id if channel else None)
        await self.refresh(interaction, f"✅ 自己紹介チャンネルを {channel.mention if channel else '未設定'} にしました。")

    async def on_auth_toggle(self, interaction):
        enabled = not self.auth()["enabled"]
        await self.set_auth(enabled=enabled)
        await self.refresh(interaction, "✅ 認証フォームを有効にしました。" if enabled else "✅ 認証フォームを停止しました。")

    async def on_send_panel(self, interaction):
        from cogs.auth import VerifyView
        if not self.auth()["role_id"]:
            return await self.refresh(interaction, "⚠️ 先に認証で付けるロールを選んでください。")
        embed = discord.Embed(title="サーバー認証", description="下のボタンを押して質問に回答してください。",
                              color=discord.Color.blue())
        try:
            await self.channel.send(embed=embed, view=VerifyView(None))
        except discord.HTTPException:
            return await self.refresh(interaction, "⚠️ このチャンネルに送れませんでした。Bot の権限を確認してください。")
        await self.refresh(interaction, "✅ このチャンネルに認証パネルを送りました。")

    async def on_global_toggle(self, interaction):
        cog = self.cog.globalchat_cog()
        connect = cog is not None and self.channel.id not in cog.active_channels
        self.set_global(connect)
        await self.refresh(interaction, "✅ このチャンネルをグローバルチャットにつなぎました。" if connect
                           else "✅ このチャンネルをグローバルチャットから外しました。")

    async def on_mute_role(self, interaction, select):
        role = select.values[0] if select.values else None
        await self.set_mute_role(role)
        await self.refresh(interaction, f"✅ ミュート管理ロールを {role.mention if role else '未設定'} にしました。")

    async def on_nation_toggle(self, interaction):
        enabled = not self.nation()["enabled"]
        await self.set_nation(enabled=enabled)
        await self.refresh(interaction, "✅ 国づくりに参加します。" if enabled else "✅ 国づくりへの参加をやめました。")

    async def on_nation_channel(self, interaction, select):
        channel = select.values[0] if select.values else None
        await self.set_nation(channel_id=channel.id if channel else None)
        await self.refresh(interaction, f"✅ 国づくりのお知らせチャンネルを {channel.mention if channel else '未設定'} にしました。")

    async def on_nation_notify(self, interaction, level):
        if level not in NOTIFY_LEVELS:
            level = NOTIFY_MAJOR
        await self.set_nation(notify=level)
        await self.refresh(interaction, f"✅ 国づくりの通知を「{NOTIFY_LEVELS[level]}」にしました。")


class ServerSetup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def globalchat_cog(self):
        cog = self.bot.get_cog("GlobalChatCog")
        return cog if cog is not None and hasattr(cog, "active_channels") and hasattr(cog, "save_channels") else None

    def mute_cog(self):
        """muted.py の管理ロール（保存は muted.py 側の save が行う）。"""
        cog = self.bot.get_cog("Muted")
        return cog if cog is not None and hasattr(cog, "admin_roles") and callable(getattr(cog, "save", None)) else None

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        channel = pick_welcome_channel(guild)
        if channel is None:
            logger.info("あいさつを送れるチャンネルがありません: guild=%s", guild.id)
            return
        try:
            await channel.send(embed=welcome_embed(getattr(self.bot.user, "name", None) or "AGOBOT"))
        except discord.HTTPException:
            logger.warning("あいさつを送れませんでした: guild=%s", guild.id, exc_info=True)

    @app_commands.command(name="setup", description="このサーバーでの Bot の初期設定（認証・グローバルチャット・国づくり・権限の確認）")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_command(self, interaction: discord.Interaction):
        await get_store().ensure_loaded()
        view = SetupWizard(self, interaction.guild, interaction.channel, interaction.user.id)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerSetup(bot))
