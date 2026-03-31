# -*- coding: utf-8 -*-
import os
import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

# .envの読み込み
load_dotenv()

# --- Discord設定 ---
TOKEN = os.getenv('TOKEN')
PREFIX = "!"

# --- Supabase設定 ---
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# クライアントの初期化
if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None
    print("WARNING: Supabase credentials are missing.")

# --- 共通ユーティリティ ---
JST = datetime.timezone(datetime.timedelta(hours=9))

def get_now():
    """日本時間の現在時刻を返す"""
    return datetime.datetime.now(JST)