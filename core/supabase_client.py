# -*- coding: utf-8 -*-
"""Supabase クライアントを 1 か所で作るためのモジュール。

キーの選び方:
  - 通常は SUPABASE_KEY（anon キー）を使う。Bot はこの前提で作られている。
  - SUPABASE_SERVICE_ROLE_KEY は任意の上書き用（既定では未設定）。設定されていればそちらを使う。

キーそのものはログに出さない。JWT の "role" クレームだけを（署名検証なしで）読んで、
どの種類のキーで動いているかを起動時に 1 回だけ表示する。
"""
import base64
import json
import logging
import os
import threading

log = logging.getLogger(__name__)

_lock = threading.Lock()
_client = None
_client_ready = False
_announced = False


def select_key(env=None):
    """(key, env_name) を返す。どちらも無ければ (None, None)。"""
    env = os.environ if env is None else env
    for name in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY"):
        value = (env.get(name) or "").strip()
        if value:
            return value, name
    return None, None


def key_role(key):
    """JWT の payload から role を取り出す（署名は検証しない）。読めなければ 'unknown'。"""
    try:
        payload = key.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        role = json.loads(base64.urlsafe_b64decode(payload)).get("role")
        return role if isinstance(role, str) and role else "unknown"
    except Exception:
        return "unknown"


def describe_key(env=None):
    """ログ用の説明文。キーそのものは含めない。"""
    key, name = select_key(env)
    if not key:
        return "Supabase key: not set"
    return f"Supabase key: {name} (role={key_role(key)})"


def create_client_from_env(env=None):
    """環境変数から新しいクライアントを作る。URL かキーが無ければ None。"""
    env = os.environ if env is None else env
    url = (env.get("SUPABASE_URL") or "").strip()
    key, _ = select_key(env)
    if not url or not key:
        return None
    import supabase as supabase_module  # テストで create_client を差し替えられるよう属性経由で呼ぶ
    return supabase_module.create_client(url, key)


def get_client():
    """プロセス全体で共有するクライアント（初回だけ作成し、種類をログに出す）。"""
    global _client, _client_ready, _announced
    with _lock:
        if not _client_ready:
            _client = create_client_from_env()
            _client_ready = True
        if not _announced:
            _announced = True
            text = describe_key()
            log.info(text)
            print(text)
        return _client


def _reset_for_tests():
    global _client, _client_ready, _announced
    with _lock:
        _client, _client_ready, _announced = None, False, False
