import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import BrowserLocalization from "./BrowserLocalization";
export const metadata: Metadata = {
  title: "AGOBOT サポート",
  description: "AGOBOTのコマンド一覧と使い方。分かりやすく、幅広く。",
  icons: { icon: "/img/nomal.png" },
};
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <BrowserLocalization />
        <header>
          <nav>
            <Link href="/" className="brand"><img src="/img/nomal.png" alt="" />AGOBOT サポート</Link>
            <Link href="/commands">コマンド一覧</Link>
          </nav>
        </header>
        <main>{children}</main>
        <footer>
          <div>AGOBOT サポート</div>
          <nav className="footer-links" aria-label="ポリシー">
            <Link href="/terms">利用規約</Link>
            <Link href="/privacy">プライバシーポリシー</Link>
          </nav>
        </footer>
      </body>
    </html>
  );
}
