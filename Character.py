import discord
from discord import app_commands
import json
import os
import requests
# ===== UID保存 =====
UID_FILE = "uid_data.json"
if os.path.exists(UID_FILE):
    with open(UID_FILE, "r") as f:
        uid_data = json.load(f)
else:
    uid_data = {}
def save_uid():
    with open(UID_FILE, "w") as f:
        json.dump(uid_data, f, indent=4)
# ===== UID登録 =====
@client.tree.command(name="register", description="スタレUIDを登録")
async def register(interaction: discord.Interaction, uid: str):

    user_id = str(interaction.user.id)

    if not uid.isdigit():
        await interaction.response.send_message("❌ UIDは数字のみです", ephemeral=True)
        return

    uid_data[user_id] = uid
    save_uid()

    await interaction.response.send_message(
        f"✅ UID `{uid}` を登録しました！",
        ephemeral=True
    )
# ===== UID確認 =====
@client.tree.command(name="uid", description="登録したUIDを確認")
async def check_uid(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id not in uid_data:
        await interaction.response.send_message("❌ UIDが登録されていません", ephemeral=True)
        return
    await interaction.response.send_message(
        f"あなたのUID: `{uid_data[user_id]}`",
        ephemeral=True
    )
# ===== UID削除 =====
@client.tree.command(name="uid_delete", description="UIDを削除")
async def delete_uid(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id not in uid_data:
        await interaction.response.send_message("❌ 登録されていません", ephemeral=True)
        return
    del uid_data[user_id]
    save_uid()
    await interaction.response.send_message("🗑️ UIDを削除しました", ephemeral=True)
# ===== 所持キャラ表示 =====
@client.tree.command(name="characters", description="所持キャラを表示")
async def characters(interaction: discord.Interaction):
    await interaction.response.defer()
    user_id = str(interaction.user.id)
    if user_id not in uid_data:
        await interaction.followup.send("❌ UIDを登録してください (/register)", ephemeral=True)
        return
    uid = uid_data[user_id]
    try:
        url = f"https://api.mihomo.me/sr_info_parsed/{uid}?lang=ja"
        data = requests.get(url).json()
        player_name = data["player"]["nickname"]
        chars = data["characters"]
        # キャラ名一覧
        char_list = []
        for c in chars:
            name = c["name"]
            level = c["level"]
            char_list.append(f"{name} Lv.{level}")
        description = "\n".join(char_list[:25])
        embed = discord.Embed(
            title=f"{player_name} の所持キャラ",
            description=description,
            color=0x00ffcc
        )
        embed.set_footer(text=f"表示: {len(chars)}体中 {min(len(chars),25)}体")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send("❌ データ取得に失敗しました", ephemeral=True)
        print(e)
