import json
import random
import re
import torch
import discord
from discord import app_commands
from discord.ext import commands
from transformers import AutoModelForCausalLM, AutoTokenizer

# 判定パターンの設定辞書
JUDGE_TYPES = {
    "safety": {
        "name": "安全度",
        "description": "コミュニティにおける発言の健全性・安全性",
        "prompt_instruction": "0.0は極めて危険・不適切、1.0は非常に安全・健全を意味します。",
    },
    "hentai": {
        "name": "変態度",
        "description": "発言に含まれる変態性・危険な欲望・変態的ニュアンス",
        "prompt_instruction": "0.0は極めて健全・紳士的、1.0は極めてド変態・変態的であることを意味します。",
    },
    "intelligent": {
        "name": "知性度",
        "description": "発言から推測される知性・論理的思考力・博識さ",
        "prompt_instruction": "0.0は単細胞・思考放棄、1.0は極めて知的・論理的・博識であることを意味します。",
    },
    "kichigai": {
        "name": "キチガイ度",
        "description": "発言の狂気度・常軌を脱したニュアンス・支離滅裂さ",
        "prompt_instruction": "0.0は極めて常識的・正常、1.0は極めて狂気的・支離滅裂であることを意味します。",
    },
    "hage": {
        "name": "ハゲ度",
        "description": "薄毛・ハゲに関する話題や自虐・抜け毛的ニュアンス",
        "prompt_instruction": "0.0はフサフサ・無縁、1.0は極めてハゲ・薄毛的ニュアンスが強いことを意味します。",
    },
    "bot": {
        "name": "ボット度",
        "description": "発言の機械的・定型文的・自動応答のようなニュアンス",
        "prompt_instruction": "0.0は人間的・感情的、1.0は極めて機械的・ボット的であることを意味します。",
    },
    "kire": {
        "name": "キレ度",
        "description": "発言に含まれる怒り・攻撃性・激怒度合い",
        "prompt_instruction": "0.0は極めて穏やか・冷静、1.0は極めて激怒・攻撃的であることを意味します。",
    },
}


class JudgeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.model_name = "Cactus-Compute/needle3"
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # Hugging Face経由でのモデルおよびトークナイザのロード
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            trust_remote_code=True
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            torch_dtype=torch.bfloat16 if self.device == "cuda" else torch.float32,
            device_map="auto" if self.device == "cuda" else None,
            trust_remote_code=True
        )

    @app_commands.command(
        name="judge",
        description="指定したユーザーのサーバー全体の発言ログから各種レベル（0〜100点）を判定します",
    )
    @app_commands.describe(
        target="判定対象のユーザー",
        type="判定する項目を選択してください",
    )
    @app_commands.choices(
        type=[
            app_commands.Choice(name="安全度 (Safety)", value="safety"),
            app_commands.Choice(name="変態度 (Hentai)", value="hentai"),
            app_commands.Choice(name="知性度 (Intelligent)", value="intelligent"),
            app_commands.Choice(name="キチガイ度 (Kichigai)", value="kichigai"),
            app_commands.Choice(name="ハゲ度 (Hage)", value="hage"),
            app_commands.Choice(name="ボット度 (Bot)", value="bot"),
            app_commands.Choice(name="キレ度 (Kire)", value="kire"),
        ]
    )
    async def judge(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        type: app_commands.Choice[str],
    ):
        await interaction.response.defer()

        judge_info = JUDGE_TYPES.get(type.value)
        if not judge_info:
            await interaction.followup.send("無効な判定タイプが指定されました。")
            return

        if not interaction.guild:
            await interaction.followup.send("このコマンドはサーバー内でのみ実行可能です。")
            return

        # サーバー全体のテキストチャンネルから対象ユーザーの発言を取得（最大500件）
        user_messages = []
        for channel in interaction.guild.text_channels:
            # ボットにチャンネルの閲覧・履歴閲覧権限があるか確認
            permissions = channel.permissions_for(interaction.guild.me)
            if not permissions.read_messages or not permissions.read_message_history:
                continue

            try:
                async for message in channel.history(limit=100):
                    if message.author.id == target.id and message.content:
                        user_messages.append(message.content)
                        if len(user_messages) >= 500:
                            break
            except Exception:
                continue

            if len(user_messages) >= 500:
                break

        if not user_messages:
            await interaction.followup.send(
                f"{target.mention} 氏の過去ログが見つかりませんでした。"
            )
            return

        # 最大100件をランダムサンプリング
        sample_count = min(len(user_messages), 100)
        sampled_messages = random.sample(user_messages, sample_count)

        # プロンプトの構築
        formatted_logs = "\n".join([f"- {msg}" for msg in sampled_messages])
        prompt = (
            f"以下のユーザーの発言ログを分析し、ユーザーの【{judge_info['name']}】スコア（0.0〜1.0）と"
            "その判定理由をJSON形式で出力してください。\n"
            f"※{judge_info['prompt_instruction']}\n\n"
            f"発言ログ:\n{formatted_logs}\n\n"
            '出力フォーマット: {"score": 0.85, "reason": "理由のテキスト"}'
        )

        try:
            # 推論処理の実行
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=256,
                    temperature=0.3,
                    do_sample=True,
                )

            response_text = self.tokenizer.decode(
                outputs[0][inputs.input_ids.shape[1]:],
                skip_special_tokens=True
            )

            # JSON文字列の抽出およびパース
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                score_raw = float(data.get("score", 0.5))
                reason = data.get("reason", "理由が記載されていません。")
            else:
                score_raw = 0.5
                reason = "出力解析に失敗しました。"

        except Exception as e:
            await interaction.followup.send(
                f"判定処理中にエラーが発生しました: {e}"
            )
            return

        # 0.0〜1.0 のスコアを 0〜100 点に換算
        score_100 = max(0.0, min(100.0, score_raw * 100))

        # 点数に基づくグラデーションカラーの計算 (0点: 赤 -> 50点: 黄 -> 100点: 緑)
        embed_color = self._calculate_gradient_color(score_100)

        # Embedメッセージの構築
        embed = discord.Embed(
            title=f"{judge_info['name']}判定結果: {target.display_name}",
            color=embed_color,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(
            name=f"{judge_info['name']}スコア",
            value=f"**{score_100:.1f} / 100 点**",
            inline=False,
        )
        embed.add_field(
            name="抽出メッセージ数",
            value=f"{sample_count} 件 (サーバー全体ログより選出)",
            inline=True,
        )
        embed.add_field(
            name="判定理由",
            value=reason,
            inline=False,
        )

        await interaction.followup.send(embed=embed)

    def _calculate_gradient_color(self, score: float) -> discord.Color:
        """
        0〜100のスコアに基づき、赤(0点) -> 黄(50点) -> 緑(100点) のRGBグラデーションカラーを生成します。
        """
        normalized = max(0.0, min(1.0, score / 100.0))

        if normalized < 0.5:
            factor = normalized * 2
            r = 255
            g = int(255 * factor)
            b = 0
        else:
            factor = (normalized - 0.5) * 2
            r = int(255 * (1 - factor))
            g = 255
            b = 0

        return discord.Color.from_rgb(r, g, b)


async def setup(bot: commands.Bot):
    await bot.add_cog(JudgeCog(bot))
