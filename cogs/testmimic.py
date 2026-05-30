import discord
from discord import app_commands
from discord.ext import commands

class MimicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # スラッシュコマンドの定義
    @app_commands.command(name="mimic", description="指定したユーザーの名前とアイコンでメッセージを送信します。")
    @app_commands.describe(member="なりきりたいメンバーを選択", message="送信したいメッセージを入力")
    async def mimic(self, interaction: discord.Interaction, member: discord.Member, message: str):
        
        # 1. サーバー内での実行かチェック
        if interaction.guild is None:
            await interaction.response.send_message("このコマンドはサーバー内でのみ実行できます。", ephemeral=True)
            return

        # 2. ボットにWebhook管理権限があるかチェック
        if not interaction.app_permissions.manage_webhooks:
            await interaction.response.send_message("ボットに「ウェブフックの管理」権限がありません。", ephemeral=True)
            return

        # 3. チャンネル内の既存Webhookを確認・作成
        channel = interaction.channel
        webhooks = await channel.webhooks()
        webhook = discord.utils.get(webhooks, name="Mimic-Webhook")

        if webhook is None:
            webhook = await channel.create_webhook(name="Mimic-Webhook")

        # 4. Webhookを使ってメンバーになりきって送信
        await webhook.send(
            content=message,
            username=member.display_name,
            avatar_url=member.display_avatar.url
        )

        # 5. スラッシュコマンドを終了させる（実行者にだけ見えるメッセージ）
        await interaction.response.send_message("なりきりメッセージを送信しました！", ephemeral=True)

# Botへの登録用関数
async def setup(bot):
    await bot.add_cog(MimicCog(bot))