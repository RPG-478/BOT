
const musicCommands = [
  {
    name: "/music play",
    text: "曲を検索して再生します。YouTube・SpotifyのURL、検索キーワード、音声ファイルを指定できます。Botは実行者がいるボイスチャンネルに参加します。開始位置の指定は、キューが空の状態で再生を始めるときだけ使えます。",
    example: "/music play query: 作曲者 曲名",
  },
  {
    name: "/music panel",
    text: "再生・一時停止・スキップなどをボタンで操作するパネルを開きます。音楽操作をまとめて行いたいときに便利です。",
    example: "/music panel",
  },
  {
    name: "/music control",
    text: "actionから一時停止/再開、スキップ、停止、シーク、キュー表示、ループ、シャッフルを選びます。シークにはseconds、ループにはloop_modeを指定します。",
    example: "/music control action: キュー表示",
  },
  {
    name: "/music sound",
    text: "actionから音量・再生速度・EQ・立体音響を設定します。音量は0.1〜2.0、再生速度は指定可能な範囲内でvalueを設定。EQはプリセット、立体音響は残響の長さ・量・解像度を選べます。",
    example: "/music sound action: 音量 value: 0.8",
  },
  {
    name: "/music library",
    text: "actionから検索、プレイリスト、音声ファイルID一覧を選びます。プレイリストは個人用またはサーバー共有で保存・一覧・再生でき、添付した音声/JSONを扱う操作もあります。検索にはquery、ファイル一覧にはlimitを指定します。",
    example: "/music library action: プレイリスト",
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
