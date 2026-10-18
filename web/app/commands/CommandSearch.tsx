"use client";
import { useState } from "react";
type Item = { id: string; category: string; text: string; html: React.ReactNode };
export default function CommandSearch({ groups }: {
  groups: { id: string; label: string; description: string; items: Item[] }[];
}) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  return (
    <>
      <input type="search" placeholder="コマンドを検索" value={query}
             onChange={(e) => setQuery(e.target.value)} aria-label="コマンドを検索" />
      {groups.map((group) => {
        const items = group.items.filter((item) => !q || item.text.includes(q));
        if (items.length === 0) return null;
        return <section key={group.id} id={group.id}><h2>{group.label}</h2>{items.map((item) => <div key={item.id}>{item.html}</div>)}</section>;
      })}
    </>
  );
}
