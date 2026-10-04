import asyncio
import os
import random
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

# 1-Shot 多重スロット選定（Pattern A）で使用する表現パーツの辞書データベース
PHRASE_DICTIONARY = {
    "empathy": {
        "deep": [
            "それは本当にお疲れ様…！すごく大変だったのが伝わってくるよ。",
            "うわぁ、それはかなり参っちゃう状況だね…心中お察しするよ。",
            "そこまで頑張ったのにそれは辛いよね…本当によく耐えたと思う！"
        ],
        "mild": [
            "なるほど、そういうことがあったんだね！教えてくれてありがとう。",
            "そっかそっか！それはちょっとしたハプニングだったね。",
            "うんうん、なるほどね！日常のちょっとした出来事って感じだね。"
        ],
        "joyful": [
            "わあ！それめちゃくちゃ凄いことじゃない！素晴らしい！",
            "やったね！聞いてるこっちまで最高に嬉しい気分だよ！",
            "すごすぎる！これまでの努力が見事に実を結んだね！"
        ],
        "neutral": [
            "なるほど、その件についてだね！話を聞くよ。",
            "なるほどね！興味深いお話を聞かせてくれてありがとう。",
            "ふむふむ、そういった状況なんだね！"
        ]
    },
    "advice": {
        "encouragement": [
            "最初は誰でも詰まるポイントだから、焦らず1ステップずつ進めていこう！",
            "ここを乗り越えれば一気に前進できるから、自分のペースで大丈夫だよ！",
            "失敗は成功の元って言うし、諦めずにトライしたこと自体が素晴らしいよ！"
        ],
        "rest": [
            "今は一度PCや作業から離れて、温かい飲み物でも飲んでゆっくりリフレッシュしよう！",
            "根詰めすぎると効率も落ちちゃうから、今日はもう十分頑張ったと思って休もう！",
            "疲れている時は無理するのが一番良くないから、明日また新鮮な気持ちでやろうね！"
        ],
        "praise": [
            "この成果は本当に自信を持って良いレベルだよ！自分をたくさん褒めてあげてね！",
            "ここまで形にできたのは君の努力の賜物だね！本当に素晴らしい！",
            "素晴らしいチャレンジ精神だね！次回もこの調子でどんどん進めよう！"
        ],
        "general": [
            "また何か進展や気づいたことがあったら、いつでも気軽に教えてね！",
            "一つずつ整理して考えていけば、きっと良い方向に向かっていくはずだよ！",
            "いつでも相談に乗るから、困った時は遠慮なく声かけてね！"
        ]
    },
    "ending": {
        "friendly": ["応援してるからね！ファイト！", "またいつでも話しかけてね！", "いつでも見守ってるよ！"],
        "sympathetic": ["無理だけは絶対しないでね…！", "今日はゆっくり休んでね！", "お体に気をつけて過ごしてね！"],
        "enthusiastic": ["次回のアクションも楽しみにしてるよ！", "この勢いでどんどん行こう！", "また素晴らしい報告待ってるね！"]
    }
}


class JevTextGenerator:
    """Jevの超高速多重判定を活用し、LLMを使わずに一瞬で日本語文脈を構築する合成エンジン"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("JEV_API_KEY", "DEMO_KEY")
        self.api_url = "https://api.typesafe.ai/v1/evaluate"  # Jev API エンドポイント

    async def analyze_and_synthesize(self, prompt: str) -> str:
        """Jevによる1-Shot多重スロット判定を行い、数10msで最適文章を合成する"""
        
        # Jevへのリクエストペイロード（1回のリクエストで文脈・感情・トーンを一気に抽出）
        payload = {
            "state": prompt,
            "questions": {
                "is_frustrated": {
                    "type": "noul",
                    "prompt": "Is the user feeling frustrated, stuck, stressed, or tired?"
                },
                "empathy_level": {
                    "type": "choice",
                    "choices": ["deep", "mild", "joyful", "neutral"],
                    "prompt": "Select the appropriate empathy level based on the user's emotional context."
                },
                "advice_type": {
                    "type": "choice",
                    "choices": ["encouragement", "rest", "praise", "general"],
                    "prompt": "Select the best response type (encouragement, rest, praise, or general)."
                },
                "ending_tone": {
                    "type": "choice",
                    "choices": ["friendly", "sympathetic", "enthusiastic"],
                    "prompt": "Select the ending tone for the response."
                }
            }
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=headers, timeout=5) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return self._compose_response(result)
                    else:
                        # API非対応またはエラー時のローカル・フォールバック判定
                        return self._fallback_synthesis(prompt)
        except Exception as e:
            # ネットワークエラーやAPIキー未設定時のローカル・ルールベース・フォールバック
            return self._fallback_synthesis(prompt)

    def _compose_response(self, jev_result: dict) -> str:
        """Jevが返した構造化タグをもとに、表現辞書からパーツを選定して高速結合"""
        empathy_tag = jev_result.get("empathy_level", {}).get("choice", "neutral")
        advice_tag = jev_result.get("advice_type", {}).get("choice", "general")
        ending_tag = jev_result.get("ending_tone", {}).get("choice", "friendly")

        # パーツのランダム選定（同じタグでも毎回表情が変わる）
        empathy_phrase = random.choice(PHRASE_DICTIONARY["empathy"].get(empathy_tag, PHRASE_DICTIONARY["empathy"]["neutral"]))
        advice_phrase = random.choice(PHRASE_DICTIONARY["advice"].get(advice_tag, PHRASE_DICTIONARY["advice"]["general"]))
        ending_phrase = random.choice(PHRASE_DICTIONARY["ending"].get(ending_tag, PHRASE_DICTIONARY["ending"]["friendly"]))

        # 3つの文節パーツを結合（ハルシネーション・文法崩れ0%）
        return f"{empathy_phrase}\n{advice_phrase}\n{ending_phrase}"

    def _fallback_synthesis(self, prompt: str) -> str:
        """Jev API未接続時でも高速動作を保証する簡易フォールバック判定"""
        # 簡易キーワード判定
        if any(w in prompt for w in ["疲れた", "詰んだ", "難しい", "エラー", "無理"]):
            empathy = random.choice(PHRASE_DICTIONARY["empathy"]["deep"])
            advice = random.choice(PHRASE_DICTIONARY["advice"]["encouragement"])
            ending = random.choice(PHRASE_DICTIONARY["ending"]["sympathetic"])
        elif any(w in prompt for w in ["できた", "成功", "やった", "最高", "嬉しい"]):
            empathy = random.choice(PHRASE_DICTIONARY["empathy"]["joyful"])
            advice = random.choice(PHRASE_DICTIONARY["advice"]["praise"])
            ending = random.choice(PHRASE_DICTIONARY["ending"]["enthusiastic"])
        else:
            empathy = random.choice(PHRASE_DICTIONARY["empathy"]["mild"])
            advice = random.choice(PHRASE_DICTIONARY["advice"]["general"])
            ending = random.choice(PHRASE_DICTIONARY["ending"]["friendly"])

        return f"{empathy}\n{advice}\n{ending}"


class JevAICog(commands.Cog):
    """Jev（判定AI）超高速文章選定エンジンを搭載したDiscord Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Jevテキストジェネレーターの初期化
        self.generator = JevTextGenerator()

    @app_commands.command(name="ai", description="Jev超高速文章合成エンジンで即座に返答します")
    @app_commands.describe(prompt="メッセージや質問を入力してください")
    async def ai_command(self, interaction: discord.Interaction, prompt: str):
        """/ai コマンド: LLMを使わずにJev判定＋超高速構造化選択で返答を生成"""
        # 処理中表示（Jevのレスポンスは数10ms〜100msのため即レス可能）
        await interaction.response.defer()

        # 時間計測用
        start_time = asyncio.get_event_loop().time()

        # Jevによる文脈多重判定 ＆ 超高速文章選定
        generated_text = await self.generator.analyze_and_synthesize(prompt)

        # 処理時間の算出
        elapsed_ms = (asyncio.get_event_loop().time() - start_time) * 1000

        # フッターにJev判定ミリ秒数を付与
        footer = f"\n\n`⚡ Jev Selection Speed: {elapsed_ms:.1f}ms | Latency: Ultra-Low`"
        final_response = generated_text + footer

        # レスポンス送信
        await interaction.followup.send(final_response)


async def setup(bot: commands.Bot):
    await bot.add_cog(JevAICog(bot))