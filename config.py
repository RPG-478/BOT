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