import random
import discord
from discord import app_commands
from discord.ext import commands
import needle

# 判定パターンの設定辞書
JUDGE_TYPES = {
    "safety": {"name": "安全度", "instruction": "0.0は危険、1.0は安全"},
    "hentai": {"name": "変態度", "instruction": "0.0は健全、1.0は変態"},
    "intelligent": {"name": "知性度", "instruction": "0.0は低知性、1.0は高知性"},
    "kichigai": {"name": "キチガイ度", "instruction": "0.0は正常、1.0は狂気"},
    "hage": {"name": "ハゲ度", "instruction": "0.0はフサフサ、1.0はハゲ"},
    "bot": {"name": "ボット度", "instruction": "0.0は人間、1.0はボット"},
    "kire": {"name": "キレ度", "instruction": "0.0は穏やか、1.0は激怒"},
}


class JudgeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="judge",
        description="指定したユーザーの発言ログから各種スコアの判定を行います",
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
        if not judge_info or not interaction.guild:
            await interaction.followup.send("無効な呼び出しです。")
            return

        # サーバー全体のテキストチャンネルから発言ログを取得（最大500件）
        user_messages = []
        for channel in interaction.guild.text_channels:
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

        # 最大100件をランダム抽出
        sample_count = min(len(user_messages), 100)
        sampled_messages = random.sample(user_messages, sample_count)

        # ツール呼び出し用関数の定義
        @needle.tool
        def record_score(score: float, reason: str):
            "ユーザーのスコア(0.0〜1.0)と判定理由を記録します。"
            return {"score": score, "reason": reason}

        # 標準の Needle エージェントを初期化（デフォルトでフル20層を使用）
        agent = needle.Needle(tools=[record_score])

        formatted_logs = "\n".join([f"- {msg}" for msg in sampled_messages])
        prompt = (
            f"発言ログを分析し、【{judge_info['name']}】（{judge_info['instruction']}）を測定して"
            "record_score ツールを実行してください。\n\n"
            f"発言ログ:\n{formatted_logs}"
        )

        try:
            response = agent.run(prompt)
            results = response.get("results", [])

            if results and isinstance(results, list):
                eval_data = results[0]
                score_raw = float(eval_data.get("score", 0.5))
                reason = str(eval_data.get("reason", "理由なし"))
            else:
                score_raw = 0.5
                reason = "ツール呼び出しが発生しませんでした。"

        except Exception as e:
            await interaction.followup.send(f"エラーが発生しました: {e}")
            return

        score_100 = max(0.0, min(100.0, score_raw * 100))
        embed_color = self._calculate_gradient_color(score_100)

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
            value=f"{sample_count} 件 (サーバー全体より抽出)",
            inline=True,
        )
        embed.add_field(name="判定理由", value=reason, inline=False)

        await interaction.followup.send(embed=embed)

    def _calculate_gradient_color(self, score: float) -> discord.Color:
        normalized = max(0.0, min(1.0, score / 100.0))
        if normalized < 0.5:
            factor = normalized * 2
            return discord.Color.from_rgb(255, int(255 * factor), 0)
        else:
            factor = (normalized - 0.5) * 2
            return discord.Color.from_rgb(int(255 * (1 - factor)), 255, 0)


async def setup(bot: commands.Bot):
    await bot.add_cog(JudgeCog(bot))
