import os
import datetime
from flask import Flask
from supabase import create_client, Client
from dotenv import load_dotenv
load_dotenv()
app = Flask('')
tok = os.getenv('TOKEN')
PREFIX = "!"
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
JST = datetime.timezone(datetime.timedelta(hours=9))