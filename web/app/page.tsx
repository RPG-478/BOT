import Link from "next/link";
import { COMMAND_GUIDES } from "@/lib/command-guides";

export default function Home() {
  return (
    <>
      <section className="home-hero">
        <img src="/img/nomal.png" alt="AGOBOT" />
        <div>
          <p className="eyebrow">AGOBOT SUPPORT</p>
          <h1>使いたいことから、すぐ辿れる。</h1>
          <p className="muted">5つのコマンドを入口に、ジャンルと細かな機能を順に案内します。</p>
          <Link className="primary-link" href="/commands">コマンド一覧を見る</Link>
        </div>
      </section>
      <section className="home-section" aria-labelledby="commands-heading">
        <div className="section-intro">
          <p className="eyebrow">START HERE</p>
          <h2 id="commands-heading">5つのコマンド</h2>
        </div>
        <div className="home-command-grid">
          {COMMAND_GUIDES.map((guide) => (
            <Link key={guide.slug} href={`/commands/${guide.slug}`} className="home-command-link">
              <code>{guide.command}</code>
              <span>{guide.title}</span>
            </Link>
          ))}
        </div>
      </section>
      <section className="home-section simple-callout">
        <h2>まずは <code>/help</code> から</h2>
        <p className="muted">Discord上でカテゴリから探したいときは、<code>/help</code> を開いてください。</p>
      </section>
    </>
  );
}
