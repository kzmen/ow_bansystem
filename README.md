# OW BAN ROOM — Python版

OWの身内カスタムや対戦会向けに、10人がブラウザから投票してBANヒーローを決めるWebアプリです。
OW本体とは連携せず、Web上で決まったBANを参加者同士のルールとして使用します。

## 入っている機能

- 主催者が6桁のルームコードを作成
- 招待URLまたはコードから参加
- TEAM A / TEAM Bに各5人まで参加
- 各プレイヤーが3体を選択
  - 第1候補: 7点
  - 第2候補: 5点
  - 第3候補: 3点
- 投票完了までは他の人の選択を非表示
- 通常4BANの自動計算
- 両チームで同じヒーローを選んだ場合の重複回避・次点繰り上げ
- 通常BANは同じロールから最大2体
- 同点時は投票した人数を優先し、さらに同点ならラウンド単位のランダム判定
- オプションの5体目「ロビーBAN」
  - 通常4BANに含まれていない
  - TEAM AとTEAM Bの両方から1票以上
  - 両チーム合計10点以上
  - ロール上限を無視
- 10人全員の投票完了で自動公開する設定
- 主催者による手動公開、参加者退出、次ラウンドへのリセット
- SQLite保存とSocket.IOによるリアルタイム更新

## Windowsでの起動（おすすめ）

1. ZIPを右クリックして「すべて展開」します。
2. 展開後のフォルダにある `START_HERE.bat` をダブルクリックします。
3. ブラウザが自動で開きます。
4. 手動で開く場合は `http://127.0.0.1:5000` を入力します。

この起動方法はPython標準機能だけを使うため、Flaskやpipのインストールは不要です。
黒い画面はサーバー本体なので、使用中は閉じないでください。

### URLが開かない場合

- ZIPの中から直接BATを押さず、必ず「すべて展開」してから実行してください。
- 黒い画面に `OW BAN ROOM を起動しました` と表示されていることを確認してください。
- URLは `http://127.0.0.1:5000` を使ってください。`https`ではありません。
- エラーが出た場合は、黒い画面が止まるため、その画面を撮影できます。

## コマンドから起動

```bash
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

macOS / Linux:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

## 同じWi-Fiのスマホ・別PCから参加

サーバーを起動したPCのローカルIPを調べ、参加者に以下の形式で共有します。

```text
http://192.168.x.x:5000
```

Windowsではコマンドプロンプトで `ipconfig` を実行し、「IPv4 アドレス」を確認できます。
初回アクセス時にWindowsファイアウォールが表示された場合は、信頼できるプライベートネットワークだけ許可してください。

## インターネットへ公開する場合

このMVPは自宅・身内用を想定しています。インターネット公開時は次を追加してください。

- HTTPS
- Redisなどを使ったSocket.IOの複数プロセス対応
- データベースの定期バックアップ
- レート制限
- 管理者認証の強化
- 利用規約・プライバシー表示

Render、Railway、Fly.ioなどへ配置できますが、SQLiteは複数サーバー構成に向かないため、本公開ではPostgreSQLへの変更を推奨します。

## データ保存

初回起動時に `ow_ban.db` が作成されます。
サーバーを再起動してもルームと投票は残ります。すべて消す場合は、サーバー停止後に `ow_ban.db` を削除してください。

## テスト

外部ライブラリを入れなくてもBAN計算テストだけ実行できます。

```bash
python -m unittest discover -s tests -v
```

## 主なファイル

```text
app.py                 Flask・Socket.IO・API
ban_logic.py           BAN集計と決定ルール
db.py                  SQLite処理
templates/             HTML画面
static/                CSS・JavaScript
tests/test_ban_logic.py 計算テスト
```

## ルール変更

5体目BANは `ban_logic.py` の `calculate_bans()` 内で独立しています。
条件や点数を変える場合は、主に以下を修正します。

```python
POINTS_BY_RANK = (7, 5, 3)
```

```python
lobby_ban_threshold=10
```

ヒーロー追加・ロール変更は `HEROES_BY_ROLE` を編集してください。

## 現在のヒーロー一覧

2026年8月2日時点の公式ヒーローページをもとに、Shionまで収録しています。ゲーム側の追加・ロール変更があった場合は `ban_logic.py` を更新してください。
