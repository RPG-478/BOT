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

# ---------------------------------------------------------------- 国づくりの初回ガイド
# !nation を初めて使った人に出す 3 ステップのチュートリアル（cogs/nation_onboarding.py）。
# 同じ文章を /help と Web サイトのガイド（NATION_GUIDE）でも使う。
NATION_TUTORIAL = [
    {
        "title": "1. 国に入る・国をつくる",
        "body": (
            "国づくりは、サーバーごとに 1 つの国を育てる遊びです。\n"
            "- このサーバーに国があれば、参加機能から国民になれます（入れるのは 1 人 1 か国）。\n"
            "- まだ国がなければ、サーバーの管理者かオーナーが建国できます。"
            "建国した人が国王になり、首都が共有マップに置かれます。"
        ),
    },
    {
        "title": "2. 空腹度とコイン",
        "body": (
            "- **空腹度**: 参加したときは 100 です。これから時間とともに減っていくしくみが入る予定です。\n"
            "- **コイン（AGO）**: 所持金は `/wallet` と共通です。ほかのゲームで稼いだコインも国づくりで使えます。\n"
            "所属国・役職・所持金・空腹度は、状態確認機能で確認できます。"
        ),
    },
    {
        "title": "3. まずやること",
        "body": (
            "1. 国民参加または建国の機能を使う\n"
            "2. 状態確認機能で自分の情報を見る\n"
            "3. Web サイトの共有マップで、自分の国の場所と広さを見てみる\n"
            "操作方法はサーバー管理者に確認してください。"
        ),
    },
]

NATION_GUIDE = "\n\n".join(f"## {step['title']}\n{step['body']}" for step in NATION_TUTORIAL)


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
            "グローバルチャットは、設定済みチャンネルの発言がほかのサーバーの接続先へ届きます。部屋を分けたいときは `!gvc` のルームを使います。"
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
            "`/game` の「数字当て」は 1〜3 の数字を当てるゲームです。当たると賭け額の 2.8 倍がもらえ、外れると 1.5 倍が引かれます。"
            "負けても残高がマイナスにならない額までしか賭けられません。"
        ),
    },
    {
        "id": "game",
        "label": "パーティーゲーム",
        "description": "人狼・ワードウルフ・UNO・ダウト・NGワード・お題しりとり・じゃんけん・Wordle・神経衰弱・ババ抜き・大富豪など、チャンネルのみんなで遊べるゲームです。",
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
            "録音・やまびこ・文字起こし・カラオケは `/voice studio`、ボイスチェンジャーは `/voice effects`、"
            "ランダム通話・グローバルVCは `/voice community` から操作できます。\n\n"
            "## 注意\n"
            "音楽と `/voice` の機能は、どれも Bot の接続を 1 つ使います。ほかの機能が使用中のときは断られるので、"
            "`/voice connection action:状態` で何が使っているかを確かめ、終わってから（または `/voice connection action:退出` してから）実行してください。"
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
        "description": "認証パネル、メッセージの一括削除、ミュートなど、管理者向けの機能です。多くは管理用の権限が必要です。",
        "guide": (
            "## はじめに\n"
            "サーバー設定ウィザード（`/setup`）は廃止されました。認証・グローバルチャット等は、既存の設定がある場合に限り引き続き動作します。"
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
    "/whisper": {"category": "support"},
    "/fujo": {"category": "support", "summary": "生存確認・ステータス・ランキング・失踪警報をまとめて操作します"},
    "/giveaway": {"category": "support", "permissions": ["manage_guild"], "guild_only": True},
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
    "!nation": {"category": "economy", "summary": "国づくり機能", "guild_only": True, "hidden": True},
    "!nation join": {"category": "economy", "guide": NATION_GUIDE, "guild_only": True,
                      "summary": "このサーバーの国に国民として参加します", "hidden": True},
    "!nation found": {"category": "economy", "guide": NATION_GUIDE, "guild_only": True,
                       "summary": "このサーバーの国を建国します（管理者かオーナーのみ）",
                       "permissions": ["administrator"], "hidden": True},
    "!nation status": {"category": "economy", "guide": NATION_GUIDE, "guild_only": True,
                       "summary": "所属国・役職・所持金・空腹度を表示します", "hidden": True},
    "!coin": {"category": "economy", "summary": "管理者が自分の残高を直接設定します", "permissions": ["bot_admin"],
              "hidden": True},

    # ---------------------------------------------------------------- パーティーゲーム
    "/game": {"category": "game"},
    "!doubt": {"category": "game", "summary": "ダウトの参加者を募集して始めます（3人以上）", "guild_only": True,
               "guide_key": "doubt"},

    # ---------------------------------------------------------------- ボイス・音楽
    "/music play": {"category": "voice", "usage": "/music play query:<URL・検索語・ID> [file:<音声ファイル>] [start_at:<秒>]"},
    "/music control": {"category": "voice", "usage": "/music control action:<操作> [seconds:<秒>] [loop_mode:<種類>]"},
    "/music sound": {"category": "voice", "usage": "/music sound action:<音量|速度|EQ|立体音響> [value|preset|feedback|wet|resolution]"},
    "/music library": {"category": "voice", "usage": "/music library action:<検索|プレイリスト|音声ID> [query|playlist_action|name|scope|file|limit]"},
    "/music panel": {"category": "voice", "usage": "/music panel"},
    "/bumprta": {"category": "voice", "usage": "/bumprta action:<状態|通知オン|通知オフ|ランキング> [event_type:<bump|up>] [scope:<自己ベスト|サーバー内|全体>]"},
    "/voice connection": {"category": "voice", "usage": "/voice connection action:<参加|退出|状態>"},
    "/voice studio": {"category": "voice", "usage": "/voice studio feature:<録音|やまびこ|文字起こし|カラオケ> action:<操作> [delay|channel|lyrics]"},
    "/voice effects": {"category": "voice", "usage": "/voice effects action:<開始|停止|状態/設定変更> [pitch|buffer_ms|max_ms]"},
    "/voice community": {"category": "voice", "usage": "/voice community network:<ランダム通話|グローバルVC> action:<開始/参加|終了/退出> [room|password]"},
    "!ffversion": {"category": "voice", "hidden": True},

    # ---------------------------------------------------------------- おたのしみ・AI
    "/zetamodoki": {"category": "fun"},
    "/zeta_reset": {"category": "fun"},
    "/dungeon": {"category": "fun"},
    "/judge": {"category": "fun"},
    "!mimic": {"category": "fun", "summary": "過去の発言をもとに、特定のメンバーの口調で AI が返事をします",
               "options": {"prompt": "話しかける内容"}},
    "!mood": {"category": "fun", "summary": "このチャンネルの直近3週間の雰囲気を AI が分析します"},
    "!ggrks": {"category": "fun", "options": {"keyword": "検索する言葉"}},

    # ---------------------------------------------------------------- サーバー管理
    "/clear": {"category": "admin", "permissions": ["manage_messages"]},
    "/muted": {"category": "admin"},
    "!dungeon_reset": {"category": "admin", "summary": "ダンジョンのマップを全サーバー分リセットします", "permissions": ["bot_admin"],
                       "hidden": True},
    "!mimic_toggle": {"category": "admin", "summary": "このチャンネルでの !mimic の自動返信を切り替えます"},
    "!check_api": {"category": "admin", "summary": "入っているライブラリの一覧を表示します", "permissions": ["bot_admin"],
                   "hidden": True},
    "!d1ping": {"category": "admin", "summary": "d1 サーバーの応答を確かめ、止まっていれば起動します",
                "permissions": ["bot_admin"], "hidden": True},
    "!all_stats": {"category": "admin", "summary": "Bot とサーバーの状態を表示します", "hidden": True},
    "!terminal": {"category": "admin", "summary": "持ち主専用の操作パネルを表示します", "permissions": ["bot_admin"],
                  "hidden": True},
    "!guild": {"category": "admin", "summary": "Bot が入っているサーバーの一覧を表示します", "permissions": ["bot_admin"],
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
