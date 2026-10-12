// 国づくりマップの純粋な計算（サーバー・テストの両方から使う。外部依存なし）
export type Tile = {
  x: number;
  y: number;
  owner_guild_id: string | null;
  owner_user_id: string | null;
  tile_type: string;
  hp: number;
  max_hp: number;
  connected: boolean;
};
export type Guild = { guild_id: string; capital_x: number | null; capital_y: number | null; treasury_coins: number };
export type Bounds = { minX: number; minY: number; maxX: number; maxY: number; width: number; height: number };

/** ギルド ID から毎回同じ色を返す（FNV-1a ハッシュ → HSL） */
export function guildColor(id: string | null | undefined): string {
  if (!id) return "#f2f1ed";
  let h = 0x811c9dc5;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  const hue = h % 360;
  const sat = 45 + ((h >>> 9) % 20);
  const light = 62 + ((h >>> 17) % 12);
  return `hsl(${hue} ${sat}% ${light}%)`;
}

/** タイルと首都の座標を含む範囲（1 マスの余白つき）。何もなければ 10x10 の空マップ */
export function calcBounds(tiles: { x: number; y: number }[], pad = 1, emptySize = 10): Bounds {
  if (tiles.length === 0) return { minX: 0, minY: 0, maxX: emptySize - 1, maxY: emptySize - 1, width: emptySize, height: emptySize };
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const t of tiles) {
    if (t.x < minX) minX = t.x;
    if (t.y < minY) minY = t.y;
    if (t.x > maxX) maxX = t.x;
    if (t.y > maxY) maxY = t.y;
  }
  minX -= pad; minY -= pad; maxX += pad; maxY += pad;
  return { minX, minY, maxX, maxY, width: maxX - minX + 1, height: maxY - minY + 1 };
}

/** ギルドごとのタイル数（多い順） */
export function countByGuild(tiles: { owner_guild_id: string | null }[]): { guild_id: string; count: number }[] {
  const m = new Map<string, number>();
  for (const t of tiles) if (t.owner_guild_id) m.set(t.owner_guild_id, (m.get(t.owner_guild_id) ?? 0) + 1);
  return [...m].map(([guild_id, count]) => ({ guild_id, count })).sort((a, b) => b.count - a.count || a.guild_id.localeCompare(b.guild_id));
}
