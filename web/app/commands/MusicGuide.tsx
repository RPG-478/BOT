
const musicCommands = [
  {
    name: "/music",
    text: "actionから再生、操作パネル、一時停止、スキップ、キュー、ループ、音響設定、検索、プレイリストなどを選びます。URL・検索語・音声ファイルもこのコマンドだけで指定できます。",
    example: "/music action: 再生 query: 作曲者 曲名",
  },
];

export default function MusicGuide() {
  return (
    <section className="guide-section" id="music-guide">
      <h2>音楽を聴く：<code>/music</code></h2>
      <p className="muted">先にボイスチャンネルへ参加してから使います。再生系の操作でBotがVCに参加します。必要な操作を選び、表示される項目を入力してください。</p>
      <div className="guide-list">
        {musicCommands.map((command) => (
          <article className="card" key={command.name}>
            <strong><code>{command.name}</code></strong>
            <p>{command.text}</p>
            <div className="muted">入力例：<code>{command.example}</code></div>
          </article>
        ))}
      </div>
      <p className="muted">曲の取得元や利用可否はリンク先・サービスの仕様により異なります。実際の操作候補はDiscordのコマンド入力欄で確認できます。</p>
    </section>
  );
}
