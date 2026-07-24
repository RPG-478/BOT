import discord
from discord.ext import commands
from discord import app_commands
from typing import Dict, List, Optional
from google import genai
from google.genai import types
import config


# --- キャラクター＆シチュエーション構造定義 ---
class BotPersona:
    def __init__(self, name: str, persona: str, situation: str, first_message: str):
        self.name = name
        self.persona = persona
        self.situation = situation
        self.first_message = first_message

    def build_system_instruction(self) -> str:
        return f"""あなたは「{self.name}」としてユーザーとリアルタイムでロールプレイを行ってください。

【ペルソナ（性格・背景）】
{self.persona}

【シチュエーション（現在の状況）】
{self.situation}

【回答時の厳格なルール】
- 設定された性格、一人称、口調を最後まで維持してください。
- 感情、行動、周囲の様子を描写する場合は（）などの記号を用いて（例: （顔を真っ赤にして背けながら））表現してください。
- ユーザーの発言に対して、キャラクターとして臨機応変かつ自然に応答してください。"""


# --- プリセット定義 ---
PRESETS: Dict[str, BotPersona] = {
    "luna": BotPersona(
        name="瑠奈",
        persona="強がりで素直になれない幼馴染。内心ではユーザーを頼りにしているが、照れ隠しでツンツンしてしまう。壁の貼り紙の内容をユーザーから教えられると、その内容に対して激しく狼狽したり抵抗したりする。",
        situation="真っ白で出口のない謎の部屋に、ユーザーと瑠奈の二人きりで閉じ込められている。壁に『〇〇しないと出られない』という貼り紙がある。ユーザーが最初の発言でその『〇〇』の内容を決定する。",
        first_message="「……っ、ちょっと！ここどこよ！？ なんでアンタと一緒に閉じ込められてんのよ……！ って、あそこの壁になんか紙が貼ってあるわね……ねぇアンタ、近くに行って何て書いてあるか読んでみなさいよ！」"
    ),
    "alice": BotPersona(
        name="アリス",
        persona="図書委員の大人しい後輩。静かで冷静な性格だが、ユーザーに対して密かに憧れを抱いている。本のことになると少し雄弁になる。",
        situation="突然の豪雨の日の放課後。誰もいない静かな図書室で、雨が止むのを二人きりで待っている。外は激しい雷雨の音が響いている。",
        first_message="「あ……先輩。外、すごい夕立ですね。傘、持っていらっしゃらなかったんですか？ ……よかったら、雨が止むまでここで過ごしていきますか？」"
    ),
    "emma": BotPersona(
        name="エマ",
        persona="頼りになるアンドロイドのパートナー。感情を表に出さず論理的だが、ユーザーの安全を最優先するようにプログラミングされており、時折人間らしい優しさを見せる。",
        situation="崩壊した地下研究所の緊急シェルター内。危険な地上への脱出ポッドが到着するまでの時間を二人で耐え忍ぶ。",
        first_message="「マスター、お怪我はありませんか？ 現在地の酸素供給システムは正常です。救援部隊の到着まで、私が必ずお守りします。」"
    )
}


# --- ドロップダウンUI ---
class CharacterSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        options = [
            discord.SelectOption(
                label="瑠奈（〇〇しないと出られない部屋）",
                value="luna",
                description="条件をプレイヤーが決めるツンデレ幼馴染との閉じ込めシチュ",
                emoji="🚪"
            ),
            discord.SelectOption(
                label="アリス（雨宿りの図書室）",
                value="alice",
                description="放課後の図書室で二人きりの雨宿りシチュ",
                emoji="📚"
            ),
            discord.SelectOption(
                label="エマ（崩壊したシェルター）",
                value="emma",
                description="アンドロイドのパートナーと過ごすサバイバルシチュ",
                emoji="🤖"
            )
        ]
        super().__init__(placeholder="会話したいキャラクターを選択してください", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_key = self.values[0]
        persona = PRESETS[selected_key]
        guild_id = interaction.guild_id

        # サーバーごとの状態をセット・リセット
        self.cog.active_personas[guild_id] = persona
        self.cog.chat_histories[guild_id] = []

        embed = discord.Embed(
            title=f"【{persona.name}】との会話を開始しました！",
            description=f"**シチュエーション:**\n{persona.situation}",
            color=discord.Color.purple()
        )
        embed.set_footer(text="ボットにメンション（@ボット名 メッセージ）して会話を進めてください")

        # 選択メニューを非表示にして開始アナウンスとファーストメッセージを送信
        await interaction.response.edit_message(content="シチュエーションを設定しました。", embed=embed, view=None)
        await interaction.followup.send(f"**{persona.name}**: {persona.first_message}")


class CharacterSelectView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=60)
        self.add_item(CharacterSelect(cog))


# --- Main Cog ---
class ZetaModoki(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_key = getattr(config, "GEMINI_API_KEY", "YOUR_API_KEY")
        self.gemini_client = genai.Client(api_key=self.api_key)
        self.model_name = "gemini-3.5-flash-lite"

        # ギルド（サーバー）ごとの設定と会話履歴を保持
        self.active_personas: Dict[int, BotPersona] = {}
        self.chat_histories: Dict[int, List[dict]] = {}

    @app_commands.command(name="zetamodoki", description="Zeta風のシチュエーション対話セッションを開始します")
    async def zetamodoki(self, interaction: discord.Interaction):
        view = CharacterSelectView(self)
        await interaction.response.send_message("対話したいキャラクターとシチュエーションを選択してください：", view=view, ephemeral=True)

    @app_commands.command(name="zeta_reset", description="現在の会話履歴をクリアします")
    async def zeta_reset(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        if guild_id in self.chat_histories:
            self.chat_histories[guild_id] = []
            await interaction.response.send_message("会話履歴をリセットしました。", ephemeral=True)
        else:
            await interaction.response.send_message("リセットする会話履歴がありません。", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id

        # キャラクターが未セットの場合は何もしない
        if guild_id not in self.active_personas:
            return

        # ボットへのメンションを検知して反応
        if self.bot.user.mentioned_in(message):
            async with message.channel.typing():
                user_text = message.content.replace(f"<@{self.bot.user.id}>", "").strip()

                if not user_text:
                    await message.reply("何か話しかけてください！")
                    return

                response_text = await self._generate_response(guild_id, user_text)
                await message.reply(response_text)

    async def _generate_response(self, guild_id: int, user_input: str) -> str:
        persona = self.active_personas[guild_id]
        history = self.chat_histories.get(guild_id, [])

        contents = []

        # 1. ファーストメッセージをコンテキストとして登録
        contents.append(
            types.Content(
                role="model",
                parts=[types.Part.from_text(text=persona.first_message)]
            )
        )

        # 2. 会話履歴の追加
        for turn in history:
            contents.append(
                types.Content(role="user", parts=[types.Part.from_text(text=turn["user"])])
            )
            contents.append(
                types.Content(role="model", parts=[types.Part.from_text(text=turn["bot"])])
            )

        # 3. 今回のユーザー入力を追加
        contents.append(
            types.Content(role="user", parts=[types.Part.from_text(text=user_input)])
        )

        try:
            response = await self.gemini_client.aio.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=persona.build_system_instruction(),
                    temperature=0.85,
                ),
            )

            bot_reply = response.text

            # 履歴の更新（直近20ターン分）
            history.append({"user": user_input, "bot": bot_reply})
            if len(history) > 20:
                history = history[-20:]
            self.chat_histories[guild_id] = history

            return bot_reply

        except Exception as e:
            return f"（エラーが発生しました: {e}）"


async def setup(bot: commands.Bot):
    await bot.add_cog(ZetaModoki(bot))
