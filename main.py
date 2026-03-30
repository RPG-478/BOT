# -*- coding: utf-8 -*-
import os
import discord
import datetime
import config

def format_log(message: str) -> str:
    """JST（日本時間）を付与した標準的なログフォーマット"""
    # config.get_now() があればそれを使用、なければ現在時刻
    try:
        now = config.get_now().strftime('%Y-%m-%d %H:%M:%S')
    except AttributeError:
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return f"[{now}] {message}"

def get_asset_path(filename: str) -> str:
    path = os.path.join("Assets", filename)
    if not os.path.exists(path):
        print(format_log(f"Warning: Asset not found at {path}"))
    return path

async def send_error_embed(ctx, error_message: str):
    embed = discord.Embed(
        title="エラーが発生しました",
        description=error_message,
        color=discord.Color.red()
    )
    if isinstance(ctx, discord.Interaction):
        await ctx.response.send_message(embed=embed, ephemeral=True)
    else:
        await ctx.send(embed=embed)

def get_options_from_list(items, battle_stats, filter_type=None):
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
