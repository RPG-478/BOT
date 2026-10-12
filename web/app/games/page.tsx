import Link from "next/link";
import { commandId, displayName, games, loadCatalog } from "@/lib/catalog";
import SampleNotice from "../SampleNotice";

export const metadata = { title: "ゲームのルール | AGOBOT" };

export default function GamesPage() {
  const catalog = loadCatalog();
  const list = games(catalog);
  return (
    <>
      <h1>ゲームのルール</h1>
      <SampleNotice show={catalog.isSample} />
      {list.length === 0 && <p className="muted">ルールはまだ登録されていません。</p>}
      <div className="grid">
        {list.map((g) => (
          <Link key={commandId(g)} href={`/games/${commandId(g)}`} className="card">
            <strong>{displayName(g)}</strong>
            <div className="muted">{g.summary}</div>
          </Link>
        ))}
      </div>
    </>
  );
}
