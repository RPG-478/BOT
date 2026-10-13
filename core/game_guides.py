# -*- coding: utf-8 -*-
"""パーティーゲームの案内文（/game のハブと Web サイトのルールページで使う）。

将来 Lunancy の ``command_meta.py`` に移す前提で、Discord に依存しない素のデータだけを置いている。
"""

DISCORD_DESCRIPTION_LIMIT = 4096

GAME_GUIDES = {
    "jinrou": {
        "id": "jinrou",
        "name": "人狼",
        "category": "game",
        "summary": "村人と人狼に分かれ、昼の話し合いと投票で人狼を探す正体隠しゲーム。",
        "players": "5人以上（おすすめ6〜12人）",
        "min_players": 5,
        "max_players": None,
        "duration": "15〜40分",
        "commands": ["/game"],
        "guide": """## 概要
参加者は「村人陣営」「人狼陣営」「第三者陣営」に分かれます。村人は話し合いと投票で人狼を見つけて追放し、人狼は正体を隠して夜に村人を襲います。

## 人数
5人以上で遊べます。

## コマンド
- `/game`: パーティーゲームの入口
""",
    },
    "wordwolf": {
        "id": "wordwolf",
        "name": "ワードウルフ",
        "category": "game",
        "summary": "1人だけ違うお題を持つ「ウルフ」を、会話から見つけ出すゲーム。",
        "players": "3人以上（おすすめ4〜8人）",
        "min_players": 3,
        "max_players": None,
        "duration": "約6分（募集1分＋本編5分）",
        "commands": ["/game"],
        "guide": """## 概要
全員にお題が配られますが、1人だけ（ウルフ）は少し違うお題を持っています。

## コマンド
- `/game`: パーティーゲームの入口
""",
    },
    "uno": {
        "id": "uno",
        "name": "UNO",
        "category": "game",
        "summary": "同じ色か同じ数字のカードを出していき、先に手札をなくした人が勝ち。",
        "players": "2人以上（おすすめ2〜8人）",
        "min_players": 2,
        "max_players": None,
        "duration": "10〜20分",
        "commands": ["/game"],
        "guide": """## 概要
おなじみのカードゲームです。場のカードと同じ色か同じ数字のカードを出していきます。

## コマンド
- `/game`: パーティーゲームの入口
""",
    },
    "doubt": {
        "id": "doubt",
        "name": "ダウト",
        "category": "game",
        "summary": "決まった数字を宣言してカードを伏せて出す。嘘だと思ったら「ダウト」！",
        "players": "3人以上（おすすめ3〜6人）",
        "min_players": 3,
        "max_players": None,
        "duration": "10〜20分",
        "commands": ["/game", "!doubt"],
        "guide": """## 概要
トランプを配り、決まった数字を宣言しながらカードを伏せて出します。

## コマンド
- `/game`: パーティーゲームの入口
- `!doubt`: ダウトの募集を始める
""",
    },
    "ngword": {
        "id": "ngword",
        "name": "NGワード",
        "category": "game",
        "summary": "自分だけ知らないNGワードを、うっかり言ったら脱落する会話ゲーム。",
        "players": "3〜8人",
        "min_players": 3,
        "max_players": 8,
        "duration": "約4〜11分（募集1分＋本編3・5・10分）",
        "commands": ["/game"],
        "guide": """## 概要
一人ひとりにNGワードが付きます。自分のNGワードだけは分かりません。

## コマンド
- `/game`: パーティーゲームの入口
""",
    },
    "shiritori": {
        "id": "shiritori",
        "name": "お題しりとり",
        "category": "game",
        "summary": "お題（食べ物・動物など）に合う言葉だけでしりとり。つまったら脱落！",
        "players": "3〜8人",
        "min_players": 3,
        "max_players": 8,
        "duration": "約5分（募集1分＋本編）",
        "commands": ["/game"],
        "guide": """## 概要
ランダムに決まるお題に合う言葉だけでしりとりをつなぎます。

## コマンド
- `/game`: パーティーゲームの入口
""",
    },
    "janken": {
        "id": "janken",
        "name": "じゃんけん",
        "category": "game",
        "summary": "みんなで一斉にじゃんけん。最後まで勝ち残った人が優勝！",
        "players": "1〜10人",
        "min_players": 1,
        "max_players": 10,
        "duration": "約1分（募集30秒＋本編）",
        "commands": ["/game"],
        "guide": """## 概要
チャンネルのみんなで一斉にじゃんけんをします。

## コマンド
- `/game`: パーティーゲームの入口
""",
    },
    "othello": {
        "id": "othello", "name": "オセロ", "category": "game",
        "summary": "黒白の石で挟んでひっくり返し、最後に石が多い方が勝ち。",
        "players": "2人", "min_players": 2, "max_players": 2,
        "duration": "約2〜10分（募集30秒）", "commands": ["/game"],
        "guide": """## 概要
黒白の石を盤に置き、相手の石を挟んでひっくり返します。

## コマンド
- `/game`: パーティーゲームの入口
""",
    },
    "poker": {
        "id": "poker", "name": "ポーカー", "category": "game",
        "summary": "5枚ドローポーカー。カードを交換し、最も強い役を作ろう。",
        "players": "2〜6人", "min_players": 2, "max_players": 6,
        "duration": "約2分（募集30秒）", "commands": ["/game"],
        "guide": """## 概要
各自に5枚配られる「5枚ドローポーカー」です。

## コマンド
- `/game`: パーティーゲームの入口
""",
    },
    "shogi": {
        "id": "shogi", "name": "将棋", "category": "game",
        "summary": "日本の将棋。駒を動かして相手の王を詰める2人対戦。Assets/shogi の駒画像を使用。",
        "players": "2人", "min_players": 2, "max_players": 2,
        "duration": "約10〜30分（募集30秒）", "commands": ["/game"],
        "guide": """## 概要
標準の将棋ルールで2人対戦します。駒の画像は Assets/shogi のPNGを使用しています。

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

GAME_ORDER = ["jinrou", "wordwolf", "uno", "doubt", "ngword", "shiritori", "janken", "othello", "poker", "shogi"]


def get_guide(game_id: str) -> dict:
    return GAME_GUIDES[game_id]


def guide_for_discord(game_id: str, limit: int = DISCORD_DESCRIPTION_LIMIT) -> str:
    skip = {"人数", "所要時間", "コマンド"}
    sections, current, title = [], [], None
    for line in GAME_GUIDES[game_id]["guide"].strip().splitlines():
        if line.startswith("## "):
            if title is not None or current:
                sections.append((title, current))
            title, current = line[3:].strip(), []
        else:
            current.append(line)
    sections.append((title, current))

    parts = []
    for title, lines in sections:
        if title in skip:
            continue
        body = "\n".join(lines).strip()
        parts.append(f"**{title}**\n{body}" if title else body)

    more = "\n\n…（続きは各ゲームのヘルプをご覧ください）"
    text = ""
    for part in parts:
        candidate = f"{text}\n\n{part}" if text else part
        if len(candidate) > limit - len(more):
            return (text or part[: limit - len(more)]) + more
        text = candidate
    return text
