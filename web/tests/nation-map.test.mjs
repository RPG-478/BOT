// lib/nation-map.ts の純粋な関数（色・範囲・集計）を確かめる
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const src = fs.readFileSync(path.join(import.meta.dirname, "..", "lib", "nation-map.ts"), "utf8");
const js = ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const m = await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));

test("guildColor は同じ ID に同じ色、違う ID に違う色", () => {
  assert.equal(m.guildColor("123"), m.guildColor("123"));
  assert.notEqual(m.guildColor("123"), m.guildColor("456"));
  assert.match(m.guildColor("abc"), /^hsl\(\d+ \d+% \d+%\)$/);
  assert.equal(m.guildColor(null), "#f2f1ed");
});

test("calcBounds は余白つきの範囲、空なら 10x10", () => {
  assert.deepEqual(m.calcBounds([]), { minX: 0, minY: 0, maxX: 9, maxY: 9, width: 10, height: 10 });
  assert.deepEqual(m.calcBounds([{ x: 2, y: 3 }, { x: -1, y: 5 }]), { minX: -2, minY: 2, maxX: 3, maxY: 6, width: 6, height: 5 });
});

test("countByGuild は所有者なしを除いて多い順", () => {
  const r = m.countByGuild([{ owner_guild_id: "b" }, { owner_guild_id: "a" }, { owner_guild_id: "a" }, { owner_guild_id: null }]);
  assert.deepEqual(r, [{ guild_id: "a", count: 2 }, { guild_id: "b", count: 1 }]);
});
