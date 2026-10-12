export const metadata = { title: "ランキング | AGOBOT" };

export default function RankingPage() {
  return (
    <>
      <h1><img src="/img/coin.png" alt="" width={36} height={36} style={{ verticalAlign: "middle", marginRight: 8 }} />ランキング</h1>
      <div className="card">
        サーバーごとのゲームの勝敗ランキングは準備中です。Bot 側で記録が始まったら、ここに表示されます。
      </div>
    </>
  );
}
