import fs from "node:fs";
import path from "node:path";
import { marked } from "marked";
export type CommandOption = { name: string; type: string; required: boolean; description: string };
export type Command = {
  name: string; kind: "slash" | "prefix"; category: string; summary: string; usage: string;
  options: CommandOption[]; permissions: string[]; guild_only: boolean; aliases: string[];
  hidden: boolean; guide?: string;
};
export type Category = { id: string; label: string; description: string; guide?: string };
export type Catalog = { generated_at: string; categories: Category[]; commands: Command[]; isSample: boolean };
const DATA_DIR = path.join(process.cwd(), "data");
/** 公開一覧には一般公開しているスラッシュコマンドのみ表示する。 */
export function loadCatalog(): Catalog {
  const real = path.join(DATA_DIR, "commands.json");
  const file = fs.existsSync(real) ? real : path.join(DATA_DIR, "commands.sample.json");
  const raw = JSON.parse(fs.readFileSync(file, "utf8"));
  return {
    generated_at: raw.generated_at ?? "",
    categories: raw.categories ?? [],
    commands: (raw.commands ?? []).filter((c: Command) =>
      !c.hidden && c.kind === "slash" && !c.name.split(" ").some((part) => part === "nation" || part.startsWith("nation_"))
    ),
    isSample: file !== real,
  };
}
export function commandId(command: Command): string {
  return `${command.kind}-${command.name}`.replace(/\s+/g, "-");
}
export function displayName(command: Command): string {
  return command.kind === "slash" ? `/${command.name}` : `!${command.name}`;
}
const PERMISSION_LABELS: Record<string, string> = {
  administrator: "管理者", manage_guild: "サーバー管理", manage_messages: "メッセージの管理",
  manage_channels: "チャンネルの管理", manage_roles: "ロールの管理",
};
export function permissionLabel(name: string): string { return PERMISSION_LABELS[name] ?? name; }
export function renderGuide(markdown: string | undefined): string {
  return markdown ? (marked.parse(markdown, { async: false }) as string) : "";
}
/** ルールページに出すゲーム：game カテゴリで guide があるコマンド */
export function games(catalog: Catalog): Command[] {
  return catalog.commands.filter((c) => c.category === "game" && c.guide);
}
