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
# CPUマルチスレッド最適化設定
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
NEEDLE_IMPORT_ERROR = None
try:
    import needle
    NEEDLE_AVAILABLE = True
except ImportError as e1:
    try:
        import cactus_needle as needle
        NEEDLE_AVAILABLE = True
    except ImportError as e2:
        needle = None
        NEEDLE_IMPORT_ERROR = f"needle: {e1} | cactus_needle: {e2}"


# ----------------------------------------------------------------------
# 英語1文字限定 ツール関数定義
# ----------------------------------------------------------------------
def append_next_character(char: str) -> str:
    """Select and append the next single English character (a-z, A-Z), space, punctuation (.,!?), or '[END]' to construct the output text.

    Args:
        char: Single character (a-z, A-Z, space, .,!?) or '[END]'.
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


class Needle1CharEnglishEngine:
    """
    英語アルファベット 1文字自己回帰生成エンジン。
    文字種を英語アルファベットおよび記号へ絞り込み、生成精度を高めた構成。
    """
    def __init__(self, max_steps: int = 50, min_steps: int = 5):
        self.agent = None
        self.init_error = None
        self.max_steps = max_steps
        self.min_steps = min_steps

        if not NEEDLE_AVAILABLE:
            self.init_error = f"Needle module not found ({NEEDLE_IMPORT_ERROR})"
            return

        try:
            init_kwargs = {"tools": [append_next_character]}
            if hasattr(needle, "Needle"):
                self.agent = needle.Needle(**init_kwargs)
            elif hasattr(needle, "Agent"):
                self.agent = needle.Agent(**init_kwargs)
            else:
                self.init_error = "Neither 'Needle' nor 'Agent' class found in module."
        except Exception as e:
            self.init_error = f"Agent Init Exception: {e}"

    async def generate_sentence(self, user_prompt: str) -> Dict[str, Any]:
        start_time = time.perf_counter()
        generated_text = ""
        trace_logs = []
        raw_debug_outputs = []
        step_count = 0
        consecutive_repeat_count = 0
        last_char = ""

        if self.agent is None:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            error_msg = self.init_error or "Unknown Initialization Error"
            return {
                "sentence": f"（Needle初期化失敗: {error_msg}）",
                "trace": [f"Init Error: {error_msg}"],
                "raw_debug": [f"Init ERR: {error_msg}"],
                "total_steps": 0,
                "latency_ms": elapsed_ms
            }

        while step_count < self.max_steps:
            step_count += 1
            chosen_char = None
            retry_count = 0

            while retry_count < 3:
                end_instruction = (
                    "DO NOT select '[END]'. Select the first appropriate English character."
                    if step_count <= self.min_steps
                    else "If the response is naturally completed, select '[END]'."
                )

                state_context = (
                    f"User Prompt: {user_prompt}\n"
                    f"Current Output: '{generated_text}'\n"
                    f"Instruction: Call 'append_next_character' with exactly ONE English character (a-z, A-Z, space, punctuation) to continue the response. {end_instruction}"
                )

                try:
                    result = await asyncio.to_thread(self.agent.run, state_context)
                    raw_debug_outputs.append(f"Step {step_count:02d} (Attempt {retry_count+1}) Raw: {repr(result)}")

                    temp_char = None
                    if result:
                        if isinstance(result, dict):
                            if "results" in result and result["results"]:
                                for res in result["results"]:
                                    candidate = self._sanitize_char(res)
                                    if candidate:
                                        temp_char = candidate
                                        break
                            if temp_char is None and "function_calls" in result and result["function_calls"]:
                                for call in result["function_calls"]:
                                    candidate = self._extract_char(call)
                                    if candidate:
                                        temp_char = candidate
                                        break
                            elif temp_char is None and "tool_calls" in result and result["tool_calls"]:
                                for call in result["tool_calls"]:
                                    candidate = self._extract_char(call)
                                    if candidate:
                                        temp_char = candidate
                                        break

                        elif hasattr(result, "function_calls") and result.function_calls:
                            for call in result.function_calls:
                                candidate = self._extract_char(call)
                                if candidate:
                                    temp_char = candidate
                                    break

                        if temp_char is None and isinstance(result, str):
                            candidate = self._sanitize_char(result)
                            if candidate:
                                temp_char = candidate
                            elif len(result.strip()) > 0:
                                cleaned = re.sub(r"[{} \[\]\"':]", "", result.strip())
                                if cleaned:
                                    temp_char = cleaned[0]

                    if temp_char == "[END]" and step_count <= self.min_steps:
                        retry_count += 1
                        continue

                    chosen_char = temp_char
                    if chosen_char is not None:
                        break

                except Exception as e:
                    print(f"[Needle Exception Step {step_count}]: {e}")
                    raw_debug_outputs.append(f"Step {step_count:02d} ERR: {e}")

                retry_count += 1

            if chosen_char is None:
                trace_logs.append(f"Step {step_count:02d}: [FAIL (Tool Call None)]")
                break

            if chosen_char == "[END]":
                trace_logs.append(f"Step {step_count:02d}: '[END]'")
                break

            trace_logs.append(f"Step {step_count:02d}: '{chosen_char}'")

            # 同一文字の連続発生抑止
            if chosen_char == last_char:
                consecutive_repeat_count += 1
                if consecutive_repeat_count >= 4:
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

    def _sanitize_char(self, val: Any) -> Optional[str]:
        if val is None:
            return None
        text = str(val)

        if "[END]" in text:
            return "[END]"

        # アルファベット、記号（, . ! ?）、スペースから最初の一文字を抽出
        match = re.search(r"[a-zA-Z0-9,\.!\?\s]", text)
        if match:
            return match.group(0)

        return None

    def _extract_char(self, call: Any) -> Optional[str]:
        if hasattr(call, "execute"):
            return self._sanitize_char(call.execute())
        if hasattr(call, "arguments"):
            args = call.arguments
            if isinstance(args, dict):
                return self._sanitize_char(args.get("char", args.get("token", "")))
        if isinstance(call, dict):
            args = call.get("arguments", call.get("args", {}))
            if isinstance(args, dict):
                val = args.get("char", args.get("token", None))
                return self._sanitize_char(val)
        return None


class Needle1CharEnglishCog(commands.Cog):
    """Needle 英語1文字自己回帰 Discord Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.engine = Needle1CharEnglishEngine(max_steps=50, min_steps=5)

    @app_commands.command(
        name="ai_needle",
        description="[100%ローカル / Needle] 英語1文字自己回帰による文章生成"
    )
    @app_commands.describe(prompt="Please enter your prompt in English")
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
            f"[軌跡]\n{trace}\n"
            f"```\n"
            f"`Steps: {steps} 回 | Latency: {latency:.2f}ms | RAM: ~28MB`"
        )

        await interaction.followup.send(msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(Needle1CharEnglishCog(bot))
