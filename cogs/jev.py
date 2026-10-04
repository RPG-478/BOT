import asyncio
import time
import os
from typing import List, Dict, Any, Literal
import discord
from discord import app_commands
from discord.ext import commands

# Needle (Cactus Compute) の読み込み
import cactus_needle as needle

# Needleが厳格に選択できるひらがな・音節・文章終了トークン
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
    "っ", "ー", "！", "？", "♪", "〜",
    "[END]"
]

# 通信往復を減らすためのSpeculative（投機的）2文字チャンク
CHUNK_CHOICES = Literal[
    "ね！", "だよ", "です", "かな", "ー！", "〜♪", "[END]"
]

def append_single_char(char: HIRAGANA_CHAR_CHOICES) -> str:
    """Select the IMMEDIATELY NEXT single hiragana character or '[END]' token to naturally build the response.
    
    Args:
        char: The single character to append, or '[END]' if sentence is complete.
    """
    return str(char)

def append_speculative_chunk(chunk: CHUNK_CHOICES) -> str:
    """Select a 2-character ending chunk or '[END]' token when the sentence is close to completion.
    
    Args:
        chunk: The ending chunk to append, or '[END]' if sentence is complete.
    """
    return str(chunk)


class NeedleAutoregressiveEngine:
    """
    Needle (100% ローカル / 28MB RAM) を使用した
    1文字・音節自己回帰（Autoregressive）日本語文章生成エンジン
    """
    def __init__(self):
        # Needleエージェントの初期化（1文字選択ツール ＆ チャンク選択ツールを登録）
        self.agent = needle.Needle(
            tools=[append_single_char, append_speculative_chunk]
        )
        self.max_steps = 20  # 最大ステップ数（ループ安全限界）

    async def generate_sentence(self, user_prompt: str) -> Dict[str, Any]:
        """
        Needleで1文字/音節ごとにルーティング・判定を行い、
        [END] トークンが選ばれるまでローカルで文字を追加していくメイン生成ループ
        """
        start_time = time.perf_counter()
        
        generated_text = ""
        trace_logs = []
        step_count = 0

        while step_count < self.max_steps:
            step_count += 1
            
            # --- needle.run 用のコンテキストプロンプト構築 ---
            # これまでに選択された文字列と、元メッセージを文脈として入力
            state_prompt = (
                f"User Input: \"{user_prompt}\"\n"
                f"Generated Text So Far: \"{generated_text}\"\n"
                f"Step: {step_count}\n"
                "Task: Pick the best next single character or speculative chunk from available tools to make a natural Japanese response. "
                "If 'Generated Text So Far' is already complete and makes sense, choose '[END]' immediately."
            )

            # --- Needle によるミリ秒単位のローカル推論＆型制約抽出 ---
            # CPU/RAM負荷ほぼゼロで数ミリ秒で決定される
            result = self.agent.run(state_prompt)
            
            chosen_token = "[END]"
            
            if result and result.get("function_calls"):
                for call in result["function_calls"]:
                    # ツールの戻り値（選ばれた1文字またはチャンク）を取得
                    output = str(call.execute())
                    chosen_token = output
                    break
            else:
                # 該当ツールが選ばれなかった場合のフォールバック（文字数に応じて[END]か記号）
                chosen_token = "[END]" if step_count > 5 else "！"

            trace_logs.append(f"Step {step_count:02d}: '{chosen_token}'")

            # [END] トークンが出現したら即時生成終了
            if chosen_token == "[END]":
                break

            generated_text += chosen_token

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return {
            "sentence": generated_text if generated_text else "（応答なし）",
            "trace": trace_logs,
            "total_steps": step_count,
            "latency_ms": elapsed_ms
        }


class NeedleCharEngineCog(commands.Cog):
    """Needle 1文字・音節自己回帰 Discord Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.engine = NeedleAutoregressiveEngine()

    @app_commands.command(
        name="ai_needle",
        description="[100%ローカル / Needle] 1文字・音節自己回帰でミリ秒単位の文章生成を行います"
    )
    @app_commands.describe(prompt="メッセージを入力してください")
    async def ai_needle_command(self, interaction: discord.Interaction, prompt: str):
        """/ai_needle コマンド: Needleのツール文法制約で1文字ずつ繋ぎ合わせる"""
        await interaction.response.defer()

        # Needleローカル生成の実行
        res = await self.engine.generate_sentence(prompt)

        sentence = res["sentence"]
        steps = res["total_steps"]
        latency = res["latency_ms"]
        trace = " ➔ ".join([t.split("'")[1] for t in res["trace"]])

        msg = (
            f"**[生成結果]: {sentence}**\n\n"
            f"```\n"
            f"[Needle 1文字/音節 ルーティング軌跡]\n{trace}\n"
            f"```\n"
            f"`⚡ Needle Local Steps: {steps} 回 | Latency: {latency:.2f}ms | Memory: ~28MB (Zero API Cost)`"
        )

        await interaction.followup.send(msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(NeedleCharEngineCog(bot))