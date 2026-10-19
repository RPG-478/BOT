
const musicCommands = [
  {
    name: "/music",
    text: "コマンドを送信すると音楽操作パネルが表示されます。パネルから再生、検索、一時停止、スキップ、キュー、ループ、音響設定、プレイリストなどを操作できます。",
    example: "/music",
  },
];

export default function MusicGuide() {
  return (
    <section className="guide-section" id="music-guide">
      <h2>音楽を聴く：<code>/music</code></h2>
      <p className="muted">ボイスチャンネルで <code>/music</code> を送信し、表示されたパネルから操作します。再生操作ではBotがVCに参加します。</p>
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
