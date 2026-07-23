import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, Dict, List
import config
from google import genai
from google.genai import types

class Character:
    def __init__(self, user_id: int, name: str, traits: str, stats: List[int], image_url: str = ""):
        self.user_id = user_id
        self.name = name
        self.traits = traits
        self.stats = {
            "筋力": stats[0],
            "観察": stats[1],
            "知性": stats[2],
            "器用": stats[3],
            "精神": stats[4],
        }
        self.hp = 10
        self.max_hp = 10
        self.items = []
        self.image_url = image_url

    def to_dict(self):
        return {
            "name": self.name,
            "traits": self.traits,
            "stats": self.stats,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "items": self.items,
            "image_url": self.image_url,
        }

    @classmethod
    def from_dict(cls, user_id: int, data: dict):
        char = cls(
            user_id=user_id,
            name=data["name"],
            traits=data["traits"],
            stats=[data["stats"][stat] for stat in config.STAT_NAMES],
            image_url=data.get("image_url", ""),
        )
        char.hp = data.get("hp", 10)
        char.items = data.get("items", [])
        return char


class GameState:
    def __init__(self):
        self.is_active = False
        self.round = 0
        self.max_round = config.MAX_ROUND
        self.current_room = config.INITIAL_ROOM
        self.players: List[int] = []
        self.actions: Dict[int, str] = {}
        self.messages_log: List[str] = []

    def reset(self):
        self.is_active = True
        self.round = 1
        self.current_room = config.INITIAL_ROOM
        self.players = []
        self.actions = {}
        self.messages_log = []

    def add_action(self, user_id: int, action: str):
        self.actions[user_id] = action

    def clear_actions(self):
        self.actions = {}

    def is_all_acted(self) -> bool:
        return len(self.actions) >= len(self.players) and len(self.players) > 0

    def is_game_over(self) -> bool:
        return self.round > self.max_round


class CharacterSheetModal(discord.ui.Modal):
    def __init__(self, cog):
        super().__init__(title="キャラクターシート作成")
        self.cog = cog
        self.name_input = discord.ui.TextInput(
            label="キャラクター名",
            placeholder="例: 田中太郎",
            max_length=30,
        )
        self.traits_input = discord.ui.TextInput(
            label="性格・特徴",
            placeholder="例: 物静かで観察眼に優れている",
            style=discord.TextStyle.paragraph,
        )
        self.stats_input = discord.ui.TextInput(
            label="能力値 (カンマ区切り: 筋力,観察,知性,器用,精神)",
            placeholder="例: 5,8,7,6,5 (各値は1-10)",
        )
        self.image_url_input = discord.ui.TextInput(
            label="画像URL (オプション)",
            placeholder="キャラクター立ち絵URL",
            required=False,
        )
        self.add_item(self.name_input)
        self.add_item(self.traits_input)
        self.add_item(self.stats_input)
        self.add_item(self.image_url_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            stats_str = self.stats_input.value.strip()
            stats = [int(x.strip()) for x in stats_str.split(",")]

            if len(stats) != 5 or any(s < 1 or s > 10 for s in stats):
                await interaction.response.send_message(
                    "能力値は5つ、各値は1-10の整数で入力してください",
                    ephemeral=True,
                )
                return

            character = Character(
                user_id=interaction.user.id,
                name=self.name_input.value,
                traits=self.traits_input.value,
                stats=stats,
                image_url=self.image_url_input.value or "",
            )

            self.cog.characters[interaction.user.id] = character
            await interaction.response.send_message(
                f"キャラクター「{character.name}」を作成しました",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                f"エラーが発生しました: {e}",
                ephemeral=True,
            )


class ActionModal(discord.ui.Modal):
    def __init__(self, cog):
        super().__init__(title="行動を入力")
        self.cog = cog
        self.action_input = discord.ui.TextInput(
            label="このラウンドでの行動を入力してください",
            placeholder="例: ドアの鍵を開けようと試みる",
            style=discord.TextStyle.paragraph,
            max_length=200,
        )
        self.add_item(self.action_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_id = interaction.user.id
            action_text = self.action_input.value.strip()

            if user_id not in self.cog.characters:
                await interaction.response.send_message(
                    "キャラクターシートを先に作成してください",
                    ephemeral=True,
                )
                return

            self.cog.game_state.add_action(user_id, action_text)

            await interaction.response.send_message(
                f"行動を入力しました: {action_text}",
                ephemeral=True,
            )

            if self.cog.game_state.is_all_acted():
                await self.cog._process_round(interaction.channel)

        except Exception as e:
            await interaction.response.send_message(
                f"エラーが発生しました: {e}",
                ephemeral=True,
            )


class ActionButton(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="行動を入力する", style=discord.ButtonStyle.primary)
    async def action_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ActionModal(self.cog))


class TRPGGame(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_key = "AQ.Ab8RN6LqsTEvK4h4ZW0u-Ni7qdxbytjUuXEJaZLDV3JG0Anygg"
        self.gemini_client = genai.Client(api_key=self.api_key)
        self.model_name = "gemini-3.5-flash-lite"
        self.characters: Dict[int, Character] = {}
        self.game_state = GameState()
        self.main_message = None
        self.main_channel = None

    @app_commands.command(name="cs", description="キャラクターシートを作成・更新します")
    async def create_character_sheet(self, interaction: discord.Interaction):
        modal = CharacterSheetModal(self)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="cs_show", description="キャラクターシートを表示します")
    @app_commands.describe(target_user="対象ユーザー（指定なしの場合は自分）")
    async def show_character_sheet(
        self, interaction: discord.Interaction, target_user: Optional[discord.User] = None
    ):
        target = target_user or interaction.user
        target_id = target.id

        if target_id not in self.characters:
            await interaction.response.send_message(
                f"{target.mention} のキャラクターシートが見つかりません",
                ephemeral=True,
            )
            return

        char = self.characters[target_id]
        embed = discord.Embed(
            title=char.name,
            description=f"性格・特徴:\n{char.traits}",
            color=discord.Color.blue(),
        )

        if char.image_url:
            embed.set_image(url=char.image_url)

        stats_text = "\n".join(
            [f"- {stat}: {value}" for stat, value in char.stats.items()]
        )
        embed.add_field(name="能力値", value=stats_text, inline=False)
        embed.add_field(
            name="ステータス",
            value=f"HP: {char.hp}/{char.max_hp}\n所持品: {', '.join(char.items) if char.items else 'なし'}",
            inline=False,
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="start_game", description="ゲームセッションを開始します")
    async def start_game(self, interaction: discord.Interaction):
        if self.game_state.is_active:
            await interaction.response.send_message(
                "既にゲームが進行中です",
                ephemeral=True,
            )
            return

        self.game_state.reset()
        self.main_channel = interaction.channel
        self.game_state.players = [interaction.user.id]

        await interaction.response.defer()

        embed = await self._create_main_embed()
        self.main_message = await interaction.channel.send(
            embed=embed, view=ActionButton(self)
        )

        await interaction.followup.send(
            "ゲームが開始されました。/join_game コマンドで参加登録してください。"
        )

    @app_commands.command(name="join_game", description="ゲームセッションに参加します")
    async def join_game(self, interaction: discord.Interaction):
        if not self.game_state.is_active:
            await interaction.response.send_message(
                "進行中のゲームセッションがありません",
                ephemeral=True,
            )
            return

        user_id = interaction.user.id

        if user_id in self.game_state.players:
            await interaction.response.send_message(
                "既に参加済みです",
                ephemeral=True,
            )
            return

        if user_id not in self.characters:
            await interaction.response.send_message(
                "キャラクターシートを先に作成してください（/cs）",
                ephemeral=True,
            )
            return

        self.game_state.players.append(user_id)
        await interaction.response.send_message(
            f"{interaction.user.mention} が参加しました"
        )

        if self.main_message:
            embed = await self._create_main_embed()
            await self.main_message.edit(embed=embed)

    async def _process_round(self, channel):
        if not self.game_state.is_all_acted():
            return

        try:
            dice_results = await self._resolve_actions()
            narrative = await self._generate_narrative(dice_results)
            self.game_state.messages_log.append(narrative)
            self.game_state.clear_actions()
            self.game_state.round += 1

            if self.main_message:
                embed = await self._create_main_embed(narrative)
                await self.main_message.edit(embed=embed, view=ActionButton(self))

            if self.game_state.is_game_over():
                await channel.send(
                    "15ラウンド終了。ゲームオーバー... 脱出することはできませんでした。"
                )
                self.game_state.is_active = False
                self.main_message = None

        except Exception as e:
            await channel.send(f"ラウンド処理エラー: {e}")

    async def _resolve_actions(self) -> Dict[int, dict]:
        results = {}

        for user_id, action_text in self.game_state.actions.items():
            char = self.characters[user_id]
            skill_used = self._infer_skill(action_text)
            stat_value = char.stats.get(skill_used, 5)

            dice_roll = random.randint(1, 100)
            success = dice_roll <= stat_value * 10

            results[user_id] = {
                "character": char,
                "action": action_text,
                "skill": skill_used,
                "stat_value": stat_value,
                "dice_roll": dice_roll,
                "success": success,
            }

        return results

    def _infer_skill(self, action_text: str) -> str:
        action_lower = action_text.lower()

        for skill, keywords in config.STAT_ACTIONS.items():
            if any(keyword in action_lower for keyword in keywords):
                return skill

        return random.choice(config.STAT_NAMES)

    async def _generate_narrative(self, dice_results: Dict[int, dict]) -> str:
        prompt_parts = self._build_gemini_prompt(dice_results)

        try:
            response = await self.gemini_client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt_parts,
                config=types.GenerateContentConfig(
                    system_instruction=self._get_system_instruction(),
                ),
            )
            return response.text
        except Exception as e:
            return f"【システムエラー】ナレーティブ生成に失敗しました: {e}"

    def _build_gemini_prompt(self, dice_results: Dict[int, dict]) -> List[str]:
        prompt_parts = []

        prompt_parts.append(
            f"【現在のラウンド】{self.game_state.round} / {self.game_state.max_round}"
        )
        prompt_parts.append(f"【現在地】{self.game_state.current_room}")

        prompt_parts.append("【参加キャラクター】")
        for user_id in self.game_state.players:
            if user_id in self.characters:
                char = self.characters[user_id]
                prompt_parts.append(
                    f"- {char.name}（{char.traits}） HP:{char.hp}/{char.max_hp}"
                )

        prompt_parts.append("【プレイヤーの行動と判定結果】")
        for user_id, result in dice_results.items():
            char = result["character"]
            action = result["action"]
            skill = result["skill"]
            dice = result["dice_roll"]
            stat = result["stat_value"]
            success_text = "成功" if result["success"] else "失敗"

            prompt_parts.append(
                f"- {char.name}: 「{action}」\n"
                f"  使用スキル: {skill} ({stat}) | "
                f"ダイス: {dice} | {success_text}"
            )

        if self.game_state.messages_log:
            prompt_parts.append("【これまでのストーリー】")
            prompt_parts.append("\n".join(self.game_state.messages_log[-3:]))

        prompt_parts.append(
            "上記のプレイヤー行動に基づいて、洋館内での情景と物語展開を日本語で描写してください。"
            "100-150文字で、雰囲気を保ちながら次への手がかりも含めてください。"
        )

        return prompt_parts

    def _get_system_instruction(self) -> str:
        return (
            "あなたは閉鎖された洋館からの脱出TRPGのゲームマスター（GM）です。\n"
            "プレイヤーの行動に基づいて、リアルな情景描写と物語展開を提供してください。\n"
            "ダイス判定の成功/失敗を反映し、サスペンス・ミステリーの雰囲気を保ってください。\n"
            "洋館内の謎や脱出への手がかりを段階的に提示してください。"
        )

    async def _create_main_embed(self, narrative: str = "") -> discord.Embed:
        room = self.game_state.current_room
        round_num = self.game_state.round
        max_round = self.game_state.max_round

        embed = discord.Embed(
            title=f"[第{round_num}ラウンド] 閉ざされた洋館 - 現在地: {room}",
            description=narrative or "ゲームが開始されました。皆で脱出を目指しましょう...",
            color=discord.Color.dark_gray(),
        )

        embed.add_field(
            name="制限",
            value=f"残り {max_round - round_num + 1} / {max_round} ラウンド",
            inline=False,
        )

        party_text = ""
        for user_id in self.game_state.players:
            if user_id in self.characters:
                char = self.characters[user_id]
                hp_bar = "█" * char.hp + "░" * (char.max_hp - char.hp)
                party_text += f"- {char.name} [{hp_bar}] HP {char.hp}/{char.max_hp}\n"

        embed.add_field(name="パーティ状態", value=party_text or "なし", inline=False)

        action_status = ""
        for user_id in self.game_state.players:
            if user_id in self.characters:
                char = self.characters[user_id]
                status = "入力済み" if user_id in self.game_state.actions else "未入力"
                action_status += f"- {char.name}: {status}\n"

        embed.add_field(name="行動入力状況", value=action_status or "なし", inline=False)

        embed.set_footer(text="すべてのプレイヤーが行動を入力するとラウンドが進行します")

        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(TRPGGame(bot))
