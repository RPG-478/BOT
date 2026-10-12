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
        "description": "ボイスチャンネルでの音楽再生、読み上げ、録音、文字起こし、ボイスチェンジャー、他サーバーとの通話などです。",
        "guide": (
            "## はじめに\n"
            "先に自分がボイスチャンネルに入ってから実行してください。音楽は `/play` に URL・検索語・音声ファイルを渡すと再生され、"
            "`/music` の操作パネルからまとめて操作できます。\n\n"
            "## 注意\n"
            "録音（`!rec`）・文字起こし（`!stt`）・ボイスチェンジャー（`!vc`）・カラオケ（`!karaoke`）・グローバルVC（`!gvc join`）は、"
            "どれも Bot の接続を 1 つ使います。別の機能を始めると、今の接続はいったん切れます。"
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
        "guide": None,
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
    "!gvc join": {
        "category": "support",
        "summary": "今いるボイスチャンネルをルームにつなぎます",
        "options": {"room_name": "参加するルーム名", "password": "非公開ルームの合言葉"},
    },
    "!gvc leave": {"category": "support", "summary": "グローバルVCから切断します（ルームは残ります）"},
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
    "/join": {"category": "voice"},
    "/leave": {"category": "voice"},
    "/play": {"category": "voice"},
    "/pause": {"category": "voice"},
    "/skip": {"category": "voice"},
    "/seek": {"category": "voice"},
    "/loop": {"category": "voice"},
    "/shuffle": {"category": "voice"},
    "/queue": {"category": "voice"},
    "/music": {"category": "voice"},
    "/playlist": {"category": "voice"},
    "/eq": {"category": "voice"},
    "/spatial": {"category": "voice"},
    "/speak": {"category": "voice", "hidden": True},  # VOICEVOX が無い環境なので使えない
    "/spotify_link": {"category": "voice", "hidden": True},
    "/spotify_unlink": {"category": "voice", "hidden": True},
    "/spotify_playlists": {"category": "voice", "hidden": True},
    "!panel": {"category": "voice"},
    "!search": {"category": "voice", "options": {"keyword": "検索する言葉"}},
    "!list": {"category": "voice", "options": {"limit": "表示する件数"}},
    "!plist": {"category": "voice", "options": {"input_data": "プレイリストの JSON"}},
    "!save_current": {"category": "voice", "options": {"name": "保存名"}},
    "!plsave": {"category": "voice", "options": {"name": "プレイリスト名"}},
    "!pllist": {"category": "voice"},
    "!plplay": {"category": "voice", "options": {"name": "プレイリスト名"}},
    "!volume": {"category": "voice", "options": {"vol": "音量（1.0 で 100%）"}},
    "!speed": {"category": "voice", "options": {"speed": "再生速度（1.0 で等速）"}},
    "!stop_all": {"category": "voice"},
    "!rval": {"category": "voice", "summary": "リバーブ（残響）の長さと量を調整します",
              "options": {"feedback": "残響の長さ（0.0〜0.95）", "wet": "残響の量（0.0〜1.0）"}},
    "!rres": {"category": "voice", "summary": "リバーブの細かさ（4 か 8）を切り替えます",
              "options": {"res": "4 または 8"}},
    "!ffversion": {"category": "voice", "hidden": True},
    "!rec": {"category": "voice", "summary": "録音の状況を表示します"},
    "!rec start": {"category": "voice", "summary": "ボイスチャンネルの録音を始めます"},
    "!rec stop": {"category": "voice", "summary": "録音を止めて、音声ファイルを送ります"},
    "!rec status": {"category": "voice", "summary": "録音の状況を表示します"},
    "!rec pitch": {"category": "voice", "summary": "直近の声の音程（ピアノの音階）を解析します"},
    "!echo": {"category": "voice", "summary": "やまびこ（エコー）の状態を表示します"},
    "!echo start": {"category": "voice", "summary": "声が遅れて返ってくる、やまびこを始めます",
                    "options": {"delay": "遅れる秒数"}},
    "!echo delay": {"category": "voice", "summary": "やまびこの遅れる秒数を変えます", "options": {"delay": "秒数"}},
    "!echo stop": {"category": "voice", "summary": "やまびこを止めます"},
    "!stt": {"category": "voice", "summary": "文字起こしのコマンド一覧を表示します"},
    "!stt start": {"category": "voice", "summary": "ボイスチャンネルの会話の文字起こしを始めます",
                   "options": {"target_channel": "文字起こしを書き込むチャンネル（省略するとこのチャンネル）"}},
    "!stt stop": {"category": "voice", "summary": "文字起こしを止めます"},
    "!karaoke": {"category": "voice", "summary": "カラオケ採点のコマンド一覧を表示します"},
    "!karaoke start": {"category": "voice", "summary": "歌詞を指定してカラオケ採点を始めます",
                       "options": {"target_lyrics": "歌う歌詞"}},
    "!karaoke score": {"category": "voice", "summary": "今の採点結果を表示します"},
    "!karaoke stop": {"category": "voice", "summary": "カラオケ採点を終わります"},
    "!vc": {"category": "voice", "summary": "ボイスチェンジャーのコマンド一覧を表示します"},
    "!vc start": {"category": "voice", "summary": "ボイスチェンジャーを始めます", "options": {"pitch": "音の高さ（半音単位）"}},
    "!vc pitch": {"category": "voice", "summary": "ボイスチェンジャーの音の高さを変えます",
                  "options": {"semitones": "半音単位の高さ（例: 3、-2）"}},
    "!vc buffer": {"category": "voice", "summary": "ボイスチェンジャーの遅延（バッファ）を調整します",
                   "options": {"target_ms": "目標の遅延（ミリ秒）", "max_ms": "最大の遅延（ミリ秒）"}},
    "!vc stop": {"category": "voice", "summary": "ボイスチェンジャーを止めます"},
    "!saito": {"category": "voice", "summary": "別のサーバーのボイスチャンネルとランダムにつないで通話します"},
    "!saito_stop": {"category": "voice", "summary": "!saito の通話を終了します"},

    # ---------------------------------------------------------------- おたのしみ・AI
    "/generate": {"category": "fun"},
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
