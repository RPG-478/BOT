import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone

class Muted(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.admin_roles = {} 
        self.mute_tasks = {}
        self.embed_color = 0xFFFFFF
        self.check_mute_expiry.start()

    def cog_unload(self):
        self.check_mute_expiry.cancel()

    # --- 共通ユーティリティ ---
    async def is_admin_role(self, interaction: discord.Interaction, silent=False) -> bool:
        allowed_role_id = self.admin_roles.get(interaction.guild_id)
        is_admin = interaction.user.guild_permissions.administrator
        has_role = allowed_role_id and any(role.id == allowed_role_id for role in interaction.user.roles)

        if is_admin or has_role:
            return True
        
        if not silent:
            msg = "管理ロールが設定されていないか、実行権限がありません。" if not allowed_role_id else "このコマンドを実行する権限がありません。"
            embed = discord.Embed(description=msg, color=self.embed_color)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        return False

    async def get_or_create_muted_role(self, guild: discord.Guild):
        role = discord.utils.get(guild.roles, name="Muted")
        if role: return role, False
        role = await guild.create_role(name="Muted", reason="Muted管理用自動生成", color=discord.Color.dark_grey())
        return role, True

    @tasks.loop(minutes=1)
    async def check_mute_expiry(self):
        now = datetime.now(timezone.utc)
        expired = []
        for (gid, uid), expire_time in self.mute_tasks.items():
            if now >= expire_time:
                guild = self.bot.get_guild(gid)
                member = guild.get_member(uid) if guild else None
                role = discord.utils.get(guild.roles, name="Muted") if guild else None
                if member and role:
                    try: await member.remove_roles(role)
                    except: pass
                expired.append((gid, uid))
        for item in expired: del self.mute_tasks[item]

    # --- セレクトメニューの定義 ---
    class MuteSettingView(discord.ui.View):
        def __init__(self, cog, admin_only=True):
            super().__init__(timeout=180)
            self.cog = cog

        @discord.ui.select(
            placeholder="実行する操作を選択してください",
            options=[
                discord.SelectOption(label="権限同期 (Link)", value="link", description="全チャンネルを発言不可に設定します"),
                discord.SelectOption(label="非表示切替 (Hide Toggle)", value="hide", description="全チャンネルの表示/非表示を切り替えます"),
                discord.SelectOption(label="管理ロール設定 (Set Admin)", value="admin", description="コマンド行使権限ロールを設定します(管理者のみ)"),
            ]
        )
        async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
            # 管理ロール設定は管理者のみ
            if select.values[0] == "admin" and not interaction.user.guild_permissions.manage_roles:
                return await interaction.response.send_message("ロール管理権限が必要です。", ephemeral=True)
            
            await interaction.response.defer(ephemeral=True)
            role, created = await self.cog.get_or_create_muted_role(interaction.guild)
            embed = discord.Embed(color=self.cog.embed_color)

            if select.values[0] == "link":
                success, error = 0, 0
                for ch in interaction.guild.channels:
                    try:
                        await ch.set_permissions(role, send_messages=False, add_reactions=False, connect=False)
                        success += 1
                    except: error += 1
                embed.title = "権限同期完了"
                embed.description = f"成功: {success} / 失敗: {error}\n発言禁止を全チャンネルに同期しました。"

            elif select.values[0] == "hide":
                first_ch = interaction.guild.text_channels[0]
                should_hide = not (first_ch.overwrites_for(role).view_channel == False)
                for ch in interaction.guild.text_channels:
                    try: await ch.set_permissions(role, view_channel=None if not should_hide else False, send_messages=False)
                    except: continue
                embed.title = "表示設定変更"
                embed.description = "全チャンネルを非表示にしました。" if should_hide else "非表示設定を解除しました(発言不可は維持)。"

            elif select.values[0] == "admin":
                embed.title = "管理ロール設定"
                embed.description = "この操作は `/muted setting` の引数 `admin_role` を指定して直接実行してください。"

            await interaction.followup.send(embed=embed, ephemeral=True)

    # --- メインコマンド ---
    @app_commands.command(name="muted", description="Mutedシステムの総合管理設定")
    @app_commands.describe(
        target="Mutedを付与するメンバー", 
        minutes="付与する時間(分)", 
        admin_role="管理ロールとして設定するロール",
        isolation_channel="隔離先として設定するチャンネル"
    )
    async def muted_setting(
        self, 
        interaction: discord.Interaction, 
        target: discord.Member = None, 
        minutes: int = None, 
        admin_role: discord.Role = None,
        isolation_channel: discord.TextChannel = None
    ):
        # 1. 管理ロールの設定（引数がある場合）
        if admin_role:
            if not interaction.user.guild_permissions.manage_roles:
                return await interaction.response.send_message("ロール管理権限が必要です。", ephemeral=True)
            self.admin_roles[interaction.guild_id] = admin_role.id
            embed = discord.Embed(description=f"管理ロールを {admin_role.mention} に設定しました。", color=self.embed_color)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # 以降、権限チェック
        if not await self.is_admin_role(interaction): return

        # 2. 個別付与 (givetime) の処理（ターゲットと時間がある場合）
        if target and minutes:
            role, created = await self.get_or_create_muted_role(interaction.guild)
            await target.add_roles(role)
            self.mute_tasks[(interaction.guild_id, target.id)] = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            embed = discord.Embed(title="Muted付与", description=f"{target.display_name} を {minutes}分間 Mutedにしました。", color=self.embed_color)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # 3. 隔離設定の処理（隔離チャンネル指定がある場合）
        if isolation_channel:
            await interaction.response.defer(ephemeral=True)
            role, _ = await self.get_or_create_muted_role(interaction.guild)
            for ch in interaction.guild.text_channels:
                try:
                    is_target = (ch.id == isolation_channel.id)
                    await ch.set_permissions(role, view_channel=is_target, send_messages=is_target)
                except: continue
            embed = discord.Embed(description=f"{isolation_channel.mention} 以外を非表示にしました。", color=self.embed_color)
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # 4. それ以外（引数なし）の場合はセレクトメニューを表示
        embed = discord.Embed(
            title="Muted システム設定",
            description="実行したいメニューを選択してください。このメッセージはあなたにのみ表示されます。",
            color=self.embed_color
        )
        await interaction.response.send_message(embed=embed, view=self.MuteSettingView(self), ephemeral=True)

async def setup(bot):
    await bot.add_cog(Muted(bot))