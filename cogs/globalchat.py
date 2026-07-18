import discord
from discord import app_commands
from discord.ext import commands
import json
import os

class GlobalChatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.save_file = "global_channels.json"
        # 登録されたチャンネルIDを保持するセット（重複を防ぐ）
        self.active_channels = self.load_channels()

    # JSONファイルから登録チャンネルを読み込む
    def load_channels(self):
        if os.path.exists(self.save_file):
            try:
                with open(self.save_file, "r", encoding="utf-8") as f:
                    return set(json.load(f))
            except Exception as e:
                print(f"データの読み込みに失敗しました: {e}")
        return set()

    # JSONファイルへ登録チャンネルを保存する
    def save_channels(self):
        try:
            with open(self.save_file, "w", encoding="utf-8") as f:
                json.dump(list(self.active_channels), f)
        except Exception as e:
            print(f"データの保存に失敗しました: {e}")

    # /chat コマンド（オン・オフ切り替え）
    @app_commands.command(name="chat", description="このチャンネルのグローバルチャット（オン/オフ）を切り替えます。")
    async def toggle_chat(self, interaction: discord.Interaction):
        # サーバー内での実行かチェック
        if interaction.guild is None:
            await interaction.response.send_message("このコマンドはサーバー内でのみ実行できます。", ephemeral=True)
            return

        # 権限チェック（「チャンネルの管理」権限を持つ人のみ変更可能にする）
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ このコマンドを実行するには「チャンネルの管理」権限が必要です。", ephemeral=True)
            return

        channel_id = interaction.channel_id

        # オンオフの切り替え処理
        if channel_id in self.active_channels:
            self.active_channels.remove(channel_id)
            status = "🔴 オフ"
        else:
            self.active_channels.add(channel_id)
            status = "🟢 オン"

        # ファイルに保存
        self.save_channels()
        
        await interaction.response.send_message(f"このチャンネルのグローバルチャットを {status} にしました！", ephemeral=True)

    # メッセージ送信を検知するイベントリスナー
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ボット自身や、他のボット、Webhookからのメッセージは無視（無限ループ防止）
        if message.author.bot or message.webhook_id:
            return

        # 送信されたチャンネルがグローバルチャットに登録されていなければ無視
        if message.channel.id not in self.active_channels:
            return

        # 【メンション対策】@の文字が入っていれば転送を弾く
        if "@" in message.content:
            try:
                # 警告としてメッセージにバツ印のリアクションを付ける
                await message.add_reaction("❌")
            except discord.Forbidden:
                pass
            return

        # 自分以外の、登録されているすべてのチャンネルIDを抽出
        target_ids = [cid for cid in self.active_channels if cid != message.channel.id]

        # 各チャンネルへメッセージを転送
        for cid in target_ids:
            channel = self.bot.get_channel(cid)
            
            # キャッシュにない場合は取得を試みる
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(cid)
                except (discord.NotFound, discord.Forbidden):
                    # チャンネルが削除されている、またはボットが入れない場合はリストから除外
                    self.active_channels.remove(cid)
                    self.save_channels()
                    continue

            # 転送先サーバーでボットに「ウェブフックの管理」権限があるか確認
            if not channel.permissions_for(channel.guild.me).manage_webhooks:
                continue

            try:
                # 既存のグローバルチャット用Webhookを探す
                webhooks = await channel.webhooks()
                webhook = discord.utils.get(webhooks, name="GlobalChat-Webhook")

                # なければ作成
                if webhook is None:
                    webhook = await channel.create_webhook(name="GlobalChat-Webhook")

                # 送信者の名前とアイコンでWebhook送信
                await webhook.send(
                    content=message.content,
                    username=f"{message.author.display_name} [{message.guild.name}]", # どこから来たか分かるようにサーバー名も付与
                    avatar_url=message.author.display_avatar.url,
                    allowed_mentions=discord.AllowedMentions.none() # 二重のメンション対策
                )
            except Exception as e:
                print(f"チャンネル {cid} への転送中にエラーが発生しました: {e}")

# Botへの登録用関数
async def setup(bot):
    await bot.add_cog(GlobalChatCog(bot))
