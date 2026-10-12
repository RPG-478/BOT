export default function SampleNotice({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <div className="card notice">
      いま表示しているのはサンプルのデータです。Bot 側でコマンド一覧を書き出すと、実際のコマンドに置き換わります。
    </div>
  );
}
