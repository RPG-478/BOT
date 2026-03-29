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
font = FontProperties(fname='font.ttf', size=16)
#from dungeo import setup_dungeon
from flask import Flask
import threading
from PIL import Image, ImageDraw
app = Flask('')
from config import *

@app.route('/')
def home():
    return "I'm alive!"

def run_web():
    app.run(host='0.0.0.0', port=8080)

# --- 修正後（この通りに書き換えてください） ---
# 1. まずパスを定義するるるるる
env_path = os.path.join(os.path.dirname(__file__), '.env')

# 2. そのパスを使って読み込む
load_dotenv(env_path)

# 3. その後でスレッドを開始する
threading.Thread(target=run_web).start()

# --- 起動時の処理 ---
async def load_extensions():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            await bot.load_extension(f"cogs.{filename[:-3]}")

# 既存の起動シーケンスの中で load_extensions() を実行するようにします
# 例: 


def embed_success(title: str = None, description: str = None) -> discord.Embed:
    """成功・完了用 Embed"""
    return discord.Embed(title=title, description=description, color=COLOR_SUCCESS)

def embed_error(title: str = None, description: str = None) -> discord.Embed:
    """失敗・エラー用 Embed"""
    return discord.Embed(title=title, description=description, color=COLOR_ERROR)

def embed_info(title: str = None, description: str = None) -> discord.Embed:
    """情報表示用 Embed"""
    return discord.Embed(title=title, description=description, color=COLOR_INFO)
def get_daily_mission(uid):
    """今日のデイリーミッションを取得。なければ新規生成"""
    today_str = datetime.datetime.now(JST).date().isoformat()
    d = daily_mission_data.get(uid)
    if not d or d.get("date") != today_str:
        chosen = random.sample([m["id"] for m in DAILY_MISSIONS_ALL], 3)
        daily_mission_data[uid] = {
            "date": today_str,
            "missions": chosen,
            "progress": {mid: 0 for mid in chosen},
            "claimed": False,
        }
    return daily_mission_data[uid]

def add_daily_progress(uid, key, amount=1):
    """デイリーミッションの進捗を加算"""
    d = get_daily_mission(uid)
    for m in DAILY_MISSIONS_ALL:
        if m["id"] == key and key in d["missions"]:
            d["progress"][key] = d["progress"].get(key, 0) + amount
            break

def get_player_stats(uid):
    if uid not in player_stats:
        player_stats[uid] = {
            "total_bread": 0,
            "total_coins_earned": 0,
            "total_gamble": 0,
            "total_steal_success": 0,
            "total_dungeon_floor": 0,
            "total_slot": 0,
            "total_dice": 0,
            "total_double": 0,
            "total_item_mix": 0,
            "max_chips_won_once": 0,
            "ticket_bought": 0,
            "trash_bought": 0,
        }
    return player_stats[uid]

def get_user_achievements(uid):
    if uid not in user_achievements:
        user_achievements[uid] = set()
    return user_achievements[uid]

async def check_and_grant_achievement(uid, achievement_id, interaction_or_channel=None):
    """実績を解除して通知"""
    ach = next((a for a in ACHIEVEMENTS if a["id"] == achievement_id), None)
    if not ach: return
    achs = get_user_achievements(uid)
    if achievement_id in achs: return
    achs.add(achievement_id)
    # Supabaseに保存
    try:
        supabase.table("user_achievements").upsert({"user_id": uid, "achievement_id": achievement_id, "unlocked_at": datetime.datetime.now(JST).isoformat()}).execute()
    except Exception as e:
        print(f"実績保存失敗: {e}")
    # 通知
    embed = embed_success(f"{ach['icon']} 実績解除！", f"**{ach['name']}**\n{ach['desc']}")
    try:
        ch = client.get_channel(LEVEL_UP_CHANNEL_ID) or await client.fetch_channel(LEVEL_UP_CHANNEL_ID)
        await ch.send(f"<@{uid}>", embed=embed)
    except Exception as e:
        print(f"実績通知失敗: {e}")

# --- アセット・プレイヤー画像のキャッシュ用（関数の外に配置） ---
_ASSET_CACHE = {}
PLAYER_IMAGE = None  # グローバルで初期化

# --- ASSET_CONFIG ---
ASSET_CONFIG = {
    ("洞窟", D_WALL): "rock.PNG",
    ("洞窟", D_FLOOR): "jimen.png",
    ("森", D_WALL): "mori_kabe.png",
    ("森", D_FLOOR): "mori_yuka.png",
    ("氷雪地帯", D_WALL): "Y_k.png",
    ("氷雪地帯", D_FLOOR): "Y_y.png",
    ("砂漠地帯", D_WALL): "Y_k.png",
    ("砂漠地帯", D_FLOOR): "Y_y.png",
}

def load_all_assets():
    """Assetsフォルダから画像を読み込みキャッシュする"""
    global _ASSET_CACHE, PLAYER_IMAGE  # PLAYER_IMAGEもグローバルとして扱う
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    assets_dir = os.path.join(base_dir, "Assets")
    
    # 1. プレイヤー画像の読み込み（ループの外で1度だけ行う）
    try:
        # AGO.PNG が Assets フォルダ内にある場合は assets_dir を結合してください
        # 実行ファイルと同じ階層にある場合はそのまま
        p_path = "AGO.PNG" 
        PLAYER_IMAGE = Image.open(p_path).convert("RGBA")
        print(f"✓ プレイヤー画像を読み込みました: {p_path}")
    except Exception as e:
        print(f"❌ プレイヤー画像(AGO.PNG)ロード失敗: {e}")
        PLAYER_IMAGE = None

    # 2. タイルアセットの読み込み
    for (biome, tid), fname in ASSET_CONFIG.items():
        path = os.path.join(assets_dir, fname)
        if os.path.isfile(path):
            try:
                # ニアレストネイバー法でリサイズ
                img = Image.open(path).convert("RGBA").resize((TILE, TILE), Image.Resampling.NEAREST)
                _ASSET_CACHE[(biome, tid)] = img
                print(f"✓ {fname} を正常に読み込みました")
            except Exception as e:
                print(f"❌ {fname} ロード失敗: {e}")
        else:
            print(f"⚠ {fname} が見つかりません: {path}")

# --- 実行 ---
# 忘れずに load_all_assets() を呼び出してください（on_ready内など）
# --- プレイヤー画像（AGO.PNG）の準備 ---

# --- ここに ASSET_CONFIG も必要です ---
ASSET_CONFIG = {
    ("洞窟", D_WALL): "rock.PNG",
    ("洞窟", D_FLOOR): "jimen.png",
    ("森", D_WALL): "mori_kabe.png",
    ("森", D_FLOOR): "mori_yuka.png",
    ("氷雪地帯", D_WALL): "Y_k.png",
    ("氷雪地帯", D_FLOOR): "Y_y.png",
    ("砂漠地帯", D_WALL): "Y_k.png",
    ("砂漠地帯", D_FLOOR): "Y_y.png",
}
_ASSET_CACHE = {}

def get_user_cache(uid):
    if uid not in user_cache:
        user_cache[uid] = {"bread_count":0,"bread_prob":0.1,"login_available":1,"coins":0,"chips":0,"xp":0,"level":0,"boxes":0,"sake":0,"hesokuri":0,"rare_bread":0,"rare_avg":0,"items":{}}
    if "items" not in user_cache[uid]: user_cache[uid]["items"] = {}
    return user_cache[uid]

async def load_user(uid):
    if uid in user_cache: return user_cache[uid]
    try:
        res = supabase.table("user_data").select("*").eq("user_id",uid).execute()
        if res.data:
            row = res.data[0]
            row.setdefault("rare_bread",0); row.setdefault("rare_avg",0)
            if not isinstance(row.get("items"),dict):
                try: row["items"] = json.loads(row["items"] or "{}")
                except: row["items"] = {}
            user_cache[uid] = row
        else:
            user_cache[uid] = {"user_id":uid,"bread_count":0,"bread_prob":0.1,"login_available":1,"coins":0,"chips":0,"xp":0,"level":0,"boxes":0,"sake":0,"hesokuri":0,"rare_bread":0,"rare_avg":0,"items":{}}
    except Exception as e:
        print(f"load_user失敗:{e}")
        user_cache[uid] = {"user_id":uid,"bread_count":0,"bread_prob":0.1,"login_available":1,"coins":0,"chips":0,"xp":0,"level":0,"boxes":0,"sake":0,"hesokuri":0,"rare_bread":0,"rare_avg":0,"items":{}}
    return user_cache[uid]

async def save_user(uid):
    if uid not in user_cache: return
    try:
        data = dict(user_cache[uid]); data["user_id"] = uid
        data.pop("rare_bread",None); data.pop("rare_avg",None)
        data["items"] = json.dumps(data.get("items",{}), ensure_ascii=False)
        supabase.table("user_data").upsert(data).execute()
    except Exception as e: print(f"save_user失敗 {uid}:{e}")

async def save_global():
    try:
        for u in [{"key":"global_pool","value":global_pool},{"key":"economy_coin","value":economy_coin},{"key":"bcount","value":bcount},{"key":"epsilon","value":epsilon}]:
            supabase.table("global_data").upsert(u).execute()
    except Exception as e: print(f"save_global失敗:{e}")

async def load_global():
    global global_pool,economy_coin,bcount,epsilon,breads_day,role_timers
    try:
        res = supabase.table("global_data").select("*").execute()
        for row in res.data:
            if row["key"]=="global_pool": global_pool=int(row["value"])
            elif row["key"]=="economy_coin": economy_coin=int(row["value"])
            elif row["key"]=="bcount": bcount=int(row["value"])
            elif row["key"]=="epsilon": epsilon=float(row["value"])
        print("グローバルデータ読み込み完了")
    except Exception as e: print(f"load_global失敗:{e}")
    try:
        ch = client.get_channel(SAVE_ID) or await client.fetch_channel(SAVE_ID)
        async for msg in ch.history(limit=40):
            for att in msg.attachments:
                if att.filename=="role_timers.txt" and not role_timers:
                    role_timers=json.loads((await att.read()).decode("utf-8")); print("ロールタイマー読み込み完了")
    except Exception as e: print(f"role_timers読み込み失敗:{e}")
    try:
        since = (datetime.datetime.now(JST) - datetime.timedelta(hours=24)).isoformat()
        res = supabase.table("rate_history").select("*").gte("timestamp", since).order("timestamp").execute()
        if res.data:
            rate_history.clear(); volume_history.clear()
            for row in res.data:
                t = datetime.datetime.fromisoformat(row["timestamp"])
                rate_history.append((t, float(row["rate"])))
                volume_history.append(int(row.get("volume", 100)))
            last = res.data[-1]
            rate_state["rate"] = float(last["rate"])
            rate_state["last_update"] = datetime.datetime.fromisoformat(last["timestamp"])
            print(f"レート履歴復元完了: {len(rate_history)}件")
    except Exception as e: print(f"rate_history復元失敗:{e}")
    # 実績の読み込み
    try:
        res = supabase.table("user_achievements").select("*").execute()
        for row in res.data:
            uid = row["user_id"]; aid = row["achievement_id"]
            if uid not in user_achievements: user_achievements[uid] = set()
            user_achievements[uid].add(aid)
        print(f"実績データ読み込み完了: {len(res.data)}件")
    except Exception as e: print(f"実績読み込み失敗:{e}")
    # プレイヤー統計の読み込み
    try:
        res = supabase.table("player_stats").select("*").execute()
        for row in res.data:
            uid = row["user_id"]
            player_stats[uid] = {
                "total_bread":          row.get("total_bread", 0),
                "total_coins_earned":   row.get("total_coins_earned", 0),
                "total_gamble":         row.get("total_gamble", 0),
                "total_steal_success":  row.get("total_steal_success", 0),
                "total_dungeon_floor":  row.get("total_dungeon_floor", 0),
                "total_slot":           row.get("total_slot", 0),
                "total_dice":           row.get("total_dice", 0),
                "total_double":         row.get("total_double", 0),
                "total_item_mix":       row.get("total_item_mix", 0),
                "max_chips_won_once":   row.get("max_chips_won_once", 0),
                "ticket_bought":        row.get("ticket_bought", 0),
                "trash_bought":         row.get("trash_bought", 0),
            }
        print(f"プレイヤー統計読み込み完了: {len(res.data)}件")
    except Exception as e: print(f"プレイヤー統計読み込み失敗:{e}")
    # デイリーミッション進捗の読み込み
    try:
        today_str = datetime.datetime.now(JST).date().isoformat()
        res = supabase.table("daily_missions").select("*").eq("date", today_str).execute()
        for row in res.data:
            uid = row["user_id"]
            daily_mission_data[uid] = {
                "date":     row.get("date", today_str),
                "missions": json.loads(row.get("missions", "[]")),
                "progress": json.loads(row.get("progress", "{}")),
                "claimed":  bool(row.get("claimed", False)),
            }
        print(f"デイリーミッション読み込み完了: {len(res.data)}件")
    except Exception as e: print(f"デイリーミッション読み込み失敗:{e}")

async def save_all_users():
    for uid in list(user_cache.keys()): await save_user(uid)
    await save_global()
    try:
        ch = client.get_channel(SAVE_ID) or await client.fetch_channel(SAVE_ID)
        with open("role_timers.txt","w",encoding="utf-8") as f: f.write(json.dumps(role_timers,ensure_ascii=False,indent=2))
        await ch.send(file=discord.File("role_timers.txt"))
    except Exception as e: print(f"role_timers保存失敗:{e}")
    # プレイヤー統計の保存
    try:
        for uid, st in list(player_stats.items()):
            row = {"user_id": uid, **st}
            supabase.table("player_stats").upsert(row).execute()
    except Exception as e: print(f"プレイヤー統計保存失敗:{e}")
    # デイリーミッション進捗の保存
    try:
        today_str = datetime.datetime.now(JST).date().isoformat()
        for uid, d in list(daily_mission_data.items()):
            if d.get("date") == today_str:
                supabase.table("daily_missions").upsert({
                    "user_id":  uid,
                    "date":     d["date"],
                    "missions": json.dumps(d["missions"], ensure_ascii=False),
                    "progress": json.dumps(d["progress"], ensure_ascii=False),
                    "claimed":  d.get("claimed", False),
                }).execute()
    except Exception as e: print(f"デイリーミッション保存失敗:{e}")

def has_item(uid,name):
    u = get_user_cache(uid); item = u["items"].get(name)
    if not item or item.get("count",0)<=0: return False
    # expiresが設定されている場合のみ期限チェック（未発動アイテムはexpiresなし）
    if item.get("expires") and datetime.datetime.now(JST).isoformat()>item["expires"]:
        # 期限切れ分を1個消費、残りがあれば保持（次のitem useで再発動可能）
        item["count"] -= 1
        item.pop("expires", None)
        if item["count"] <= 0:
            del u["items"][name]
        return False
    # expiresなし（未発動）またはexpires内なら有効
    return True

def is_item_active(uid,name):
    """時間付きアイテムが発動中（expires設定済み＆期限内）かチェック"""
    u = get_user_cache(uid); item = u["items"].get(name)
    if not item or item.get("count",0)<=0: return False
    if not item.get("expires"): return False
    return datetime.datetime.now(JST).isoformat() <= item["expires"]

def use_item_once(uid, name):
    u = get_user_cache(uid)
    items = u.get("items", {})
    if name in items:
        items[name]["count"] -= 1
        if items[name]["count"] <= 0:
            del items[name]

def give_item(uid,name,count=1):
    u = get_user_cache(uid); info = ITEMS.get(name,{}); duration = info.get("duration")
    u["items"].setdefault(name,{"count":0})["count"]+=count
    # 時間付きアイテムは item use 実行時にタイマー開始するため、ここでは expires を設定しない

def is_in_prison(uid):
    until = prison_state.get(uid)
    if not until: return False
    if datetime.datetime.now(JST)<until: return True
    del prison_state[uid]; return False

def set_prison(uid,hours):
    prison_state[uid]=datetime.datetime.now(JST)+datetime.timedelta(hours=hours)

def xp_needed(lv): return lv*100

def get_exchange_rate():
    now = datetime.datetime.now(JST)
    if rate_state["last_update"] is None:
        rate_state["last_update"] = now
        rate_history.append((now, BASE_RATE))
        volume_history.append(random.randint(50,200))
        return BASE_RATE, "市場開始"
    rate = rate_state["rate"]
    event_text = ""
    trend_strength = abs(market_state["trend"])
    base_vol = 0.002
    vol = base_vol + trend_strength * 2
    vol = min(vol, 0.04)
    rate *= (1 + random.gauss(0, vol))
    rate *= (1 + market_state["trend"])
    if random.random() < 0.05:
        market_state["trend"] = random.uniform(-0.005, 0.005)
    if random.random() < 0.02:
        news = random.choice(news_list)
        rate *= news[1]
        event_text = news[0]
    if random.random() < 0.03:
        whale = random.choice([("大口買い",1.1),("大口売り",0.9)])
        rate *= whale[1]
        event_text = whale[0]
    if len(rate_history) >= 20:
        ma = sum(p for _,p in rate_history[-20:]) / 20
    else:
        ma = rate
    deviation = (rate - ma) / ma
    recovery_state["energy"] += deviation * 0.03
    recovery_state["energy"] *= 0.99
    energy = recovery_state["energy"]
    trigger_prob = min(abs(energy) * 0.4, 0.3)
    if random.random() < trigger_prob:
        release = energy * random.uniform(0.2,0.6)
        rate *= (1 - release)
        recovery_state["energy"] -= release
    rate = max(rate,1)
    volume = random.randint(100,2000)
    rate_state["rate"] = rate
    rate_state["last_update"] = now
    rate_history.append((now, rate))
    volume_history.append(volume)
    daily_stats["rate_history_daily"].append((now, rate))
    if len(rate_history) > 2000:
        rate_history.pop(0)
        volume_history.pop(0)
    try:
        supabase.table("rate_history").insert({
            "timestamp": now.isoformat(),
            "rate": float(rate),
            "volume": volume,
            "event": event_text or None,
        }).execute()
    except Exception as e: print(f"rate_history保存失敗:{e}")
    return int(rate), event_text

def generate_chart():
    now = datetime.datetime.now(JST)
    cutoff = now - datetime.timedelta(hours=5)
    filtered = [(t,p) for (t,p) in rate_history if t >= cutoff]
    filtered_vol = [v for (t,p),v in zip(rate_history, volume_history) if t >= cutoff]
    if not filtered:
        filtered = rate_history[-1:] if rate_history else [(now, BASE_RATE)]
        filtered_vol = volume_history[-1:] if volume_history else [100]
    fmd=defaultdict(list); vd=defaultdict(int)
    for (t,p),v in zip(filtered, filtered_vol):
        key=t.replace(minute=(t.minute//5)*5,second=0,microsecond=0); fmd[key].append(p); vd[key]+=v
    ohlc=[]; vols=[]
    for k in sorted(fmd):
        ps=fmd[k]; ohlc.append((k,ps[0],max(ps),min(ps),ps[-1])); vols.append(vd[k])
    ohlc=ohlc[-60:]; vols=vols[-60:]
    closes=[x[4] for x in ohlc]
    ma=[sum(closes[i-20:i])/20 if i>=20 else None for i in range(len(closes))]
    fig,(ax,ax2)=plt.subplots(2,1,figsize=(9,5),gridspec_kw={"height_ratios":[4,1]},facecolor="#2b2d31")
    ax.set_facecolor("#2b2d31"); ax2.set_facecolor("#2b2d31")
    for i,(t,o,h,l,c) in enumerate(ohlc):
        color="#00ff88" if c>=o else "#ff4444"
        ax.plot([i,i],[l,h],color=color); ax.add_patch(plt.Rectangle((i-0.3,min(o,c)),0.6,abs(c-o),color=color))
    ax.plot(ma,color="#ffaa00",linewidth=2); ax2.bar(range(len(vols)),vols)
    labels=[x[0].strftime("%H:%M") for x in ohlc]; step=max(1,len(labels)//10)
    ax.set_xticks(range(0,len(labels),step)); ax.set_xticklabels(labels[::step],rotation=45,color="white")
    ax.tick_params(colors="white"); ax2.tick_params(colors="white"); ax.set_title("コッペパン市場（過去5時間）",color="white",fontproperties=font)
    buf=io.BytesIO(); plt.savefig(buf,format="png",bbox_inches="tight",facecolor="#2b2d31"); buf.seek(0); plt.close(); return buf

def get_internal_rate(uid):
    m=internal_mode.get(uid,"NORMAL")
    return 0.75 if m=="FEVER" else 0.60

def add_xp(uid, xp):
    u = get_user_cache(uid); u["xp"] += xp; leveled = False; levels_gained = []
    while u["xp"] >= xp_needed(u["level"] + 1):
        u["xp"] -= xp_needed(u["level"] + 1); u["level"] += 1; leveled = True
        levels_gained.append(u["level"])
        # レベルアップごとにレアパン10個
        u["bread_count"] = u.get("bread_count", 0) + 10
        st = get_player_stats(uid); st["total_bread"] = st.get("total_bread", 0) + 10
    # 付与すべきロールIDリスト
    role_grants = [LEVEL_ROLES[lv] for lv in levels_gained if lv in LEVEL_ROLES]
    return leveled, role_grants

def add_chips(uid,amt): get_user_cache(uid)["chips"]+=amt
def subtract_chips(uid,amt): get_user_cache(uid)["chips"]-=amt
def get_chips(uid): return get_user_cache(uid)["chips"]
def get_coins(uid): return get_user_cache(uid)["coins"]
def check_count(uid): return get_user_cache(uid)["bread_count"]

intents=discord.Intents.default(); intents.message_content=True; intents.members=True; intents.voice_states=True

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents); self.tree=CommandTree(self)
    async def setup_hook(self):
        try:
            await self.tree.sync()
            print("コマンド同期完了")
        except discord.errors.HTTPException as e:
            if e.status == 429:
                print(f"レート制限中のためコマンド同期をスキップします")
            else:
                raise e
client=MyClient()
@tasks.loop(minutes=5)
async def auto_save():
    try:
        # 1. 既存のユーザーデータ保存
        await save_all_users()
        # tryの中に成功時のメッセージを入れる
        print("自動保存完了 (探索データ含む)")
        
    except Exception as e:
        # エラーが起きた時だけここが実行される
        print(f"探索データの自動保存中にエラー: {e}")


@tasks.loop(minutes=1)
async def update_rate_task(): get_exchange_rate()

@tasks.loop(minutes=1)
async def bread_bake():
    global global_pool; global_pool+=10
    ch=client.get_channel(random.choice(bread_ids))
    if ch: await ch.send("パン")

@tasks.loop(minutes=5)
async def vc_xp_loop():
    for uid in list(vc_members.keys()):
        await load_user(str(uid))
        result = add_xp(str(uid), random.randint(VC_XP_MIN, VC_XP_MAX))
        leveled, role_grants = result if isinstance(result, tuple) else (result, [])
        if leveled:
            for g in client.guilds:
                m = g.get_member(uid)
                if m: await send_level_up_message(m, get_user_cache(str(uid))["level"], role_grants)

@tasks.loop(hours=1)
async def check_role_expiry():
    now=datetime.datetime.now(JST); expired=[]
    for uid,info in list(role_timers.items()):
        if info.get("boost"): continue
        if now>=datetime.datetime.fromisoformat(info["expires"]):
            expired.append(uid)
            for g in client.guilds:
                m=g.get_member(int(uid))
                if m:
                    r=g.get_role(info["role_id"])
                    if r:
                        try: await m.remove_roles(r); await m.send(f"ロール `{r.name}` の期限が切れました。")
                        except: pass
    for uid in expired: del role_timers[uid]
    boost_expired=[]
    for key,info in list(role_timers.items()):
        if not info.get("boost"): continue
        if now>=datetime.datetime.fromisoformat(info["expires"]):
            boost_expired.append(key)
            uid=key.replace("boost_","")
            for g in client.guilds:
                m=g.get_member(int(uid))
                if m:
                    r=g.get_role(info["role_id"])
                    if r:
                        try: await m.remove_roles(r)
                        except: pass
    for k in boost_expired: del role_timers[k]

@tasks.loop(hours=1)
async def cleanup_rate_history():
    try:
        cutoff = (datetime.datetime.now(JST) - datetime.timedelta(hours=24)).isoformat()
        supabase.table("rate_history").delete().lt("timestamp", cutoff).execute()
        print("rate_history古いデータ削除完了")
    except Exception as e: print(f"rate_history削除失敗:{e}")

@tasks.loop(hours=1)
async def midnight_tasks():
    now=datetime.datetime.now(JST)
    if now.hour==0:
        await send_daily_report(); reset_daily_stats()
        if now.day==1: await monthly_team_ranking_role()

async def send_daily_report():
    try:
        user=await client.fetch_user(DAILY_REPORT_USER_ID)
        buf=None; daily_rate=daily_stats["rate_history_daily"]
        if len(daily_rate)>=2:
            fig,ax=plt.subplots(figsize=(8,3),facecolor="#2b2d31"); ax.set_facecolor("#2b2d31")
            rates=[x[1] for x in daily_rate]; times=[x[0] for x in daily_rate]
            ax.plot(range(len(rates)),rates,color="#00ff88")
            labels=[t.strftime("%H:%M") for t in times]; step=max(1,len(labels)//8)
            ax.set_xticks(range(0,len(labels),step)); ax.set_xticklabels(labels[::step],rotation=45,color="white")
            ax.tick_params(colors="white"); ax.set_title("本日のレート推移",color="white")
            buf2=io.BytesIO(); plt.savefig(buf2,format="png",bbox_inches="tight",facecolor="#2b2d31"); buf2.seek(0); plt.close(); buf=buf2
        tcn,tcv,tbn,tbv,tbc="不明",0,"不明",0,0
        try:
            res=supabase.table("user_data").select("user_id,coins,bread_count").execute()
            if res.data:
                tc=max(res.data,key=lambda x:x.get("coins",0)); tb=max(res.data,key=lambda x:x.get("bread_count",0))
                tcv=tc.get("coins",0); tbv=tb.get("bread_count",0); tbc=tb.get("coins",0)
                for g in client.guilds:
                    m=g.get_member(int(tc["user_id"]))
                    if m: tcn=m.display_name
                    m2=g.get_member(int(tb["user_id"]))
                    if m2: tbn=m2.display_name
        except: pass
        try: team_count=len(supabase.table("teams").select("team_id").execute().data)
        except: team_count="?"
        sorted_cmds=sorted(command_usage.items(),key=lambda x:x[1],reverse=True)[:10]
        cmd_lines="\n".join([f"  /{k}: {v}回" for k,v in sorted_cmds]) if sorted_cmds else "  なし"
        sorted_team_users=sorted(team_command_usage.items(),key=lambda x:x[1],reverse=True)[:5]
        team_user_lines_list=[]
        for tuid,cnt in sorted_team_users:
            for g in client.guilds:
                m=g.get_member(int(tuid))
                if m: team_user_lines_list.append(f"  {m.display_name}: {cnt}回"); break
            else: team_user_lines_list.append(f"  ID:{tuid}: {cnt}回")
        team_user_lines="\n".join(team_user_lines_list) if team_user_lines_list else "  なし"
        # カテゴリ別コマンド使用数
        cat_lines="\n".join([f"  {cat}: {cnt}回" for cat,cnt in category_command_usage.items()])
        report=(f" **本日の日報**\n\n パン: **{daily_stats['pan_count']}個**\n ギャンブル: **{daily_stats['gamble_count']}回**\n"
                f" パンと言われた回数: **{daily_stats['pan_word_count']}回**\n\n"
                f" パン→コイン: **{daily_stats['pan_to_coin']}回** / コイン→パン: **{daily_stats['coin_to_pan']}回**\n"
                f" 稼がれたコイン: **{daily_stats['coins_earned']:,}枚**\n\n"
                f" コイン1位: **{tcn}** — {tcv:,}コイン\n パン1位: **{tbn}** — {tbv:,}個 / {tbc:,}コイン\n\n"
                f" チーム数: **{team_count}**\n ロール購入: **{daily_stats['shop_role_count']}回** / アイテム購入: **{daily_stats['shop_item_count']}回**\n\n"
                f" **コマンド使用回数（本日上位10）:**\n{cmd_lines}\n\n"
                f" **カテゴリ別コマンド使用回数:**\n{cat_lines}\n\n"
                f" **チームコマンド使用者（本日上位5）:**\n{team_user_lines}")
        if buf: await user.send(content=report,file=discord.File(buf,"daily_rate.png"))
        else: await user.send(content=report)
        # Supabaseにも日報を保存
        try:
            today_str = datetime.datetime.now(JST).date().isoformat()
            report_data = {
                "date": today_str,
                "pan_count": daily_stats["pan_count"],
                "gamble_count": daily_stats["gamble_count"],
                "pan_word_count": daily_stats["pan_word_count"],
                "pan_to_coin": daily_stats["pan_to_coin"],
                "coin_to_pan": daily_stats["coin_to_pan"],
                "coins_earned": daily_stats["coins_earned"],
                "shop_role_count": daily_stats["shop_role_count"],
                "shop_item_count": daily_stats["shop_item_count"],
                "top_coin_user": tcn,
                "top_coin_value": tcv,
                "top_bread_user": tbn,
                "top_bread_value": tbv,
                "command_usage": json.dumps(dict(sorted_cmds), ensure_ascii=False),
                "category_usage": json.dumps(dict(category_command_usage), ensure_ascii=False),
            }
            supabase.table("daily_reports").upsert(report_data).execute()
            print("日報をSupabaseに保存しました")
        except Exception as e:
            print(f"日報Supabase保存失敗:{e}")
    except Exception as e: print(f"日報送信失敗:{e}")

def reset_daily_stats():
    global daily_stats, command_usage, team_command_usage
    daily_stats={"pan_count":0,"gamble_count":0,"pan_to_coin":0,"coin_to_pan":0,"coins_earned":0,"shop_role_count":0,"shop_item_count":0,"rate_history_daily":[],"pan_word_count":0}
    command_usage={}
    team_command_usage={}
    for k in category_command_usage: category_command_usage[k] = 0

async def monthly_team_ranking_role():
    try:
        all_teams=supabase.table("teams").select("*").execute().data
        if not all_teams: return
        ranked=[]
        for t in all_teams:
            tc=await get_team_total_coins(t["team_id"]); members=await get_team_members(t["team_id"]); ranked.append((t,tc,members))
        ranked.sort(key=lambda x:x[1],reverse=True); top_team,_,top_members=ranked[0]
        for g in client.guilds:
            rr=g.get_role(TEAM_RANK_ROLE_ID)
            if not rr: continue
            for m in rr.members:
                try: await m.remove_roles(rr)
                except: pass
            for m in top_members:
                gm=g.get_member(int(m["user_id"]))
                if gm:
                    try: await gm.add_roles(rr)
                    except: pass
    except Exception as e: print(f"月次チームロール失敗:{e}")

async def send_level_up_message(member, new_level, role_grants=None):
    try:
        ch = client.get_channel(LEVEL_UP_CHANNEL_ID) or await client.fetch_channel(LEVEL_UP_CHANNEL_ID)
        embed = embed_info()
        embed.description = (f"**{member.display_name}** がレベルアップしました！\n"
                             f"Lv. **{new_level}** \n次のレベルまで: **{xp_needed(new_level+1)} XP**\n"
                             f"🍞 レアパン **+10個** ゲット！")
        await ch.send(content=member.mention, embed=embed)
        # ロール付与
        if role_grants:
            for g in client.guilds:
                m = g.get_member(member.id)
                if m:
                    for role_id in role_grants:
                        r = g.get_role(role_id)
                        if r:
                            try:
                                await m.add_roles(r)
                                await ch.send(embed=embed_success(f"🎉 ロール付与", f"{member.mention} にロール **{r.name}** を付与しました！"))
                            except Exception as e:
                                print(f"ロール付与失敗 {role_id}: {e}")
    except Exception as e:
        print(f"レベルアップ通知失敗:{e}")

@client.event
async def on_ready():
    global bcount, epsilon
    print("Ready"); await load_global(); await asyncio.sleep(30)
    
    # --- ここにアセット読み込みを追加 ---
    load_all_assets() 
    await load_extensions() # これを追加
    await bot.tree.sync()   # スラッシュコマンドの同期
    print(f'Logged in as {bot.user}')
    # -------------------------------

    if not auto_save.is_running(): auto_save.start()
    if not update_rate_task.is_running(): update_rate_task.start()
    if not bread_bake.is_running(): bread_bake.start()
    if not vc_xp_loop.is_running(): vc_xp_loop.start()
    if not check_role_expiry.is_running(): check_role_expiry.start()
    if not cleanup_rate_history.is_running(): cleanup_rate_history.start()
    if not midnight_tasks.is_running(): midnight_tasks.start()
    if not lottery_loop.is_running(): lottery_loop.start()
    
    await dg_load_all()
    if not dungeon_task.is_running(): dungeon_task.start()
    
    client.loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(shutdown()))
    print("起動完了")


async def shutdown():
    await save_all_users(); await client.close()

@client.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.application_command:
        cmd_name = interaction.command.qualified_name if interaction.command else "unknown"
        command_usage[cmd_name] = command_usage.get(cmd_name, 0) + 1
        if cmd_name.startswith("team"):
            uid = str(interaction.user.id)
            team_command_usage[uid] = team_command_usage.get(uid, 0) + 1
        # カテゴリ別集計
        for cat, cmds in COMMAND_CATEGORIES.items():
            if any(cmd_name == c or cmd_name.startswith(c + " ") for c in cmds):
                category_command_usage[cat] = category_command_usage.get(cat, 0) + 1
                break

@client.event
async def on_voice_state_update(member,before,after):
    uid=member.id
    if before.channel is None and after.channel is not None: vc_members[uid]=datetime.datetime.now()
    elif before.channel is not None and after.channel is None: vc_members.pop(uid,None)

@client.event
async def on_message(message):
    global bcount,today,breads_day,global_pool,economy_coin
    current_date=datetime.datetime.now(JST).date()
    if today!=current_date:
        breads_day.append(bcount); bcount=0; today=current_date
        for uid in user_cache: user_cache[uid]["login_available"]=1
    person=message.author; guild=message.guild; uid=str(person.id)
    if 'パン' in message.content: daily_stats["pan_word_count"]+=1
    await load_user(uid); u=get_user_cache(uid)
    if 'パン' in message.content and message.channel.id in bread_ids:
        if stop: return
        if (not message.author.bot) or (message.content=='パン' and message.author.id==client.user.id):
            bcount+=1; daily_stats["pan_count"]+=1; r=random.random()
            bp=u["bread_prob"]
            if has_item(uid,"積立主義"): bp=max(0.01,bp-0.20)
            if has_item(uid,"職人気質"): bp=min(0.99,bp+0.10)
            if r<bp:
                role=discord.utils.get(guild.roles,name="パン職人")
                gain=1+(1 if has_item(uid,"ネズミ算") else 0)
                u["bread_count"]+=gain
                for i,need in enumerate([30000,10000,5000,2500,500]):
                    if u["bread_count"]>=need:
                        ro=guild.get_role(int(["1416341170551918632","1416341035331616838","1411170717147598902","1411178549511192631","1411178608784965652"][i]))
                        try: await person.add_roles(ro)
                        except: pass
                try: await person.add_roles(role)
                except: pass
                u["bread_prob"]=max(0.01,u["bread_prob"]-0.03)
                await message.reply(f"# {random.choice(atari)}\n{person.mention}レアパンが当選しました。/exchangeで交換できます。")
                if random.random()<0.3: u["boxes"]+=1; await message.channel.send(f" **宝箱が出ました！** {person.mention} （所持:{u['boxes']}個）")
                if random.random()<0.5:
                    scale=random.randint(1,1000)+(random.randint(10000,1000000) if random.random()<0.01 else 0)
                    if has_item(uid,"独占契約"):
                        u["coins"]+=scale; use_item_once(uid,"独占契約"); await message.channel.send(f"**鉱山発見！** 独占契約発動！ {scale}コインを直接獲得！")
                    else:
                        global_pool+=scale; economy_coin-=int(scale*1.3); u["coins"]+=int(scale*0.3)
                        await message.channel.send(f"**鉱山を発見しました！！！** 鉱山規模{scale}コイン。発見ボーナスを獲得。")
            else:
                if has_item(uid,"ワンボックス") and random.random()<0.01: u["boxes"]+=1; await message.channel.send(f" **ワンボックス発動！** {person.mention}")
                if random.random()<0.1:
                    u["bread_prob"]=max(0.01,u["bread_prob"]-0.01); choice=random.choice(hazure)
                    if choice in ["確変","<:opanchu:1419129639439171686><:opanchu:1419129639439171686><:opanchu:1419129639439171686>"]:
                        u["bread_prob"]+=0.03; choice+="\nレアパンの出る確率が上がりました"
                    await message.reply(choice)
                else:
                    u["bread_prob"]=min(0.9,u["bread_prob"]+0.01)
                    cg=random.randint(20,30) if has_item(uid,"積立主義") else (2 if has_item(uid,"プレーン型") else 1)
                    u["coins"]+=cg; daily_stats["coins_earned"]+=cg; scale=random.randint(1,5); global_pool+=scale; economy_coin-=scale
                    await message.reply(f"-#  自動でコッペパンコインに変換されました（+{cg}枚） {scale}コインがグローバルプールに落ちました。")
            await save_user(uid)
    if not message.author.bot:
        now=datetime.datetime.now(); last=msg_cooldowns.get(uid)
        if last is None or (now-last).total_seconds()>=MSG_COOLDOWN:
            msg_cooldowns[uid]=now
            result = add_xp(uid, random.randint(MSG_XP_MIN, MSG_XP_MAX))
            leveled, role_grants = result if isinstance(result, tuple) else (result, [])
            if leveled: await send_level_up_message(message.author, u["level"], role_grants)
    if isinstance(message.channel, discord.DMChannel) and str(message.author.id)==DELETE_ALLOWED:
        if message.content.startswith("/delete "):
            target=message.content[len("/delete "):].strip()
            if target.upper()=="ALL":
                try:
                    supabase.table("user_data").delete().neq("user_id","___never___").execute()
                    user_cache.clear()
                    await message.channel.send(" 全ユーザーデータを削除しました。️この操作は取り消せません。")
                except Exception as e: await message.channel.send(f"削除失敗:{e}")
            else:
                try:
                    supabase.table("user_data").delete().eq("user_id",target).execute()
                    user_cache.pop(target,None)
                    await message.channel.send(f" ユーザー `{target}` のデータを削除しました。")
                except Exception as e: await message.channel.send(f"削除失敗:{e}")
        elif message.content.startswith("/delete"):
            await message.channel.send("使い方: `/delete [ユーザーID]` または `/delete ALL`")

# ============================================================
#  コマンド（全レスポンスをEmbed統一）
# ============================================================
@client.tree.command(name="today",description="今日作ったパンの数")
async def today_cmd(i:Interaction):
    await i.response.send_message(embed=embed_info(" 今日のパン",f"本日のパン生産数: **{bcount}個**"))

@client.tree.command(name="bpd",description="breads per day")
async def bpd(i:Interaction):
    if not breads_day:
        await i.response.send_message(embed=embed_error("エラー","まだパンが作られていません。"))
        return
    avg=sum(breads_day)/len(breads_day)
    await i.response.send_message(embed=embed_info(" 1日平均パン数",f"**{avg:.2f}個 / 日**"))

@client.tree.command(name="economy_coin",description="グローバルプール残高を表示")
async def pool(i:discord.Interaction):
    embed=embed_info(" 経済情報")
    embed.add_field(name=" 国庫",value=f"**{economy_coin:,} コイン**",inline=True)
    embed.add_field(name=" グローバルプール",value=f"**{global_pool:,} コイン**",inline=True)
    await i.response.send_message(embed=embed)

@client.tree.command(name="random",description="ランダムな編成を作成します")
async def random_team(i:Interaction):
    global epsilon
    with open('characters.json',"r",encoding="utf-8") as f: chars=json.load(f)
    rd=random.random()
    content=""
    if rd>epsilon:
        member=[random.choice(chars["耐久"])]; others=chars["その他"][:]
        for _ in range(3): c=random.choice(others); member.append(c); others.remove(c)
        if "アベンチュリン" in member: epsilon+=0.0000001
        for idx,party in enumerate(party_list):
            if set(member)==set(party): content=f"「{party_name[idx]}」これにて完成！"; epsilon=0
    else:
        rd=random.randint(0,len(party_list)-1); member=party_list[rd]; content=f"「{party_name[rd]}」これにて完成！"; epsilon=0
    embed=embed_info(" ランダム編成", content if content else None)
    embed.add_field(name="編成",value=f"`{', '.join(member)}`",inline=False)
    await i.response.send_message(embed=embed)

@client.tree.command(name="party_check",description="パーティーが出る確率の調整をチェックします")
async def epsilon_check(i:Interaction):
    await i.response.send_message(embed=embed_info(" 確率チェック",f"基礎確率 +**{(100*epsilon):.5f}%**"))

@client.tree.command(name='give',description="レアパンを譲渡します（手数料10%）")
async def give(i:Interaction,count:int,member:discord.Member):
    if count<10:
        await i.response.send_message(embed=embed_error("エラー","最低でも10個のパンを指定してください"))
        return
    uid=str(i.user.id); await load_user(uid); await load_user(str(member.id)); u=get_user_cache(uid)
    lose=math.ceil(count*1.1)
    if u["bread_count"]>=lose:
        u["bread_count"]-=lose; get_user_cache(str(member.id))["bread_count"]+=count
        await save_user(uid); await save_user(str(member.id))
        embed=embed_success(" パン譲渡完了")
        embed.add_field(name="譲渡先",value=member.mention,inline=True)
        embed.add_field(name="譲渡数",value=f"**{count}個**",inline=True)
        embed.add_field(name="手数料込み消費",value=f"**{lose}個**",inline=True)
        await i.response.send_message(embed=embed)
    else:
        await i.response.send_message(embed=embed_error("エラー",f"パンが足りません。\n所持: **{u['bread_count']}個** / 必要: **{lose}個**"))

@client.tree.command(name="login",description="ログインボーナスをゲットします")
async def login(i:Interaction):
    uid=str(i.user.id); await load_user(uid); u=get_user_cache(uid)
    if u["login_available"]:
        u["login_available"]=0; u["boxes"]+=5; u["bread_count"]+=20; ct="20"
        if random.randint(1,5)==1: u["bread_count"]+=30; ct="50"
        await save_user(uid)
        embed=embed_success(" ログインボーナス")
        embed.add_field(name=" レアパン",value=f"**+{ct}個**",inline=True)
        embed.add_field(name=" 宝箱",value="**+5個**",inline=True)
        await i.response.send_message(embed=embed)
    else:
        await i.response.send_message(embed=embed_error("ログインボーナス","すでにログインボーナスを獲得しています。明日また来てください！"))

@client.tree.command(name="bread_change",description="一部の管理者用です")
async def bread_change(i:Interaction,type:str,userid:str,number:str):
    if str(i.user.id) not in moderators:
        await i.response.send_message(embed=embed_error("権限エラー","このコマンドを実行する権限がありません。"))
        return
    n=int(number); await load_user(userid); u=get_user_cache(userid)
    if type=="bread": u["bread_count"]=n
    elif type=="coin": u["coins"]=n
    elif type=="chip": u["chips"]+=n
    elif type=="login":
        for uid in user_cache: user_cache[uid]["login_available"]=n
    elif type=="grant":
        r=i.guild.get_role(n); m=await i.guild.fetch_member(int(userid)); await m.add_roles(r)
    elif type=="stop":
        global stop; stop=True
    elif type=="start": stop=False
    else:
        await i.response.send_message(embed=embed_error("エラー","typeが無効です"))
        return
    await save_user(userid)
    await i.response.send_message(embed=embed_success(" 実行完了",f"`{type}` を `{userid}` に適用しました。"))

@client.tree.command(name="level",description="自分または指定したユーザーのレベルを確認します")
async def level_cmd(i:Interaction,member:discord.Member=None):
    if not member: member=i.user
    await load_user(str(member.id)); u=get_user_cache(str(member.id)); lv=u["level"]; xp=u["xp"]; needed=xp_needed(lv+1)
    progress=int((xp/needed)*20) if needed>0 else 0; bar="█"*progress+"░"*(20-progress)
    embed=embed_info(f" {member.display_name} のレベル情報")
    embed.add_field(name="レベル",value=f"**{lv}**",inline=True)
    embed.add_field(name="XP",value=f"**{xp}/{needed}**",inline=True)
    embed.add_field(name="進捗",value=f"`{bar}`",inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    await i.response.send_message(embed=embed)

@client.tree.command(name="ranking_level",description="レベルランキングを表示します")
async def ranking_level(i:Interaction):
    await i.response.defer()
    try: res=supabase.table("user_data").select("user_id,level,xp").order("level",desc=True).limit(10).execute(); data=res.data
    except Exception as e:
        await i.followup.send(embed=embed_error("エラー",f"データ取得失敗: {e}"))
        return
    medals=["","",""]; text=""
    for idx,row in enumerate(data):
        m=i.guild.get_member(int(row["user_id"])); name=m.display_name if m else "[退出済み]"
        text+=f"{medals[idx] if idx<3 else f'`{idx+1}.`'} **{name}** — Lv.{row['level']} ({row['xp']} XP)\n"
    await i.followup.send(embed=embed_info(" レベルランキング TOP10",text))

@client.tree.command(name="wallet",description="レアパン・コイン・チップの残高を確認します")
async def wallet_cmd(i:Interaction,member:discord.Member=None):
    if not member: member=i.user
    uid=str(member.id); await load_user(uid); u=get_user_cache(uid); rate,_=get_exchange_rate()
    embed=embed_info(f" {member.display_name} の所持状況")
    embed.add_field(name=" レアパン",value=f"**{u['bread_count']}個**",inline=True)
    embed.add_field(name=" コッペパンコイン",value=f"**{u['coins']:,}枚**",inline=True)
    embed.add_field(name=" アンパンチップ",value=f"**{u['chips']:,}チップ**",inline=True)
    embed.add_field(name=" 現在の為替レート",value=f"1レアパン = **{rate}コイン**",inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    await i.response.send_message(embed=embed)

class RateView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label=" リロード",style=discord.ButtonStyle.green)
    async def reload(self,i:discord.Interaction,b:discord.ui.Button):
        await i.response.defer(); rate,event=get_exchange_rate(); chart=generate_chart()
        embed=embed_info(" コッペパン為替",f"現在レート **{rate} coin**")
        if event: embed.add_field(name=" ニュース",value=event)
        embed.set_image(url="attachment://chart.png")
        await i.edit_original_response(embed=embed,attachments=[discord.File(chart,"chart.png")],view=self)

@client.tree.command(name="rate",description="現在レートとグラフを確認します（過去5時間）")
async def rate_cmd(i:discord.Interaction):
    await i.response.defer(); rate,event=get_exchange_rate(); chart=generate_chart()
    embed=embed_info(" コッペパン為替",f"現在レート **{rate} coin**")
    if event: embed.add_field(name=" ニュース",value=event)
    embed.set_image(url="attachment://chart.png")
    await i.followup.send(embed=embed,file=discord.File(chart,"chart.png"),view=RateView())

@client.tree.command(name="shop",description="ショップ：ロール(1,000,000コイン)またはアイテムを購入します")
@discord.app_commands.choices(category=[discord.app_commands.Choice(name="ロール（1,000,000コイン）",value="role"),discord.app_commands.Choice(name="アイテム（焼き釜など）",value="item")])
@discord.app_commands.choices(item_name=[discord.app_commands.Choice(name=" 酒 300コイン",value="sake"),discord.app_commands.Choice(name=" へそくり 800コイン",value="hesokuri"),discord.app_commands.Choice(name="ブロンズ焼き釜 500コイン",value="oven_ブロンズ"),discord.app_commands.Choice(name="シルバー焼き釜 2000コイン",value="oven_シルバー"),discord.app_commands.Choice(name="ゴールド焼き釜 5000コイン",value="oven_ゴールド"),discord.app_commands.Choice(name="プリズム焼き釜 500000コイン",value="oven_プリズム")])
async def shop(i:Interaction,category:discord.app_commands.Choice[str],role:discord.Role=None,item_name:discord.app_commands.Choice[str]=None):
    if stop:
        await i.response.send_message(embed=embed_error("停止中","現在BOTは停止中です。"))
        return
    uid=str(i.user.id); await load_user(uid); u=get_user_cache(uid); coins=u["coins"]
    if category.value=="item":
        if item_name is None:
            embed=embed_info(" アイテムショップ")
            embed.add_field(name="アイテム一覧",value=(
                " 酒 — **300コイン**\n"
                " へそくり — **800コイン**\n"
                " ブロンズ焼き釜 — **500コイン**\n"
                "️ シルバー焼き釜 — **2,000コイン**\n"
                " ゴールド焼き釜 — **5,000コイン**\n"
                " プリズム焼き釜 — **500,000コイン**"
            ),inline=False)
            embed.set_footer(text="item_nameを選択して購入してください")
            await i.response.send_message(embed=embed)
            return
        val=item_name.value
        if val.startswith("oven_"):
            on=val.replace("oven_",""); price=OVEN_PRICES[on]
            if coins<price:
                await i.response.send_message(embed=embed_error("コイン不足",f"所持: **{coins:,}枚** / 必要: **{price:,}枚**"))
                return
            u["coins"]-=price; give_item(uid,f"焼き釜_{on}",1); await save_user(uid); daily_stats["shop_item_count"]+=1
            embed=embed_success(" 購入完了",f"**{on}焼き釜** を購入しました！（{price:,}コイン）\n`/item use 焼き釜_{on}` で使用できます。")
            await i.response.send_message(embed=embed)
            return
        prices={"sake":300,"hesokuri":800}; names={"sake":" 酒","hesokuri":" へそくり"}
        price=prices[val]; name=names[val]
        if coins<price:
            await i.response.send_message(embed=embed_error("コイン不足",f"所持: **{coins:,}枚** / 必要: **{price:,}枚**"))
            return
        u["coins"]-=price; u[val]=u.get(val,0)+1; await save_user(uid); daily_stats["shop_item_count"]+=1
        embed=embed_success(" 購入完了",f"{name} を購入しました！（{price}コイン）\n所持コイン: **{u['coins']:,}枚**")
        await i.response.send_message(embed=embed)
        return
    if role is None:
        await i.response.send_message(embed=embed_error("エラー","ロールを選択してください。"))
        return
    if int(role.id) not in SHOP_ROLES:
        await i.response.send_message(embed=embed_error("エラー","そのロールはショップで購入できません。"))
        return
    rname=SHOP_ROLE_NAMES[SHOP_ROLES.index(int(role.id))]
    if any(r.id==role.id for r in i.user.roles):
        if coins<ROLE_PRICE:
            await i.response.send_message(embed=embed_error("コイン不足",f"所持: **{coins:,}枚** / 必要: **{ROLE_PRICE:,}枚**"))
            return
        u["coins"]-=ROLE_PRICE
        if uid in role_timers and role_timers[uid]["role_id"]==role.id:
            ne=datetime.datetime.fromisoformat(role_timers[uid]["expires"])+datetime.timedelta(days=ROLE_DURATION_DAYS)
        else: ne=datetime.datetime.now(JST)+datetime.timedelta(days=ROLE_DURATION_DAYS)
        role_timers[uid]={"role_id":role.id,"expires":ne.isoformat()}; await save_user(uid); daily_stats["shop_role_count"]+=1
        embed=embed_success(" 期限延長完了",f"ロール `{rname}` の期限を延長しました！（{ROLE_PRICE:,}コイン）\n新しい有効期限: **{ne.strftime('%Y/%m/%d')}**")
        await i.response.send_message(embed=embed)
        return
    having=[r.id for r in i.user.roles if r.id in SHOP_ROLES]
    if having:
        if coins<ROLE_SWAP_PRICE:
            await i.response.send_message(embed=embed_error("コイン不足",f"所持: **{coins:,}枚** / 必要: **{ROLE_SWAP_PRICE:,}枚**"))
            return
        u["coins"]-=ROLE_SWAP_PRICE
        for hid in having:
            ro=i.guild.get_role(hid)
            if ro and hid not in [TEAM_SHOP_ROLE_ID,BOOST_SHOP_ROLE_ID]: await i.user.remove_roles(ro)
        await i.user.add_roles(role); expires=datetime.datetime.now(JST)+datetime.timedelta(days=ROLE_DURATION_DAYS)
        role_timers[uid]={"role_id":role.id,"expires":expires.isoformat()}; await save_user(uid); daily_stats["shop_role_count"]+=1
        embed=embed_success(" ロール付け替え完了",f"ロール `{rname}` に付け替えました！（{ROLE_SWAP_PRICE:,}コイン）\n有効期限: **{expires.strftime('%Y/%m/%d')}**")
        await i.response.send_message(embed=embed)
        return
    if coins<ROLE_PRICE:
        await i.response.send_message(embed=embed_error("コイン不足",f"所持: **{coins:,}枚** / 必要: **{ROLE_PRICE:,}枚**"))
        return
    u["coins"]-=ROLE_PRICE; await i.user.add_roles(role)
    expires=datetime.datetime.now(JST)+datetime.timedelta(days=ROLE_DURATION_DAYS)
    role_timers[uid]={"role_id":role.id,"expires":expires.isoformat()}; await save_user(uid); daily_stats["shop_role_count"]+=1
    embed=embed_success(" ロール購入完了",f"ロール `{rname}` を購入しました！（{ROLE_PRICE:,}コイン）\n有効期限: **{expires.strftime('%Y/%m/%d')}**")
    await i.response.send_message(embed=embed)

@client.tree.command(name="team_shop",description="チームランキング1位限定ショップ（100,000コイン）")
async def team_shop(i:Interaction):
    uid=str(i.user.id); m=i.guild.get_member(int(uid)); rr=i.guild.get_role(TEAM_RANK_ROLE_ID)
    if not rr or rr not in m.roles:
        await i.response.send_message(embed=embed_error("アクセス不可","このショップはチームランキング1位のチームメンバーのみ利用できます。"))
        return
    await load_user(uid); u=get_user_cache(uid)
    if u["coins"]<TEAM_SHOP_ROLE_PRICE:
        await i.response.send_message(embed=embed_error("コイン不足",f"所持: **{u['coins']:,}枚** / 必要: **{TEAM_SHOP_ROLE_PRICE:,}枚**"))
        return
    sr=i.guild.get_role(TEAM_SHOP_ROLE_ID)
    if not sr:
        await i.response.send_message(embed=embed_error("エラー","ロールが見つかりません。"))
        return
    u["coins"]-=TEAM_SHOP_ROLE_PRICE; await i.user.add_roles(sr); await save_user(uid)
    embed=embed_success(" 特別ロール購入完了",f"特別ロールを購入しました！（{TEAM_SHOP_ROLE_PRICE:,}コイン）\nこのロールはキャラロールを買っても外れません。")
    await i.response.send_message(embed=embed)

@client.tree.command(name="boost_shop",description="ブースター限定特別ロール（1,000,000コイン・90日）")
async def boost_shop(i:Interaction):
    uid=str(i.user.id); m=i.guild.get_member(int(uid)); br=i.guild.get_role(BOOST_ROLE_ID)
    if not br or br not in m.roles:
        await i.response.send_message(embed=embed_error("アクセス不可","このショップはサーバーブースターのみ利用できます。"))
        return
    await load_user(uid); u=get_user_cache(uid)
    if u["coins"]<BOOST_SHOP_ROLE_PRICE:
        await i.response.send_message(embed=embed_error("コイン不足",f"所持: **{u['coins']:,}枚** / 必要: **{BOOST_SHOP_ROLE_PRICE:,}枚**"))
        return
    u["coins"]-=BOOST_SHOP_ROLE_PRICE; sr=i.guild.get_role(BOOST_SHOP_ROLE_ID)
    if sr: await i.user.add_roles(sr)
    bk=f"boost_{uid}"
    ne=(datetime.datetime.fromisoformat(role_timers[bk]["expires"])+datetime.timedelta(days=BOOST_SHOP_ROLE_DAYS)) if bk in role_timers else (datetime.datetime.now(JST)+datetime.timedelta(days=BOOST_SHOP_ROLE_DAYS))
    role_timers[bk]={"role_id":BOOST_SHOP_ROLE_ID,"expires":ne.isoformat(),"boost":True}; await save_user(uid)
    embed=embed_success(" ブーストロール購入完了",f"ブースト特別ロールを購入しました！（{BOOST_SHOP_ROLE_PRICE:,}コイン）\n有効期限: **{ne.strftime('%Y/%m/%d')}**\nこのロールはキャラロールを買っても外れません。")
    await i.response.send_message(embed=embed)

@client.tree.command(name="role_status",description="現在つけているショップロールと残り期間を確認します")
async def role_status(i:Interaction):
    uid=str(i.user.id)
    embed=embed_info(" ロール状況")
    has_any=False
    if uid in role_timers:
        info=role_timers[uid]; expires=datetime.datetime.fromisoformat(info["expires"]); days=(expires-datetime.datetime.now(JST)).days
        r=i.guild.get_role(info["role_id"]); rn=r.name if r else "不明なロール"
        embed.add_field(name=" キャラロール",value=f"**{rn}**\n残り **{days}日**（{expires.strftime('%Y/%m/%d')}まで）",inline=False)
        has_any=True
    bk=f"boost_{uid}"
    if bk in role_timers:
        info2=role_timers[bk]; expires2=datetime.datetime.fromisoformat(info2["expires"]); days2=(expires2-datetime.datetime.now(JST)).days
        embed.add_field(name=" ブーストロール",value=f"残り **{days2}日**（{expires2.strftime('%Y/%m/%d')}まで）",inline=False)
        has_any=True
    if not has_any:
        await i.response.send_message(embed=embed_info(" ロール状況","現在期限管理されているロールはありません。"))
        return
    await i.response.send_message(embed=embed)

item_group=app_commands.Group(name="item",description="アイテム関連コマンド")

@item_group.command(name="shop",description="特殊アイテムショップを開きます")
async def item_shop(i:Interaction):
    embed=embed_info("️ 特殊アイテムショップ")
    lines=""
    for name,info in ITEMS.items():
        if name in UNCRAFTABLE_ITEMS: continue
        dur=f"({info['duration']}h)" if info["duration"] else "(消耗品)"
        lines+=f"**{name}** {dur} — {info['price']:,}コイン\n"
    embed.description=lines[:4000]
    embed.set_footer(text="/item buy [名前] で購入")
    await i.response.send_message(embed=embed)

@item_group.command(name="buy", description="特殊アイテムを購入します")
@app_commands.describe(name="アイテム名（/item shopで確認）",amount="購入数")
async def item_buy(i: Interaction, name: str, amount: int = 1):
    await i.response.defer()
    uid = str(i.user.id); await load_user(uid); u = get_user_cache(uid)
    if amount <= 0:
        await i.followup.send(embed=embed_error("エラー","購入数は1以上にしてください。"))
        return
    if amount > 999:
        await i.followup.send(embed=embed_error("エラー","一度に購入できるのは999個までです。"))
        return
    if name not in ITEMS:
        await i.followup.send(embed=embed_error("エラー","そのアイテムは存在しません。`/item shop` で確認してください。"))
        return
    if name in UNCRAFTABLE_ITEMS:
        await i.followup.send(embed=embed_error("購入不可","このアイテムは購入できません。"))
        return
    info = ITEMS[name]; price = info["price"]; total_price = price * amount
    if u["coins"] < total_price:
        await i.followup.send(embed=embed_error("コイン不足",f"所持: **{u['coins']:,}枚** / 必要: **{total_price:,}枚**"))
        return
    u["coins"] -= total_price; give_item(uid, name, amount); await save_user(uid)
    daily_stats["shop_item_count"] += amount
    embed=embed_success(" 購入完了",f"**{name} ×{amount}** を購入しました！（{total_price:,}コイン）")
    embed.add_field(name="効果",value=info['desc'],inline=False)
    await i.followup.send(embed=embed)
@item_group.command(name="use", description="アイテムを使用します")
@app_commands.describe(name="使用するアイテム名")
async def item_use(i: Interaction, name: str):
    # 1. 応答遅延対策
    await i.response.defer(ephemeral=True)
    
    uid = str(i.user.id)
    await load_user(uid)
    u = get_user_cache(uid)
    
    # --- 1. 焼き釜の処理 ---
    if name.startswith("焼き釜_"):
        on = name.replace("焼き釜_", "")
        if not has_item(uid, name):
            await i.followup.send(embed=embed_error("エラー", f"**{name}** を持っていません。"))
            return
        if uid in active_kneads:
            await i.followup.send(embed=embed_error("エラー", "すでに焼き釜が稼働中です！"))
            return
        
        # ★修正：awaitを削除
        use_item_once(uid, name)
        await save_user(uid)
        
        minutes = OVEN_TYPES.get(on, [30])[0]
        embed = embed_success(f" {on}焼き釜 稼働開始", f"{i.user.mention} の{on}焼き釜が稼働開始！\n**{minutes}分間**、自動でパンをこねます")
        await i.followup.send(embed=embed)
        active_kneads[uid] = asyncio.create_task(knead_with_oven_task(i.user, i.channel, minutes, oven_name=on))
        return

    # --- 2. 酒の処理 ---
    if name == "酒":
        if u.get("sake", 0) <= 0:
            await i.followup.send(embed=embed_error("エラー", " 酒を持っていません。"))
            return
        u["sake"] -= 1
        # (酒の効果計算)
        effects = [
            ("bread_prob", 0.05, " 酒を飲んだ！レアパン確率が5%上昇した！"),
            ("coins", random.randint(100, 500), " 酒を飲んだ！気分がよくなってコインを拾った！"),
            ("chips", random.randint(50, 200), " 酒を飲んだ！賭け事が楽しくなってチップを獲得！"),
        ]
        ef = random.choice(effects)
        if ef[0] == "bread_prob":
            u["bread_prob"] = min(0.9, u.get("bread_prob", 0.1) + ef[1])
            msg = ef[2]
        elif ef[0] == "coins":
            u["coins"] += ef[1]
            msg = ef[2] + f"（+{ef[1]}コイン）"
        else:
            u["chips"] += ef[1]
            msg = ef[2] + f"（+{ef[1]}チップ）"
        await save_user(uid)
        await i.followup.send(embed=embed_success(" 酒を使用", msg))
        return

    # --- 3. 開拓のコンパス ---
    if name == "開拓のコンパス":
        if not has_item(uid, "開拓のコンパス"):
            await i.followup.send(embed=embed_error("エラー", "**開拓のコンパス** を持っていません。"))
            return

        floor, px, py = None, None, None
        if uid in dg_bases:
            floor, px, py = dg_bases[uid]
        elif uid in dg_players:
            p_data = dg_players[uid]
            floor = p_data.get("floor")
            px, py = p_data.get("x"), p_data.get("y")

        if floor is None:
            await i.followup.send(embed=embed_error("情報", "コンパスは静かに震えている…（探索中ではありません）"))
            return

        stair_pos = dg_stairs.get(floor)
        if not stair_pos:
            try:
                target_f = int(floor)
                res = supabase.table("dungeon_stairs").select("x, y").eq("floor", target_f).execute()
                if res.data and len(res.data) > 0:
                    stair_pos = (int(res.data[0]['x']), int(res.data[0]['y']))
                    dg_stairs[floor] = stair_pos
            except Exception as e:
                print(f"❌ Compass DB Error: {e}")

        if not stair_pos:
            # マップ走査救済
            d_ensure_map(floor)
            grid = dg_maps.get(floor)
            if grid:
                for y_idx, row in enumerate(grid):
                    if D_STAIRS in row:
                        stair_pos = (row.index(D_STAIRS), y_idx)
                        dg_stairs[floor] = stair_pos
                        try:
                            supabase.table("dungeon_stairs").upsert({"floor": int(floor), "x": stair_pos[0], "y": stair_pos[1]}).execute()
                        except: pass
                        break

        if not stair_pos:
            await i.followup.send(embed=embed_error("エラー", f"{floor}階で階段を検知できませんでした。"))
            return

        # ★重要修正：use_item_onceは同期関数なのでawaitを外す
        use_item_once(uid, "開拓のコンパス")

        sx, sy = stair_pos
        if px is not None and py is not None:
            dx, dy = sx - px, sy - py
            dirs = []
            if dy < 0: dirs.append("北");
            elif dy > 0: dirs.append("南");
            if dx > 0: dirs.append("東");
            elif dx < 0: dirs.append("西");
            direction = "".join(dirs) if dirs else "足元"
            res_msg = f"コンパスが激しく反応した！\n\n階段は **{floor}階** の **【{direction}】** 方向にあるようだ。"
        else:
            res_msg = f"コンパスが光を放った！\n\n**{floor}階** のどこかに階段が存在するようだ。"

        await save_user(uid)
        await i.followup.send(embed=embed_success("🧭 開拓のコンパス", res_msg))
        return

    # --- 4. 汎用アイテム ---
    if name not in ITEMS or not has_item(uid, name):
        await i.followup.send(embed=embed_error("エラー", "そのアイテムは使用できません。"))
        return

    # ★重要修正：ここもawaitを外す
    use_item_once(uid, name)

    info = ITEMS[name]
    duration = info.get("duration")
    embed = embed_success(f"{name} を使用")
    embed.add_field(name="効果", value=info['desc'], inline=False)
    
    if duration:
        item_data = u.get("items", {}).get(name, {})
        count = item_data.get("count", 1)
        total_hours = duration * count
        item_data["expires"] = (datetime.datetime.now(JST) + datetime.timedelta(hours=total_hours)).isoformat()
        embed.add_field(name="効果時間", value=f"**{total_hours}時間**（{count}個分累積）", inline=True)
        
    await save_user(uid)
    await i.followup.send(embed=embed)


@item_group.command(name="list",description="所持アイテム一覧を表示します")
async def item_list(i:Interaction):
    uid=str(i.user.id); await load_user(uid); u=get_user_cache(uid)
    now_str=datetime.datetime.now(JST).isoformat(); active={}
    for k,v in u.get("items",{}).items():
        if v.get("count",0)>0 and not (v.get("expires") and now_str>v["expires"]): active[k]=v
    if not active:
        await i.response.send_message(embed=embed_info(" 所持アイテム","アイテムを持っていません。"))
        return
    embed=embed_info(" 所持アイテム一覧")
    lines=""
    for k,v in active.items():
        exp=""
        if v.get("expires"):
            rem=(datetime.datetime.fromisoformat(v["expires"])-datetime.datetime.now(JST)).total_seconds()/3600
            exp=f" _(残り{rem:.1f}h)_"
        lines+=f"**{k}**: {v['count']}個{exp}\n"
    embed.description=lines
    await i.response.send_message(embed=embed)

client.tree.add_command(item_group)

class HelpView(discord.ui.View):
    def __init__(self): super().__init__(timeout=60)
    def get_embed(self, cat):
        def _usage(cmd):
            cnt = command_usage.get(cmd, 0)
            return f" `({cnt}回)`" if cnt > 0 else ""
        if cat == "bread":
            e = embed_info("🍞 パン関係コマンド")
            e.description = (
                f"`/breads [@メンバー]`…パン所持数確認{_usage('breads')}\n"
                f"`/today`…今日のパン総数{_usage('today')}\n"
                f"`/bpd`…1日平均パン数{_usage('bpd')}\n"
                f"`/eat_bread`…レアパンを食べる{_usage('eat_bread')}\n"
                f"`/give [個数] [@相手]`…レアパン譲渡（手数料10%）{_usage('give')}\n"
                f"`/login`…ログインボーナス（20〜50個）{_usage('login')}\n"
                f"`/item use 焼き釜_[種類]`…焼き釜でパンこね\n"
                f"\n📊 **本日のカテゴリ使用数: {category_command_usage.get('パン関係',0)}回**"
            )
        elif cat == "economy":
            e = embed_info("💰 経済関係コマンド")
            e.description = (
                f"`/wallet [@メンバー]`…残高確認{_usage('wallet')}\n"
                f"`/exchange [方向] [数量]`…レアパン⇔コイン⇔チップ交換{_usage('exchange')}\n"
                f"`/rate`…為替レートとグラフ（過去5時間）{_usage('rate')}\n"
                f"`/steal`…コインを盗む{_usage('steal')}\n"
                f"`/economy_coin`…国庫&プール残高{_usage('economy_coin')}\n"
                f"`/mining`…プールからコイン採掘{_usage('mining')}\n"
                f"`/trade [数量]`…レアパン取引{_usage('trade')}\n"
                f"`/lottery`…宝くじ購入{_usage('lottery')}\n"
                f"\n📊 **本日のカテゴリ使用数: {category_command_usage.get('経済関係',0)}回**"
            )
        elif cat == "gambling":
            e = embed_info("🎲 ミニゲーム関係コマンド")
            e.description = (
                f"`/slot7 [回数]`…7リールスロット（1000チップ固定）{_usage('slot7')}\n"
                f"`/dice [max] [number] [bet]`…数字当てゲーム{_usage('dice')}\n"
                f"`/double [bet]`…ダブルゲーム（コイン）{_usage('double')}\n"
                f"`/blackjack [bet]`…ブラックジャック（コイン）{_usage('blackjack')}\n"
                f"`/bj_duel [bet]`…プレイヤー対戦BJ（チップ・最低500）{_usage('bj_duel')}\n"
                f"`/daily`…デイリーミッション確認・報酬受け取り{_usage('daily')}\n"
                f"\n📊 **本日のカテゴリ使用数: {category_command_usage.get('ミニゲーム関係',0)}回**"
            )
        elif cat == "shop":
            e = embed_info("🛒 ショップ関係コマンド")
            e.description = (
                f"`/shop`…ロール(1,000,000コイン)・焼き釜・アイテム購入{_usage('shop')}\n"
                f"`/item shop`…特殊アイテムショップ一覧\n"
                f"`/item buy [名前]`…特殊アイテム購入\n"
                f"`/item use [名前]`…アイテム使用\n"
                f"`/item list`…所持アイテム確認\n"
                f"`/open`…宝箱を全部開ける{_usage('open')}\n"
                f"`/role_status`…ロール残り期間確認{_usage('role_status')}\n"
                f"`/team_shop`…チームランキング1位限定(100,000コイン){_usage('team_shop')}\n"
                f"`/boost_shop`…ブースター限定(1,000,000コイン・90日){_usage('boost_shop')}\n"
                f"\n📊 **本日のカテゴリ使用数: {category_command_usage.get('ショップ関係',0)}回**"
            )
        elif cat == "team":
            e = embed_info("👥 チーム関係コマンド")
            e.description = (
                f"`/make_team [名前]`…チーム作成(100,000コイン){_usage('make_team')}\n"
                f"`/team join`…招待コード発行（オーナーのみ）\n"
                f"`/team join [code]`…チームに参加\n"
                f"`/team name [新名前]`…チーム名変更(10,000コイン・オーナーのみ)\n"
                f"`/team status`…チーム状態確認\n"
                f"`/team bonus`…チームボーナス宝箱(1日1回)\n"
                f"`/team leave`…チーム脱退(5日間参加不可)\n"
                f"`/team member_delete [@member]`…メンバー削除（オーナーのみ）\n"
                f"`/team disband`…チーム解散（オーナーのみ）\n"
                f"`/team break [チームID]`…チーム強制解散（モデレーターのみ）\n"
                f"\n📊 **本日のカテゴリ使用数: {category_command_usage.get('チーム関係',0)}回**"
            )
        elif cat == "items_list":
            e = embed_info("🎒 アイテム関係コマンド")
            lines = ""
            for name, info in ITEMS.items():
                if name in UNCRAFTABLE_ITEMS:
                    dur = f"（{info['duration']}時間）" if info["duration"] else "（消耗品）"
                    lines += f"**{name}** {dur} — 非売品\n{info['desc']}\n\n"
                else:
                    dur = f"（{info['duration']}時間）" if info["duration"] else "（消耗品）"
                    lines += f"**{name}** {dur} — {info['price']:,}コイン\n{info['desc']}\n\n"
            lines += f"\n📊 **本日のカテゴリ使用数: {category_command_usage.get('アイテム関係',0)}回**"
            e.description = lines[:4000]
        elif cat == "oven":
            e = embed_info("🔥 焼きがま関係コマンド")
            e.description = (
                "**ブロンズ焼き釜** 500コイン — 5分、レアパン1/分\n"
                "**シルバー焼き釜** 2000コイン — 15分、レアパン2/分\n"
                "**ゴールド焼き釜** 5000コイン — 30分、レアパン5/分\n"
                "**プリズム焼き釜** 20000コイン — 60分、レアパン20/分\n"
                "**レインボー焼き釜** 50000コイン — 60分、レアパン1〜50/分+宝箱1/分\n\n"
                f"`/shop category:アイテム` で購入後\n`/item use 焼き釜_[種類]` で使用\n"
                f"`/oven_status` … 稼働中の焼き釜の状態確認{_usage('oven_status')}\n"
                f"\n📊 **本日のカテゴリ使用数: {category_command_usage.get('焼きがま関係',0)}回**"
            )
        elif cat == "dungeon":
            e = embed_info("🏰 ダンジョン関係コマンド")
            e.description = (
                f"`/dungeon`…ダンジョンに入る{_usage('dungeon')}\n"
                f"`/dungeon_reset`…マップリセット（モデレーターのみ）{_usage('dungeon_reset')}\n\n"
                "🗺️ **バイオーム**\n"
                "1〜9階: 洞窟 / 10〜19階: 森 / 20〜29階: 氷雪地帯 / 30〜40階: 砂漠地帯\n\n"
                "⚔️ **ゲームプレイ**\n"
                "移動・宝箱・罠・ショップ・拠点・鉱山・エネミーエンカウントあり\n"
                f"\n📊 **本日のカテゴリ使用数: {category_command_usage.get('ダンジョン関係',0)}回**"
            )
        elif cat == "other":
            e = embed_info("⚙️ その他コマンド")
            e.description = (
                f"`/level [@メンバー]`…レベルとXP確認{_usage('level')}\n"
                f"`/ranking_level`…レベルランキングTOP10{_usage('ranking_level')}\n"
                f"`/ranking [type]`…各種ランキング（bread/coin/wallet/team）{_usage('ranking')}\n"
                f"`/my_stats`…自分のプレイ統計{_usage('my_stats')}\n"
                f"`/achievement`…実績一覧と解除条件{_usage('achievement')}\n"
                f"`/my_achievement`…自分が解除した実績{_usage('my_achievement')}\n"
                f"`/random`…ランダム編成を生成{_usage('random')}\n"
                f"`/party_check`…編成確率確認{_usage('party_check')}\n"
                "`/reset`…管理者用リセット\n"
                "`/kill`…モデレーター用BOT停止\n"
                "⚠️ 管理者以外さわらないでください全てが壊れます"
            )
        else:
            e = embed_info("ヘルプ")
        return e

    @discord.ui.button(label="パン",     style=discord.ButtonStyle.secondary)
    async def bread_btn(self,   i, b): await i.response.edit_message(embed=self.get_embed("bread"),     view=self)
    @discord.ui.button(label="経済",     style=discord.ButtonStyle.secondary)
    async def economy_btn(self, i, b): await i.response.edit_message(embed=self.get_embed("economy"),   view=self)
    @discord.ui.button(label="ミニゲーム",style=discord.ButtonStyle.secondary)
    async def gambling_btn(self,i, b): await i.response.edit_message(embed=self.get_embed("gambling"),  view=self)
    @discord.ui.button(label="ショップ", style=discord.ButtonStyle.secondary)
    async def shop_btn(self,    i, b): await i.response.edit_message(embed=self.get_embed("shop"),      view=self)
    @discord.ui.button(label="チーム",   style=discord.ButtonStyle.secondary)
    async def team_btn(self,    i, b): await i.response.edit_message(embed=self.get_embed("team"),      view=self)
    @discord.ui.button(label="アイテム", style=discord.ButtonStyle.secondary)
    async def items_btn(self,   i, b): await i.response.edit_message(embed=self.get_embed("items_list"),view=self)
    @discord.ui.button(label="焼き釜",   style=discord.ButtonStyle.secondary)
    async def oven_btn(self,    i, b): await i.response.edit_message(embed=self.get_embed("oven"),      view=self)
    @discord.ui.button(label="ダンジョン",style=discord.ButtonStyle.secondary)
    async def dungeon_btn(self, i, b): await i.response.edit_message(embed=self.get_embed("dungeon"),   view=self)
    @discord.ui.button(label="その他",   style=discord.ButtonStyle.secondary)
    async def other_btn(self,   i, b): await i.response.edit_message(embed=self.get_embed("other"),     view=self)

@client.tree.command(name="help",description="コマンド一覧")
async def help_cmd(i:Interaction):
    view=HelpView(); await i.response.send_message(embed=view.get_embed("bread"),view=view)

class Slot7View(View):
    def __init__(self,uid,max_spin):
        super().__init__(timeout=120); self.user_id=uid; self.max_spin=max_spin; self.remaining=max_spin
    async def interaction_check(self,i):
        if str(i.user.id)!=self.user_id:
            await i.response.send_message(embed=embed_error("エラー","この台はあなた専用です。"),ephemeral=True)
            return False
        return True
    @discord.ui.button(label=" 回す",style=discord.ButtonStyle.primary)
    async def spin(self,i:Interaction,b:Button):
        global global_pool,economy_coin
        if self.remaining<=0:
            await i.response.send_message(embed=embed_error("エラー","回数上限に達しました。"),ephemeral=True)
            return
        if is_in_prison(self.user_id):
            await i.response.send_message(embed=embed_error("プリズン中","プリズン状態中はギャンブルできません。"),ephemeral=True)
            return
        await i.response.defer(); self.remaining-=1; uid=self.user_id; u=get_user_cache(uid)
        kakuhen=kakuhen_data.get(uid,0)>0; streak=lose_streak.get(uid,0); daily_stats["gamble_count"]+=1
        # デイリーミッション & 統計
        add_daily_progress(uid, "slot_play")
        st = get_player_stats(uid); st["total_gamble"] = st.get("total_gamble", 0) + 1; st["total_slot"] = st.get("total_slot", 0) + 1
        if kakuhen: six_counter[uid]=six_counter.get(uid,0)+1
        force_six=False
        if not kakuhen:
            sc=six_counter.get(uid,0)
            if random.random()<sc*0.01: six_counter[uid]=0; force_six=random.random()<0.5
        sw=14 if kakuhen else 16
        if has_item(uid,"お祓い棒"): sw=max(1,sw-1)
        wl=[8,8,8,8,8,8,sw,5,8,8]
        sl=[6,6,6,6,6]+random.choices(range(10),k=2) if force_six else random.choices(range(10),weights=wl,k=7)
        reels=f" {''.join(map(str,sl))}"; counts={n:sl.count(n) for n in set(sl)}; max_match=max(counts.values()); reward=0
        bonuses=[]; bm={2:1.1,3:6,4:25,5:120,6:500,7:2000}
        if streak>=3:
            reward=BET*50; lose_streak[uid]=0; u["chips"]+=reward; bonuses.append(f" 天井発動！！ +{reward}チップ")
        elif max_match>=2:
            reward=int(BET*bm.get(max_match,0)); number=max(counts,key=counts.get)
            if max_match==2 and has_item(uid,"安牌なギャンブル"): reward+=500; bonuses.append(" 安牌なギャンブル発動！")
            if number==7:
                reward*=5; bonuses.append(" 7ボーナス！")
                if max_match>=3: kakuhen_data[uid]=7; bonuses.append(" 確変突入！！")
            elif number==6 and not kakuhen:
                if max_match>=5:
                    tc=u["chips"]
                    if has_item(uid,"悪魔的な報酬") and random.random()<0.25:
                        reward=tc*2; global_pool+=int(tc*0.03); economy_coin+=int(tc*0.07); u["chips"]=reward; use_item_once(uid,"悪魔的な報酬"); bonuses.append(f" 悪魔的な報酬発動！！ {reward}チップ獲得！")
                    else:
                        global_pool+=int(tc*0.03); economy_coin+=int(tc*0.07); u["chips"]=0; reward=0; bonuses.append(" 66666！！！全没収")
                else: reward=-int(BET*9); global_pool+=2700; economy_coin+=7300; bonuses.append(" 6ペナルティ！")
            if kakuhen:
                if max_match>=3 and number==6: kakuhen_data[uid]-=1; bonuses.append(" 確変減少")
                else: reward=int(reward*3); bonuses.append(" 確変倍率！")
                if counts.get(7,0)>=2: kakuhen_data[uid]+=1; bonuses.append(" 確変延長！")
            if kakuhen and sl==[7,7,7,7,7,7,7]: reward=BET*100000; bonuses.append(" 超JACKPOT！！！")
            if max_match>=5 and has_item(uid,"神がかり") and random.random()<0.75: reward=int(reward*2.5); bonuses.append(" 神がかり発動！")
            u["chips"]+=reward; economy_coin-=int(reward*0.1); lose_streak[uid]=0
        else: lose_streak[uid]=streak+1
        if kakuhen:
            kakuhen_data[uid]-=1
            if kakuhen_data[uid]<=0: bonuses.append(" 確変終了...")
        # 結果に応じてEmbed色を決定
        if reward>0: embed=embed_success(reels)
        elif reward<0 or (max_match>=5 and sl.count(6)>=5): embed=embed_error(reels)
        else: embed=embed_info(reels)
        if max_match>=2 and not (streak>=3):
            embed.add_field(name="結果",value=f"{max_match}揃い！ **{reward:+,}チップ**",inline=False)
        if bonuses:
            embed.add_field(name="ボーナス",value="\n".join(bonuses),inline=False)
        embed.add_field(name="残り回数",value=f"{self.remaining}/{self.max_spin}",inline=True)
        embed.add_field(name="現在所持",value=f"{u['chips']:,}チップ",inline=True)
        await i.edit_original_response(content=None,embed=embed,view=self)

@client.tree.command(name="slot7",description="超中毒7スロット（10〜1000回指定）")
@app_commands.describe(times="回数（10〜1000）")
async def slot7(i:Interaction,times:int):
    uid=str(i.user.id)
    if is_in_prison(uid):
        await i.response.send_message(embed=embed_error("プリズン中","プリズン状態中はギャンブルできません。"))
        return
    if times<10 or times>1000:
        await i.response.send_message(embed=embed_error("エラー","10〜1000回で指定してください。"))
        return
    await load_user(uid); u=get_user_cache(uid); total_cost=times*BET
    if u["chips"]<total_cost:
        await i.response.send_message(embed=embed_error("チップ不足",f"必要: **{total_cost:,}チップ** / 所持: **{u['chips']:,}チップ**"))
        return
    u["chips"]-=total_cost; view=Slot7View(uid,times)
    embed=embed_info(f" {times}回スロット開始",f"先払い: **{total_cost:,}チップ**\n現在所持: **{u['chips']:,}チップ**")
    await i.response.send_message(embed=embed,view=view)

@client.tree.command(name="dice",description="アンパンチップを賭けて数字当てゲームをします（最低10チップ）")
async def dice(i:Interaction,max:int,number:int,bet:int=10):
    global global_pool; uid=str(i.user.id)
    if is_in_prison(uid):
        await i.response.send_message(embed=embed_error("プリズン中","プリズン状態中はギャンブルできません。"))
        return
    if bet<10:
        await i.response.send_message(embed=embed_error("エラー","最低10チップから賭けられます。"))
        return
    if max<5 or max>10000 or number<1 or number>max:
        await i.response.send_message(embed=embed_error("エラー","無効な数字です。"))
        return
    await load_user(uid); u=get_user_cache(uid)
    if u["chips"]<bet:
        await i.response.send_message(embed=embed_error("チップ不足",f"所持: **{u['chips']:,}チップ**"))
        return
    u["chips"]-=bet; daily_stats["gamble_count"]+=1
    add_daily_progress(uid, "dice_play")
    st = get_player_stats(uid); st["total_gamble"] = st.get("total_gamble",0)+1; st["total_dice"] = st.get("total_dice",0)+1
    if number==rm:
        prize=bet*max; u["chips"]+=prize
        embed=embed_success(" ダイス — 当たり！")
        embed.add_field(name="予想",value=str(number),inline=True)
        embed.add_field(name="結果",value=str(rm),inline=True)
        embed.add_field(name="獲得",value=f"**+{prize:,}チップ**",inline=False)
    else:
        global_pool+=int(bet*0.3)
        embed=embed_error(" ダイス — はずれ")
        embed.add_field(name="予想",value=str(number),inline=True)
        embed.add_field(name="結果",value=str(rm),inline=True)
        embed.add_field(name="損失",value=f"**-{bet:,}チップ**",inline=False)
    await save_user(uid); await i.response.send_message(embed=embed)

@client.tree.command(name="steal",description="コインを持っているランダムなユーザーからコインを盗みます。")
async def steal(i:Interaction):
    uid=str(i.user.id)
    if is_in_prison(uid):
        await i.response.send_message(embed=embed_error("プリズン中","プリズン状態中はstealできません。"))
        return
    await load_user(uid); u=get_user_cache(uid)
    if u["coins"]<50:
        await i.response.send_message(embed=embed_error("エラー","コインが50枚以上必要です。"))
        return
    targets=[t for t,d in user_cache.items() if t!=uid and d["coins"]>=50]
    if not targets:
        await i.response.send_message(embed=embed_error("エラー","盗める相手がいません。"))
        return
    tid=random.choice(targets); tm=i.guild.get_member(int(tid)); tn=tm.display_name if tm else "謎のユーザー"
    td=user_cache[tid]; bonus_lines=[]

    # ====== 防御側の無効化判定 ======
    # ヘリオス優先: ヘリオスがあれば75%、なければ警棒50%を参照
    block_rate = 0.0
    use_helios = has_item(tid,"ヘリオス")
    use_baton  = has_item(tid,"警棒") and not use_helios

    if use_helios:
        block_rate = 0.75
    elif use_baton:
        block_rate = 0.50
    # 大警棒: +15%加算（ヘリオス・警棒どちらとも併用可）
    if has_item(tid,"大警棒"):
        block_rate += 0.15

    blocked = random.random() < block_rate

    if blocked:
        # 無効化発動 ------
        prison_min = 5/60
        if use_helios:
            prison_min = 7/60  # ヘリオスは7分プリズン
            use_item_once(tid,"ヘリオス")
        elif use_baton:
            use_item_once(tid,"警棒")  # 警棒は消耗品
        if has_item(tid,"大警棒"):
            prison_min = max(prison_min, 7/60)
            use_item_once(tid,"大警棒")
            # 大警棒: 無効化時に警棒を獲得
            give_item(tid,"警棒",1); bonus_lines.append(f"{tn} が大警棒発動！警棒を獲得した。")
        set_prison(uid, prison_min)

        # ヴァンパイア: 無効化時に攻撃側から奪う
        if has_item(tid,"ヴァンパイア"):
            vamp_coin = int(u["coins"] * 0.40)
            vamp_bread = int(u.get("bread_count",0) * 0.20)
            u["coins"] = max(0, u["coins"] - vamp_coin)
            u["bread_count"] = max(0, u.get("bread_count",0) - vamp_bread)
            td["coins"] += vamp_coin; td["bread_count"] = td.get("bread_count",0) + vamp_bread
            use_item_once(tid,"ヴァンパイア")
            bonus_lines.append(f"ヴァンパイア発動！{vamp_coin:,}コイン＋レアパン{vamp_bread}個を奪われた。")

        await save_user(uid); await save_user(tid)
        desc = f"**{tn}** に撃退された！{int(prison_min*60)}分間プリズン状態になりました。"
        if bonus_lines: desc += "\n" + "\n".join(bonus_lines)
        await i.response.send_message(embed=embed_error("steal失敗", desc))
        return

    # ====== 攻撃側の成功判定 ======
    # 基本成功率50%、大怪盗+10%
    success_rate = 0.50
    if has_item(uid,"大怪盗"): success_rate += 0.10
    # 大泥帽+15%
    if has_item(uid,"大泥帽"): success_rate += 0.15
    if has_item(uid,"フレイムスティーラー"): success_rate += 0.25

    success = random.random() < success_rate

    if success:
        gain = 50
        # 泥帽: 相手コインの10〜100%上乗せ＋チップ20%
        if has_item(uid,"泥帽"):
            bc = int(td["coins"] * random.uniform(0.1,1.0))
            bchip = int(td.get("chips",0) * 0.2)
            gain += bc; u["chips"] = u.get("chips",0) + bchip
            td["coins"] = max(0, td["coins"] - bc)
            use_item_once(uid,"泥帽")
            bonus_lines.append(f"泥帽発動！+{bc:,}コイン＋{bchip:,}チップ追加獲得")
        # 大泥帽: さらに相手レアパン25%上乗せ
        if has_item(uid,"大泥帽"):
            bp = int(td.get("bread_count",0) * 0.25)
            u["bread_count"] = u.get("bread_count",0) + bp
            td["bread_count"] = max(0, td.get("bread_count",0) - bp)
            use_item_once(uid,"大泥帽")
            bonus_lines.append(f"大泥帽発動！レアパン+{bp}個追加獲得")
        u["coins"] += gain; td["coins"] -= 50

        # フレイムスティーラー: steal成功時に完璧な器を獲得
        if has_item(uid,"フレイムスティーラー"):
            give_item(uid,"完璧な器",1)
            # 完璧な器が12個揃ったら発動
            vessel_count = u["items"].get("完璧な器",{}).get("count",0)
            if vessel_count >= 12:
                use_item_once(uid,"フレイムスティーラー")
                u["items"].pop("完璧な器",None)
                give_item(uid,"フレイムスティーラー",1)
                u["boxes"] = u.get("boxes",0) + 12
                bonus_lines.append("完璧な器が12個揃った！フレイムスティーラーと宝箱12個を獲得！")
            else:
                bonus_lines.append(f"フレイムスティーラー発動！完璧な器を獲得（{vessel_count}/12）")

        await save_user(uid); await save_user(tid)
        desc = f"**{tn}** から **{gain:,}コイン** 盗みました！"
        if bonus_lines: desc += "\n" + "\n".join(bonus_lines)
        # 統計・実績
        st = get_player_stats(uid); st["total_steal_success"] = st.get("total_steal_success",0)+1
        if st["total_steal_success"] >= 30:
            asyncio.create_task(check_and_grant_achievement(uid, "steal_30"))
        await i.response.send_message(embed=embed_success("steal成功", desc))
    else:
        # 失敗処理
        prison_on_fail = True
        if has_item(uid,"大怪盗"): prison_on_fail = False  # 大怪盗: 失敗時プリズンなし

        u["coins"] -= 50; td["coins"] += 50
        if has_item(uid,"泥帽"):
            if prison_on_fail: set_prison(uid, 6)
            use_item_once(uid,"泥帽")
        elif prison_on_fail:
            set_prison(uid, 5/60)

        # フレイムスティーラー: 失敗時消滅
        if has_item(uid,"フレイムスティーラー"):
            use_item_once(uid,"フレイムスティーラー")
            bonus_lines.append("フレイムスティーラーが消滅した...")

        await save_user(uid); await save_user(tid)
        desc = f"失敗し、**{tn}** にコイン **50枚** を渡しました..."
        if not prison_on_fail: desc += "\n大怪盗発動！プリズンを回避した。"
        if bonus_lines: desc += "\n" + "\n".join(bonus_lines)
        await i.response.send_message(embed=embed_error("steal失敗", desc))

@client.tree.command(name="exchange",description="レアパン・コイン・アンパンチップを交換します")
@discord.app_commands.choices(direction=[discord.app_commands.Choice(name="レアパン→コイン",value="to_coin"),discord.app_commands.Choice(name="コイン→レアパン",value="to_bread"),discord.app_commands.Choice(name="コイン→チップ（1コイン=9チップ）",value="coin_to_chip"),discord.app_commands.Choice(name="チップ→コイン（11チップ=1コイン）",value="chip_to_coin")])
async def exchange_cmd(i:Interaction,direction:discord.app_commands.Choice[str],amount:int):
    global global_pool,economy_coin
    if amount<=0:
        await i.response.send_message(embed=embed_error("エラー","1以上の数を指定してください"))
        return
    uid=str(i.user.id); await load_user(uid); u=get_user_cache(uid); rate,_=get_exchange_rate(); dv=direction.value
    if dv=="to_coin":
        if u["bread_count"]<amount:
            await i.response.send_message(embed=embed_error("レアパン不足",f"所持: **{u['bread_count']}個** / 必要: **{amount}個**"))
            return
        cg=round(amount*rate); u["bread_count"]-=amount; u["coins"]+=cg
        daily_stats["pan_to_coin"]+=1; daily_stats["coins_earned"]+=cg; await save_user(uid)
        # 大富豪実績チェック
        st = get_player_stats(uid); st["total_coins_earned"] = st.get("total_coins_earned",0)+cg
        if u["coins"] >= 10000000: asyncio.create_task(check_and_grant_achievement(uid, "coins_10m"))
        embed=embed_success(" 交換完了")
        embed.add_field(name="交換",value=f" **{amount}個** →  **{cg:,}枚**",inline=False)
        embed.add_field(name="レート",value=f"1レアパン = {rate}コイン",inline=True)
        await i.response.send_message(embed=embed)
    elif dv=="to_bread":
        cost=round(amount*rate)
        if u["coins"]<cost:
            await i.response.send_message(embed=embed_error("コイン不足",f"所持: **{u['coins']:,}枚** / 必要: **{cost:,}枚**"))
            return
        u["coins"]-=cost; u["bread_count"]+=amount; daily_stats["coin_to_pan"]+=1; await save_user(uid)
        embed=embed_success(" 交換完了")
        embed.add_field(name="交換",value=f" **{cost:,}枚** →  **{amount}個**",inline=False)
        embed.add_field(name="レート",value=f"1レアパン = {rate}コイン",inline=True)
        await i.response.send_message(embed=embed)
    elif dv=="coin_to_chip":
        if u["coins"]<amount:
            await i.response.send_message(embed=embed_error("コイン不足",f"所持: **{u['coins']:,}枚** / 必要: **{amount:,}枚**"))
            return
        cg=amount*COIN_TO_CHIP; u["coins"]-=amount; u["chips"]+=cg
        global_pool+=int(amount*0.3); economy_coin+=int(amount*0.7); await save_user(uid)
        embed=embed_success(" 交換完了")
        embed.add_field(name="交換",value=f" **{amount:,}枚** →  **{cg:,}チップ**",inline=False)
        await i.response.send_message(embed=embed)
    elif dv=="chip_to_coin":
        if u["chips"]<amount:
            await i.response.send_message(embed=embed_error("チップ不足",f"所持: **{u['chips']:,}チップ** / 必要: **{amount:,}チップ**"))
            return
        if amount<CHIP_TO_COIN:
            await i.response.send_message(embed=embed_error("エラー",f"チップ→コインは最低 **{CHIP_TO_COIN}チップ** から交換できます。"))
            return
        cg=amount//CHIP_TO_COIN; cu=cg*CHIP_TO_COIN; u["chips"]-=cu; u["coins"]+=cg
        global_pool+=int(amount*0.03); economy_coin+=int(amount*0.07); daily_stats["coins_earned"]+=cg; await save_user(uid)
        embed=embed_success(" 交換完了")
        embed.add_field(name="交換",value=f" **{cu:,}チップ** →  **{cg:,}枚**",inline=False)
        await i.response.send_message(embed=embed)

@client.tree.command(name="open",description="所持している宝箱を全部開けます")
async def open_treasure(i:Interaction):
    global economy_coin; await i.response.defer(); uid=str(i.user.id); await load_user(uid); u=get_user_cache(uid)
    if u["boxes"]<=0:
        await i.followup.send(embed=embed_error("エラー","宝箱を持っていません。"))
        return
    boxes=u["boxes"]; u["boxes"]=0; total_coins=0; got_sake=0; got_hesokuri=0; got_items={}
    normal_item_pool = [name for name in ITEMS if name not in UNCRAFTABLE_ITEMS and name not in BOX_NEVER_DROP]
    # ゴールドラッシュ: 宝箱1個あたり基礎コイン+1000
    gold_rush_bonus = 1000 if has_item(uid,"ゴールドラッシュ") else 0
    # オープンスレイヤー: 宝箱開封のたびに25%で追加1個、初回発動で消滅
    open_slayer_active = has_item(uid,"オープンスレイヤー")
    open_slayer_fired = False
    extra_boxes = 0
    box_idx = 0
    while box_idx < boxes + extra_boxes:
        box_idx += 1
        c = random.randint(BOX_DROP_RATES["coin_min"], BOX_DROP_RATES["coin_max"]) + gold_rush_bonus
        total_coins += c; economy_coin -= c
        if open_slayer_active and not open_slayer_fired and random.random() < 0.25:
            extra_boxes += 1; open_slayer_fired = True
            use_item_once(uid,"オープンスレイヤー"); open_slayer_active = False
            got_items["オープンスレイヤー(追加宝箱)"] = got_items.get("オープンスレイヤー(追加宝箱)",0) + 1
        if random.random() < BOX_DROP_RATES["sake"]: got_sake += 1
        if random.random() < BOX_DROP_RATES["hesokuri"]: got_hesokuri += 1
        item_dropped = False
        if not item_dropped and random.random() < BOX_DROP_RATES["uncraftable"]:
            drop_name = random.choice(list(BOX_DROP_UNCRAFTABLE))
            give_item(uid, drop_name, 1); got_items[drop_name] = got_items.get(drop_name, 0) + 1; item_dropped = True
        if not item_dropped and normal_item_pool:
            if random.random() < BOX_DROP_RATES["normal_item"]:
                drop_name = random.choice(normal_item_pool)
                give_item(uid, drop_name, 1); got_items[drop_name] = got_items.get(drop_name, 0) + 1; item_dropped = True
        if not item_dropped:
            for on, rate_key in [("ブロンズ","oven_ブロンズ"),("シルバー","oven_シルバー"),("ゴールド","oven_ゴールド"),("プリズム","oven_プリズム")]:
                if f"焼き釜_{on}" in BOX_NEVER_DROP: continue
                if random.random() < BOX_DROP_RATES[rate_key]:
                    give_item(uid, f"焼き釜_{on}", 1); got_items[f"焼き釜_{on}"] = got_items.get(f"焼き釜_{on}", 0) + 1; item_dropped = True; break
    total_opened = boxes + extra_boxes
    u["coins"] += total_coins; u["sake"] = u.get("sake",0) + got_sake
    u["hesokuri"] = u.get("hesokuri",0) + got_hesokuri
    daily_stats["coins_earned"] += total_coins; await save_user(uid)
    embed=embed_success(f"宝箱 x{total_opened} 開封結果")
    result_lines=f"コイン: **{total_coins:,}枚**"
    if gold_rush_bonus: result_lines += f"（ゴールドラッシュ+{gold_rush_bonus*total_opened:,}含む）"
    result_lines += f"\n酒: **{got_sake}個**\nへそくり: **{got_hesokuri}個**"
    for k,v in got_items.items(): result_lines+=f"\n**{k}**: {v}個"
    embed.description=result_lines
    embed.add_field(name="所持コイン",value=f"**{u['coins']:,}枚**",inline=True)
    await i.followup.send(embed=embed)

class DoubleView(discord.ui.View):
    def __init__(self,uid): super().__init__(timeout=60); self.user_id=uid
    async def interaction_check(self,i): return str(i.user.id)==self.user_id
    def make_status_embed(self, title=" ダブルゲーム", color=None):
        if self.user_id in double_game:
            g=double_game[self.user_id]; bet=g["bet"]; cv=int(bet*g["multiplier"]); profit=cv-bet
        else: bet=cv=profit=0
        e=discord.Embed(title=title, color=color or COLOR_INFO)
        e.add_field(name="BET",value=f"**{bet:,}**",inline=True)
        e.add_field(name="現在価値",value=f"**{cv:,}**",inline=True)
        e.add_field(name="純利益",value=f"**{profit:+,}**",inline=True)
        e.add_field(name="プール",value=f"{global_pool:,}",inline=True)
        return e
    @discord.ui.button(label="GO",style=discord.ButtonStyle.green)
    async def go_button(self,i:discord.Interaction,b:discord.ui.Button):
        global global_pool,economy_coin; uid=self.user_id
        if is_in_prison(uid):
            await i.response.send_message(embed=embed_error("プリズン中","プリズン状態中はギャンブルできません。"),ephemeral=True)
            return
        if uid not in double_game:
            await i.response.edit_message(embed=self.make_status_embed("ゲーム終了",COLOR_ERROR),view=None)
            return
        g=double_game[uid]; u=get_user_cache(uid); win=random.random()<get_internal_rate(uid); daily_stats["gamble_count"]+=1
        add_daily_progress(uid, "double_play")
        st = get_player_stats(uid); st["total_gamble"] = st.get("total_gamble",0)+1; st["total_double"] = st.get("total_double",0)+1
        if win:
            g["streak"]+=1; g["multiplier"]*=1.9; win_streak[uid]=win_streak.get(uid,0)+1; lose_streak[uid]=0
            if internal_mode.get(uid)=="CHARGE": internal_mode[uid]="FEVER"
            if internal_mode.get(uid)=="FEVER" and win_streak[uid]>=3: internal_mode[uid]="NORMAL"; win_streak[uid]=0
            embed=self.make_status_embed(f" 成功！倍率 {g['multiplier']:.2f}x", COLOR_SUCCESS)
            await i.response.edit_message(embed=embed,view=self)
        else:
            lose_streak[uid]=lose_streak.get(uid,0)+1; win_streak[uid]=0
            if has_item(uid,"やっぱナシ"):
                loss=int(g["bet"]*0.9); global_pool+=int(loss*0.3); economy_coin+=int(loss*0.7); del double_game[uid]; self.stop(); use_item_once(uid,"やっぱナシ")
                embed=self.make_status_embed(" 失敗…（やっぱナシ発動！損失10%軽減）",COLOR_ERROR)
                await i.response.edit_message(embed=embed,view=None)
            else:
                global_pool+=int(g["bet"]*0.3); economy_coin+=int(g["bet"]*0.7)
                if lose_streak[uid]>=6: internal_mode[uid]="CHARGE"
                elif lose_streak[uid]>=3: internal_mode[uid]="HELL"
                del double_game[uid]; self.stop()
                embed=self.make_status_embed(" 失敗…",COLOR_ERROR)
                await i.response.edit_message(embed=embed,view=None)
    @discord.ui.button(label="CASHOUT",style=discord.ButtonStyle.red)
    async def cashout_button(self,i:discord.Interaction,b:discord.ui.Button):
        global economy_coin; uid=self.user_id
        if uid not in double_game:
            await i.response.edit_message(embed=self.make_status_embed("ゲーム終了",COLOR_ERROR),view=None)
            return
        g=double_game[uid]; payout=int(g["bet"]*g["multiplier"]); get_user_cache(uid)["coins"]+=payout; economy_coin-=payout; del double_game[uid]
        if payout>500: internal_mode[uid]="HELL"
        self.stop(); await save_user(uid)
        embed=self.make_status_embed(f" 確定！{payout:,}コイン獲得！",COLOR_SUCCESS)
        await i.response.edit_message(embed=embed,view=None)

@client.tree.command(name="double",description="ダブルゲーム開始")
async def double(i:discord.Interaction,bet:int):
    uid=str(i.user.id)
    if is_in_prison(uid):
        await i.response.send_message(embed=embed_error("プリズン中","プリズン状態中はギャンブルできません。"))
        return
    if bet<=0:
        await i.response.send_message(embed=embed_error("エラー","BETは1以上にしてください"))
        return
    await load_user(uid); u=get_user_cache(uid)
    if u["coins"]<bet:
        await i.response.send_message(embed=embed_error("コイン不足",f"所持: **{u['coins']:,}枚** / 必要: **{bet:,}枚**"))
        return
    u["coins"]-=bet; double_game[uid]={"bet":bet,"multiplier":1.0,"streak":0}
    view=DoubleView(uid)
    embed=embed_info(" ダブルゲーム開始",f"BET: **{bet:,}コイン**")
    await i.response.send_message(embed=embed,view=view)

def draw_card(): return random.choice([1,2,3,4,5,6,7,8,9,10,10,10,10])
def calc_total(hand):
    total=sum(hand)
    while total>21 and 11 in hand: hand[hand.index(11)]=1; total=sum(hand)
    return total

class BlackjackView(discord.ui.View):
    def __init__(self,uid,bet):
        super().__init__(timeout=60); self.user_id=uid; self.bet=bet; self.player=[draw_card(),draw_card()]; self.dealer=[draw_card(),draw_card()]
    async def interaction_check(self,i): return str(i.user.id)==str(self.user_id)
    @discord.ui.button(label="ヒット",style=discord.ButtonStyle.green)
    async def hit(self,i:discord.Interaction,b:discord.ui.Button):
        self.player.append(draw_card()); total=calc_total(self.player)
        if total>21:
            self.stop()
            embed=embed_error(" ブラックジャック — バースト！")
            embed.add_field(name="あなた",value=f"{self.player} ({total})",inline=False)
            embed.add_field(name="結果",value=f"-{self.bet:,}コイン",inline=False)
            await i.response.edit_message(embed=embed,view=None)
        else:
            embed=embed_info(" ブラックジャック")
            embed.add_field(name="あなた",value=f"{self.player} ({total})",inline=False)
            embed.add_field(name="ディーラー",value=f"{self.dealer[0]} ?",inline=False)
            await i.response.edit_message(embed=embed,view=self)
    @discord.ui.button(label="スタンド",style=discord.ButtonStyle.red)
    async def stand(self,i:discord.Interaction,b:discord.ui.Button):
        global global_pool,economy_coin; uid=str(i.user.id)
        while calc_total(self.dealer)<17: self.dealer.append(draw_card())
        pt=calc_total(self.player); dt=calc_total(self.dealer); u=get_user_cache(uid); daily_stats["gamble_count"]+=1
        if dt>21 or pt>dt:
            result=f"+{self.bet:,}コイン"; u["coins"]+=self.bet*2; economy_coin-=self.bet
            embed=embed_success(" ブラックジャック — 勝ち！")
        elif pt<dt:
            result=f"-{self.bet:,}コイン"; global_pool+=int(self.bet*0.3); economy_coin+=int(self.bet*0.7)
            embed=embed_error(" ブラックジャック — 負け")
        else:
            result="引き分け（返却）"; u["coins"]+=self.bet
            embed=embed_info(" ブラックジャック — 引き分け")
        self.stop(); await save_user(uid)
        embed.add_field(name="あなた",value=f"{self.player} ({pt})",inline=True)
        embed.add_field(name="ディーラー",value=f"{self.dealer} ({dt})",inline=True)
        embed.add_field(name="結果",value=result,inline=False)
        await i.response.edit_message(embed=embed,view=None)

@client.tree.command(name="blackjack",description="ブラックジャックで遊ぶ")
@app_commands.describe(bet="賭けるコイン枚数")
async def blackjack(i:discord.Interaction,bet:int):
    uid=str(i.user.id)
    if is_in_prison(uid):
        await i.response.send_message(embed=embed_error("プリズン中","プリズン状態中はギャンブルできません。"),ephemeral=True)
        return
    if bet<10:
        await i.response.send_message(embed=embed_error("エラー","10以上を入力してください"),ephemeral=True)
        return
    await load_user(uid); u=get_user_cache(uid)
    if bet>u["coins"]:
        await i.response.send_message(embed=embed_error("コイン不足","所持金が不足しています"),ephemeral=True)
        return
    u["coins"]-=bet; view=BlackjackView(uid,bet); total=calc_total(view.player)
    embed=embed_info(" ブラックジャック開始")
    embed.add_field(name="あなた",value=f"{view.player} ({total})",inline=False)
    embed.add_field(name="ディーラー",value=f"{view.dealer[0]} ?",inline=False)
    await i.response.send_message(embed=embed,view=view)

class JoinView(discord.ui.View):
    def __init__(self,creator,bet): super().__init__(timeout=60); self.creator=creator; self.bet=bet
    @discord.ui.button(label="参加する",style=discord.ButtonStyle.green)
    async def join(self,i:Interaction,b:discord.ui.Button):
        if i.user.id==self.creator.id:
            await i.response.send_message(embed=embed_error("エラー","自分とは対戦できません。"),ephemeral=True)
            return
        uid=str(i.user.id); await load_user(uid)
        if get_chips(uid)<self.bet:
            await i.response.send_message(embed=embed_error("チップ不足",f"必要: **{self.bet:,}チップ**"),ephemeral=True)
            return
        subtract_chips(uid,self.bet); did=str(self.creator.id)
        active_duels[did]={"p1":self.creator,"p2":i.user,"bet":self.bet,"hands":{str(self.creator.id):[draw_card(),draw_card()],str(i.user.id):[draw_card(),draw_card()]},"stand":[]}
        view=DuelView(did)
        embed=embed_info(f" BJ対戦開始！",f"{self.creator.mention} vs {i.user.mention}")
        d=active_duels[did]
        embed.add_field(name=self.creator.display_name,value=str(d["hands"][str(self.creator.id)]),inline=True)
        embed.add_field(name=i.user.display_name,value=str(d["hands"][str(i.user.id)]),inline=True)
        await i.response.edit_message(embed=embed,view=view)

class DuelView(discord.ui.View):
    def __init__(self,did): super().__init__(timeout=120); self.duel_id=did
    async def interaction_check(self,i): return i.user in [active_duels[self.duel_id]["p1"],active_duels[self.duel_id]["p2"]]
    def status_embed(self, title=" BJ対戦", color=None):
        d=active_duels[self.duel_id]; p1,p2=d["p1"],d["p2"]; h1=d["hands"][str(p1.id)]; h2=d["hands"][str(p2.id)]
        e=discord.Embed(title=title, color=color or COLOR_INFO)
        e.add_field(name=p1.display_name,value=f"{h1} ({calc_total(h1)})",inline=True)
        e.add_field(name=p2.display_name,value=f"{h2} ({calc_total(h2)})",inline=True)
        return e
    @discord.ui.button(label="Hit",style=discord.ButtonStyle.green)
    async def hit(self,i:Interaction,b):
        d=active_duels[self.duel_id]; uid=str(i.user.id); d["hands"][uid].append(draw_card())
        if calc_total(d["hands"][uid])>21:
            winner=d["p1"] if i.user!=d["p1"] else d["p2"]; await self.end_game(i,winner,"バースト！")
            return
        await i.response.edit_message(embed=self.status_embed(),view=self)
    @discord.ui.button(label="Stand",style=discord.ButtonStyle.red)
    async def stand(self,i:Interaction,b):
        d=active_duels[self.duel_id]; d["stand"].append(i.user.id)
        if len(d["stand"])==2: await self.judge(i)
        else: await i.response.send_message(embed=embed_info("Stand","Standしました。相手の行動を待っています。"),ephemeral=True)
    async def judge(self,i):
        d=active_duels[self.duel_id]; p1,p2=d["p1"],d["p2"]; v1=calc_total(d["hands"][str(p1.id)]); v2=calc_total(d["hands"][str(p2.id)])
        if v1>v2: winner=p1
        elif v2>v1: winner=p2
        else: winner=None
        if winner:
            payout=int(d["bet"]*2*0.95); add_chips(str(winner.id),payout); await save_user(str(winner.id))
            embed=self.status_embed(f" {winner.display_name} の勝利！",COLOR_SUCCESS)
            embed.add_field(name="獲得",value=f"**+{payout:,}チップ**",inline=False)
        else:
            add_chips(str(p1.id),d["bet"]); add_chips(str(p2.id),d["bet"]); await save_user(str(p1.id)); await save_user(str(p2.id))
            embed=self.status_embed(" 引き分け（チップ返却）",COLOR_INFO)
        await i.response.edit_message(embed=embed,view=None); del active_duels[self.duel_id]
    async def end_game(self,i,winner,reason):
        d=active_duels[self.duel_id]; payout=int(d["bet"]*2*0.95); add_chips(str(winner.id),payout); await save_user(str(winner.id))
        embed=self.status_embed(f" {reason} — {winner.display_name} の勝利！",COLOR_SUCCESS)
        embed.add_field(name="獲得",value=f"**+{payout:,}チップ**",inline=False)
        await i.response.edit_message(embed=embed,view=None); del active_duels[self.duel_id]

@client.tree.command(name="bj_duel",description="プレイヤー対戦ブラックジャック（チップ使用・最低500チップ）")
async def bj_duel(i:Interaction,bet:int):
    uid=str(i.user.id)
    if is_in_prison(uid):
        await i.response.send_message(embed=embed_error("プリズン中","プリズン状態中はギャンブルできません。"))
        return
    if bet<500:
        await i.response.send_message(embed=embed_error("エラー","最低ベットは500チップです。"))
        return
    await load_user(uid)
    if get_chips(uid)<bet:
        await i.response.send_message(embed=embed_error("チップ不足",f"所持: **{get_chips(uid):,}チップ**"))
        return
    subtract_chips(uid,bet)
    embed=embed_info(" BJ対戦募集中",f"ベット: **{bet:,}チップ**\n参加者募集中...")
    await i.response.send_message(embed=embed,view=JoinView(i.user,bet))

class MiningView(View):
    def __init__(self,uid):
        super().__init__(timeout=60); self.user_id=uid; base=random.randint(1,20)
        if has_item(uid,"大規模採掘"): base+=1
        self.mining_count=0; self.max_mining=base; self.message=None
    @discord.ui.button(label="Mine ",style=discord.ButtonStyle.green)
    async def mine_button(self,i:Interaction,b:Button):
        global global_pool,economy_coin; uid=self.user_id
        if i.user.id!=int(uid):
            await i.response.send_message(embed=embed_error("エラー","あなたは操作できません"),ephemeral=True)
            return
        if self.mining_count>=self.max_mining:
            await i.response.send_message(embed=embed_error("エラー","もう採掘できません"),ephemeral=True)
            return
        if global_pool<=0:
            await i.response.send_message(embed=embed_error("エラー","プールにコインがありません…"),ephemeral=True)
            return
        base=random.randint(10,500)
        if has_item(uid,"プリズンマイナー"): base+=1000
        if has_item(uid,"落盤対策"): mined=base
        else: mined=base if random.random()<0.8 else 0
        if has_item(uid,"直下掘り") and random.random()<0.9: mined=0
        extra=0; le=False; lc=0.1
        if has_item(uid,"プリズンマイナー"): lc+=0.05
        if has_item(uid,"直下掘り"): lc+=0.50
        if random.random()<lc: extra=max(1,int(global_pool*random.uniform(0.01,0.1))); mined+=extra; le=True
        mined=min(mined,global_pool); global_pool-=mined; economy_coin-=mined; get_user_cache(uid)["coins"]+=mined; daily_stats["coins_earned"]+=mined; self.mining_count+=1; await save_user(uid)
        if mined>0:
            embed=embed_success(" 採掘成功",f"**{mined:,}コイン** を採掘しました！")
        else:
            embed=embed_error(" 採掘失敗"," 採掘に失敗しました…")
        if le: embed.add_field(name=" 大量採掘ボーナス！",value=f"+{extra:,}コイン",inline=False)
        embed.add_field(name="所持コイン",value=f"{get_user_cache(uid)['coins']:,}",inline=True)
        embed.add_field(name="残りプール",value=f"{global_pool:,}",inline=True)
        embed.set_footer(text=f"{self.mining_count}/{self.max_mining}回採掘済み")
        await self.message.edit(embed=embed,view=self)
        if self.mining_count>=self.max_mining or global_pool<=0:
            for c in self.children: c.disabled=True
            await self.message.edit(view=self)

@client.tree.command(name="mining",description="コインを採掘します")
async def mining_cmd(i:Interaction):
    uid=str(i.user.id); now=asyncio.get_event_loop().time()
    if uid in mining_ct and now-mining_ct[uid]<MINING_COOLDOWN:
        await i.response.send_message(embed=embed_error("クールタイム中",f"残り **{int(MINING_COOLDOWN-(now-mining_ct[uid]))}秒**"),ephemeral=True)
        return
    if global_pool<=0:
        await i.response.send_message(embed=embed_error("エラー","プールにコインがありません…"),ephemeral=True)
        return
    await load_user(uid); view=MiningView(uid)
    embed=embed_info(" コイン採掘","下のボタンを押して採掘します！\n最大20回まで採掘可能")
    await i.response.send_message(embed=embed,view=view); view.message=await i.original_response(); mining_ct[uid]=now

async def knead_with_oven_task(user,channel,minutes,progress_interval=5,oven_name="ブロンズ"):
    global bcount,global_pool,economy_coin; uid=str(user.id); await load_user(uid); u=get_user_cache(uid)
    total_seconds=minutes*60; interval=60; progress_seconds=progress_interval*60; elapsed=0; next_progress=progress_seconds; cumulative_pool=0
    oi=OVEN_TYPES.get(oven_name,(5,1,0)); bpm=oi[1]; box_pm=oi[2]
    try:
        while elapsed<total_seconds:
            await asyncio.sleep(interval); elapsed+=interval; bcount+=1; daily_stats["pan_count"]+=1
            gain=random.randint(1,50) if bpm is None else bpm; u["bread_count"]+=gain
            # デイリーミッション進捗（1分ごとにパンこね）
            add_daily_progress(uid, "knead_rare", gain)
            # 統計
            st = get_player_stats(uid); st["total_bread"] = st.get("total_bread",0)+gain
            # パン1000個実績チェック
            if st["total_bread"] >= 1000:
                asyncio.create_task(check_and_grant_achievement(uid, "bread_1000"))
            if box_pm>0: u["boxes"]+=box_pm
            scale=random.randint(1,10); global_pool+=scale; economy_coin-=scale; cumulative_pool+=scale
            if elapsed>=next_progress or elapsed>=total_seconds:
                embed=embed_info(f" {oven_name}焼き釜 進捗",f"{user.mention}")
                embed.add_field(name="経過時間",value=f"{elapsed//60}分",inline=True)
                embed.add_field(name="パン獲得",value=f"+{gain}枚",inline=True)
                embed.add_field(name="プール増加",value=f"{cumulative_pool}コイン",inline=True)
                await channel.send(embed=embed); next_progress+=progress_seconds
    finally:
        await save_user(uid)
        await channel.send(embed=embed_success(f" {oven_name}焼き釜 終了",f"{user.mention} の焼き釜の時間が終了しました！"))
        active_kneads.pop(uid,None)

def generate_team_code(): return ''.join(random.choices(string.ascii_letters+string.digits,k=6))

async def get_team_by_owner(oid):
    try: res=supabase.table("teams").select("*").eq("owner_id",oid).execute(); return res.data[0] if res.data else None
    except: return None

async def get_team_by_id(tid):
    try: res=supabase.table("teams").select("*").eq("team_id",tid).execute(); return res.data[0] if res.data else None
    except: return None

async def get_member_team(uid):
    try: res=supabase.table("team_members").select("*").eq("user_id",uid).execute(); return res.data[0] if res.data else None
    except: return None

async def get_team_members(tid):
    try: return supabase.table("team_members").select("*").eq("team_id",tid).execute().data
    except: return []

async def get_team_total_coins(tid):
    members=await get_team_members(tid); total=0
    for m in members: await load_user(m["user_id"]); total+=get_user_cache(m["user_id"])["coins"]
    return total

async def is_banned(uid):
    m=await get_member_team(uid)
    if m and m.get("ban_until"):
        try:
            bu=datetime.datetime.fromisoformat(m["ban_until"])
            if datetime.datetime.now(JST)<(bu.replace(tzinfo=JST) if bu.tzinfo is None else bu): return True,bu
        except: pass
    return False,None

@client.tree.command(name="make_team",description="チームを作成します（10万コイン消費）")
@app_commands.describe(name="チーム名")
async def make_team(i:Interaction,name:str):
    uid=str(i.user.id); await load_user(uid); u=get_user_cache(uid); existing=await get_member_team(uid)
    if existing and existing.get("team_id"):
        await i.response.send_message(embed=embed_error("エラー","すでにチームに所属しています。先に `/team leave` で脱退してください。"))
        return
    if u["coins"]<TEAM_CREATE_COST:
        await i.response.send_message(embed=embed_error("コイン不足",f"所持: **{u['coins']:,}枚** / 必要: **{TEAM_CREATE_COST:,}枚**"))
        return
    tid=generate_team_code(); u["coins"]-=TEAM_CREATE_COST; await save_user(uid)
    try:
        supabase.table("teams").insert({"team_id":tid,"name":name,"owner_id":uid,"bonus_date":""}).execute()
        supabase.table("team_members").upsert({"user_id":uid,"team_id":tid,"ban_until":""}).execute()
    except Exception as e:
        await i.response.send_message(embed=embed_error("エラー",f"チーム作成失敗: {e}"))
        return
    embed=embed_success(" チーム作成完了")
    embed.add_field(name="チーム名",value=f"**{name}**",inline=True)
    embed.add_field(name="チームID",value=f"`{tid}`",inline=True)
    embed.add_field(name="消費コイン",value=f"**{TEAM_CREATE_COST:,}枚**",inline=True)
    embed.set_footer(text="メンバーを招待するには /team join で招待コードを発行してください")
    await i.response.send_message(embed=embed)

team_group=app_commands.Group(name="team",description="チーム関連コマンド")

@team_group.command(name="join",description="チームに参加する / 招待コードを発行する")
@app_commands.describe(code="参加コード（省略すると招待コードを発行します）")
async def team_join(i:Interaction,code:str=None):
    uid=str(i.user.id); banned,bu=await is_banned(uid)
    if banned:
        await i.response.send_message(embed=embed_error("参加制限",f"チームへの参加は **{bu.strftime('%Y/%m/%d')}** まで制限されています。"))
        return
    if code is None:
        team=await get_team_by_owner(uid)
        if not team:
            await i.response.send_message(embed=embed_error("エラー","あなたはチームのオーナーではありません。"))
            return
        members=await get_team_members(team["team_id"])
        if len(members)>=TEAM_MAX_MEMBERS:
            await i.response.send_message(embed=embed_error("満員",f"メンバーが上限（{TEAM_MAX_MEMBERS}人）に達しています。"))
            return
        embed=embed_info(" 招待コード発行",f"チーム **{team['name']}** の招待コード:\n# `{team['team_id']}`\n参加したい人は `/team join {team['team_id']}` と入力してください。")
        await i.response.send_message(embed=embed)
        return
    existing=await get_member_team(uid)
    if existing and existing.get("team_id"):
        await i.response.send_message(embed=embed_error("エラー","すでにチームに所属しています。先に `/team leave` で脱退してください。"))
        return
    team=await get_team_by_id(code)
    if not team:
        await i.response.send_message(embed=embed_error("エラー","無効なコードです。"))
        return
    members=await get_team_members(team["team_id"])
    if len(members)>=TEAM_MAX_MEMBERS:
        await i.response.send_message(embed=embed_error("満員",f"このチームは満員です（上限{TEAM_MAX_MEMBERS}人）。"))
        return
    try: supabase.table("team_members").upsert({"user_id":uid,"team_id":team["team_id"],"ban_until":""}).execute()
    except Exception as e:
        await i.response.send_message(embed=embed_error("エラー",f"参加失敗: {e}"))
        return
    await i.response.send_message(embed=embed_success(" チーム参加完了",f"チーム **{team['name']}** に参加しました！"))

@team_group.command(name="name",description="チーム名を変更します（オーナーのみ・10,000コイン）")
@app_commands.describe(new_name="新しいチーム名")
async def team_rename(i:Interaction,new_name:str):
    uid=str(i.user.id); team=await get_team_by_owner(uid)
    if not team:
        await i.response.send_message(embed=embed_error("エラー","あなたはチームのオーナーではありません。"))
        return
    await load_user(uid); u=get_user_cache(uid)
    if u["coins"]<TEAM_RENAME_COST:
        await i.response.send_message(embed=embed_error("コイン不足",f"所持: **{u['coins']:,}枚** / 必要: **{TEAM_RENAME_COST:,}枚**"))
        return
    old_name=team["name"]; u["coins"]-=TEAM_RENAME_COST
    try: supabase.table("teams").update({"name":new_name}).eq("team_id",team["team_id"]).execute()
    except Exception as e:
        await i.response.send_message(embed=embed_error("エラー",f"チーム名変更失敗: {e}"))
        return
    await save_user(uid)
    embed=embed_success("️ チーム名変更完了",f"**{old_name}** → **{new_name}**\n消費コイン: **{TEAM_RENAME_COST:,}枚**")
    await i.response.send_message(embed=embed)

@team_group.command(name="status",description="チームの状態を確認します")
async def team_status(i:Interaction):
    uid=str(i.user.id); mr=await get_member_team(uid)
    if not mr or not mr.get("team_id"):
        await i.response.send_message(embed=embed_error("エラー","チームに所属していません。"))
        return
    await i.response.defer(); team=await get_team_by_id(mr["team_id"])
    if not team:
        await i.followup.send(embed=embed_error("エラー","チームデータが見つかりません。"))
        return
    members=await get_team_members(team["team_id"]); tc=await get_team_total_coins(team["team_id"])
    created_at=datetime.datetime.fromisoformat(team["created_at"]); days=(datetime.datetime.now(JST)-created_at.astimezone(JST)).days
    try:
        all_teams=supabase.table("teams").select("team_id").execute().data; tcs=[]
        for t in all_teams: tcs.append((t["team_id"],await get_team_total_coins(t["team_id"])))
        tcs.sort(key=lambda x:x[1],reverse=True); rank=next((idx+1 for idx,(tid,_) in enumerate(tcs) if tid==team["team_id"]),"?")
    except: rank="?"
    mnames=[]
    for m in members:
        mem=i.guild.get_member(int(m["user_id"])); name=mem.display_name if mem else f"ID:{m['user_id']}"
        mnames.append(f"{'' if m['user_id']==team['owner_id'] else '　'} {name}")
    embed=embed_info(f" {team['name']}")
    embed.add_field(name=" 総資産",value=f"**{tc:,}コイン**",inline=True)
    embed.add_field(name=" ランキング",value=f"**{rank}位**",inline=True)
    embed.add_field(name=" 結成日数",value=f"**{days}日**",inline=True)
    embed.add_field(name=f" メンバー ({len(members)}/{TEAM_MAX_MEMBERS})",value="\n".join(mnames) or "なし",inline=False)
    await i.followup.send(embed=embed)

@team_group.command(name="bonus",description="チームボーナス宝箱を獲得します（1日1回）")
async def team_bonus(i:Interaction):
    uid=str(i.user.id); mr=await get_member_team(uid)
    if not mr or not mr.get("team_id"):
        await i.response.send_message(embed=embed_error("エラー","チームに所属していません。"))
        return
    team=await get_team_by_id(mr["team_id"])
    if not team:
        await i.response.send_message(embed=embed_error("エラー","チームデータが見つかりません。"))
        return
    ts=datetime.datetime.now(JST).strftime("%Y-%m-%d")
    if team.get("bonus_date")==ts:
        await i.response.send_message(embed=embed_error("受取済み","今日はすでにチームボーナスを受け取っています。明日また来てください！"))
        return
    tc=await get_team_total_coins(team["team_id"])
    boxes=1 if tc<100000 else 2 if tc<500000 else 3 if tc<1000000 else 4 if tc<2000000 else 5 if tc<5000000 else 6
    await load_user(uid); u=get_user_cache(uid); u["boxes"]+=boxes; await save_user(uid)
    try: supabase.table("teams").update({"bonus_date":ts}).eq("team_id",team["team_id"]).execute()
    except Exception as e:
        await i.response.send_message(embed=embed_error("エラー",f"更新失敗: {e}"))
        return
    embed=embed_success(" チームボーナス獲得！")
    embed.add_field(name="チーム総資産",value=f"**{tc:,}コイン**",inline=True)
    embed.add_field(name="獲得宝箱",value=f"**{boxes}個** ",inline=True)
    embed.set_footer(text="/open で宝箱を開けられます！")
    await i.response.send_message(embed=embed)

@team_group.command(name="leave",description="チームから脱退します（5日間参加不可）")
async def team_leave(i:Interaction):
    uid=str(i.user.id); mr=await get_member_team(uid)
    if not mr or not mr.get("team_id"):
        await i.response.send_message(embed=embed_error("エラー","チームに所属していません。"))
        return
    team=await get_team_by_id(mr["team_id"])
    if team and team["owner_id"]==uid:
        await i.response.send_message(embed=embed_error("エラー","オーナーは脱退できません。チームを解散するには `/team disband` を使ってください。"))
        return
    bu=(datetime.datetime.now(JST)+datetime.timedelta(days=TEAM_BAN_LEAVE_DAYS)).isoformat()
    try: supabase.table("team_members").update({"team_id":None,"ban_until":bu}).eq("user_id",uid).execute()
    except Exception as e:
        await i.response.send_message(embed=embed_error("エラー",f"脱退失敗: {e}"))
        return
    embed=embed_info(" チーム脱退",f"チーム **{team['name']}** から脱退しました。\n次のチームに参加できるのは **{TEAM_BAN_LEAVE_DAYS}日後** です。")
    await i.response.send_message(embed=embed)

@team_group.command(name="member_delete",description="メンバーをチームから削除します（オーナーのみ）")
@app_commands.describe(member="削除するメンバー")
async def team_member_delete(i:Interaction,member:discord.Member):
    uid=str(i.user.id); tid=str(member.id); team=await get_team_by_owner(uid)
    if not team:
        await i.response.send_message(embed=embed_error("エラー","あなたはチームのオーナーではありません。"))
        return
    if tid==uid:
        await i.response.send_message(embed=embed_error("エラー","自分自身は削除できません。"))
        return
    mr=await get_member_team(tid)
    if not mr or mr.get("team_id")!=team["team_id"]:
        await i.response.send_message(embed=embed_error("エラー","そのメンバーはこのチームにいません。"))
        return
    bu=(datetime.datetime.now(JST)+datetime.timedelta(days=TEAM_BAN_DELETE_DAYS)).isoformat()
    try: supabase.table("team_members").update({"team_id":None,"ban_until":bu}).eq("user_id",tid).execute()
    except Exception as e:
        await i.response.send_message(embed=embed_error("エラー",f"削除失敗: {e}"))
        return
    embed=embed_error(" メンバー削除",f"**{member.display_name}** をチームから削除しました。\nこの人は **{TEAM_BAN_DELETE_DAYS}日間** チームに参加できません。")
    await i.response.send_message(embed=embed)

@team_group.command(name="disband",description="チームを解散します（オーナーのみ）")
async def team_disband(i:Interaction):
    uid=str(i.user.id); team=await get_team_by_owner(uid)
    if not team:
        await i.response.send_message(embed=embed_error("エラー","あなたはチームのオーナーではありません。"))
        return
    try:
        supabase.table("team_members").update({"team_id":None}).eq("team_id",team["team_id"]).execute()
        supabase.table("teams").delete().eq("team_id",team["team_id"]).execute()
    except Exception as e:
        await i.response.send_message(embed=embed_error("エラー",f"解散失敗: {e}"))
        return
    await i.response.send_message(embed=embed_error(" チーム解散",f"チーム **{team['name']}** を解散しました。"))

@team_group.command(name="break",description="管理人以外いじらないでください（モデレーター専用・チーム強制解散）")
@app_commands.describe(team_id="解散させるチームのID")
async def team_break(i:Interaction,team_id:str):
    if str(i.user.id) not in moderators:
        await i.response.send_message(embed=embed_error("権限エラー","権限がありません。"),ephemeral=True)
        return
    team=await get_team_by_id(team_id)
    if not team:
        await i.response.send_message(embed=embed_error("エラー",f"チームID `{team_id}` が見つかりません。"),ephemeral=True)
        return
    tname=team["name"]
    try:
        supabase.table("team_members").update({"team_id":None}).eq("team_id",team_id).execute()
        supabase.table("teams").delete().eq("team_id",team_id).execute()
    except Exception as e:
        await i.response.send_message(embed=embed_error("エラー",f"強制解散失敗: {e}"))
        return
    embed=embed_error(" チーム強制解散",f"チーム **{tname}** (`{team_id}`) を強制解散しました。")
    await i.response.send_message(embed=embed)

client.tree.add_command(team_group)

@client.tree.command(name="ranking",description="各種ランキングを表示します")
@app_commands.describe(ranking_type="ランキングの種類",start="開始順位（デフォルト1）",end="終了順位（デフォルト10）")
@app_commands.choices(ranking_type=[
    app_commands.Choice(name=" パンランキング",value="bread"),
    app_commands.Choice(name=" コインランキング",value="coin"),
    app_commands.Choice(name=" 総合資産ランキング",value="wallet"),
    app_commands.Choice(name=" チームランキング",value="team"),
])
async def ranking(i:Interaction,ranking_type:app_commands.Choice[str]=None,start:int=1,end:int=10):
    type=ranking_type.value if ranking_type else "bread"
    await i.response.defer(); guild=i.guild
    if type=="bread":
        try: res=supabase.table("user_data").select("user_id,bread_count").order("bread_count",desc=True).execute(); data=res.data
        except Exception as e:
            await i.followup.send(embed=embed_error("エラー",f"データ取得失敗: {e}"))
            return
        if not data:
            await i.followup.send(embed=embed_error("エラー","データがありません"))
            return
        end=min(end,len(data)); start=max(1,start)
        if start>end:
            await i.followup.send(embed=embed_error("エラー","範囲が無効です"))
            return
        medals=["","",""]; text=""
        for idx,row in enumerate(data[start-1:end],start=start):
            m=guild.get_member(int(row["user_id"])); name=(m.display_name if m else "[退出済み]").replace("`","")
            bc=row.get("bread_count") or 0
            text+=f"{medals[idx-1] if idx<=3 else f'`{idx}.`'} **{name}** — {bc:,}個\n"
        await i.followup.send(embed=embed_info(" パンランキング",text))
    elif type=="coin":
        try: res=supabase.table("user_data").select("user_id,coins").order("coins",desc=True).limit(10).execute(); data=res.data
        except Exception as e:
            await i.followup.send(embed=embed_error("エラー",f"データ取得失敗: {e}"))
            return
        medals=["","",""]; text=""
        for idx,row in enumerate(data):
            m=guild.get_member(int(row["user_id"])); name=m.display_name if m else "[退出済み]"
            text+=f"{medals[idx] if idx<3 else f'`{idx+1}.`'} **{name}** — {row['coins']:,}コイン\n"
        await i.followup.send(embed=embed_info(" コインランキング TOP10",text))
    elif type=="wallet":
        try: res=supabase.table("user_data").select("user_id,bread_count,coins,chips").execute(); data=res.data
        except Exception as e:
            await i.followup.send(embed=embed_error("エラー",f"データ取得失敗: {e}"))
            return
        rate=rate_state["rate"]
        scored=sorted(
            [(row["user_id"], int((row.get("bread_count") or 0)*rate*COIN_TO_CHIP)+(row.get("coins") or 0)*COIN_TO_CHIP+(row.get("chips") or 0)) for row in data],
            key=lambda x:x[1],reverse=True
        )
        medals=["","",""]; text=""
        for idx,(uid2,total) in enumerate(scored[:10]):
            m=guild.get_member(int(uid2)); name=m.display_name if m else "[退出済み]"
            text+=f"{medals[idx] if idx<3 else f'`{idx+1}.`'} **{name}** — {total:,}チップ相当\n"
        await i.followup.send(embed=embed_info(" 総合資産ランキング TOP10（チップ換算）",text))
    elif type=="team":
        try: all_teams=supabase.table("teams").select("*").execute().data
        except Exception as e:
            await i.followup.send(embed=embed_error("エラー",f"データ取得失敗: {e}"))
            return
        tcs=sorted([(t["name"],await get_team_total_coins(t["team_id"])) for t in all_teams],key=lambda x:x[1],reverse=True)
        medals=["","",""]; text=""
        for idx,(name,coins) in enumerate(tcs[:10]):
            text+=f"{medals[idx] if idx<3 else f'`{idx+1}.`'} **{name}** — {coins:,}コイン\n"
        await i.followup.send(embed=embed_info(" チーム総資産ランキング TOP10",text or "チームがまだありません"))

class TradeView(discord.ui.View):
    def __init__(self,uid,amount): super().__init__(timeout=120); self.user_id=uid; self.amount=amount
    async def interaction_check(self,i): return str(i.user.id)==self.user_id
    def make_embed(self):
        user=get_user_cache(self.user_id); price=rate_state["rate"]; stock=user.get("rare_bread",0); avg=user.get("rare_avg",0)
        value=stock*price; profit=(price-avg)*stock; pf=f"+{int(profit)}" if profit>=0 else f"{int(profit)}"
        embed=embed_info(" レアパン取引")
        embed.add_field(name="現在価格",value=f"{int(price)} coin",inline=True)
        embed.add_field(name="保有量",value=f"{stock}",inline=True)
        embed.add_field(name="平均取得価格",value=f"{round(avg,1)}",inline=True)
        embed.add_field(name="評価額",value=f"{int(value)}",inline=True)
        embed.add_field(name="含み損益",value=pf,inline=True)
        embed.add_field(name="取引数量",value=f"{self.amount}",inline=False)
        return embed
    @discord.ui.button(label="BUY",style=discord.ButtonStyle.green)
    async def buy(self,i:Interaction,b:Button):
        user=get_user_cache(self.user_id); price=rate_state["rate"]; total=price*self.amount
        if user["coins"]<total:
            await i.response.send_message(embed=embed_error("コイン不足","コインが足りません"),ephemeral=True)
            return
        stock=user.get("rare_bread",0); avg=user.get("rare_avg",0); ns=stock+self.amount
        user["rare_bread"]=ns; user["rare_avg"]=((stock*avg)+(self.amount*price))/ns if ns>0 else 0; user["coins"]-=int(total)
        await i.response.edit_message(embed=self.make_embed(),view=self)
    @discord.ui.button(label="SELL",style=discord.ButtonStyle.red)
    async def sell(self,i:Interaction,b:Button):
        user=get_user_cache(self.user_id); stock=user.get("rare_bread",0)
        if stock<self.amount:
            await i.response.send_message(embed=embed_error("保有量不足","保有量が足りません"),ephemeral=True)
            return
        price=rate_state["rate"]; user["rare_bread"]-=self.amount; user["coins"]+=int(price*self.amount)
        await i.response.edit_message(embed=self.make_embed(),view=self)

@item_group.command(name="mix", description="アイテムを合成します")
@app_commands.describe(item1="素材1", item2="素材2")
async def item_mix(i: Interaction, item1: str, item2: str):
    await i.response.defer()
    uid = str(i.user.id); await load_user(uid); u = get_user_cache(uid)
    item1 = item1.strip(); item2 = item2.strip()
    items = u.get("items", {})
    def get_count(name): return items.get(name, {}).get("count", 0)
    if item1 == item2:
        if get_count(item1) < 2:
            await i.followup.send(embed=embed_error("素材不足",f"**{item1}** が2個必要です"))
            return
    else:
        if get_count(item1) < 1:
            await i.followup.send(embed=embed_error("素材不足",f"**{item1}** を持っていません"))
            return
        if get_count(item2) < 1:
            await i.followup.send(embed=embed_error("素材不足",f"**{item2}** を持っていません"))
            return
    key = tuple(sorted([item1, item2]))
    if key not in CRAFT_RECIPES:
        await i.followup.send(embed=embed_info("合成","その組み合わせでは何も起こりませんでした…"))
        return
    loading_embed = embed_info("️ 合成中...",f"{item1} + {item2}")
    msg = await i.followup.send(embed=loading_embed, wait=True)
    for dot in ["️ 合成中.", "️ 合成中..", "️ 合成中..."]:
        await asyncio.sleep(0.4)
        loading_embed.title = dot
        try: await msg.edit(embed=loading_embed)
        except: pass
    if item1 == item2:
        use_item_once(uid, item1); use_item_once(uid, item1)
    else:
        use_item_once(uid, item1); use_item_once(uid, item2)
    results = CRAFT_RECIPES.get(key, [])
    if not results:
        await msg.edit(embed=embed_error("エラー","合成エラー（レシピ不正）"))
        return
    r = random.random(); total = 0; result_item = None
    for name, prob in results:
        total += prob
        if r <= total: result_item = name; break
    if result_item is None: result_item = results[-1][0]
    give_item(uid, result_item, 1)
    add_daily_progress(uid, "item_mix")
    st = get_player_stats(uid); st["total_item_mix"] = st.get("total_item_mix",0)+1
    # 鉄墓合成実績
    if result_item == "鉄墓":
        asyncio.create_task(check_and_grant_achievement(uid, "iron_grave"))
        embed = embed_error(" 合成失敗",f"**{item1}** + **{item2}**\n️ ゴミができた…")
    else:
        embed = embed_success(" 合成成功",f"**{item1}** + **{item2}**\n️ **{result_item}** を獲得！")
    embed.set_footer(text=f"{i.user.display_name} の合成")
    await save_user(uid)
    await asyncio.sleep(0.3)
    try: await msg.edit(embed=embed)
    except: await i.followup.send(embed=embed)

lottery_data={"tickets":{},"last_draw":None}
LOTTERY_PRICE=100

@client.tree.command(name="lottery",description="宝くじ購入")
@app_commands.describe(amount="購入枚数")
async def lottery_buy(interaction:discord.Interaction,amount:int):
    uid=str(interaction.user.id); await load_user(uid); user=get_user_cache(uid)
    if amount<=0:
        await interaction.response.send_message(embed=embed_error("エラー","1枚以上指定してください"),ephemeral=True)
        return
    cost=amount*LOTTERY_PRICE
    if user["coins"]<cost:
        await interaction.response.send_message(embed=embed_error("コイン不足",f"所持: **{user['coins']:,}枚** / 必要: **{cost:,}枚**"),ephemeral=True)
        return
    user["coins"]-=cost
    lottery_data["tickets"][uid]=lottery_data["tickets"].get(uid,0)+amount
    embed=embed_success(" 宝くじ購入完了",f"**{amount}枚** 購入しました！\n合計所持: **{lottery_data['tickets'][uid]}枚**")
    await interaction.response.send_message(embed=embed,ephemeral=True)

@client.tree.command(name="lottery_status",description="所持枚数確認")
async def lottery_status(interaction:discord.Interaction):
    uid=str(interaction.user.id)
    my=lottery_data["tickets"].get(uid,0)
    total=sum(lottery_data["tickets"].values())
    prob=(my/total*100) if total>0 else 0
    embed=embed_info(" 宝くじ状況")
    embed.add_field(name="所持枚数",value=f"**{my}枚**",inline=True)
    embed.add_field(name="総枚数",value=f"**{total}枚**",inline=True)
    embed.add_field(name="当選確率",value=f"**{round(prob,2)}%**",inline=True)
    await interaction.response.send_message(embed=embed,ephemeral=True)

@tasks.loop(hours=1)
async def lottery_loop():
    now=datetime.datetime.now(JST)
    if now.weekday()!=0 or now.hour!=0: return
    if lottery_data["last_draw"]==now.date(): return
    lottery_data["last_draw"]=now.date()
    if not lottery_data["tickets"]: return
    pool=[]
    for uid,amount in lottery_data["tickets"].items(): pool.extend([uid]*amount)
    winner=random.choice(pool)
    bot_uid=str(client.user.id); await load_user(bot_uid); bot=get_user_cache(bot_uid)
    total_coins=bot.get("coins",0); total_bread=bot.get("bread_count",0); total_boxes=bot.get("boxes",0)
    bot["coins"]=0; bot["bread_count"]=0; bot["boxes"]=0
    await load_user(winner); user=get_user_cache(winner)
    user["coins"]+=total_coins; user["bread_count"]+=total_bread; user["boxes"]+=total_boxes
    lottery_data["tickets"]={}
    channel=client.get_channel(LEVEL_UP_CHANNEL_ID)
    if channel:
        embed=embed_success(" 宝くじ当選！",f"<@{winner}>")
        embed.add_field(name=" コイン",value=f"**{total_coins:,}枚**",inline=True)
        embed.add_field(name=" パン",value=f"**{total_bread}個**",inline=True)
        embed.add_field(name=" 宝箱",value=f"**{total_boxes}個**",inline=True)
        await channel.send(embed=embed)

@client.tree.command(name="trade",description="レアパン取引")
async def trade(i:Interaction,stock:int):
    uid=str(i.user.id); await load_user(uid); view=TradeView(uid,stock)
    await i.response.send_message(embed=view.make_embed(),view=view)

@client.tree.command(name="reset",description="️管理者以外さわらないでください全てが壊れます（国庫/プール/レートリセット）")
@app_commands.describe(target="リセット対象",amount="設定するコイン数（rateの場合は不要）")
@app_commands.choices(target=[app_commands.Choice(name="国庫 (economy_coin)",value="economy_coin"),app_commands.Choice(name="グローバルプール (global_pool)",value="global_pool"),app_commands.Choice(name="レート (rate)",value="rate")])
async def reset_cmd(i:Interaction,target:app_commands.Choice[str],amount:int=0):
    global economy_coin,global_pool,rate_state,rate_history
    if str(i.user.id) not in RESET_ALLOWED:
        await i.response.send_message(embed=embed_error("権限エラー","権限がありません。"),ephemeral=True)
        return
    if target.value=="economy_coin":
        economy_coin=amount; await save_global()
        await i.response.send_message(embed=embed_success(" リセット完了",f"国庫を **{amount:,}コイン** にリセットしました。"))
    elif target.value=="global_pool":
        global_pool=amount; await save_global()
        await i.response.send_message(embed=embed_success(" リセット完了",f"グローバルプールを **{amount:,}コイン** にリセットしました。"))
    elif target.value=="rate":
        rate_state["rate"]=BASE_RATE; rate_state["last_update"]=None; rate_history.clear()
        await i.response.send_message(embed=embed_success(" リセット完了",f"レートを **{BASE_RATE}コイン** にリセットしました。"))

@client.tree.command(name="would_break",description="️管理者以外さわらないでください全てが壊れます（データ削除）")
@app_commands.describe(target="削除対象のユーザーID。ALLで全員")
async def would_break(i:Interaction,target:str):
    if str(i.user.id) not in WOULD_BREAK_ALLOWED:
        await i.response.send_message(embed=embed_error("権限エラー","権限がありません。️管理者以外さわらないでください"),ephemeral=True)
        return
    if target.upper()=="ALL":
        try:
            supabase.table("user_data").delete().neq("user_id","___never___").execute(); user_cache.clear()
            await i.response.send_message(embed=embed_success(" 削除完了","全ユーザーデータを削除しました。️この操作は取り消せません。"))
        except Exception as e:
            await i.response.send_message(embed=embed_error("エラー",f"削除失敗: {e}"))
    else:
        try:
            supabase.table("user_data").delete().eq("user_id",target).execute(); user_cache.pop(target,None)
            await i.response.send_message(embed=embed_success(" 削除完了",f"ユーザー `{target}` のデータを削除しました。"))
        except Exception as e:
            await i.response.send_message(embed=embed_error("エラー",f"削除失敗: {e}"))

@client.tree.command(name="kill",description="BOTを停止します（モデレーターのみ）️管理者以外さわらないでください")
async def kill_cmd(i:Interaction):
    if str(i.user.id) not in moderators:
        await i.response.send_message(embed=embed_error("権限エラー","権限がありません。"),ephemeral=True)
        return
    await i.response.send_message(embed=embed_info(" BOT停止","BOTを停止します..."))
    await save_all_users(); await client.close()

# ================================================================
#  /oven_status — プリズム焼き釜残り時間確認
# ================================================================
@client.tree.command(name="oven_status", description="稼働中の焼き釜の残り時間を確認します")
async def oven_status(i: Interaction):
    uid = str(i.user.id)
    if uid not in active_kneads:
        await i.response.send_message(embed=embed_info("🔥 焼き釜", "現在稼働中の焼き釜はありません。"), ephemeral=True)
        return
    task = active_kneads[uid]
    if task.done():
        active_kneads.pop(uid, None)
        await i.response.send_message(embed=embed_info("🔥 焼き釜", "焼き釜はすでに終了しています。"), ephemeral=True)
        return
    # タスク内の残り時間はタスクオブジェクトから直接は取れないため、開始時刻管理が必要
    # ここでは「稼働中」の表示のみ行い、詳細は item list で確認案内
    embed = embed_info("🔥 焼き釜 稼働中", "現在焼き釜が稼働中です。\n`/item list` でアイテム状態を確認できます。")
    await i.response.send_message(embed=embed, ephemeral=True)

# ================================================================
#  /daily — デイリーミッション確認・報酬受け取り
# ================================================================
@client.tree.command(name="daily", description="デイリーミッションを確認します")
async def daily_cmd(i: Interaction):
    uid = str(i.user.id)
    await load_user(uid)
    d = get_daily_mission(uid)
    missions_info = {m["id"]: m for m in DAILY_MISSIONS_ALL}

    all_clear = all(
        d["progress"].get(mid, 0) >= missions_info[mid]["target"]
        for mid in d["missions"]
    )

    if all_clear and not d.get("claimed", False):
        # 報酬受け取り
        u = get_user_cache(uid)
        u["bread_count"] = u.get("bread_count", 0) + DAILY_MISSION_REWARD
        d["claimed"] = True
        # Supabase保存
        try:
            supabase.table("daily_missions").upsert({
                "user_id":  uid,
                "date":     d["date"],
                "missions": json.dumps(d["missions"], ensure_ascii=False),
                "progress": json.dumps(d["progress"], ensure_ascii=False),
                "claimed":  True,
            }).execute()
        except Exception as e:
            print(f"デイリーミッション保存失敗:{e}")
        await save_user(uid)

    lines = []
    for mid in d["missions"]:
        m_info = missions_info.get(mid)
        if not m_info:
            continue
        prog  = d["progress"].get(mid, 0)
        target = m_info["target"]
        done  = prog >= target
        mark  = "⭕" if done else "❌"
        lines.append(f"{mark} {m_info['desc']} ({min(prog, target)}/{target})")

    if all_clear and d.get("claimed", False):
        status_text = "✅ 今日のデイリーはクリアしています！\n（報酬受取済み）"
        embed = embed_success("📋 デイリーミッション", "\n".join(lines) + f"\n\n{status_text}")
    elif all_clear:
        status_text = f"🎉 全クリア！ レアパン **{DAILY_MISSION_REWARD}個** を獲得しました！"
        embed = embed_success("📋 デイリーミッション", "\n".join(lines) + f"\n\n{status_text}")
    else:
        embed = embed_info("📋 デイリーミッション", "\n".join(lines) + f"\n\n全クリアで レアパン **{DAILY_MISSION_REWARD}個** ゲット！")

    await i.response.send_message(embed=embed)

# ================================================================
#  /my_stats — 自分のプレイ統計
# ================================================================
@client.tree.command(name="my_stats", description="自分のプレイ統計を確認します")
async def my_stats(i: Interaction):
    uid = str(i.user.id)
    await load_user(uid)
    u   = get_user_cache(uid)
    st  = get_player_stats(uid)
    d   = get_daily_mission(uid)
    missions_info = {m["id"]: m for m in DAILY_MISSIONS_ALL}

    daily_lines = []
    for mid in d["missions"]:
        m_info = missions_info.get(mid)
        if not m_info: continue
        prog   = d["progress"].get(mid, 0)
        target = m_info["target"]
        mark   = "⭕" if prog >= target else "❌"
        daily_lines.append(f"{mark} {m_info['desc']} ({min(prog,target)}/{target})")

    embed = embed_info(f"📊 {i.user.display_name} のプレイ統計")
    embed.add_field(name="レアパン所持",     value=f"{u.get('bread_count',0):,}個",           inline=True)
    embed.add_field(name="コイン所持",       value=f"{u.get('coins',0):,}枚",                 inline=True)
    embed.add_field(name="チップ所持",       value=f"{u.get('chips',0):,}チップ",             inline=True)
    embed.add_field(name="レベル",           value=f"Lv.**{u.get('level',0)}** ({u.get('xp',0)} XP)",inline=True)
    embed.add_field(name="総パン獲得",       value=f"{st.get('total_bread',0):,}個",          inline=True)
    embed.add_field(name="総コイン獲得",     value=f"{st.get('total_coins_earned',0):,}枚",   inline=True)
    embed.add_field(name="総ギャンブル回数", value=f"{st.get('total_gamble',0):,}回",         inline=True)
    embed.add_field(name="スロット",         value=f"{st.get('total_slot',0):,}回",           inline=True)
    embed.add_field(name="ダイス",           value=f"{st.get('total_dice',0):,}回",           inline=True)
    embed.add_field(name="ダブルゲーム",     value=f"{st.get('total_double',0):,}回",         inline=True)
    embed.add_field(name="steal成功",        value=f"{st.get('total_steal_success',0):,}回", inline=True)
    embed.add_field(name="錬成回数",         value=f"{st.get('total_item_mix',0):,}回",      inline=True)
    embed.add_field(name="ダンジョン最深階", value=f"{st.get('total_dungeon_floor',0)}階",    inline=True)
    embed.add_field(name="今日のデイリー",   value="\n".join(daily_lines) if daily_lines else "未取得", inline=False)
    embed.set_thumbnail(url=i.user.display_avatar.url)
    await i.response.send_message(embed=embed)

# ================================================================
#  /achievement — 実績一覧表示
# ================================================================
@client.tree.command(name="achievement", description="実績一覧と解除条件を確認します")
async def achievement_cmd(i: Interaction):
    embed = embed_info("🏆 実績一覧")
    lines = ""
    for a in ACHIEVEMENTS:
        lines += f"{a['icon']} **{a['name']}**\n　{a['desc']}\n\n"
    embed.description = lines[:4000]
    await i.response.send_message(embed=embed)

# ================================================================
#  /my_achievement — 自分が解除した実績
# ================================================================
@client.tree.command(name="my_achievement", description="自分が解除した実績を確認します")
async def my_achievement_cmd(i: Interaction):
    uid  = str(i.user.id)
    achs = get_user_achievements(uid)
    if not achs:
        await i.response.send_message(embed=embed_info("🏆 解除済み実績", "まだ実績を解除していません。\n`/achievement` で実績一覧を確認しましょう！"))
        return
    lines = ""
    for a in ACHIEVEMENTS:
        if a["id"] in achs:
            lines += f"✅ {a['icon']} **{a['name']}** — {a['desc']}\n"
    locked_count = len(ACHIEVEMENTS) - len(achs)
    embed = embed_success(f"🏆 解除済み実績 ({len(achs)}/{len(ACHIEVEMENTS)})", lines)
    if locked_count > 0:
        embed.set_footer(text=f"残り {locked_count} 個の実績が未解除です。/achievement で確認！")
    await i.response.send_message(embed=embed)

#  変更点:
#   - XPリセットバグ修正（dungeon_enterでload_user）
#   - 拠点内で動けないバグ修正（BaseInteriorView._move）
#   - Supabase永続化（dg_players/dg_maps/dg_bases/dg_used）
#   - 画像マップ（Discordチャンネル方式）
#
#  【on_ready に追記が必要な行】
#    await dg_load_all()
#    if not dungeon_task.is_running(): dungeon_task.start()
#
#  【環境変数】
#    DUNGEON_IMG_CHANNEL_ID : 画像投稿用チャンネルID
# ================================================================

import io

# 追加アセットは load_all_assets() で _ASSET_CACHE に読み込み済み
# _ROCK_TILE / _rock_path は廃止。ASSET_CONFIGで管理。

def _draw_tile(draw, img, x, y, cell, biome, is_player=False, is_fog=False):
    # lazily load assets if not loaded yet
    if '_ASSET_CACHE' not in globals() or not globals().get('_ASSET_CACHE'):
        try:
            load_all_assets()
        except Exception as e:
            print(f"! load_all_assets fallback error: {e}")

    px, py = x * TILE, y * TILE
    if is_fog:
        draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=(0,0,0))
        return
    if is_player:
        # 床を先に描いてからプレイヤーを重ねる
        floor_col = TILE_COLORS[D_FLOOR].get(biome, (40,30,25)) if isinstance(TILE_COLORS[D_FLOOR], dict) else TILE_COLORS[D_FLOOR]
        draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=floor_col)
        col = TILE_COLORS["player"]
        margin = 6
        draw.ellipse([px+margin, py+margin, px+TILE-margin-1, py+TILE-margin-1], fill=col)
        return

    # すべてのセルタイプで、アセットキャッシュに存在するなら優先して貼り付け
    tile_img = _ASSET_CACHE.get((biome, cell))
    if tile_img is not None:
        img.paste(tile_img, (px, py), tile_img)
        return

    # 罠は床と同じ色（見えない）
    if cell == D_TRAP:
        # 罠は床と同じ色
        col_src = TILE_COLORS[D_FLOOR]
        col = col_src.get(biome, (40,30,25)) if isinstance(col_src, dict) else col_src
        draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=col)
        return
    col_src = TILE_COLORS.get(cell, (80,80,80))
    if isinstance(col_src, dict):
        col = col_src.get(biome, (80,80,80))
    else:
        col = col_src
    draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=col)
    # アイコン的な印をつける
    if cell == D_CHEST:
        margin = 8
        draw.rectangle([px+margin, py+margin, px+TILE-margin-1, py+TILE-margin-1],
                       fill=(255,255,100), outline=(180,140,0), width=2)
    elif cell == D_STAIRS:
        for s in range(3):
            sx = px + 6 + s*6; sy = py + TILE - 8 - s*6
            draw.rectangle([sx, sy, sx+TILE-14, sy+4], fill=(255,255,255))
    elif cell == D_SHOP:
        draw.text((px+TILE//2, py+TILE//2), "S", fill=(255,255,255))
    elif cell == D_MINE:
        draw.text((px+TILE//2-4, py+TILE//2-6), "⛏", fill=(200,200,200))
    elif cell == D_BASE:
        draw.text((px+TILE//2-4, py+TILE//2-6), "🏠", fill=(255,255,255))

def d_build_map_image(uid, floor, px, py, radius=D_VIEW_R):
    """マップをPillow Image として生成（d_render_image/d_render_pillow 共通処理）"""
    d_ensure_map(floor)
    bname, *_ = d_get_biome(floor)
    size = radius * 2 + 1
    img = Image.new("RGB", (size * TILE, size * TILE), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    for vy_i, vy in enumerate(range(py - radius, py + radius + 1)):
        for vx_i, vx in enumerate(range(px - radius, px + radius + 1)):
            is_player = (vx == px and vy == py)
            if not (0 <= vx < D_MAP_W and 0 <= vy < D_MAP_H):
                _draw_tile(draw, img, vx_i, vy_i, D_WALL, bname, is_fog=True)
                continue
            cell = dg_maps[floor][vy][vx]
            _draw_tile(draw, img, vx_i, vy_i, cell, bname, is_player=is_player)

    return img

async def d_render_image(uid, floor, px, py, radius=D_VIEW_R):
    """マップを画像として生成しDiscordにアップロード、URLを返す"""
    img = d_build_map_image(uid, floor, px, py, radius)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    try:
        ch = client.get_channel(DUNGEON_IMG_CHANNEL_ID) or \
             await client.fetch_channel(DUNGEON_IMG_CHANNEL_ID)
        msg = await ch.send(file=discord.File(buf, filename="map.png"))
        return msg.attachments[0].url
    except Exception as e:
        print(f"画像アップロード失敗: {e}")
        return None
from PIL import Image, ImageDraw
import io

# 1マスのサイズ定義
T_SIZE = 32

def generate_pillow_file(grid, pw, ph, is_main=False):
    """
    gridデータからPillow画像を生成しdiscord.Fileを返す
    is_main: メインマップ用の描画設定にする場合はTrue
    """
    global PLAYER_IMAGE
    if not grid:
        img = Image.new("RGBA", (T_SIZE, T_SIZE), (0, 0, 0, 255))
    else:
        # グリッド範囲の計算
        max_x = max(k[0] for k in grid.keys())
        max_y = max(k[1] for k in grid.keys())
        img = Image.new("RGBA", ((max_x + 1) * T_SIZE, (max_y + 1) * T_SIZE), (0, 0, 0, 255))

    draw = ImageDraw.Draw(img)

    for (x, y), cell in grid.items():
        # セルタイプに応じた色分け（既存の定数 I_WALL, D_WALL等を利用）
        if cell in [I_WALL, D_WALL]:
            color = (60, 60, 60, 255) # 壁
        elif cell in [I_EXIT, D_STAIRS]:
            color = (0, 200, 100, 255) # 出口・階段
        elif cell == D_CHEST:
            color = (255, 215, 0, 255) # 宝箱（金）
        else:
            color = (200, 200, 200, 255) # 床
        
        draw.rectangle([x * T_SIZE, y * T_SIZE, (x + 1) * T_SIZE - 1, (y + 1) * T_SIZE - 1], fill=color)

    # --- プレイヤーの描画 (AGO.PNGに差し替え) ---
    px, py = pw * T_SIZE, ph * T_SIZE
    if PLAYER_IMAGE:
        # 画像サイズが32px固定のため、そのまま貼り付け
        img.paste(PLAYER_IMAGE, (px, py), PLAYER_IMAGE)
    else:
        draw.ellipse([px + 4, py + 4, px + T_SIZE - 5, py + T_SIZE - 5], fill=(255, 50, 50, 255))

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return discord.File(fp=buf, filename="map.png")

async def d_render_status_map(uid, floor, px, py):
    """広域マップを生成してURLを返す"""
    import io
    global PLAYER_IMAGE
    d_ensure_map(floor)
    bname, *_ = d_get_biome(floor)
    
    status_radius = 25
    size = status_radius * 2 + 1
    
    # 画像作成
    img = Image.new("RGB", (size * TILE, size * TILE), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 探索済みデータの安全な取得
    user_dg = Dg.get(uid, {}).get(floor, set()) 

    for vy_i, vy in enumerate(range(py - status_radius, py + status_radius + 1)):
        for vx_i, vx in enumerate(range(px - status_radius, px + status_radius + 1)):
            is_player = (vx == px and vy == py)
            if not (0 <= vx < D_MAP_W and 0 <= vy < D_MAP_H): continue
            
            # 霧判定
            if not is_player and (vx, vy) not in user_dg: continue
            
            cell = dg_maps[floor][vy][vx]
            # --- プレイヤー描画を分離して差し替え ---
            # まずタイルのみを描画
            _draw_tile(draw, img, vx_i, vy_i, cell, bname, is_player=False)
            
            # プレイヤーの位置ならAGO.PNGを上書き
            if is_player:
                dx, dy = vx_i * TILE, vy_i * TILE
                if PLAYER_IMAGE:
                    img.paste(PLAYER_IMAGE, (dx, dy), PLAYER_IMAGE)
                else:
                    draw.ellipse([dx + 2, dy + 2, dx + TILE - 3, dy + TILE - 3], fill=(255, 50, 50))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    
    try:
        target_id = int(DUNGEON_IMG_CHANNEL_ID)
        ch = client.get_channel(target_id) or await client.fetch_channel(target_id)
        msg = await ch.send(file=discord.File(buf, filename="status_map.png"))
        return msg.attachments[0].url
    except Exception as e:
        print(f"❌ マップ生成失敗: {e}")
        return None # 失敗時は None を返す

# ----------------------------------------------------------------
#  施設内部レイアウト（9x9 / 7x7固定）
# ----------------------------------------------------------------
SHOP_LAYOUT = [
    "#######",
    "#.....#",
    "#.CCC.#",
    "#.....#",
    "#.....#",
    "#E....#",
    "#######",
]
BASE_LAYOUT = [
    "#########",
    "#.......#",
    "#.S...S.#",
    "#.......#",
    "#..@.R..#",
    "#.......#",
    "#.B...A.#",
    "#E......#",
    "#########",
]
LOBY_LAYOUT = [
    "############", # ← カンマを追加
    "#..........#", # ← カンマを追加
    "#..........#", # (以下同様)
    "#..........#",
    "#..........#",
    "#..........#",
    "#..........#",
    "#..........#",
    "############"
]

INTERIOR_EMOJI = {
    I_WALL: "⬜", I_FLOOR: "⬛", I_EXIT: "🚪",
    I_COUNTER: "🛒", I_REST: "🛋️", I_STORAGE: "💰", 
    I_BAKERY: "🍞", I_DOUBLE: "❷", I_SLOT: "🎰",
}

def _parse_layout(layout):
    grid = {}; start = (1, 1)
    for y, row in enumerate(layout):
        for x, ch in enumerate(row):
            if   ch == "#": grid[(x, y)] = I_WALL
            elif ch == ".": grid[(x, y)] = I_FLOOR
            elif ch == "E": grid[(x, y)] = I_EXIT
            elif ch == "C": grid[(x, y)] = I_COUNTER
            elif ch == "R": grid[(x, y)] = I_REST
            elif ch == "S": grid[(x, y)] = I_STORAGE
            elif ch == "@": grid[(x, y)] = I_FLOOR; start = (x, y)
            elif ch == "B": grid[(x, y)] = I_BAKERY
            elif ch == "L": grid[(x, y)] = I_SLOT    # ← x.y を x,y に修正
            elif ch == "D": grid[(x, y)] = I_DOUBLE  # ← x.y を x,y に修正
    return grid, start

SHOP_GRID, SHOP_START = _parse_layout(SHOP_LAYOUT)
BASE_GRID, BASE_START = _parse_layout(BASE_LAYOUT)
# 必要であれば LOBY も
LOBY_GRID, LOBY_START = _parse_layout(LOBY_LAYOUT)


# ----------------------------------------------------------------
#  HP/ATK/DEF管理
# ----------------------------------------------------------------
D_MAX_HP   = 150
D_BASE_ATK = 10
D_BASE_DEF = 5
D_BASE_SPD = 10
D_BASE_CRIT= 0.05

def d_hpbar(hp, max_hp, n=8):
    f = int((hp / max_hp) * n) if max_hp > 0 else 0
    return "█"*f + "░"*(n-f)

def d_get_player(uid):
    if uid not in dg_players:
        dg_players[uid] = {
            "floor":1, "x":1, "y":1,
            "hp":D_MAX_HP, "max_hp":D_MAX_HP,
            "atk":D_BASE_ATK, "def_":D_BASE_DEF,
            "spd":D_BASE_SPD, "crit":D_BASE_CRIT,
        }
    p = dg_players[uid]
    lv = get_user_cache(uid).get("level", 1) or 1
    p["atk"]   = D_BASE_ATK + lv * 2
    p["def_"]  = D_BASE_DEF + lv
    p["spd"]   = D_BASE_SPD + lv * 2
    p["max_hp"]= D_MAX_HP   + lv * 10
    if p["hp"] > p["max_hp"]: p["hp"] = p["max_hp"]
    return p

# ----------------------------------------------------------------
#  Supabase 永続化
# ----------------------------------------------------------------
async def dg_load_all():
    """起動時に全データをDBからロード"""
    global dg_players, dg_maps, dg_starts, dg_used, dg_bases
    try:
        # プレイヤー
        res = supabase.table("dungeon_players").select("*").execute()
        for row in res.data:
            dg_players[row["user_id"]] = row["data"]
        print(f"dungeon_players ロード完了: {len(dg_players)}件")
    except Exception as e:
        print(f"dungeon_players ロード失敗: {e}")

    try:
        # マップ
        res = supabase.table("dungeon_maps").select("*").execute()
        for row in res.data:
            fl = row["floor"]
            # gridはlist of list
            dg_maps[fl]   = row["grid"]
            dg_starts[fl] = tuple(row["starts"]) if row["starts"] else (1,1)
            dg_used[fl]   = set(tuple(u) for u in (row["used"] or []))
        print(f"dungeon_maps ロード完了: {len(dg_maps)}階分")
    except Exception as e:
        print(f"dungeon_maps ロード失敗: {e}")

    try:
        # 拠点
        res = supabase.table("dungeon_bases").select("*").execute()
        for row in res.data:
            dg_bases[row["user_id"]] = (row["floor"], row["x"], row["y"])
        print(f"dungeon_bases ロード完了: {len(dg_bases)}件")
    except Exception as e:
        print(f"dungeon_bases ロード失敗: {e}")

    # ロードできなかった階はメモリで生成
    for fl in range(1, D_FLOORS+1):
        d_ensure_map(fl)

async def dg_save_player(uid):
    """プレイヤー状態を保存"""
    if uid not in dg_players: return
    try:
        supabase.table("dungeon_players").upsert({
            "user_id": uid,
            "data": dg_players[uid]
        }).execute()
    except Exception as e:
        print(f"dg_save_player失敗 {uid}: {e}")

async def dg_save_map(floor):
    """マップを保存（宝箱を開けた・罠を踏んだタイミングで呼ぶ）"""
    if floor not in dg_maps: return
    try:
        supabase.table("dungeon_maps").upsert({
            "floor":  floor,
            "grid":   dg_maps[floor],
            "starts": list(dg_starts.get(floor, (1,1))),
            "used":   [list(u) for u in dg_used.get(floor, set())],
        }).execute()
    except Exception as e:
        print(f"dg_save_map失敗 floor={floor}: {e}")

async def dg_save_base(uid):
    """拠点を保存"""
    try:
        if uid in dg_bases:
            fl, x, y = dg_bases[uid]
            supabase.table("dungeon_bases").upsert({
                "user_id": uid, "floor": fl, "x": x, "y": y
            }).execute()
        else:
            supabase.table("dungeon_bases").delete().eq("user_id", uid).execute()
    except Exception as e:
        print(f"dg_save_base失敗 {uid}: {e}")

# ----------------------------------------------------------------
#  セルオートマトン法 (階段座標保存対応)
# ----------------------------------------------------------------
def d_gen_floor(floor):
    grid=[[D_WALL if (x==0 or y==0 or x==D_MAP_W-1 or y==D_MAP_H-1)
           else (D_WALL if random.random()<0.45 else D_FLOOR)
           for x in range(D_MAP_W)] for y in range(D_MAP_H)]
    for _ in range(5):
        new=[[D_WALL]*D_MAP_W for _ in range(D_MAP_H)]
        for y in range(D_MAP_H):
            for x in range(D_MAP_W):
                if x==0 or y==0 or x==D_MAP_W-1 or y==D_MAP_H-1:
                    new[y][x]=D_WALL; continue
                walls=sum(1 for dy in range(-1,2) for dx in range(-1,2)
                          if grid[y+dy][x+dx]==D_WALL)
                new[y][x]=D_WALL if walls>=5 else D_FLOOR
        grid=new
    visited=set(); best=set()
    for sy in range(1, D_MAP_H-1):
        for sx in range(1, D_MAP_W-1):
            if grid[sy][sx]==D_FLOOR and (sx,sy) not in visited:
                region=set(); queue=[(sx,sy)]
                while queue:
                    cx,cy=queue.pop()
                    if (cx,cy) in region: continue
                    region.add((cx,cy))
                    for dx,dy in [(0,1),(0,-1),(1,0),(-1,0)]:
                        nx,ny=cx+dx,cy+dy
                        if (0<nx<D_MAP_W-1 and 0<ny<D_MAP_H-1
                                and grid[ny][nx]==D_FLOOR
                                and (nx,ny) not in region):
                            queue.append((nx,ny))
                visited|=region
                if len(region)>len(best): best=region
    for y in range(D_MAP_H):
        for x in range(D_MAP_W):
            if grid[y][x]==D_FLOOR and (x,y) not in best:
                grid[y][x]=D_WALL

    # --- 階段・スタートの設置 ---
    candidates=list(best); random.shuffle(candidates)
    sx,sy=candidates[0]
    grid[sy][sx]=D_START; dg_starts[floor]=(sx,sy)
    
    stair_x, stair_y = None, None
    for ex,ey in candidates[1:]:
        if abs(ex-sx)+abs(ey-sy)>20:
            grid[ey][ex]=D_STAIRS
            stair_x, stair_y = ex, ey
            break
    else:
        if len(candidates)>1:
            stair_x, stair_y = candidates[1][0], candidates[1][1]
            grid[stair_y][stair_x]=D_STAIRS

    # ★階段座標をDBとメモリに永続化 (ここが肝です)
    if stair_x is not None:
        dg_stairs[floor] = (stair_x, stair_y)
        try:
            supabase.table("dungeon_stairs").upsert({
                "floor": floor, "x": stair_x, "y": stair_y
            }).execute()
        except Exception as e:
            print(f"⚠️ 階段保存エラー: {e}")

    # --- 以降、アイテム・罠の配置 (変更なし) ---
    floor_cells=[p for p in best if grid[p[1]][p[0]]==D_FLOOR]
    random.shuffle(floor_cells)
    placed_chest=0; placed_trap=0; placed_shop=0; placed_mine=0
    max_chest=max(3,len(floor_cells)//80)
    max_trap =max(2,len(floor_cells)//120)
    max_shop =max(1,len(floor_cells)//300)
    max_mine =max(2,len(floor_cells)//150)
    for fx,fy in floor_cells:
        if all([placed_chest>=max_chest, placed_trap>=max_trap,
                placed_shop>=max_shop,   placed_mine>=max_mine]): break
        r=random.random()
        if placed_shop<max_shop and r<0.03:
            grid[fy][fx]=D_SHOP;  placed_shop+=1
        elif placed_mine<max_mine and r<0.10:
            grid[fy][fx]=D_MINE;  placed_mine+=1
        elif placed_chest<max_chest and r<0.60:
            grid[fy][fx]=D_CHEST; placed_chest+=1
        elif placed_trap<max_trap:
            grid[fy][fx]=D_TRAP;  placed_trap+=1
    return grid

def d_ensure_map(floor):
    if floor not in dg_maps:
        dg_maps[floor] = d_gen_floor(floor)
        dg_used[floor] = set()

def d_get_cell(floor, x, y):
    d_ensure_map(floor)
    if 0<=y<D_MAP_H and 0<=x<D_MAP_W:
        return dg_maps[floor][y][x]
    return D_WALL

def d_consume(floor, x, y):
    dg_used[floor].add((x,y))
    dg_maps[floor][y][x]=D_FLOOR

# ----------------------------------------------------------------
#  報酬・罠・採掘処理
# ----------------------------------------------------------------
def d_open_chest(uid):
    u=get_user_cache(uid); roll=random.random()
    if roll<0.5:
        coins=random.randint(50,300); u["coins"]=u.get("coins",0)+coins
        return f"🟨 宝箱！ コイン **+{coins}** 枚"
    elif roll<0.8:
        bread=random.randint(3,15); u["bread_count"]=u.get("bread_count",0)+bread
        return f"🟨 宝箱！ レアパン **+{bread}** 個"
    elif roll<0.95:
        boxes=random.randint(1,3); u["boxes"]=u.get("boxes",0)+boxes
        return f"🟨 宝箱！ 宝箱 **+{boxes}** 個"
    else:
        chips=random.randint(100,500); u["chips"]=u.get("chips",0)+chips
        return f"🟨 宝箱！ チップ **+{chips}** 枚"

def d_trigger_trap(uid):
    u=get_user_cache(uid); p=d_get_player(uid); roll=random.random()
    if roll<0.4:
        loss=random.randint(30,150); u["coins"]=max(0,u.get("coins",0)-loss)
        return f"🟥 罠！ コイン **-{loss}** 枚"
    elif roll<0.7:
        dmg=random.randint(10,30); p["hp"]=max(0,p["hp"]-dmg)
        return f"🟥 罠！ HP **-{dmg}**"
    elif roll<0.85:
        loss=random.randint(1,5); u["bread_count"]=max(0,u.get("bread_count",0)-loss)
        return f"🟥 罠！ レアパン **-{loss}** 個"
    else:
        loss=random.randint(50,200); u["chips"]=max(0,u.get("chips",0)-loss)
        return f"🟥 罠！ チップ **-{loss}** 枚"

def d_do_mine(uid):
    u=get_user_cache(uid)
    gain=random.randint(30,200)
    u["coins"]=u.get("coins",0)+gain
    return gain

# ----------------------------------------------------------------
#  敵データ生成
# ----------------------------------------------------------------
D_ENEMY_NAMES = {
    "洞窟":     ["コウモリ","ゴブリン","岩石スライム"],
    "森":       ["オオカミ","毒キノコ","トレント"],
    "氷雪地帯": ["雪男","アイスゴーレム","白熊"],
    "砂漠地帯": ["サソリ","砂蛇","炎トカゲ"],
}
D_SUPERENEMY_NAMES = {
    "洞窟":     ["セミオートキラーマシン"],
    "森":       ["邪蛇"],
    "氷雪地帯": ["雪女"],
    "砂漠地帯": ["鬼"],
}
D_BOSS_NAMES = {
    "洞窟":     ["ドラゴン"],
    "森":       ["ヌシ","ぱすた"],
    "氷雪地帯": ["凍ったコッペパン"],
    "砂漠地帯": ["炎龍"],
}
# 敵ごとの個別パラメータマスタ
# hp_m: HP倍率, atk_m: 攻撃倍率, def_m: 防御倍率, spd: 固定素早さ, crit: クリティカル率, ai: 行動リスト
# coin_m: コイン倍率, xp_m: 経験値倍率, boxes: 宝箱基本数
ENEMY_STATS_MASTER = {
    "コウモリ":       {"hp_m": 0.7, "atk_m": 0.5, "def_m": 0.5, "spd": 10, "crit": 0,    "ai": ["attack","wait"], "coin_m": 0.8, "xp_m": 0.8, "boxes": 0},
    "ゴブリン":       {"hp_m": 1.0, "atk_m": 1.1, "def_m": 0.8, "spd": 15, "crit": 0.08, "ai": ["attack"], "coin_m": 1.0, "xp_m": 1.0, "boxes": 0},
    "岩石スライム":   {"hp_m": 1.5, "atk_m": 0.8, "def_m": 1.8, "spd": 5,  "crit": 0.02, "ai": ["attack"], "coin_m": 1.2, "xp_m": 1.1, "boxes": 0},
    "オオカミ":       {"hp_m": 0.9, "atk_m": 1.2, "def_m": 0.7, "spd": 20, "crit": 0.10, "ai": ["attack"], "coin_m": 1.1, "xp_m": 1.2, "boxes": 0},
    "毒キノコ":       {"hp_m": 1.2, "atk_m": 0.8, "def_m": 1.0, "spd": 5,  "crit": 0.05, "ai": ["attack"], "coin_m": 1.0, "xp_m": 1.0, "boxes": 0},
    "トレント":       {"hp_m": 2.0, "atk_m": 1.0, "def_m": 1.5, "spd": 3,  "crit": 0.03, "ai": ["attack","attack","heal"], "coin_m": 1.5, "xp_m": 1.5, "boxes": 0},
    
    "セミオートキラーマシン": {"hp_m": 4.5, "atk_m": 2.8, "def_m": 1.5, "spd": 22, "crit": 0.25, "ai": ["attack"], "coin_m": 3.0, "xp_m": 5.0, "boxes": 1},
    "邪蛇":           {"hp_m": 3.0, "atk_m": 3.4, "def_m": 1.2, "spd": 28, "crit": 0.15, "ai": ["attack"], "coin_m": 2.5, "xp_m": 4.0, "boxes": 1},
    
    "ヌシ":           {"hp_m": 20.0, "atk_m": 4.5, "def_m": 2.2, "spd": 12, "crit": 0.10, "ai": ["attack"], "coin_m": 10.0, "xp_m": 10.0, "boxes": 5},
    "ドラゴン":       {"hp_m": 18.0, "atk_m": 5.0, "def_m": 2.5, "spd": 20, "crit": 0,    "ai": ["attack"], "coin_m": 12.0, "xp_m": 12.0, "boxes": 5},
    "ぱすた":        {"hp_m": 100, "atk_m": 0, "def_m": 10, "spd": 100, "crit": 0,     "ai": ["wait"], "coin_m": 0.1, "xp_m": 0.1, "boxes": 0},

    "ミミック":       {"hp_m": 2.5, "atk_m": 2.0, "def_m": 1.2, "spd": 8,  "crit": 0.25, "ai": ["attack"], "coin_m": 5.0, "xp_m": 3.0, "boxes": 1},
    "default":        {"hp_m": 1.0, "atk_m": 1.0, "def_m": 1.0, "spd": 10, "crit": 0.05, "ai": ["attack"], "coin_m": 1.0, "xp_m": 1.0, "boxes": 0}
}

def d_make_enemy(floor, forced_name=None):
    import random
    base_hp  = 15 + floor * 8
    base_atk = 4  + floor * 2
    base_def = 1  + floor
    bname, _, _, _, _ = d_get_biome(floor)

    # 1. ランクと名前の決定
    if forced_name:
        name = forced_name
        etype = "normal" 
    else:
        r = random.random()
        if r < 0.01:
            etype = "boss"
            name = random.choice(D_BOSS_NAMES.get(bname, ["ボス"]))
        elif r < 0.11:
            etype = "elite"
            name = random.choice(D_SUPERENEMY_NAMES.get(bname, ["精鋭"]))
        else:
            etype = "normal"
            name = random.choice(D_ENEMY_NAMES.get(bname, ["謎の敵"]))

    # 2. マスタから個別パラメータを取得
    clean_key = name.split()[0].replace("👾", "").strip()
    m = ENEMY_STATS_MASTER.get(clean_key, ENEMY_STATS_MASTER["default"])

    # ランクによる倍率補正
    rank_hp_mul  = 4.0 if etype == "elite" else (15.0 if etype == "boss" else 1.0)
    rank_atk_mul = 2.5 if etype == "elite" else (4.0 if etype == "boss" else 1.0)
    rank_def_mul = 1.5 if etype == "elite" else (2.0 if etype == "boss" else 1.0)

    # 3. ステータス確定
    m_hp_m  = m.get("hp_m")
    hp = int((base_hp + random.randint(-3, 3)) * m_hp_m * rank_hp_mul)
    atk = int((base_atk + random.randint(-1, 1)) * m.get("atk_m", 1.0) * rank_atk_mul)
    defe = int(base_def * m.get("def_m", 1.0) * rank_def_mul)
    
    # 4. 報酬計算
    m_coin_m = m.get("coin_m", 1.0)
    m_xp_m   = m.get("xp_m", 1.0)
    m_boxes  = m.get("boxes", 0)

    if etype == "elite":
        reward_coins = int(random.randint(80, 150) * floor * m_coin_m)
        reward_xp    = int(random.randint(100, 800) * floor * m_xp_m)
        reward_box   = max(1, m_boxes) # 精鋭は最低1個
    elif etype == "boss":
        reward_coins = int(random.randint(2000, 4000) * floor * m_coin_m)
        reward_xp    = int(random.randint(1000, 2000) * floor * m_xp_m)
        reward_box   = max(5, m_boxes) # ボスは最低5個
    else:
        reward_coins = int(random.randint(20, 80) * floor * m_coin_m)
        reward_xp    = int(random.randint(10, 30) * floor * m_xp_m)
        # 通常敵: マスタに箱設定があるか、5%の確率でドロップ
        reward_box   = m_boxes if m_boxes > 0 else (1 if random.random() < 0.05 else 0)

    return {
        "name":         name,
        "type":         etype,
        "hp":           hp,
        "max_hp":       hp,
        "atk":          atk,
        "def_":         defe,
        "spd":          m.get("spd", 10),
        "crit":         m.get("crit", 0.05),
        "reward_coins": reward_coins,
        "reward_xp":    reward_xp,
        "reward_box":   reward_box,
    }
# ================================================================
#  戦闘View
# ================================================================
class DungeonCombatView(discord.ui.View):
    def __init__(self, uid, floor, x, y, enemy):
        super().__init__(timeout=180)
        self.uid = uid; self.floor = floor; self.x = x; self.y = y
        self.enemy = enemy; self.log = []; self.defending = False

    def _embed(self, has_image=True):
        p = d_get_player(self.uid); e = self.enemy
        ratio = p["hp"] / max(p["max_hp"], 1)
        color = 0x00ff88 if ratio > 0.5 else (0xffaa00 if ratio > 0.25 else 0xff4444)

        etype = e.get("type", "normal")
        type_text = {"normal": "通常", "elite": "精鋭", "boss": "ボス"}[etype]

        em = discord.Embed(title=f"⚔️ {e['name']}（{type_text}）が現れた！", color=color)
        if has_image: em.set_image(url="attachment://map.png")

        p_crit_display = int(p.get("crit", 0.05) * 100)
        em.add_field(name="あなた",
            value=f"`{d_hpbar(p['hp'],p['max_hp'])}`{p['hp']}/{p['max_hp']}\n⚔️{p['atk']} 🛡️{p['def_']}",
            inline=True)

        e_crit_display = int(e.get("crit", 0.05) * 100)
        em.add_field(name=e["name"],
            value=f"`{d_hpbar(e['hp'],e['max_hp'])}`{e['hp']}/{e['max_hp']}\n",
            inline=True)

        if self.log:
            em.add_field(name="ログ", value="\n".join(self.log[-5:]), inline=False)
        return em

    def _calculate_damage(self, attacker, defender, is_defending=False):
        import random
        is_crit = random.random() < attacker.get("crit", 0.05)
        target_def = defender.get("def_", 0)
        if is_defending: target_def *= 2
        dmg = max(1, attacker["atk"] - target_def + random.randint(-2, 3))
        if is_crit: return int(dmg * 1.5), True
        return dmg, False

    def _enemy_turn(self) -> str:
        p = d_get_player(self.uid); e = self.enemy
        # 敵の名前（Lv.x を除く）でマスタを参照
        raw_name = e["name"].split()[0].replace("👾", "").strip()
        master = ENEMY_STATS_MASTER.get(raw_name, ENEMY_STATS_MASTER["default"])
        action = random.choice(master.get("ai", ["attack"]))
        
        log_msg = ""
        if action == "strong_attack":
            dmg, crit = self._calculate_damage(e, p, self.defending)
            dmg = int(dmg * 1.4)
            p["hp"] = max(0, p["hp"] - dmg); log_msg = f"🔥 **{e['name']}の強攻撃！！** {dmg} ダメージ"
        elif action == "heal":
            heal_amt = int(e["max_hp"] * 0.15)
            e["hp"] = min(e["max_hp"], e["hp"] + heal_amt); log_msg = f"💚 {e['name']}は傷口を舐めて {heal_amt} 回復した"
        elif action == "wait":
            log_msg = f"💤 {e['name']}は様子を伺っている..."
        else:
            dmg, crit = self._calculate_damage(e, p, self.defending)
            p["hp"] = max(0, p["hp"] - dmg)
            c_msg = "⚠️ **CRITICAL!!** " if crit else ""
            log_msg = f"{c_msg}{e['name']}の攻撃：{dmg} ダメージ"

        self.defending = False
        return log_msg

    async def _win(self, i):
        e = self.enemy; u = get_user_cache(self.uid)
        u["coins"] = u.get("coins", 0) + e["reward_coins"]
        if e["reward_box"] > 0: u["boxes"] = u.get("boxes", 0) + e["reward_box"]
        leveled = add_xp(self.uid, e["reward_xp"])
        msg = f"🎉 勝利！ +{e['reward_coins']}コイン +{e['reward_xp']}XP"
        if e["reward_box"] > 0: msg += f" +宝箱{e['reward_box']}個"
        if leveled:
            lv = get_user_cache(self.uid)["level"]
            msg += f"\n⬆️ レベルアップ！ Lv.**{lv}**"
        self.log.append(msg); await save_user(self.uid); await dg_save_player(self.uid); self.stop()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=mv._embed(msg), view=mv, attachments=[map_file])

    async def _lose(self, i):
        p = d_get_player(self.uid)
        p["hp"] = p["max_hp"]; p["floor"] = 1; p["x"], p["y"] = dg_starts.get(1, (1, 1))
        self.log.append("敗北… スタート地点へ送還された")
        await dg_save_player(self.uid); self.stop()
        mv = DungeonMainView(self.uid, 1, p["x"], p["y"])
        map_file = d_render_pillow(self.uid, 1, p["x"], p["y"])
        await i.edit_original_response(embed=mv._embed("敗北して戻された…"), view=mv, attachments=[map_file])

    @discord.ui.button(label="⚔ 攻撃", style=discord.ButtonStyle.red, row=0)
    async def attack(self, i, b):
        await i.response.defer()
        p = d_get_player(self.uid); e = self.enemy
        p_first = p.get("spd", 10) >= e.get("spd", 10)
        
        if p_first:
            dmg, crit = self._calculate_damage(p, e)
            e["hp"] = max(0, e["hp"] - dmg)
            self.log.append(f"{'💥 **CRIT!!** ' if crit else ''}{dmg} ダメージ！")
            if e["hp"] <= 0: await self._win(i); return
            self.log.append(self._enemy_turn())
        else:
            self.log.append(self._enemy_turn())
            if p["hp"] <= 0: await self._lose(i); return
            dmg, crit = self._calculate_damage(p, e)
            e["hp"] = max(0, e["hp"] - dmg)
            self.log.append(f"{'💥 **CRIT!!** ' if crit else ''}{dmg} ダメージ！")

        if e["hp"] <= 0: await self._win(i); return
        if p["hp"] <= 0: await self._lose(i); return
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=self._embed(), view=self, attachments=[map_file])

    @discord.ui.button(label="🛡 防御", style=discord.ButtonStyle.blurple, row=0)
    async def defend(self, i, b):
        await i.response.defer()
        self.defending = True
        self.log.append(f"🛡 防御体制！\n{self._enemy_turn()}")
        if d_get_player(self.uid)["hp"] <= 0: await self._lose(i); return
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=self._embed(), view=self, attachments=[map_file])

    @discord.ui.button(label="逃げる", style=discord.ButtonStyle.grey, row=0)
    async def run_away(self, i, b):
        await i.response.defer()
        if self.enemy.get("type") == "boss":
            self.log.append("ボスからは逃げられない！\n" + self._enemy_turn())
            if d_get_player(self.uid)["hp"] <= 0: await self._lose(i); return
            await i.edit_original_response(embed=self._embed(), view=self, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])
            return
        if random.random() < (0.2 if self.enemy.get("type") == "elite" else 0.5):
            self.stop(); mv = DungeonMainView(self.uid, self.floor, self.x, self.y)
            await i.edit_original_response(embed=mv._embed("逃走成功"), view=mv, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])
        else:
            self.log.append("逃げ失敗！\n" + self._enemy_turn())
            if d_get_player(self.uid)["hp"] <= 0: await self._lose(i); return
            await i.edit_original_response(embed=self._embed(), view=self, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])


# ----------------------------------------------------------------
#  マップ表示
def d_render_pillow(uid, floor, px, py, radius=D_VIEW_R):
    """メインマップをPillowで生成し、discord.Fileを返す"""
    img = d_build_map_image(uid, floor, px, py, radius)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return discord.File(fp=buf, filename="map.png")

def i_render_pillow(grid, pw, ph):
    """施設内部をPillowで生成し、discord.Fileを返す"""
    if not grid:
        img = Image.new("RGBA", (T_SIZE, T_SIZE), (0, 0, 0, 255))
    else:
        max_x = max(x for x, y in grid) + 1
        max_y = max(y for x, y in grid) + 1
        img = Image.new("RGBA", (max_x * T_SIZE, max_y * T_SIZE), (0, 0, 0, 255))

    draw = ImageDraw.Draw(img)

    for (vx, vy), cell in grid.items():
        dx, dy = vx * T_SIZE, vy * T_SIZE
        
        # タイルの色決定（INTERIOR_EMOJIのキーに対応）
        if cell == I_WALL: color = (60, 60, 60, 255)
        elif cell == I_EXIT: color = (0, 200, 100, 255)
        else: color = (220, 220, 220, 255) # 床
        
        draw.rectangle([dx, dy, dx + T_SIZE - 1, dy + T_SIZE - 1], fill=color)

        # プレイヤーの描画
        if vx == pw and vy == ph:
            draw.ellipse([dx + 4, dy + 4, dx + T_SIZE - 5, dy + T_SIZE - 5], fill=(255, 50, 50, 255))

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return discord.File(fp=buf, filename="map.png")

# ================================================================
#  鉱山View
# ================================================================
class DungeonMineView(discord.ui.View):
    def __init__(self, uid, floor, x, y, max_count=None):
        super().__init__(timeout=120)
        self.uid = uid; self.floor = floor; self.x = x; self.y = y
        self.count = 0; self.max_count = max_count or random.randint(3, 8)
        self.total = 0; self.log = []

    def _embed(self, msg="", has_image=True):
        """Pillow画像を表示するためのEmbed生成"""
        p = d_get_player(self.uid)
        em = discord.Embed(title="⛏ 鉱山", color=0x5C4033)
        
        if has_image:
            em.set_image(url="attachment://map.png")
            
        em.add_field(name="採掘回数", value=f"{self.count}/{self.max_count}", inline=True)
        em.add_field(name="合計",     value=f"**{self.total:,}** コイン",     inline=True)
        em.add_field(name="HP",
                     value=f"`{d_hpbar(p['hp'], p['max_hp'])}` {p['hp']}/{p['max_hp']}",
                     inline=True)
        
        if self.log: 
            em.add_field(name="採掘履歴", value="\n".join(self.log[-4:]), inline=False)
        if msg: 
            em.add_field(name="お知らせ", value=msg, inline=False)
        return em

    @discord.ui.button(label="⛏ 採掘する", style=discord.ButtonStyle.blurple, row=0)
    async def mine(self, i, b):
        await i.response.defer()
        # 採掘中も現在の座標の画像を生成して維持
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)

        if self.count >= self.max_count:
            await i.edit_original_response(
                embed=self._embed("鉱脈が枯れた…"), 
                attachments=[map_file], view=self
            ); return

        gain = d_do_mine(self.uid)
        self.count += 1
        self.total += gain
        self.log.append(f"⛏ {self.count}回目: **+{gain}** コイン")
        
        await save_user(self.uid)

        if self.count >= self.max_count:
            # 掘り尽くした場合、マップチップを床に書き換え
            d_consume(self.floor, self.x, self.y)
            asyncio.create_task(dg_save_map(self.floor))
            self.children[0].disabled = True
            
            # チップ書き換え後の最新画像を生成（⛏が消えて床になる）
            new_map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
            await i.edit_original_response(
                embed=self._embed("💫 掘り尽くした！"), 
                attachments=[new_map_file], view=self
            )
        else:
            await i.edit_original_response(
                embed=self._embed(), 
                attachments=[map_file], view=self
            )

    @discord.ui.button(label="立ち去る", style=discord.ButtonStyle.grey, row=0)
    async def leave(self, i, b):
        await i.response.defer()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y)
        # メインビューに戻る際の画像を生成
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        
        await i.edit_original_response(
            embed=mv._embed(f"採掘終了。合計 **{self.total:,}** コイン獲得"), 
            attachments=[map_file], view=mv
        )


# ================================================================
#  STATUSサブメニューView
# ================================================================
class DungeonStatusView(discord.ui.View):
    def __init__(self, uid, floor, x, y):
        super().__init__(timeout=120)
        self.uid = uid; self.floor = floor; self.x = x; self.y = y
        # 拠点の有無でワープボタンの有効化を切り替え
        self.children[1].disabled = (self.uid not in dg_bases)

    async def _embed(self, msg=""):
        p = d_get_player(self.uid); u = get_user_cache(self.uid)
        bname, _, _, _, bcolor = d_get_biome(self.floor)
        own = dg_bases.get(self.uid)
        base_str = f"{own[0]}階 ({own[1]},{own[2]})" if own else "未設置"
        
        # 広域マップURLを取得
        map_url = await d_render_status_map(self.uid, self.floor, self.x, self.y)
        
        em = discord.Embed(title=f"📊 STATUS — {bname} {self.floor}階", color=bcolor)
        
        # 画像URLがある場合のみセット
        if map_url:
            em.set_image(url=map_url)
        else:
            em.description = "⚠ マップ画像の生成に失敗しました"
            
        em.add_field(name="HP", value=f"`{d_hpbar(p['hp'], p['max_hp'])}` {p['hp']}/{p['max_hp']}", inline=False)
        em.add_field(name="ATK", value=str(p["atk"]), inline=True)
        em.add_field(name="DEF", value=str(p["def_"]), inline=True)
        em.add_field(name="コイン", value=f"{u.get('coins',0):,}枚", inline=True)
        em.add_field(name="レアパン", value=f"{u.get('bread_count',0)}個", inline=True)
        em.add_field(name="チップ", value=f"{u.get('chips',0):,}枚", inline=True)
        em.add_field(name="現在地", value=f"{self.floor}階 ({self.x},{self.y})", inline=True)
        em.add_field(name="拠点", value=base_str, inline=True)
        
        # msgが空でない場合のみログフィールドを追加（ここが空だとエラーになるため）
        if msg and msg.strip(): 
            em.add_field(name="ログ", value=msg, inline=False)
            
        return em

    # --- 以下、ボタン処理 (前回と同様) ---
    @discord.ui.button(label="🏠 拠点を設置", style=discord.ButtonStyle.blurple, row=0)
    async def set_base(self, i, b):
        await i.response.defer()
        if self.uid in dg_bases:
            await i.edit_original_response(embed=await self._embed("❌ 既に拠点があります"), view=self)
            return
        dg_bases[self.uid] = (self.floor, self.x, self.y)
        dg_maps[self.floor][self.y][self.x] = D_BASE
        self.children[1].disabled = False
        asyncio.create_task(dg_save_base(self.uid)); asyncio.create_task(dg_save_map(self.floor))
        await i.edit_original_response(embed=await self._embed(f"🏠 拠点を設置しました"), view=self)

    @discord.ui.button(label="🌀 拠点にワープ", style=discord.ButtonStyle.green, row=0)
    async def warp(self, i, b):
        await i.response.defer()
        own = dg_bases.get(self.uid)
        if not own:
            await i.edit_original_response(embed=await self._embed("❌ 拠点なし"), view=self); return
        wf, wx, wy = own; d_ensure_map(wf); p = d_get_player(self.uid)
        p["floor"] = wf; p["x"] = wx; p["y"] = wy
        asyncio.create_task(dg_save_player(self.uid))
        mv = DungeonMainView(self.uid, wf, wx, wy)
        await i.edit_original_response(embed=mv._embed("🌀 ワープした！"), attachments=[d_render_pillow(self.uid, wf, wx, wy)], view=mv)

    @discord.ui.button(label="🍞 パンを食べて全回復", style=discord.ButtonStyle.success, row=1)
    async def eat_bread(self, i, b):
        await i.response.defer()
        p = d_get_player(self.uid); u = get_user_cache(self.uid)
        if u.get('bread_count', 0) <= 0:
            await i.edit_original_response(embed=await self._embed("❌ パンがありません"), view=self); return
        u['bread_count'] -= 1; p['hp'] = p['max_hp']
        asyncio.create_task(save_user_cache(self.uid)); asyncio.create_task(dg_save_player(self.uid))
        await i.edit_original_response(embed=await self._embed("✨ HP全回復！"), view=self)

    @discord.ui.button(label="⬅ 戻る", style=discord.ButtonStyle.grey, row=1)
    async def back(self, i, b):
        await i.response.defer()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=mv._embed(), attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)], view=mv)

# ================================================================
#  施設内部View（共通基底）
# ================================================================
class InteriorView(discord.ui.View):
    def __init__(self, uid, grid, pw, ph, return_floor, return_x, return_y, title, color):
        super().__init__(timeout=300)
        self.uid=uid; self.grid=grid
        self.pw=pw; self.ph=ph
        self.return_floor=return_floor
        self.return_x=return_x; self.return_y=return_y
        self.title=title; self.color=color

    def _embed(self, msg="", has_image=True):
        p = d_get_player(self.uid)
        em = discord.Embed(title=self.title, color=self.color)
        
        # 修正：テキストマップ(i_render)を廃止し、添付画像を参照
        if has_image:
            em.set_image(url="attachment://map.png")
        
        em.add_field(name="❤️ HP",
                     value=f"`{d_hpbar(p['hp'],p['max_hp'])}`{p['hp']}/{p['max_hp']}",
                     inline=True)
        if msg: em.add_field(name="ログ", value=msg, inline=False)
        return em

    async def _on_step(self, cell, i=None): return ""

    async def _move(self, i, dx, dy):
        await i.response.defer()
        # 1. 次の座標を計算
        nx, ny = self.pw + dx, self.ph + dy
        
        # 2. 判定用のセル取得
        cell = self.grid.get((nx, ny), I_WALL)
        
        # --- 壁判定 ---
        if cell == I_WALL:
            # 移動せず、現在の座標でマップを再生成して「壁」ログを表示
            map_file = i_render_pillow(self.grid, self.pw, self.ph)
            await i.edit_original_response(
                embed=self._embed("🔲 壁！進めない"), 
                attachments=[map_file]
            )
            return
            
        # --- 出口判定 ---
        if cell == I_EXIT:
            mv = DungeonMainView(self.uid, self.return_floor, self.return_x, self.return_y)
            # DungeonMainView側も画像対応している前提で呼び出し
            map_file = d_render_pillow(self.uid, self.return_floor, self.return_x, self.return_y)
            await i.edit_original_response(
                embed=mv._embed("施設を出た"), 
                view=mv, 
                attachments=[map_file]
            )
            return
            
        # --- 移動成功 ---
        # 3. 座標を実際に更新
        self.pw, self.ph = nx, ny
        
        # 4. 足元のイベント実行（宝箱やメッセージなど）
        msg = await self._on_step(cell, i)
        
        # 5. 【重要】更新後の座標で新しいマップ画像を生成
        map_file = i_render_pillow(self.grid, self.pw, self.ph)
        
        # 6. 画像を添付してレスポンスを更新（これで「動いた」ことが見える）
        await i.edit_original_response(
            embed=self._embed(msg), 
            view=self, 
            attachments=[map_file]
        )

    # ボタン定義（既存のものを維持）
    @discord.ui.button(label="↖️", style=discord.ButtonStyle.grey, row=0, custom_id="i_lu")
    async def leftup(self,   i, b): await self._move(i, -1, -1)
    @discord.ui.button(label="⬆️", style=discord.ButtonStyle.grey, row=0, custom_id="i_u")
    async def up(self,       i, b): await self._move(i,  0, -1)
    @discord.ui.button(label="↗️", style=discord.ButtonStyle.grey, row=0, custom_id="i_ru")
    async def rightup(self,  i, b): await self._move(i,  1, -1)
    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.grey, row=1, custom_id="i_l")
    async def left(self,     i, b): await self._move(i, -1,  0)
    @discord.ui.button(label="☑️", style=discord.ButtonStyle.grey, row=1, custom_id="i_c")
    async def check(self,    i, b): await self._move(i,  0,  0)
    @discord.ui.button(label="➡️", style=discord.ButtonStyle.grey, row=1, custom_id="i_r")
    async def right(self,    i, b): await self._move(i,  1,  0)
    @discord.ui.button(label="↙️", style=discord.ButtonStyle.grey, row=2, custom_id="i_ld")
    async def leftdown(self, i, b): await self._move(i, -1,  1)
    @discord.ui.button(label="⬇️", style=discord.ButtonStyle.grey, row=2, custom_id="i_d")
    async def down(self,     i, b): await self._move(i,  0,  1)
    @discord.ui.button(label="↘️", style=discord.ButtonStyle.grey, row=2, custom_id="i_rd")
    async def rightdown(self,i, b): await self._move(i,  1,  1)


# ================================================================
#  ショップ内部View
# ================================================================
class ShopInteriorView(InteriorView):
    def __init__(self, uid, return_floor, return_x, return_y):
        # SHOP_GRID, SHOP_START 等の定数を使用
        super().__init__(uid, SHOP_GRID, SHOP_START[0], SHOP_START[1],
                         return_floor, return_x, return_y, "🏪 ショップ", 0x8B4513)

    async def _on_step(self, cell, i=None):
        if cell == I_COUNTER:
            # カウンター（店員の前）に着いた時
            sv = ShopPurchaseView(self.uid, self)
            # 修正：Viewが切り替わってもマップ画像が消えないよう、現在のマップを生成して添付
            map_file = i_render_pillow(self.grid, self.pw, self.ph)
            await i.edit_original_response(
                embed=self._embed("🛒 何を買いますか？"), 
                view=sv,
                attachments=[map_file]
            )
            return None  # _move側での再編集を防止
        return ""

    async def _move(self, i, dx, dy):
        """
        親クラスの _move をそのまま使っても良いですが、
        既存の ShopInteriorView 独自のロジック（msg is not None 判定）を維持した Pillow 版です。
        """
        await i.response.defer()
        nx, ny = self.pw + dx, self.ph + dy
        cell = self.grid.get((nx, ny), I_WALL)
        
        # 壁判定
        if cell == I_WALL:
            map_file = i_render_pillow(self.grid, self.pw, self.ph)
            await i.edit_original_response(
                embed=self._embed("🔲 壁！進めない"), 
                view=self,
                attachments=[map_file]
            ); return
            
        # 出口判定
        if cell == I_EXIT:
            mv = DungeonMainView(self.uid, self.return_floor, self.return_x, self.return_y)
            # メインマップ用の画像生成関数を呼び出し
            map_file = d_render_pillow(self.uid, self.return_floor, self.return_x, self.return_y)
            await i.edit_original_response(
                embed=mv._embed("ショップを出た"), 
                view=mv,
                attachments=[map_file]
            ); return

        # 座標更新
        self.pw, self.ph = nx, ny
        msg = await self._on_step(cell, i)
        
        # _on_step 内で View が切り替わっていない（Noneが返っていない）場合のみ、移動後のマップを描画
        if msg is not None:
            map_file = i_render_pillow(self.grid, self.pw, self.ph)
            await i.edit_original_response(
                embed=self._embed(msg), 
                view=self,
                attachments=[map_file]
            )


# ================================================================
#  ショップ購入View
# ================================================================
class ShopPurchaseView(discord.ui.View):
    def __init__(self, uid, shop_view):
        super().__init__(timeout=60)
        self.uid = uid
        self.shop_view = shop_view  # ShopInteriorViewのインスタンス

    def _embed(self, msg=""):
        u = get_user_cache(self.uid)
        em = discord.Embed(title="🛒 購入", color=0x8B4513)
        # 画像を参照するように設定
        em.set_image(url="attachment://map.png")
        
        em.add_field(name="所持コイン", value=f"**{u.get('coins',0):,}** 枚", inline=False)
        em.add_field(name="商品一覧", value=(
            "1️⃣ HP回復薬（小） — **50コイン** HP+30\n"
            "2️⃣ HP回復薬（大） — **150コイン** HP+80\n"
            "3️⃣ レアパン — **200コイン** +1個\n"
            "4️⃣ 宝箱 — **300コイン** +1個"
        ), inline=False)
        if msg: 
            em.add_field(name="ログ", value=msg, inline=False)
        return em

    @discord.ui.button(label="HP+30 (50c)", style=discord.ButtonStyle.green, row=0)
    async def b1(self, i, b): await self._buy(i, 50, "hp_s")
    
    @discord.ui.button(label="HP+80 (150c)", style=discord.ButtonStyle.green, row=0)
    async def b2(self, i, b): await self._buy(i, 150, "hp_l")
    
    @discord.ui.button(label="パン (200c)", style=discord.ButtonStyle.blurple, row=1)
    async def b3(self, i, b): await self._buy(i, 200, "bread")
    
    @discord.ui.button(label="宝箱+1 (300c)", style=discord.ButtonStyle.blurple, row=1)
    async def b4(self, i, b): await self._buy(i, 300, "box")

    @discord.ui.button(label="⬅ 戻る", style=discord.ButtonStyle.grey, row=2)
    async def back(self, i, b):
        await i.response.defer()
        # 戻る際も現在のショップマップ画像を生成して添付
        map_file = i_render_pillow(self.shop_view.grid, self.shop_view.pw, self.shop_view.ph)
        await i.edit_original_response(
            embed=self.shop_view._embed(), 
            view=self.shop_view,
            attachments=[map_file]
        )

    async def _buy(self, i, price, item):
        await i.response.defer()
        u = get_user_cache(self.uid)
        p = d_get_player(self.uid)
        
        # 購入中も背景画像を維持するために生成
        map_file = i_render_pillow(self.shop_view.grid, self.shop_view.pw, self.shop_view.ph)

        if u.get("coins", 0) < price:
            await i.edit_original_response(
                embed=self._embed("❌ コインが足りません"), 
                view=self,
                attachments=[map_file]
            )
            return

        u["coins"] -= price
        if item == "hp_s":
            p["hp"] = min(p["max_hp"], p["hp"] + 30)
            msg = f"✅ HP +30（{p['hp']}/{p['max_hp']}）"
        elif item == "hp_l":
            p["hp"] = min(p["max_hp"], p["hp"] + 80)
            msg = f"✅ HP +80（{p['hp']}/{p['max_hp']}）"
        elif item == "bread":
            u["bread_count"] = u.get("bread_count", 0) + 1
            msg = "✅ レアパン +1個"
        else:
            u["boxes"] = u.get("boxes", 0) + 1
            msg = "✅ 宝箱 +1個"

        await save_user(self.uid)
        await i.edit_original_response(
            embed=self._embed(msg), 
            view=self,
            attachments=[map_file]
        )


# ================================================================
#  拠点内部View
# ================================================================
class BaseInteriorView(InteriorView):
    def __init__(self, uid, return_floor, return_x, return_y, is_own=True):
        # 親クラスの __init__ を呼び出し (self.pw, self.ph が初期化される)
        super().__init__(uid, BASE_GRID, BASE_START[0], BASE_START[1],
                         return_floor, return_x, return_y, "🏠 拠点", 0x4a4a8a)
        self.is_own = is_own
        # 権限チェック (最後のボタン = 解体ボタン)
        if len(self.children) > 0:
            self.children[-1].disabled = not is_own

    async def _on_step(self, cell, i=None):
        """各マスを踏んだ時の処理"""
        # 休憩 (I_REST)
        if cell == I_REST:
            p = d_get_player(self.uid)
            old_hp = p["hp"]
            p["hp"] = p["max_hp"]
            asyncio.create_task(dg_save_player(self.uid))
            return f"休憩しました。HPが全回復しました ({old_hp} -> {p['hp']})"

        # パン工房 (I_BAKERY)
        if cell == I_BAKERY:
            u = get_user_cache(self.uid)
            c = random.randint(10, 50)
            u["coins"] = u.get("coins", 0) + c
            
            if random.random() < 0.2:
                u["bread_count"] = u.get("bread_count", 0) + 1
                msg = f"パンが焼けました！ (+1個) / {c}コイン獲得"
            else:
                msg = f"パンをこねています... / {c}コイン獲得"
            
            asyncio.create_task(save_user_cache(self.uid))
            return msg

        # ストレージ (I_STORAGE)
        if cell == I_STORAGE:
            u = get_user_cache(self.uid)
            # 同期処理
            asyncio.create_task(save_user_cache(self.uid))
            asyncio.create_task(dg_save_player(self.uid))
            
            info = f"コイン:{u.get('coins',0):,} / パン:{u.get('bread_count',0)} / チップ:{u.get('chips',0):,}"
            return f"データを同期しました。\n{info}"

        return ""

    # 親クラス InteriorView の _move を利用するため、独自の _move_logic は削除または整理
    # もし InteriorView の _move をそのまま使うなら、ボタン定義は不要ですが、
    # 独自ボタン（退出・解体）があるため、そこでの画像処理を記述します。

    @discord.ui.button(label="拠点から出る", style=discord.ButtonStyle.grey, row=4)
    async def leave(self, interaction, button):
        await interaction.response.defer()
        mv = DungeonMainView(self.uid, self.return_floor, self.return_x, self.return_y)
        # 退出時、メインマップの画像を生成して添付
        map_file = d_render_pillow(self.uid, self.return_floor, self.return_x, self.return_y)
        await interaction.edit_original_response(
            embed=mv._embed("拠点を後にしました"), 
            view=mv,
            attachments=[map_file]
        )

    @discord.ui.button(label="拠点を解体", style=discord.ButtonStyle.red, row=3)
    async def disband(self, i, b):
        await i.response.defer()
        if not self.is_own:
            map_file = i_render_pillow(self.grid, self.pw, self.ph)
            await i.edit_original_response(embed=self._embed("権限がありません"), view=self, attachments=[map_file]); return
        
        own = dg_bases.get(self.uid)
        of = 1
        if own:
            of, ox, oy = own
            if dg_maps.get(of) and dg_maps[of][oy][ox] == D_BASE:
                dg_maps[of][oy][ox] = D_FLOOR
            del dg_bases[self.uid]
            asyncio.create_task(dg_save_base(self.uid))
            asyncio.create_task(dg_save_map(of))
        
        mv = DungeonMainView(self.uid, self.return_floor, self.return_x, self.return_y)
        # 解体して外に出る際も画像を生成
        map_file = d_render_pillow(self.uid, self.return_floor, self.return_x, self.return_y)
        await i.edit_original_response(embed=mv._embed("拠点を解体しました"), view=mv, attachments=[map_file])
# ================================================================
#  階段選択View
# ================================================================
class DungeonStairsView(discord.ui.View):
    def __init__(self, uid, floor, x, y):
        super().__init__(timeout=60)
        self.uid = uid
        self.floor = floor
        self.x = x
        self.y = y
        # 階層制限によるボタン無効化
        self.children[0].disabled = (floor <= 1)
        self.children[1].disabled = (floor >= D_FLOORS)

    @discord.ui.button(label="上の階へ", style=discord.ButtonStyle.blurple, row=0)
    async def go_up(self, i, b):
        await i.response.defer()
        self.floor -= 1
        d_ensure_map(self.floor)
        
        # プレイヤー情報の更新と座標の初期化
        p = d_get_player(self.uid)
        sx, sy = dg_starts.get(self.floor, (1, 1))
        self.x, self.y = sx, sy
        p["floor"] = self.floor
        p["x"], p["y"] = self.x, self.y
        
        asyncio.create_task(dg_save_player(self.uid))
        
        # 新しい階層のViewと画像を生成
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        
        # 画像を添付して更新
        await i.edit_original_response(
            embed=mv._embed(f"🔺 {self.floor}階へ戻った！"), 
            view=mv,
            attachments=[map_file]
        )

    @discord.ui.button(label="下の階へ", style=discord.ButtonStyle.green, row=0)
    async def go_down(self, i, b):
        await i.response.defer()
        self.floor += 1
        d_ensure_map(self.floor)
        
        # プレイヤー情報の更新と座標の初期化
        p = d_get_player(self.uid)
        sx, sy = dg_starts.get(self.floor, (1, 1))
        self.x, self.y = sx, sy
        p["floor"] = self.floor
        p["x"], p["y"] = self.x, self.y
        
        # ダンジョン最深階統計・実績
        st = get_player_stats(self.uid)
        if self.floor > st.get("total_dungeon_floor", 0):
            st["total_dungeon_floor"] = self.floor
        if self.floor >= 30:
            asyncio.create_task(check_and_grant_achievement(self.uid, "dungeon_30"))
        
        asyncio.create_task(dg_save_player(self.uid))
        
        # 新しい階層のViewと画像を生成
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        
        # 画像を添付して更新
        await i.edit_original_response(
            embed=mv._embed(f"🔻 {self.floor}階へ進んだ！"), 
            view=mv,
            attachments=[map_file]
        )

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.grey, row=0)
    async def cancel(self, i, b):
        await i.response.defer()
        # 現在の階層・座標のままメインビューに戻る
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        
        await i.edit_original_response(
            embed=mv._embed(), 
            view=mv,
            attachments=[map_file]
        )

# ================================================================
#  メインマップView
# ================================================================
class DungeonMainView(discord.ui.View):
    def __init__(self, uid, floor, x, y):
        super().__init__(timeout=600)
        self.uid = uid
        self.floor = floor
        self.x = x
        self.y = y

    def _embed(self, msg="", has_image=True, image_url=None):
        """Pillow画像(attachment://map.png)またはURL画像を表示するためのEmbed生成"""
        bname, _, _, _, bcolor = d_get_biome(self.floor)
        p = d_get_player(self.uid)
        em = discord.Embed(
            title=f"🏰 {bname} {self.floor}階 ({self.x},{self.y})",
            color=bcolor
        )
        
        if has_image:
            if image_url:
                em.set_image(url=image_url)
            else:
                em.set_image(url="attachment://map.png")
        else:
            em.add_field(name="マップ", value=d_render_text(self.uid, self.floor, self.x, self.y), inline=False)
            
        em.add_field(name="HP", value=f"`{d_hpbar(p['hp'],p['max_hp'])}` {p['hp']}/{p['max_hp']}", inline=True)
        if msg and msg.strip(): 
            em.add_field(name="ログ", value=msg, inline=False)
        return em

    async def _move(self, i, dx, dy):
        await i.response.defer()
        nx, ny = self.x + dx, self.y + dy
        ct = d_get_cell(self.floor, nx, ny)

        # --- 1. 壁判定 ---
        if ct == D_WALL:
            map_url = await d_render_image(self.uid, self.floor, self.x, self.y)
            await i.edit_original_response(embed=self._embed("🔲 壁！進めない", has_image=True, image_url=map_url), view=self)
            return

        # 座標更新
        self.x, self.y = nx, ny
        p = d_get_player(self.uid)
        p["floor"] = self.floor
        p["x"], p["y"] = self.x, self.y

        # --- 2. 探索データの記録 (修正済: self. を付与) ---
        if self.uid not in Dg: Dg[self.uid] = {}
        if self.floor not in Dg[self.uid]: Dg[self.uid][self.floor] = set()
        Dg[self.uid][self.floor].add((self.x, self.y))

        # Supabase への保存処理 (同期)
        explored_list = [list(c) for c in Dg[self.uid][self.floor]]
        supabase.table("user_exploration").upsert({
            "uid": self.uid,
            "floor": self.floor,
            "explored_coords": explored_list
        }).execute()

        msg = ""

        # --- 3. 特殊タイル・イベント判定 ---
        if ct == D_STAIRS:
            sv = DungeonStairsView(self.uid, self.floor, self.x, self.y)
            map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
            await i.edit_original_response(embed=self._embed("🔺 階段がある。どうする？"), attachments=[map_file], view=sv)
            return

        elif ct == D_CHEST:
            msg = d_open_chest(self.uid)
            d_consume(self.floor, self.x, self.y)
            asyncio.create_task(save_user_cache(self.uid))
            asyncio.create_task(dg_save_map(self.floor))

        elif ct == D_TRAP:
            msg = d_trigger_trap(self.uid)
            d_consume(self.floor, self.x, self.y)
            asyncio.create_task(save_user_cache(self.uid))
            asyncio.create_task(dg_save_map(self.floor))

        elif ct == D_SHOP:
            sv = ShopInteriorView(self.uid, self.floor, self.x, self.y)
            map_file = i_render_pillow(SHOP_GRID, SHOP_START[0], SHOP_START[1])
            await i.edit_original_response(embed=sv._embed("🏪 ショップに入った"), attachments=[map_file], view=sv)
            return

        elif ct == D_BASE:
            is_own = (dg_bases.get(self.uid) == (self.floor, self.x, self.y))
            bv = BaseInteriorView(self.uid, self.floor, self.x, self.y, is_own=is_own)
            label = "🏠 自分の拠点に入った" if is_own else "🏠 他の人の拠点に入った"
            map_file = i_render_pillow(BASE_GRID, BASE_START[0], BASE_START[1])
            await i.edit_original_response(embed=bv._embed(label), attachments=[map_file], view=bv)
            return

        elif ct == D_MINE:
            mv = DungeonMineView(self.uid, self.floor, self.x, self.y)
            map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
            await i.edit_original_response(embed=mv._embed("⛏ 鉱山を発見！"), attachments=[map_file], view=mv)
            return

        else:
            import random
            bname, _, _, _, _ = d_get_biome(self.floor)
            rate = D_ENCOUNTER_RATES.get(bname, 0.10)
            if random.random() < rate:
                enemy = d_make_enemy(self.floor)
                cv = DungeonCombatView(self.uid, self.floor, self.x, self.y, enemy)
                map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
                await i.edit_original_response(embed=cv._embed(), attachments=[map_file], view=cv)
                return

        # --- 4. 死亡判定 ---
        if p["hp"] <= 0:
            p["hp"] = p["max_hp"]
            p["floor"] = 1
            start_pos = dg_starts.get(1, (1, 1))
            p["x"], p["y"] = start_pos
            self.floor = 1; self.x, self.y = p["x"], p["y"]
            msg += "\n力尽きた… スタート地点へ戻された"

        # --- 5. 最終的な画面更新 ---
        asyncio.create_task(dg_save_player(self.uid))
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=self._embed(msg), attachments=[map_file], view=self)

    # --- ボタン定義 ---
    @discord.ui.button(label="↖️", style=discord.ButtonStyle.grey, row=0, custom_id="dg_lu")
    async def leftup(self,   i, b): await self._move(i, -1, -1)
    @discord.ui.button(label="⬆️", style=discord.ButtonStyle.grey, row=0, custom_id="dg_u")
    async def up(self,       i, b): await self._move(i,  0, -1)
    @discord.ui.button(label="↗️", style=discord.ButtonStyle.grey, row=0, custom_id="dg_ru")
    async def rightup(self,  i, b): await self._move(i,  1, -1)
    
    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.grey, row=1, custom_id="dg_l")
    async def left(self,     i, b): await self._move(i, -1,  0)
    @discord.ui.button(label="☑️", style=discord.ButtonStyle.grey, row=1, custom_id="dg_c")
    async def check(self,    i, b): await self._move(i,  0,  0)
    @discord.ui.button(label="➡️", style=discord.ButtonStyle.grey, row=1, custom_id="dg_r")
    async def right(self,    i, b): await self._move(i,  1,  0)
    
    @discord.ui.button(label="↙️", style=discord.ButtonStyle.grey, row=2, custom_id="dg_ld")
    async def leftdown(self, i, b): await self._move(i, -1,  1)
    @discord.ui.button(label="⬇️", style=discord.ButtonStyle.grey, row=2, custom_id="dg_d")
    async def down(self,     i, b): await self._move(i,  0,  1)
    @discord.ui.button(label="↘️", style=discord.ButtonStyle.grey, row=2, custom_id="dg_rd")
    async def rightdown(self,i, b): await self._move(i,  1,  1)

    @discord.ui.button(label="STATUS", style=discord.ButtonStyle.green, row=3, custom_id="dg_status")
    async def status(self, i, b):
        await i.response.defer()
        sv = DungeonStatusView(self.uid, self.floor, self.x, self.y)
        status_embed = await sv._embed()
        await i.edit_original_response(embed=status_embed, attachments=[], view=sv)


# ================================================================
#  /dungeon コマンド  ← XPリセットバグ修正済み
# ================================================================
@client.tree.command(name="dungeon", description="ダンジョンに入ります")
async def dungeon_enter(interaction: Interaction):
    # 既存の defer はそのまま
    await interaction.response.defer()
    uid = str(interaction.user.id)
    
    # ユーザーデータのロードとプレイヤー情報の取得
    await load_user(uid)
    p = d_get_player(uid)
    floor, x, y = p["floor"], p["x"], p["y"]
    
    # マップ生成の確認
    d_ensure_map(floor)
    
    # 初期位置の設定
    sx, sy = dg_starts.get(floor, (1, 1))
    if x == 1 and y == 1:
        x, y = sx, sy
        p["x"] = x
        p["y"] = y
        # 座標が更新されたので保存
        asyncio.create_task(dg_save_player(uid))

    # --- Pillow 移行に伴う変更点 ---
    
    # 1. Viewの作成
    mv = DungeonMainView(uid, floor, x, y)
    
    # 2. 初期表示用のマップ画像を生成 (d_render_image を使用)
    map_url = await d_render_image(uid, floor, x, y)

    # 3. Embedの生成（画像ありフラグをTrueに）
    em = mv._embed("ダンジョンへようこそ！", has_image=True, image_url=map_url)

    # 4. followup.send で URL付きEmbedを送信
    await interaction.followup.send(embed=em, view=mv)


# ================================================================
#  /dungeon_reset（モデレーターのみ）
# ================================================================
@client.tree.command(name="dungeon_reset", description="ダンジョンマップをリセットします（モデレーターのみ）")
async def dungeon_reset(interaction: Interaction):
    if str(interaction.user.id) not in moderators:
        await interaction.response.send_message(
            embed=embed_error("権限エラー","権限がありません"), ephemeral=True); return
    await interaction.response.defer()
    dg_maps.clear(); dg_players.clear(); dg_starts.clear()
    dg_used.clear(); dg_bases.clear()
    # DBも全消去
    try:
        supabase.table("dungeon_maps").delete().neq("floor",0).execute()
        supabase.table("dungeon_players").delete().neq("user_id","").execute()
        supabase.table("dungeon_bases").delete().neq("user_id","").execute()
    except Exception as e:
        print(f"dungeon_reset DB削除失敗: {e}")
    for fl in range(1, D_FLOORS+1):
        d_ensure_map(fl)
        asyncio.create_task(dg_save_map(fl))
    await interaction.followup.send(
        embed=embed_success("リセット完了","マップを再生成しました！"))

# ================================================================
#  月次リセットタスク
# ================================================================
@tasks.loop(hours=1)
async def dungeon_task():
    now=datetime.datetime.now(JST)
    if now.day==1 and now.hour==0:
        dg_maps.clear(); dg_players.clear(); dg_starts.clear()
        dg_used.clear(); dg_bases.clear()
        try:
            supabase.table("dungeon_maps").delete().neq("floor",0).execute()
            supabase.table("dungeon_players").delete().neq("user_id","").execute()
            supabase.table("dungeon_bases").delete().neq("user_id","").execute()
        except Exception as e:
            print(f"dungeon月次リセットDB削除失敗: {e}")
        for fl in range(1, D_FLOORS+1):
            d_ensure_map(fl)
            asyncio.create_task(dg_save_map(fl))
        print("ダンジョン月次リセット完了")

from keep_alive import keep_alive
keep_alive()
client.run(tok)
