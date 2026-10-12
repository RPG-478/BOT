import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "AGOBOT",
  description: "パーティーゲームとサポート機能の Discord Bot、AGOBOT の使い方",
  icons: { icon: "/img/nomal.png" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <header>
          <nav>
            <Link href="/" className="brand">
              <img src="/img/nomal.png" alt="" />
              AGOBOT
            </Link>
            <Link href="/">ホーム</Link>
            <Link href="/commands">コマンド</Link>
            <Link href="/games">ゲーム</Link>
            <Link href="/ranking">ランキング</Link>
            <Link href="/map">マップ</Link>
          </nav>
        </header>
        <main>{children}</main>
        <footer>AGOBOT</footer>
      </body>
    </html>
  );
}
