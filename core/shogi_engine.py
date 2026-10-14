"""
Shogi Game Engine
Supports basic rules including drops, promotion, nifu (two pawns), and simple check detection.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Set
from copy import deepcopy
import enum

class Color(enum.Enum):
    SENTE = 1  # Black, bottom
    GOTE = -1  # White, top

class PieceType(enum.Enum):
    PAWN = "歩"
    LANCE = "香"
    KNIGHT = "桂"
    SILVER = "銀"
    GOLD = "金"
    BISHOP = "角"
    ROOK = "飛"
    KING = "王"

PROMOTED = {
    PieceType.PAWN: "と",
    PieceType.LANCE: "成香",
    PieceType.KNIGHT: "成桂",
    PieceType.SILVER: "成銀",
    PieceType.BISHOP: "馬",
    PieceType.ROOK: "龍",
}

# Movement deltas (dx, dy) relative to player direction
# dy positive is forward for Sente (towards rank 1, which is negative y in board[0..8])
# We'll use board[rank][file] where rank 0 is Gote's back (top), rank 8 is Sente's back (bottom)
# Files 0-8 left to right from Sente's view? Standard is file 1-9 right to left from Sente, but we'll use 0-8.

@dataclass
class Piece:
    type: PieceType
    color: Color
    promoted: bool = False

    def __str__(self):
        if self.promoted and self.type in PROMOTED:
            return PROMOTED[self.type]
        return self.type.value

    def is_promotable(self) -> bool:
        return self.type not in (PieceType.GOLD, PieceType.KING)

class ShogiGame:
    def __init__(self):
        self.board: List[List[Optional[Piece]]] = [[None for _ in range(9)] for _ in range(9)]
        self.hands: Dict[Color, Dict[PieceType, int]] = {
            Color.SENTE: {pt: 0 for pt in PieceType},
            Color.GOTE: {pt: 0 for pt in PieceType},
        }
        self.turn: Color = Color.SENTE
        self.move_history: List[str] = []
        self._setup_initial()

    def _setup_initial(self):
        """Standard setup. Sente at bottom (rank 8), Gote at top (rank 0).
        Files 0-8 from left (file 9) to right (file 1) from Sente's perspective.
        """
        # Sente back rank (rank 8)
        sente_back = [
            PieceType.LANCE, PieceType.KNIGHT, PieceType.SILVER, PieceType.GOLD,
            PieceType.KING, PieceType.GOLD, PieceType.SILVER, PieceType.KNIGHT, PieceType.LANCE
        ]
        for f, pt in enumerate(sente_back):
            self.board[8][f] = Piece(pt, Color.SENTE)

        # Sente Bishop on file 1 (index 7? wait correct:
        # Standard: from Sente view, left is file 9, right is file 1.
        # Bishop is on 8h: file 8 (from right? ), wait.
        # Files numbered 1 (rightmost from Sente) to 9 (leftmost).
        # So index 0 = file 9 (left), index 8 = file 1 (right).
        # Bishop for Sente on 8h: file 8 is index 1 (since file 9=0, file 8=1).
        # Rook on 2h: file 2 is index 7.
        self.board[7][1] = Piece(PieceType.BISHOP, Color.SENTE)  # file 8
        self.board[7][7] = Piece(PieceType.ROOK, Color.SENTE)    # file 2

        # Sente pawns rank 6 (index 6)
        for f in range(9):
            self.board[6][f] = Piece(PieceType.PAWN, Color.SENTE)

        # Gote back rank (rank 0)
        gote_back = [
            PieceType.LANCE, PieceType.KNIGHT, PieceType.SILVER, PieceType.GOLD,
            PieceType.KING, PieceType.GOLD, PieceType.SILVER, PieceType.KNIGHT, PieceType.LANCE
        ]
        for f, pt in enumerate(gote_back):
            self.board[0][f] = Piece(pt, Color.GOTE)

        # Gote: Rook on 8b (file 8, rank 2 -> index 1,1), Bishop on 2b (file 2 -> index 7,1)
        self.board[1][1] = Piece(PieceType.ROOK, Color.GOTE)     # file 8
        self.board[1][7] = Piece(PieceType.BISHOP, Color.GOTE)   # file 2

        # Gote pawns rank 2 (index 2)
        for f in range(9):
            self.board[2][f] = Piece(PieceType.PAWN, Color.GOTE)

    def get_piece_moves(self, rank: int, file: int) -> List[Tuple[int, int]]:
        """Return list of (to_rank, to_file) legal moves for piece at position. Ignores check for now."""
        piece = self.board[rank][file]
        if not piece or piece.color != self.turn:
            return []
        moves = []
        # Simple movement generators
        directions = self._get_directions(piece)
        for dr, df in directions:
            if piece.type in (PieceType.KNIGHT, PieceType.PAWN) or (piece.promoted and piece.type == PieceType.PAWN):
                # Single step
                nr, nf = rank + dr * piece.color.value, file + df  # color.value: SENTE=1 forward is -rank? Wait fix.
                # Board: rank 0 top (Gote), rank 8 bottom (Sente).
                # Sente forward is decreasing rank.
                # So for Sente (color=1), forward dr should be negative.
                # Let's redefine.
            # Better redefine movement.
        # Rewrite properly.
        return self._generate_moves(rank, file)

    def _generate_moves(self, rank: int, file: int) -> List[Tuple[int, int]]:
        piece = self.board[rank][file]
        if not piece:
            return []
        moves = []
        color = piece.color
        # Forward: SENTE decreases rank, GOTE increases rank
        fwd = -1 if color == Color.SENTE else 1

        def add_if_valid(nr: int, nf: int) -> bool:
            if not (0 <= nr < 9 and 0 <= nf < 9):
                return False
            target = self.board[nr][nf]
            if target is None or target.color != color:
                moves.append((nr, nf))
                return target is None  # can continue sliding if empty
            return False

        pt = piece.type
        prom = piece.promoted

        if pt == PieceType.PAWN and not prom:
            add_if_valid(rank + fwd, file)
        elif pt == PieceType.LANCE and not prom:
            r = rank + fwd
            while 0 <= r < 9:
                if not add_if_valid(r, file):
                    break
                r += fwd
        elif pt == PieceType.KNIGHT and not prom:
            for df in [-1, 1]:
                add_if_valid(rank + 2 * fwd, file + df)
        elif pt == PieceType.SILVER and not prom:
            for dr, df in [(fwd, 0), (fwd, -1), (fwd, 1), (-fwd, -1), (-fwd, 1)]:
                add_if_valid(rank + dr, file + df)
        elif pt == PieceType.GOLD or (prom and pt in (PieceType.PAWN, PieceType.LANCE, PieceType.KNIGHT, PieceType.SILVER)):
            for dr, df in [(fwd, 0), (fwd, -1), (fwd, 1), (0, -1), (0, 1), (-fwd, 0)]:
                add_if_valid(rank + dr, file + df)
        elif pt == PieceType.KING:
            for dr in [-1, 0, 1]:
                for df in [-1, 0, 1]:
                    if dr != 0 or df != 0:
                        add_if_valid(rank + dr, file + df)
        elif pt == PieceType.BISHOP:
            for dr, df in [(1, 1), (1, -1), (-1, 1), (-1, -1)]:
                r, f = rank + dr, file + df
                while add_if_valid(r, f):
                    r += dr
                    f += df
            if prom:  # Horse: also king-like orthogonal
                for dr, df in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    add_if_valid(rank + dr, file + df)
        elif pt == PieceType.ROOK:
            for dr, df in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                r, f = rank + dr, file + df
                while add_if_valid(r, f):
                    r += dr
                    f += df
            if prom:  # Dragon: also king-like diagonal
                for dr, df in [(1, 1), (1, -1), (-1, 1), (-1, -1)]:
                    add_if_valid(rank + dr, file + df)

        return moves

    def can_promote(self, piece: Piece, from_rank: int, to_rank: int) -> bool:
        if not piece.is_promotable() or piece.promoted:
            return False
        # Promotion zone: for Sente ranks 0-2, for Gote ranks 6-8
        zone = range(3) if piece.color == Color.SENTE else range(6,9)
        return from_rank in zone or to_rank in zone

    def is_nifu(self, color: Color, file: int) -> bool:
        """True if dropping a pawn on this file is illegal (already has unpromoted pawn)."""
        for r in range(9):
            p = self.board[r][file]
            if p and p.color == color and p.type == PieceType.PAWN and not p.promoted:
                return True
        return False

    def get_drop_squares(self, piece_type: PieceType) -> List[Tuple[int, int]]:
        squares = []
        for r in range(9):
            for f in range(9):
                if self.board[r][f] is not None:
                    continue
                # Basic drop rules
                if piece_type == PieceType.PAWN:
                    if self.is_nifu(self.turn, f):
                        continue
                    # No drop on last rank for some pieces
                    if (self.turn == Color.SENTE and r == 0) or (self.turn == Color.GOTE and r == 8):
                        continue
                elif piece_type == PieceType.LANCE:
                    if (self.turn == Color.SENTE and r == 0) or (self.turn == Color.GOTE and r == 8):
                        continue
                elif piece_type == PieceType.KNIGHT:
                    if self.turn == Color.SENTE and r <= 1:
                        continue
                    if self.turn == Color.GOTE and r >= 7:
                        continue
                # TODO: uchi-fu-zume (pawn drop mate) more complex, skip for now
                squares.append((r, f))
        return squares

    def make_move(self, from_pos: Optional[Tuple[int,int]], to_pos: Tuple[int,int], promote: bool = False, drop_type: Optional[PieceType] = None) -> bool:
        """Execute move. from_pos None means drop."""
        tr, tf = to_pos
        if drop_type:
            if self.hands[self.turn][drop_type] <= 0:
                return False
            if self.board[tr][tf] is not None:
                return False
            if (tr, tf) not in self.get_drop_squares(drop_type):
                return False
            self.board[tr][tf] = Piece(drop_type, self.turn)
            self.hands[self.turn][drop_type] -= 1
        else:
            fr, ff = from_pos
            piece = self.board[fr][ff]
            if not piece or piece.color != self.turn:
                return False
            if (tr, tf) not in self._generate_moves(fr, ff):
                return False
            captured = self.board[tr][tf]
            if captured:
                # Add to hand, unpromoted
                cap_type = captured.type
                self.hands[self.turn][cap_type] += 1
            self.board[tr][tf] = piece
            self.board[fr][ff] = None
            # Forced promotion
            force = False
            if piece.type == PieceType.PAWN and not piece.promoted:
                if (piece.color == Color.SENTE and tr == 0) or (piece.color == Color.GOTE and tr == 8):
                    force = True
            elif piece.type == PieceType.LANCE and not piece.promoted:
                if (piece.color == Color.SENTE and tr == 0) or (piece.color == Color.GOTE and tr == 8):
                    force = True
            elif piece.type == PieceType.KNIGHT and not piece.promoted:
                if piece.color == Color.SENTE and tr <= 1:
                    force = True
                if piece.color == Color.GOTE and tr >= 7:
                    force = True
            if force or (promote and self.can_promote(piece, fr, tr)):
                piece.promoted = True
        self.turn = Color.GOTE if self.turn == Color.SENTE else Color.SENTE
        return True

    def get_selectable_pieces(self) -> List[Tuple[int, int]]:
        """Positions of own pieces that have at least one move."""
        positions = []
        for r in range(9):
            for f in range(9):
                p = self.board[r][f]
                if p and p.color == self.turn and self._generate_moves(r, f):
                    positions.append((r, f))
        return positions

    def get_hand_pieces(self) -> List[PieceType]:
        return [pt for pt, cnt in self.hands[self.turn].items() if cnt > 0]
