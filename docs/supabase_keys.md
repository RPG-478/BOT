# Supabase キーの扱い

AGOBOT は **anon キー（`SUPABASE_KEY`）で動く前提** で作られています。
Supabase クライアントは `core/supabase_client.py` で 1 つだけ作り、Bot 全体で共有します。
起動時に、どの種類のキーを使っているかだけをログに 1 回出します（キーそのものは出しません）。

```
Supabase key: SUPABASE_KEY (role=anon)
```

## キーが漏れたときの作り直し

1. Supabase の Project Settings → API（JWT Keys）で JWT シークレットを作り直す。anon キーも service_role キーも変わります。
2. 新しい anon キーを、次の 3 か所の `SUPABASE_KEY` に入れる。
   - AGOBOT（ラズパイ）の `.env` → Bot を再起動
   - TYPETA の Bot の `.env` → Bot を再起動
   - Vercel の Environment Variables の `SUPABASE_KEY` → Redeploy
3. AGOBOT の起動ログに `Supabase key: SUPABASE_KEY (role=anon)` と出ることを確認する。

## （任意・将来）service_role キーへの移行

いまは行いません。将来 anon キーを読み取り専用に絞りたくなったときのメモです。

1. `.env` に `SUPABASE_SERVICE_ROLE_KEY=<service_role キー>` を足すと、`SUPABASE_KEY` より優先して使われます（既定では未設定）。
2. 起動ログが `role=service_role` になったことを確認する。
3. TYPETA の Bot も同じように切り替える。
4. 両方の Bot が動くのを確かめてから、Luna が権限を絞る SQL を PR で出し、TYPETA のレビュー後に本番へ入れる。

## 注意

- キーは Discord などのチャットに絶対に貼らないでください。
- service_role キーは Vercel（サイト）には絶対に入れないでください。サイトは anon キーだけを使います。
- `.env` はコミットしないでください。
