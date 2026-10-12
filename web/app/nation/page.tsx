import Link from "next/link";

export const metadata = { title: "国づくり | AGOBOT" };

const ROADMAP = [
  { phase: "フェーズ1", title: "鉄道", items: ["農場・鉱山などのマスを持てるようにする", "線路を敷いて、首都とつながっているかを判定する"] },
  { phase: "フェーズ2", title: "商業", items: ["お店・カジノ・レストランのマス", "国庫・税率・労働報酬など、国のお金のしくみ"] },
  { phase: "フェーズ3", title: "政治", items: ["国王・大臣・国民の役職ごとにできること", "入国料・出国料、国を移るしくみ"] },
  { phase: "フェーズ4", title: "レイド", items: ["ほかの国のマスを攻めたり守ったりする（マスの HP・防御力）", "国どうしの同盟"] },
];

export default function NationGuide() {
  return (
    <>
      <section className="hero">
        <img src="/img/coin.png" alt="アゴのコイン" />
        <div>
          <h1>国づくり</h1>
          <p className="muted" style={{ margin: 0 }}>
            AGOBOT が入っているサーバーどうしで、1 つの大きなマップを共有して国を育てるゲームです。
            1 つのサーバーが 1 つの国になり、メンバーはその国の国民として参加します。
          </p>
          <p style={{ marginBottom: 0 }}><Link href="/map">いまのマップを見る →</Link></p>
        </div>
      </section>

      <h2>はじめかた</h2>
      <div className="steps">
        <div className="card"><span className="num">1</span><strong><code>/setup</code></strong><div className="muted">管理者が「国づくり」のステップで参加をオンにし、お知らせチャンネルと通知の量（大きな出来事だけ／全部）を選びます。設定していないサーバーは参加扱いです。</div></div>
        <div className="card"><span className="num">2</span><strong><code>/nation found</code></strong><div className="muted">サーバーの管理者かオーナーが建国します。首都はマップの中心 (0,0) にいちばん近い空きマスに置かれ、建国した人が国王になります。</div></div>
        <div className="card"><span className="num">3</span><strong><code>/nation join</code></strong><div className="muted">ほかのメンバーは、いるサーバーの国に国民として参加します。</div></div>
        <div className="card"><span className="num">4</span><strong><code>/nation status</code></strong><div className="muted">所属国・役職・所持金・空腹度を、自分にだけ表示します。</div></div>
      </div>

      <h2>ルール</h2>
      <div className="grid">
        <div className="card"><strong>国と国民</strong><div className="muted">国は 1 サーバーに 1 つだけ。1 人が入れる国も 1 つだけです。役職は国王・大臣・国民の 3 つです。</div></div>
        <div className="card"><strong>空腹度</strong><div className="muted">参加したときは 100（最大）から始まり、<code>/nation status</code> でバーとして表示されます。0 より下にはなりません。<span className="badge">今後追加予定</span>時間とともに減るしくみ</div></div>
        <div className="card game-card"><img src="/img/coin.png" alt="" /><div><strong>コイン（AGO）</strong><div className="muted">所持金は <code>/wallet</code> と共通です。ほかの機能でためたコインがそのまま国づくりでも使えます。</div></div></div>
        <div className="card"><strong>共有マップ</strong><div className="muted">マップはすべてのサーバーで 1 つです。<Link href="/map">マップのページ</Link>で、どの国がどこにあるかを見られます。</div></div>
      </div>

      <h2>ロードマップ <span className="badge">今後追加予定</span></h2>
      <p className="muted">ここから先はまだ遊べません。内容や順番は変わることがあります。</p>
      <div className="grid">
        {ROADMAP.map((r) => (
          <div key={r.phase} className="card">
            <span className="badge">{r.phase}</span><strong>{r.title}</strong>
            <ul className="muted" style={{ margin: "6px 0 0", paddingLeft: 20 }}>
              {r.items.map((i) => <li key={i}>{i}</li>)}
            </ul>
          </div>
        ))}
      </div>
    </>
  );
}
