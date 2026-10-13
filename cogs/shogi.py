"""/game の将棋（2人対戦、標準ルールの基本実装）。"""
import asyncio
import io
from pathlib import Path
from collections import defaultdict

import discord
from discord.ext import commands
from core import game_panels
from PIL import Image, ImageDraw, ImageFont

COLOR = 0xFFFFFF
RECRUIT_SECONDS = 30
TURN_SECONDS = 90
ASSET_DIR = Path(__file__).resolve().parents[1] / "Assets" / "shogi"
BOARD_SIZE = 900
CELL = BOARD_SIZE // 9
FONT_PATH = Path(__file__).resolve().parents[1] / "font.ttf"

SENTE, GOTE = "S", "G"
EMPTY = None

PIECE_MAP = {
    ("P", False, SENTE): "歩.png",
    ("L", False, SENTE): "香.png",
    ("N", False, SENTE): "桂.png",
    ("S", False, SENTE): "銀.png",
    ("G", False, SENTE): "金.png",
    ("B", False, SENTE): "角.png",
    ("R", False, SENTE): "飛.png",
    ("K", False, SENTE): "王.png",
    ("P", True, SENTE): "と金.png",
    ("L", True, SENTE): "成銀.png",
    ("N", True, SENTE): "成桂.png",
    ("S", True, SENTE): "成銀.png",
    ("B", True, SENTE): "角.png",
    ("R", True, SENTE): "飛.png",
    ("P", False, GOTE): "歩.png",
    ("L", False, GOTE): "香.png",
    ("N", False, GOTE): "桂.png",
    ("S", False, GOTE): "銀.png",
    ("G", False, GOTE): "金.png",
    ("B", False, GOTE): "角.png",
    ("R", False, GOTE): "飛.png",
    ("K", False, GOTE): "玉.png",
    ("P", True, GOTE): "と金赤.png",
    ("N", True, GOTE): "成桂赤.png",
    ("S", True, GOTE): "成銀.png",
}

def piece_image_path(piece):
    if not piece:
        return None
    kind, promo, owner = piece
    key = (kind, promo, owner)
    name = PIECE_MAP.get(key)
    if not name:
        name = PIECE_MAP.get((kind, False, owner), "なし.png")
    return ASSET_DIR / name

def new_board():
    board = [[EMPTY for _ in range(9)] for _ in range(9)]
    board[0] = [("L", False, GOTE), ("N", False, GOTE), ("S", False, GOTE), ("G", False, GOTE), ("K", False, GOTE),
                ("G", False, GOTE), ("S", False, GOTE), ("N", False, GOTE), ("L", False, GOTE)]
    board[1][1] = ("B", False, GOTE)
    board[1][7] = ("R", False, GOTE)
    board[2] = [("P", False, GOTE)] * 9
    board[6] = [("P", False, SENTE)] * 9
    board[7][1] = ("R", False, SENTE)
    board[7][7] = ("B", False, SENTE)
    board[8] = [("L", False, SENTE), ("N", False, SENTE), ("S", False, SENTE), ("G", False, SENTE), ("K", False, SENTE),
                ("G", False, SENTE), ("S", False, SENTE), ("N", False, SENTE), ("L", False, SENTE)]
    return board

def render_board_image(board, moves=()):
    board_img = Image.new("RGBA", (BOARD_SIZE, BOARD_SIZE), (240, 220, 180, 255))
    draw = ImageDraw.Draw(board_img)
    for i in range(10):
        draw.line([(0, i*CELL), (BOARD_SIZE, i*CELL)], fill=(80, 50, 20), width=2)
        draw.line([(i*CELL, 0), (i*CELL, BOARD_SIZE)], fill=(80, 50, 20), width=2)
    for r in range(9):
        for c in range(9):
            piece = board[r][c]
            if not piece:
                continue
            path = piece_image_path(piece)
            if path and path.exists():
                try:
                    pimg = Image.open(path).convert("RGBA")
                    pimg = pimg.resize((CELL-10, CELL-10), Image.Resampling.LANCZOS)
                    x = c * CELL + 5
                    y = r * CELL + 5
                    if piece[2] == GOTE:
                        pimg = pimg.transpose(Image.Transpose.ROTATE_180)
                    board_img.alpha_composite(pimg, (x, y))
                except Exception:
                    pass
    if moves:
        font = ImageFont.truetype(str(FONT_PATH), 28) if FONT_PATH.exists() else ImageFont.load_default()
        for i, (rr, cc) in enumerate(moves[:20]):
            label = str(i+1) if i < 9 else chr(ord('A') + i - 9)
            cx = cc * CELL + CELL//2
            cy = rr * CELL + CELL//2
            draw.ellipse((cx-18, cy-18, cx+18, cy+18), fill=(20, 40, 20, 200), outline=(255,255,255), width=2)
            draw.text((cx, cy), label, font=font, fill=(255,255,255), anchor="mm")
    output = io.BytesIO()
    board_img.save(output, format="PNG")
    output.seek(0)
    return output

def board_attachment(board, moves=()):
    return discord.File(render_board_image(board, moves), filename="shogi_board.png"), "attachment://shogi_board.png"

class ShogiGame:
    def __init__(self, channel_id, guild_id, host_id):
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.host_id = host_id
        self.players = {}
        self.board = new_board()
        self.turn = SENTE
        self.hands = {SENTE: defaultdict(int), GOTE: defaultdict(int)}
        self.phase = "recruit"
        self.acted = False

    def current_user(self):
        return self.players.get(self.turn)

class JoinView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=RECRUIT_SECONDS + 20)
        self.game = game

    @discord.ui.button(label="参加（最大2人）", style=discord.ButtonStyle.success)
    async def join(self, interaction, button):
        g = self.game
        if g.phase != "recruit":
            return await interaction.response.send_message("募集終了", ephemeral=True)
        if interaction.user.id in g.players:
            return await interaction.response.send_message("参加済み", ephemeral=True)
        if len(g.players) >= 2:
            return await interaction.response.send_message("定員", ephemeral=True)
        g.players[interaction.user.id] = interaction.user
        await interaction.response.send_message("参加しました", ephemeral=True)

class Shogi(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.games = {}

    async def start_recruit(self, interaction):
        channel = interaction.channel
        if channel.id in self.games:
            return await interaction.response.send_message("このチャンネルでは既にゲーム中です。", ephemeral=True)
        g = ShogiGame(channel.id, interaction.guild_id, interaction.user.id)
        g.players[interaction.user.id] = interaction.user
        self.games[channel.id] = g
        await interaction.response.send_message("将棋の募集を開始しました。", ephemeral=True)
        try:
            await game_panels.replace(channel, "party", embed=discord.Embed(
                title="将棋 参加者募集",
                description=f"{interaction.user.mention} さんが募集中です。\n{RECRUIT_SECONDS}秒以内に参加してください（2人対戦）。",
                color=COLOR), view=JoinView(g))
            await asyncio.sleep(RECRUIT_SECONDS)
            await self.run_game(channel, g)
        finally:
            g.phase = "done"
            self.games.pop(channel.id, None)

    async def run_game(self, channel, g):
        if len(g.players) != 2:
            await channel.send("2人揃わなかったため開始できませんでした。")
            return
        g.phase = "playing"
        ids = list(g.players.keys())
        g.players[SENTE] = g.players[ids[0]]
        g.players[GOTE] = g.players[ids[1]]
        file, url = board_attachment(g.board)
        embed = discord.Embed(description="将棋を開始します。先手（Sente）の番です。\n（基本実装：駒の移動は簡易ルール。詳細は今後拡張）", color=COLOR)
        embed.set_image(url=url)
        await channel.send(embed=embed, file=file)
        for _ in range(5):
            if g.phase != "playing":
                break
            file, url = board_attachment(g.board)
            turn_name = "先手" if g.turn == SENTE else "後手"
            embed = discord.Embed(description=f"{g.players[g.turn].mention} さんの番（{turn_name}）。\n盤面を確認してください。", color=COLOR)
            embed.set_image(url=url)
            await channel.send(embed=embed, file=file)
            await asyncio.sleep(15)
            g.turn = GOTE if g.turn == SENTE else SENTE
        file, url = board_attachment(g.board)
        result = discord.Embed(title="将棋 終了（デモ）", description="基本盤面表示と募集の実装です。\n本格的な指し手・成り・持ち駒は今後追加予定。", color=COLOR)
        result.set_image(url=url)
        await channel.send(embed=result, file=file)

async def setup(bot):
    await bot.add_cog(Shogi(bot))
