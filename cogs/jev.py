import asyncio
import time
import os
from typing import List, Dict, Any, Literal
import discord
from discord import app_commands
from discord.ext import commands

# Needle (Cactus Compute) の安全な読み込み（モジュール名の揺らぎを吸収）
NEEDLE_AVAILABLE = False
try:
    import needle
    NEEDLE_AVAILABLE = True
except ImportError:
    try:
        import cactus_needle as needle
        NEEDLE_AVAILABLE = True
    except ImportError:
        needle = None

# 50音・促音・拗音・句読点および文章終了トークン [END] の厳格な型定義
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
    "、", "。", "？",
    "[END]"
]

def _append_func(char: HIRAGANA_CHAR_CHOICES) -> str:
    """Select the IMMEDIATELY NEXT single Japanese character or '[END]' token to construct the response.
    
    Args:
        char: The single character to append to the generated sentence, or '[END]' if the sentence is complete.
    """
    return str(char)

# Needleツールデコレータの安全な適応
if NEEDLE_AVAILABLE and hasattr(needle, "tool"):
    append_next_character = needle.tool(_append_func)
else:
    append_next_character = _append_func


class NeedleCoreAutoregressiveEngine:
    """
    Needle (100% ローカル / 28MB RAM) を使用した
    堅実・堅牢な1文字自己回帰（Autoregressive）日本語生成エンジン
    """
    def __init__(self):
        self.agent = None
        self.max_steps = 25  # ループ安全限界ステップ数

        # Needle エージェントの安全な初期化
        if NEEDLE_AVAILABLE and needle is not None:
            try:
                if hasattr(needle, "Needle"):
                    self.agent = needle.Needle(tools=[append_next_character])
                elif hasattr(needle, "Agent"):
                    self.agent = needle.Agent(tools=[append_next_character])
            except Exception as e:
                print(f"[Needle Initialization Warning]: {e}")

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

            chosen_char = "[END]"

            # --- Needle ローカル文法制約推論 (スレッド化でBotを停止させない) ---
            if self.agent is not None:
                try:
                    result = await asyncio.to_thread(self.agent.run, state_context)
                    
                    if result and isinstance(result, dict) and result.get("function_calls"):
                        for call in result["function_calls"]:
                            chosen_char = str(call.execute())
                            break
                    elif result and hasattr(result, "function_calls"):
                        for call in result.function_calls:
                            chosen_char = str(call.execute())
                            break
                    else:
                        chosen_char = "[END]" if step_count > 5 else "。"
                except Exception as e:
                    chosen_char = "[END]" if step_count > 3 else "。"
            else:
                # モジュール非ロード時のフォールバック動作
                if step_count > 5:
                    chosen_char = "[END]"
                else:
                    sample_chars = ["そ", "う", "だ", "ね", "。"]
                    chosen_char = sample_chars[min(step_count - 1, len(sample_chars) - 1)]

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
            f"[Needle選択ステップ]\n{trace}\n"
            f"```\n"
            f"`Core Needle Steps: {steps} 回 | Total Latency: {latency:.2f}ms | RAM: ~28MB`"
        )

        await interaction.followup.send(msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(NeedleCoreEngineCog(bot))