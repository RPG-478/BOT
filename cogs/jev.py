import os
import sys
import re
import asyncio
import time
from enum import Enum
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
# 大量基本単語 Enum（列挙型）定義 (100語超)
# ----------------------------------------------------------------------
class WordChoice(str, Enum):
    # 挨拶・感嘆詞
    HELLO = "HELLO"
    HI = "HI"
    THANKS = "THANKS"
    THANK_YOU = "THANK YOU"
    PLEASE = "PLEASE"
    YES = "YES"
    NO = "NO"
    OK = "OK"
    BYE = "BYE"
    GOODBYE = "GOODBYE"
    SORRY = "SORRY"
    WELCOME = "WELCOME"
    GREAT = "GREAT"
    NICE = "NICE"

    # 代名詞
    I = "I"
    YOU = "YOU"
    HE = "HE"
    SHE = "SHE"
    IT = "IT"
    WE = "WE"
    THEY = "THEY"
    THIS = "THIS"
    THAT = "THAT"
    MY = "MY"
    YOUR = "YOUR"
    HIS = "HIS"
    HER = "HER"
    OUR = "OUR"
    ME = "ME"
    HIM = "HIM"
    US = "US"
    THEM = "THEM"
    WHAT = "WHAT"
    WHO = "WHO"
    WHERE = "WHERE"
    WHEN = "WHEN"
    WHY = "WHY"
    HOW = "HOW"

    # 助動詞・b動詞
    AM = "AM"
    IS = "IS"
    ARE = "ARE"
    WAS = "WAS"
    WERE = "WERE"
    BE = "BE"
    DO = "DO"
    DOES = "DOES"
    DID = "DID"
    CAN = "CAN"
    COULD = "COULD"
    WILL = "WILL"
    WOULD = "WOULD"
    MUST = "MUST"
    SHOULD = "SHOULD"
    HAVE = "HAVE"
    HAS = "HAS"
    HAD = "HAD"

    # 主要動詞
    GO = "GO"
    COME = "COME"
    SEE = "SEE"
    KNOW = "KNOW"
    THINK = "THINK"
    MAKE = "MAKE"
    TAKE = "TAKE"
    GET = "GET"
    WANT = "WANT"
    LIKE = "LIKE"
    HELP = "HELP"
    NEED = "NEED"
    USE = "USE"
    FIND = "FIND"
    SAY = "SAY"
    TELL = "TELL"
    WORK = "WORK"

    # 名詞
    TIME = "TIME"
    DAY = "DAY"
    TODAY = "TODAY"
    NAME = "NAME"
    FRIEND = "FRIEND"
    BOT = "BOT"
    AI = "AI"
    USER = "USER"
    THING = "THING"
    WORLD = "WORLD"
    SYSTEM = "SYSTEM"

    # 形容詞・副詞
    GOOD = "GOOD"
    BAD = "BAD"
    BEST = "BEST"
    NEW = "NEW"
    OLD = "OLD"
    BIG = "BIG"
    SMALL = "SMALL"
    VERY = "VERY"
    SO = "SO"
    WELL = "WELL"
    NOW = "NOW"
    HERE = "HERE"
    THERE = "THERE"
    ALWAYS = "ALWAYS"
    NEVER = "NEVER"
    AGAIN = "AGAIN"

    # 前置詞・接続詞・記号
    IN = "IN"
    ON = "ON"
    AT = "AT"
    TO = "TO"
    FOR = "FOR"
    WITH = "WITH"
    ABOUT = "ABOUT"
    BY = "BY"
    FROM = "FROM"
    AND = "AND"
    BUT = "BUT"
    OR = "OR"
    IF = "IF"
    BECAUSE = "BECAUSE"
    PERIOD = "."
    COMMA = ","
    QUESTION = "?"
    EXCLAMATION = "!"

    # 終了識別子
    END = "[END]"


def append_next_word(word: WordChoice) -> str:
    """Select and append the single best word or token from the WordChoice Enum to build the sentence naturally.

    Args:
        word: The selected word, token, or '[END]' from the permitted Enum choices.
    """
    return str(word.value if isinstance(word, WordChoice) else word)


if NEEDLE_AVAILABLE and hasattr(needle, "tool"):
    try:
        append_next_word = needle.tool(triggers=[r".*"])(append_next_word)
    except Exception:
        try:
            append_next_word = needle.tool(append_next_word)
        except Exception as e:
            print(f"[Needle Tool Register Warning]: {e}")


class NeedleWordEnumEngine:
    """
    100語超の基本単語 Enum スキーマに基づく単語自己回帰生成エンジン。
    """
    def __init__(self, max_steps: int = 20, min_steps: int = 2):
        self.agent = None
        self.init_error = None
        self.max_steps = max_steps
        self.min_steps = min_steps

        if not NEEDLE_AVAILABLE:
            self.init_error = f"Needle module not found ({NEEDLE_IMPORT_ERROR})"
            return

        try:
            init_kwargs = {"tools": [append_next_word]}
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
        generated_words: List[str] = []
        trace_logs = []
        raw_debug_outputs = []
        step_count = 0
        consecutive_repeat_count = 0
        last_word = ""

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
            chosen_word = None
            retry_count = 0

            current_text = " ".join(generated_words)

            while retry_count < 3:
                state_context = (
                    f"User Prompt: {user_prompt}\n"
                    f"Current Output: '{current_text}'\n"
                    f"Action: Call 'append_next_word' selecting the single best WordChoice to logically continue the sentence."
                )

                try:
                    result = await asyncio.to_thread(self.agent.run, state_context)
                    raw_debug_outputs.append(f"Step {step_count:02d} (Attempt {retry_count+1}) Raw: {repr(result)}")

                    temp_word = None
                    if result:
                        if isinstance(result, dict):
                            if "results" in result and result["results"]:
                                for res in result["results"]:
                                    candidate = self._parse_enum_value(res)
                                    if candidate:
                                        temp_word = candidate
                                        break
                            if temp_word is None and "function_calls" in result and result["function_calls"]:
                                for call in result["function_calls"]:
                                    candidate = self._extract_enum(call)
                                    if candidate:
                                        temp_word = candidate
                                        break
                            elif temp_word is None and "tool_calls" in result and result["tool_calls"]:
                                for call in result["tool_calls"]:
                                    candidate = self._extract_enum(call)
                                    if candidate:
                                        temp_word = candidate
                                        break

                        elif hasattr(result, "function_calls") and result.function_calls:
                            for call in result.function_calls:
                                candidate = self._extract_enum(call)
                                if candidate:
                                    temp_word = candidate
                                    break

                        if temp_word is None and isinstance(result, str):
                            temp_word = self._parse_enum_value(result)

                    if temp_word == "[END]" and step_count <= self.min_steps:
                        retry_count += 1
                        continue

                    chosen_word = temp_word
                    if chosen_word is not None:
                        break

                except Exception as e:
                    print(f"[Needle Exception Step {step_count}]: {e}")
                    raw_debug_outputs.append(f"Step {step_count:02d} ERR: {e}")

                retry_count += 1

            if chosen_word is None:
                trace_logs.append(f"Step {step_count:02d}: [FAIL (Tool Call None)]")
                break

            if chosen_word == "[END]":
                trace_logs.append(f"Step {step_count:02d}: '[END]'")
                break

            trace_logs.append(f"Step {step_count:02d}: '{chosen_word}'")

            # 単語ループ検知
            if chosen_word == last_word:
                consecutive_repeat_count += 1
                if consecutive_repeat_count >= 2:
                    trace_logs.append(f"Step {step_count:02d}: [LOOP DETECTED - FORCED END]")
                    break
            else:
                consecutive_repeat_count = 0
                last_word = chosen_word

            generated_words.append(chosen_word)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        # 記号の前後のスペース整形
        final_sentence = " ".join(generated_words)
        final_sentence = re.sub(r"\s+([.,!?])", r"\1", final_sentence)

        return {
            "sentence": final_sentence if final_sentence else "（Needleツール呼出失敗）",
            "trace": trace_logs,
            "raw_debug": raw_debug_outputs,
            "total_steps": step_count,
            "latency_ms": elapsed_ms
        }

    def _parse_enum_value(self, val: Any) -> Optional[str]:
        if val is None:
            return None
        if isinstance(val, WordChoice):
            return val.value

        text = str(val).strip()

        # Enum のキー名（例: "HELLO", "THANK_YOU"）直接指定時のマッピング
        if text in WordChoice.__members__:
            return WordChoice[text].value

        # Enum の値直接指定時のマッピング
        for item in WordChoice:
            if item.value == text or item.value == text.upper():
                return item.value

        return None

    def _extract_enum(self, call: Any) -> Optional[str]:
        if hasattr(call, "execute"):
            return self._parse_enum_value(call.execute())
        if hasattr(call, "arguments"):
            args = call.arguments
            if isinstance(args, dict):
                return self._parse_enum_value(args.get("word", args.get("char", args.get("token", ""))))
        if isinstance(call, dict):
            args = call.get("arguments", call.get("args", {}))
            if isinstance(args, dict):
                val = args.get("word", args.get("char", args.get("token", None)))
                return self._parse_enum_value(val)
        return None


class NeedleWordEnumCog(commands.Cog):
    """Needle 単語 Enum 選択式自己回帰 Discord Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.engine = NeedleWordEnumEngine(max_steps=20, min_steps=2)

    @app_commands.command(
        name="ai_needle",
        description="[100%ローカル / Needle] 単語Enum選択による自己回帰文章生成"
    )
    @app_commands.describe(prompt="プロンプトを入力してください")
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
            f"[Needle 単語選択軌跡]\n{trace}\n"
            f"```\n"
            f"`⚡ Steps: {steps} 回 | Latency: {latency:.2f}ms | RAM: ~28MB`"
        )

        await interaction.followup.send(msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(NeedleWordEnumCog(bot))
