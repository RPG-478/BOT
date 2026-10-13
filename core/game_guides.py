# -*- coding: utf-8 -*-
"""パーティーゲームの案内文（/game のハブと Web サイトのルールページで使う）。

将来 Lunancy の ``command_meta.py`` に移す前提で、Discord に依存しない素のデータだけを置いている。
"""

DISCORD_DESCRIPTION_LIMIT = 4096

GAME_GUIDES = {
    "othello": {
        "id": "othello", "name": "オセロ", "category": "game",
        "summary": "黒白の石で挟んでひっくり返し、最後に石が多い方が勝ち。",
        "players": "2人", "min_players": 2, "max_players": 2,
        "duration": "約2〜10分（募集30秒）", "commands": ["/game"],
        "guide": """## 概要
黒白の石を盤に置き、相手の石を挟んでひっくり返します。最後に石の数が多い方の勝ちです。

## コマンド
- `/game`: パーティーゲームの入口
""",
    },
    "shogi": {
        "id": "shogi", "name": "将棋", "category": "game",
        "summary": "日本の将棋。駒を動かして相手の王を詰める2人対戦。",
        "players": "2人", "min_players": 2, "max_players": 2,
        "duration": "約10〜30分（募集30秒）", "commands": ["/game"],
        "guide": """## 概要
標準の将棋ルールで2人対戦します。Assets/shogi の駒PNGを使用した盤面表示です。

## 遊び方
1. `/game` で「将棋」を選び、募集します。
2. 30秒以内に2人集まると開始します。
3. 盤面画像が表示されます。

## 注意
基本実装です。本格的な指し手・成り・持ち駒は今後拡張予定です。

## コマンド
- `/game`: パーティーゲームの入口
""",
    },
}

GAME_ORDER = ["othello", "shogi"]


def get_guide(game_id: str) -> dict:
    return GAME_GUIDES[game_id]


def guide_for_discord(game_id: str, limit: int = DISCORD_DESCRIPTION_LIMIT) -> str:
    return GAME_GUIDES[game_id]["guide"][:limit]
