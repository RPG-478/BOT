# =====================
# SaitoRelay Cog (通話系)
# =====================
class SaitoRelay(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.matching_queue = [] 

    @commands.command()
    async def saito(self, ctx):
        """音声中継マッチング (エンコーダー強制初期化版)"""
        if not ctx.author.voice:
            return await ctx.send("VCに参加してから実行してください。")

        if ctx.voice_client:
            return await ctx.send("このサーバーでは既に接続中です。")

        self.matching_queue = [c for c in self.matching_queue if c.guild.id != ctx.guild.id]

        target_peer = None
        for i, peer in enumerate(self.matching_queue):
            if peer.guild.id != ctx.guild.id:
                target_peer = self.matching_queue.pop(i)
                break
        
        if not target_peer:
            self.matching_queue.append(ctx)
            return await ctx.send(f"🔎 相手を探しています... ({ctx.guild.name})")

        await ctx.send(f"🤝 **{target_peer.guild.name}** と接続中...")
        await target_peer.send(f"🤝 **{ctx.guild.name}** と接続中...")

        try:
            vc1 = await ctx.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
            vc2 = await target_peer.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient)

            silence_src1 = discord.FFmpegPCMAudio("/dev/null") 
            silence_src2 = discord.FFmpegPCMAudio("/dev/null")
            vc1.play(silence_src1)
            vc2.play(silence_src2)

            class RelaySink(voice_recv.AudioSink):
                def __init__(self, dest_vc):
                    super().__init__()
                    self.dest_vc = dest_vc

                def wants_opus(self) -> bool:
                    return True

                def write(self, user, data: voice_recv.VoiceData):
                    if self.dest_vc and self.dest_vc.is_connected():
                        try:
                            self.dest_vc.send_audio_packet(data.data)
                        except Exception:
                            pass

                def cleanup(self):
                    self.dest_vc = None

            vc1.listen(RelaySink(vc2))
            vc2.listen(RelaySink(vc1))

            await ctx.send("🎙️ 通話を開始しました。")
            await target_peer.send("🎙️ 通話を開始しました。")

        except Exception as e:
            logging.error(f"Saito Match Error: {e}")
            if ctx.voice_client: await ctx.voice_client.disconnect()
            if target_peer.voice_client: await target_peer.voice_client.disconnect()

    @commands.command()
    async def saito_stop(self, ctx):
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("通話を終了しました。")

async def setup(bot):
    await bot.add_cog(SaitoRelay(bot))


