"""
ゴッドフィールド - Discord Bot Cog
システム枠組み: god_field.py
アイテムデータ: godfield.net/i18n/ja.json
"""

import discord
from discord.ext import commands
import asyncio
import random
import uuid
import json

# ================================================================
# アイテムデータ (godfield.net/i18n/ja.json の items 配列より)
# ================================================================
_ITEMS_JSON = r"""
[
{"imageName":"discard","category":"trade","ability":"discard","name":"捨てる"},
{"imageName":"sacrifice","category":"trade","ability":"sacrifice","name":"ささげる"},
{"imageName":"exchange","category":"trade","ability":"exchange","price":5,"giftRate":20,"name":"両替"},
{"imageName":"sell","category":"trade","ability":"sell","price":5,"giftRate":20,"name":"売る"},
{"imageName":"buy","category":"trade","ability":"buy","price":5,"giftRate":20,"name":"買う"},
{"imageName":"bronze-club","category":"weapons","atk":1,"price":1,"giftRate":3,"name":"銅のこん棒"},
{"imageName":"silver-club","category":"weapons","atk":1,"price":10,"giftRate":1,"name":"銀のこん棒"},
{"imageName":"gold-club","category":"weapons","atk":1,"price":25,"giftRate":1,"name":"金のこん棒"},
{"imageName":"blowgun","category":"weapons","atk":1,"isPlusAtk":true,"price":1,"giftRate":1,"name":"吹き矢"},
{"imageName":"whip","category":"weapons","atk":2,"price":1,"giftRate":4,"name":"ムチ"},
{"imageName":"saver-rod","category":"weapons","atk":2,"def":6,"price":10,"giftRate":1,"name":"セイバーロッド"},
{"imageName":"crossbow","category":"weapons","atk":2,"isPlusAtk":true,"price":2,"giftRate":1,"name":"クロスボウ"},
{"imageName":"punch","category":"weapons","atk":3,"price":1,"giftRate":5,"name":"パンチ"},
{"imageName":"saw-boom-boom","category":"weapons","atk":3,"ability":"attackTwice","price":10,"giftRate":1,"name":"のこぶんぶん"},
{"imageName":"boomerang","category":"weapons","atk":3,"isPlusAtk":true,"price":3,"giftRate":1,"name":"ブーメラン"},
{"imageName":"hatchet","category":"weapons","atk":4,"price":2,"giftRate":6,"name":"ハチェット"},
{"imageName":"spiked-belt","category":"weapons","atk":4,"def":2,"price":3,"giftRate":1,"name":"とげベルト"},
{"imageName":"battle-ball","category":"weapons","atk":4,"isPlusAtk":true,"price":4,"giftRate":1,"name":"バトルボール"},
{"imageName":"chain-sickle","category":"weapons","atk":5,"price":2,"giftRate":7,"name":"鎖ガマ"},
{"imageName":"plate-of-strike","category":"weapons","atk":5,"def":7,"price":3,"giftRate":1,"name":"打撃の鉄板"},
{"imageName":"bouncing-sword","category":"weapons","atk":5,"ability":"bounceWeapon","price":10,"giftRate":7,"name":"乱弾武剣"},
{"imageName":"warrior-s-bow","category":"weapons","atk":5,"isPlusAtk":true,"price":5,"giftRate":1,"name":"戦士の弓"},
{"imageName":"hard-hammer","category":"weapons","atk":6,"price":2,"giftRate":8,"name":"硬いつち"},
{"imageName":"elbow-sack","category":"weapons","atk":6,"def":3,"price":3,"giftRate":1,"name":"エルボーサック"},
{"imageName":"jet-yo-yo","category":"weapons","atk":6,"isPlusAtk":true,"price":6,"giftRate":1,"name":"ジェットヨーヨー"},
{"imageName":"glaive-classic","category":"weapons","atk":7,"price":3,"giftRate":8,"name":"なぎなたクラシック"},
{"imageName":"ghost-sword","category":"weapons","atk":7,"ability":"absorbHP","price":10,"giftRate":1,"name":"ゴーストソード"},
{"imageName":"unknown-feather","category":"weapons","atk":7,"isPlusAtk":true,"price":7,"giftRate":1,"name":"未知の羽根"},
{"imageName":"final-tusk","category":"weapons","atk":8,"price":3,"giftRate":8,"name":"ファイナル牙"},
{"imageName":"hell-scissors","category":"weapons","atk":8,"ability":"addCurseOnDamage","curse":"hell","price":15,"giftRate":1,"name":"地獄のハサミ"},
{"imageName":"psychic-card","category":"weapons","atk":8,"isPlusAtk":true,"price":8,"giftRate":1,"name":"サイキックカード"},
{"imageName":"power-halberd","category":"weapons","atk":9,"price":3,"giftRate":7,"name":"パワーハルベルト"},
{"imageName":"gale-sword","category":"weapons","atk":9,"ability":"addCurseOnDamage","curse":"cold","price":10,"giftRate":1,"name":"疾風剣"},
{"imageName":"sky-harpoon","category":"weapons","atk":9,"isPlusAtk":true,"ability":"bounceMiracle","price":5,"giftRate":1,"name":"スカイハープーン"},
{"imageName":"wonder-sword","category":"weapons","atk":10,"price":4,"giftRate":7,"name":"ワンダーソード"},
{"imageName":"bogus-spear","category":"weapons","atk":10,"ability":"addCurseOnDamage","curse":"dream","price":10,"giftRate":1,"name":"いんちきスピア"},
{"imageName":"sword-shield","category":"weapons","atk":10,"def":10,"price":15,"giftRate":1,"name":"ソードシールド"},
{"imageName":"reflection-sword","category":"weapons","atk":10,"ability":"reflectWeapon","price":5,"giftRate":3,"name":"反射剣"},
{"imageName":"moonlight-axe","category":"weapons","atk":10,"ability":"reflectMiracle","price":10,"giftRate":1,"name":"月光のオノ"},
{"imageName":"gravity-mace","category":"weapons","atk":11,"price":4,"giftRate":4,"name":"グラビティメイス"},
{"imageName":"hexagon-doom","category":"weapons","atk":11,"ability":"addCurseOnDamage","curse":"darkcloud","price":15,"giftRate":1,"name":"六角凶"},
{"imageName":"angel-knife","category":"weapons","atk":11,"ability":"blockMiracle","price":15,"giftRate":1,"name":"エンゼルナイフ"},
{"imageName":"horror-wheel","category":"weapons","atk":11,"isPlusAtk":true,"price":10,"giftRate":1,"name":"恐怖の車輪"},
{"imageName":"direct-smash-axe","category":"weapons","atk":12,"price":4,"giftRate":4,"name":"もろぶっこみアクス"},
{"imageName":"real-ghost-sword","category":"weapons","atk":12,"ability":"absorbHP","price":15,"giftRate":1,"name":"リアルゴーストソード"},
{"imageName":"spiritual-staff","category":"weapons","atk":12,"ability":"cutCost","price":20,"giftRate":1,"name":"精霊の杖"},
{"imageName":"spear-in-fine-view","category":"weapons","atk":13,"price":5,"giftRate":4,"name":"絶景のヤリ"},
{"imageName":"severe-gale-sword","category":"weapons","atk":13,"ability":"addCurseOnDamage","curse":"cold","price":15,"giftRate":1,"name":"激烈疾風剣"},
{"imageName":"legendary-scabbard","category":"weapons","atk":13,"def":1,"price":3,"giftRate":1,"name":"伝説の剣のさや"},
{"imageName":"angel-sword","category":"weapons","atk":13,"ability":"blockMiracle","price":15,"giftRate":1,"name":"エンゼルソード"},
{"imageName":"top-of-combat","category":"weapons","atk":13,"isPlusAtk":true,"price":10,"giftRate":1,"name":"独楽コンバット"},
{"imageName":"violent-flail","category":"weapons","atk":14,"price":5,"giftRate":3,"name":"暴れフレイル"},
{"imageName":"evil-broadsword","category":"weapons","atk":14,"ability":"dealSameDamage","price":1,"giftRate":1,"name":"邪神の大剣"},
{"imageName":"dragon-claws","category":"weapons","atk":15,"price":5,"giftRate":3,"name":"ドラゴンクロウ"},
{"imageName":"angel-axe","category":"weapons","atk":15,"ability":"blockMiracle","price":15,"giftRate":1,"name":"エンゼルアクス"},
{"imageName":"angel-bow","category":"weapons","atk":15,"isPlusAtk":true,"ability":"blockMiracle","price":15,"giftRate":1,"name":"エンゼルの弓"},
{"imageName":"god-sword","category":"weapons","atk":30,"price":30,"giftRate":1,"name":"神の剣"},
{"imageName":"magical-stick","category":"weapons","ability":"atkBy2xMP","price":10,"giftRate":1,"name":"マジカルステッキ"},
{"imageName":"torch","category":"weapons","element":"fire","atk":1,"price":1,"giftRate":1,"name":"たいまつ"},
{"imageName":"icicle","category":"weapons","element":"water","atk":1,"price":1,"giftRate":1,"name":"つらら"},
{"imageName":"wooden-sword","category":"weapons","element":"wood","atk":1,"price":1,"giftRate":1,"name":"木刀"},
{"imageName":"wind-talons","category":"weapons","element":"stone","atk":1,"ability":"addCurseOnDamage","curse":"cold","price":10,"giftRate":1,"name":"風のカギ爪"},
{"imageName":"piece-of-brightness","category":"weapons","element":"light","atk":1,"isPlusAtk":true,"price":10,"giftRate":1,"name":"輝きのカケラ"},
{"imageName":"pri-pri-pricker","category":"weapons","element":"darkness","atk":1,"price":10,"giftRate":1,"name":"ちくりんちょ"},
{"imageName":"ouch-knife","category":"weapons","element":"fire","atk":2,"price":2,"giftRate":1,"name":"あちちナイフ"},
{"imageName":"wand-of-ignition","category":"weapons","element":"fire","atk":2,"isPlusAtk":true,"ability":"setElement","price":15,"giftRate":1,"name":"発火のワンド"},
{"imageName":"thorn-whip","category":"weapons","element":"wood","atk":2,"price":2,"giftRate":1,"name":"いばらのムチ"},
{"imageName":"leaf-shuriken","category":"weapons","element":"wood","atk":2,"isPlusAtk":true,"price":4,"giftRate":1,"name":"葉っぱ手裏剣"},
{"imageName":"sword-ware","category":"weapons","element":"stone","atk":2,"price":2,"giftRate":1,"name":"つるぎ焼き"},
{"imageName":"flash-dagger","category":"weapons","element":"light","atk":2,"ability":"addCurseOnDamage","curse":"flash","price":15,"giftRate":1,"name":"フラッシュダガー"},
{"imageName":"fire-whip","category":"weapons","element":"fire","atk":3,"price":3,"giftRate":1,"name":"燃えムチ"},
{"imageName":"fog-gun","category":"weapons","element":"water","atk":3,"ability":"addCurseOnDamage","curse":"fog","price":10,"giftRate":1,"name":"霧鉄砲"},
{"imageName":"bur-nut","category":"weapons","element":"wood","atk":3,"price":3,"giftRate":1,"name":"いがナッツ"},
{"imageName":"mature-rubber-bow","category":"weapons","element":"wood","atk":3,"isPlusAtk":true,"price":6,"giftRate":1,"name":"熟成ゴムの弓"},
{"imageName":"star-staff","category":"weapons","element":"light","atk":3,"price":3,"giftRate":1,"name":"スタースタッフ"},
{"imageName":"cobra","category":"weapons","element":"darkness","atk":3,"price":10,"giftRate":1,"name":"コブラ"},
{"imageName":"flaming-roll","category":"weapons","element":"fire","atk":4,"def":4,"price":8,"giftRate":1,"name":"ほむら巻き"},
{"imageName":"fire-crossbow","category":"weapons","element":"fire","atk":4,"isPlusAtk":true,"price":8,"giftRate":1,"name":"ファイヤークロスボウ"},
{"imageName":"frozen-hammer","category":"weapons","element":"water","atk":4,"price":4,"giftRate":1,"name":"氷結ハンマー"},
{"imageName":"dream-mallet","category":"weapons","element":"wood","atk":4,"ability":"addCurseOnDamage","curse":"dream","price":15,"giftRate":1,"name":"夢の木づち"},
{"imageName":"goodbye-sword","category":"weapons","element":"darkness","atk":4,"price":10,"giftRate":1,"name":"さよならの剣"},
{"imageName":"blaze-blade","category":"weapons","element":"fire","atk":5,"price":5,"giftRate":1,"name":"ブレイズブレイド"},
{"imageName":"wand-of-mystic-water","category":"weapons","element":"water","atk":5,"isPlusAtk":true,"ability":"setElement","price":15,"giftRate":1,"name":"魔水のワンド"},
{"imageName":"paleolithic-javelin","category":"weapons","element":"stone","atk":5,"isPlusAtk":true,"price":10,"giftRate":1,"name":"旧石器ジャベリン"},
{"imageName":"justice-lance","category":"weapons","element":"light","atk":5,"price":5,"giftRate":1,"name":"ジャスティスランス"},
{"imageName":"killer-fork","category":"weapons","element":"darkness","atk":5,"price":10,"giftRate":1,"name":"キラーフォーク"},
{"imageName":"abyss-dart","category":"weapons","element":"darkness","atk":5,"isPlusAtk":true,"price":15,"giftRate":1,"name":"冥矢"},
{"imageName":"neolithic-tomahawk","category":"weapons","element":"stone","atk":7,"isPlusAtk":true,"price":10,"giftRate":1,"name":"新石器トマホーク"},
{"imageName":"fire-dragon-s-horn","category":"weapons","element":"fire","atk":8,"price":10,"giftRate":1,"name":"火竜一角"},
{"imageName":"water-dragon-s-horn","category":"weapons","element":"water","atk":8,"price":10,"giftRate":1,"name":"水竜一角"},
{"imageName":"holy-sword","category":"weapons","element":"light","atk":9,"price":15,"giftRate":1,"name":"聖剣"},
{"imageName":"death-s-scythe","category":"weapons","element":"darkness","atk":10,"price":20,"giftRate":1,"name":"死神のカマ"},
{"imageName":"diamond-sword","category":"weapons","element":"stone","atk":13,"price":25,"giftRate":1,"name":"ダイヤモンドソード"},
{"imageName":"dangerous-pestle","category":"weapons","element":"light","atk":30,"ability":"danger","price":5,"giftRate":1,"name":"あぶないキネ"},
{"imageName":"spark-bag","category":"weapons","element":"fire","atk":1,"hitRate":75,"price":2,"giftRate":1,"name":"火の粉袋"},
{"imageName":"shadow-hand","category":"weapons","element":"darkness","atk":2,"hitRate":50,"price":8,"giftRate":1,"name":"シャドウハンド"},
{"imageName":"fog-fan","category":"weapons","element":"water","atk":3,"hitRate":50,"ability":"addCurseOnDamage","curse":"fog","price":8,"giftRate":1,"name":"霧の扇"},
{"imageName":"vine-shoot","category":"weapons","element":"wood","atk":3,"hitRate":75,"ability":"absorbHP","price":10,"giftRate":1,"name":"つるシュート"},
{"imageName":"lightning-kids","category":"weapons","element":"light","atk":3,"hitRate":25,"price":2,"giftRate":1,"name":"イナヅマキッズ"},
{"imageName":"flame-cup","category":"weapons","element":"fire","atk":4,"hitRate":75,"price":6,"giftRate":1,"name":"火炎杯"},
{"imageName":"chill-cup","category":"weapons","element":"water","atk":4,"hitRate":75,"price":6,"giftRate":1,"name":"冷気杯"},
{"imageName":"plant-cup","category":"weapons","element":"wood","atk":4,"hitRate":75,"price":6,"giftRate":1,"name":"植物杯"},
{"imageName":"rock-cup","category":"weapons","element":"stone","atk":4,"hitRate":75,"price":6,"giftRate":1,"name":"岩石杯"},
{"imageName":"oversize-snowball","category":"weapons","element":"water","atk":5,"hitRate":50,"price":5,"giftRate":1,"name":"特大雪玉"},
{"imageName":"cliff-hammer","category":"weapons","element":"stone","atk":6,"hitRate":25,"price":4,"giftRate":1,"name":"ガケッツチ"},
{"imageName":"light-orb","category":"weapons","element":"light","atk":6,"hitRate":75,"price":10,"giftRate":1,"name":"光のオーブ"},
{"imageName":"fire-shower","category":"weapons","element":"fire","atk":7,"hitRate":75,"price":10,"giftRate":1,"name":"烈火シャワー"},
{"imageName":"jinn-s-rocking-horse","category":"weapons","element":"wood","atk":8,"hitRate":75,"def":6,"price":15,"giftRate":1,"name":"魔神の木馬"},
{"imageName":"rain-deity-s-saber","category":"weapons","element":"water","atk":9,"hitRate":50,"price":9,"giftRate":1,"name":"雨神刀"},
{"imageName":"flare-axe","category":"weapons","element":"fire","atk":10,"hitRate":50,"price":10,"giftRate":1,"name":"フレアアクス"},
{"imageName":"petit-saturn","category":"weapons","element":"stone","atk":20,"hitRate":25,"price":15,"giftRate":1,"name":"プチサターン"},
{"imageName":"ascension-bow","category":"weapons","element":"light","atk":1,"hitRate":25,"ability":"attackDyingly","abilityValue":30,"price":10,"giftRate":1,"name":"昇天弓"},
{"imageName":"leather-cap","category":"armor","def":1,"price":1,"giftRate":10,"name":"革の帽子"},
{"imageName":"sky-boots","category":"armor","def":1,"ability":"bounceMiracle","price":5,"giftRate":1,"name":"スカイブーツ"},
{"imageName":"aqua-shoes","category":"armor","element":"water","def":1,"price":2,"giftRate":1,"name":"アクアシューズ"},
{"imageName":"laurel-wreath","category":"armor","element":"wood","def":1,"price":2,"giftRate":1,"name":"草かんむり"},
{"imageName":"slate","category":"armor","element":"stone","def":1,"price":2,"giftRate":1,"name":"石版"},
{"imageName":"leather-clothes","category":"armor","def":2,"price":2,"giftRate":10,"name":"革の服"},
{"imageName":"sparkle-glove","category":"armor","element":"fire","def":2,"price":4,"giftRate":1,"name":"火花の手袋"},
{"imageName":"aqua-glove","category":"armor","element":"water","def":2,"price":4,"giftRate":1,"name":"アクアグローブ"},
{"imageName":"wood-shield","category":"armor","element":"wood","def":2,"price":4,"giftRate":1,"name":"木の盾"},
{"imageName":"bedrock","category":"armor","element":"stone","def":2,"price":4,"giftRate":1,"name":"岩盤"},
{"imageName":"iron-gauntlet","category":"armor","def":3,"price":3,"giftRate":8,"name":"アイアンガントレット"},
{"imageName":"ogre-s-shoes","category":"armor","atk":5,"isPlusAtk":true,"def":3,"price":10,"giftRate":1,"name":"鬼のくつ"},
{"imageName":"sky-gauntlet","category":"armor","def":3,"ability":"bounceMiracle","price":5,"giftRate":1,"name":"スカイガントレット"},
{"imageName":"flame-boots","category":"armor","element":"fire","def":3,"price":6,"giftRate":1,"name":"フレイムブーツ"},
{"imageName":"ice-boots","category":"armor","element":"water","def":3,"price":6,"giftRate":1,"name":"アイスブーツ"},
{"imageName":"sacred-tree-gauntlet","category":"armor","element":"wood","def":3,"price":6,"giftRate":1,"name":"御神木の小手"},
{"imageName":"crystal-board","category":"armor","element":"stone","def":3,"price":6,"giftRate":1,"name":"結晶板"},
{"imageName":"iron-shield","category":"armor","def":4,"price":4,"giftRate":8,"name":"アイアンシールド"},
{"imageName":"flame-helm","category":"armor","element":"fire","def":4,"price":8,"giftRate":1,"name":"フレイムヘルム"},
{"imageName":"ice-helm","category":"armor","element":"water","def":4,"price":8,"giftRate":1,"name":"アイスヘルム"},
{"imageName":"grove-shield","category":"armor","element":"wood","def":4,"price":8,"giftRate":1,"name":"林の盾"},
{"imageName":"terra-shoes","category":"armor","element":"stone","def":4,"price":8,"giftRate":1,"name":"大地のくつ"},
{"imageName":"iron-armor","category":"armor","def":5,"price":5,"giftRate":8,"name":"アイアンアーマー"},
{"imageName":"ogre-s-gauntlet","category":"armor","atk":10,"isPlusAtk":true,"def":5,"price":15,"giftRate":1,"name":"鬼の小手"},
{"imageName":"sky-helm","category":"armor","def":5,"ability":"bounceMiracle","price":5,"giftRate":1,"name":"スカイヘルム"},
{"imageName":"flame-shield","category":"armor","element":"fire","def":5,"price":10,"giftRate":1,"name":"フレイムシールド"},
{"imageName":"ice-shield","category":"armor","element":"water","def":5,"price":10,"giftRate":1,"name":"アイスシールド"},
{"imageName":"resin-knit-robe","category":"armor","element":"wood","def":5,"price":10,"giftRate":1,"name":"樹脂で編んだ法衣"},
{"imageName":"terra-gauntlet","category":"armor","element":"stone","def":5,"price":10,"giftRate":1,"name":"大地の小手"},
{"imageName":"steel-gauntlet","category":"armor","def":6,"price":6,"giftRate":6,"name":"はがねの小手"},
{"imageName":"spiritual-socks","category":"armor","def":6,"ability":"cutCost","price":20,"giftRate":1,"name":"精霊の足袋"},
{"imageName":"flame-mail","category":"armor","element":"fire","def":6,"price":10,"giftRate":1,"name":"フレイムメイル"},
{"imageName":"ice-armor","category":"armor","element":"water","def":6,"price":10,"giftRate":1,"name":"アイスアーマー"},
{"imageName":"forest-shield","category":"armor","element":"wood","def":6,"price":10,"giftRate":1,"name":"森の盾"},
{"imageName":"terra-helm","category":"armor","element":"stone","def":6,"price":10,"giftRate":1,"name":"大地のかぶと"},
{"imageName":"shining-high-heels","category":"armor","element":"light","def":6,"price":15,"giftRate":1,"name":"ぴかぴかハイヒール"},
{"imageName":"steel-helm","category":"armor","def":7,"price":7,"giftRate":6,"name":"はがねのかぶと"},
{"imageName":"ogre-s-helm","category":"armor","atk":10,"isPlusAtk":true,"def":7,"price":15,"giftRate":1,"name":"鬼のかぶと"},
{"imageName":"sky-shield","category":"armor","def":7,"ability":"bounceMiracle","price":5,"giftRate":1,"name":"スカイシールド"},
{"imageName":"burning-shield","category":"armor","element":"fire","def":7,"price":10,"giftRate":1,"name":"バーニングシールド"},
{"imageName":"snow-mitten","category":"armor","element":"water","def":7,"price":10,"giftRate":1,"name":"スノーミトン"},
{"imageName":"steel-shield","category":"armor","def":8,"price":8,"giftRate":6,"name":"はがねの盾"},
{"imageName":"beautiful-glasswork","category":"armor","def":8,"price":20,"giftRate":1,"name":"美しいガラス細工"},
{"imageName":"moonlight-helm","category":"armor","def":8,"ability":"reflectMiracle","price":10,"giftRate":1,"name":"月光のかぶと"},
{"imageName":"burning-jacket","category":"armor","element":"fire","def":8,"price":10,"giftRate":1,"name":"バーニングジャケット"},
{"imageName":"snow-mask","category":"armor","element":"water","def":8,"price":10,"giftRate":1,"name":"スノーマスク"},
{"imageName":"amber-breastplate","category":"armor","element":"wood","def":8,"price":10,"giftRate":1,"name":"コハクの胸当て"},
{"imageName":"terra-armor","category":"armor","element":"stone","def":8,"price":10,"giftRate":1,"name":"大地のよろい"},
{"imageName":"steel-armor","category":"armor","def":9,"price":9,"giftRate":6,"name":"はがねのよろい"},
{"imageName":"ogre-s-armor","category":"armor","atk":15,"isPlusAtk":true,"def":9,"price":20,"giftRate":1,"name":"鬼のよろい"},
{"imageName":"spiritual-hood","category":"armor","def":9,"ability":"cutCost","price":20,"giftRate":1,"name":"精霊の頭巾"},
{"imageName":"sky-armor","category":"armor","def":9,"ability":"bounceMiracle","price":5,"giftRate":1,"name":"スカイアーマー"},
{"imageName":"angel-gauntlet","category":"armor","def":9,"ability":"blockMiracle","price":15,"giftRate":1,"name":"エンゼルの小手"},
{"imageName":"energy-helm","category":"armor","def":10,"price":10,"giftRate":4,"name":"エナジーヘルム"},
{"imageName":"moonlight-shield","category":"armor","def":10,"ability":"reflectMiracle","price":10,"giftRate":1,"name":"月光の盾"},
{"imageName":"fever-mask","category":"armor","element":"fire","def":10,"ability":"selfCurse","curse":"fever","price":10,"giftRate":1,"name":"熱狂仮面"},
{"imageName":"glittering-dress","category":"armor","element":"light","def":10,"price":15,"giftRate":1,"name":"きらきらドレス"},
{"imageName":"energy-armor","category":"armor","def":11,"price":10,"giftRate":4,"name":"エナジーアーマー"},
{"imageName":"angel-cap","category":"armor","def":11,"ability":"blockMiracle","price":15,"giftRate":1,"name":"エンゼルの帽子"},
{"imageName":"core-barrier","category":"armor","def":12,"price":10,"giftRate":2,"name":"コアバリヤー"},
{"imageName":"spiritual-sash","category":"armor","def":12,"ability":"cutCost","price":20,"giftRate":1,"name":"精霊の帯"},
{"imageName":"moonlight-armor","category":"armor","def":12,"ability":"reflectMiracle","price":10,"giftRate":1,"name":"月光のよろい"},
{"imageName":"heat-haze-armor","category":"armor","element":"fire","def":12,"price":15,"giftRate":1,"name":"陽炎のよろい"},
{"imageName":"core-protector","category":"armor","def":13,"price":10,"giftRate":2,"name":"コアプロテクター"},
{"imageName":"angel-shield","category":"armor","def":13,"ability":"blockMiracle","price":15,"giftRate":1,"name":"エンゼルシールド"},
{"imageName":"dreaming-hat","category":"armor","element":"wood","def":14,"ability":"selfCurseAndRedraw","curse":"dream","price":15,"giftRate":1,"name":"夢見る帽子"},
{"imageName":"angel-armor","category":"armor","def":15,"ability":"blockMiracle","price":15,"giftRate":1,"name":"エンゼルアーマー"},
{"imageName":"god-shield","category":"armor","def":30,"price":30,"giftRate":1,"name":"神の盾"},
{"imageName":"mars-ring","category":"armor","element":"fire","hitRate":75,"ability":"counterAtk","price":10,"giftRate":1,"name":"火星の指輪"},
{"imageName":"mercury-ring","category":"armor","element":"water","ability":"counterCurse","curse":"fog","price":10,"giftRate":1,"name":"水星の指輪"},
{"imageName":"jupiter-ring","category":"armor","element":"wood","ability":"counterCurse","curse":"dream","price":10,"giftRate":1,"name":"木星の指輪"},
{"imageName":"saturn-ring","category":"armor","element":"stone","ability":"counter2xAtk","price":10,"giftRate":1,"name":"土星の指輪"},
{"imageName":"uranus-ring","category":"armor","element":"light","ability":"counterCurse","curse":"flash","price":10,"giftRate":1,"name":"天王の指輪"},
{"imageName":"pluto-ring","category":"armor","element":"darkness","ability":"counterCurse","curse":"darkcloud","price":10,"giftRate":1,"name":"冥王の指輪"},
{"imageName":"neptune-ring","category":"armor","ability":"counterBoost2xMP","price":10,"giftRate":1,"name":"海王の指輪"},
{"imageName":"venus-ring","category":"armor","ability":"counterTakeCP","price":10,"giftRate":1,"name":"金星の指輪"},
{"imageName":"rainbow-curtain","category":"armor","ability":"filterAtkElement","price":15,"giftRate":3,"name":"虹のカーテン"},
{"imageName":"super-mirror","category":"armor","ability":"reflectAnything","price":10,"giftRate":1,"name":"スーパーミラー"},
{"imageName":"smile-dew","category":"sundries","ability":"boostHP","abilityValue":5,"price":1,"giftRate":12,"name":"スマイルのしずく"},
{"imageName":"heart-dew","category":"sundries","ability":"boostHP","abilityValue":10,"price":3,"giftRate":8,"name":"ハートのしずく"},
{"imageName":"romance-water","category":"sundries","ability":"boostHP","abilityValue":15,"price":5,"giftRate":4,"name":"ロマンスウォーター"},
{"imageName":"galaxy-geyser","category":"sundries","ability":"boostHP","abilityValue":20,"price":20,"giftRate":1,"name":"天の川のおいしい水"},
{"imageName":"smile-flower","category":"sundries","ability":"boostMP","abilityValue":5,"price":1,"giftRate":12,"name":"スマイルの花"},
{"imageName":"heart-flower","category":"sundries","ability":"boostMP","abilityValue":10,"price":3,"giftRate":8,"name":"ハートの花"},
{"imageName":"romance-fragrance","category":"sundries","ability":"boostMP","abilityValue":15,"price":5,"giftRate":4,"name":"ロマンスの香木"},
{"imageName":"heaven-herb","category":"sundries","ability":"boostMPAndAddCurse","abilityValue":20,"curse":"heaven","price":20,"giftRate":1,"name":"天国草"},
{"imageName":"smile-shell","category":"sundries","ability":"removeMildCurses","price":5,"giftRate":12,"name":"スマイルの貝がら"},
{"imageName":"heart-shell","category":"sundries","ability":"removeAllCurses","price":15,"giftRate":6,"name":"ハートの貝がら"},
{"imageName":"guardian-pot","category":"sundries","ability":"setGuardian","price":10,"giftRate":3,"name":"守護封印のつぼ"},
{"imageName":"thump-thump-tear","category":"sundries","ability":"boostHPOrDealDamage","abilityValue":10,"price":1,"giftRate":2,"name":"ドキドキ涙"},
{"imageName":"strength-powder","category":"sundries","atk":10,"isPlusAtk":true,"price":15,"giftRate":2,"name":"ちからの粉"},
{"imageName":"spiritual-doll","category":"sundries","ability":"cutCost","price":5,"giftRate":2,"name":"精霊のぬいぐるみ"},
{"imageName":"nocturnal-broom","category":"sundries","ability":"removeItems","price":10,"giftRate":1,"name":"夜空のホウキ"},
{"imageName":"goddess-s-soap","category":"sundries","ability":"removeUsedMiracles","price":10,"giftRate":1,"name":"女神の石けん"},
{"imageName":"string-of-fate","category":"sundries","ability":"callPhenomenon","price":3,"giftRate":1,"name":"運命のひも"},
{"imageName":"sun-amulet","category":"sundries","ability":"revive","abilityValue":10,"price":10,"giftRate":1,"name":"太陽のお守り"},
{"imageName":"dangerous-mortar","category":"sundries","ability":"attractDanger","abilityValue":99,"price":1,"giftRate":1,"name":"あぶないウス"},
{"imageName":"fireball","category":"miracles","element":"fire","atk":2,"isPlusAtk":true,"cost":2,"giftRate":1,"name":"＜火の玉＞"},
{"imageName":"ice","category":"miracles","element":"water","atk":4,"cost":2,"giftRate":1,"name":"＜氷＞"},
{"imageName":"darkness","category":"miracles","element":"darkness","atk":5,"cost":5,"giftRate":1,"name":"＜闇＞"},
{"imageName":"big-tree","category":"miracles","element":"wood","atk":6,"cost":3,"giftRate":1,"name":"＜大木＞"},
{"imageName":"rock","category":"miracles","element":"stone","atk":8,"cost":4,"giftRate":1,"name":"＜岩＞"},
{"imageName":"flame","category":"miracles","element":"fire","atk":10,"cost":5,"giftRate":1,"name":"＜炎＞"},
{"imageName":"absorption","category":"miracles","element":"light","atk":10,"ability":"absorbHP","cost":10,"giftRate":1,"name":"＜吸収＞"},
{"imageName":"meteor","category":"miracles","element":"light","atk":10,"isPlusAtk":true,"cost":7,"giftRate":1,"name":"＜流星＞"},
{"imageName":"waterfall","category":"miracles","element":"water","atk":25,"cost":12,"giftRate":1,"name":"＜滝＞"},
{"imageName":"wind","category":"miracles","ability":"addCurse","curse":"cold","cost":6,"giftRate":1,"name":"＜風＞"},
{"imageName":"heaven-wind","category":"miracles","ability":"addCurse","curse":"heaven","cost":15,"giftRate":1,"name":"＜天国風＞"},
{"imageName":"fog","category":"miracles","element":"water","ability":"addCurse","curse":"fog","cost":3,"giftRate":1,"name":"＜霧＞"},
{"imageName":"dream","category":"miracles","element":"wood","ability":"addCurse","curse":"dream","cost":6,"giftRate":1,"name":"＜夢＞"},
{"imageName":"dark-cloud","category":"miracles","element":"darkness","ability":"addCurse","curse":"darkcloud","cost":5,"giftRate":1,"name":"＜暗雲＞"},
{"imageName":"flash","category":"miracles","element":"light","atk":1,"hitRate":25,"ability":"addCurseOnDamage","curse":"flash","cost":3,"giftRate":1,"name":"＜閃光＞"},
{"imageName":"smoke","category":"miracles","element":"fire","atk":5,"hitRate":75,"cost":4,"giftRate":1,"name":"＜煙＞"},
{"imageName":"avalanche","category":"miracles","element":"water","atk":8,"hitRate":75,"cost":6,"giftRate":1,"name":"＜雪崩＞"},
{"imageName":"thunder","category":"miracles","element":"light","atk":10,"hitRate":25,"cost":4,"giftRate":1,"name":"＜雷＞"},
{"imageName":"mudflow","category":"miracles","element":"stone","atk":12,"hitRate":50,"cost":6,"giftRate":1,"name":"＜土石流＞"},
{"imageName":"magma","category":"miracles","element":"fire","atk":15,"hitRate":75,"cost":10,"giftRate":1,"name":"＜マグマ＞"},
{"imageName":"ice-age","category":"miracles","element":"water","atk":30,"hitRate":75,"cost":30,"giftRate":1,"name":"＜氷河期＞"},
{"imageName":"aura","category":"miracles","isPlusAtk":true,"ability":"doubleAtk","cost":6,"giftRate":1,"name":"＜オーラ＞"},
{"imageName":"mirage","category":"miracles","isPlusAtk":true,"ability":"attackEveryEnemy","cost":5,"giftRate":1,"name":"＜蜃気楼＞"},
{"imageName":"wall","category":"miracles","ability":"blockWeapon","cost":6,"giftRate":1,"name":"＜壁＞"},
{"imageName":"turbulence","category":"miracles","ability":"bounceMiracle","cost":5,"giftRate":1,"name":"＜乱気流＞"},
{"imageName":"spring","category":"miracles","ability":"boostHP","abilityValue":10,"cost":7,"giftRate":1,"name":"＜泉＞"},
{"imageName":"treasure","category":"miracles","ability":"boostCP","abilityValue":10,"cost":5,"giftRate":1,"name":"＜財宝＞"},
{"imageName":"tone","category":"miracles","ability":"removeMildCurses","cost":2,"giftRate":1,"name":"＜音色＞"},
{"imageName":"song","category":"miracles","ability":"removeAllCurses","cost":5,"giftRate":1,"name":"＜歌声＞"},
{"imageName":"release","category":"miracles","ability":"setGuardian","cost":15,"giftRate":1,"name":"＜解放＞"},
{"imageName":"afterglow","category":"phenomena","ability":"setCurseOfEverybody","curse":"fever","name":"夕焼け"},
{"imageName":"dense-fog","category":"phenomena","ability":"setCurseOfEverybody","curse":"fog","name":"濃霧"},
{"imageName":"mushroom-outbreak","category":"phenomena","ability":"confuseEverybody","name":"きのこ大発生"},
{"imageName":"tornado","category":"phenomena","ability":"setHPOfEverybody","abilityValue":1,"name":"竜巻"},
{"imageName":"gigantic-tub","category":"phenomena","element":"light","atk":50,"ability":"attackSomebody","name":"巨大なタライ"},
{"imageName":"black-hole","category":"phenomena","element":"darkness","atk":30,"hitRate":75,"name":"ブラックホール"},
{"imageName":"warm-current","category":"phenomena","ability":"boostHP","abilityValue":50,"name":"暖流"},
{"imageName":"gold-mountain","category":"phenomena","ability":"collectCPOfEverybody","name":"金山"},
{"imageName":"magnetic-storm","category":"phenomena","ability":"shuffleItemsOfEverybody","name":"磁気嵐"},
{"imageName":"solar-eclipse","category":"phenomena","ability":"setGuardianOfEverybody","name":"日食"}
]
"""

ALL_ITEMS: list = json.loads(_ITEMS_JSON)

# ================================================================
# 定数
# ================================================================

ELEMENT_EMOJI = {
    "fire":     "🔥",
    "water":    "💧",
    "wood":     "🌿",
    "stone":    "🪨",
    "light":    "✨",
    "darkness": "🌑",
    "":         "",
}
ELEMENT_NAME = {
    "fire":     "🔥火",
    "water":    "💧水",
    "wood":     "🌿木",
    "stone":    "🪨土",
    "light":    "✨光",
    "darkness": "🌑闇",
    "":         "無",
}

# 攻撃属性 → それを防げる防具属性
# None = どの防具でも防御不可 (光)
# "any" = どの属性でも防御可 (無属性・闇)
ELEMENT_DEFENSE: dict = {
    "":         "any",    # 無属性: 何でも防御可
    "fire":     "water",  # 火: 水で防御
    "water":    "fire",   # 水: 火で防御
    "wood":     "stone",  # 木: 土で防御
    "stone":    "wood",   # 土: 木で防御
    "light":    None,     # 光: 防御不可
    "darkness": "any",    # 闇: 何でも防御可 (残ダメ時HP=0)
}

CURSE_NAME = {
    "cold":      "風邪",
    "fever":     "熱病",
    "hell":      "地獄病",
    "heaven":    "天国病",
    "fog":       "霧",
    "flash":     "閃光",
    "dream":     "夢",
    "darkcloud": "暗雲",
}
CURSE_DAMAGE = {"cold": 1, "fever": 2, "hell": 5}
CURSE_PROGRESS = {"cold": "fever", "fever": "hell", "hell": "heaven"}
MILD_CURSES = {"cold", "fever", "fog", "flash"}

GUARDIAN_NAME = {
    "mars":    "🔥火星神",
    "mercury": "💧水星神",
    "jupiter": "🌿木星神",
    "saturn":  "🪨土星神",
    "uranus":  "✨天王神",
    "pluto":   "🌑冥王神",
    "neptune": "🌊海王神",
    "venus":   "💰金星神",
    "earth":   "🌍地球神",
    "moon":    "🌙月神",
}
ALL_GUARDIANS = list(GUARDIAN_NAME.keys())

CAT_EMOJI = {
    "weapons":   "⚔️",
    "armor":     "🛡️",
    "sundries":  "🎒",
    "miracles":  "✨",
    "trade":     "💱",
}

# ================================================================
# ドロープール構築
# ================================================================

def _build_pool() -> list:
    pool = []
    for item in ALL_ITEMS:
        cat = item.get("category", "")
        if cat in ("devils", "guardians", "phenomena"):
            continue
        if item.get("ability") in ("discard", "sacrifice"):
            continue
        rate = item.get("giftRate", 1)
        pool.extend([item] * rate)
    return pool

_DRAW_POOL = _build_pool()
_PHENOMENA_POOL = [i for i in ALL_ITEMS if i.get("category") == "phenomena"]

# ================================================================
# Card クラス
# ================================================================

class Card:
    __slots__ = (
        "raw", "image_name", "name", "category", "element",
        "atk", "def_", "is_plus_atk", "hit_rate",
        "ability", "ability_value", "curse",
        "price", "gift_rate", "cost", "guardian", "is_reusable",
    )

    def __init__(self, data: dict):
        self.raw          = data
        self.image_name   = data.get("imageName", "")
        self.name         = data.get("name", "")
        self.category     = data.get("category", "")
        self.element      = data.get("element", "")
        self.atk          = data.get("atk", 0)
        self.def_         = data.get("def", 0)
        self.is_plus_atk  = data.get("isPlusAtk", False)
        self.hit_rate     = data.get("hitRate", 100)
        self.ability      = data.get("ability", "")
        self.ability_value = data.get("abilityValue", 0)
        self.curse        = data.get("curse", "")
        self.price        = data.get("price", 0)
        self.gift_rate    = data.get("giftRate", 1)
        self.cost         = data.get("cost", 0)
        self.guardian     = data.get("guardian", "")
        self.is_reusable  = (self.category == "miracles")

    # ---------- 表示用 ----------

    def label(self) -> str:
        """SelectOption ラベル用 (100文字以内)"""
        em = CAT_EMOJI.get(self.category, "")
        tags = []
        if self.atk:
            p = "+" if self.is_plus_atk else ""
            tags.append(f"{p}攻{self.atk}")
        if self.def_:
            tags.append(f"守{self.def_}")
        if self.element:
            tags.append(ELEMENT_EMOJI.get(self.element, ""))
        if self.hit_rate < 100:
            tags.append(f"{self.hit_rate}%")
        if self.cost:
            tags.append(f"MP{self.cost}")
        body = f" ({' '.join(tags)})" if tags else ""
        return f"{em}{self.name}{body}"[:100]

    def desc(self) -> str:
        """SelectOption description (100文字以内)"""
        parts = []
        if self.ability:
            parts.append(self.ability)
        if self.curse:
            parts.append(f"→{CURSE_NAME.get(self.curse, self.curse)}")
        if self.ability_value:
            parts.append(f"x{self.ability_value}")
        return (", ".join(parts) or self.category)[:100]

    def status_line(self) -> str:
        """手札表示の1行"""
        tags = []
        if self.element:
            tags.append(ELEMENT_NAME.get(self.element, ""))
        if self.atk:
            p = "+" if self.is_plus_atk else ""
            tags.append(f"{p}攻{self.atk}")
        if self.def_:
            tags.append(f"守{self.def_}")
        if self.hit_rate < 100:
            tags.append(f"命{self.hit_rate}%")
        if self.cost:
            tags.append(f"MP{self.cost}")
        inner = " ".join(tags)
        return f"{CAT_EMOJI.get(self.category,'')}{self.name}{'  ['+inner+']' if inner else ''}"

# ================================================================
# ヘルパー関数
# ================================================================

def draw_card() -> Card:
    return Card(dict(random.choice(_DRAW_POOL)))


def create_player(user) -> dict:
    return {
        "id":       user.id,
        "name":     user.display_name,
        "hp":       40,
        "mp":       10,
        "cp":       20,
        "items":    [draw_card() for _ in range(5)],  # 武器/防具/雑貨/取引
        "miracles": [],                               # 奇跡 (永続・再使用可)
        "curses":   {},                               # {curse_name: True}
        "guardian": None,
        "revive_hp": 0,                               # 太陽のお守りによる蘇生HP
        "cutcost":  False,                            # 消費なし (次の奇跡)
    }


def player_status_line(p: dict) -> str:
    icon = "💀" if p["hp"] <= 0 else "⚔️"
    curses = " ".join(CURSE_NAME.get(c, c) for c in p["curses"])
    guardian = f" [{GUARDIAN_NAME.get(p['guardian'],'?')}]" if p["guardian"] else ""
    curse_part = f" ☠️{curses}" if curses else ""
    return f"{icon} **{p['name']}** HP:{p['hp']} MP:{p['mp']} 💰{p['cp']}{guardian}{curse_part}"

# ================================================================
# UI Views
# ================================================================

class JoinView(discord.ui.View):
    def __init__(self, timeout: int):
        super().__init__(timeout=timeout)
        self.joined_users: list = []

    @discord.ui.button(label="⚔️ 参戦する", style=discord.ButtonStyle.primary)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if uid not in [u.id for u in self.joined_users]:
            self.joined_users.append(interaction.user)
            await interaction.response.send_message(
                f"✅ **{interaction.user.display_name}** が参戦！（現在 {len(self.joined_users)} 人）",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("すでに参加済みです。", ephemeral=True)


# ---------- ターン制御 ----------

class TurnControlView(discord.ui.View):
    def __init__(self, pid: int, player: dict, game: dict, channel, iid: str):
        super().__init__(timeout=90)
        self.pid = pid
        self.player = player
        self.game = game
        self.channel = channel
        self.iid = iid
        self.resolved = False

    @discord.ui.button(label="⚡ 行動開始", style=discord.ButtonStyle.primary)
    async def act(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.pid:
            return await interaction.response.send_message("あなたのターンではありません。", ephemeral=True)
        if self.game.get("active_interaction_id") != self.iid:
            return await interaction.response.send_message("このターンは既に終了しています。", ephemeral=True)
        self.resolved = True
        await interaction.response.send_message(
            embed=_hand_embed(self.player),
            view=ItemSelectView(self.player, self.game, self.channel, self.iid),
            ephemeral=True
        )

    async def on_timeout(self):
        if not self.resolved and self.game.get("active_interaction_id") == self.iid:
            self.game["active_interaction_id"] = None
            await self.channel.send(f"⏰ {self.player['name']} のターンがタイムアウトしました。")
            await self.game["cog"].process_turn_end(self.channel)


def _hand_embed(player: dict) -> discord.Embed:
    e = discord.Embed(title=f"📦 {player['name']} の手持ち神器", color=0x5865f2)
    items_text = "\n".join(f"`{i+1}.` {c.status_line()}" for i, c in enumerate(player["items"])) or "なし"
    e.add_field(name="神器", value=items_text[:1024], inline=False)
    if player["miracles"]:
        mir_text = "\n".join(f"✨ {m.status_line()}" for m in player["miracles"])
        e.add_field(name="奇跡（再使用可）", value=mir_text[:1024], inline=False)
    curse_text = "、".join(CURSE_NAME.get(c, c) for c in player["curses"]) or "なし"
    e.add_field(
        name="ステータス",
        value=f"HP:**{player['hp']}** MP:**{player['mp']}** 💰{player['cp']} | 災い:{curse_text}",
        inline=False
    )
    return e


# ---------- アイテム選択 ----------

class ItemSelectView(discord.ui.View):
    def __init__(self, player: dict, game: dict, channel, iid: str):
        super().__init__(timeout=90)
        self.player  = player
        self.game    = game
        self.channel = channel
        self.iid     = iid
        self._build()

    def _build(self):
        options = []
        for i, c in enumerate(self.player["items"]):
            options.append(discord.SelectOption(
                label=c.label()[:100], value=f"item_{i}", description=c.desc()
            ))
        for i, m in enumerate(self.player["miracles"]):
            cost = m.cost if not self.player.get("cutcost") else 0
            options.append(discord.SelectOption(
                label=m.label()[:100], value=f"mir_{i}",
                description=f"MP消費:{cost}  {m.desc()}"[:100]
            ))
        options.append(discord.SelectOption(label="🙏 祈る（スキップ）",        value="pray"))
        options.append(discord.SelectOption(label="🗑️ 捨てる（神器を1つ捨てる）", value="discard_action"))
        options.append(discord.SelectOption(label="🌟 ささげる（神器1つ→新神器）", value="sacrifice_action"))

        options = options[:25]  # Discord上限
        sel = discord.ui.Select(placeholder="神器を選んで行動してください", options=options)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.player["id"]:
            return await interaction.response.send_message("あなたのターンではありません。", ephemeral=True)
        if self.game.get("active_interaction_id") != self.iid:
            return await interaction.response.send_message("このターンは既に終了しています。", ephemeral=True)

        val = interaction.data["values"][0]
        cog = self.game["cog"]

        if val == "pray":
            self.game["active_interaction_id"] = None
            await interaction.response.send_message("🙏 祈りました。", ephemeral=True)
            return await cog.process_turn_end(self.channel)

        elif val == "discard_action":
            return await interaction.response.edit_message(
                content="🗑️ 捨てる神器を選択：", embed=None,
                view=DiscardSelectView(self.player, self.game, self.channel, self.iid, "discard")
            )

        elif val == "sacrifice_action":
            return await interaction.response.edit_message(
                content="🌟 ささげる神器を選択：", embed=None,
                view=DiscardSelectView(self.player, self.game, self.channel, self.iid, "sacrifice")
            )

        elif val.startswith("item_"):
            idx  = int(val[5:])
            card = self.player["items"][idx]
            await cog.handle_item_action(interaction, self.player, card, idx, self.game, self.channel, self.iid, is_miracle=False)

        elif val.startswith("mir_"):
            idx  = int(val[4:])
            card = self.player["miracles"][idx]
            cost = card.cost if not self.player.get("cutcost") else 0
            if self.player["mp"] < cost:
                return await interaction.response.send_message(
                    f"MPが足りません（必要:{cost} / 現在:{self.player['mp']}）", ephemeral=True
                )
            await cog.handle_item_action(interaction, self.player, card, idx, self.game, self.channel, self.iid, is_miracle=True)


# ---------- 捨てる / ささげる ----------

class DiscardSelectView(discord.ui.View):
    def __init__(self, player: dict, game: dict, channel, iid: str, mode: str):
        super().__init__(timeout=60)
        self.player  = player
        self.game    = game
        self.channel = channel
        self.iid     = iid
        self.mode    = mode
        opts = [
            discord.SelectOption(label=c.label()[:100], value=str(i))
            for i, c in enumerate(player["items"])
        ]
        sel = discord.ui.Select(placeholder="神器を選択", options=opts[:25])
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction):
        if self.game.get("active_interaction_id") != self.iid:
            return
        idx = int(interaction.data["values"][0])
        self.player["items"].pop(idx)
        cog = self.game["cog"]
        if self.mode == "sacrifice":
            self.player["items"].append(draw_card())
            await cog.log(self.channel, f"🌟 {self.player['name']} が神器をささげ、新しい神器を授かった。")
        else:
            await cog.log(self.channel, f"🗑️ {self.player['name']} が神器を捨てた。")
        self.game["active_interaction_id"] = None
        await interaction.response.send_message("完了。", ephemeral=True)
        await cog.process_turn_end(self.channel)


# ---------- 攻撃対象選択 ----------

class TargetSelectView(discord.ui.View):
    def __init__(self, attacker: dict, card: Card, card_idx: int,
                 game: dict, channel, iid: str, is_miracle: bool = False):
        super().__init__(timeout=60)
        self.attacker   = attacker
        self.card       = card
        self.card_idx   = card_idx
        self.game       = game
        self.channel    = channel
        self.iid        = iid
        self.is_miracle = is_miracle

        targets = [p for pid, p in game["players"].items()
                   if pid != attacker["id"] and p["hp"] > 0]
        for t in targets:
            btn = discord.ui.Button(
                label=f"⚔️ {t['name']} (HP:{t['hp']})",
                style=discord.ButtonStyle.danger
            )
            btn.callback = self._make_cb(t["id"])
            self.add_item(btn)

        cancel = discord.ui.Button(label="キャンセル", style=discord.ButtonStyle.secondary)
        cancel.callback = self._cancel
        self.add_item(cancel)

    def _make_cb(self, target_id: int):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.attacker["id"]: return
            if self.game.get("active_interaction_id") != self.iid: return
            if not self.is_miracle:
                self.attacker["items"].pop(self.card_idx)
                self.attacker["items"].append(draw_card())
            else:
                cost = self.card.cost if not self.attacker.get("cutcost") else 0
                self.attacker["mp"] = max(0, self.attacker["mp"] - cost)
                self.attacker["cutcost"] = False
            await interaction.response.edit_message(
                content=f"🎯 {self.game['players'][target_id]['name']} を攻撃対象に確定！", view=None
            )
            await self.game["cog"].trigger_defense_phase(
                self.channel, self.attacker, target_id, self.card
            )
        return cb

    async def _cancel(self, interaction: discord.Interaction):
        if interaction.user.id != self.attacker["id"]: return
        await interaction.response.edit_message(content="キャンセルしました。", view=None)


# ---------- 防御 ----------

class DefensePromptView(discord.ui.View):
    def __init__(self, attacker: dict, target_id: int, attack_card: Card, game: dict, channel):
        super().__init__(timeout=60)
        self.attacker    = attacker
        self.target_id   = target_id
        self.attack_card = attack_card
        self.game        = game
        self.channel     = channel
        self.resolved    = False

    @discord.ui.button(label="🛡️ 防御神器を選択", style=discord.ButtonStyle.success)
    async def open_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_id or self.resolved:
            return
        target = self.game["players"][self.target_id]
        atk_elem    = self.attack_card.element
        need_elem   = ELEMENT_DEFENSE.get(atk_elem, "any")  # 防御に必要な属性

        # 光属性: 防御不可
        if need_elem is None:
            self.resolved = True
            await interaction.response.send_message("✨ 光属性攻撃は防御不可！", ephemeral=True)
            return await self.game["cog"].resolve_damage(
                self.channel, self.attacker, target, self.attack_card, []
            )

        # 防御可能な防具を抽出
        eligible = []
        for i, c in enumerate(target["items"]):
            if c.category != "armor": continue
            if need_elem == "any":
                eligible.append((i, c))
            elif c.element == need_elem:
                eligible.append((i, c))

        # 閃光カース: 防御1枚まで
        max_sel = 1 if "flash" in target["curses"] else max(1, len(eligible))

        options = [discord.SelectOption(label="🙏 無防備（防御しない）", value="none")]
        for i, c in eligible:
            options.append(discord.SelectOption(
                label=c.label()[:100], value=str(i), description=c.desc()
            ))

        sel = discord.ui.Select(
            placeholder="防御神器を選択（複数可）",
            options=options[:25],
            min_values=1,
            max_values=min(max_sel, len(options))
        )

        async def defense_cb(inter: discord.Interaction):
            if self.resolved: return
            self.resolved = True
            defense_cards = []
            if "none" not in sel.values:
                for idx_str in sorted([int(x) for x in sel.values], reverse=True):
                    if idx_str < len(target["items"]):
                        c = target["items"].pop(idx_str)
                        defense_cards.append(c)
                        target["items"].append(draw_card())
            await inter.response.send_message("🛡️ 防御確定。", ephemeral=True)
            await self.game["cog"].resolve_damage(
                self.channel, self.attacker, target, self.attack_card, defense_cards
            )

        sel.callback = defense_cb
        v = discord.ui.View()
        v.add_item(sel)
        elem_hint = f"（{ELEMENT_NAME.get(atk_elem,'無')}属性攻撃 → {ELEMENT_NAME.get(need_elem, need_elem if need_elem else '?')} 属性防具で防御可）"
        await interaction.response.send_message(
            f"⚔️ **{self.attacker['name']}** の **{self.attack_card.label()}** {elem_hint}",
            view=v, ephemeral=True
        )

    async def on_timeout(self):
        if not self.resolved:
            self.resolved = True
            target = self.game["players"][self.target_id]
            await self.game["cog"].resolve_damage(
                self.channel, self.attacker, target, self.attack_card, []
            )


# ---------- 両替 ----------

class ExchangeView(discord.ui.View):
    def __init__(self, player: dict, card_idx: int, game: dict, channel, iid: str):
        super().__init__(timeout=60)
        self.player   = player
        self.card_idx = card_idx
        self.game     = game
        self.channel  = channel
        self.iid      = iid

    async def _do(self, interaction, src: str, dst: str, amount: int = 10):
        if self.game.get("active_interaction_id") != self.iid: return
        if self.player.get(src, 0) < amount:
            return await interaction.response.send_message(
                f"{src} が足りません（必要:{amount} / 現在:{self.player.get(src,0)}）", ephemeral=True
            )
        self.player[src] -= amount
        self.player[dst] += amount
        self.player["items"].pop(self.card_idx)
        self.player["items"].append(draw_card())
        self.game["active_interaction_id"] = None
        await self.game["cog"].log(self.channel, f"💱 {self.player['name']} 両替（{src}→{dst} 各{amount}）")
        await interaction.response.send_message("両替完了。", ephemeral=True)
        await self.game["cog"].process_turn_end(self.channel)

    @discord.ui.button(label="HP10 → MP10",  style=discord.ButtonStyle.secondary)
    async def hp_mp(self, i, b): await self._do(i, "hp", "mp")
    @discord.ui.button(label="HP10 → 💰10",  style=discord.ButtonStyle.secondary)
    async def hp_cp(self, i, b): await self._do(i, "hp", "cp")
    @discord.ui.button(label="MP10 → HP10",  style=discord.ButtonStyle.secondary)
    async def mp_hp(self, i, b): await self._do(i, "mp", "hp")
    @discord.ui.button(label="MP10 → 💰10",  style=discord.ButtonStyle.secondary)
    async def mp_cp(self, i, b): await self._do(i, "mp", "cp")
    @discord.ui.button(label="💰10 → HP10",  style=discord.ButtonStyle.secondary)
    async def cp_hp(self, i, b): await self._do(i, "cp", "hp")
    @discord.ui.button(label="💰10 → MP10",  style=discord.ButtonStyle.secondary)
    async def cp_mp(self, i, b): await self._do(i, "cp", "mp")


# ---------- 売る ----------

class SellSelectView(discord.ui.View):
    """売る神器と相手を選ぶ"""
    def __init__(self, player: dict, tool_idx: int, game: dict, channel, iid: str):
        super().__init__(timeout=60)
        self.player   = player
        self.tool_idx = tool_idx
        self.game     = game
        self.channel  = channel
        self.iid      = iid
        opts = [
            discord.SelectOption(label=f"{c.name} (💰{c.price})", value=str(i))
            for i, c in enumerate(player["items"]) if i != tool_idx
        ]
        if opts:
            sel = discord.ui.Select(placeholder="売りつける神器を選択", options=opts[:25])
            sel.callback = self._on_select
            self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction):
        item_idx = int(interaction.data["values"][0])
        item = self.player["items"][item_idx]
        targets = [p for pid, p in self.game["players"].items()
                   if pid != self.player["id"] and p["hp"] > 0]
        view = SellTargetView(self.player, item, item_idx, self.tool_idx, self.game, self.channel, self.iid, targets)
        await interaction.response.edit_message(content=f"{item.name} を誰に売りますか？", view=view)


class SellTargetView(discord.ui.View):
    def __init__(self, seller: dict, item: Card, item_idx: int, tool_idx: int,
                 game: dict, channel, iid: str, targets: list):
        super().__init__(timeout=60)
        for t in targets:
            btn = discord.ui.Button(
                label=f"{t['name']} (所持💰:{t['cp']})", style=discord.ButtonStyle.secondary
            )
            btn.callback = self._make_cb(seller, item, item_idx, tool_idx, game, channel, iid, t["id"])
            self.add_item(btn)

    @staticmethod
    def _make_cb(seller, item, item_idx, tool_idx, game, channel, iid, tid):
        async def cb(interaction: discord.Interaction):
            if game.get("active_interaction_id") != iid: return
            t = game["players"][tid]
            price = item.price
            # 代金徴収: CP → MP → HP の順で消費
            remain = price
            for key in ("cp", "mp", "hp"):
                if remain <= 0: break
                paid = min(t[key], remain)
                t[key] -= paid
                remain  -= paid
            t["hp"] = max(0, t["hp"])
            seller["cp"] += price
            # アイテム交換
            seller["items"].pop(item_idx)
            adj = tool_idx if tool_idx < len(seller["items"]) else max(0, tool_idx - 1)
            if seller["items"]: seller["items"].pop(adj)
            while len(seller["items"]) < 5: seller["items"].append(draw_card())
            t["items"].append(item)
            game["active_interaction_id"] = None
            await game["cog"].log(channel, f"💰 {seller['name']} → {t['name']} に {item.name} を 💰{price} で売った。")
            await interaction.response.send_message("売買完了。", ephemeral=True)
            await game["cog"].process_turn_end(channel)
        return cb


# ---------- 買う ----------

class BuyTargetView(discord.ui.View):
    """買う: 相手プレイヤーを選ぶ"""
    def __init__(self, buyer: dict, tool_idx: int, game: dict, channel, iid: str):
        super().__init__(timeout=60)
        targets = [p for pid, p in game["players"].items()
                   if pid != buyer["id"] and p["hp"] > 0]
        for t in targets:
            btn = discord.ui.Button(label=f"{t['name']} の神器を見る", style=discord.ButtonStyle.secondary)
            btn.callback = self._make_cb(buyer, tool_idx, t, game, channel, iid)
            self.add_item(btn)

    @staticmethod
    def _make_cb(buyer, tool_idx, target_player, game, channel, iid):
        async def cb(interaction: discord.Interaction):
            items = target_player["items"]
            opts = [
                discord.SelectOption(label=f"{c.name} (💰{c.price})", value=str(i))
                for i, c in enumerate(items)
            ]
            if not opts:
                return await interaction.response.send_message("相手の神器がありません。", ephemeral=True)
            sel = discord.ui.Select(placeholder="購入する神器を選択", options=opts[:25])

            async def buy_cb(inter: discord.Interaction):
                if game.get("active_interaction_id") != iid: return
                idx  = int(inter.data["values"][0])
                item = target_player["items"][idx]
                if buyer["cp"] < item.price:
                    return await inter.response.send_message(
                        f"💰が足りません（必要:{item.price} / 現在:{buyer['cp']}）", ephemeral=True
                    )
                buyer["cp"] -= item.price
                target_player["cp"] += item.price
                target_player["items"].pop(idx)
                target_player["items"].append(draw_card())
                buyer["items"].pop(tool_idx)
                buyer["items"].append(item)
                game["active_interaction_id"] = None
                cog = game["cog"]
                await cog.log(channel, f"💰 {buyer['name']} が {target_player['name']} から {item.name} を 💰{item.price} で購入。")
                await inter.response.send_message("購入完了。", ephemeral=True)
                await cog.process_turn_end(channel)

            sel.callback = buy_cb
            v = discord.ui.View()
            v.add_item(sel)
            await interaction.response.edit_message(content=f"{target_player['name']} の神器一覧：", view=v)
        return cb


# ---------- 奇跡の呪い付与: 対象選択 ----------

class CurseTargetView(discord.ui.View):
    """addCurse 奇跡で呪いを与える対象を選ぶ"""
    def __init__(self, caster: dict, card: Card, card_idx: int,
                 game: dict, channel, iid: str, is_miracle: bool):
        super().__init__(timeout=60)
        self.caster     = caster
        self.card       = card
        self.card_idx   = card_idx
        self.game       = game
        self.channel    = channel
        self.iid        = iid
        self.is_miracle = is_miracle

        targets = [p for pid, p in game["players"].items()
                   if pid != caster["id"] and p["hp"] > 0]
        for t in targets:
            btn = discord.ui.Button(label=f"☠️ {t['name']}", style=discord.ButtonStyle.danger)
            btn.callback = self._make_cb(t["id"])
            self.add_item(btn)

    def _make_cb(self, tid: int):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.caster["id"]: return
            if self.game.get("active_interaction_id") != self.iid: return
            target = self.game["players"][tid]
            target["curses"][self.card.curse] = True
            # MP消費
            if self.is_miracle:
                cost = self.card.cost if not self.caster.get("cutcost") else 0
                self.caster["mp"] = max(0, self.caster["mp"] - cost)
                self.caster["cutcost"] = False
            else:
                self.caster["items"].pop(self.card_idx)
                self.caster["items"].append(draw_card())
            self.game["active_interaction_id"] = None
            cog = self.game["cog"]
            await cog.log(self.channel,
                f"☠️ {self.caster['name']} が {target['name']} に **{CURSE_NAME.get(self.card.curse, self.card.curse)}** を与えた！")
            await interaction.response.edit_message(content="呪い付与完了。", view=None)
            await cog.process_turn_end(self.channel)
        return cb


# ================================================================
# メイン Cog
# ================================================================

class GodField(commands.Cog):
    def __init__(self, bot):
        self.bot   = bot
        self.games: dict = {}

    # ---------- ユーティリティ ----------

    async def log(self, channel, text: str):
        g   = self.games.get(channel.id)
        msg = await channel.send(text)
        if g:
            g["temp_msgs"].append(msg)

    def _status_embed(self, game: dict, title: str = "") -> discord.Embed:
        lines = [player_status_line(p) for p in game["players"].values()]
        e = discord.Embed(
            title=title or f"ゴッドフィールド Round {game['round']}",
            description="\n".join(lines),
            color=0x2b2d31
        )
        return e

    # ---------- ゲーム開始 ----------

        if len(v.joined_users) < 2:
            return await ctx.send("⚠️ 人数不足（最低2名）のため中止します。")

        players     = {u.id: create_player(u) for u in v.joined_users}
        turn_order  = list(players.keys())
        random.shuffle(turn_order)

        self.games[ctx.channel.id] = {
            "players":              players,
            "turn_order":           turn_order,
            "current_index":        0,
            "round":                1,
            "active_interaction_id": None,
            "cog":                  self,
            "temp_msgs":            [],
            "tiebreak":             False,
        }
        names = "、".join(p["name"] for p in players.values())
        await ctx.send(f"🌟 **戦い開始！** 参戦者：{names}")
        await self.send_turn_panel(ctx.channel)

    # ---------- ターンパネル ----------

    async def send_turn_panel(self, channel):
        if channel.id not in self.games: return
        g = self.games[channel.id]

        # 前ターンのメッセージを掃除
        for m in g["temp_msgs"]:
            try: await m.delete()
            except: pass
        g["temp_msgs"] = []

        pid    = g["turn_order"][g["current_index"]]
        player = g["players"][pid]

        # ターン開始: 呪いダメージ
        await self._apply_curse_effects(channel, player, g)
        if player["hp"] <= 0:
            await self.log(channel, f"💀 {player['name']} が災いで昇天した。")
            return await self.process_turn_end(channel)

        # 新しい神器を授かる
        new = draw_card()
        if new.category == "miracles":
            player["miracles"].append(new)
            await self.log(channel, f"✨ {player['name']} が奇跡 **{new.name}** を授かった！")
        else:
            player["items"].append(new)
            await self.log(channel, f"📦 {player['name']} が **{new.name}** を授かった。")

        iid = str(uuid.uuid4())
        g["active_interaction_id"] = iid

        e = self._status_embed(g, f"⚡ Round {g['round']} — {player['name']} のターン")
        m = await channel.send(
            content=f"<@{pid}> ⚡ 行動を選択してください：",
            embed=e,
            view=TurnControlView(pid, player, g, channel, iid)
        )
        g["temp_msgs"].append(m)

    # ---------- 呪い処理 ----------

    async def _apply_curse_effects(self, channel, player: dict, game: dict):
        to_upgrade = []
        for curse in list(player["curses"]):
            dmg = CURSE_DAMAGE.get(curse, 0)
            if curse == "heaven":
                player["hp"] += 5
                await self.log(channel, f"😇 {player['name']} 天国病 HP+5")
                if random.random() < 0.05:
                    player["hp"] = 0
                    await self.log(channel, f"💥 {player['name']} の天国病が発作！ HP→0")
                continue
            if dmg:
                player["hp"] -= dmg
                await self.log(channel, f"{'🤧🤒💀'[['cold','fever','hell'].index(curse)]} {player['name']} {CURSE_NAME[curse]} -{dmg}HP")
            if random.random() < 0.05:
                nxt = CURSE_PROGRESS.get(curse)
                if nxt:
                    to_upgrade.append((curse, nxt))

        for old, new in to_upgrade:
            player["curses"].pop(old, None)
            player["curses"][new] = True
            await self.log(channel, f"😱 {player['name']} の **{CURSE_NAME[old]}** が **{CURSE_NAME[new]}** に悪化！")

        player["hp"] = max(0, player["hp"])

    # ---------- アイテム使用ハンドラ ----------

    async def handle_item_action(self, interaction, player: dict, card: Card, card_idx: int,
                                  game: dict, channel, iid: str, is_miracle: bool):
        cog = game["cog"]

        # ===== トレードカード =====
        if card.category == "trade":
            if card.ability == "exchange":
                return await interaction.response.edit_message(
                    content="💱 【両替】組み合わせを選択：", embed=None,
                    view=ExchangeView(player, card_idx, game, channel, iid)
                )
            if card.ability == "sell":
                return await interaction.response.edit_message(
                    content="💰 【売る】売りつける神器を選択：", embed=None,
                    view=SellSelectView(player, card_idx, game, channel, iid)
                )
            if card.ability == "buy":
                return await interaction.response.edit_message(
                    content="💰 【買う】購入先を選択：", embed=None,
                    view=BuyTargetView(player, card_idx, game, channel, iid)
                )
            return

        # ===== 武器 =====
        if card.category == "weapons":
            # マジカルステッキ: MP×2攻撃
            if card.ability == "atkBy2xMP":
                eff_atk = player["mp"] * 2
                proxy = Card(dict(card.raw, atk=eff_atk, ability=""))
                return await interaction.response.edit_message(
                    content=f"⚔️ {card.name}（攻:{eff_atk}）— 攻撃対象を選択：", embed=None,
                    view=TargetSelectView(player, proxy, card_idx, game, channel, iid, is_miracle=False)
                )
            # 通常武器（攻撃値があるもの）
            return await interaction.response.edit_message(
                content=f"⚔️ 【{card.name}】攻撃対象を選択：", embed=None,
                view=TargetSelectView(player, card, card_idx, game, channel, iid, is_miracle=False)
            )

        # ===== 奇跡 =====
        if card.category == "miracles":
            cost = card.cost if not player.get("cutcost") else 0

            # 攻撃奇跡
            if card.atk > 0 or card.ability in ("absorbHP", "doubleAtk"):
                # 蜃気楼: 全敵攻撃（特殊）
                if card.ability == "attackEveryEnemy":
                    player["mp"] = max(0, player["mp"] - cost)
                    player["cutcost"] = False
                    game["active_interaction_id"] = None
                    targets = [p for pid, p in game["players"].items()
                               if pid != player["id"] and p["hp"] > 0]
                    await interaction.response.send_message(f"🌀 {card.name} — 全敵攻撃！", ephemeral=True)
                    for t in targets:
                        await cog.trigger_defense_phase(channel, player, t["id"], card)
                    return
                return await interaction.response.edit_message(
                    content=f"✨ 【{card.name}】(MP{cost}) 攻撃対象を選択：", embed=None,
                    view=TargetSelectView(player, card, card_idx, game, channel, iid, is_miracle=True)
                )

            # 呪い付与奇跡 (addCurse)
            if card.ability == "addCurse":
                return await interaction.response.edit_message(
                    content=f"☠️ 【{card.name}】呪いを与える相手を選択：", embed=None,
                    view=CurseTargetView(player, card, card_idx, game, channel, iid, is_miracle=True)
                )

            # 非攻撃奇跡 (回復・守護神など) → 即時発動
            player["mp"] = max(0, player["mp"] - cost)
            player["cutcost"] = False
            game["active_interaction_id"] = None
            await interaction.response.send_message(f"✨ {card.name} 発動！", ephemeral=True)
            await cog._apply_noncombat_effect(channel, player, card, game)
            return await cog.process_turn_end(channel)

        # ===== 防具 =====
        if card.category == "armor":
            return await interaction.response.send_message(
                "🛡️ 防具は攻撃された時に防御で使います。他の行動を選んでください。",
                ephemeral=True
            )

        # ===== 雑貨 =====
        if card.category == "sundries":
            game["active_interaction_id"] = None
            player["items"].pop(card_idx)
            player["items"].append(draw_card())
            await interaction.response.send_message(f"🎒 {card.name} を使用！", ephemeral=True)
            await cog._apply_noncombat_effect(channel, player, card, game)
            return await cog.process_turn_end(channel)

    # ---------- 非戦闘エフェクト (奇跡/雑貨 共通) ----------

    async def _apply_noncombat_effect(self, channel, player: dict, card: Card, game: dict):
        ab  = card.ability
        val = card.ability_value

        if ab == "boostHP":
            player["hp"] += val
            await self.log(channel, f"💚 {player['name']} HP+{val}（{card.name}）")

        elif ab == "boostMP":
            player["mp"] += val
            await self.log(channel, f"💙 {player['name']} MP+{val}（{card.name}）")

        elif ab == "boostCP":
            player["cp"] += val
            await self.log(channel, f"💰 {player['name']} 💰+{val}（{card.name}）")

        elif ab == "boostMPAndAddCurse":
            player["mp"] += val
            player["curses"][card.curse] = True
            await self.log(channel, f"💙 {player['name']} MP+{val} → {CURSE_NAME.get(card.curse,'?')} 発症！")

        elif ab == "removeAllCurses":
            player["curses"].clear()
            await self.log(channel, f"✨ {player['name']} の全ての災いが払われた！")

        elif ab == "removeMildCurses":
            for c in MILD_CURSES: player["curses"].pop(c, None)
            await self.log(channel, f"🐚 {player['name']} の軽い災いが払われた。")

        elif ab == "setGuardian":
            g_key = random.choice(ALL_GUARDIANS)
            player["guardian"] = g_key
            await self.log(channel, f"🌟 {player['name']} に守護神 **{GUARDIAN_NAME.get(g_key)}** が宿った！")

        elif ab == "cutCost":
            player["cutcost"] = True
            await self.log(channel, f"✨ {player['name']} 次の奇跡のMP消費が0になった！")

        elif ab == "revive":
            player["revive_hp"] = val
            await self.log(channel, f"☀️ {player['name']} が太陽のお守りを装備（HP0時 +{val}蘇生）")

        elif ab == "removeItems":
            targets = [p for pid, p in game["players"].items()
                       if pid != player["id"] and p["hp"] > 0]
            if targets:
                t = random.choice(targets)
                removed = 0
                for _ in range(3):
                    if t["items"]:
                        i = random.randrange(len(t["items"]))
                        t["items"].pop(i)
                        t["items"].append(draw_card())
                        removed += 1
                await self.log(channel, f"🧹 {player['name']} が {t['name']} の神器を {removed} 個掃いた！")

        elif ab == "removeUsedMiracles":
            targets = [p for pid, p in game["players"].items()
                       if pid != player["id"] and p["hp"] > 0]
            if targets:
                t = random.choice(targets)
                n = min(2, len(t["miracles"]))
                for _ in range(n): t["miracles"].pop(random.randrange(len(t["miracles"])))
                await self.log(channel, f"🧼 {player['name']} が {t['name']} の奇跡を {n} 個洗い流した！")

        elif ab == "boostHPOrDealDamage":
            targets = [p for pid, p in game["players"].items()
                       if pid != player["id"] and p["hp"] > 0]
            if targets and random.random() < 0.5:
                t = random.choice(targets)
                t["hp"] = max(0, t["hp"] - val)
                await self.log(channel, f"💧 ドキドキ涙が {t['name']} に {val} ダメージ！")
            else:
                player["hp"] += val
                await self.log(channel, f"💧 ドキドキ涙で HP+{val}！")

        elif ab == "callPhenomenon":
            await self._call_phenomenon(channel, game)

        elif ab == "attractDanger":
            await self.log(channel, f"💥 あぶないウス！ {player['name']} に 99 ダメージ！！")
            player["hp"] = max(0, player["hp"] - 99)

        elif ab == "selfCurse":
            player["curses"][card.curse] = True
            await self.log(channel, f"😈 {player['name']} 自身に {CURSE_NAME.get(card.curse,'?')} 発症（{card.name}）")

        elif ab == "selfCurseAndRedraw":
            player["curses"][card.curse] = True
            # 神器を全て入れ替え
            player["items"] = [draw_card() for _ in range(len(player["items"]))]
            await self.log(channel, f"🌀 {player['name']} {CURSE_NAME.get(card.curse,'?')} + 神器全一新！")

        elif ab == "blockWeapon":
            # <壁> は防御フェーズ用だが雑貨/奇跡として使った場合は無効
            await self.log(channel, f"🧱 {card.name} は防御フェーズでのみ有効です。")

    # ---------- 超常現象 ----------

    async def _call_phenomenon(self, channel, game: dict):
        if not _PHENOMENA_POOL: return
        p_card = Card(random.choice(_PHENOMENA_POOL))
        await self.log(channel, f"🌀 **超常現象！** ✦ {p_card.name} ✦ が発生！")
        players = list(game["players"].values())
        alive   = [p for p in players if p["hp"] > 0]

        if p_card.ability == "setCurseOfEverybody":
            for pl in alive:
                pl["curses"][p_card.curse] = True
            await self.log(channel, f"全員に **{CURSE_NAME.get(p_card.curse,'?')}** が！")

        elif p_card.ability == "setHPOfEverybody":
            for pl in alive: pl["hp"] = max(1, p_card.ability_value)
            await self.log(channel, f"全員のHPが {p_card.ability_value} に！")

        elif p_card.ability == "boostHP":
            for pl in alive: pl["hp"] += p_card.ability_value
            await self.log(channel, f"全員 HP+{p_card.ability_value}！")

        elif p_card.ability == "collectCPOfEverybody":
            total = sum(p["cp"] for p in alive)
            for pl in alive: pl["cp"] = 0
            lucky = random.choice(alive)
            lucky["cp"] = total
            await self.log(channel, f"💰 全員の所持金 {total} 円が {lucky['name']} に集まった！")

        elif p_card.ability == "shuffleItemsOfEverybody":
            all_items = []
            for pl in alive:
                all_items.extend(pl["items"])
                pl["items"] = []
            random.shuffle(all_items)
            for pl in alive:
                n = max(3, min(8, len(all_items) // len(alive)))
                pl["items"] = all_items[:n]
                all_items   = all_items[n:]
            await self.log(channel, "🌀 全員の神器が無作為に入れ替わった！")

        elif p_card.ability == "attackSomebody" and p_card.atk > 0:
            t = random.choice(alive)
            t["hp"] = max(0, t["hp"] - p_card.atk)
            await self.log(channel, f"💥 {p_card.name} が {t['name']} に {p_card.atk} ダメージ！")

        elif p_card.atk > 0:
            t    = random.choice(alive)
            hit  = random.randint(1, 100) <= (p_card.hit_rate if p_card.hit_rate < 100 else 100)
            if hit:
                t["hp"] = max(0, t["hp"] - p_card.atk)
                await self.log(channel, f"💥 {p_card.name} が {t['name']} に {p_card.atk} ダメージ！")
            else:
                await self.log(channel, f"💨 {p_card.name} — 外れた！")

        elif p_card.ability == "confuseEverybody":
            await self.log(channel, "🍄 きのこ大発生！全員が混乱し 3 回ずつ勝手に行動する！")
            for pl in alive:
                for _ in range(3):
                    if pl["items"]:
                        c = random.choice(pl["items"])
                        # 雑貨をランダム使用（簡易）
                        if c.category == "sundries" and c.ability == "boostHP":
                            pl["hp"] += c.ability_value
                        elif c.category == "weapons" and c.atk > 0:
                            others = [x for x in alive if x["id"] != pl["id"]]
                            if others:
                                random.choice(others)["hp"] = max(0, random.choice(others)["hp"] - c.atk)

    # ---------- 防御フェーズ ----------

    async def trigger_defense_phase(self, channel, attacker: dict, target_id: int, attack_card: Card):
        if channel.id not in self.games: return
        g      = self.games[channel.id]
        target = g["players"][target_id]

        # 命中判定
        hit_chance = attack_card.hit_rate
        # 暗雲: 全体攻撃（isPlusAtk）は必中
        if "darkcloud" in target.get("curses", {}) and attack_card.is_plus_atk:
            hit_chance = 100

        roll = random.randint(1, 100)
        if roll > hit_chance:
            await self.log(channel, f"💨 **外れた！** ({attack_card.name} 命中率:{hit_chance}% / 出目:{roll})")
            return await self.process_turn_end(channel)

        await self.log(channel,
            f"⚔️ **{attacker['name']}** → **{target['name']}** ：{attack_card.label()}"
        )
        view = DefensePromptView(attacker, target_id, attack_card, g, channel)
        m = await channel.send(
            content=f"<@{target_id}> 🛡️ 防御神器を選択してください！（60秒）",
            view=view
        )
        g["temp_msgs"].append(m)

    # ---------- ダメージ解決 ----------

    async def resolve_damage(self, channel, attacker: dict, target: dict,
                              attack_card: Card, defense_cards: list):
        if channel.id not in self.games: return
        g        = self.games[channel.id]
        atk_elem = attack_card.element
        need_def = ELEMENT_DEFENSE.get(atk_elem, "any")

        # === 特殊防御: 全反射 ===
        for dc in defense_cards:
            if dc.ability == "reflectAnything":
                await self.log(channel, f"🪞 **スーパーミラー** で全て跳ね返した！")
                return await self.trigger_defense_phase(channel, target, attacker["id"], attack_card)

            if dc.ability == "filterAtkElement":
                # 虹のカーテン: 攻撃の属性を除去 → 無属性扱い
                proxy    = Card(dict(attack_card.raw, element=""))
                attack_card = proxy
                atk_elem = ""
                need_def = "any"
                await self.log(channel, f"🌈 虹のカーテンが攻撃の属性を除去！（無属性として処理）")
                break

        # 奇跡ブロック / バウンス
        for dc in defense_cards:
            if dc.ability == "blockMiracle" and attack_card.is_reusable:
                await self.log(channel, f"🛑 {dc.name} が奇跡を止めた！")
                return await self.process_turn_end(channel)
            if dc.ability == "reflectMiracle" and attack_card.is_reusable:
                await self.log(channel, f"🔄 {dc.name} が奇跡を跳ね返した！")
                return await self.trigger_defense_phase(channel, target, attacker["id"], attack_card)
            if dc.ability == "bounceMiracle" and attack_card.is_reusable:
                others = [p for pid, p in g["players"].items()
                          if pid != target["id"] and p["hp"] > 0]
                nt = random.choice(others) if others else target
                await self.log(channel, f"💨 {dc.name} が奇跡を弾いた → {nt['name']} へ！")
                return await self.trigger_defense_phase(channel, attacker, nt["id"], attack_card)

        # 無属性武器バウンス / 反射
        if not atk_elem and not attack_card.is_reusable:
            for dc in defense_cards:
                if dc.ability == "reflectWeapon":
                    await self.log(channel, f"🔄 {dc.name} が武器を跳ね返した！")
                    return await self.trigger_defense_phase(channel, target, attacker["id"], attack_card)
                if dc.ability == "bounceWeapon":
                    alive = [p for pid, p in g["players"].items() if p["hp"] > 0]
                    nt = random.choice(alive)
                    await self.log(channel, f"💨 {dc.name} が武器を弾いた → {nt['name']} へ！")
                    return await self.trigger_defense_phase(channel, attacker, nt["id"], attack_card)

        # ＜壁＞: 無属性武器をブロック
        for dc in defense_cards:
            if dc.ability == "blockWeapon" and not atk_elem and not attack_card.is_reusable:
                await self.log(channel, f"🧱 {dc.name} が武器を完全に止めた！")
                return await self.process_turn_end(channel)

        # === 防御値計算 ===
        total_def = 0
        for dc in defense_cards:
            if need_def is None:
                # 光属性: 何も防げない（既に DefensePromptView で防御不可通知済み）
                pass
            elif need_def == "any":
                total_def += dc.def_
            elif dc.element == need_def:
                total_def += dc.def_
            else:
                await self.log(channel,
                    f"⚠️ {dc.name}（{ELEMENT_NAME.get(dc.element,'無')}）は"
                    f"{ELEMENT_NAME.get(atk_elem,'無')} 属性攻撃を防げない！"
                )

        # オーラ: 倍攻撃
        base_atk = attack_card.atk
        if attack_card.ability == "doubleAtk":
            base_atk *= 2

        dmg = max(0, base_atk - total_def)

        # 闇属性: 残ダメがあれば HP=0
        if atk_elem == "darkness" and dmg > 0:
            target["hp"] = 0
            await self.log(channel, f"🌑 **闇属性！** {target['name']} のHPが0になった！")
        else:
            target["hp"] = max(0, target["hp"] - dmg)
            elem_str = f" [{ELEMENT_NAME.get(atk_elem,'無')}]" if atk_elem else ""
            await self.log(channel,
                f"💥 {target['name']} に **{dmg}ダメージ**{elem_str}"
                f"（攻{base_atk} - 守{total_def}）　HP残:{target['hp']}"
            )

        # === 攻撃後エフェクト ===
        if dmg > 0:
            if attack_card.ability == "absorbHP":
                attacker["hp"] += dmg
                await self.log(channel, f"{attacker['name']} HP+{dmg}（HP吸収）")

            if attack_card.ability == "dealSameDamage":
                attacker["hp"] = max(0, attacker["hp"] - dmg)
                await self.log(channel, f"{attacker['name']} にも {dmg} ダメージ（邪神の大剣）")

            if attack_card.ability == "addCurseOnDamage" and attack_card.curse:
                target["curses"][attack_card.curse] = True
                await self.log(channel,
                    f"{target['name']} に **{CURSE_NAME.get(attack_card.curse,'?')}** が発症！"
                )

            if attack_card.ability == "attackTwice":
                await self.log(channel, f"{attack_card.name} — **二回攻撃！**")
                return await self.trigger_defense_phase(channel, attacker, target["id"], attack_card)

        # === 防御カウンター ===
        for dc in defense_cards:
            if dc.ability == "counterAtk" and dmg > 0:
                attacker["hp"] = max(0, attacker["hp"] - dmg)
                await self.log(channel, f"{target['name']} 反撃！ {dmg} ダメージ！（{dc.name}）")
            elif dc.ability == "counter2xAtk" and dmg > 0:
                attacker["hp"] = max(0, attacker["hp"] - dmg * 2)
                await self.log(channel, f"{target['name']} 2倍反撃！ {dmg*2} ダメージ！（{dc.name}）")
            elif dc.ability == "counterBoost2xMP" and dmg > 0:
                target["mp"] += dmg * 2
                await self.log(channel, f"{target['name']} MP+{dmg*2}（海王の指輪）")
            elif dc.ability == "counterTakeCP" and dmg > 0:
                taken = min(attacker["cp"], dmg)
                attacker["cp"] -= taken
                target["cp"]   += taken
                await self.log(channel, f"{target['name']} が {attacker['name']} から 💰{taken} 没収！（金星の指輪）")
            elif dc.ability == "counterCurse" and dmg > 0:
                attacker["curses"][dc.curse] = True
                await self.log(channel,
                    f"☠️ {target['name']} の {dc.name} が {attacker['name']} に"
                    f" **{CURSE_NAME.get(dc.curse,'?')}** を与えた！"
                )

        # 昇天チェック (対象)
        if target["hp"] <= 0:
            if target.get("revive_hp", 0):
                target["hp"] = target["revive_hp"]
                target["revive_hp"] = 0
                await self.log(channel, f"{target['name']} 蘇生！ HP:{target['hp']}")
            else:
                await self.log(channel, f"**{target['name']}** が昇天した！")

        # 昇天チェック (攻撃側)
        if attacker["hp"] <= 0 and attack_card.ability != "attackTwice":
            await self.log(channel, f"**{attacker['name']}** も昇天した！")

        await self.process_turn_end(channel)

    # ---------- ターン終了 ----------

    async def process_turn_end(self, channel):
        if channel.id not in self.games: return
        g = self.games[channel.id]

        alive = [i for i, p in g["players"].items() if p["hp"] > 0]
        if len(alive) <= 1:
            winner = g["players"][alive[0]]["name"] if alive else "なし"
            await channel.send(f"**勝者：{winner}！** ゲーム終了！")
            del self.games[channel.id]
            return

        # 次のプレイヤーへ
        g["current_index"] = (g["current_index"] + 1) % len(g["turn_order"])
        while g["players"][g["turn_order"][g["current_index"]]]["hp"] <= 0:
            g["current_index"] = (g["current_index"] + 1) % len(g["turn_order"])

        if g["current_index"] == 0:
            g["round"] += 1

        await asyncio.sleep(2)
        await self.send_turn_panel(channel)


# ================================================================
# setup
# ================================================================
# god_field.py への追記パッチ
# 以下のメソッドを GodField クラスの process_turn_end の直後、
# クラス末尾（async def setup(bot) の直前）に追加してください。

# ================================================================
# 追加メソッド: play.py ハブとの連携用
# ================================================================

    # --- play.py の GameSelectView から呼ばれるゲーム開始メソッド ---
    async def start_from_hub(self, channel, join_view):
        """
        play.py の GameSelectView で JoinView を表示した後に
        create_task で呼ばれる。60 秒待機してからゲームを開始する。
        """
        await asyncio.sleep(60)

        if len(join_view.joined_users) < 2:
            await channel.send("⚠️ 人数不足（最低2名）のため中止します。")
            return

        players     = {u.id: create_player(u) for u in join_view.joined_users}
        turn_order  = list(players.keys())
        random.shuffle(turn_order)

        self.games[channel.id] = {
            "players":               players,
            "turn_order":            turn_order,
            "current_index":         0,
            "round":                 1,
            "active_interaction_id": None,
            "cog":                   self,
            "temp_msgs":             [],
            "tiebreak":              False,
        }
        names = "、".join(p["name"] for p in players.values())
        await channel.send(f"🌟 **戦い開始！** 参戦者：{names}")
        await self.send_turn_panel(channel)


# ================================================================
# 挿入位置の目印（元ファイルのこの行の直前に上記メソッドを追加）
# ================================================================
# async def setup(bot):
#     await bot.add_cog(GodField(bot))
async def setup(bot):
    await bot.add_cog(GodField(bot))
    