import Link from "next/link";

export const metadata = { title: "リーダーボード | AGOBOT" };

export default function RankingPage() {
  return (
    <>
      <div className="page-heading">
        <p className="eyebrow">LEADERBOARD</p>
        <h1>リーダーボード</h1>
        <p className="muted">サーバー内のゲーム成績を確認するためのページです。</p>
      </div>
      <div className="simple-panel">
        <h2>ゲームのランキング</h2>
        <p>サーバーごとのゲーム勝敗ランキングは、順次このページで確認できるようになります。ゲームを始めるには <Link href="/commands/game">/game の案内</Link> をご覧ください。</p>
      </div>
    </>
  );
}
