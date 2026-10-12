"""コマンドカタログ（core/command_catalog.py）に合わせる、人が決める情報。

コマンドを追加したら、COMMAND_META に "/名前"（スラッシュ）か "!名前"（プレフィックス）の
キーで 1 行足してください。足し忘れると tests/test_command_catalog.py が知らせます。

各項目で使えるキー（category 以外は省略できる）
- category: CATEGORIES の id
- summary: 一覧に出す 1 行の説明（コマンドの description が空・分かりにくいときに上書き）
- usage: 使い方の例（省略すると引数から自動で作る）
- options: {"引数名": "説明"}（プレフィックスコマンドの引数には説明が付いていないので、ここで補う）
- permissions: 自動で読み取れない権限（コマンドの中で確かめている場合など）
- hidden: True にすると /help や Web の一覧に出さない（デバッグ用・持ち主専用など）
- guide: 詳しい説明（Markdown）
- guide_key: core/game_guides.py の GAME_GUIDES のキー。そのゲームのルール説明を guide として使う
"""

from __future__ import annotations

CATEGORIES = [
    {
        "id": "support",
        "label": "サポート",
        "description": "ヘルプ、サーバーをまたぐグローバルチャット、匿名のつぶやき、生存確認など、サーバー生活を便利にする機能です。",
        "guide": (
            "## はじめに\n"
            "`/help` でカテゴリごとのコマンド一覧を見られます。`/help command:` にコマンド名を入れると、"
            "そのコマンドの使い方だけを表示します。\n\n"
            "## グローバルチャット\n"
            "`/chat` を実行したチャンネルの発言が、同じく `/chat` をオンにしたほかのサーバーのチャンネルへ届きます"
            "（実行には「チャンネルの管理」権限が必要です）。部屋を分けたいときは `!gvc` のルームを使います。"
        ),
    },
    {
        "id": "economy",
        "label": "コイン",
        "description": "サーバー共通のコイン（AGO）の残高確認・送金・ランキングと、コインを賭けるミニゲームです。",
        "guide": (
            "## コインのしくみ\n"
            "はじめて `/wallet` を使うと 10 AGO もらえます。`/pay` でほかの人に送金でき、"
            "`/leaderboard` で保有ランキングを見られます。\n\n"
            "## 数字当て\n"
            "`/guess` は 1〜3 の数字を当てるゲームです。当たると賭け額の 2.8 倍がもらえ、外れると 1.5 倍が引かれます。"
            "負けても残高がマイナスにならない額までしか賭けられません。"
        ),
    },
    {
        "id": "game",
        "label": "パーティーゲーム",
        "description": "人狼・ワードウルフ・UNO・ダウトなど、チャンネルのみんなで遊べるゲームです。",
        "guide": (
            "## 遊び方\n"
            "それぞれのゲームのコマンドを実行すると参加者の募集が始まり、ボタンで参加できます。"
            "ルールは各コマンドの「ガイド」で確認できます。\n\n"
            "## 人数の目安\n"
            "人狼は 5 人以上、ワードウルフとダウトは 3 人以上、UNO は 2 人以上で遊べます。"
        ),
    },
    {
        "id": "voice",
        "label": "ボイス・音楽",
        "description": "ボイスチャンネルでの音楽再生（`/music`）と、録音・文字起こし・ボイスチェンジャー・他サーバーとの通話など（`/voice`）です。",
        "guide": (
            "## はじめに\n"
            "先に自分がボイスチャンネルに入ってから実行してください。音楽は `/music play` に URL・検索語・音声ファイルを渡すと"
            "Bot が VC に入って再生します。`/music panel` の操作パネルからまとめて操作できます。"
            "録音・やまびこ・文字起こし・カラオケ・ボイスチェンジャー・ランダム通話・グローバルVC は `/voice` の各サブコマンドで、"
            "`action` で開始・停止などを選びます。\n\n"
            "## 注意\n"
            "音楽と `/voice` の機能は、どれも Bot の接続を 1 つ使います。ほかの機能が使用中のときは断られるので、"
            "`/voice status` で何が使っているかを確かめ、終わってから（または `/voice leave` してから）実行してください。"
            "録音を始めると、チャンネルに「録音を開始しました」と表示されます。"
            "誰もいない状態が 3 分続くと Bot は自動で退出します。"
        ),
    },
    {
        "id": "fun",
        "label": "おたのしみ・AI",
        "description": "画像生成、AI との会話、チャンネルの雰囲気分析、検索リンク、暗算・ダンジョンなどのひとりで遊べる機能です。",
        "guide": None,
    },
    {
        "id": "admin",
        "label": "サーバー管理",
        "description": "初期設定（/setup）、認証パネル、メッセージの一括削除、ミュートなど、管理者向けの機能です。多くは管理用の権限が必要です。",
        "guide": (
            "## はじめに\n"
            "Bot を入れたら、まず `/setup` を実行してください（「サーバー管理」権限が必要です）。"
            "認証・グローバルチャットの設定と、Bot に足りない権限の確認が 1 か所でできます。"
        ),
    },
]

CATEGORY_IDS = tuple(c["id"] for c in CATEGORIES)

# このキーのコマンドは、環境によっては読み込まれない（無くてもテストで失敗にしない）
OPTIONAL_COMMANDS = {
    "/judge": "needle3 が入っている環境（ラズパイ）でだけ読み込まれる",
    "/game": "パーティーゲームの入口。PR #34 で追加予定",
}

COMMAND_META: dict[str, dict] = {
    # ---------------------------------------------------------------- サポート
    "/help": {"category": "support"},
    "!help": {
        "category": "support",
        "summary": "コマンドの一覧と使い方を表示します（詳しくは /help）",
        "options": {"command": "使い方を見たいコマンド名"},
    },
    "/chat": {"category": "support", "permissions": ["manage_channels"]},
    "/whisper": {"category": "support"},
    "/fujo register": {"category": "support"},
    "/fujo status": {"category": "support"},
    "/fujo hindo": {"category": "support"},
    "/fujo ranking": {"category": "support"},
    "/fujo freeze": {"category": "support"},
    "/fujo panic set": {"category": "support"},
    "/fujo panic disable": {"category": "support"},
    "!gvc": {"category": "support", "summary": "グローバルVC（サーバーをまたぐ通話・チャットのルーム）のコマンド一覧を表示します"},
    "!gvc create": {
        "category": "support",
        "summary": "グローバルVCのルームを作成します",
        "usage": "!gvc create <ルーム名> [--max 5] [--private] [--password 合言葉] [--desc 説明]",
        "options": {"room_name": "ルーム名（スペースを含むときは \"\" で囲む）",
                    "options": "--max 最大サーバー数 / --private 非公開 / --password 合言葉 / --desc 説明"},
        "guild_only": True,
    },
    "!gvc list": {"category": "support", "summary": "ルームの一覧を表示します"},
    "!gvc info": {"category": "support", "summary": "ルームの詳細を表示します", "options": {"room_name": "ルーム名"}},
    "!gvc delete": {
        "category": "support",
        "summary": "ルームを削除します（作成者か、作成したサーバーの管理者のみ）",
        "options": {"room_name": "ルーム名"},
    },
    "!gvc chat": {"category": "support", "summary": "グローバルVCのテキストチャット連携のコマンド一覧を表示します"},
    "!gvc chat connect": {
        "category": "support",
        "summary": "このチャンネルをルームのチャットにつなぎます",
        "options": {"room_name": "ルーム名", "password": "非公開ルームの合言葉"},
    },
    "!gvc chat disconnect": {"category": "support", "summary": "このチャンネルのチャット連携を解除します"},

    # ---------------------------------------------------------------- コイン
    "/wallet": {"category": "economy"},
    "/pay": {"category": "economy"},
    "/leaderboard": {"category": "economy"},
    "/guess": {"category": "economy"},
    "!coin": {"category": "economy", "summary": "管理者が自分の残高を直接設定します", "permissions": ["bot_admin"],
              "hidden": True},

    # ---------------------------------------------------------------- パーティーゲーム
    "/game": {"category": "game"},
    "/jinrou": {"category": "game", "guide_key": "jinrou"},
    "/jinrou_help": {"category": "game"},
    "/jinrou_rating": {"category": "game"},
    "/jinrou_ranking": {"category": "game"},
    "/kill": {"category": "game"},
    "/wordwolf": {"category": "game", "guide_key": "wordwolf"},
    "/uno_start": {"category": "game", "guide_key": "uno"},
    "/uno_end": {"category": "game"},
    "!doubt": {"category": "game", "summary": "ダウトの参加者を募集して始めます（3人以上）", "guild_only": True,
               "guide_key": "doubt"},

    # ---------------------------------------------------------------- ボイス・音楽
    "/music play": {"category": "voice", "usage": "/music play query:<URL・検索語・ID> [file:<音声ファイル>] [start_at:<秒>]"},
    "/music pause": {"category": "voice", "usage": "/music pause"},
    "/music skip": {"category": "voice", "usage": "/music skip"},
    "/music stop": {"category": "voice", "usage": "/music stop"},
    "/music seek": {"category": "voice", "usage": "/music seek seconds:<秒>"},
    "/music queue": {"category": "voice", "usage": "/music queue"},
    "/music loop": {"category": "voice", "usage": "/music loop mode:<OFF / 1曲 / キュー全体>"},
    "/music shuffle": {"category": "voice", "usage": "/music shuffle"},
    "/music volume": {"category": "voice", "usage": "/music volume value:<0.1〜2.0>"},
    "/music speed": {"category": "voice", "usage": "/music speed value:<0.5〜64>"},
    "/music eq": {"category": "voice", "usage": "/music eq mode:<プリセット または FFmpeg フィルター>"},
    "/music spatial": {"category": "voice",
                       "usage": "/music spatial [feedback:<0.0〜0.95>] [wet:<0.0〜1.0>] [resolution:<4 / 8>]"},
    "/music panel": {"category": "voice", "usage": "/music panel"},
    "/music search": {"category": "voice", "usage": "/music search keyword:<検索する言葉>"},
    "/music playlist": {"category": "voice",
                        "usage": "/music playlist action:<保存 / 一覧 / 再生> [name:<名前>] [scope:<自分 / サーバー>] [file:<JSON>]"},
    "/music files": {"category": "voice", "usage": "/music files [limit:<1〜100>]"},
    "/voice join": {"category": "voice", "usage": "/voice join"},
    "/voice leave": {"category": "voice", "usage": "/voice leave"},
    "/voice status": {"category": "voice", "usage": "/voice status"},
    "/voice record": {"category": "voice", "usage": "/voice record action:<開始|停止|状態|音程解析>"},
    "/voice echo": {"category": "voice", "usage": "/voice echo action:<開始|遅延変更|停止> [delay:<秒>]"},
    "/voice transcribe": {"category": "voice", "usage": "/voice transcribe action:<開始|停止> [channel:<送り先>]"},
    "/voice karaoke": {"category": "voice", "usage": "/voice karaoke action:<開始|採点|終了> [lyrics:<お題の歌詞>]"},
    "/voice changer": {
        "category": "voice",
        "usage": "/voice changer action:<開始|停止|状態> [pitch:<半音>] [buffer_ms:<ms>] [max_ms:<ms>]",
    },
    "/voice match": {"category": "voice", "usage": "/voice match action:<開始|終了>"},
    "/voice global": {"category": "voice", "usage": "/voice global action:<参加|退出> [room:<ルーム名>] [password:<合言葉>]"},
    "!ffversion": {"category": "voice", "hidden": True},

    # ---------------------------------------------------------------- おたのしみ・AI
    "/zetamodoki": {"category": "fun"},
    "/zeta_reset": {"category": "fun"},
    "/flash": {"category": "fun"},
    "/dungeon": {"category": "fun"},
    "/judge": {"category": "fun"},
    "!mimic": {"category": "fun", "summary": "過去の発言をもとに、特定のメンバーの口調で AI が返事をします",
               "options": {"prompt": "話しかける内容"}},
    "!mood": {"category": "fun", "summary": "このチャンネルの直近3週間の雰囲気を AI が分析します"},
    "!ggrks": {"category": "fun", "options": {"keyword": "検索する言葉"}},

    # ---------------------------------------------------------------- サーバー管理
    "/setup": {
        "category": "admin",
        "summary": "このサーバーでの Bot の初期設定（認証・グローバルチャット・権限の確認）をします",
        "usage": "/setup",
        "permissions": ["manage_guild"],
        "guide": (
            "## 使い方\n"
            "`/setup` を実行すると、自分にだけ見える設定画面が開きます。ステップごとにメニューやボタンで設定し、"
            "選んだ内容はすぐ保存されます。使わない機能は「次へ（スキップ）」で飛ばせます。"
            "もう一度実行すると、今の設定が表示されます。\n\n"
            "## ステップ\n"
            "1. 認証: 付けるロール、自己紹介チャンネル、フォームの有効/停止。このチャンネルに認証パネルも送れます\n"
            "2. グローバルチャット: このチャンネルをつなぐ / 外す\n"
            "3. ミュート管理ロール（対応している場合）\n"
            "4. まとめ: 設定内容と、機能ごとに Bot に足りない権限の一覧"
        ),
    },
    "/send_panel": {"category": "admin"},
    "/sync_category_perms": {"category": "admin"},
    "/clear": {"category": "admin", "permissions": ["manage_messages"]},
    "/muted": {"category": "admin"},
    "/dungeon_reset": {"category": "admin"},
    "!mimic_toggle": {"category": "admin", "summary": "このチャンネルでの !mimic の自動返信を切り替えます"},
    "/check_api": {"category": "admin", "hidden": True},
    "/d1ping": {"category": "admin", "hidden": True},
    "!all_stats": {"category": "admin", "summary": "Bot とサーバーの状態を表示します", "hidden": True},
    "!terminal": {"category": "admin", "summary": "持ち主専用の操作パネルを表示します", "permissions": ["bot_admin"],
                  "hidden": True},
}


def game_guides() -> dict:
    """core/game_guides.py があれば、そのルール説明を返す（無い環境では空）。"""
    try:
        from core import game_guides as module
    except ImportError:
        return {}
    return getattr(module, "GAME_GUIDES", {}) or {}


def resolve_guide(meta: dict) -> str | None:
    """guide（直接書いたもの）か guide_key（core/game_guides.py の項目）からガイドを返す。"""
    if meta.get("guide"):
        return meta["guide"]
    key = meta.get("guide_key")
    if key:
        guide = (game_guides().get(key) or {}).get("guide")
        if guide:
            return guide
    return None
