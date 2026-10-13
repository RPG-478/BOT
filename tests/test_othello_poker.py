"""オセロ・ポーカーの基本ルールテスト。"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import game_fakes  # noqa: F401
from cogs.othello import (
    BLACK, WHITE, Othello, OthelloGame, labelled_moves, legal_moves, new_board, play_move,
    reaction_emoji, render_board_image,
)
from cogs.poker import evaluate
from PIL import Image, ImageChops


class OthelloTest(unittest.TestCase):
    def test_initial_moves_and_flip(self):
        board = new_board()
        moves = legal_moves(board, BLACK)
        self.assertEqual(len(moves), 4)
        self.assertTrue(play_move(board, BLACK, 2, 3))
        self.assertEqual(board[3][3], BLACK)
        self.assertEqual(board[2][3], BLACK)
        self.assertEqual(len(legal_moves(board, WHITE)), 3)

    def test_reject_illegal_move(self):
        self.assertFalse(play_move(new_board(), BLACK, 0, 0))

    def test_move_labels_and_reaction_mapping(self):
        moves = legal_moves(new_board(), BLACK)
        self.assertEqual(labelled_moves(moves), list(zip("1234", moves)))
        self.assertEqual(reaction_emoji("1"), "1️⃣")
        self.assertEqual(reaction_emoji("A"), "🇦")
        self.assertEqual(reaction_emoji("Z"), "🇿")

    def test_legal_moves_are_drawn_on_board(self):
        board = new_board()
        move = legal_moves(board, BLACK)[0]
        plain = Image.open(render_board_image(board)).convert("RGBA")
        labelled = Image.open(render_board_image(board, [move])).convert("RGBA")
        self.assertEqual(labelled.size, (800, 800))
        self.assertIsNotNone(ImageChops.difference(plain, labelled).getbbox())


class OthelloReactionTest(unittest.IsolatedAsyncioTestCase):
    async def test_reaction_places_the_corresponding_legal_move(self):
        game = OthelloGame(1, 1, 1)
        black = SimpleNamespace(id=1, mention="<@1>", bot=False)
        white = SimpleNamespace(id=2, mention="<@2>", bot=False)
        game.players = {BLACK: black, WHITE: white}
        game.phase = "playing"
        moves = legal_moves(game.board, BLACK)

        class Message:
            id = 99

            async def remove_reaction(self, emoji, user):
                pass

        message = Message()
        cog = Othello(None)
        cog.reaction_sessions[message.id] = {
            "game": game, "moves": moves, "offset": 0, "active": [], "description": "turn"
        }
        reaction = SimpleNamespace(message=message, emoji=reaction_emoji("1"))
        await cog.on_reaction_add(reaction, black)

        self.assertTrue(game.acted)
        self.assertEqual(game.board[moves[0][0]][moves[0][1]], BLACK)

    async def test_other_players_reaction_does_not_place_a_piece(self):
        game = OthelloGame(1, 1, 1)
        black = SimpleNamespace(id=1, mention="<@1>", bot=False)
        white = SimpleNamespace(id=2, mention="<@2>", bot=False)
        game.players = {BLACK: black, WHITE: white}
        game.phase = "playing"
        moves = legal_moves(game.board, BLACK)

        class Message:
            id = 100

            async def remove_reaction(self, emoji, user):
                pass

        message = Message()
        cog = Othello(None)
        cog.reaction_sessions[message.id] = {
            "game": game, "moves": moves, "offset": 0, "active": [], "description": "turn"
        }
        reaction = SimpleNamespace(message=message, emoji=reaction_emoji("1"))
        await cog.on_reaction_add(reaction, white)

        self.assertFalse(game.acted)
        self.assertEqual(game.board, new_board())


class PokerTest(unittest.TestCase):
    def test_hand_rank_order(self):
        hands = [
            ["2♠", "3♥", "4♦", "5♣", "6♠"],
            ["A♠", "A♥", "A♦", "A♣", "2♠"],
            ["2♠", "2♥", "2♦", "3♣", "3♠"],
        ]
        ranked = [evaluate(hand)[0] for hand in hands]
        self.assertGreater(ranked[1], ranked[2])
        self.assertGreater(ranked[2], ranked[0])

    def test_wheel_straight_flush(self):
        score, name = evaluate(["A♠", "2♠", "3♠", "4♠", "5♠"])
        self.assertEqual(name, "ストレートフラッシュ")
        self.assertEqual(score, (8, 5))


if __name__ == "__main__":
    unittest.main()
