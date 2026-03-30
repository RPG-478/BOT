# -*- coding: utf-8 -*-
import os
import discord
import config  # config.py から JST や supabase を参照

def format_log(message: str) -> str:
    """
    JST（日本時間）を付与した標準的なログフォーマットを返します。
    """
    now = config.get_now().strftime('%Y-%m-%d %H:%M:%S')
    return f"[{now}] {message}"

def get_asset_path(filename: str) -> str:
    """
    Assets フォルダ内のファイルパスを安全に取得します。
    """
    path = os.path.join("Assets", filename)
    if not os.path.exists(path):
        print(format_log(f"Warning: Asset not found at {path}"))
    return path

async def send_error_embed(ctx, error_message: str):
    """
    共通のエラー埋め込みメッセージを送信します。
    """
    embed = discord.Embed(
        title="エラーが発生しました",
        description=error_message,
        color=discord.Color.red()
    )
    await ctx.send(embed=embed)

# --- 汎用セレクトシステム ---

def get_options_from_list(items, filter_type=None):
    """
    リスト（手札や盤面）をスキャンして、SelectOptionのリストを返す。
    items: カードデータのリスト
    filter_type: "戦闘" や "サポート" など。Noneなら全表示。
    """
    options = []
    for i, card in enumerate(items):
        if filter_type is None or card.get("type") == filter_type:
            # 戦闘カードならスタッツを表示、そうでなければ種別を表示
            if card.get("type") == "戦闘":
                from pault_game import BATTLE_STATS # 循環参照に注意（必要に応じて関数内でインポート）
                s = BATTLE_STATS.get(card["name"], [0, 0])
                label = f"{card['name']} (ATK:{s[0]}/DFN:{s[1]})"
            else:
                label = f"{card['name']} [{card.get('type', '不明')}]"
                
            options.append(discord.SelectOption(label=label, value=str(i)))
    return options