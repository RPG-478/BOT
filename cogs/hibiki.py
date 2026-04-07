class ReplyAI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel_state = {}

    # ===== トグルコマンド =====
    @commands.command(name="oo")
    async def toggle_ai(self, ctx: commands.Context):
        channel_id = ctx.channel.id

        state = not self.channel_state.get(channel_id, False)
        self.channel_state[channel_id] = state

        await ctx.send(
            "うおｗAIモードONｗ" if state else "AIモードOFF"
        )

    # ===== テスト用コマンド =====
    @commands.command(name="test")
    async def test(self, ctx):
        await ctx.send("動いてるぞｗ")
