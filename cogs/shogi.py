"""/game の将棋（2人対戦、リアクション選択、手駒・二歩対応）。"""
import asyncio
import io
from pathlib import Path

import discord
from discord.ext import commands
from core import game_panels
from PIL import Image, ImageDraw, ImageFont

from core.shogi_engine import ShogiGame, Color, PieceType, Piece

COLOR = 0x8b4513
RECRUIT_SECONDS = 45
TURN_SECONDS = 90
ASSET_DIR = Path(__file__).resolve().parents[1] / "Assets" / "shogi"
SQUARE_SIZE = 68
MARGIN = 140
BOARD_SIZE = 9 * SQUARE_SIZE
IMG_W = BOARD_SIZE + 2 * MARGIN
IMG_H = BOARD_SIZE + 2 * MARGIN
MOVE_LABELS = tuple("123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
REACTION_PAGE_SIZE = 16
NEXT_PAGE = "➡️"
PREV_PAGE = "⬅️"
HAND_EMOJI = "✋"
CANCEL_EMOJI = "↩️"

def reaction_emoji(label: str) -> str:
    if label in "123456789" and len(label) == 1:
        return f"{label}\ufe0f\u20e3"
    if label in MOVE_LABELS[9:] and len(label) == 1:
        return chr(0x1F1E6 + ord(label) - ord("A"))
    raise ValueError(label)

class ShogiRenderer:
    def __init__(self):
        self.font_label = ImageFont.truetype(str(ASSET_DIR.parent.parent / "font.ttf"), 16)
        self.font_hand = ImageFont.truetype(str(ASSET_DIR.parent.parent / "font.ttf"), 18)
        self.cache = {}

    def _piece_img(self, piece: Piece) -> Image.Image:
        is_gote = piece.color == Color.GOTE
        base = {
            PieceType.KING: "王.png" if not is_gote else "玉.png",
            PieceType.ROOK: "飛.png",
            PieceType.BISHOP: "角.png",
            PieceType.GOLD: "金.png",
            PieceType.SILVER: "銀.png",
            PieceType.KNIGHT: "桂.png",
            PieceType.LANCE: "香.png",
            PieceType.PAWN: "歩.png",
        }.get(piece.type, "なし.png")
        if piece.promoted:
            if piece.type == PieceType.PAWN:
                base = "と金赤.png" if is_gote else "と金.png"
            elif piece.type == PieceType.ROOK:
                base = "龍赤.png" if is_gote else "龍.png"
            elif piece.type == PieceType.BISHOP:
                base = "馬赤.png" if is_gote else "馬.png"
            elif piece.type == PieceType.SILVER:
                base = "成銀赤.png" if is_gote else "成銀.png"
            elif piece.type == PieceType.KNIGHT:
                base = "成桂赤.png" if is_gote else "成桂.png"
            elif piece.type == PieceType.LANCE:
                base = "成香赤.png" if is_gote else "成香.png"
        path = ASSET_DIR / base
        ck = str(path) + ("g" if is_gote else "")
        if ck not in self.cache:
            try:
                im = Image.open(path).convert("RGBA")
                if is_gote:
                    im = im.rotate(180, expand=False)
                im.thumbnail((SQUARE_SIZE - 6, SQUARE_SIZE - 6), Image.Resampling.LANCZOS)
                self.cache[ck] = im
            except Exception:
                self.cache[ck] = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        return self.cache[ck]

    def render(self, game: ShogiGame, labels=None, selected=None) -> io.BytesIO:
        img = Image.new("RGB", (IMG_W, IMG_H), "#f4e4c1")
        draw = ImageDraw.Draw(img)
        # Hands
        draw.rectangle([8, 8, MARGIN - 8, IMG_H // 2 - 8], fill="#edd9b0", outline="#654321", width=2)
        draw.rectangle([IMG_W - MARGIN + 8, IMG_H // 2 + 8, IMG_W - 8, IMG_H - 8], fill="#edd9b0", outline="#654321", width=2)
        self._hand(draw, game.hands[Color.GOTE], 16, 16, "後手の手駒")
        self._hand(draw, game.hands[Color.SENTE], IMG_W - MARGIN + 16, IMG_H - MARGIN + 16, "先手の手駒")

        ox = oy = MARGIN
        for i in range(10):
            draw.line([(ox, oy + i * SQUARE_SIZE), (ox + BOARD_SIZE, oy + i * SQUARE_SIZE)], fill="#222", width=1)
            draw.line([(ox + i * SQUARE_SIZE, oy), (ox + i * SQUARE_SIZE, oy + BOARD_SIZE)], fill="#222", width=1)

        if selected:
            r, f = selected
            draw.rectangle([ox + f * SQUARE_SIZE + 2, oy + r * SQUARE_SIZE + 2,
                            ox + (f + 1) * SQUARE_SIZE - 2, oy + (r + 1) * SQUARE_SIZE - 2], outline="#e4572e", width=4)

        for r in range(9):
            for f in range(9):
                p = game.board[r][f]
                if p:
                    pi = self._piece_img(p)
                    img.paste(pi, (ox + f * SQUARE_SIZE + (SQUARE_SIZE - pi.width) // 2,
                                   oy + r * SQUARE_SIZE + (SQUARE_SIZE - pi.height) // 2), pi)

        if labels:
            for label, (r, f) in labels:
                x = ox + f * SQUARE_SIZE + 4
                y = oy + r * SQUARE_SIZE + 2
                draw.rectangle([x - 1, y - 1, x + 18, y + 16], fill="#ffffffee")
                draw.text((x, y), label, fill="#003399", font=self.font_label)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf

    def _hand(self, draw, hand, x, y, title):
        draw.text((x, y), title, fill="#333", font=self.font_hand)
        yy = y + 26
        for pt in PieceType:
            if hand[pt] > 0:
                draw.text((x, yy), f"{pt.value}×{hand[pt]}", fill="#222", font=self.font_hand)
                yy += 22

class ShogiSession:
    def __init__(self, channel_id, guild_id, host_id):
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.host_id = host_id
        self.players = {}
        self.game = ShogiGame()
        self.phase = "recruit"
        self.state = "select_piece"
        self.selected = None
        self.selected_drop = None
        self.acted = False
        self.renderer = ShogiRenderer()
        self.current_msg = None

class JoinView(discord.ui.View):
    def __init__(self, session):
        super().__init__(timeout=RECRUIT_SECONDS + 30)
        self.session = session

    @discord.ui.button(label="参加（先手/後手）", style=discord.ButtonStyle.success)
    async def join(self, interaction, button):
        s = self.session
        if s.phase != "recruit":
            return await interaction.response.send_message("募集終了", ephemeral=True)
        if interaction.user.id in s.players:
            return await interaction.response.send_message("既に参加中", ephemeral=True)
        if len(s.players) >= 2:
            return await interaction.response.send_message("定員", ephemeral=True)
        s.players[interaction.user.id] = interaction.user
        await interaction.response.send_message("参加しました", ephemeral=True)

    @discord.ui.button(label="抜ける", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction, button):
        s = self.session
        if s.phase != "recruit" or interaction.user.id not in s.players or interaction.user.id == s.host_id:
            return await interaction.response.send_message("抜けられません", ephemeral=True)
        del s.players[interaction.user.id]
        await interaction.response.send_message("参加を取り消しました", ephemeral=True)

class Shogi(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sessions = {}
        self.reaction_sessions = {}

    async def _add_reactions(self, msg, emojis):
        # Parallel-ish for speed
        tasks = [msg.add_reaction(e) for e in emojis]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _clear_reactions(self, msg):
        try:
            await msg.clear_reactions()
        except Exception:
            pass

    async def start_recruit(self, interaction):
        ch = interaction.channel
        if ch.id in self.sessions:
            return await interaction.response.send_message("このチャンネルでは既に将棋中です。", ephemeral=True)
        s = ShogiSession(ch.id, interaction.guild_id, interaction.user.id)
        s.players[interaction.user.id] = interaction.user
        self.sessions[ch.id] = s
        await interaction.response.send_message("将棋の募集を開始しました。", ephemeral=True)
        try:
            msg = await game_panels.replace(ch, "party", embed=discord.Embed(
                title="将棋 参加者募集", description=f"{interaction.user.mention} さんが募集中です。\n{RECRUIT_SECONDS}秒以内に参加してください（2人対戦）。", color=COLOR),
                view=JoinView(s))
            await asyncio.sleep(RECRUIT_SECONDS)
            await self.run_game(ch, s)
        finally:
            s.phase = "done"
            self.sessions.pop(ch.id, None)

    async def _update_board_msg(self, s: ShogiSession, channel, description, labels=None, selected=None, extra_emojis=None):
        buf = s.renderer.render(s.game, labels=labels, selected=selected)
        file = discord.File(buf, "shogi.png")
        embed = discord.Embed(description=description, color=COLOR)
        embed.set_image(url="attachment://shogi.png")
        if s.current_msg is None:
            s.current_msg = await game_panels.replace(channel, "party", embed=embed, file=file)
        else:
            try:
                await s.current_msg.edit(embed=embed, attachments=[file])
            except Exception:
                # Fallback if edit fails
                s.current_msg = await game_panels.replace(channel, "party", embed=embed, file=file)
        await self._clear_reactions(s.current_msg)
        emojis = []
        if labels:
            emojis.extend(reaction_emoji(lab) for lab, _ in labels[:REACTION_PAGE_SIZE])
        if extra_emojis:
            emojis.extend(extra_emojis)
        await self._add_reactions(s.current_msg, emojis)
        self.reaction_sessions[s.current_msg.id] = {"session": s, "labels": dict(labels or [])}

    async def run_game(self, channel, s: ShogiSession):
        if len(s.players) != 2:
            await channel.send("参加者が2人集まらなかったため開始できませんでした。")
            return
        s.phase = "playing"
        ids = list(s.players.values())
        s.players = {Color.SENTE: ids[0], Color.GOTE: ids[1]}
        await channel.send(f"将棋開始！ 先手: {ids[0].mention} / 後手: {ids[1].mention}")
        idle = 0
        while s.phase == "playing":
            turn_user = s.players[s.game.turn]
            s.acted = False
            s.state = "select_piece"
            s.selected = None
            s.selected_drop = None
            selectables = s.game.get_selectable_pieces()
            labels = list(zip(MOVE_LABELS, selectables))[:REACTION_PAGE_SIZE]
            desc = (f"{turn_user.mention} さんの番（{'先手' if s.game.turn == Color.SENTE else '後手'}）。\n"
                    "動ける駒のラベルに対応するリアクションを押すか、✋で手駒を確認してください。")
            await self._update_board_msg(s, channel, desc, labels=labels, extra_emojis=[HAND_EMOJI])
            for _ in range(TURN_SECONDS):
                if s.acted or s.phase != "playing":
                    break
                await asyncio.sleep(1)
            if s.current_msg:
                self.reaction_sessions.pop(s.current_msg.id, None)
            if not s.acted:
                idle += 1
                await channel.send(f"{turn_user.mention} さんは時間切れのためパスしました。")
                if idle >= 2:
                    break
                s.game.turn = Color.GOTE if s.game.turn == Color.SENTE else Color.SENTE
            else:
                idle = 0
        await channel.send("将棋を終了しました。")

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return
        session_data = self.reaction_sessions.get(reaction.message.id)
        if not session_data:
            return
        s: ShogiSession = session_data["session"]
        if s.phase != "playing" or s.players.get(s.game.turn, None) is None or s.players[s.game.turn].id != user.id or s.acted:
            return
        emoji = str(reaction.emoji)
        try:
            await reaction.message.remove_reaction(reaction.emoji, user)
        except Exception:
            pass
        labels = session_data.get("labels", {})
        if emoji == HAND_EMOJI and s.state == "select_piece":
            hand_pieces = s.game.get_hand_pieces()
            if not hand_pieces:
                await reaction.message.channel.send("手駒がありません。", delete_after=3)
                return
            # Switch to hand selection
            s.state = "select_hand"
            hand_labels = list(zip(MOVE_LABELS, hand_pieces))[:REACTION_PAGE_SIZE]
            desc = f"{s.players[s.game.turn].mention} さんの手駒選択。打ちたい駒を選んでください。"
            await self._update_board_msg(s, reaction.message.channel, desc, labels=hand_labels, extra_emojis=[CANCEL_EMOJI])
            return
        if emoji == CANCEL_EMOJI and s.state in ("select_hand", "select_drop_dest"):
            s.state = "select_piece"
            s.selected_drop = None
            # Re-show piece selection
            selectables = s.game.get_selectable_pieces()
            labels = list(zip(MOVE_LABELS, selectables))[:REACTION_PAGE_SIZE]
            desc = f"{s.players[s.game.turn].mention} さんの番。駒を選んでください。"
            await self._update_board_msg(s, reaction.message.channel, desc, labels=labels, extra_emojis=[HAND_EMOJI])
            return
        for label, pos in labels.items():
            if reaction_emoji(label) == emoji:
                if s.state == "select_piece":
                    # Select piece, show destinations
                    s.selected = pos
                    dests = s.game._generate_moves(*pos)
                    if not dests:
                        return
                    s.state = "select_dest"
                    dest_labels = list(zip(MOVE_LABELS, dests))[:REACTION_PAGE_SIZE]
                    desc = f"移動先を選択してください（{len(dests)}箇所）。↩️でキャンセル。"
                    await self._update_board_msg(s, reaction.message.channel, desc, labels=dest_labels, selected=pos, extra_emojis=[CANCEL_EMOJI])
                elif s.state == "select_dest":
                    # Execute move
                    success = s.game.make_move(s.selected, pos, promote=True)
                    if success:
                        s.acted = True
                        # Force refresh on next loop
                elif s.state == "select_hand":
                    # pos is PieceType
                    s.selected_drop = pos
                    drops = s.game.get_drop_squares(pos)
                    if not drops:
                        await reaction.message.channel.send("打てる場所がありません。", delete_after=3)
                        return
                    s.state = "select_drop_dest"
                    drop_labels = list(zip(MOVE_LABELS, drops))[:REACTION_PAGE_SIZE]
                    desc = f"打ち場所を選択してください。↩️でキャンセル。"
                    await self._update_board_msg(s, reaction.message.channel, desc, labels=drop_labels, extra_emojis=[CANCEL_EMOJI])
                elif s.state == "select_drop_dest":
                    success = s.game.make_move(None, pos, drop_type=s.selected_drop)
                    if success:
                        s.acted = True
                break

async def setup(bot):
    await bot.add_cog(Shogi(bot))
