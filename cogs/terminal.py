import asyncio
import os
import pty
import discord
from discord.ext import commands

# 単一のIDから、許可するIDの集合(set)に変更
ALLOWED_USER_IDS = {
    1320705325686587408,
    1000302102473613373,  # 追加したい2人目のユーザーID
}
TARGET_DIR = os.path.expanduser("~/BOT")

async def run_interactive_terminal(bot, thread, cmd):
    full_command = f"cd {TARGET_DIR} && source venv/bin/activate && {cmd}"
    master, slave = pty.openpty()

    # masterを非ブロックモードに設定（イベントループのフリーズ防止）
    os.set_blocking(master, False)

    try:
        process = await asyncio.create_subprocess_shell(
            full_command,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            executable="/bin/bash"
        )
        os.close(slave)

        input_queue = asyncio.Queue()

        def check_message(m):
            return m.channel.id == thread.id and m.author.id in ALLOWED_USER_IDS

        async def listen_messages():
            while True:
                try:
                    msg = await bot.wait_for("message", check=check_message)
                    await input_queue.put(msg.content.strip())
                except asyncio.CancelledError:
                    break

        async def read_output():
            output_buffer = ""
            while True:
                try:
                    try:
                        data = os.read(master, 1024)
                    except (BlockingIOError, OSError):
                        data = None

                    if data:
                        output_buffer += data.decode("utf-8", errors="replace")

                    # 出力バッファが存在し、一時的に追加データが無くなったタイミングでDiscordに送信
                    if output_buffer and not data:
                        text_to_send = output_buffer
                        output_buffer = ""
                        if len(text_to_send.strip()) > 0:
                            if len(text_to_send) > 1900:
                                text_to_send = text_to_send[-1900:]
                            await thread.send(f"```bash\n{text_to_send}\n```")

                    if process.returncode is not None and not data:
                        break

                    await asyncio.sleep(0.2)
                except asyncio.CancelledError:
                    break

        async def handle_input():
            while True:
                user_input = await input_queue.get()
                if user_input.lower() == "cancel":
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await thread.send("プロセスの実行を強制終了しました。")
                    break
                try:
                    os.write(master, (user_input + "\n").encode("utf-8"))
                except OSError:
                    break

        await thread.send(f"実行開始: `{cmd}`\nキャンセルする場合は `cancel` と送信してください。")

        listener_task = asyncio.create_task(listen_messages())
        reader_task = asyncio.create_task(read_output())
        writer_task = asyncio.create_task(handle_input())

        await process.wait()

        # 残りの出力を読み切るための猶予時間
        await asyncio.sleep(0.5)

        listener_task.cancel()
        reader_task.cancel()
        writer_task.cancel()

        await thread.send("処理が終了しました。")

    finally:
        try:
            os.close(master)
        except OSError:
            pass

class TerminalModal(discord.ui.Modal, title="対話ターミナル実行"):
    command_input = discord.ui.TextInput(
        label="実行コマンド",
        style=discord.TextStyle.paragraph,
        placeholder="sudo certbot --- や python main.py など",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id not in ALLOWED_USER_IDS:
            await interaction.response.send_message("実行権限がありません。", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        cmd = self.command_input.value

        if isinstance(interaction.channel, discord.TextChannel):
            thread = await interaction.channel.create_thread(
                name=f"term-{cmd[:15]}".replace(" ", "-"),
                auto_archive_duration=60
            )
        else:
            await interaction.followup.send("テキストチャンネル内で実行してください。", ephemeral=True)
            return

        await interaction.followup.send(f"スレッドを作成しました: {thread.mention}")
        asyncio.create_task(run_interactive_terminal(interaction.client, thread, cmd))

class TerminalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="コマンド送信", style=discord.ButtonStyle.primary, custom_id="terminal_send_button")
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in ALLOWED_USER_IDS:
            await interaction.response.send_message("実行権限がありません。", ephemeral=True)
            return
        await interaction.response.send_modal(TerminalModal())

class TerminalCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="terminal")
    async def send_panel(self, ctx):
        if ctx.author.id not in ALLOWED_USER_IDS:
            return
        
        embed = discord.Embed(
            title="ラズパイ 擬似ターミナル (対話対応)",
            description=f"下のボタンを押してコマンドを入力してください。\n実行時に作成されるスレッド内で入力応答が可能です。\n実行パス: `{TARGET_DIR}`",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, view=TerminalView())

async def setup(bot):
    await bot.add_cog(TerminalCog(bot))
