diff --git a/README.md b/README.md
index 9da6caa99c55c3c153b05b8c0e625a8b546e922f..0eef5b64a48dfed4d6ac2638ad56714a49d9ab11 100644
--- a/README.md
+++ b/README.md
@@ -28,56 +28,67 @@ keirin-bot/
 │   ├── ai_engine.py     # AI予想エンジン v2.0
 │   ├── trader.py        # 資金管理（損切り・選手DB）
 │   ├── backtest.py      # バックテストエンジン
 │   └── bot.py           # メイン制御
 ├── data/
 │   └── data.json        # 収支・学習データ
 └── requirements.txt
 ```
 
 ## 🚀 クイックスタート
 
 ### 1. リポジトリをFork
 
 GitHubでこのリポジトリをForkしてください。
 
 ### 2. Secretsを設定
 
 リポジトリの Settings → Secrets and variables → Actions で以下を設定：
 
 | Secret | 説明 | 取得先 |
 |--------|------|--------|
 | `GEMINI_API_KEY` | Google Gemini API | [Google AI Studio](https://makersuite.google.com/app/apikey) |
 | `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot | [LINE Developers](https://developers.line.biz/) |
 | `LINE_USER_ID` | 通知先ユーザーID | LINE Developers Console |
 
-### 3. Actionsを有効化
+### 3. Deploy keys を追加（サーバーや自前のrunnerでGitHubへSSH接続する場合）
+
+1. デプロイ先サーバーでSSH鍵を作成（例）
+   ```bash
+   ssh-keygen -t ed25519 -C "keirin-bot-deploy" -f ~/.ssh/keirin_bot_deploy
+   ```
+2. `~/.ssh/keirin_bot_deploy.pub` の内容（公開鍵部分だけ）を GitHub → Settings → Deploy keys → **Add deploy key** にそのまま貼り付け、名前を付けて保存
+   - 読み取り専用で十分です（`Allow write access` は通常不要）
+   - 秘密鍵（`~/.ssh/keirin_bot_deploy`）はサーバー側に残し、GitHubには渡さないでください
+3. サーバー側で `~/.ssh/keirin_bot_deploy` を利用できるようにし、`git clone git@github.com:YOUR_USERNAME/keirin-bot.git` などのSSHアクセスで動作確認してください。
+
+### 4. Actionsを有効化
 
 1. リポジトリの **Actions** タブをクリック
 2. 「I understand my workflows...」をクリックして有効化
 
-### 4. 手動実行でテスト
+### 5. 手動実行でテスト
 
 1. **Actions** タブ → 左側の **🌅 Morning - Prediction** を選択
 2. 右側の **Run workflow** ボタンをクリック
 3. **demo_mode** にチェックを入れる
 4. **Run workflow** をクリック
 
 ## 📱 LINEコマンド
 
 Botに以下のメッセージを送信して操作：
 
 | コマンド | 機能 |
 |---------|------|
 | `今日の予想` | 本日の予想状況を確認 |
 | `収支確認` | 現在の収支レポート |
 | `本日停止` | 本日のベットを停止 |
 | `再開` | ベットを再開 |
 | `バックテスト` | 戦略検証を実行 |
 | `ヘルプ` | コマンド一覧 |
 
 ## 🧠 予想ロジック「鉄板の守」
 
 ### コンセプト
 > 「10回の的中より、1回のトリガミ・ハズレを憎む」
 
 ### 分析要素
