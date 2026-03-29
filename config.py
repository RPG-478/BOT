# -*- coding: utf-8 -*-
import os, discord, json, random, asyncio, datetime, math, signal, string, io
from discord.ui import View, Button
from discord import app_commands, Interaction
from discord.app_commands import CommandTree
from discord.ext import tasks
from supabase import create_client, Client
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from collections import defaultdict
from matplotlib.font_manager import FontProperties
from dotenv import load_dotenv
from constants import *
font = FontProperties(fname='font.ttf', size=16)
#from dungeo import setup_dungeon
from flask import Flask
import threading
app = Flask('')
tok = os.getenv('TOKEN')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
# ============================================================
#  Embed カラー定数 
# ============================================================
COLOR_SUCCESS = 0x00ff88   #  成功・完了
COLOR_ERROR   = 0xff4444   #  失敗・エラー・権限なし
COLOR_INFO    = 0x8B4513   # ℹ️ 情報・確認
# ============================================================

stop = False; breads_day = []; user_cache = {}; role_timers = {}; vc_members = {}; msg_cooldowns = {}
kakuhen_data = {}; lose_streak = {}; six_counter = {}; active_kneads = {}; mining_ct = {}
double_game = {}; internal_mode = {}; win_streak = {}; active_duels = {}
market_state = {"trend":0}; prison_state = {}; rate_history = []; volume_history = []
bcount = 0; economy_coin = 100000000; global_pool = 0; epsilon = 0
today = datetime.datetime.now(JST).date()
rate_state = {"rate":BASE_RATE,"last_update":None}
recovery_state = {"energy": 0.0}
daily_stats = {"pan_count":0,"gamble_count":0,"pan_to_coin":0,"coin_to_pan":0,"coins_earned":0,"shop_role_count":0,"shop_item_count":0,"rate_history_daily":[],"pan_word_count":0}
command_usage = {}
team_command_usage = {}
dg_stairs = {}

# ============================================================
#  レベルロール定義 (レベル達成時に付与)
# ============================================================
LEVEL_ROLES = {
    1:  1111111,
    10: 2222222,
    25: 3333333,
    40: 555555,
    50: 6666666,
}
# ============================================================
#  デイリーミッション定義
# ============================================================
DAILY_MISSIONS_ALL = [
    {"id": "knead_rare",    "desc": "レアパンを10個こねる",        "key": "knead_rare",    "target": 10},
    {"id": "slot_play",     "desc": "スロットで10回遊ぶ",          "key": "slot_play",     "target": 10},
    {"id": "dice_play",     "desc": "ダイスで3回遊ぶ",             "key": "dice_play",     "target": 3},
    {"id": "item_mix",      "desc": "アイテムを2回錬成する",       "key": "item_mix",      "target": 2},
    {"id": "double_play",   "desc": "ダブルゲームを2回する",       "key": "double_play",   "target": 2},
]
DAILY_MISSION_REWARD = 60  # レアパン60個

# デイリーミッションの進捗 {uid: {"date": date, "missions": [id,...], "progress": {id: count}, "claimed": bool}}
daily_mission_data = {}
