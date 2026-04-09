# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import asyncio
import random

def we(description: str = None, title: str = None) -> discord.Embed:
    """白色embedを生成するヘルパー"""
    return discord.Embed(title=title, description=description, color=0xFFFFFF)

class DoubtEngine:
    def __init__(self, player_ids):
        self.players = player_ids
        self.hands = {p_id: [] for p_id in player_ids}
        self.field = []
        self.current_turn_idx = 0
        self.last_claimed_num = None
        self.last_player_id = None
        self.is_accepting_doubt = False
        self.last_panel_msg = None 
        self.next_required_num = 1
        self.pass_count = 0
        
        self._setup_game()

    def _setup_game(self):
        suits = ["S", "H", "D", "C"]
        deck = [f"[{s}-{r}]" for s in suits for r in range(1, 14)]
        deck.extend(["[JK-1]", "[JK-2]"])
        random.shuffle(deck)
        
        per_player = len(deck) // len(self.players)
        for i, p_id in enumerate(self.players):
            start = i * per_player
            end = (i + 1) * per_player if i != len(self.players) - 1 else len(deck)
            self.hands[p_id] = sorted(deck[start:end])

    @property
    def current_player_id(self):
        return self.players[self.current_turn_idx]

    def next_turn(self):
        self.current_turn_idx = (self.current_turn_idx + 1) % len(self.players)

class CardSelect(discord.ui.Select):
    def __init__(self, hand, game_engine, cog):
        options = [discord.SelectOption(label=card, value=card) for card in hand[:25]]
        super().__init__(placeholder="出すカードを1枚選んでください", options=options)
        self.game_engine = game_engine
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        selected_card = self.values[0]
        game = self.game_engine
        user_id = interaction.user.id
        
        if user_id != game.current_player_id:
            return await interaction.response.send_message(embed=we("あなたのターンではありません"), ephemeral=True)
        
        claimed_num = game.next_required_num
        
        if selected_card in game.hands[user_id]:
            game.hands[user_id].remove(selected_card)
            game.field.append((user_id, selected_card))
            game.last_claimed_num = claimed_num
            game.last_player_id = user_id
            game.pass_count = 0 
            
            await interaction.response.send_message(embed=we(f"**{selected_card}** を「**{claimed_num}**」として出しました。"), ephemeral=True)
            await interaction.channel.send(embed=we(f"<@{user_id}> が「**{claimed_num}**」を宣言してカードを置きました。5秒間ダウト受付中。"))
            
            game.next_required_num = 1 if claimed_num == 13 else claimed_num + 1
            
            game.is_accepting_doubt = True
            game.next_turn()
            
            await asyncio.sleep(5)
            
            if game.is_accepting_doubt:
                game.is_accepting_doubt = False
                await self.cog.send_main_screen(interaction.channel, game)

class GameControlView(discord.ui.View):
    def __init__(self, game_engine, cog):
        super().__init__(timeout=None)
        self.game_engine = game_engine
        self.cog = cog

    @discord.ui.button(label="手札確認", style=discord.ButtonStyle.grey)
    async def check_hand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.game_engine.hands:
            return await interaction.response.send_message(embed=we("あなたはゲームに参加していません。"), ephemeral=True)
            
        hand = self.game_engine.hands.get(interaction.user.id, [])
        hand_str = " ".join(hand) if hand else "手札がありません"
        embed = discord.Embed(title="あなたの手札", description=hand_str, color=0xFFFFFF)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="カードを置く", style=discord.ButtonStyle.red)
    async def play(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.game_engine.hands:
            return await interaction.response.send_message(embed=we("あなたはゲームに参加していません。"), ephemeral=True)
            
        if interaction.user.id != self.game_engine.current_player_id:
            return await interaction.response.send_message(embed=we("あなたのターンではありません"), ephemeral=True)
        
        view = discord.ui.View()
        view.add_item(CardSelect(self.game_engine.hands[interaction.user.id], self.game_engine, self.cog))
        await interaction.response.send_message(embed=we(f"どのカードを「{self.game_engine.next_required_num}」として出しますか？"), view=view, ephemeral=True)

class DoubtJoinView(discord.ui.View):
    def __init__(self, host_id):
        super().__init__(timeout=65) 
        self.players = [host_id]

    @discord.ui.button(label="参加", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.players:
            self.players.append(interaction.user.id)
            await interaction.response.send_message(embed=we(f"参加しました (現在: {len(self.players)}名)"), ephemeral=True)
        else:
            await interaction.response.send_message(embed=we("既に参加しています"), ephemeral=True)

class Doubt(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.games = {}

    async def send_main_screen(self, channel, game):
        if game.last_panel_msg:
            try:
                await game.last_panel_msg.delete()
            except:
                pass

        embed = discord.Embed(title="Doubt Game", color=0xFFFFFF)
        embed.add_field(name="現在の手番", value=f"<@{game.current_player_id}>", inline=False)
        embed.add_field(name="出すべき数字", value=f"**{game.next_required_num}**", inline=True)
        embed.add_field(name="場の状況", value=f"合計: {len(game.field)}枚", inline=True)
        
        status_list = [f"<@{p_id}>: 残り {len(game.hands.get(p_id, []))}枚" for p_id in game.players]
        embed.add_field(name="プレイヤー", value="\n".join(status_list), inline=False)
        
        view = GameControlView(game, self)
        content = f"次の方、カードを選んでください: <@{game.current_player_id}>"
        game.last_panel_msg = await channel.send(content=content, embed=embed, view=view)

    async def start_from_hub(self, channel, player_ids):
        await asyncio.sleep(60)
        
        if len(player_ids) < 3:
            return await channel.send(embed=we("人数不足（3名以上必要）のため、ダウトを開始できませんでした。"))
        
        engine = DoubtEngine(player_ids)
        self.games[channel.id] = engine
        await channel.send(embed=we("3名以上の参加を確認。カードを配り、ゲームを開始します！"))
        await self.send_main_screen(channel, engine)

    @commands.command(name="doubt")
    async def start_game(self, ctx):
        view = DoubtJoinView(ctx.author.id)
        embed = discord.Embed(
            title="ダウト参加者募集", 
            description="ボタンを押して参加してください\n**3名以上で開始します**（募集時間: 60秒）", 
            color=0xFFFFFF
        )
        await ctx.send(embed=embed, view=view)
        await self.start_from_hub(ctx.channel, view.players)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        game = self.games.get(message.channel.id)
        if not game: return

        if message.author.id == game.current_player_id and message.content == "パス":
            game.pass_count += 1
            if game.pass_count >= len(game.players):
                game.next_required_num = 1
                game.pass_count = 0
                await message.channel.send(embed=we("全員がパスしたため、数字が1に戻ります。"))
            
            game.next_turn()
            await self.send_main_screen(message.channel, game)
            return

        elif "ダウト" in message.content and game.is_accepting_doubt:
            if message.author.id not in game.hands:
                return

            game.is_accepting_doubt = False
            last_player, actual_card = game.field[-1]
            
            if "JK" in actual_card:
                is_lie = False
            else:
                try:
                    actual_num = int(''.join(filter(str.isdigit, actual_card.split('-')[-1])))
                except:
                    actual_num = 0
                is_lie = (actual_num != game.last_claimed_num)
            
            embed = discord.Embed(title="審議結果", color=0xFFFFFF)
            embed.add_field(name="宣言された数字", value=f"{game.last_claimed_num}")
            embed.add_field(name="実際のカード", value=f"{actual_card}")
            
            if is_lie:
                embed.description = f"**嘘でした！**（ダウト成功）\n出した人 <@{last_player}> は場のカードをすべて回収します。"
                penalty_user = last_player
            else:
                embed.description = f"**本当でした！**（ダウト失敗）\nダウトと言った <@{message.author.id}> がすべて回収します。"
                penalty_user = message.author.id
            
            for _, c in game.field:
                game.hands[penalty_user].append(c)
            game.hands[penalty_user].sort()
            game.field.clear()
            
            await message.channel.send(embed=embed)
            
            for p_id in game.players:
                if len(game.hands.get(p_id, [])) == 0:
                    win_embed = discord.Embed(title="Game Set!", description=f"勝者: <@{p_id}>", color=0xFFFFFF)
                    await message.channel.send(embed=win_embed)
                    if message.channel.id in self.games:
                        del self.games[message.channel.id]
                    return

            await self.send_main_screen(message.channel, game)

async def setup(bot):
    await bot.add_cog(Doubt(bot))
