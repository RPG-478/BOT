# AGOBOT Web

AGOBOT の紹介・コマンド一覧・ゲームのルール・ランキングのサイトです（Next.js、Vercel にデプロイ）。

## データ

コマンド一覧とルールは、Bot のコードから書き出した `data/commands.json` から作ります。

```bash
# リポジトリのルートで（Bot 側の書き出し）
python -m tools.export_commands -o web/data/commands.json
```

`data/commands.json` が無いあいだは `data/commands.sample.json`（サンプル）を表示し、画面にもサンプルであることを出します。

## 開発

```bash
cd web
npm install
npm run dev    # http://localhost:3000
npm test       # commands.json の形を確認
npm run build
```

## Vercel

プロジェクトの Root Directory を `web` にしてください。main に push されるたびに本番が更新されます。
