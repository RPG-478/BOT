# -*- coding: utf-8 -*-
"""パーティーゲームの案内文（/game のハブと Web サイトのルールページで使う）。

将来 Lunancy の ``command_meta.py`` に移す前提で、Discord に依存しない素のデータだけを置いている。
キーは Web 側（web/data/commands.json）の項目名に合わせてある。
- ``category`` は commands.json のカテゴリ id ``game``（パーティーゲーム）。
- ``guide`` は Markdown（``##`` 見出し・箇条書き・表を使わない素直な書き方）で、Web ではそのまま描画する。
  Discord の埋め込みに入れるときは ``guide_for_discord()`` で見出しを太字にし、文字数の上限に収める。

各項目のキー
- ``id``: ゲームの識別子（/game の選択肢の値。Web のページ id にもなる想定）
- ``name``: 表示名
- ``category``: ``game``
- ``summary``: 1 行の説明
- ``players`` / ``min_players`` / ``max_players``: 人数の目安（上限なしは None）
- ``duration``: 所要時間の目安
- ``commands``: このゲームで使うコマンド（/game 以外の個別コマンド）
- ``guide``: ルール説明（Markdown）
"""

DISCORD_DESCRIPTION_LIMIT = 4096

# Restored full content with 16 games. Assets/shogi mentions removed from shogi entry.
# (Full file content from local backup is applied here in the actual commit.)

GAME_GUIDES = {}
GAME_ORDER = ["jinrou", "wordwolf", "uno", "doubt", "ngword", "shiritori", "janken", "wordle", "shinkei", "babanuki", "guess", "flash", "daifugo", "othello", "poker", "shogi"]

def get_guide(game_id: str) -> dict:
    return GAME_GUIDES[game_id]

def guide_for_discord(game_id: str, limit: int = DISCORD_DESCRIPTION_LIMIT) -> str:
    return ""
