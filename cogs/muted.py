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
        # 管理ロールが未設定の場合
        allowed_role_id = self.admin_roles.get(interaction.guild_id)
        if not allowed_role_id and not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                description="管理ロールが設定されていません。管理権限を持つユーザーが `/muted set_admin` を実行して設定を行ってください。",
                color=self.embed_color
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False

        # 権限チェック
        if interaction.user.guild_permissions.administrator:
            return True
        if allowed_role_id and any(role.id == allowed_role_id for role in interaction.user.roles):
            return True
        
        embed = discord.Embed(description="このコマンドを実行する権限がありません。", color=self.embed_color)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False

    async def get_or_create_muted_role(self, guild: discord.Guild):
        role = discord.utils.get(guild.roles, name="Muted")
        if role:
            return role, False
        new_role = await guild.create_role(
            name="Muted",
            reason="Muted管理用ロールの自動生成",
            color=discord.Color.dark_grey()
        )
        return new_role, True

    @tasks.loop(minutes=1)
    async def check_mute_expiry(self):
        now = datetime.now(timezone.utc)
        expired_list = []
        for (guild_id, user_id), expire_time in self.mute_tasks.items():
            if now >= expire_time:
                guild = self.bot.get_guild(guild_id)
                if not guild: continue
                member = guild.get_member(user_id)
                role = discord.utils.get(guild.roles, name="Muted")
                if member and role:
                    try: await member.remove_roles(role, reason="Muted期間終了")
                    except: pass
                expired_list.append((guild_id, user_id))
        for item in expired_list:
            del self.mute_tasks[item]

    muted_group = app_commands.Group(name="muted", description="Mutedロールの管理システム")

    @muted_group.command(name="set_admin", description="Mutedコマンドを実行できる管理ロールを設定します")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def set_admin(self, interaction: discord.Interaction, role: discord.Role):
        self.admin_roles[interaction.guild_id] = role.id
        embed = discord.Embed(
            title="管理ロール設定",
            description=f"管理ロールを {role.mention} に設定しました。このロールを持つメンバーはMutedコマンドを利用できます。",
            color=self.embed_color
        )
        await interaction.response.send_message(embed=embed)

    @muted_group.command(name="givetime", description="指定時間、Mutedロールを付与します")
    async def givetime(self, interaction: discord.Interaction, member: discord.Member, minutes: int):
        if not await self.is_admin_role(interaction): return

        role, created = await self.get_or_create_muted_role(interaction.guild)
        await member.add_roles(role)
        
        expire_time = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        self.mute_tasks[(interaction.guild_id, member.id)] = expire_time
        
        embed = discord.Embed(title="Muted付与", color=self.embed_color)
        embed.description = f"{member.display_name} を {minutes}分間 Mutedに設定しました。"
        if created:
            embed.set_footer(text="Mutedロールを新規作成しました。/muted link 推奨")
        
        await interaction.response.send_message(embed=embed)

    @muted_group.command(name="link", description="全チャンネルの権限にMutedロールの制限を同期")
    async def link(self, interaction: discord.Interaction):
        if not await self.is_admin_role(interaction): return

        await interaction.response.defer(ephemeral=True)
        role, _ = await self.get_or_create_muted_role(interaction.guild)

        success, error = 0, 0
        for channel in interaction.guild.channels:
            try:
                await channel.set_permissions(role, send_messages=False, add_reactions=False, connect=False)
                success += 1
            except: error += 1
        
        embed = discord.Embed(
            title="権限同期完了",
            description=f"成功: {success}件 / 失敗: {error}件\n全てのチャンネルで発言禁止設定を同期しました。",
            color=self.embed_color
        )
        await interaction.followup.send(embed=embed)

    @muted_group.command(name="custom", description="Mutedのカスタム設定（非表示のトグル等）")
    @app_commands.choices(mode=[
        app_commands.Choice(name="hide/show (全非表示の切替)", value="hide_toggle"),
        app_commands.Choice(name="isolation (特定チャンネルのみ表示)", value="iso")
    ])
    async def custom(self, interaction: discord.Interaction, mode: str, target_channel: discord.TextChannel = None):
        if not await self.is_admin_role(interaction): return

        await interaction.response.defer(ephemeral=True)
        role, _ = await self.get_or_create_muted_role(interaction.guild)
        embed = discord.Embed(title="カスタム設定適用", color=self.embed_color)

        if mode == "hide_toggle":
            # 現在の「全非表示」状態を判定（最初のテキストチャンネルを確認）
            first_channel = interaction.guild.text_channels[0]
            current_perms = first_channel.overwrites_for(role)
            
            # 既に非表示(view_channel=False)なら解除、そうでなければ非表示に
            should_hide = not (current_perms.view_channel == False)
            
            for channel in interaction.guild.text_channels:
                try:
                    await channel.set_permissions(role, view_channel=None if not should_hide else False, send_messages=False)
                except: continue
            
            embed.description = "全てのテキストチャンネルを表示設定に戻しました(発言不可のみ維持)。" if not should_hide else "全てのテキストチャンネルを非表示にしました。"
        
        elif mode == "iso":
            if not target_channel:
                embed.description = "隔離先のチャンネルを指定してください。"
                return await interaction.followup.send(embed=embed)
            
            for channel in interaction.guild.text_channels:
                try:
                    is_target = (channel.id == target_channel.id)
                    await channel.set_permissions(role, view_channel=is_target, send_messages=is_target)
                except: continue
            embed.description = f"{target_channel.mention} 以外を非表示にしました。"

        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Muted(bot))