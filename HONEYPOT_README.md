# Honeypot Kick Feature

## Apply

From repo root after checkout of this branch:

```bash
cp artifacts/honeypot/support.py cogs/support.py
cp artifacts/honeypot/general.py cogs/general.py
```

Or apply the patches:

```bash
patch -p0 < artifacts/honeypot/honeypot-support.patch
patch -p0 < artifacts/honeypot/honeypot-general.patch
```

## Summary
- `/support` → モデレーション → ハニーポット
- チャンネル選択 → 警告パネル設置（Components V2 Container、白基調 `color=0xFFFFFF`）
- ハニーポットチャンネルへの投稿 → ソフトバン（`delete_message_days=7` + unban）でキック相当＋メッセージ削除
- 管理者 / manage_guild / ban_members / Bot は対象外
- 設定パネルも白基調 Components V2（`as_panel_v2`）
