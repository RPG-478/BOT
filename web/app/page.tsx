import Link from "next/link";
import { loadCatalog } from "@/lib/catalog";
import { CAST } from "@/lib/art";
import SampleNotice from "./SampleNotice";

export default function Home() {
  const catalog = loadCatalog();
  return (
    <>
      <section className="hero">
        <img src="/img/nomal.png" alt="アゴ" />
        <div>
          <h1>AGOBOT</h1>
          <p className="muted" style={{ margin: 0 }}>
            みんなで遊べるパーティーゲームと、サーバー運営を助けるサポート機能の Discord Bot です。
          </p>
          <div className="cast">
            {CAST.map((c) => (
              <img key={c.src} src={c.src} alt={c.label} title={c.label} />
            ))}
          </div>
        </div>
      </section>
      <SampleNotice show={catalog.isSample} />
      <h2>はじめかた</h2>
      <div className="steps">
        <div className="card"><span className="num">1</span><strong>招待する</strong><div className="muted">AGOBOT をサーバーに招待します。</div></div>
        <div className="card"><span className="num">2</span><strong><code>/setup</code></strong><div className="muted">管理者が使うチャンネルや機能を設定します。</div></div>
        <div className="card"><span className="num">3</span><strong><code>/help</code></strong><div className="muted">機能ごとの使い方と例が表示されます。</div></div>
      </div>
      <h2>国づくり</h2>
      <Link href="/nation" className="card game-card">
        <img src="/img/coin.png" alt="アゴのコイン" />
        <div>
          <strong>サーバーどうしで国を育てよう</strong>
          <div className="muted">1 つの共有マップで、サーバーごとに国をつくります。<code>/nation found</code> で建国、<code>/nation join</code> で参加。遊び方を見る →</div>
        </div>
      </Link>
      <h2>人狼 役職図鑑</h2>
      <Link href="/jinrou/roles" className="card game-card">
        <img src="/img/jinrou/jinrou.png" alt="人狼" />
        <div>
          <strong>人狼の役職をイラストつきで紹介</strong>
          <div className="muted">陣営・能力・勝ち方を役職ごとに見られます。はじめての人は遊ぶ前にどうぞ。図鑑を見る →</div>
        </div>
      </Link>
      <h2>できること</h2>
      <div className="grid">
        {catalog.categories.map((category) => (
          <Link key={category.id} href={`/commands#${category.id}`} className="card">
            <strong>{category.label}</strong>
            <div className="muted">{category.description}</div>
          </Link>
        ))}
      </div>
    </>
  );
}
