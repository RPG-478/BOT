import asyncio
import time
import os
from typing import List, Dict, Any, Literal
import discord
from discord import app_commands
from discord.ext import commands

# Needle (Cactus Compute) の読み込み
import cactus_needle as needle

# 50音・促音・拗音・記号および文章終了トークン [END] の厳格な型定義
HIRAGANA_CHAR_CHOICES = Literal[
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
    "！", "？", "♪", "〜",
    "[END]"
]

def append_next_character(char: HIRAGANA_CHAR_CHOICES) -> str:
    """Select the IMMEDIATELY NEXT single Japanese character or '[END]' token to construct the response.
    
    Args:
        char: The single character to append to the generated sentence, or '[END]' if the sentence is complete.
    """
    return str(char)


class NeedleCoreAutoregressiveEngine:
    """
    Needle (100% ローカル / 28MB RAM) を使用した
    堅実・堅牢な1文字自己回帰（Autoregressive）日本語生成エンジン
    """
    def __init__(self):
        # 1文字追加ツールのみを厳格に登録
        self.agent = needle.Needle(
            tools=[append_next_character]
        )
        self.max_steps = 25  # ループ安全限界ステップ数

    async def generate_sentence(self, user_prompt: str) -> Dict[str, Any]:
        """
        1ステップ＝1文字の確実な決定ループ。
        [END] トークンが選ばれるまで純粋にローカル推論のみでテキストを伸長する。
        """
        start_time = time.perf_counter()
        
        generated_text = ""
        trace_logs = []
        step_count = 0

        while step_count < self.max_steps:
            step_count += 1
            
            # --- Needleへ渡す文脈Stateの明瞭な構造化 ---
            state_context = (
                "[SYSTEM ROLE]\n"
                "You are an empathetic, natural Japanese assistant.\n"
                "Construct a friendly, grammatically correct Japanese response character by character.\n\n"
                f"[USER INPUT]: \"{user_prompt}\"\n"
                f"[CURRENT GENERATED TEXT]: \"{generated_text}\"\n"
                f"[CURRENT STEP]: {step_count} / {self.max_steps}\n\n"
                "[TASK INSTRUCTION]\n"
                "Choose the single best NEXT character from 'append_next_character' to logically continue '[CURRENT GENERATED TEXT]'.\n"
                "CRITICAL: If '[CURRENT GENERATED TEXT]' already forms a complete, natural, and friendly Japanese sentence, you MUST choose '[END]' immediately."
            )

            # --- Needle ローカル文法制約推論 (数ミリ秒) ---
            result = self.agent.run(state_context)
            
            chosen_char = "[END]"
            
            if result and result.get("function_calls"):
                for call in result["function_calls"]:
                    chosen_char = str(call.execute())
                    break
            else:
                # ツール非選択時の安全フォールバック
                chosen_char = "[END]" if step_count > 5 else "！"

            trace_logs.append(f"Step {step_count:02d}: '{chosen_char}'")

            # [END] トークンが選ばれたら即座にループ終了
            if chosen_char == "[END]":
                break

            generated_text += chosen_char

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return {
            "sentence": generated_text if generated_text else "（応答なし）",
            "trace": trace_logs,
            "total_steps": step_count,
            "latency_ms": elapsed_ms
        }


class NeedleCoreEngineCog(commands.Cog):
    """Needle 堅実1文字自己回帰 Discord Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.engine = NeedleCoreAutoregressiveEngine()

    @app_commands.command(
        name="ai_needle",
        description="[100%ローカル / Needle] 1文字自己回帰ループによる堅実な文章生成"
    )
    @app_commands.describe(prompt="メッセージを入力してください")
    async def ai_needle_command(self, interaction: discord.Interaction, prompt: str):
        """/ai_needle コマンド実行ハンドラ"""
        await interaction.response.defer()

        # 生成処理実行
        res = await self.engine.generate_sentence(prompt)

        sentence = res["sentence"]
        steps = res["total_steps"]
        latency = res["latency_ms"]
        trace = " ➔ ".join([t.split("'")[1] for t in res["trace"]])

        msg = (
            f"**[生成結果]: {sentence}**\n\n"
            f"```\n"
            f"[Needle 1文字選択ステップ軌跡]\n{trace}\n"
            f"```\n"
            f"`⚡ Core Needle Steps: {steps} 回 | Total Latency: {latency:.2f}ms | RAM: ~28MB`"
        )

        await interaction.followup.send(msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(NeedleCoreEngineCog(bot))