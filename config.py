# -*- coding: utf-8 -*-

import os
import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

# .envの読み込み

load_dotenv()

# ============================================================

# Discord 設定

# ============================================================

TOKEN  = os.getenv('TOKEN')
PREFIX = "!"

# ============================================================

# Supabase 設定

# ============================================================

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

if SUPABASE_URL and SUPABASE_KEY:
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
supabase = None
print("WARNING: Supabase credentials are missing.")

# ============================================================

# 共通ユーティリティ

# ============================================================

JST = datetime.timezone(datetime.timedelta(hours=9))

def get_now():
"""日本時間の現在時刻を返す"""
return datetime.datetime.now(JST)

COLOR_SUCCESS = 0x00ff88   # 成功・完了
COLOR_ERROR   = 0xff4444   # 失敗・エラー
COLOR_INFO    = 0x8B4513   # 情報・確認


# — コマンド使用統計 —

command_usage        = {}
team_command_usage   = {}
category_command_usage = {cat: 0 for cat in COMMAND_CATEGORIES}

# — ユーザーキャッシュ —

user_cache   = {}
role_timers  = {}
prison_state = {}

# — ゲームセッション —

vc_members    = {}
msg_cooldowns = {}
active_kneads = {}
mining_ct     = {}
double_game   = {}
active_duels  = {}
kakuhen_data  = {}
lose_streak   = {}
six_counter   = {}
internal_mode = {}
win_streak    = {}

# — プレイヤー統計・実績 —

player_stats      = {}
user_achievements = {}
daily_mission_data= {}

# — ダンジョン用グローバル —

dg_maps    = {}
dg_players = {}
dg_starts  = {}
dg_used    = {}
dg_bases   = {}
dg_stairs  = {}
dg_session = {}
dg_boxes   = {}
Dg         = {}   # 探索済み座標 {uid: {floor: set[(x,y)]}}

# ============================================================

# ダンジョン定数

# ============================================================

# — タイルID（文字列） —

D_WALL   = "wall"
D_FLOOR  = "floor"
D_START  = "start"
D_STAIRS = "stairs"
D_CHEST  = "chest"
D_TRAP   = "trap"
D_SHOP   = "shop"
D_BASE   = "base"
D_MINE   = "mine"
D_LOBY   = "loby"

# — 施設内部タイルID —

I_WALL    = "i_wall"
I_FLOOR   = "i_floor"
I_EXIT    = "i_exit"
I_COUNTER = "i_counter"
I_REST    = "i_rest"
I_STORAGE = "i_storage"
I_BAKERY  = "i_bakery"
I_DOUBLE  = "i_double"
I_SLOT    = "i_slot"

# — マップサイズ —

D_MAP_W  = 101
D_MAP_H  = 101
D_FLOORS = 40
D_VIEW_R = 5    # 視野半径（5 → 11×11 表示）
TILE     = 32   # 1マスのピクセル数

# — バイオーム定義 (floor range, 名前, 壁emoji, 床emoji, 特殊emoji, 埋め込みカラー) —

D_BIOMES = [
(range(1,  10), "洞窟",     "⬜", "⬛", "🌫️", 0x5C4033),
(range(10, 20), "森",       "🟫", "🟩", "🌫️", 0x2D5A1B),
(range(20, 30), "氷雪地帯", "⬜", "🔹", "🌫️", 0x5B9BD5),
(range(30, 41), "砂漠地帯", "🟧", "🟨", "🌫️", 0xC8600A),
]

# — バイオームごとのエンカウント率 —

D_ENCOUNTER_RATES = {
"洞窟":     0.05,
"森":       0.20,
"氷雪地帯": 0.07,
"砂漠地帯": 0.13,
}

# — タイルカラー（Pillow描画用） —

TILE_COLORS = {
D_WALL:   {"洞窟":(80,60,50),   "森":(40,60,20),   "氷雪地帯":(200,220,240), "砂漠地帯":(120,80,30)},
D_FLOOR:  {"洞窟":(40,30,25),   "森":(60,100,30),  "氷雪地帯":(100,160,200), "砂漠地帯":(200,160,60)},
D_START:  (30, 100, 220),
D_STAIRS: (220, 60,  60),
D_CHEST:  (220, 200, 30),
D_TRAP:   None,          # 床と同色（見えない）
D_SHOP:   (180, 80,  200),
D_BASE:   (80,  120, 220),
D_MINE:   (255, 0,   120),
"player": (30,  220, 120),
"fog":    (0,   0,   0),
}