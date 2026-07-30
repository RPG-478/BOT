import discord
from discord.ext import commands
import asyncio
import time
import logging
import configparser
import string
import subprocess
import json
import io
import yt_dlp
import struct
import math  # 追加: Timerクラスのサイン波計算で必要
from discord.ext import voice_recv
import threading
import random
import numpy as np
from scipy import signal
import numpy as np

class DebugCog(commands.Cog):
  def __init__(self, bot):
    self.bot = bot
    self.log_buffer = bot.log_buffer

  def get_cpu_usage(self):
      def read_cpu():
          try:
              with open("/proc/stat", "r") as f:
                  line = f.readline()
                  values = list(map(int, line.split()[1:]))
                  return values[3], sum(values)
          except: return 0, 1
      i1, t1 = read_cpu()
       time.sleep(0.5)
      i2, t2 = read_cpu()
      if t2 - t1 == 0: return 0
      return 100 * (1 - (i2 - i1) / (t2 - t1))

  def get_mem_usage(self):
      try:
          mem = {}
          with open("/proc/meminfo") as f:
              for line_str in f:
                  parts = line_str.split(":")
                  if len(parts) == 2: mem[parts[0]] = int(parts[1].split()[0])
          total = mem.get("MemTotal", 1)
          used = total - mem.get("MemAvailable", mem.get("MemFree", 0))
          return (used / total) * 100, used, total
      except: return 0, 0, 0
