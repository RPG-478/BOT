#!/bin/bash
cd /home/luna/BOT
# リモートの更新を確認
git fetch origin main

# 変更があるかチェック
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse @{u})

if [ $LOCAL != $REMOTE ]; then
    echo "$(date): 更新が見つかりました。デプロイを開始します。"
    git reset --hard origin/main
    # 必要に応じてボットを再起動するコマンドをここに追加
    # 例: pkill -f main.py && source venv/bin/activate && nohup python main.py &
else
    echo "$(date): 変更はありません。"
fi
