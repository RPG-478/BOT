import Link from "next/link";
import { loadCatalog } from "@/lib/catalog";
import SampleNotice from "./SampleNotice";

export default function Home() {
  const catalog = loadCatalog();
  return (
    <>
      <h1>AGOBOT</h1>
      <p className="muted">みんなで遊べるパーティーゲームと、サーバー運営を助けるサポート機能の Discord Bot です。</p>
      <SampleNotice show={catalog.isSample} />
      <h2>はじめに</h2>
      <div className="card">
        サーバーに入ったら、まず <code>/help</code> を実行してください。機能ごとに使い方と例が表示されます。
      </div>
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
