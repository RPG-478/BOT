import discord
from discord.ext import commands

class MimicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="mimic", help="指定したユーザーの名前とアイコンでメッセージを送信します。")
    @commands.bot_has_permissions(manage_webhooks=True)  # ボットにWebhook管理権限が必要
    @commands.guild_only()  # サーバー内のみで実行可能
    async def mimic(self, ctx, member: discord.Member, *, message: str):
        # 1. 元のコマンドメッセージを削除して、なりきり感を高める
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            # メッセージ削除権限がない場合はスキップ
            pass

        # 2. チャンネル内に既存のボット用Webhookがあるか確認
        webhooks = await ctx.channel.webhooks()
        webhook = discord.utils.get(webhooks, name="Mimic-Webhook")

        # 3. なければ新しく作成
        if webhook is None:
            webhook = await ctx.channel.create_webhook(name="Mimic-Webhook")

        # 4. 指定されたメンバの「表示名」と「アバターURL」を使ってメッセージを送信
        await webhook.send(
            content=message,
            username=member.display_name,
            avatar_url=member.display_avatar.url
        )

# Botへの登録用関数
async def setup(bot):
    await bot.add_cog(MimicCog(bot))
