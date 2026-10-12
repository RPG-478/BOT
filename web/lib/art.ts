/** ゲームごとの絵（web/public/img）。決まっていないゲームはアゴ。 */
const GAME_ART: Record<string, string> = {
  werewolf: "/img/jinrou.png",
  jinrou: "/img/jinrou.png",
  人狼: "/img/jinrou.png",
  uno: "/img/agomunihadohou.png",
};

export function gameArt(name: string): string {
  const key = Object.keys(GAME_ART).find((k) => name.toLowerCase().includes(k));
  return key ? GAME_ART[key] : "/img/nomal.png";
}

export const CAST = [
  { src: "/img/jinrou.png", label: "人狼" },
  { src: "/img/uranai.png", label: "占い師" },
  { src: "/img/kishi.png", label: "騎士" },
  { src: "/img/reibai.png", label: "霊媒師" },
  { src: "/img/kyousinsya.png", label: "狂信者" },
  { src: "/img/wankoro.png", label: "わんころ" },
  { src: "/img/panya.png", label: "パン屋" },
];
