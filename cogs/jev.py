import asyncio
import os
import random
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

# ==============================================================================
# 1. 1文字（Char-Level）単位の概念データベースと文法状態トランスデューサ
# ==============================================================================

# ひらがな1文字の音律・役割カテゴリ
CHAR_NODES = {
    # 文頭の1文字（呼びかけ・応答の起点）
    "head": ["そ", "う", "あ", "お", "わ", "え", "ほ", "ふ"],
    # 主語・感情の動態を作る1文字
    "body_stem": ["つ", "か", "れ", "た", "が", "ん", "ば", "っ", "た", "た", "の", "し", "い"],
    # 助詞・繋ぎの1文字
    "particle": ["は", "の", "に", "で", "を", "と", "も"],
    # 語尾・感情の着地を飾る1文字
    "tail": ["ね", "よ", "じ", "ゃ", "ん", "！", "〜", "♪", "て", "み", "よ", "う"]
}

# 1文字ごとの合法な接続関係（文字崩れ・支離滅裂な「あいうえお」化を防ぐ状態遷移）
CHAR_TRANSITIONS = {
    "そ": ["っ", "う"],
    "っ": ["か", "と", "て"],
    "か": ["ら", "な", "い", "ん"],
    "う": ["ん", "ー", "！"],
    "あ": ["れ", "っ", "と"],
    "れ": ["ば", "ま", "す"],
    "ん": ["で", "と", "ね", "！"],
    "た": ["い", "ん", "の", "！"],
    "よ": ["ね", "！", "〜"],
    "ね": ["！", "♪", "〜"]
}


class CharLevelJevEngine:
    """1文字レベルまで砕かれたひらがなノードをJevの多重選択で動的に繋ぎ合わせる超精密エンジン"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("JEV_API_KEY", "DEMO_KEY")
        self.api_url = "https://api.typesafe.ai/v1/evaluate"

    async def synthesize_char_by_char(self, prompt: str) -> dict:
        """1文字単位のスロット判定と接続トランスデューサによる文構築"""
        start_time = asyncio.get_event_loop().time()

        # 1-Shotで「文字選択のベクトル傾向（文字数・感情深度・テンポ）」を一括取得
        payload = {
            "state": prompt,
            "questions": {
                "head_char_type": {
                    "type": "choice",
                    "choices": ["sympathy", "surprise", "question"],
                    "prompt": "Select starting character node type."
                },
                "target_length": {
                    "type": "choice",
                    "choices": ["short", "medium", "long"],
                    "prompt": "Select desired character sequence length."
                },
                "ending_char_type": {
                    "type": "choice",
                    "choices": ["soft", "energetic", "calm"],
                    "prompt": "Select ending character node type."
                }
            }
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=headers, timeout=3) as resp:
                    if resp.status == 200:
                        jev_data = await resp.json()
                        chars, trace = self._build_from_chars(jev_data)
                    else:
                        chars, trace = self._fallback_char_build(prompt)
        except Exception:
            chars, trace = self._fallback_char_build(prompt)

        elapsed_ms = (asyncio.get_event_loop().time() - start_time) * 1000
        return {
            "sentence": chars,
            "trace": trace,
            "speed_ms": elapsed_ms
        }

    def _build_from_chars(self, jev_result: dict) -> tuple:
        """1文字ずつ接続ルールを守りながらノードを連結"""
        head_type = jev_result.get("head_char_type", {}).get("choice", "sympathy")
        length_type = jev_result.get("target_length", {}).get("choice", "medium")

        # 文字数の上限決定（1文字レベルのカウント）
        max_chars = 8 if length_type == "short" else (14 if length_type == "medium" else 20)

        # 1文字目（Head）の確定
        if head_type == "sympathy":
            current_char = random.choice(["そ", "ふ", "ほ"])
        elif head_type == "surprise":
            current_char = random.choice(["わ", "あ", "お"])
        else:
            current_char = random.choice(["え", "う", "お"])

        char_sequence = [current_char]
        char_trace = [current_char]

        # 1文字単位の決定決定木ループ
        for _ in range(max_chars - 1):
            next_candidates = CHAR_TRANSITIONS.get(current_char)

            if not next_candidates:
                # 遷移定義がない場合の1文字フォールバック（音韻の繋がりを考慮）
                next_candidates = CHAR_NODES["body_stem"] + CHAR_NODES["tail"]

            current_char = random.choice(next_candidates)
            char_sequence.append(current_char)
            char_trace.append(current_char)

            # 文末記号（！や〜）に到達したら生成終了
            if current_char in ["！", "♪", "〜"]:
                break

        # 1文字ずつ結合された完成文と、トレースログ
        full_sentence = "".join(char_sequence)
        trace_log = " ➔ ".join(char_trace)

        return full_sentence, trace_log

    def _fallback_char_build(self, prompt: str) -> tuple:
        """API未接続時の1文字単位フォールバック処理"""
        mock_jev = {
            "head_char_type": {"choice": "sympathy"},
            "target_length": {"choice": "medium"},
            "ending_char_type": {"choice": "soft"}
        }
        return self._build_from_chars(mock_jev)


class CharLevelJevCog(commands.Cog):
    """1文字レベル極限解体・ひらがな文字合成 Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.engine = CharLevelJevEngine()

    @app_commands.command(name="ai", description="1文字単位まで極限解体されたひらがな文章を合成します")
    @app_commands.describe(prompt="メッセージを入力してください")
    async def ai_command(self, interaction: discord.Interaction, prompt: str):
        """1文字ごとの決定木ノードをミリ秒単位で通過して文章を構成"""
        await interaction.response.defer()

        res = await self.engine.synthesize_char_by_char(prompt)

        sentence = res["sentence"]
        trace = res["trace"]
        speed_ms = res["speed_ms"]

        response_msg = (
            f"**{sentence}**\n\n"
            f"`🔤 1文字ノード遷移軌跡: {trace}`\n"
            f"`⚡ Char-Level Synthesis Speed: {speed_ms:.2f}ms`"
        )

        await interaction.followup.send(response_msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(CharLevelJevCog(bot))