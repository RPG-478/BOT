import asyncio
import os
import random
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

# 文章のフロー（位置関係・トーン・文字数制限）を極小単位に概念化・刻み込んだ表現データベース
HIRAGANA_MATRIX = {
    # 位置0: 文頭・接続・テンポ（呼びかけ）
    "pos_0_intro": {
        "deep_sympathy": ["そっか...", "うーん...", "なるほど..."],
        "mild_sympathy": ["そっかそっか！", "うんうん！", "なるほどね！"],
        "praise": ["わあ！", "すごーい！", "やったね！"],
        "question": ["おや？", "ふむふむ！", "えーっとね..."]
    },
    # 位置1: 主語・文脈対象（わかち書き単位で刻む）
    "pos_1_subject": {
        "work_study": ["きょう の おしごと", "べんきょう の こと", "さぎょう"],
        "emotion_state": ["いま の きもち", "その かんじ", "その ハプニング"],
        "general": ["それ", "その こと", "きょう の できごと"]
    },
    # 位置2: 格助詞・位置指定接続
    "pos_2_particle": {
        "topic": ["は", "について は"],
        "cause": ["で", "によって"],
        "target": ["に", "へ の とりくみ は"]
    },
    # 位置3: 状態・動詞・述語の核（述語部分を細分化）
    "pos_3_predicate": {
        "hard": ["かなり たいへん", "すごく がんばった", "ちょっと つかれちゃった"],
        "success": ["みごとに できた", "うまく いった", "バッチリ きまった"],
        "stuck": ["すこし つまづいちゃった", "なやんじゃった", "むずかしかった"]
    },
    # 位置4: 補助動詞・文脈接続・相づち展開
    "pos_4_auxiliary": {
        "state_past": ["みたい だね。", "ようす だね。", "かんじ だったね。"],
        "effort_past": ["んだね！", "みたい だね！", "のかな？"],
        "continuity": ["みたい だけど、", "ようす だけど、"]
    },
    # 位置5: 感情語尾・結び・ねぎらい（一文の締めくくり）
    "pos_5_ending": {
        "encouragement": ["ゆっくり やすんでね！", "無理 しないでね！", "自分の ぺーす で いこうね！"],
        "praise": ["ほんとう に えらいよ！", "じしん を もってね！", "すばらしいよ！"],
        "friendly": ["いつでも 話してね！", "また おしえてね！", "おうえん してるよ！"]
    }
}


class JevHiraganaSynthesizer:
    """文章フローを極小要素（文頭・主語・助詞・述語・補助・語尾）に刻み、Jevで一括選定してひらがな一文を構築するエンジン"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("JEV_API_KEY", "DEMO_KEY")
        self.api_url = "https://api.typesafe.ai/v1/evaluate"

    async def synthesize_hiragana_sentence(self, user_prompt: str) -> dict:
        """Jevによる位置別・概念別の多重スロット判定を行い、完璧なひらがな一文を結合する"""
        start_time = asyncio.get_event_loop().time()

        # 1回のリクエストで「文脈カテゴリ」「感情深度」「文章のフロー構造」を細かく判定
        payload = {
            "state": user_prompt,
            "questions": {
                "tone_category": {
                    "type": "choice",
                    "choices": ["deep_sympathy", "mild_sympathy", "praise", "question"],
                    "prompt": "Select emotional tonecategory."
                },
                "topic_category": {
                    "type": "choice",
                    "choices": ["work_study", "emotion_state", "general"],
                    "prompt": "Select topic category."
                },
                "state_category": {
                    "type": "choice",
                    "choices": ["hard", "success", "stuck"],
                    "prompt": "Select state category."
                },
                "ending_category": {
                    "type": "choice",
                    "choices": ["encouragement", "praise", "friendly"],
                    "prompt": "Select ending category."
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
                        result = await resp.json()
                        sentence, flow_slots = self._compose_from_tags(result)
                    else:
                        sentence, flow_slots = self._fallback_composition(user_prompt)
        except Exception:
            sentence, flow_slots = self._fallback_composition(user_prompt)

        elapsed_ms = (asyncio.get_event_loop().time() - start_time) * 1000
        return {
            "sentence": sentence,
            "flow_slots": flow_slots,
            "speed_ms": elapsed_ms
        }

    def _compose_from_tags(self, jev_result: dict) -> tuple:
        """刻まれた各位置スロットからタグに対応するパーツを厳密に抽出してガッチャンコ"""
        tone = jev_result.get("tone_category", {}).get("choice", "mild_sympathy")
        topic = jev_result.get("topic_category", {}).get("choice", "general")
        state = jev_result.get("state_category", {}).get("choice", "hard")
        ending = jev_result.get("ending_category", {}).get("choice", "friendly")

        # 各位置（位置0〜5）のパーツを厳密にピックアップ
        p0 = random.choice(HIRAGANA_MATRIX["pos_0_intro"].get(tone, HIRAGANA_MATRIX["pos_0_intro"]["mild_sympathy"]))
        p1 = random.choice(HIRAGANA_MATRIX["pos_1_subject"].get(topic, HIRAGANA_MATRIX["pos_1_subject"]["general"]))
        p2 = random.choice(HIRAGANA_MATRIX["pos_2_particle"]["topic"])
        p3 = random.choice(HIRAGANA_MATRIX["pos_3_predicate"].get(state, HIRAGANA_MATRIX["pos_3_predicate"]["hard"]))
        p4 = random.choice(HIRAGANA_MATRIX["pos_4_auxiliary"]["effort_past"])
        p5 = random.choice(HIRAGANA_MATRIX["pos_5_ending"].get(ending, HIRAGANA_MATRIX["pos_5_ending"]["friendly"]))

        # 一文のフローとして結合（読みやすさのためスペース区切り／わかち書き）
        full_sentence = f"{p0} {p1} {p2} {p3} {p4} {p5}"
        
        flow_debug = f"[{p0}] + [{p1}] + [{p2}] + [{p3}] + [{p4}] + [{p5}]"
        return full_sentence, flow_debug

    def _fallback_composition(self, prompt: str) -> tuple:
        """API未接続時のローカルキーワード・ルール選定フォールバック"""
        if any(w in prompt for w in ["つかれた", "むり", "へとへと", "しんどい", "大変", "疲れた"]):
            tone, topic, state, ending = "deep_sympathy", "emotion_state", "hard", "encouragement"
        elif any(w in prompt for w in ["できた", "やった", "成功", "かんせい", "完成"]):
            tone, topic, state, ending = "praise", "work_study", "success", "praise"
        else:
            tone, topic, state, ending = "mild_sympathy", "general", "hard", "friendly"

        jev_mock = {
            "tone_category": {"choice": tone},
            "topic_category": {"choice": topic},
            "state_category": {"choice": state},
            "ending_category": {"choice": ending}
        }
        return self._compose_from_tags(jev_mock)


class JevHiraganaCog(commands.Cog):
    """ひらいがな文章構造化エンジンを統合したDiscord Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.synthesizer = JevHiraganaSynthesizer()

    @app_commands.command(name="ai", description="Jev構造化エンジンでひらがな一文を爆速生成します")
    @app_commands.describe(prompt="メッセージを入力してください")
    async def ai_command(self, interaction: discord.Interaction, prompt: str):
        """/ai コマンド: 細かく刻まれた構造概念を結合して完全なひらがな一文を生成"""
        await interaction.response.defer()

        # ひらがな一文合成処理を実行
        res = await self.synthesizer.synthesize_hiragana_sentence(prompt)

        hiragana_text = res["sentence"]
        flow_debug = res["flow_slots"]
        speed_ms = res["speed_ms"]

        # レスポンスメッセージ構築
        response_msg = (
            f"**{hiragana_text}**\n\n"
            f"`🧩 フロー概念分解: {flow_debug}`\n"
            f"`⚡ Jev Atomized Speed: {speed_ms:.2f}ms`"
        )

        await interaction.followup.send(response_msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(JevHiraganaCog(bot))