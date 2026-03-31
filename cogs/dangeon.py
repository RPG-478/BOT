# -*- coding: utf-8 -*-
import os
import io
import asyncio
import random
import datetime
import discord
from discord.ext import commands, tasks
from PIL import Image, ImageDraw

# config.py から supabase, JST, 各種定数、グローバル変数をインポート
from config import *

# ================================================================
#  1. タイルIDと内部定数の定義
# ================================================================
D_WALL   = 0  # 壁
D_FLOOR  = 1  # 床
D_START  = 2  # 開始地点
D_STAIRS = 3  # 階段
D_CHEST  = 4  # 宝箱
D_TRAP   = 5  # 罠
D_SHOP   = 6  # ショップ
D_BASE   = 7  # 拠点

class DungeonCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # --- 2. パス解決とアセット保持 ---
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assets_path = os.path.join(self.base_dir, "Assets")
        
        # 画像キャッシュ用辞書
        self.assets = {
            "tiles": {},   # {(biome_name, tile_id): Image}
            "entities": {} # {"player": Image}
        }
        
        # ユーザーごとの移動ロック
        self.move_locks = {}

    def get_lock(self, user_id):
        uid = str(user_id)
        if uid not in self.move_locks:
            self.move_locks[uid] = asyncio.Lock()
        return self.move_locks[uid]

    # ================================================================
    #  3. アセットロード・検証 (フェーズ1)
    # ================================================================
    async def cog_load(self):
        """Cog読み込み時の初期化フロー統合版"""
        self.load_all_images()
        self.verify_assets()
        print(f"✅ DungeonCog: Initialization complete (JST: {datetime.datetime.now(JST)})")

    def load_all_images(self):
        if not os.path.exists(self.assets_path):
            print(f"⚠️ Warning: Assets directory not found at {self.assets_path}")
            return

        # プレイヤー画像
        p_path = os.path.join(self.assets_path, "AGO.PNG")
        if os.path.exists(p_path):
            try:
                img = Image.open(p_path).convert("RGBA")
                self.assets["entities"]["player"] = img.resize((TILE, TILE), Image.Resampling.LANCZOS)
            except Exception as e:
                print(f"❌ Failed to load AGO.PNG: {e}")

        # タイル画像定義
        tile_definitions = {
            "洞窟": {D_WALL: "rock.PNG", D_FLOOR: "jimen.png"},
            "森":   {D_WALL: "mori_kabe.png", D_FLOOR: "mori_yuka.png"},
            "氷雪地帯": {D_WALL: "Y_k.png", D_FLOOR: "Y_y.png"},
        }

        for biome, tiles in tile_definitions.items():
            for tid, filename in tiles.items():
                fpath = os.path.join(self.assets_path, filename)
                if os.path.exists(fpath):
                    try:
                        img = Image.open(fpath).convert("RGBA")
                        self.assets["tiles"][(biome, tid)] = img.resize((TILE, TILE), Image.Resampling.NEAREST)
                    except Exception as e:
                        print(f"❌ Failed to load {filename}: {e}")

    def verify_assets(self):
        required_biomes = [b[1] for b in D_BIOMES]
        required_tids = [D_WALL, D_FLOOR]
        print("--- Dungeon Asset Verification ---")
        if "player" not in self.assets["entities"]:
            print("⚠️ [Critical] Player image (AGO.PNG) is missing.")
        for biome in required_biomes:
            for tid in required_tids:
                if (biome, tid) not in self.assets["tiles"]:
                    # 存在しない場合は get_tile_image が動的生成する
                    pass
        print("✅ Verification process finished.")
        print("----------------------------------")

    def get_biome_by_floor(self, floor: int):
        for f_range, name, wall_emo, floor_emo, spec_emo, color_hex in D_BIOMES:
            if floor in f_range:
                return name, wall_emo, floor_emo, spec_emo, color_hex
        return "深淵", "⬛", "🔲", "💠", 0x000000

    def hex_to_rgb(self, hex_color: int):
        return ((hex_color >> 16) & 0xFF, (hex_color >> 8) & 0xFF, hex_color & 0xFF)

    def get_tile_image(self, biome_name: str, tile_id: int):
        img = self.assets["tiles"].get((biome_name, tile_id))
        if img: return img
        
        # 動的フォールバック生成
        found_color = 0x808080
        for _, name, _, _, _, color in D_BIOMES:
            if name == biome_name:
                found_color = color
                break
        rgb = self.hex_to_rgb(found_color)
        if tile_id == D_WALL:
            rgb = tuple(max(0, c - 40) for c in rgb)
        
        fallback_img = Image.new("RGBA", (TILE, TILE), rgb + (255,))
        self.assets["tiles"][(biome_name, tile_id)] = fallback_img
        return fallback_img

    async def get_image_as_file(self, image_obj, filename="map.png"):
        buf = io.BytesIO()
        image_obj.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return discord.File(fp=buf, filename=filename)

    # ================================================================
    #  4. マップ生成ロジック (フェーズ2)
    # ================================================================
    def generate_base_map(self, floor: int):
        random.seed(f"floor_{floor}_{datetime.datetime.now(JST).month}")
        grid = [[D_WALL if random.random() < 0.45 else D_FLOOR 
                 for _ in range(D_MAP_W)] for _ in range(D_MAP_H)]

        for _ in range(4):
            new_grid = [row[:] for row in grid]
            for y in range(1, D_MAP_H - 1):
                for x in range(1, D_MAP_W - 1):
                    wall_count = 0
                    for dy in [-1, 0, 1]:
                        for dx in [-1, 0, 1]:
                            if grid[y + dy][x + dx] == D_WALL:
                                wall_count += 1
                    new_grid[y][x] = D_WALL if wall_count > 4 else D_FLOOR
            grid = new_grid

        for y in range(D_MAP_H):
            grid[y][0] = grid[y][D_MAP_W - 1] = D_WALL
        for x in range(D_MAP_W):
            grid[0][x] = grid[D_MAP_H - 1][x] = D_WALL
        return grid

    def remove_isolated_areas(self, grid):
        h, w = len(grid), len(grid[0])
        visited = set()
        areas = []
        for y in range(h):
            for x in range(w):
                if grid[y][x] == D_FLOOR and (x, y) not in visited:
                    areas.append(self._flood_fill(grid, x, y, visited))
        if not areas: return grid
        main_area = max(areas, key=len)
        for area in areas:
            if area is main_area: continue
            for tx, ty in area: grid[ty][tx] = D_WALL
        return grid

    def _flood_fill(self, grid, start_x, start_y, global_visited):
        area = []
        queue = [(start_x, start_y)]
        global_visited.add((start_x, start_y))
        h, w = len(grid), len(grid[0])
        while queue:
            cx, cy = queue.pop(0)
            area.append((cx, cy))
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < w and 0 <= ny < h:
                    if grid[ny][nx] == D_FLOOR and (nx, ny) not in global_visited:
                        global_visited.add((nx, ny))
                        queue.append((nx, ny))
        return area

    def place_objects(self, grid, floor: int):
        empty_cells = [(x, y) for y in range(D_MAP_H) 
                       for x in range(D_MAP_W) if grid[y][x] == D_FLOOR]
        if not empty_cells: return grid
        random.shuffle(empty_cells)

        sx, sy = empty_cells.pop()
        grid[sy][sx] = D_START
        dg_starts[floor] = (sx, sy)

        ex, ey = empty_cells.pop()
        grid[ey][ex] = D_STAIRS

        if floor % 10 == 0:
            bx, by = empty_cells.pop()
            grid[by][bx] = D_BASE
            dg_bases[floor] = (bx, by)

        if random.random() < 0.15:
            grid[empty_cells.pop()[1]][empty_cells.pop()[0]] = D_SHOP

        for _ in range(random.randint(3, 8)):
            if empty_cells:
                pos = empty_cells.pop()
                grid[pos[1]][pos[0]] = D_TRAP
        for _ in range(random.randint(2, 5)):
            if empty_cells:
                pos = empty_cells.pop()
                grid[pos[1]][pos[0]] = D_CHEST
        return grid

    def generate_full_map(self, floor: int):
        grid = self.generate_base_map(floor)
        grid = self.remove_isolated_areas(grid)
        grid = self.place_objects(grid, floor)
        return grid

    def d_ensure_map(self, floor: int):
        if floor in dg_maps: return
        dg_maps[floor] = self.generate_full_map(floor)
        print(f"✅ Dungeon: Floor {floor} generated.")
    # ================================================================
    #  3-1. Pillow：描画エンジン基礎
    # ================================================================
    def draw_dungeon_map(self, floor: int, player_x: int, player_y: int):
        """
        プレイヤーの現在地を中心に、視野範囲(D_VIEW_R)を描画した画像を生成する。
        """
        # 1. 描画範囲の計算
        # 半径が5なら、中心を含めて 5 + 1 + 5 = 11マス の一辺になる
        view_size = D_VIEW_R * 2 + 1
        canvas_px = view_size * TILE
        
        # 2. ベースキャンバスの作成 (RGBA)
        # 背景は真っ暗（視野外の色）で初期化
        image = Image.new("RGBA", (canvas_px, canvas_px), (0, 0, 0, 255))
        
        # 3. マップデータの取得（なければ生成）
        self.d_ensure_map(floor)
        grid = dg_maps[floor]
        biome_name, _, _, _, _ = self.get_biome_by_floor(floor)

        # 4. タイル描画ループ
        # プレイヤーを中心に、-D_VIEW_R から +D_VIEW_R の範囲をスキャン
        for dy in range(-D_VIEW_R, D_VIEW_R + 1):
            for dx in range(-D_VIEW_R, D_VIEW_R + 1):
                map_x = player_x + dx
                map_y = player_y + dy
                
                # キャンバス上の描画位置
                draw_x = (dx + D_VIEW_R) * TILE
                draw_y = (dy + D_VIEW_R) * TILE

                # マップの範囲内かチェック
                if 0 <= map_x < D_MAP_W and 0 <= map_y < D_MAP_H:
                    tile_id = grid[map_y][map_x]
                    
                    # バイオームとタイルIDに基づいた画像を取得 (1-2で実装済み)
                    tile_img = self.get_tile_image(biome_name, tile_id)
                    
                    # 指定位置に貼り付け
                    image.paste(tile_img, (draw_x, draw_y))
                else:
                    # マップ外は描画せず（初期値の黒のまま）
                    pass

        # 5. 特殊オブジェクトの追加（階段など）の描画
        # ※ ここでは基本タイルとして描画されているが、
        # 必要に応じてここでエフェクトを重ねる

        return image
    # ================================================================
    #  3-2. Pillow：キャラクターとUIの合成
    # ================================================================
    def draw_player_and_ui(self, base_image: Image.Image, floor: int, px: int, py: int):
        """
        背景画像にプレイヤーと現在の状況テキストを重ねる
        """
        # 1. プレイヤーの描画
        # 視野の中心座標を計算（D_VIEW_R=5 なら 5マス目）
        center_pos = (D_VIEW_R * TILE, D_VIEW_R * TILE)
        
        # プレイヤー画像(AGO.PNG)を取得して合成
        player_img = self.assets["entities"].get("player")
        if player_img:
            # 透明度を維持して貼り付け
            base_image.alpha_composite(player_img, center_pos)
        else:
            # 画像がない場合の予備：赤い円を描画
            draw = ImageDraw.Draw(base_image)
            draw.ellipse([center_pos, (center_pos[0]+TILE, center_pos[1]+TILE)], fill="red")

        # 2. UIテキストの描画準備
        draw = ImageDraw.Draw(base_image)
        # config.py 等で定義されているマップデータを参照
        grid = dg_maps[floor]
        current_tile = grid[py][px]

        # 3. 足元の情報の表示（階段やショップなど）
        info_text = ""
        if current_tile == D_STAIRS: info_text = ">> EXIT <<"
        elif current_tile == D_SHOP: info_text = "$$ SHOP $$"
        elif current_tile == D_BASE: info_text = "== BASE =="
        elif current_tile == D_CHEST: info_text = "[ TREASURE ]"

        if info_text:
            # 画面下部に黒い帯を引いて文字を見やすくする
            canvas_w = base_image.width
            draw.rectangle([0, base_image.height - 20, canvas_w, base_image.height], fill=(0,0,0,180))
            draw.text((canvas_w//2 - 30, base_image.height - 18), info_text, fill="white")

        return base_image

    # --- 描画プロセスの統合 ---
    async def get_dungeon_view_image(self, floor: int, px: int, py: int):
        """
        3-1 と 3-2 を組み合わせて、Discord送信用の File オブジェクトを返す
        """
        # ステップ 3-1: 背景描画
        img = self.draw_dungeon_map(floor, px, py)
        # ステップ 3-2: キャラ・UI合成
        img = self.draw_player_and_ui(img, floor, px, py)
        
        # 1-3 で作ったユーティリティで Discord.File に変換
        return await self.get_image_as_file(img, filename=f"dungeon_F{floor}.png")
    # ================================================================
    #  4-1. Supabase：プレイヤーデータ連携
    # ================================================================
    async def db_load_player(self, user_id: int):
        """
        Supabase からプレイヤーの現在状況を読み込み、dg_players に同期する。
        データがない場合は初期位置（開始地点）を設定する。
        """
        uid = str(user_id)
        
        # 1. すでにメモリ(dg_players)にある場合はそれを返す
        if uid in dg_players:
            return dg_players[uid]

        # 2. DBから取得
        try:
            response = supabase.table("dungeon_players").select("*").eq("user_id", uid).execute()
            if response.data:
                data = response.data[0]
                dg_players[uid] = {
                    "floor": data["floor"],
                    "x": data["x"],
                    "y": data["y"],
                    "hp": data.get("hp", 100), # 必要に応じて拡張
                    "last_move": datetime.datetime.now(JST)
                }
                return dg_players[uid]
        except Exception as e:
            print(f"❌ DB Load Error (User: {uid}): {e}")

        # 3. データがない（新規プレイヤー）場合は1階の開始地点へ
        floor = 1
        self.d_ensure_map(floor)
        sx, sy = dg_starts.get(floor, (50, 50)) # 取得失敗時の安全策で中央
        
        new_player = {
            "floor": floor,
            "x": sx,
            "y": sy,
            "hp": 100,
            "last_move": datetime.datetime.now(JST)
        }
        dg_players[uid] = new_player
        
        # 新規作成をDBに保存
        await self.db_save_player(user_id)
        return new_player

    async def db_save_player(self, user_id: int):
        """
        現在のメモリ上のプレイヤー状態を Supabase へ書き込む (Upsert)
        """
        uid = str(user_id)
        if uid not in dg_players:
            return

        p = dg_players[uid]
        save_data = {
            "user_id": uid,
            "floor": p["floor"],
            "x": p["x"],
            "y": p["y"],
            "hp": p["hp"],
            "updated_at": datetime.datetime.now(JST).isoformat()
        }

        try:
            # upsert: すでにあれば更新、なければ挿入
            supabase.table("dungeon_players").upsert(save_data).execute()
        except Exception as e:
            print(f"❌ DB Save Error (User: {uid}): {e}")
    # ================================================================
    #  4-2. Supabase：マップ・拠点データの保存と復元
    # ================================================================
    async def db_save_map(self, floor: int):
        """
        指定階層のマップデータを JSON 形式で Supabase に保存する。
        """
        if floor not in dg_maps:
            return

        grid_data = dg_maps[floor]
        # JSON 文字列に変換して保存 (Supabaseの text型 または jsonb型 を想定)
        grid_json = json.dumps(grid_data)
        
        save_data = {
            "floor": floor,
            "map_data": grid_json,
            "start_pos": json.dumps(dg_starts.get(floor)),
            "base_pos": json.dumps(dg_bases.get(floor)),
            "updated_at": datetime.datetime.now(JST).isoformat()
        }

        try:
            supabase.table("dungeon_maps").upsert(save_data).execute()
        except Exception as e:
            print(f"❌ DB Map Save Error (Floor: {floor}): {e}")

    async def db_load_all_maps(self):
        """
        起動時に DB から全階層のマップデータを読み込み、メモリ(dg_maps等)に展開する。
        """
        try:
            res = supabase.table("dungeon_maps").select("*").execute()
            if not res.data:
                return

            for item in res.data:
                fl = item["floor"]
                dg_maps[fl] = json.loads(item["map_data"])
                if item.get("start_pos"):
                    dg_starts[fl] = tuple(json.loads(item["start_pos"]))
                if item.get("base_pos"):
                    dg_bases[fl] = tuple(json.loads(item["base_pos"]))
            
            print(f"✅ Loaded {len(res.data)} maps from DB.")
        except Exception as e:
            print(f"❌ DB Map Load Error: {e}")

    # ================================================================
    #  初期化プロセスの更新
    # ================================================================
    async def cog_load(self):
        """
        1-3 までの初期化に加え、DBからのマップ復元を追加
        """
        self.load_all_images()
        self.verify_assets()
        
        # --- 追加: 起動時にDBからマップをロード ---
        await self.db_load_all_maps()
        
        print(f"✅ DungeonCog: Initialization complete (JST: {datetime.datetime.now(JST)})")
    # ================================================================
    #  5-1. 移動・衝突判定
    # ================================================================
    async def move_player(self, user_id: int, dx: int, dy: int):
        """
        プレイヤーを(dx, dy)方向に移動させる。
        戻り値: (成功か失敗か, メッセージ)
        """
        uid = str(user_id)
        
        # 1. プレイヤーデータのロード (4-1の実装を使用)
        p = await self.db_load_player(user_id)
        floor = p["floor"]
        
        # 2. マップデータの準備
        self.d_ensure_map(floor)
        grid = dg_maps[floor]
        
        # 3. 移動先座標の計算
        new_x = p["x"] + dx
        new_y = p["y"] + dy
        
        # 4. 衝突判定
        # マップの範囲外、または「壁(D_WALL)」の場合は移動不可
        if not (0 <= new_x < D_MAP_W and 0 <= new_y < D_MAP_H):
            return False, "マップの端で行き止まりだ。"
            
        if grid[new_y][new_x] == D_WALL:
            return False, "壁があって進めない。"

        # 5. 座標の更新
        p["x"] = new_x
        p["y"] = new_y
        p["last_move"] = datetime.datetime.now(JST)
        
        # 6. DBへ保存 (4-1の実装を使用)
        await self.db_save_player(user_id)
        
        return True, "移動した。"
    # ================================================================
    #  5-2. タイルイベント発火システム
    # ================================================================
    async def process_tile_event(self, user_id: int):
        """
        プレイヤーの現在地のタイルに応じたイベントを実行する。
        戻り値: (イベントメッセージ, 追加フラグ)
        """
        uid = str(user_id)
        p = dg_players[uid]
        floor = p["floor"]
        grid = dg_maps[floor]
        
        tile_id = grid[p["y"]][p["x"]]
        event_msg = ""
        special_flag = None # 'stairs', 'shop' など

        # 1. 階段 (D_STAIRS)
        if tile_id == D_STAIRS:
            event_msg = "🛗 **階段を見つけた！** \n`!next` で次の階層へ進めます。"
            special_flag = "stairs"

        # 2. 罠 (D_TRAP)
        elif tile_id == D_TRAP:
            damage = random.randint(5, 15)
            p["hp"] = max(0, p["hp"] - damage)
            event_msg = f"⚠️ **罠を踏んだ！** \n{damage} のダメージを受けた！ (残りHP: {p['hp']})"
            # 罠は一度踏んだら消える設定（任意）
            grid[p["y"]][p["x"]] = D_FLOOR 

        # 3. 宝箱 (D_CHEST)
        elif tile_id == D_CHEST:
            gold_gain = random.randint(20, 100)
            # config.py 等に所持金データがある場合はここで加算
            # ここではメッセージのみ
            event_msg = f"🎁 **宝箱を開けた！** \n{gold_gain} G を手に入れた！"
            grid[p["y"]][p["x"]] = D_FLOOR

        # 4. ショップ (D_SHOP)
        elif tile_id == D_SHOP:
            event_msg = "💰 **怪しい商人だ。** \n何か買っていきますか？"
            special_flag = "shop"

        # 5. 拠点 (D_BASE)
        elif tile_id == D_BASE:
            p["hp"] = 100 # 全回復
            event_msg = "🏡 **拠点に到着した。** \n体力が全回復した！"

        # 変更があればDBに保存
        if tile_id in [D_TRAP, D_CHEST, D_BASE]:
            await self.db_save_player(user_id)

        return event_msg, special_flag
    # ================================================================
    #  5-3. エンカウント・戦闘計算機
    # ================================================================
    async def check_encounter(self, user_id: int):
        """
        移動後にエンカウント判定を行い、遭遇した場合は戦闘処理を実行する。
        戻り値: 戦闘ログ（遭遇しなかった場合は None）
        """
        uid = str(user_id)
        p = dg_players[uid]
        floor = p["floor"]

        # 1. エンカウント判定 (config.py の確率を使用、デフォルト10%など)
        # 床(D_FLOOR)の上でのみエンカウントが発生するようにする
        grid = dg_maps[floor]
        if grid[p["y"]][p["x"]] != D_FLOOR:
            return None

        if random.random() > 0.10: # 10%の確率で遭遇
            return None

        # 2. 敵の生成 (階層に応じて強さをスケーリング)
        enemy_hp = 20 + (floor * 5)
        enemy_atk = 5 + (floor * 2)
        
        # プレイヤーの攻撃力（本来は装備品などで計算するが、ここでは簡易版）
        player_atk = 15 + (floor // 2) 

        log = ["👾 **モンスターに遭遇した！**"]
        
        # 3. 簡易ターン制バトル (最大5ターン)
        for turn in range(1, 6):
            # プレイヤーの攻撃
            dmg_to_enemy = max(1, player_atk + random.randint(-2, 2))
            enemy_hp -= dmg_to_enemy
            log.append(f"└ ターン{turn}: {dmg_to_enemy} のダメージを与えた！")

            if enemy_hp <= 0:
                exp = floor * 10
                log.append(f"✨ **勝利！** {exp} の経験値を獲得。")
                break
            
            # 敵の攻撃
            dmg_to_player = max(1, enemy_atk - 5 + random.randint(-1, 1))
            p["hp"] = max(0, p["hp"] - dmg_to_player)
            log.append(f"  └ 敵の反撃: {dmg_to_player} のダメージを受けた！")

            if p["hp"] <= 0:
                log.append("💀 **目の前が真っ暗になった...**")
                # 死亡処理: 1階の開始地点へ戻す
                p["floor"] = 1
                p["hp"] = 100
                sx, sy = dg_starts.get(1, (50, 50))
                p["x"], p["y"] = sx, sy
                break
        else:
            log.append("💨 決着がつかず、モンスターは逃げ去った。")

        # 4. 結果をDBに保存
        await self.db_save_player(user_id)
        
        return "\n".join(log)
# ================================================================
#  6-1. Discord UI：移動ボタンパネル
# ================================================================
class DungeonView(discord.ui.View):
    def __init__(self, cog, user_id):
        super().__init__(timeout=60) # 60秒でタイムアウト
        self.cog = cog
        self.user_id = user_id

    async def handle_move(self, interaction: discord.Interaction, dx: int, dy: int):
        """移動ボタンが押された時の共通処理"""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("これは他のプレイヤーの操作パネルです。", ephemeral=True)
            return

        # 1-1 で実装したロックを取得（連打防止）
        async with self.cog.get_lock(self.user_id):
            # 1. 移動実行 (5-1)
            success, msg = await self.cog.move_player(self.user_id, dx, dy)
            if not success:
                await interaction.response.edit_message(content=f"⚠️ {msg}")
                return

            # 2. イベント・戦闘判定 (5-2, 5-3)
            event_log, special_flag = await self.cog.process_tile_event(self.user_id)
            battle_log = await self.cog.check_encounter(self.user_id)

            # 3. 新しい画像の生成 (3-1, 3-2)
            p = dg_players[str(self.user_id)]
            file = await self.cog.get_dungeon_view_image(p["floor"], p["x"], p["y"])

            # 4. メッセージの組み立て
            full_msg = f"階層: {p['floor']}F | HP: {p['hp']}\n"
            if event_log: full_msg += f"{event_log}\n"
            if battle_log: full_msg += f"{battle_log}\n"

            # 5. Discord上の表示を更新
            await interaction.response.edit_message(content=full_msg, attachments=[file], view=self)

    # --- ボタン配置（3x3のグリッドを想定） ---
    @discord.ui.button(label="↖️", style=discord.ButtonStyle.secondary, row=0)
    async def nw(self, intx, btn): await self.handle_move(intx, -1, -1)
    
    @discord.ui.button(label="⬆️", style=discord.ButtonStyle.primary, row=0)
    async def n(self, intx, btn): await self.handle_move(intx, 0, -1)
    
    @discord.ui.button(label="↗️", style=discord.ButtonStyle.secondary, row=0)
    async def ne(self, intx, btn): await self.handle_move(intx, 1, -1)

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.primary, row=1)
    async def w(self, intx, btn): await self.handle_move(intx, -1, 0)
    
    @discord.ui.button(label="●", style=discord.ButtonStyle.danger, row=1)
    async def center(self, intx, btn): 
        # 中心ボタンは「更新」として機能
        await self.handle_move(intx, 0, 0)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.primary, row=1)
    async def e(self, intx, btn): await self.handle_move(intx, 1, 0)

    @discord.ui.button(label="↙️", style=discord.ButtonStyle.secondary, row=2)
    async def sw(self, intx, btn): await self.handle_move(intx, -1, 1)
    
    @discord.ui.button(label="⬇️", style=discord.ButtonStyle.primary, row=2)
    async def s(self, intx, btn): await self.handle_move(intx, 0, 1)
    
    @discord.ui.button(label="↘️", style=discord.ButtonStyle.secondary, row=2)
    async def se(self, intx, btn): await self.handle_move(intx, 1, 1)
    # ================================================================
    #  6-2. 起動コマンド：!d
    # ================================================================
    @commands.command(name="d")
    async def enter_dungeon(self, ctx):
        """
        ダンジョン探索を開始、または現在の状況を表示する。
        """
        user_id = ctx.author.id
        
        # 1. ローディングメッセージ（画像生成に時間がかかる場合があるため）
        wait_msg = await ctx.send("🔦 ダンジョンの奥を確認中...")

        try:
            # 2. プレイヤーデータのロード（4-1で実装）
            p = await self.db_load_player(user_id)
            floor = p["floor"]

            # 3. マップの存在確認と生成（2-3で実装）
            self.d_ensure_map(floor)

            # 4. 現在地の画像生成（3-2で実装）
            file = await self.get_dungeon_view_image(floor, p["x"], p["y"])

            # 5. 操作パネル(View)の作成（6-1で実装）
            view = DungeonView(self, user_id)

            # 6. 本送信
            content = f"🏰 **ダンジョン探索中** ({floor}F)\n👤 **{ctx.author.display_name}** | HP: {p['hp']}"
            await ctx.send(content=content, file=file, view=view)

            # 7. ローディングメッセージを消去
            await wait_msg.delete()

        except Exception as e:
            await wait_msg.edit(content=f"❌ 探索中にエラーが発生しました: {e}")
            print(f"Dungeon Error (!d): {e}")

    # ================================================================
    #  6-3. 階層移動コマンド：!next
    # ================================================================
    @commands.command(name="next")
    async def go_next_floor(self, ctx):
        """階段(D_STAIRS)にいる場合、次の階層へ進む"""
        uid = str(ctx.author.id)
        if uid not in dg_players:
            return await ctx.send("まずは `!d` でダンジョンに入ってください。")

        p = dg_players[uid]
        grid = dg_maps[p["floor"]]
        
        if grid[p["y"]][p["x"]] != D_STAIRS:
            return await ctx.send("ここには階段がありません。")

        # 次の階層へ
        p["floor"] += 1
        self.d_ensure_map(p["floor"])
        
        # 次の階の開始地点へ移動
        sx, sy = dg_starts[p["floor"]]
        p["x"], p["y"] = sx, sy
        
        await self.db_save_player(ctx.author.id)
        await ctx.send(f"🛗 {p['floor']}階へ降りました。`!d` で探索を再開しましょう！")
async def setup(bot):
    await bot.add_cog(DungeonCog(bot))