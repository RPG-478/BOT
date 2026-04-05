import discord
from discord.ext import commands
from discord import app_commands
import datetime

class Muted(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.admin_roles = {} 

    async def is_admin_role(self, interaction: discord.Interaction) -> bool:
        allowed_role_id = self.admin_roles.get(interaction.guild_id)
        if interaction.user.guild_permissions.administrator:
            return True
        if allowed_role_id and any(role.id == allowed_role_id for role in interaction.user.roles):
            return True
        
        await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
        return False

    async def get_or_create_muted_role(self, guild: discord.Guild):
        """Mutedロールを取得、なければ作成する"""
        role = discord.utils.get(guild.roles, name="Muted")
        if role:
            return role, False

        # ロールが存在しない場合、新規作成
        # 位置を上の方にするために、Botのロールの直下に配置するのが理想ですが、基本は下位に作成されます
        new_role = await guild.create_role(
            name="Muted",
            reason="Mutedコマンド実行による自動生成",
            color=discord.Color.dark_grey()
        )
        return new_role, True

    muted_group = app_commands.Group(name="muted", description="Mutedロールの管理システム")

    @muted_group.command(name="set_admin", description="Mutedコマンドを実行できる管理ロールを設定します")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def set_admin(self, interaction: discord.Interaction, role: discord.Role):
        self.admin_roles[interaction.guild_id] = role.id
        await interaction.response.send_message(f"管理ロールを {role.mention} に設定しました。")

    @muted_group.command(name="givetime", description="指定時間、Mutedロールを付与します")
    async def givetime(self, interaction: discord.Interaction, member: discord.Member, minutes: int):
        if not await self.is_admin_role(interaction): return

        role, created = await self.get_or_create_muted_role(interaction.guild)
        
        await member.add_roles(role)
        
        msg = f"{member.display_name} を {minutes}分間 Mutedにしました。"
        if created:
            msg += "\n⚠️ **Mutedロールを新規作成しました。** 各チャンネルへの権限反映を完了させるため、`/muted link` の実行を推奨します。"
        
        await interaction.response.send_message(msg)

    @muted_group.command(name="link", description="全チャンネルの権限にMutedロールの書き込み禁止を同期")
    async def link(self, interaction: discord.Interaction):
        if not await self.is_admin_role(interaction): return

        await interaction.response.defer(ephemeral=True)
        
        role, _ = await self.get_or_create_muted_role(interaction.guild)

        success_count = 0
        error_count = 0

        for channel in interaction.guild.channels:
            try:
                # 送信、リアクション、スレッド作成、通話を制限
                await channel.set_permissions(
                    role, 
                    send_messages=False, 
                    add_reactions=False, 
                    create_public_threads=False,
                    connect=False
                )
                success_count += 1
            except:
                error_count += 1
        
        await interaction.followup.send(f"同期完了: {success_count}個のチャンネルを設定しました。(失敗: {error_count})")

    @muted_group.command(name="custom", description="Mutedのカスタム設定（非表示や隔離）")
    @app_commands.choices(mode=[
        app_commands.Choice(name="hide_all (全非表示)", value="hide"),
        app_commands.Choice(name="isolation (隔離チャンネルのみ表示)", value="iso")
    ])
    async def custom(self, interaction: discord.Interaction, mode: str, target_channel: discord.TextChannel = None):
        if not await self.is_admin_role(interaction): return

        await interaction.response.defer(ephemeral=True)

        role, created = await self.get_or_create_muted_role(interaction.guild)

        if mode == "hide":
            for channel in interaction.guild.text_channels:
                try:
                    await channel.set_permissions(role, view_channel=False)
                except: continue
            
            res = "設定完了：Mutedユーザーから全チャンネルを隠しました。"
            if created: res += "\n(Mutedロールを自動作成しました)"
            await interaction.followup.send(res)
        
        elif mode == "iso":
            if not target_channel:
                return await interaction.followup.send("隔離先となるチャンネルを指定してください。")
            
            for channel in interaction.guild.text_channels:
                try:
                    is_target = (channel.id == target_channel.id)
                    await channel.set_permissions(role, view_channel=is_target, send_messages=is_target)
                except: continue
            
            res = f"設定完了：{target_channel.mention} 以外を非表示にしました。"
            if created: res += "\n(Mutedロールを自動作成しました。今後のため `/muted link` も推奨します)"
            await interaction.followup.send(res)

async def setup(bot):
    await bot.add_cog(Muted(bot))