import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import asyncio

class Muted(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_mutes.start()  # 時間経過による剥奪チェック

    def cog_unload(self):
        self.check_mutes.cancel()

    muted_group = app_commands.Group(name="muted", description="Mutedロールの管理コマンド")

    # --- /muted givetime ---
    @muted_group.command(name="givetime", description="指定時間、Mutedロールを付与します")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def givetime(self, interaction: discord.Interaction, member: discord.Member, minutes: int):
        role = discord.utils.get(interaction.guild.roles, name="Muted")
        if not role:
            await interaction.response.send_message("Mutedロールが見つかりません。先に作成してください。", ephemeral=True)
            return

        await member.add_roles(role)
        # 本来はDBやファイルに終了時刻を保存するのが望ましいです
        end_time = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
        
        await interaction.response.send_message(f"{member.display_name} に {minutes}分間 Mutedを付与しました。")

    # --- /muted link ---
    @muted_group.command(name="link", description="全チャンネルの権限にMutedロールの制限を同期します")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def link(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # 処理が長くなる可能性があるため
        
        role = discord.utils.get(interaction.guild.roles, name="Muted")
        if not role:
            await interaction.followup.send("Mutedロールが存在しません。")
            return

        for channel in interaction.guild.channels:
            # 既に設定がある場合は上書き、ない場合は追加
            await channel.set_permissions(role, send_messages=False, add_reactions=False)
        
        await interaction.followup.send("全てのチャンネルの権限同期が完了しました。")

    # --- /muted custom ---
    @muted_group.command(name="custom", description="Mutedのカスタム設定（チャンネル非表示など）")
    @app_commands.choices(mode=[
        app_commands.Choice(name="hide_all (全非表示)", value="hide"),
        app_commands.Choice(name="isolation (隔離チャンネルのみ)", value="iso")
    ])
    async def custom(self, interaction: discord.Interaction, mode: str, target_channel: discord.TextChannel = None):
        role = discord.utils.get(interaction.guild.roles, name="Muted")
        
        if mode == "hide":
            for channel in interaction.guild.text_channels:
                await channel.set_permissions(role, view_channel=False)
            await interaction.response.send_message("設定完了：Mutedロール保持者にチャンネルを非表示にしました。")
        
        elif mode == "iso" and target_channel:
            # 指定チャンネルだけ見れるようにし、他を消す
            for channel in interaction.guild.text_channels:
                view = (channel.id == target_channel.id)
                await channel.set_permissions(role, view_channel=view, send_messages=view)
            await interaction.response.send_message(f"設定完了：{target_channel.mention} 以外を非表示にしました。")

    @tasks.loop(seconds=60)
    async def check_mutes(self):
        # ここにDBなどから期限切れユーザーを抽出してロールを外す処理を記述します
        pass

async def setup(bot):
    await bot.add_cog(Muted(bot))
