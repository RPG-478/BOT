import io
import base64
import aiohttp
import random
import os
import discord
from discord import app_commands
from discord.ext import commands

# cogs.dangeon から必要な関数・定数をインポート
from cogs.dangeon import (
    d_get_player,
    d_build_map_image,
    d_render_pillow,
    d_get_cell,
    d_ensure_map,
    d_consume,
    d_open_chest,
    d_trigger_trap,
    d_do_mine,
    d_make_enemy,
    d_apply_reward,
    DungeonCombatView,
    d_get_biome,
    dg_save_player,
    dg_save_map,
    dg_starts,
    D_MAP_W,
    D_MAP_H,
    D_WALL,
    D_STAIRS,
    D_CHEST,
    D_TRAP,
    D_MINE,
    D_FLOORS,
    D_ENCOUNTER_RATES
)

D1_ENDPOINT = os.environ.get("D1_ENDPOINT", "http://127.0.0.1:8082/v1/systemone")

class D1DungeonPlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _call_d1(self, state_str: str, questions: dict, b64_img: str) -> str:
        payload = {
            "state": state_str,
            "images": [f"data:image/png;base64,{b64_img}"],
            "questions": questions
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(D1_ENDPOINT, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        q_key = list(questions.keys())[0]
                        return res.get("answers", {}).get(q_key, {}).get("choice", "")
        except Exception:
            pass
        return ""

    @app_commands.command(name="d1_dungeon", description="D1-omniにダンジョンを1ターン操作させます")
    async def d1_dungeon(self, interaction: discord.Interaction):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        p = d_get_player(uid)
        floor, x, y = p["floor"], p["x"], p["y"]
        supabase = getattr(self.bot, "supabase", None)

        # マップ画像の生成と Base64 化
        pil_img = d_build_map_image(uid, floor, x, y)
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        b64_img = base64.b64encode(buf.getvalue()).decode("utf-8")

        current_cell = d_get_cell(floor, x, y)

        # 1. 階段マスにいる場合
        if current_cell == D_STAIRS:
            questions = {
                "stairs_action": {
                    "type": "choice",
                    "instructions": "You reached stairs. Select whether to go to the next floor or stay.",
                    "criteria": {
                        "stairs_up": "Proceed to the next upper floor and fully restore HP",
                        "stairs_back": "Stay on current floor and continue exploring"
                    }
                }
            }
            state_str = f"Floor {floor} ({x}, {y}) - On Stairs Tile. HP: {p['hp']}/{p['max_hp']}"
            choice = await self._call_d1(state_str, questions, b64_img)

            if choice == "stairs_up" and floor < D_FLOORS:
                p["floor"] = floor + 1
                p["hp"] = p["max_hp"]
                d_ensure_map(p["floor"])
                sx, sy = dg_starts[p["floor"]]
                p["x"], p["y"] = sx, sy
                if supabase:
                    await dg_save_player(uid, supabase)
                await interaction.followup.send(f"🤖 **D1の判断**: `stairs_up` を選択。フロア {p['floor']} へ進みました。")
                return
            else:
                await interaction.followup.send(f"🤖 **D1の判断**: `stairs_back` を選択。そのまま探索を続けます。")
                return

        # 2. 鉱山マスにいる場合
        elif current_cell == D_MINE:
            questions = {
                "mine_action": {
                    "type": "choice",
                    "instructions": "You found a mine. Select whether to mine coins or leave.",
                    "criteria": {
                        "mine": "Dig and mine coins from the mine",
                        "mine_back": "Leave the mine without digging"
                    }
                }
            }
            state_str = f"Floor {floor} ({x}, {y}) - On Mine Tile. HP: {p['hp']}/{p['max_hp']}"
            choice = await self._call_d1(state_str, questions, b64_img)

            if choice == "mine":
                gain = d_do_mine(uid)
                await d_apply_reward(uid, supabase, coins=gain)
                d_consume(floor, x, y)
                if supabase:
                    await dg_save_map(floor, supabase)
                await interaction.followup.send(f"🤖 **D1の判断**: `mine` を選択。採掘で +{gain} コイン獲得しました。")
                return
            else:
                await interaction.followup.send(f"🤖 **D1の判断**: `mine_back` を選択。採掘せずに戻りました。")
                return

        # 3. 通常探索移動（※ status 選択肢を除外）
        questions = {
            "move_action": {
                "type": "choice",
                "instructions": "Select the next direction to move or action to take in the dungeon.",
                "criteria": {
                    "up": "Move north / up",
                    "down": "Move south / down",
                    "left": "Move west / left",
                    "right": "Move east / right",
                    "leftup": "Move northwest",
                    "rightup": "Move northeast",
                    "leftdown": "Move southwest",
                    "rightdown": "Move southeast",
                    "check": "Stay on current tile and check surroundings"
                }
            }
        }
        state_str = f"Floor {floor} ({x}, {y}) - Exploring. HP: {p['hp']}/{p['max_hp']}"
        choice = await self._call_d1(state_str, questions, b64_img)

        # 移動方向の適用処理
        move_map = {
            "up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0),
            "leftup": (-1, -1), "rightup": (1, -1), "leftdown": (-1, 1), "rightdown": (1, 1),
            "check": (0, 0)
        }

        if choice in move_map:
            dx, dy = move_map[choice]
            nx, ny = x + dx, y + dy

            if choice != "check":
                corner_cut = (
                    dx != 0 and dy != 0 and (
                        d_get_cell(floor, x + dx, y) == D_WALL
                        or d_get_cell(floor, x, y + dy) == D_WALL
                    )
                )
                if (not (0 <= nx < D_MAP_W and 0 <= ny < D_MAP_H)
                        or d_get_cell(floor, nx, ny) == D_WALL
                        or corner_cut):
                    await interaction.followup.send(f"🤖 **D1の判断**: `{choice}` を選択しましたが、壁のため移動できませんでした。")
                    return
                p["x"], p["y"] = nx, ny
                x, y = nx, ny

            msg = f"🤖 **D1の判断**: `{choice}` を実行しました。（現在位置: {x}, {y}）"
            target_cell = d_get_cell(floor, x, y)

            # 各種マスイベントの適用
            if target_cell == D_CHEST:
                chest_msg, reward = d_open_chest(uid, supabase)
                await d_apply_reward(uid, supabase, **reward)
                d_consume(floor, x, y)
                if supabase:
                    await dg_save_map(floor, supabase)
                msg += f"\n結果: {chest_msg}"

            elif target_cell == D_TRAP:
                trap_msg, penalty = d_trigger_trap(uid)
                await d_apply_reward(uid, supabase, **penalty)
                d_consume(floor, x, y)
                if supabase:
                    await dg_save_map(floor, supabase)
                msg += f"\n結果: {trap_msg}"

            else:
                bname, _, _, _, _ = d_get_biome(floor)
                rate = D_ENCOUNTER_RATES.get(bname, 0.10)
                if random.random() < rate:
                    enemy = d_make_enemy(floor)
                    combat = DungeonCombatView(uid, floor, x, y, enemy, supabase)
                    map_file = d_render_pillow(uid, floor, x, y)
                    await interaction.followup.send(
                        content=msg + f"\n敵が現れた: **{enemy['name']}**",
                        embed=combat._embed(), view=combat, file=map_file
                    )
                    return

            if supabase:
                await dg_save_player(uid, supabase)

            await interaction.followup.send(msg)
        else:
            await interaction.followup.send("🤖 **D1の判断**: 判定結果の取得に失敗しました。")

async def setup(bot: commands.Bot):
    await bot.add_cog(D1DungeonPlayerCog(bot))
