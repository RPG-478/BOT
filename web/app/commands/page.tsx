import Link from "next/link";
import { commandId, displayName, loadCatalog, permissionLabel } from "@/lib/catalog";
import SampleNotice from "../SampleNotice";
import CommandSearch from "./CommandSearch";

export const metadata = { title: "コマンド一覧 | AGOBOT" };

export default function CommandsPage() {
  const catalog = loadCatalog();
  const groups = catalog.categories.map((category) => ({
    id: category.id,
    label: category.label,
    description: category.description,
    items: catalog.commands
      .filter((c) => c.category === category.id)
      .map((c) => ({
        id: commandId(c),
        category: c.category,
        text: `${displayName(c)} ${c.summary} ${c.aliases.join(" ")}`.toLowerCase(),
        html: (
          <div className="card" id={commandId(c)}>
            <strong><code>{displayName(c)}</code></strong>
            {c.guild_only && <span className="badge">サーバー内のみ</span>}
            {c.permissions.map((p) => <span key={p} className="badge">{permissionLabel(p)}</span>)}
            <div>{c.summary}</div>
            {c.usage && <div className="muted">例：<code>{c.usage}</code></div>}
            {c.options.length > 0 && (
              <table>
                <tbody>
                  {c.options.map((o) => (
                    <tr key={o.name}>
                      <td><code>{o.name}</code>{o.required ? "（必須）" : ""}</td>
                      <td className="muted">{o.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {c.category === "game" && c.guide && <Link href={`/games/${commandId(c)}`}>ルールを見る</Link>}
          </div>
        ),
      })),
  }));
  return (
    <>
      <h1>コマンド一覧</h1>
      <SampleNotice show={catalog.isSample} />
      <CommandSearch groups={groups} />
      {catalog.generated_at && <p className="muted">最終更新：{catalog.generated_at}</p>}
    </>
  );
}
