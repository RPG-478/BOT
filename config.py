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

