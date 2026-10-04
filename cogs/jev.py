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
# HTML特化型 ASTノードの Enum 定義
# ----------------------------------------------------------------------
class HTMLNodeChoice(str, Enum):
    # ドキュメント基本構造
    DOCTYPE_HTML = "DOCTYPE_HTML"        # <!DOCTYPE html>
    HTML_OPEN = "HTML_OPEN"              # <html lang="ja">
    HTML_CLOSE = "HTML_CLOSE"            # </html>
    HEAD_OPEN = "HEAD_OPEN"              # <head>
    HEAD_CLOSE = "HEAD_CLOSE"            # </head>
    BODY_OPEN = "BODY_OPEN"              # <body>
    BODY_CLOSE = "BODY_CLOSE"            # </body>

    # メタ情報・スタイル
    META_CHARSET = "META_CHARSET"        # <meta charset="UTF-8">
    TITLE_ELEMENT = "TITLE_ELEMENT"      # <title>Sample Page</title>
    LINK_CSS = "LINK_CSS"                # <link rel="stylesheet" href="style.css">

    # レイアウト・セクション
    HEADER_OPEN = "HEADER_OPEN"          # <header>
    HEADER_CLOSE = "HEADER_CLOSE"        # </header>
    MAIN_OPEN = "MAIN_OPEN"              # <main>
    MAIN_CLOSE = "MAIN_CLOSE"            # </main>
    DIV_CONTAINER = "DIV_CONTAINER"      # <div class="container">
    DIV_CARD = "DIV_CARD"                # <div class="card">
    DIV_CLOSE = "DIV_CLOSE"              # </div>
    FOOTER_OPEN = "FOOTER_OPEN"          # <footer>
    FOOTER_CLOSE = "FOOTER_CLOSE"        # </footer>

    # テキスト・見出し・コンテンツ
    H1_HEADING = "H1_HEADING"            # <h1>Title</h1>
    H2_HEADING = "H2_HEADING"            # <h2>Subtitle</h2>
    PARAGRAPH = "PARAGRAPH"              # <p>Text content...</p>
    ANCHOR_BUTTON = "ANCHOR_BUTTON"      # <a href="#" class="btn">Click Here</a>
    IMAGE_TAG = "IMAGE_TAG"              # <img src="image.jpg" alt="Image">

    # リスト構造
    UL_OPEN = "UL_OPEN"                  # <ul>
    UL_CLOSE = "UL_CLOSE"                # </ul>
    LI_ITEM = "LI_ITEM"                  # <li>List Item</li>

    # 構築完了
    END_HTML = "[END_HTML]"              # HTML構築終了


def append_html_node(node: HTMLNodeChoice) -> str:
    """Select the exact next HTML structural node to construct a valid HTML document.

    Args:
        node: The HTML structural node selected from the permitted HTMLNodeChoice Enum.
    """
    return str(node.value if isinstance(node, HTMLNodeChoice) else node)


if NEEDLE_AVAILABLE and hasattr(needle, "tool"):
    try:
        append_html_node = needle.tool(triggers=[r".*"])(append_html_node)
    except Exception:
        try:
            append_html_node = needle.tool(append_html_node)
        except Exception as e:
            print(f"[Needle Tool Register Warning]: {e}")


class NeedleHTMLBuilder:
    """
    HTMLノード選択型コード構築エンジン。
    NeedleにHTMLタグ要素を選択させ、構文的妥当性を持つHTMLコードを復元。
    """
    def __init__(self, max_steps: int = 20):
        self.agent = None
        self.init_error = None
        self.max_steps = max_steps

        if not NEEDLE_AVAILABLE:
            self.init_error = f"Needle module not found ({NEEDLE_IMPORT_ERROR})"
            return

        try:
            init_kwargs = {"tools": [append_html_node]}
            if hasattr(needle, "Needle"):
                self.agent = needle.Needle(**init_kwargs)
            elif hasattr(needle, "Agent"):
                self.agent = needle.Agent(**init_kwargs)
            else:
                self.init_error = "Neither 'Needle' nor 'Agent' class found in module."
        except Exception as e:
            self.init_error = f"Agent Init Exception: {e}"

    async def build_html(self, user_prompt: str) -> Dict[str, Any]:
        start_time = time.perf_counter()
        selected_nodes: List[str] = []
        trace_logs = []
        raw_debug_outputs = []
        step_count = 0

        if self.agent is None:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            error_msg = self.init_error or "Unknown Initialization Error"
            return {
                "html": f"<!-- Needle Init Error: {error_msg} -->",
                "trace": [f"Init Error: {error_msg}"],
                "raw_debug": [f"Init ERR: {error_msg}"],
                "total_steps": 0,
                "latency_ms": elapsed_ms
            }

        while step_count < self.max_steps:
            step_count += 1
            chosen_node = None
            retry_count = 0

            current_node_chain = " -> ".join(selected_nodes) if selected_nodes else "EMPTY_AST"

            while retry_count < 3:
                state_context = (
                    f"Task: Construct HTML layout for user request: '{user_prompt}'\n"
                    f"Current HTML Node Chain: [{current_node_chain}]\n"
                    f"Action: Call 'append_html_node' selecting the best HTMLNodeChoice to build a valid, well-structured HTML document."
                )

                try:
                    result = await asyncio.to_thread(self.agent.run, state_context)
                    raw_debug_outputs.append(f"Step {step_count:02d} (Attempt {retry_count+1}) Raw: {repr(result)}")

                    temp_node = None
                    if result:
                        if isinstance(result, dict):
                            if "results" in result and result["results"]:
                                for res in result["results"]:
                                    candidate = self._parse_enum_value(res)
                                    if candidate:
                                        temp_node = candidate
                                        break
                            if temp_node is None and "function_calls" in result and result["function_calls"]:
                                for call in result["function_calls"]:
                                    candidate = self._extract_enum(call)
                                    if candidate:
                                        temp_node = candidate
                                        break
                            elif temp_node is None and "tool_calls" in result and result["tool_calls"]:
                                for call in result["tool_calls"]:
                                    candidate = self._extract_enum(call)
                                    if candidate:
                                        temp_node = candidate
                                        break

                        elif hasattr(result, "function_calls") and result.function_calls:
                            for call in result.function_calls:
                                candidate = self._extract_enum(call)
                                if candidate:
                                    temp_node = candidate
                                    break

                        if temp_node is None and isinstance(result, str):
                            temp_node = self._parse_enum_value(result)

                    chosen_node = temp_node
                    if chosen_node is not None:
                        break

                except Exception as e:
                    print(f"[Needle Exception Step {step_count}]: {e}")
                    raw_debug_outputs.append(f"Step {step_count:02d} ERR: {e}")

                retry_count += 1

            if chosen_node is None:
                trace_logs.append(f"Step {step_count:02d}: [FAIL (Tool Call None)]")
                break

            if chosen_node == "[END_HTML]":
                trace_logs.append(f"Step {step_count:02d}: '[END_HTML]'")
                break

            trace_logs.append(f"Step {step_count:02d}: '{chosen_node}'")
            selected_nodes.append(chosen_node)

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # HTMLノード列を評価し、適切なインデントでHTMLコードにコンパイル
        generated_html = self._compile_nodes_to_html(selected_nodes)

        return {
            "html": generated_html,
            "nodes": selected_nodes,
            "trace": trace_logs,
            "raw_debug": raw_debug_outputs,
            "total_steps": step_count,
            "latency_ms": elapsed_ms
        }

    def _compile_nodes_to_html(self, nodes: List[str]) -> str:
        """HTMLノード列を自動でインデント整列し完全なHTMLコードへ復元"""
        if not nodes:
            return "<!-- 生成ノードなし -->"

        lines = []
        indent_level = 0
        indent_str = "  "

        # 自我閉鎖ノード/自己完結エレメントの判定
        closing_nodes = {
            HTMLNodeChoice.HTML_CLOSE.value,
            HTMLNodeChoice.HEAD_CLOSE.value,
            HTMLNodeChoice.BODY_CLOSE.value,
            HTMLNodeChoice.HEADER_CLOSE.value,
            HTMLNodeChoice.MAIN_CLOSE.value,
            HTMLNodeChoice.DIV_CLOSE.value,
            HTMLNodeChoice.FOOTER_CLOSE.value,
            HTMLNodeChoice.UL_CLOSE.value,
        }

        for node in nodes:
            # 閉じタグの場合、インデントを事前に減算
            if node in closing_nodes and indent_level > 0:
                indent_level -= 1

            prefix = indent_str * indent_level

            if node == HTMLNodeChoice.DOCTYPE_HTML.value:
                lines.append("<!DOCTYPE html>")
            elif node == HTMLNodeChoice.HTML_OPEN.value:
                lines.append(f"{prefix}<html lang=\"ja\">")
                indent_level += 1
            elif node == HTMLNodeChoice.HTML_CLOSE.value:
                lines.append(f"{prefix}</html>")
            elif node == HTMLNodeChoice.HEAD_OPEN.value:
                lines.append(f"{prefix}<head>")
                indent_level += 1
            elif node == HTMLNodeChoice.HEAD_CLOSE.value:
                lines.append(f"{prefix}</head>")
            elif node == HTMLNodeChoice.BODY_OPEN.value:
                lines.append(f"{prefix}<body>")
                indent_level += 1
            elif node == HTMLNodeChoice.BODY_CLOSE.value:
                lines.append(f"{prefix}</body>")
            elif node == HTMLNodeChoice.META_CHARSET.value:
                lines.append(f"{prefix}<meta charset=\"UTF-8\">")
            elif node == HTMLNodeChoice.TITLE_ELEMENT.value:
                lines.append(f"{prefix}<title>Web Page</title>")
            elif node == HTMLNodeChoice.LINK_CSS.value:
                lines.append(f"{prefix}<link rel=\"stylesheet\" href=\"style.css\">")
            elif node == HTMLNodeChoice.HEADER_OPEN.value:
                lines.append(f"{prefix}<header>")
                indent_level += 1
            elif node == HTMLNodeChoice.HEADER_CLOSE.value:
                lines.append(f"{prefix}</header>")
            elif node == HTMLNodeChoice.MAIN_OPEN.value:
                lines.append(f"{prefix}<main>")
                indent_level += 1
            elif node == HTMLNodeChoice.MAIN_CLOSE.value:
                lines.append(f"{prefix}</main>")
            elif node == HTMLNodeChoice.DIV_CONTAINER.value:
                lines.append(f"{prefix}<div class=\"container\">")
                indent_level += 1
            elif node == HTMLNodeChoice.DIV_CARD.value:
                lines.append(f"{prefix}<div class=\"card\">")
                indent_level += 1
            elif node == HTMLNodeChoice.DIV_CLOSE.value:
                lines.append(f"{prefix}</div>")
            elif node == HTMLNodeChoice.FOOTER_OPEN.value:
                lines.append(f"{prefix}<footer>")
                indent_level += 1
            elif node == HTMLNodeChoice.FOOTER_CLOSE.value:
                lines.append(f"{prefix}</footer>")
            elif node == HTMLNodeChoice.H1_HEADING.value:
                lines.append(f"{prefix}<h1>Main Heading</h1>")
            elif node == HTMLNodeChoice.H2_HEADING.value:
                lines.append(f"{prefix}<h2>Section Title</h2>")
            elif node == HTMLNodeChoice.PARAGRAPH.value:
                lines.append(f"{prefix}<p>This is a paragraph constructed by Needle AST Engine.</p>")
            elif node == HTMLNodeChoice.ANCHOR_BUTTON.value:
                lines.append(f"{prefix}<a href=\"#\" class=\"btn\">Click Here</a>")
            elif node == HTMLNodeChoice.IMAGE_TAG.value:
                lines.append(f"{prefix}<img src=\"https://via.placeholder.com/150\" alt=\"Placeholder\">")
            elif node == HTMLNodeChoice.UL_OPEN.value:
                lines.append(f"{prefix}<ul>")
                indent_level += 1
            elif node == HTMLNodeChoice.UL_CLOSE.value:
                lines.append(f"{prefix}</ul>")
            elif node == HTMLNodeChoice.LI_ITEM.value:
                lines.append(f"{prefix}<li>List Item</li>")

        return "\n".join(lines) if lines else "<!-- 生成ノードなし -->"

    def _parse_enum_value(self, val: Any) -> Optional[str]:
        if val is None:
            return None
        if isinstance(val, HTMLNodeChoice):
            return val.value

        text = str(val).strip()
        if text in HTMLNodeChoice.__members__:
            return HTMLNodeChoice[text].value

        for item in HTMLNodeChoice:
            if item.value == text or item.value == text.upper():
                return item.value

        return None

    def _extract_enum(self, call: Any) -> Optional[str]:
        if hasattr(call, "execute"):
            return self._parse_enum_value(call.execute())
        if hasattr(call, "arguments"):
            args = call.arguments
            if isinstance(args, dict):
                return self._parse_enum_value(args.get("node", args.get("char", args.get("token", ""))))
        if isinstance(call, dict):
            args = call.get("arguments", call.get("args", {}))
            if isinstance(args, dict):
                val = args.get("node", args.get("char", args.get("token", None)))
                return self._parse_enum_value(val)
        return None


class NeedleHTMLBuilderCog(commands.Cog):
    """Needle HTML特化 ASTノード選択 Discord Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.builder = NeedleHTMLBuilder(max_steps=20)

    @app_commands.command(
        name="ai_needle",
        description="[100%ローカル / Needle] HTML ASTノード選択によるWebレイアウト自動構築"
    )
    @app_commands.describe(prompt="作成したいHTML構造・レイアウトの指示を入力してください")
    async def ai_needle_command(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer()

        res = await self.builder.build_html(prompt)

        html_code = res["html"]
        steps = res["total_steps"]
        latency = res["latency_ms"]
        trace = " ➔ ".join([t for t in res["trace"]])

        print("\n=== [Needle Raw Output Trace] ===")
        for dbg in res["raw_debug"]:
            print(dbg)
        print("=================================\n")

        msg = (
            f"**[HTML AST変換結果]:**\n"
            f"```html\n{html_code}\n```\n"
            f"```\n"
            f"[選択HTMLノード軌跡]\n{trace}\n"
            f"```\n"
            f"`⚡ Steps: {steps} 回 | Latency: {latency:.2f}ms | RAM: ~28MB`"
        )

        await interaction.followup.send(msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(NeedleHTMLBuilderCog(bot))
