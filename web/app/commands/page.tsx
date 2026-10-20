import Link from "next/link";
import { COMMAND_GUIDES } from "@/lib/command-guides";

export const metadata = { title: "コマンド一覧 | AGOBOT" };

export default function CommandsPage() {
  return (
    <>
      <div className="page-heading">
        <p className="eyebrow">COMMANDS</p>
        <h1>コマンド一覧</h1>
        <p className="muted">使いたいコマンドを選ぶと、ジャンルごとの機能を確認できます。</p>
      </div>
      <div className="command-list" aria-label="公開コマンド一覧">
        {COMMAND_GUIDES.map((guide) => (
          <Link key={guide.slug} href={`/commands/${guide.slug}`} className="command-card">
            <div>
              <code className="command-code">{guide.command}</code>
              <h2>{guide.title}</h2>
              <p>{guide.summary}</p>
            </div>
            <span className="card-arrow" aria-hidden="true">→</span>
          </Link>
        ))}
      </div>
      <p className="quiet-note">各コマンドはDiscordで入力すると、自分だけに見える操作パネルが開きます。</p>
    </>
  );
}
