import os
import sys
import re

# ----------------------------------------------------------------------
# ラズパイ4B（4コア）向け CPUマルチスレッド並列化設定
# ----------------------------------------------------------------------
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["OPENBLAS_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"
os.environ["VECLIB_MAXIMUM_THREADS"] = "4"
os.environ["NUMEXPR_NUM_THREADS"] = "4"

import asyncio
import time
from typing import List, Dict, Any
import discord
from discord import app_commands
from discord.ext import commands

# PyTorch 等のスレッド補強
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

# 1文字追加ツール
# triggers=[r".*"] を指定することで、Needleの確信度フィルタを迂回し、常にこのツールを発火させます
def append_next_character(char: str) -> str:
    """Select and append the single next Japanese hiragana character, punctuation (、。？), or '[END]' to naturally build the output sentence.

    Args:
        char: Single Japanese character or punctuation or '[END]'.
    """
    return str(char)

# needle.tool デコレータの適用 (triggers パターンマッチで強制呼び出しを有効化)
if NEEDLE_AVAILABLE and hasattr(needle, "tool"):
    try:
        append_next_character = needle.tool(triggers=[r".*"])(append_next_character)
    except Exception:
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
            
            # --- Needleへの指示文脈 (引数 char に選ばせたい文字が抽出されやすいシンプルな構成) ---
            state_context = (
                f"User: {user_prompt}\n"
                f"Generated text so far: '{generated_text}'\n"
                f"Select next char to append:"
            )

            chosen_char = None

            if self.agent is not None:
                try:
                    # バックグラウンドスレッドでNeedle推論を実行
                    result = await asyncio.to_thread(self.agent.run, state_context)
                    
                    # 生のレスポンスログを保存
                    raw_debug_outputs.append(f"Step {step_count:02d} Raw: {repr(result)}")
                    
                    # 1. 正常な Tool Call / Results オブジェクトの解析
                    if result:
                        if isinstance(result, dict):
                            # results (実行済み戻り値) の確認
                            if "results" in result and result["results"]:
                                for res in result["results"]:
                                    if res is not None:
                                        chosen_char = str(res)
                                        break
                            # function_calls / tool_calls の解析
                            if chosen_char is None and "function_calls" in result and result["function_calls"]:
                                for call in result["function_calls"]:
                                    if hasattr(call, "execute"):
                                        chosen_char = str(call.execute())
                                    elif hasattr(call, "arguments") and "char" in call.arguments:
                                        chosen_char = str(call.arguments["char"])
                                    elif isinstance(call, dict):
                                        args = call.get("arguments", call.get("args", {}))
                                        if "char" in args:
                                            chosen_char = str(args["char"])
                                    break
                            elif chosen_char is None and "tool_calls" in result and result["tool_calls"]:
                                for call in result["tool_calls"]:
                                    if hasattr(call, "execute"):
                                        chosen_char = str(call.execute())
                                    elif isinstance(call, dict) and "arguments" in call:
                                        chosen_char = str(call["arguments"].get("char", ""))
                                    break

                        elif hasattr(result, "function_calls") and result.function_calls:
                            for call in result.function_calls:
                                chosen_char = str(call.execute())
                                break

                        # 2. テキスト・文字列として返ってきた場合のフォールバックパース
                        if chosen_char is None and isinstance(result, str):
                            if "[END]" in result:
                                chosen_char = "[END]"
                            else:
                                match = re.search(r"['\"]?([^'\"\)\s]{1,5})['\"]?", result)
                                if match:
                                    chosen_char = match.group(1)[0]

                except Exception as e:
                    print(f"[Needle Exception Step {step_count}]: {e}")
                    raw_debug_outputs.append(f"Step {step_count:02d} ERR: {e}")

            # 抽出失敗時のトラッキング
            if chosen_char is None:
                trace_logs.append(f"Step {step_count:02d}: [FAIL (Tool Call None)]")
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
            f"[ステップ軌跡]\n{trace}\n"
            f"```\n"
            f"`Core Needle Steps: {steps} 回 | Total Latency: {latency:.2f}ms | RAM: ~28MB`"
        )

        await interaction.followup.send(msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(NeedleCoreEngineCog(bot))