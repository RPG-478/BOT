import os
import sys

# ----------------------------------------------------------------------
# ラズパイ4B（4コア）向け CPUマルチスレッド並列化設定
# 必ず Needle や PyTorch などの C++ バインディングをインポートする前に設定
# ----------------------------------------------------------------------
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["OPENBLAS_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"
os.environ["VECLIB_MAXIMUM_THREADS"] = "4"
os.environ["NUMEXPR_NUM_THREADS"] = "4"

import asyncio
import time
import random
from typing import List, Dict, Any, Literal
import discord
from discord import app_commands
from discord.ext import commands

# PyTorch 等が内部で使われている場合の補強
try:
    import torch
    torch.set_num_threads(4)
    torch.set_num_interop_threads(4)
except ImportError:
    pass

# Needle (Cactus Compute) の安全な読み込み
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

# 50音・標準句読点・疑問符および文章終了トークン [END]
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

def append_next_character(char: HIRAGANA_CHAR_CHOICES) -> str:
    """Append the single next Japanese character or '[END]' to construct the answer.

    Args:
        char: Single Japanese hiragana character or '[END]'.
    """
    return str(char)

# needle.tool デコレータの適用
if NEEDLE_AVAILABLE and hasattr(needle, "tool"):
    try:
        append_next_character = needle.tool(append_next_character)
    except Exception as e:
        print(f"[Needle Tool Register Warning]: {e}")


class NeedleCoreAutoregressiveEngine:
    """
    Needle (100% ローカル / 28MB RAM) を使用した
    1文字自己回帰（Autoregressive）日本語生成エンジン
    """
    def __init__(self):
        self.agent = None
        self.max_steps = 15

        if NEEDLE_AVAILABLE and needle is not None:
            try:
                init_kwargs = {"tools": [append_next_character]}
                
                if hasattr(needle, "Needle"):
                    self.agent = needle.Needle(**init_kwargs)
                elif hasattr(needle, "Agent"):
                    self.agent = needle.Agent(**init_kwargs)
            except Exception as e:
                print(f"[Needle Engine Init Error]: {e}")

    async def generate_sentence(self, user_prompt: str) -> Dict[str, Any]:
        start_time = time.perf_counter()
        
        generated_text = ""
        trace_logs = []
        step_count = 0
        raw_debug_outputs = []

        while step_count < self.max_steps:
            step_count += 1
            
            # --- Needleへのシンプルな指示プロンプト ---
            state_context = (
                f"User question: {user_prompt}\n"
                f"Current text: {generated_text}\n"
                f"Call append_next_character with the single next character to answer naturally."
            )

            chosen_char = None

            if self.agent is not None:
                try:
                    # バックグラウンドスレッドでNeedle推論を実行
                    result = await asyncio.to_thread(self.agent.run, state_context)
                    
                    # 生のレスポンスログを保存
                    raw_debug_outputs.append(f"Step {step_count}: {repr(result)}")
                    
                    # 戻り値の解析
                    if result:
                        if isinstance(result, dict) and result.get("function_calls"):
                            for call in result["function_calls"]:
                                chosen_char = str(call.execute())
                                break
                        elif hasattr(result, "function_calls") and result.function_calls:
                            for call in result.function_calls:
                                chosen_char = str(call.execute())
                                break
                        elif isinstance(result, str):
                            # 文字列で直接返ってきた場合の抽出
                            for c in result:
                                if c in HIRAGANA_CHAR_CHOICES.__args__:
                                    chosen_char = c
                                    break
                except Exception as e:
                    print(f"[Needle Exception Step {step_count}]: {e}")
                    raw_debug_outputs.append(f"Step {step_count} ERR: {e}")

            # ツール呼び出しに失敗した場合（[FAIL]と明記して原因追究）
            if chosen_char is None:
                trace_logs.append(f"Step {step_count:02d}: [FAIL (Tool Call None)]")
                # 原因特定のために1回失敗したら即時中断
                break

            trace_logs.append(f"Step {step_count:02d}: '{chosen_char}'")

            if chosen_char == "[END]":
                break

            generated_text += chosen_char

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return {
            "sentence": generated_text if generated_text else "（Needleツール呼出失敗）",
            "trace": trace_logs,
            "raw_debug": raw_debug_outputs,
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
        await interaction.response.defer()

        res = await self.engine.generate_sentence(prompt)

        sentence = res["sentence"]
        steps = res["total_steps"]
        latency = res["latency_ms"]
        trace = " ➔ ".join([t for t in res["trace"]])
        
        # コンソールログに生のNeedle戻り値を表示
        print("\n=== [Needle Raw Output Trace] ===")
        for dbg in res["raw_debug"]:
            print(dbg)
        print("=================================\n")

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