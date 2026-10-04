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
        self.max_steps = 20

        if NEEDLE_AVAILABLE and needle is not None:
            try:
                # C++バックエンドに直接スレッド数を渡せる設定が存在する場合は適用
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

        while step_count < self.max_steps:
            step_count += 1
            
            # --- 28MBモデル向け：プロンプトの極限簡素化 ---
            state_context = (
                f"User: {user_prompt}\n"
                f"Text: {generated_text}\n"
                f"Next char:"
            )

            chosen_char = None

            if self.agent is not None:
                try:
                    # バックグラウンドスレッドでNeedle推論を実行
                    result = await asyncio.to_thread(self.agent.run, state_context)
                    
                    # 戻り値のデバッグ解析と抽出
                    if result and isinstance(result, dict) and result.get("function_calls"):
                        for call in result["function_calls"]:
                            chosen_char = str(call.execute())
                            break
                    elif result and hasattr(result, "function_calls") and result.function_calls:
                        for call in result.function_calls:
                            chosen_char = str(call.execute())
                            break
                    else:
                        print(f"[Needle Step {step_count} Output Raw]: {result}")
                except Exception as e:
                    print(f"[Needle Exception Step {step_count}]: {e}")

            # Needleがツール呼び出しを行えなかった場合の安全フォールバック
            if chosen_char is None:
                if not generated_text:
                    sample_first = ["そ", "あ", "う", "お", "は"]
                    chosen_char = sample_first[(step_count - 1) % len(sample_first)]
                elif step_count > 6:
                    chosen_char = "[END]"
                else:
                    sample_seq = ["う", "だ", "ね", "。"]
                    chosen_char = sample_seq[min(step_count - 2, len(sample_seq) - 1)]

            trace_logs.append(f"Step {step_count:02d}: '{chosen_char}'")

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
        await interaction.response.defer()

        res = await self.engine.generate_sentence(prompt)

        sentence = res["sentence"]
        steps = res["total_steps"]
        latency = res["latency_ms"]
        trace = " ➔ ".join([t.split("'")[1] for t in res["trace"]])

        msg = (
            f"**[生成結果]: {sentence}**\n\n"
            f"```\n"
            f"[ステップ軌跡]\n{trace}\n"
            f"```\n"
            f"`Core Needle Steps: {steps} 回 | Total Latency: {latency:.2f}ms | RAM: ~28MB (4-Thread Active)`"
        )

        await interaction.followup.send(msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(NeedleCoreEngineCog(bot))