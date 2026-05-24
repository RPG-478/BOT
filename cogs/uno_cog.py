import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import re

# ==========================================
# 1. UNOのゲームロジック・データ管理クラス
# ==========================================
class UnoGame:
    def __init__(self, channel_id, host_id):
        self.channel_id = channel_id
        self.host_id = host_id
        self.players = []           # プレイヤーIDのリスト
        self.hands = {}             # {player_id: [カード文字列のリスト]}
        self.deck = []              # 山札
        self.discard_pile = []      # 捨て札
        self.current_player_idx = 0
        self.direction = 1          # 1: 正順, -1: 逆順
        self.is_started = False
        self.current_color = None   # ワイルド等で変更された現在指定されている色
        
        # 内部処理用
        self.active_panel_message = None  # 現在アクティブなコントロールパネルのDiscordメッセージ
        self.uno_declared = False         # 現ターンでUNO宣言が成功したか
        self.waiting_for_uno = False      # UNO宣言の猶予時間中か

    def setup_deck(self):
        colors = ['赤', '青', '黄', '緑']
        numbers = [str(i) for i in range(10)] + ['Skip', 'Reverse', '+2']
        specials = ['Wild', 'Wild+4']
        
        self.deck = []
        # 通常カードの追加
        for color in colors:
            for num in numbers:
                count = 1 if num == '0' else 2
                for _ in range(count):
                    self.deck.append(f"{color}の{num}")
        # ワイルドカードの追加
        for spec in specials:
            for _ in range(4):
                self.deck.append(spec)
        
        random.shuffle(self.deck)

    def draw_card(self, player_id, count=1):
        drawn = []
        for _ in range(count):
            if not self.deck:
                if len(self.discard_pile) > 1:
                    top_card = self.discard_pile.pop()
                    self.deck = self.discard_pile.copy()
                    self.discard_pile = [top_card]
                    random.shuffle(self.deck)
                else:
                    break # これ以上引けない
            if self.deck:
                drawn.append(self.deck.pop())
        self.hands[player_id].extend(drawn)
        return drawn

    def get_playable_cards(self, player_id):
        """ルール上、出すことができるカードを絞り込む"""
        hand = self.hands.get(player_id, [])
        playable = []
        
        if not self.discard_pile:
            return hand.copy()
            
        top_card = self.discard_pile[-1]
        
        # ワイルドなどで色が変わっている場合、その色を基準にする
        target_color = self.current_color
        
        # 一番上のカードのパース (例: "赤の5", "青のSkip", "Wild")
        top_color = None
        top_value = None
        if "の" in top_card:
            top_color, top_value = top_card.split("の")
            
        if target_color is None:
            target_color = top_color

        for card in hand:
            if card in ["Wild", "Wild+4"]:
                playable.append(card)
                continue
                
            if "の" in card:
                c_color, c_value = card.split("の")
                # 色が同じ、または数字・効果が同じなら出せる
                if c_color == target_color or c_value == top_value:
                    playable.append(card)
                    
        return playable

    def next_turn_idx(self, steps=1):
        """次の手番のインデックスを計算する"""
        n = len(self.players)
        return (self.current_player_idx + self.direction * steps) % n

    def advance_turn(self, steps=1):
        self.current_player_idx = self.next_turn_idx(steps)


# ==========================================
# 2. UI コンポーネント (ボタン・セレクトメニュー)
# ==========================================

class JoinView(discord.ui.View):
    """参加受付用のビューパネル"""
    def __init__(self, game: UnoGame, cog):
        super().__init__(timeout=60.0)
        self.game = game
        self.cog = cog

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.green, custom_id="uno_join_btn")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game.is_started:
            return await interaction.response.send_message("既にゲームは開始されています。", ephemeral=True)
        if interaction.user.id in self.game.players:
            return await interaction.response.send_message("既に参加しています！", ephemeral=True)
            
        self.game.players.append(interaction.user.id)
        self.game.hands[interaction.user.id] = []
        
        embed = interaction.message.embeds[0]
        # 参加者リストを更新
        players_text = "\n".join([f"• <@{p_id}>" for p_id in self.game.players])
        embed.set_field_at(0, name=f"参加者 ({len(self.game.players)}人)", value=players_text, inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="即時スタート", style=discord.ButtonStyle.blurple, custom_id="uno_force_start_btn")
    async def force_start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host_id:
            return await interaction.response.send_message("ホスト（部屋を建てた人）だけが即時スタートできます。", ephemeral=True)
        if len(self.game.players) < 2:
            return await interaction.response.send_message("開始するには最低2人のプレイヤーが必要です！", ephemeral=True)
            
        self.stop() # タイマータスクを終了させる
        await interaction.response.defer()
        await self.cog.start_uno_game(interaction.channel, self.game)

    @discord.ui.button(label="ゲームをキャンセル", style=discord.ButtonStyle.red, custom_id="uno_cancel_btn")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host_id:
            return await interaction.response.send_message("ホスト（部屋を建てた人）だけがキャンセルできます。", ephemeral=True)
            
        self.stop()
        if self.game.channel_id in self.cog.games:
            del self.cog.games[self.game.channel_id]
        
        await interaction.response.edit_message(content="⚠️ ゲームの募集がキャンセルされました。", embed=None, view=None)


class CardSelect(discord.ui.Select):
    """手番プレイヤーがカードを選択するセレクトメニュー"""
    def __init__(self, game: UnoGame, playable_cards: list, cog):
        self.game = game
        self.cog = cog
        
        options = []
        # 出せるカードをセレクトオプションに追加
        for card in playable_cards:
            options.append(discord.SelectOption(label=card, value=card, emoji="🃏"))
            
        # 出せるカードがない、またはパスを明示的に選べるよう常にパス選択肢を用意
        options.append(discord.SelectOption(label="山札から1枚引く (パス)", value="DRAW_PASS", emoji="➕"))
        
        super().__init__(placeholder="出すカードを選択してください...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        current_player_id = self.game.players[self.game.current_player_idx]
        if interaction.user.id != current_player_id:
            return await interaction.response.send_message("あなたの番ではありません！", ephemeral=True)

        selected_card = self.values[0]
        await interaction.response.defer() # ボタン押下後の読み込み中対策

        if selected_card == "DRAW_PASS":
            # 1枚引く
            drawn = self.game.draw_card(current_player_id, 1)
            drawn_str = drawn[0] if drawn else "なし"
            
            # 引いたカードが今出せるかチェック
            self.game.current_color = None # 一旦色指定をリセットして通常チェック
            playable_now = self.game.get_playable_cards(current_player_id)
            
            if drawn[0] in playable_now:
                # 引いたカードを出せる場合、自動で出すか選ばせる追加演出も可能ですが、
                # シンプルにするため引いた後に手番を交代します
                msg = f"🃏 <@{current_player_id}> さんは山札から1枚引きました（{drawn_str}）。出せる状態ですがパスしました。"
            else:
                msg = f"🃏 <@{current_player_id}> さんは出せるカードがないため、山札から1枚引きました。"
                
            self.game.advance_turn()
            await self.cog.send_game_panel(interaction.channel, self.game, info_msg=msg)
            return

        # カードを出す処理
        self.game.hands[current_player_id].remove(selected_card)
        self.game.discard_pile.append(selected_card)
        self.game.current_color = None # 通常カードを出した際は色変更リセット

        # UNO宣言が必要な状況か判定 (手札が1枚になった時)
        hand_len = len(self.game.hands[current_player_id])
        uno_penalty_check = False
        
        if hand_len == 1:
            uno_penalty_check = True
            self.game.uno_declared = False
            self.game.waiting_for_uno = True
            # 非同期で5秒間の「UNO」発言監視を開始
            asyncio.create_task(self.cog.uno_declaration_timer(interaction.channel, self.game, current_player_id))

        # 特殊カードの効果処理
        action_msg = f"📤 <@{current_player_id}> さんが **[{selected_card}]** を出しました！"
        
        if selected_card in ["Wild", "Wild+4"]:
            # 色指定セレクト用のビューを送り、手番処理は色指定後に回す
            view = WildColorView(self.game, selected_card, current_player_id, self.cog, action_msg, uno_penalty_check)
            
            # 手札を見る用のパネルは消去する
            if self.game.active_panel_message:
                try:
                    await self.game.active_panel_message.delete()
                except discord.NotFound:
                    pass
            
            self.game.active_panel_message = await interaction.channel.send(
                content=f"<@{current_player_id}> さん、次の色を選択してください！", 
                view=view
            )
            return

        # 通常＆その他の特殊カードの処理
        await self.process_card_effect(selected_card, action_msg)


    async def process_card_effect(self, card: str, base_msg: str):
        """カードの効果処理を行い、次のターンへ移行する"""
        current_player_id = self.game.players[self.game.current_player_idx]
        
        # 勝敗判定
        if len(self.game.hands[current_player_id]) == 0:
            await self.cog.finish_game(self.game.channel_id, current_player_id)
            return

        next_msg = ""
        
        # スキップ、リバース、+2の効果分岐
        if "Skip" in card:
            skipped_player = self.game.players[self.game.next_turn_idx(1)]
            next_msg = f"\n🚫 <@{skipped_player}> さんのターンがスキップされました！"
            self.game.advance_turn(2) # 1人飛ばして進める
            
        elif "Reverse" in card:
            if len(self.game.players) == 2:
                # 2人プレイ時のリバースはスキップと同じ挙動
                skipped_player = self.game.players[self.game.next_turn_idx(1)]
                next_msg = f"\n🔄 2人プレイのため、<@{skipped_player}> さんのターンがスキップされました！"
                self.game.advance_turn(2)
            else:
                self.game.direction *= -1
                next_msg = f"\n🔄 順番が逆回転になりました！"
                self.game.advance_turn(1)
                
        elif "+2" in card:
            target_player = self.game.players[self.game.next_turn_idx(1)]
            drawn_cards = self.game.draw_card(target_player, 2)
            next_msg = f"\n⚠️ <@{target_player}> さんは2枚引かされ、手番がスキップされました！"
            self.game.advance_turn(2) # 引かされたプレイヤーはパスされる
            
        else:
            # 通常の数字カード
            self.game.advance_turn(1)

        combined_msg = base_msg + next_msg
        await self.cog.send_game_panel(self.cog.bot.get_channel(self.game.channel_id), self.game, info_msg=combined_msg)


class WildColorView(discord.ui.View):
    """ワイルドカード使用時に色を選ぶボタン群"""
    def __init__(self, game: UnoGame, card_type: str, player_id: int, cog, action_msg: str, uno_penalty: bool):
        super().__init__(timeout=30.0)
        self.game = game
        self.card_type = card_type
        self.player_id = player_id
        self.cog = cog
        self.action_msg = action_msg
        self.uno_penalty = uno_penalty

    async def handle_color_choice(self, interaction: discord.Interaction, color: str):
        if interaction.user.id != self.player_id:
            return await interaction.response.send_message("あなたの選択パネルではありません！", ephemeral=True)
            
        await interaction.response.defer()
        self.game.current_color = color
        
        color_msg = f"\n🎨 場の色が **[{color}]** に指定されました！"
        effect_msg = ""
        
        if self.card_type == "Wild+4":
            target_player = self.game.players[self.game.next_turn_idx(1)]
            self.game.draw_card(target_player, 4)
            effect_msg = f"\n🔥 <@{target_player}> さんは4枚引かされ、手番がスキップされました！"
            self.game.advance_turn(2)
        else:
            self.game.advance_turn(1)
            
        # 勝利チェック
        if len(self.game.hands[self.player_id]) == 0:
            await self.cog.finish_game(self.game.channel_id, self.player_id)
            return

        combined_msg = self.action_msg + color_msg + effect_msg
        await self.cog.send_game_panel(interaction.channel, self.game, info_msg=combined_msg)

    @discord.ui.button(label="赤", style=discord.ButtonStyle.danger, custom_id="color_red")
    async def red(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_color_choice(interaction, "赤")

    @discord.ui.button(label="青", style=discord.ButtonStyle.primary, custom_id="color_blue")
    async def blue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_color_choice(interaction, "青")

    @discord.ui.button(label="黄", style=discord.ButtonStyle.success, custom_id="color_yellow")
    async def yellow(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 黄色を緑（Success）と分けたいが、ButtonStyleのバリエーション上Success(緑)と区分
        await self.handle_color_choice(interaction, "黄")

    @discord.ui.button(label="緑", style=discord.ButtonStyle.secondary, custom_id="color_green")
    async def green(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_color_choice(interaction, "緑")


class GameControlView(discord.ui.View):
    """メインゲーム進行中、手番プレイヤーが使用する操作ビュー"""
    def __init__(self, game: UnoGame, playable_cards: list, cog):
        super().__init__(timeout=180.0) # 3分の操作タイムアウト
        self.game = game
        self.cog = cog
        
        # セレクトメニューをこのビューに追加
        self.add_item(CardSelect(game, playable_cards, cog))


# ==========================================
# 3. Discord Bot Cog 本体
# ==========================================
class Uno(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.games = {} # {channel_id: UnoGame}

    @app_commands.command(name="uno_start", description="UNOゲームを開始し、参加者を募集します。")
    async def uno_start(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        
        if channel_id in self.games:
            return await interaction.response.send_message("⚠️ このチャンネルでは既にUNOゲームが進行中、または準備中です。", ephemeral=True)
            
        game = UnoGame(channel_id, interaction.user.id)
        # 作成者を最初のプレイヤーとして自動登録
        game.players.append(interaction.user.id)
        game.hands[interaction.user.id] = []
        self.games[channel_id] = game

        embed = discord.Embed(
            title="🃏 UNO（ウノ）対戦ルーム",
            description="ゲームを開始するには2人以上のプレイヤーが必要です。\n1分後に自動的にゲームが開始されます。",
            color=discord.Color.gold()
        )
        embed.add_field(name=f"参加者 (1人)", value=f"• <@{interaction.user.id}>", inline=False)
        embed.set_footer(text="ホストはボタンから即時開始またはキャンセルが行えます。")

        view = JoinView(game, self)
        await interaction.response.send_message("📢 UNOゲームの募集を開始しました！", ephemeral=True)
        game.active_panel_message = await interaction.channel.send(embed=embed, view=view)

        # 1分間の待機処理
        await asyncio.sleep(60)
        
        # 1分経過後にまだ開始されていないか確認 (キャンセルされてないか、強制起動されてないか)
        if channel_id in self.games and not game.is_started:
            if len(game.players) >= 2:
                await self.start_uno_game(interaction.channel, game)
            else:
                del self.games[channel_id]
                try:
                    await game.active_panel_message.edit(content="⚠️ 参加人数が足りなかったため（最低2人）、ゲームの募集を終了しました。", embed=None, view=None)
                except discord.NotFound:
                    pass

    async def start_uno_game(self, channel, game: UnoGame):
        game.is_started = True
        game.setup_deck()
        
        # 全員に7枚配る
        for p_id in game.players:
            game.draw_card(p_id, 7)
            
        # 最初の1枚（ワイルド系以外が出るまで繰り返す）
        first_card = game.deck.pop()
        while first_card in ["Wild", "Wild+4"]:
            game.deck.insert(0, first_card) # 山札の下（または中身）に戻してシャッフル
            random.shuffle(game.deck)
            first_card = game.deck.pop()
            
        game.discard_pile.append(first_card)
        
        # 最初のカードの「色」をパースして設定
        if "の" in first_card:
            game.current_color = first_card.split("の")[0]

        start_msg = f"🎉 UNOゲームがスタートしました！\n最初の場カードは **[{first_card}]** です。"
        await self.send_game_panel(channel, game, info_msg=start_msg)

    async def send_game_panel(self, channel, game: UnoGame, info_msg: str = ""):
        """ターン進行用の総合ゲームパネルを送信する"""
        # 以前のアクティブなパネルを消去
        if game.active_panel_message:
            try:
                await game.active_panel_message.delete()
            except discord.NotFound:
                pass

        current_player_id = game.players[game.current_player_idx]
        playable_cards = game.get_playable_cards(current_player_id)
        
        # 場の色・状況のテキスト化
        current_top = game.discard_pile[-1]
        active_color = game.current_color if game.current_color else current_top.split("の")[0]

        embed = discord.Embed(
            title="🎮 UNO プレイ中",
            description=info_msg if info_msg else "各自カードを選択してゲームを進めてください。",
            color=self.get_embed_color(active_color)
        )
        embed.add_field(name="現在の場のカード", value=f"👉 **[{current_top}]**", inline=True)
        embed.add_field(name="指定された色", value=f"🎨 **[{active_color}]**", inline=True)
        
        # 順番リストの作成
        order_list = []
        for idx, p_id in enumerate(game.players):
            hand_count = len(game.hands[p_id])
            marker = "▶️ " if idx == game.current_player_idx else "• "
            order_list.append(f"{marker}<@{p_id}>: 手札 {hand_count}枚")
            
        embed.add_field(name="プレイヤー順", value="\n".join(order_list), inline=False)
        embed.set_footer(text="手番プレイヤーは下のセレクトメニューからカードを出せます。")

        view = GameControlView(game, playable_cards, self)
        game.active_panel_message = await channel.send(embed=embed, view=view)

    def get_embed_color(self, color_name):
        colors = {
            '赤': discord.Color.red(),
            '青': discord.Color.blue(),
            '黄': discord.Color.gold(),
            '緑': discord.Color.green()
        }
        return colors.get(color_name, discord.Color.dark_grey())

    # ==========================================
    # 4. UNO宣言システム (チャットイベント検知)
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        channel_id = message.channel.id
        if channel_id not in self.games:
            return

        game = self.games[channel_id]
        if not game.is_started or not game.waiting_for_uno:
            return

        # 最新のターンプレイヤーを取得
        last_player_id = game.players[game.current_player_idx]
        
        # 該当プレイヤーが「うの、ウノ、UNO、uno」を発言したか正規表現でチェック
        if message.author.id == last_player_id:
            content = message.content.strip().lower()
            if re.fullmatch(r"(うの|ウノ|uno)", content):
                game.uno_declared = True
                await message.reply("📣 **「ウノ！」宣言が確認されました！セーフ！**")

    async def uno_declaration_timer(self, channel, game: UnoGame, player_id: int):
        """カードを出してから5秒間、UNO発言を待つタイマー"""
        await asyncio.sleep(5.0)
        
        # 5秒経った時点でゲームが続いており、かつそのプレイヤーの手札が1枚のままの場合
        if game.channel_id in self.games and len(game.hands.get(player_id, [])) == 1:
            if not game.uno_declared:
                # ペナルティとして1枚引かせる
                drawn = game.draw_card(player_id, 1)
                drawn_str = f"（{drawn[0]}）" if drawn else ""
                
                await channel.send(
                    f"⏰ **ペナルティ！** <@{player_id}> さんは5秒以内に「UNO」の宣言がなかったため、山札から1枚引きました。{drawn_str}"
                )
                
                # 手札が2枚に戻るため、ゲーム表示を最新にする
                await self.send_game_panel(channel, game, info_msg=f"⚠️ <@{player_id}> さんにUNO未宣言ペナルティが適用されました。")
            
            # 状態をリセット
            game.waiting_for_uno = False
            game.uno_declared = False

    async def finish_game(self, channel_id: int, winner_id: int):
        """ゲーム終了時の勝者発表処理"""
        channel = self.bot.get_channel(channel_id)
        
        embed = discord.Embed(
            title="🏆 UNO ゲーム決着！",
            description=f"🎉🎉 <@{winner_id}> さんが手札をすべて使い切り、見事勝利しました！ 🎉🎉",
            color=discord.Color.brand_green()
        )
        
        if channel_id in self.games:
            game = self.games[channel_id]
            # 各自の最終残手札を公開
            remains = []
            for p_id in game.players:
                if p_id != winner_id:
                    cards_str = ", ".join(game.hands[p_id])
                    remains.append(f"<@{p_id}>: {cards_str} ({len(game.hands[p_id])}枚)")
            if remains:
                embed.add_field(name="他のプレイヤーの残り手札", value="\n".join(remains), inline=False)
                
            # メッセージお片付け
            if game.active_panel_message:
                try:
                    await game.active_panel_message.delete()
                except discord.NotFound:
                    pass
            del self.games[channel_id]

        await channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Uno(bot))
