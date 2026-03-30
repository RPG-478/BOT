# ~/BOT/defining.py
# -*- coding: utf-8 -*-
import os
import discord
import config  # config.py から JST や supabase を参照

def format_log(message: str) -> str:
    """
    JST（日本時間）を付与した標準的なログフォーマットを返します。
    """
    # config.get_now() を使うことで、JST（日本時間）に統一されます
    now = config.get_now().strftime('%Y-%m-%d %H:%M:%S')
    return f"[{now}] {message}"

def get_asset_path(filename: str) -> str:
    """
    Assets フォルダ内のファイルパスを安全に取得します。
    画像などのリソース管理用です。
    """
    path = os.path.join("Assets", filename)
    if not os.path.exists(path):
        # 警告ログを出す（開発時に役立ちます）
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

def get_options_from_list(items, battle_stats, filter_type=None):
    """
    カードリストからセレクトメニューの選択肢を生成します。
    battle_statsを引数に取ることで、循環参照を回避しています。
    """
    options = []
    for i, card in enumerate(items):
        if filter_type is None or card.get("type") == filter_type:
            if card.get("type") == "戦闘":
                s = battle_stats.get(card["name"], [0, 0])
                label = f"{card['name']} (ATK:{s[0]}/DFN:{s[1]})"
            else:
                label = f"{card['name']} [{card.get('type', '不明')}]"
                
            options.append(discord.SelectOption(label=label, value=str(i)))
    return options

class GenericPickerView(discord.ui.View):
    """汎用的なカード選択用Viewクラスです。"""
    def __init__(self, options, min_v, max_v, placeholder, callback_func):
        super().__init__(timeout=None)
        select = discord.ui.Select(
            placeholder=placeholder,
            min_values=min_v,
            max_values=max_v,
            options=options
        )
        async def internal_callback(interaction):
            indices = [int(v) for v in select.values]
            await callback_func(interaction, indices)
        select.callback = internal_callback
        self.add_item(select)