import asyncio
import os
import random
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

# 1文字候補の50音・記号・および文章終了トークン [END]
ALL_HIRAGANA = [
    "あ", "い", "う", "え", "お",
    "か", "き", "く", "け", "こ",
    "さ", "し", "す", "せ", "そ",
    "た", "ち", "つ", "て", "と",
    "な", "に", "ぬ", "ね", "の",
    "は", "ひ", "ふ", "へ", "ほ",
    "ま", "み", "む", "め", "も",
    "や", "ゆ", "よ",
    "ら", "り", "る", "れ", "ろ",
    "わ", "を", "ん",
    "っ", "ゃ", "ゅ", "ょ", "ー",
    "！", "？", "♪",
]

END_TOKEN = "[END]"

class AutoregressiveJevCharEngine:
    """Jevを用いて1文字ずつ自己回帰的（Autoregressive）に文字を選択・追加し、

    [END] トークンが選ばれるまで一文を生成し続ける雛形エンジン。
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("JEV_API_KEY", "DEMO_KEY")
        self.api_url = "https://api.typesafe.ai/v1/evaluate"
        self.max_steps = 30  # 無限ループ防止用の最大生成ステップ数

    async def generate_sentence_step_by_step(self, user_prompt: str) -> dict:
        """1文字ごとにJevに問い合わせ、文脈（State）を更新しながら文章を伸長するメインループ"""
        start_time = asyncio.get_event_loop().time()

        generated_text = ""
        trace_history = []
        step_count = 0

        # 自己回帰生成（Autoregressive Generation Loop）
        while step_count < self.max_steps:
            step_count += 1

            # 選択肢リスト（ひらがな全般 ＋ 文章終了トークン）
            candidates = ALL_HIRAGANA + [END_TOKEN]

            # 1文字選択のAPIリクエスト実行
            chosen_char = await self._predict_next_char(
                user_prompt=user_prompt,
                current_text=generated_text,
                candidates=candidates,
                step=step_count
            )

            trace_history.append(f"Step {step_count}: '{chosen_char}'")

            # 終了トークン [END] が選ばれた場合は即時生成終了
            if chosen_char == END_TOKEN:
                break

            # 生成テキストに1文字追加（文脈の更新）
            generated_text += chosen_char

        elapsed_ms = (asyncio.get_event_loop().time() - start_time) * 1000

        return {
            "sentence": generated_text if generated_text else "（空の生成）",
            "trace": trace_history,
            "total_steps": step_count,
            "speed_ms": elapsed_ms
        }

    async def _predict_next_char(self, user_prompt: str, current_text: str, candidates: list, step: int) -> str:
        """現在の文脈（プロンプト + ここまでに生成された文字列）をJevにわたし、

        最も適した次の1文字または [END] を確率選択させる。
        """
        # Jevへの入力State（役割・ユーザー発言・現在生成中の文字列を明確に構造化）
        state_context = (
            "[Role] You are a friendly, highly natural Japanese AI assistant.\n"
            f"[User Input] \"{user_prompt}\"\n"
            f"[Generated So Far] \"{current_text}\"\n"
            f"[Current Step] {step}"
        )

        payload = {
            "state": state_context,
            "questions": {
                "next_char": {
                    "type": "choice",
                    "choices": candidates,
                    "prompt": (
                        "Based on '[Generated So Far]', select the SINGLE next character from 'choices' that makes "
                        "the sequence sound like completely natural, grammatically correct Japanese responding to '[User Input]'. "
                        f"If '[Generated So Far]' already forms a complete, natural, and friendly response, you MUST select '{END_TOKEN}' immediately."
                    )
                }
            }
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=headers, timeout=2) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        chosen = result.get("next_char", {}).get("choice", END_TOKEN)
                        return chosen
                    else:
                        return self._fallback_step_selection(current_text, step)
        except Exception:
            return self._fallback_step_selection(current_text, step)

    def _fallback_step_selection(self, current_text: str, step: int) -> str:
        """API未接続時・テスト用の1文字判定シミュレーション。

        一定文字数を超えると [END] が出やすくなる挙動の実験。
        """
        # 10文字を超えたら段階的に [END] の選択確率を上げる
        if step > 12:
            return END_TOKEN if random.random() < 0.6 else random.choice(["！", "〜", "ね"])
        elif step > 6:
            candidates = ["つ", "か", "れ", "た", "よ", "ね", "！", "〜", END_TOKEN]
            return random.choice(candidates)
        else:
            first_chars = ["そ", "う", "だ", "ね", "あ", "お", "か"]
            return random.choice(first_chars)


class CharAutoregressiveCog(commands.Cog):
    """1文字自己回帰（Autoregressive）Jev生成エンジン Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.engine = AutoregressiveJevCharEngine()

    @app_commands.command(name="ai", description="1文字ずつJevで判定・生成し、[END]で打ち切る自己回帰テスト")
    @app_commands.describe(prompt="メッセージを入力してください")
    async def ai_command(self, interaction: discord.Interaction, prompt: str):
        """/ai コマンド: 1文字ステップループを実行し、生成結果とログを返却"""
        await interaction.response.defer()

        res = await self.engine.generate_sentence_step_by_step(prompt)

        sentence = res["sentence"]
        trace = "\n".join(res["trace"][:10])  # ログの先頭10ステップを表示
        if len(res["trace"]) > 10:
            trace += f"\n... (計 {res['total_steps']} ステップ)"

        speed_ms = res["speed_ms"]

        response_msg = (
            f"**生成結果: {sentence}**\n\n"
            f"```\n[1文字ステップ採択ログ]\n{trace}\n```\n"
            f"`⚡ Autoregressive Steps: {res['total_steps']} | Time: {speed_ms:.2f}ms`"
        )

        await interaction.followup.send(response_msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(CharAutoregressiveCog(bot))