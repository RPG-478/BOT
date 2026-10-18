import Link from "next/link";
import { loadCatalog } from "@/lib/catalog";
import SampleNotice from "./SampleNotice";

export default function Home() {
  const catalog = loadCatalog();
  return (
    <>
      <section className="hero support-hero">
        <img src="/img/nomal.png" alt="AGOBOT" />
        <div>
          <p className="eyebrow">AGOBOT サポート</p>
          <h1>分かりやすく、幅広く。</h1>
          <p className="muted">ゲームも音楽も、Discordで使える機能のコマンドと使い方をまとめています。</p>
          <Link className="primary-link" href="/commands">コマンド一覧を見る →</Link>
        </div>
      </section>
      <SampleNotice show={catalog.isSample} />
      <section className="support-links" aria-label="よく使うコマンド">
        <Link href="/commands#game" className="card">
          <strong><code>/game</code> ゲームで遊ぶ</strong>
          <p className="muted">遊ぶゲームを選び、ルールを確認して募集を始めます。</p>
        </Link>
        <Link href="/commands#voice" className="card">
          <strong><code>/music</code> 音楽を楽しむ</strong>
          <p className="muted">URLや検索語から再生し、キューや音響を操作できます。</p>
        </Link>
      </section>
    </>
  );
}
