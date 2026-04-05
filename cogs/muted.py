import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone

class Muted(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.admin_roles = {} 
        self.mute_tasks = {}
        self.embed_color = 0xFFFFFF  # 白色
        self.check_mute_expiry.start()

    def cog_unload(self):
        self.check_mute_expiry.cancel()

    async def is_admin_role(self, interaction: discord.Interaction) -> bool:
        allowed_role_id = self.admin_roles.get(interaction.guild_id)
        if interaction.user.guild_permissions.administrator:
            return True
        if allowed_role_id and any(role.id == allowed_role_id for role in interaction.user.roles):
            return True
        
        embed = discord.Embed(description="❌ このコマンドを実行する権限がありません。", color=self.embed_color)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False

    async def get_or_create_muted_role(self, guild: discord.Guild):
        role = discord.utils.get(guild.roles, name="Muted")
        if role:
            return role, False

        new_role = await guild.create_role(
            name="Muted",
            reason="Mutedコマンド実行による自動生成",
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
                    try:
                        await member.remove_roles(role, reason="Muted期間終了")
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
            title="⚙️ 管理ロール設定",
            description=f"管理ロールを {role.mention} に設定しました。",
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
        
        embed = discord.Embed(title="🔇 Muted付与", color=self.embed_color)
        embed.description = f"**{member.display_name}** を {minutes}分間 Mutedにしました。"
        if created:
            embed.add_field(name="⚠️ 注意", value="Mutedロールを新規作成しました。`/muted link` を実行して権限を同期してください。")
        
        await interaction.response.send_message(embed=embed)

    @muted_group.command(name="link", description="全チャンネルの権限にMutedロールの書き込み禁止を同期")
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
            title="🔄 権限同期完了",
            description=f"成功: {success}件 / 失敗: {error}件\n全てのチャンネルでMutedの書き込みを制限しました。",
            color=self.embed_color
        )
        await interaction.followup.send(embed=embed)

    @muted_group.command(name="custom", description="Mutedのカスタム設定")
    @app_commands.choices(mode=[
        app_commands.Choice(name="hide_all (全非表示)", value="hide"),
        app_commands.Choice(name="isolation (隔離チャンネルのみ表示)", value="iso")
    ])
    async def custom(self, interaction: discord.Interaction, mode: str, target_channel: discord.TextChannel = None):
        if not await self.is_admin_role(interaction): return

        await interaction.response.defer(ephemeral=True)
        role, created = await self.get_or_create_muted_role(interaction.guild)
        embed = discord.Embed(title="🛠️ カスタム設定適用", color=self.embed_color)

        if mode == "hide":
            for channel in interaction.guild.text_channels:
                try: await channel.set_permissions(role, view_channel=False)
                except: continue
            embed.description = "Mutedユーザーから全てのテキストチャンネルを隠しました。"
        
        elif mode == "iso":
            if not target_channel:
                embed.description = "❌ 隔離先のチャンネルを指定してください。"
                return await interaction.followup.send(embed=embed)
            
            for channel in interaction.guild.text_channels:
                try:
                    is_target = (channel.id == target_channel.id)
                    await channel.set_permissions(role, view_channel=is_target, send_messages=is_target)
                except: continue
            embed.description = f"{target_channel.mention} 以外を非表示にしました。"

        if created:
            embed.set_footer(text="Mutedロールを自動作成しました。")
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Muted(bot))