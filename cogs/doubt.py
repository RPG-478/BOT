# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import asyncio
import random

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
        # 次に宣言すべき数字を管理
        self.next_required_num = 1
        # パスした人数をカウント
        self.pass_count = 0
        
        self._setup_game()

    def _setup_game(self):
        suits = ["S", "H", "D", "C"]
        deck = [f"[{s}-{r}]" for s in suits for r in range(1, 14)]
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
        selected = self.values[0]
        self.cog.pending_cards[interaction.user.id] = selected
        
        target_num = self.game_engine.next_required_num
        embed = discord.Embed(
            description=f"選んだカード: **{selected}**\n次に、このカードとして「**{target_num}**」とチャットで送信してください。", 
            color=0xFFFFFF
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class GameControlView(discord.ui.View):
    def __init__(self, game_engine, cog):
        super().__init__(timeout=None)
        self.game_engine = game_engine
        self.cog = cog

    @discord.ui.button(label="手札確認", style=discord.ButtonStyle.grey)
    async def check_hand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.game_engine.hands:
            return await interaction.response.send_message("あなたはゲームに参加していません。", ephemeral=True)
            
        hand = self.game_engine.hands.get(interaction.user.id, [])
        hand_str = " ".join(hand) if hand else "手札がありません"
        embed = discord.Embed(title="あなたの手札", description=hand_str, color=0xFFFFFF)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="カードを置く", style=discord.ButtonStyle.red)
    async def play(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.game_engine.hands:
            return await interaction.response.send_message("あなたはゲームに参加していません。", ephemeral=True)
            
        if interaction.user.id != self.game_engine.current_player_id:
            return await interaction.response.send_message("あなたのターンではありません", ephemeral=True)
        
        view = discord.ui.View()
        view.add_item(CardSelect(self.game_engine.hands[interaction.user.id], self.game_engine, self.cog))
        await interaction.response.send_message(f"どのカードを「{self.game_engine.next_required_num}」として出しますか？", view=view, ephemeral=True)

class DoubtJoinView(discord.ui.View):
    def __init__(self, host_id):
        super().__init__(timeout=65) 
        self.players = [host_id]

    @discord.ui.button(label="参加", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.players:
            self.players.append(interaction.user.id)
            await interaction.response.send_message(f"参加しました (現在: {len(self.players)}名)", ephemeral=True)
        else:
            await interaction.response.send_message("既に参加しています", ephemeral=True)

class Doubt(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.games = {}
        self.pending_cards = {}

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
        game.last_panel_msg = await channel.send(embed=embed, view=view)

    async def start_from_hub(self, channel, player_ids):
        await asyncio.sleep(60)
        
        if len(player_ids) < 3:
            return await channel.send("人数不足（3名以上必要）のため、ダウトを開始できませんでした。")
        
        engine = DoubtEngine(player_ids)
        self.games[channel.id] = engine
        await channel.send("3名以上の参加を確認。カードを配り、ゲームを開始します！")
        await self.send_main_screen(channel, engine)

    @commands.command(name="doubt")
    async def start_game(self, ctx):
        view = DoubtJoinView(ctx.author.id)
        embed = discord.Embed(
            title="ダウト参加者募集", 
            description="ボタンを押して参加してください\n**※3名以上で開始します**（募集時間: 60秒）", 
            color=0xFFFFFF
        )
        await ctx.send(embed=embed, view=view)
        await self.start_from_hub(ctx.channel, view.players)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        game = self.games.get(message.channel.id)
        if not game: return

        # パス処理
        if message.author.id == game.current_player_id and message.content == "パス":
            game.pass_count += 1
            # 全員がパスしたらリセット
            if game.pass_count >= len(game.players):
                game.next_required_num = 1
                game.pass_count = 0
                await message.channel.send("全員がパスしたため、数字が1に戻ります。")
            
            game.next_turn()
            await self.send_main_screen(message.channel, game)
            return

        # カードを置く処理
        if message.author.id == game.current_player_id and message.author.id in self.pending_cards:
            if message.content.isdigit():
                val = int(message.content)
                # 指定の数字以外は弾く
                if val != game.next_required_num:
                    await message.channel.send(f"現在は「{game.next_required_num}」を出す番です。", delete_after=3)
                    return

                card = self.pending_cards.pop(message.author.id)
                if card in game.hands[message.author.id]:
                    game.hands[message.author.id].remove(card)
                    game.field.append((message.author.id, card))
                    game.last_claimed_num = val
                    game.last_player_id = message.author.id
                    game.pass_count = 0 # 誰かが出したらパスカウントリセット
                    
                    await message.channel.send(f"<@{message.author.id}> が「**{val}**」を宣言してカードを置きました。5秒間ダウト受付中。")
                    
                    # 次の数字をセット（13の次は1）
                    game.next_required_num = 1 if val == 13 else val + 1
                    
                    game.is_accepting_doubt = True
                    game.next_turn()
                    
                    await asyncio.sleep(5)
                    
                    if game.is_accepting_doubt:
                        game.is_accepting_doubt = False
                        await self.send_main_screen(message.channel, game)

        # ダウト宣言の処理
        elif "ダウト" in message.content and game.is_accepting_doubt:
            if message.author.id not in game.hands:
                return

            game.is_accepting_doubt = False
            last_player, actual_card = game.field[-1]
            
            try:
                actual_num = int(''.join(filter(str.isdigit, actual_card.split('-')[-1])))
            except:
                actual_num = 0
                
            is_lie = (actual_num != game.last_claimed_num)
            
            embed = discord.Embed(title="審議結果", color=0xFFFFFF)
            embed.add_field(name="宣言された数字", value=f"{game.last_claimed_num}")
            embed.add_field(name="実際のカード", value=f"{actual_card}")
            
            if is_lie:
                embed.description = f"**嘘でした！**\n出した人 <@{last_player}> は場のカードをすべて回収します。"
                penalty_user = last_player
            else:
                embed.description = f"**本当でした！**\nダウトと言った <@{message.author.id}> がすべて回収します。"
                penalty_user = message.author.id
            
            for _, c in game.field:
                game.hands[penalty_user].append(c)
            game.hands[penalty_user].sort()
            game.field.clear()
            
            # ダウトが発生したら数字は1に戻る
            game.next_required_num = 1
            
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