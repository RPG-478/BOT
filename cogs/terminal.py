import asyncio
import io
import os
import discord
from discord.ext import commands

ALLOWED_USER_ID = 1320705325686587408
TARGET_DIR = os.path.expanduser("~/BOT")

class TerminalModal(discord.ui.Modal, title="ターミナルコマンド実行"):
    command_input = discord.ui.TextInput(
        label="実行コマンド",
        style=discord.TextStyle.paragraph,
        placeholder="pip list や python main.py など",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != ALLOWED_USER_ID:
            await interaction.response.send_message("実行権限がありません。", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        
        cmd = self.command_input.value
        full_command = f"cd {TARGET_DIR} && source venv/bin/activate && {cmd}"
        
        process = await asyncio.create_subprocess_shell(
            full_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            executable="/bin/bash"
        )
        
        stdout, stderr = await process.communicate()
        output = (stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")).strip()
        
        if not output:
            output = "(出力なし)"
            
        if len(output) > 1900:
            file_data = io.BytesIO(output.encode("utf-8"))
            await interaction.followup.send(
                content=f"実行コマンド: `{cmd}`",
                file=discord.File(file_data, filename="terminal_log.txt")
            )
        else:
            await interaction.followup.send(
                content=f"**実行コマンド:** `{cmd}`\n```bash\n{output}\n```"
            )

class TerminalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="コマンド送信", style=discord.ButtonStyle.primary, custom_id="terminal_send_button")
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != ALLOWED_USER_ID:
            await interaction.response.send_message("実行権限がありません。", ephemeral=True)
            return
        await interaction.response.send_modal(TerminalModal())

class TerminalCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="terminal")
    async def send_panel(self, ctx):
        if ctx.author.id != ALLOWED_USER_ID:
            return
        
        embed = discord.Embed(
            title="ラズパイ 擬似ターミナル",
            description=f"下のボタンを押して実行するコマンドを入力してください。\n実行パス: `{TARGET_DIR}`\n環境: `venv` アクティベート済み",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, view=TerminalView())

async def setup(bot):
    await bot.add_cog(TerminalCog(bot))
