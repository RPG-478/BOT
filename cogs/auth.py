import discord
from discord import app_commands
from discord.ext import commands

INTRO_CHANNEL_ID = 1531592567131734056

class QuestionModal(discord.ui.Modal, title="認証フォーム"):
    q1 = discord.ui.TextInput(
        label="あだ名はなんですか？(5文字以内)",
        placeholder="5文字以内で入力",
        max_length=5,
        required=True
    )
    q2 = discord.ui.TextInput(
        label="一番のウリはなんですか？",
        style=discord.TextStyle.paragraph,
        required=True
    )
    q3 = discord.ui.TextInput(
        label="堅実型ですか、発想型ですか？",
        placeholder="堅実型 または 発想型",
        required=True
    )
    q4 = discord.ui.TextInput(
        label="あなたは自分に寛容になれますか(Y/N)",
        placeholder="Y または N",
        max_length=2,
        required=True
    )

    def __init__(self, role_id: int):
        super().__init__()
        self.role_id = role_id

    async def on_submit(self, interaction: discord.Interaction):
        ans1 = self.q1.value.strip()
        ans2 = self.q2.value.strip()
        ans3 = self.q3.value.strip()
        ans4 = self.q4.value.strip().upper()

        if len(ans1) > 5 or len(ans1) == 0:
            await interaction.response.send_message("あだ名は5文字以内で入力してください。", ephemeral=True)
            return

        if ans3 not in ["堅実型", "発想型"]:
            await interaction.response.send_message("3つ目の質問は「堅実型」または「発想型」で回答してください。", ephemeral=True)
            return

        if ans4 not in ["Y", "N", "Ｙ", "Ｎ"]:
            await interaction.response.send_message("4つ目の質問は Y または N で回答してください。", ephemeral=True)
            return

        role = interaction.guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message("指定されたロールが存在しません。", ephemeral=True)
            return

        intro_channel = interaction.guild.get_channel(INTRO_CHANNEL_ID)
        if intro_channel:
            webhooks = await intro_channel.webhooks()
            webhook = webhooks[0] if webhooks else await intro_channel.create_webhook(name="SelfIntroWebhook")

            content = (
                f"【あだ名】\n{ans1}\n\n"
                f"【一番のウリ】\n{ans2}\n\n"
                f"【タイプ】\n{ans3}\n\n"
                f"【自分への寛容さ】\n{ans4}"
            )

            await webhook.send(
                content=content,
                username=interaction.user.display_name,
                avatar_url=interaction.user.display_avatar.url
            )

        await interaction.user.add_roles(role)
        await interaction.response.send_message("認証が完了しました。ロールを付与しました。", ephemeral=True)

class VerifyView(discord.ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id

    @discord.ui.button(label="認証を開始する", style=discord.ButtonStyle.green, custom_id="verify_button_persistent")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(QuestionModal(self.role_id))

class VerificationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="send_panel", description="指定したチャンネルに認証パネルを送信します")
    @app_commands.checks.has_permissions(administrator=True)
    async def send_panel(self, interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role):
        embed = discord.Embed(
            title="サーバー認証",
            description="下のボタンを押して質問に回答してください。",
            color=discord.Color.blue()
        )
        await channel.send(embed=embed, view=VerifyView(role.id))
        await interaction.response.send_message("認証パネルを送信しました。", ephemeral=True)

    @app_commands.command(name="sync_category_perms", description="指定カテゴリ内のチャンネル権限を一斉同期・設定します")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_category_perms(self, interaction: discord.Interaction, category: discord.CategoryChannel, role: discord.Role):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        everyone_role = guild.default_role

        overwrites = {
            everyone_role: discord.PermissionOverwrite(view_channel=False),
            role: discord.PermissionOverwrite(view_channel=True)
        }

        await category.edit(overwrites=overwrites)

        for channel in category.channels:
            await channel.edit(sync_permissions=True)

        await interaction.followup.send(f"カテゴリ「{category.name}」配下の全チャンネルの権限を同期しました。")

async def setup(bot: commands.Bot):
    await bot.add_cog(VerificationCog(bot))
