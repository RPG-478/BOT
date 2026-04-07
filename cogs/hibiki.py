@commands.Cog.listener()
async def on_message(self, message: discord.Message):

    # ===== bot無視 =====
    if message.author.bot:
        return

    channel_id = message.channel.id

    # ===== トグル（最優先）=====
    if message.content.strip() == "!oo":
        state = not self.channel_state.get(channel_id, False)
        self.channel_state[channel_id] = state

        await message.channel.send(
            "うおｗAIモードONｗ" if state else "AIモードOFF"
        )
        return

    # ===== コマンド処理（後）=====
    await self.bot.process_commands(message)

    # ===== OFFなら何もしない =====
    if not self.channel_state.get(channel_id, False):
        return

    # ===== ランダム返信 =====
    if random.random() > self._get_prob(channel_id):
        return

    # ===== クールダウン =====
    if not self._cooldown_ok(message.author.id):
        return

    # ===== テキスト整形 =====
    text = self._clean_text(message.content, self.bot.user)
    if not text:
        text = "無言"

    # ===== AI生成 =====
    async with message.channel.typing():
        try:
            reply = await asyncio.wait_for(
                self._run_llm(text),
                timeout=8.0
            )
        except asyncio.TimeoutError:
            reply = "考えるの遅いｗ"
        except Exception as e:
            print(f"[ReplyAI Error] {e}")
            reply = "エラーで無理だった"

    # ===== 返信 =====
    await message.reply(
        reply[:120],
        allowed_mentions=discord.AllowedMentions.none()
    )

    # ===== usageログ =====
    if message.guild:
        self._log_usage(message.guild.id)
