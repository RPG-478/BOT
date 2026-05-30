import discord
from discord import app_commands
from discord.ext import commands

class MimicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mimic", description="指定したユーザーの名前とアイコンでメッセージを送信します。")
    @app_commands.describe(member="なりきりたいメンバーを選択", message="送信したいメッセージを入力")
    async def mimic(self, interaction: discord.Interaction, member: discord.Member, message: str):
        
        # 1. サーバー内での実行かチェック
        if interaction.guild is None:
            await interaction.response.send_message("このコマンドはサーバー内でのみ実行できます。", ephemeral=True)
            return

        # 2. 【メンション対策】@の文字が入っていれば即座に弾く
        if "@" in message:
            await interaction.response.send_message("❌ メッセージに「@」を含めることはできません。", ephemeral=True)
            return

        # 3. ボットにWebhook管理権限があるかチェック
        if not interaction.app_permissions.manage_webhooks:
            await interaction.response.send_message("ボットに「ウェブフックの管理」権限がありません。", ephemeral=True)
            return

        # 4. 応答を保留（画面にメッセージを出さずに処理を開始）
        await interaction.response.defer(ephemeral=True)

        try:
            # 5. チャンネル内の既存Webhookを確認・作成
            channel = interaction.channel
            webhooks = await channel.webhooks()
            webhook = discord.utils.get(webhooks, name="Mimic-Webhook")

            if webhook is None:
                webhook = await channel.create_webhook(name="Mimic-Webhook")

            # 6. Webhookを使って送信
            # allowed_mentions=none を設定して、万が一のすり抜けメンションも無効化
            await webhook.send(
                content=message,
                username=member.display_name,
                avatar_url=member.display_avatar.url,
                allowed_mentions=discord.AllowedMentions.none()
            )
            
        finally:
            # 7. 保留していた応答を完全に削除する
            # これにより、実行者の画面に「送信しました」などのログを残さず終了します
            await interaction.delete_original_response()

# Botへの登録用関数
async def setup(bot):
    await bot.add_cog(MimicCog(bot))
