import { notFound } from "next/navigation";
import { commandId, displayName, games, loadCatalog, renderGuide } from "@/lib/catalog";
import { gameArt } from "@/lib/art";

export function generateStaticParams() {
  return games(loadCatalog()).map((g) => ({ id: commandId(g) }));
}

export default async function GamePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const game = games(loadCatalog()).find((g) => commandId(g) === id);
  if (!game) notFound();
  return (
    <>
      <h1 style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <img src={gameArt(game.name)} alt="" width={56} height={56} />
        {displayName(game)}
      </h1>
      <p className="muted">{game.summary}</p>
      <div className="card" dangerouslySetInnerHTML={{ __html: renderGuide(game.guide) }} />
    </>
  );
}
