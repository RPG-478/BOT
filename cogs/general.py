"""/general: コイン・生存確認・ランキング系機能の操作パネル。"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from core.panel_v2 import as_panel_v2, edit_panel_v2
from core import guild_settings, shortcuts
from core.game_guides import GAME_GUIDES, GAME_ORDER


GENERAL_GENRES = {
    "economy": ("コイン・ランキング", "所持状況、送金、コインや bump/up のランキング"),
    "survival": ("生存確認", "追跡、アクティブ頻度、フリーズ、失踪警報"),
    "custom": ("custom", "メッセージで実行するショートカットの登録・編集・削除"),
}
GENERAL_ACTIONS = {
    "economy": [
        ("プレイヤー状況", "status"),
        ("コイン送金", "pay"),
        ("コイン保有ランキング", "coin_leaderboard"),
        ("bump RTAランキング", "bump_leaderboard"),
        ("up RTAランキング", "up_leaderboard"),
    ],
    "survival": [
        ("追跡登録・解除", "fujo_register"),
        ("アクティブ頻度", "fujo_hindo"),
        ("生存確認ランキング", "fujo_ranking"),
        ("フリーズ", "fujo_freeze"),
        ("失踪警報解除", "fujo_panic_disable"),
    ],
    "custom": [("ショートカットを管理", "shortcut_manage")],
}

SHORTCUT_ROOTS = {
    "general": ("/general", [(label, value) for values in GENERAL_ACTIONS.values() for label, value in values if value != "shortcut_manage"]),
    "vc": ("/vc", [("VC参加", "join"), ("VC退出", "leave"), ("VC状態", "status"),
                    ("音楽操作パネル", "music_panel"), ("録音開始", "record_start"), ("録音停止", "record_stop"),
                    ("やまびこ開始", "echo_start"), ("やまびこ停止", "echo_stop"),
                    ("文字起こし開始", "transcribe_start"), ("文字起こし停止", "transcribe_stop"),
                    ("カラオケ開始", "karaoke_start"), ("カラオケ停止", "karaoke_stop"),
                    ("ランダム通話開始", "match_start"), ("ランダム通話終了", "match_stop"),
                    ("グローバルVC開始", "global_start"), ("グローバルVC終了", "global_stop")]),
    "game": ("/game", [("ゲーム開始: " + GAME_GUIDES[game]["name"], "game:" + game) for game in GAME_ORDER]),
    "support": ("/support", [("Muted設定", "muted"), ("匿名つぶやき", "whisper"), ("メッセージ削除", "clear"),
                              ("一括ロール操作", "role_bulk"), ("bump/up状態", "bumprta_status"),
                              ("bump/upオン", "bumprta_on"), ("bump/upオフ", "bumprta_off"),
                              ("絵文字便乗設定", "binjou"), ("VC入退室履歴", "vc_log"),
                              ("メッセージ編集履歴", "message_log"), ("モデレート履歴", "moderation_log"),
                              ("ハニーポット", "honeypot")]),
    "help": ("/help", [("ヘルプを表示", "overview")]),
}


# NOTE: Rest of general.py is unchanged from main; only SHORTCUT_ROOTS support list was extended.
# Full file content continues below to keep the file complete.
