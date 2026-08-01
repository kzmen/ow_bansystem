# Renderで公開する手順

## 1. GitHubへアップロード

1. GitHubにログインし、右上の「+」→「New repository」を開く。
2. Repository nameを `ow-ban-room` にする。
3. PublicまたはPrivateを選び、「Create repository」を押す。
4. 作成したリポジトリで「uploading an existing file」を押す。
5. このフォルダの中身をすべてアップロードする。
   - `app.py` や `render.yaml` がリポジトリの一番上に見える状態にする。
   - `ow-ban-render-ready` フォルダごと入れない。
6. 「Commit changes」を押す。

## 2. Renderへ公開

1. RenderにGitHubでログインする。
2. Dashboardで「New」→「Blueprint」を選ぶ。
3. 先ほど作った `ow-ban-room` リポジトリを接続する。
4. `render.yaml` が読み込まれたことを確認し、「Deploy Blueprint」を押す。
5. BuildとDeployが完了するまで、画面のログを確認する。
6. 表示された `https://〇〇.onrender.com` を開く。

## 3. みんなに使ってもらう

1. 公開URLをDiscordに貼る。
2. 主催者がルームを作成する。
3. 表示されたルームURLまたはルームコードを参加者へ送る。
4. 参加者はブラウザだけで利用できる。

## 無料版の注意

- 15分間アクセスがない場合、サービスが休止する。
- 休止後の最初のアクセスは起動に少し時間がかかる。
- 無料版ではSQLiteのルーム情報が休止・再起動・再デプロイ時に消える。
- 試合中にアクセスやWebSocket通信が続いている間は利用できる。
- 公開URL自体は変わらない。
