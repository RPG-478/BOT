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

    async def is_admin_role(self, interaction: discord.Interaction) -> bool:
        allowed_role_id = self.admin_roles.get(interaction.guild_id)
        if interaction.user.guild_permissions.administrator:
            return True
        if allowed_role_id and any(role.id == allowed_role_id for role in interaction.user.roles):
            return True
        
        embed = discord.Embed(description="管理ロールが設定されていないか、権限がありません。管理者による `/muted admin_role:` の設定が必要です。", color=self.embed_color)
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
                if not guild: continue
                member = guild.get_member(uid)
                role = discord.utils.get(guild.roles, name="Muted")
                if member and role:
                    try: await member.remove_roles(role)
                    except: pass
                expired.append((gid, uid))
        for item in expired: del self.mute_tasks[item]

    # --- セレクトメニュー ---
    class MuteSettingView(discord.ui.View):
        def __init__(self, cog):
            super().__init__(timeout=60) # 1分でメニューを無効化
            self.cog = cog

        @discord.ui.select(
            placeholder="操作を選択（一度選択すると終了します）",
            options=[
                discord.SelectOption(label="権限同期", value="link", description="全チャンネルを発言不可に設定"),
                discord.SelectOption(label="非表示切替", value="hide_toggle", description="全チャンネルの表示/非表示を反転"),
            ]
        )
        async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
            await interaction.response.defer(ephemeral=True)
            role, _ = await self.cog.get_or_create_muted_role(interaction.guild)
            embed = discord.Embed(color=self.cog.embed_color)

            if select.values[0] == "link":
                success, error = 0, 0
                for ch in interaction.guild.channels:
                    try:
                        await ch.set_permissions(role, send_messages=False, add_reactions=False, connect=False)
                        success += 1
                    except: error += 1
                embed.description = f"同期完了 (成功: {success} / 失敗: {error})"

            elif select.values[0] == "hide_toggle":
                # 最初のチャンネルの状態を見て、非表示にするか元に戻すか決める
                target_ch = interaction.guild.text_channels[0]
                current_overwrite = target_ch.overwrites_for(role)
                
                # 現在「見えない」設定なら、設定をクリア(None)して見えるようにする
                # 現在「見える」または「未設定」なら、Falseにして見えないようにする
                is_hidden = (current_overwrite.view_channel == False)
                new_view_state = None if is_hidden else False

                for ch in interaction.guild.text_channels:
                    try:
                        await ch.set_permissions(role, view_channel=new_view_state, send_messages=False)
                    except: continue
                
                embed.description = "非表示設定を解除しました。" if is_hidden else "全てのチャンネルを非表示にしました。"

            # 選択されたらメニューを削除して、二度押しできないようにする
            await interaction.edit_original_response(embed=embed, view=None)
            self.stop() # Viewのループを止める

    # --- メインコマンド ---
    @app_commands.command(name="muted", description="Mutedシステム管理")
    @app_commands.describe(target="対象者", minutes="時間(分)", admin_role="管理ロール設定", isolation_channel="隔離先設定")
    async def muted_setting(
        self, 
        interaction: discord.Interaction, 
        target: discord.Member = None, 
        minutes: int = None, 
        admin_role: discord.Role = None,
        isolation_channel: discord.TextChannel = None
    ):
        # 1. 管理ロール設定
        if admin_role:
            if not interaction.user.guild_permissions.manage_roles:
                embed = discord.Embed(description="権限が不足しています。", color=self.embed_color)
                return await interaction.response.send_message(embed=embed, ephemeral=True)
            self.admin_roles[interaction.guild_id] = admin_role.id
            embed = discord.Embed(description=f"管理ロールを {admin_role.mention} に設定しました。", color=self.embed_color)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # 権限チェック
        if not await self.is_admin_role(interaction): return

        # 2. 個別付与 (実行後、再度使うにはコマンドを打ち直す)
        if target and minutes:
            role, _ = await self.get_or_create_muted_role(interaction.guild)
            await target.add_roles(role)
            self.mute_tasks[(interaction.guild_id, target.id)] = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            embed = discord.Embed(description=f"{target.display_name} を {minutes}分間 Mutedにしました。", color=self.embed_color)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # 3. 隔離設定
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

        # 4. 引数なし：メニュー表示（一度使うと消える）
        embed = discord.Embed(title="Muted システム設定", description="メニューを選択してください。一度実行すると終了します。", color=self.embed_color)
        await interaction.response.send_message(embed=embed, view=self.MuteSettingView(self), ephemeral=True)

async def setup(bot):
    await bot.add_cog(Muted(bot))
