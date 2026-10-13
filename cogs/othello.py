"""/game のオセロ（2人対戦、標準8x8ルール）。"""
import asyncio

import discord
from discord.ext import commands
from core import game_panels

COLOR = 0xFFFFFF
RECRUIT_SECONDS = 30
TURN_SECONDS = 60
EMPTY, BLACK, WHITE = ".", "●", "○"
DIRECTIONS = [(dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0)]


def new_board():
    b = [[EMPTY] * 8 for _ in range(8)]
    b[3][3], b[4][4], b[3][4], b[4][3] = WHITE, WHITE, BLACK, BLACK
    return b


def captures(board, player, row, col):
    if not (0 <= row < 8 and 0 <= col < 8) or board[row][col] != EMPTY:
        return []
    other = WHITE if player == BLACK else BLACK
    found = []
    for dr, dc in DIRECTIONS:
        path, r, c = [], row + dr, col + dc
        while 0 <= r < 8 and 0 <= c < 8 and board[r][c] == other:
            path.append((r, c)); r += dr; c += dc
        if path and 0 <= r < 8 and 0 <= c < 8 and board[r][c] == player:
            found.extend(path)
    return found


def legal_moves(board, player):
    return [(r, c) for r in range(8) for c in range(8) if captures(board, player, r, c)]


def play_move(board, player, row, col):
    flipped = captures(board, player, row, col)
    if not flipped:
        return False
    board[row][col] = player
    for r, c in flipped:
        board[r][c] = player
    return True


def render(board):
    header = "  A B C D E F G H"
    rows = [f"{r+1} " + " ".join(board[r]) for r in range(8)]
    return "```\n" + header + "\n" + "\n".join(rows) + "\n```"


class OthelloGame:
    def __init__(self, channel_id, guild_id, host_id):
        self.channel_id, self.guild_id, self.host_id = channel_id, guild_id, host_id
        self.players = {}
        self.board = new_board()
        self.turn = BLACK
        self.pass_count = 0
        self.acted = False
        self.phase = "recruit"

    def current_user(self):
        return self.players[BLACK if self.turn == BLACK else WHITE]

    def score(self):
        return sum(cell == BLACK for row in self.board for cell in row), sum(cell == WHITE for row in self.board for cell in row)


class JoinView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=RECRUIT_SECONDS + 30)
        self.game = game

    @discord.ui.button(label="参加（最大2人）", style=discord.ButtonStyle.success)
    async def join(self, interaction, button):
        g = self.game
        if g.phase != "recruit":
            return await interaction.response.send_message("募集は終了しました。", ephemeral=True)
        if interaction.user.id in g.players:
            return await interaction.response.send_message("すでに参加しています。", ephemeral=True)
        if len(g.players) >= 2:
            return await interaction.response.send_message("定員です。", ephemeral=True)
        g.players[interaction.user.id] = interaction.user
        await interaction.response.send_message("参加しました。", ephemeral=True)

    @discord.ui.button(label="抜ける", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction, button):
        g = self.game
        if g.phase != "recruit" or interaction.user.id not in g.players:
            return await interaction.response.send_message("参加中の募集がありません。", ephemeral=True)
        if interaction.user.id == g.host_id:
            return await interaction.response.send_message("募集主は抜けられません。", ephemeral=True)
        del g.players[interaction.user.id]
        await interaction.response.send_message("参加を取り消しました。", ephemeral=True)


class MoveSelect(discord.ui.Select):
    def __init__(self, cog, game, moves, page=0):
        self.cog, self.game, self.moves = cog, game, moves
        self.page = page
        start = page * 25
        options = [discord.SelectOption(label=f"{chr(65+c)}{r+1}", value=str(i))
                   for i, (r, c) in enumerate(moves[start:start + 25], start)]
        super().__init__(placeholder="置くマスを選択", options=options)

    async def callback(self, interaction):
        r, c = self.moves[int(self.values[0])]
        await self.cog.submit_move(interaction, self.game, r, c)


class MoveView(discord.ui.View):
    def __init__(self, cog, game, moves):
        super().__init__(timeout=TURN_SECONDS)
        self.cog, self.game, self.moves, self.page = cog, game, moves, 0
        self.add_item(MoveSelect(cog, game, moves, self.page))
        if len(moves) > 25:
            self.add_item(discord.ui.Button(label="次の候補", style=discord.ButtonStyle.secondary))
            self.children[-1].callback = self.next_page

    async def next_page(self, interaction):
        self.page = (self.page + 1) % ((len(self.moves) + 24) // 25)
        self.clear_items()
        self.add_item(MoveSelect(self.cog, self.game, self.moves, self.page))
        if len(self.moves) > 25:
            button = discord.ui.Button(label="次の候補", style=discord.ButtonStyle.secondary)
            button.callback = self.next_page
            self.add_item(button)
        await interaction.response.edit_message(view=self)


class TurnView(discord.ui.View):
    def __init__(self, cog, game):
        super().__init__(timeout=TURN_SECONDS + 10)
        self.cog, self.game = cog, game

    @discord.ui.button(label="置くマスを選ぶ", style=discord.ButtonStyle.primary)
    async def choose(self, interaction, button):
        g = self.game
        if interaction.user.id != g.current_user().id or g.acted:
            return await interaction.response.send_message("あなたの番ではありません。", ephemeral=True)
        await interaction.response.send_message(render(g.board) + "\n置く場所を選んでください。",
                                                view=MoveView(self.cog, g, legal_moves(g.board, g.turn)), ephemeral=True)


class Othello(commands.Cog):
    def __init__(self, bot):
        self.bot, self.games = bot, {}

    async def start_recruit(self, interaction):
        channel = interaction.channel
        if channel.id in self.games:
            return await interaction.response.send_message("このチャンネルでは既にゲーム中です。", ephemeral=True)
        g = OthelloGame(channel.id, interaction.guild_id, interaction.user.id)
        g.players[interaction.user.id] = interaction.user
        self.games[channel.id] = g
        await interaction.response.send_message("オセロの募集を開始しました。", ephemeral=True)
        try:
            await game_panels.replace(channel, "party", embed=discord.Embed(
                title="オセロ 参加者募集", description=f"{interaction.user.mention} さんが募集中です。\n{RECRUIT_SECONDS}秒以内に参加してください（2人対戦）。", color=COLOR), view=JoinView(g))
            await asyncio.sleep(RECRUIT_SECONDS)
            await self.run_game(channel, g)
        finally:
            g.phase = "done"
            self.games.pop(channel.id, None)

    async def submit_move(self, interaction, g, row, col):
        if g.phase != "playing" or interaction.user.id != g.current_user().id or g.acted:
            return await interaction.response.send_message("この手は受け付けられません。", ephemeral=True)
        if not play_move(g.board, g.turn, row, col):
            return await interaction.response.send_message("その場所には置けません。", ephemeral=True)
        g.acted = True
        await interaction.response.send_message(f"{chr(65+col)}{row+1} に置きました。", ephemeral=True)

    async def run_game(self, channel, g):
        if len(g.players) != 2:
            await channel.send("参加者が2人集まらなかったため、オセロを開始できませんでした。")
            return
        g.phase = "playing"
        g.players[BLACK], g.players[WHITE] = list(g.players.values())
        await channel.send("オセロを開始します。黒（●）が先手です。\n" + render(g.board))
        idle = 0
        while g.phase == "playing":
            moves = legal_moves(g.board, g.turn)
            if not moves:
                g.pass_count += 1
                if g.pass_count >= 2 or all(cell != EMPTY for row in g.board for cell in row):
                    break
                g.turn = WHITE if g.turn == BLACK else BLACK
                await channel.send(f"{g.players[BLACK if g.turn == WHITE else WHITE].mention} さんは置ける場所がないためパス。\n{render(g.board)}")
                continue
            g.acted = False
            color, uid = g.turn, g.current_user().id
            await game_panels.replace(channel, "party", embed=discord.Embed(
                description=f"{g.players[color].mention} さんの番（{ '黒 ●' if color == BLACK else '白 ○'}）。\n{render(g.board)}", color=COLOR), view=TurnView(self, g))
            for _ in range(TURN_SECONDS):
                if g.acted or g.phase != "playing": break
                await asyncio.sleep(1)
            if g.acted:
                idle = 0
                g.pass_count = 0
                g.turn = WHITE if color == BLACK else BLACK
            else:
                idle += 1
                await channel.send(f"{g.players[color].mention} さんは時間切れのためパスしました。")
                g.pass_count += 1
                g.turn = WHITE if color == BLACK else BLACK
                if idle >= 2: break
        g.phase = "done"
        black, white = g.score()
        outcome = "引き分け" if black == white else f"勝者: {g.players[BLACK if black > white else WHITE].mention}"
        await channel.send(embed=discord.Embed(title="オセロ 終了", description=f"{outcome}\n黒: {black} / 白: {white}\n\n{render(g.board)}", color=COLOR))


async def setup(bot):
    await bot.add_cog(Othello(bot))
