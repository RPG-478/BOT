# -*- coding: utf-8 -*-
"""パーティーゲームの案内文。"""

DISCORD_DESCRIPTION_LIMIT = 4096

GAME_GUIDES = {
    "jinrou": {"id": "jinrou", "name": "人狼", "category": "game", "summary": "人狼ゲーム", "players": "5人以上", "min_players": 5, "max_players": None, "duration": "15〜40分", "commands": ["/game"], "guide": "## 概要\n人狼"},
    "shogi": {"id": "shogi", "name": "将棋", "category": "game", "summary": "日本の将棋。駒を動かして相手の王を詰める2人対戦。", "players": "2人", "min_players": 2, "max_players": 2, "duration": "約10〜30分", "commands": ["/game"], "guide": "## 概要\n標準の将棋ルールで2人対戦します。"},
}

GAME_ORDER = ["jinrou", "shogi"]

def get_guide(game_id: str) -> dict:
    return GAME_GUIDES[game_id]

def guide_for_discord(game_id: str, limit: int = DISCORD_DESCRIPTION_LIMIT) -> str:
    return GAME_GUIDES.get(game_id, {}).get("guide", "")
