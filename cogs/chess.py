"""/game のチェス（2人対戦、提供されたスプライトシートを使用）。"""
import asyncio
import io
import random
from pathlib import Path

import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

from core import game_panels

COLOR = 0x6F4E37
RECRUIT_SECONDS = 30
TURN_SECONDS = 90
ASSET = Path(__file__).resolve().parents[1] / "Assets" / "chess" / "IMG_4904.png"
MOVE_LABELS = tuple("123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
REACTION_PAGE_SIZE = 20
NEXT_PAGE = "➡️"
PREVIOUS_PAGE = "⬅️"

# board[row][col], row 0 is rank 8. Uppercase = white, lowercase = black.
BACK_RANK = "RNBQKBNR"
START_BOARD = [list(BACK_RANK.lower()), list("pppppppp"), *([list("........")] * 4),
               list("PPPPPPPP"), list(BACK_RANK)]
DIRECTIONS = {
    "B": ((1, 1), (1, -1), (-1, 1), (-1, -1)),
    "R": ((1, 0), (-1, 0), (0, 1), (0, -1)),
    "Q": ((1, 1), (1, -1), (-1, 1), (-1, -1), (1, 0), (-1, 0), (0, 1), (0, -1)),
}


def reaction_emoji(label):
    if label in "123456789" and len(label) == 1:
        return f"{label}\ufe0f\u20e3"
    if label.isalpha() and len(label) == 1:
        return chr(0x1F1E6 + ord(label.upper()) - ord("A"))
    raise ValueError(label)


def inside(r, c):
    return 0 <= r < 8 and 0 <= c < 8


def color_of(piece):
    return "white" if piece != "." and piece.isupper() else "black"


def clone_board(board):
    return [row[:] for row in board]


def pseudo_moves(board, row, col, *, include_castle=False):
    piece = board[row][col]
    if piece == ".":
        return []
    kind, own = piece.upper(), color_of(piece)
    moves = []
    if kind == "P":
        step = -1 if own == "white" else 1
        start = 6 if own == "white" else 1
        nr = row + step
        if inside(nr, col) and board[nr][col] == ".":
            moves.append((nr, col))
            if row == start and board[row + 2 * step][col] == ".":
                moves.append((row + 2 * step, col))
        for dc in (-1, 1):
            nr, nc = row + step, col + dc
            if inside(nr, nc) and board[nr][nc] != "." and color_of(board[nr][nc]) != own:
                moves.append((nr, nc))
        return moves
    if kind == "N":
        for dr, dc in ((2, 1), (2, -1), (-2, 1), (-2, -1), (1, 2), (1, -2), (-1, 2), (-1, -2)):
            nr, nc = row + dr, col + dc
            if inside(nr, nc) and (board[nr][nc] == "." or color_of(board[nr][nc]) != own):
                moves.append((nr, nc))
        return moves
    if kind == "K":
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                nr, nc = row + dr, col + dc
                if inside(nr, nc) and (board[nr][nc] == "." or color_of(board[nr][nc]) != own):
                    moves.append((nr, nc))
        return moves
    for dr, dc in DIRECTIONS[kind]:
        nr, nc = row + dr, col + dc
        while inside(nr, nc):
            if board[nr][nc] == ".":
                moves.append((nr, nc))
            else:
                if color_of(board[nr][nc]) != own:
                    moves.append((nr, nc))
                break
            nr, nc = nr + dr, nc + dc
    return moves


def king_pos(board, side):
    target = "K" if side == "white" else "k"
    return next(((r, c) for r in range(8) for c in range(8) if board[r][c] == target), None)


def attacked(board, square, by_side):
    kr, kc = square
    for r in range(8):
        for c in range(8):
            if board[r][c] != "." and color_of(board[r][c]) == by_side:
                if board[r][c].upper() == "P":
                    step = -1 if by_side == "white" else 1
                    if (kr, kc) in ((r + step, c - 1), (r + step, c + 1)):
                        return True
                    continue
                if (kr, kc) in pseudo_moves(board, r, c):
                    return True
    return False


def in_check(board, side):
    pos = king_pos(board, side)
    return pos is None or attacked(board, pos, "black" if side == "white" else "white")


def legal_moves(board, side):
    result = []
    for r in range(8):
        for c in range(8):
            if board[r][c] == "." or color_of(board[r][c]) != side:
                continue
            for dest in pseudo_moves(board, r, c):
                trial = clone_board(board)
                trial[dest[0]][dest[1]] = trial[r][c]
                trial[r][c] = "."
                if not in_check(trial, side):
                    result.append(((r, c), dest))
    return result


PIECE_VALUES = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 20000}


def apply_move(board, move):
    """盤面を複製して指し手を適用する。戻り値は新しい盤面。"""
    source, dest = move
    result = clone_board(board)
    piece = result[source[0]][source[1]]
    result[dest[0]][dest[1]] = piece
    result[source[0]][source[1]] = "."
    if piece.upper() == "P" and dest[0] in (0, 7):
        result[dest[0]][dest[1]] = "Q" if piece.isupper() else "q"
    return result


def evaluate(board, side):
    """CPU視点の簡易評価。駒得・中央・合法手数・王手を組み合わせる。"""
    score = 0
    for r, row in enumerate(board):
        for c, piece in enumerate(row):
            if piece == ".":
                continue
            value = PIECE_VALUES[piece.upper()]
            if piece.upper() != "K" and 2 <= r <= 5 and 2 <= c <= 5:
                value += 12
            score += value if color_of(piece) == side else -value
    opponent = "black" if side == "white" else "white"
    score += 4 * (len(legal_moves(board, side)) - len(legal_moves(board, opponent)))
    if in_check(board, opponent):
        score += 70
    if in_check(board, side):
        score -= 70
    return score


def _minimax(board, side_to_move, ai_side, depth, alpha, beta):
    moves = legal_moves(board, side_to_move)
    if depth == 0 or not moves:
        if not moves and in_check(board, side_to_move):
            return (-100000 if side_to_move == ai_side else 100000), None
        return evaluate(board, ai_side), None
    maximizing = side_to_move == ai_side
    best_score = -float("inf") if maximizing else float("inf")
    best_move = None
    opponent = "black" if side_to_move == "white" else "white"
    for move in moves:
        score, _ = _minimax(apply_move(board, move), opponent, ai_side, depth - 1, alpha, beta)
        if (maximizing and score > best_score) or (not maximizing and score < best_score):
            best_score, best_move = score, move
        if maximizing:
            alpha = max(alpha, best_score)
        else:
            beta = min(beta, best_score)
        if beta <= alpha:
            break
    return best_score, best_move


def choose_ai_move(board, side="black", difficulty=5):
    """難易度1〜10でCPUの指し手を選ぶ。重い探索は別スレッドから呼び出す。"""
    difficulty = max(1, min(10, int(difficulty)))
    moves = legal_moves(board, side)
    if not moves:
        return None
    if difficulty <= 2:
        return random.choice(moves)
    depth = 1 if difficulty <= 4 else 2 if difficulty <= 6 else 3
    _, best = _minimax(board, side, side, depth, -float("inf"), float("inf"))
    return best or random.choice(moves)


def move_label(index):
    return MOVE_LABELS[index]


def render_board(board, labels=(), selected=None):
    source = Image.open(ASSET).convert("RGBA")
    board_img = source.crop((0, 0, 740, 800)).resize((800, 800), Image.Resampling.LANCZOS)
    sheet = source
    # source sprite cells: black back/pawns, then white pawns/back.
    sprites = {}
    for side, row_back, row_pawn in (("black", 32, 132), ("white", 590, 680)):
        for idx, kind in enumerate("RNBQKBNR"):
            sprites[(side, kind)] = sheet.crop((760 + idx * 90, row_back, 850 + idx * 90, row_back + 92))
        for idx in range(8):
            sprites[(side, "P")] = sheet.crop((760 + idx * 90, row_pawn, 850 + idx * 90, row_pawn + 92))
    cell = 100
    for r in range(8):
        for c in range(8):
            p = board[r][c]
            if p == ".":
                continue
            sprite = sprites[("white" if p.isupper() else "black", p.upper())]
            sprite.thumbnail((cell - 12, cell - 12), Image.Resampling.LANCZOS)
            board_img.alpha_composite(sprite, (c * cell + (cell - sprite.width) // 2, r * cell + (cell - sprite.height) // 2))
    draw = ImageDraw.Draw(board_img, "RGBA")
    font = ImageFont.truetype(str(ASSET.parents[2] / "font.ttf"), 30)
    if selected:
        r, c = selected
        draw.rectangle((c * cell + 3, r * cell + 3, (c + 1) * cell - 3, (r + 1) * cell - 3), outline=(224, 69, 46, 255), width=7)
    for label, (r, c) in labels:
        cx, cy = c * cell + 50, r * cell + 50
        draw.ellipse((cx - 20, cy - 20, cx + 20, cy + 20), fill=(35, 85, 55, 230), outline="white", width=3)
        draw.text((cx, cy), label, font=font, fill="white", anchor="mm")
    out = io.BytesIO()
    board_img.save(out, format="PNG", optimize=True)
    out.seek(0)
    return out


class ChessGame:
    def __init__(self, channel_id, guild_id, host_id, mode="human", difficulty=5):
        self.channel_id, self.guild_id, self.host_id = channel_id, guild_id, host_id
        self.players = {}
        self.board = clone_board(START_BOARD)
        self.turn = "white"
        self.phase = "recruit"
        self.acted = False
        self.selected = None
        self.current_msg = None
        self.mode = mode
        self.difficulty = max(1, min(10, int(difficulty)))

    def current_user(self):
        return self.players[self.turn]


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
        if g.phase != "recruit" or interaction.user.id not in g.players or interaction.user.id == g.host_id:
            return await interaction.response.send_message("募集主は抜けられません。", ephemeral=True)
        del g.players[interaction.user.id]
        await interaction.response.send_message("参加を取り消しました。", ephemeral=True)


class Chess(commands.Cog):
    def __init__(self, bot):
        self.bot, self.games, self.reaction_sessions = bot, {}, {}

    async def _add_reactions(self, message, emojis):
        await asyncio.gather(
            *(message.add_reaction(emoji) for emoji in emojis),
            return_exceptions=True,
        )

    async def start_recruit(self, interaction, mode="human", difficulty=5):
        channel = interaction.channel
        if channel.id in self.games:
            return await interaction.response.send_message("このチャンネルでは既にチェス中です。", ephemeral=True)
        g = ChessGame(channel.id, interaction.guild_id, interaction.user.id, mode, difficulty)
        if mode == "cpu":
            g.players["white"] = interaction.user
            g.phase = "playing"
            await interaction.response.send_message(f"CPU対戦（難易度 {g.difficulty}/10）を開始します。", ephemeral=True)
            try:
                await self.run_cpu_game(channel, g)
            finally:
                g.phase = "done"
                self.games.pop(channel.id, None)
            return
        g.players[interaction.user.id] = interaction.user
        self.games[channel.id] = g
        await interaction.response.send_message("チェスの募集を開始しました。", ephemeral=True)
        try:
            await game_panels.replace(channel, "party", embed=discord.Embed(
                title="チェス 参加者募集", description=f"{interaction.user.mention} さんが募集中です。\n{RECRUIT_SECONDS}秒以内に参加してください（2人対戦）。", color=COLOR), view=JoinView(g))
            await asyncio.sleep(RECRUIT_SECONDS)
            await self.run_game(channel, g)
        finally:
            g.phase = "done"
            self.games.pop(channel.id, None)

    async def show_turn(self, channel, g):
        side_name = "白" if g.turn == "white" else "黒"
        moves = legal_moves(g.board, g.turn)
        sources = []
        for source, _ in moves:
            if source not in sources:
                sources.append(source)
        labels = [(move_label(i), pos) for i, pos in enumerate(sources[:len(MOVE_LABELS)])]
        desc = f"{g.current_user().mention} さんの番（{side_name}）。駒を選んでください。"
        if in_check(g.board, g.turn):
            desc += "\n王手です。"
        file = discord.File(render_board(g.board, labels, g.selected), filename="chess_board.png")
        embed = discord.Embed(description=desc, color=COLOR)
        embed.set_image(url="attachment://chess_board.png")
        if g.current_msg is None:
            g.current_msg = await game_panels.replace(channel, "party", embed=embed, file=file)
        else:
            await g.current_msg.edit(embed=embed, attachments=[file])
        self.reaction_sessions[g.current_msg.id] = {"game": g, "labels": dict(labels), "sources": sources}
        await self._add_reactions(g.current_msg, [reaction_emoji(label) for label, _ in labels])

    async def run_game(self, channel, g):
        if len(g.players) != 2:
            await channel.send("参加者が2人集まらなかったため開始できませんでした。")
            return
        ids = list(g.players.values())
        g.players = {"white": ids[0], "black": ids[1]}
        g.phase = "playing"
        await channel.send(f"チェス開始！ 白: {ids[0].mention} / 黒: {ids[1].mention}")
        await self._play_loop(channel, g)

    async def run_cpu_game(self, channel, g):
        await channel.send(f"CPU対戦開始！ 白: {g.players['white'].mention} / 黒: CPU（難易度 {g.difficulty}/10）")
        await self._play_loop(channel, g)

    async def _play_loop(self, channel, g):
        while g.phase == "playing":
            if g.mode == "cpu" and g.turn == "black":
                move = await asyncio.to_thread(choose_ai_move, g.board, "black", g.difficulty)
                if move is None:
                    break
                g.board = apply_move(g.board, move)
                g.turn = "white"
                continue
            g.acted = False
            g.selected = None
            await self.show_turn(channel, g)
            for _ in range(TURN_SECONDS):
                if g.acted or g.phase != "playing":
                    break
                await asyncio.sleep(1)
            if not g.acted:
                await channel.send(f"{g.current_user().mention} さんは時間切れです。チェスを終了しました。")
                break
            if not legal_moves(g.board, g.turn):
                break
        await channel.send("チェスを終了しました。")

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return
        data = self.reaction_sessions.get(reaction.message.id)
        if not data:
            return
        g = data["game"]
        if g.phase != "playing" or g.current_user().id != user.id or g.acted:
            return
        try:
            await reaction.message.remove_reaction(reaction.emoji, user)
        except Exception:
            pass
        chosen = next((pos for label, pos in data["labels"].items() if reaction_emoji(label) == str(reaction.emoji)), None)
        if chosen is None:
            return
        if g.selected is None:
            g.selected = chosen
            destinations = [dest for source, dest in legal_moves(g.board, g.turn) if source == chosen]
            labels = [(move_label(i), dest) for i, dest in enumerate(destinations)]
            file = discord.File(render_board(g.board, labels, chosen), filename="chess_board.png")
            embed = discord.Embed(description="移動先を選んでください。", color=COLOR)
            embed.set_image(url="attachment://chess_board.png")
            await reaction.message.edit(embed=embed, attachments=[file])
            self.reaction_sessions[reaction.message.id] = {"game": g, "labels": dict(labels), "sources": destinations}
            await self._add_reactions(reaction.message, [reaction_emoji(label) for label, _ in labels])
            return
        source = g.selected
        if (source, chosen) not in legal_moves(g.board, g.turn):
            return
        piece = g.board[source[0]][source[1]]
        g.board[chosen[0]][chosen[1]] = piece
        g.board[source[0]][source[1]] = "."
        if piece.upper() == "P" and chosen[0] in (0, 7):
            g.board[chosen[0]][chosen[1]] = "Q" if piece.isupper() else "q"
        g.turn = "black" if g.turn == "white" else "white"
        g.acted = True


async def setup(bot):
    await bot.add_cog(Chess(bot))
