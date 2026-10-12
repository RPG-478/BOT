import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "AGOBOT",
  description: "パーティーゲームとサポート機能の Discord Bot、AGOBOT の使い方",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <header>
          <nav>
            <Link href="/" className="brand">AGOBOT</Link>
            <Link href="/commands">コマンド</Link>
            <Link href="/games">ゲームのルール</Link>
            <Link href="/ranking">ランキング</Link>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
