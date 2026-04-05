import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime

class Muted(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # ギルドIDごとに管理権限ロールIDを保存する辞書
        self.admin_roles = {} 

    # 独自チェック: 管理者ロールか、サーバー管理者権限を持っているか
    async def is_admin_role(self, interaction: discord.Interaction) -> bool:
        allowed_role_id = self.admin_roles.get(interaction.guild_id)
        # サーバー管理者権限がある、または設定されたロールを持っている
        if interaction.user.guild_permissions.administrator:
            return True
        if allowed_role_id and any(role.id == allowed_role_id for role in interaction.user.roles):
            return True
        
        await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
        return False

    muted_group = app_commands.Group(name="muted", description="Mutedロールの管理システム")

    # --- 管理ロールの設定 ---
    @muted_group.command(name="set_admin", description="Mutedコマンドを実行できる管理ロールを設定します")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def set_admin(self, interaction: discord.Interaction, role: discord.Role):
        self.admin_roles[interaction.guild_id] = role.id
        await interaction.response.send_message(f"管理ロールを {role.mention} に設定しました。")

    # --- /muted givetime ---
    @muted_group.command(name="givetime", description="指定時間、Mutedロールを付与します")
    async def givetime(self, interaction: discord.Interaction, member: discord.Member, minutes: int):
        if not await self.is_admin_role(interaction): return

        role = discord.utils.get(interaction.guild.roles, name="Muted")
        if not role:
            return await interaction.response.send_message("Mutedロールが見つかりません。")

        await member.add_roles(role)
        await interaction.response.send_message(f"{member.display_name} を {minutes}分間 Mutedにしました。")

    # --- /muted link ---
    @muted_group.command(name="link", description="全チャンネルの権限にMutedロールの書き込み禁止を同期")
    async def link(self, interaction: discord.Interaction):
        if not await self.is_admin_role(interaction): return

        # 処理が長くなるのでdeferで応答を保留
        await interaction.response.defer(ephemeral=True)
        
        role = discord.utils.get(interaction.guild.roles, name="Muted")
        if not role:
            return await interaction.followup.send("Mutedロールが存在しません。")

        for channel in interaction.guild.channels:
            try:
                await channel.set_permissions(role, send_messages=False, add_reactions=False)
            except:
                continue # カテゴリやアクセスできないチャンネルはスキップ
        
        await interaction.followup.send("全てのチャンネルの権限同期が完了しました。")

    # --- /muted custom ---
    @muted_group.command(name="custom", description="Mutedのカスタム設定（非表示や隔離）")
    @app_commands.choices(mode=[
        app_commands.Choice(name="hide_all (全非表示)", value="hide"),
        app_commands.Choice(name="isolation (隔離チャンネルのみ表示)", value="iso")
    ])
    async def custom(self, interaction: discord.Interaction, mode: str, target_channel: discord.TextChannel = None):
        if not await self.is_admin_role(interaction): return

        # 応答を保留（これがないと全チャンネルループ時にタイムアウトします）
        await interaction.response.defer(ephemeral=True)

        role = discord.utils.get(interaction.guild.roles, name="Muted")
        if not role:
            return await interaction.followup.send("Mutedロールが存在しません。")

        if mode == "hide":
            for channel in interaction.guild.text_channels:
                try:
                    await channel.set_permissions(role, view_channel=False)
                except:
                    continue
            await interaction.followup.send("設定完了：Mutedユーザーからチャンネルをすべて隠しました。")
        
        elif mode == "iso":
            if not target_channel:
                return await interaction.followup.send("隔離先となるチャンネルを指定してください。")
            
            for channel in interaction.guild.text_channels:
                try:
                    is_target = (channel.id == target_channel.id)
                    await channel.set_permissions(role, view_channel=is_target, send_messages=is_target)
                except:
                    continue
            await interaction.followup.send(f"設定完了：{target_channel.mention} 以外を非表示にしました。")

async def setup(bot):
    await bot.add_cog(Muted(bot))