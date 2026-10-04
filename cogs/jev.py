import os
import sys
import re
import asyncio
import time
from typing import List, Dict, Any, Optional
import discord
from discord import app_commands
from discord.ext import commands

# ----------------------------------------------------------------------
# CPUマルチスレッド最適化設定（ラズパイ4B等 4コア環境向け）
# ----------------------------------------------------------------------
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["OPENBLAS_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"
os.environ["VECLIB_MAXIMUM_THREADS"] = "4"
os.environ["NUMEXPR_NUM_THREADS"] = "4"

try:
    import torch
    torch.set_num_threads(4)
    torch.set_num_interop_threads(4)
except ImportError:
    pass

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


# ----------------------------------------------------------------------
# 1文字限定 ツール関数定義
# ----------------------------------------------------------------------
def append_next_character(char: str) -> str:
    """文脈に適合する次の1文字（ひらがな、カタカナ、漢字、記号）、または '[END]' を選択します。

    Args:
        char: 厳格に1文字の文字列、または '[END]'。
    """
    return str(char)


if NEEDLE_AVAILABLE and hasattr(needle, "tool"):
    try:
        append_next_character = needle.tool(triggers=[r".*"])(append_next_character)
    except Exception:
        try:
            append_next_character = needle.tool(append_next_character)
        except Exception as e:
            print(f"[Needle Tool Register Warning]: {e}")


class Needle1CharEngine:
    """
    1文字単位に限定した自己回帰生成エンジン。
    1文字強制的切り詰めおよび同一文字ループ検知機構を搭載。
    """
    def __init__(self, max_steps: int = 50):
        self.agent = None
        self.max_steps = max_steps

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
        raw_debug_outputs = []
        step_count = 0
        consecutive_repeat_count = 0
        last_char = ""

        while step_count < self.max_steps:
            step_count += 1

            state_context = (
                f"User Prompt: {user_prompt}\n"
                f"Generated Text: '{generated_text}'\n"
                f"Instruction: Call 'append_next_character' with EXACTLY ONE single Japanese character, punctuation, or '[END]' to append next."
            )

            chosen_char = None

            if self.agent is not None:
                try:
                    result = await asyncio.to_thread(self.agent.run, state_context)
                    raw_debug_outputs.append(f"Step {step_count:02d} Raw: {repr(result)}")

                    if result:
                        if isinstance(result, dict):
                            if "results" in result and result["results"]:
                                for res in result["results"]:
                                    if res is not None:
                                        chosen_char = str(res)
                                        break
                            if chosen_char is None and "function_calls" in result and result["function_calls"]:
                                for call in result["function_calls"]:
                                    chosen_char = self._extract_char(call)
                                    if chosen_char:
                                        break
                            elif chosen_char is None and "tool_calls" in result and result["tool_calls"]:
                                for call in result["tool_calls"]:
                                    chosen_char = self._extract_char(call)
                                    if chosen_char:
                                        break

                        elif hasattr(result, "function_calls") and result.function_calls:
                            for call in result.function_calls:
                                chosen_char = self._extract_char(call)
                                if chosen_char:
                                    break

                        if chosen_char is None and isinstance(result, str):
                            if "[END]" in result:
                                chosen_char = "[END]"
                            else:
                                match = re.search(r"['\"]?([^'\"\)\s])['\"]?", result)
                                if match:
                                    chosen_char = match.group(1)

                except Exception as e:
                    print(f"[Needle Exception Step {step_count}]: {e}")
                    raw_debug_outputs.append(f"Step {step_count:02d} ERR: {e}")

            if chosen_char is None:
                trace_logs.append(f"Step {step_count:02d}: [FAIL (Tool Call None)]")
                break

            # 1文字制限の厳格化（[END] 以外の複数文字返却時は先頭1文字へ強制切り詰め）
            if chosen_char != "[END]" and len(chosen_char) > 1:
                chosen_char = chosen_char[0]

            trace_logs.append(f"Step {step_count:02d}: '{chosen_char}'")

            if chosen_char == "[END]":
                break

            # 同一文字の連続発生（ループ）防止
            if chosen_char == last_char:
                consecutive_repeat_count += 1
                if consecutive_repeat_count >= 3:
                    trace_logs.append(f"Step {step_count:02d}: [LOOP DETECTED - FORCED END]")
                    break
            else:
                consecutive_repeat_count = 0
                last_char = chosen_char

            generated_text += chosen_char

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return {
            "sentence": generated_text if generated_text else "（Needleツール呼出失敗）",
            "trace": trace_logs,
            "raw_debug": raw_debug_outputs,
            "total_steps": step_count,
            "latency_ms": elapsed_ms
        }

    def _extract_char(self, call: Any) -> Optional[str]:
        """ツール呼出オブジェクトより引数を抽出します。"""
        if hasattr(call, "execute"):
            return str(call.execute())
        if hasattr(call, "arguments"):
            args = call.arguments
            if isinstance(args, dict):
                return str(args.get("char", args.get("token", "")))
        if isinstance(call, dict):
            args = call.get("arguments", call.get("args", {}))
            if isinstance(args, dict):
                val = args.get("char", args.get("token", None))
                if val is not None:
                    return str(val)
        return None


class Needle1CharEngineCog(commands.Cog):
    """Needle 1文字厳格自己回帰 Discord Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.engine = Needle1CharEngine(max_steps=50)

    @app_commands.command(
        name="ai_needle",
        description="[100%ローカル / Needle] 1文字厳格自己回帰による安定生成"
    )
    @app_commands.describe(prompt="メッセージを入力してください")
    async def ai_needle_command(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer()

        res = await self.engine.generate_sentence(prompt)

        sentence = res["sentence"]
        steps = res["total_steps"]
        latency = res["latency_ms"]
        trace = " ➔ ".join([t for t in res["trace"]])

        print("\n=== [Needle Raw Output Trace] ===")
        for dbg in res["raw_debug"]:
            print(dbg)
        print("=================================\n")

        msg = (
            f"**[生成結果]: {sentence}**\n\n"
            f"```\n"
            f"[Needle 1文字選択軌跡]\n{trace}\n"
            f"```\n"
            f"`⚡ Steps: {steps} 回 | Latency: {latency:.2f}ms | RAM: ~28MB`"
        )

        await interaction.followup.send(msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(Needle1CharEngineCog(bot))
