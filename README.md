# 🚴 競輪予想LINE Bot v2.0 - 鉄板の守

Google Gemini APIを活用した競輪予想を自動で行い、LINEで通知するBot。
仮想通貨（10,000円）を用いた収支シミュレーション機能付き。

## ✨ v2.0 新機能

| 機能 | 説明 |
|------|------|
| 🎯 マルチベット | 3連単、3連複、2車単、ワイドに対応 |
| ⚠️ 損切りルール | 3連敗または日次損失3000円で自動停止 |
| 👤 選手DB | 選手別成績を蓄積・分析 |
| 🌤️ 天候分析 | 風向き・風速を考慮した予想 |
| 📊 期待値計算 | オッズと自信度から期待値を算出 |
| 🔬 バックテスト | 過去データで戦略を検証 |
| 📱 LINEコマンド | リッチメニュー対応 |

## 📁 プロジェクト構成

```
keirin-bot/
├── .github/workflows/
│   ├── morning.yml      # 朝9時: 予想配信
│   ├── night.yml        # 夜21時: 結果報告
│   └── backtest.yml     # バックテスト（手動）
├── src/
│   ├── scraper.py       # スクレイパー（オッズ・天候対応）
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

### 3. Actionsを有効化

1. リポジトリの **Actions** タブをクリック
2. 「I understand my workflows...」をクリックして有効化

### 4. 手動実行でテスト

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

| 要素 | 内容 |
|------|------|
| バンク特性 | 33バンク→先行有利、500バンク→追込有利 |
| 天候・風 | 向かい風→追込有利、追い風→先行有利 |
| ライン結束 | コメントからセンチメント分析 |
| 期待値 | オッズ × 的中確率 > 1.0 を優先 |
| 悪魔の証明 | 本命が飛ぶシナリオ3つを検証 |

### リスク判定
- リスク確率 10% 以上 → **見送り（KEN）**

## ⚠️ 損切りルール

自動的にベットを停止する条件：

| 条件 | 閾値 |
|------|------|
| 連敗 | 3連敗 |
| 日次損失 | 3,000円 |
| 資金不足 | 100円未満 |

手動で `本日停止` / `再開` も可能。

## 💰 資金管理

### ケリー基準（簡易版）

```
ベット額 = 現在資金 × 自信度 × 0.1
```

### 賭け式別配分

| 賭け式 | 配分比率 |
|--------|----------|
| 3連単 | 60% |
| 3連複 | 20% |
| 2車単 | 15% |
| ワイド | 5% |

## 🔬 バックテスト

過去データで戦略を検証：

```bash
# ローカル実行
cd src
python bot.py backtest --races 100

# GitHub Actions
Actions → 🔬 Backtest → Run workflow
```

### 出力例
```
📊 【バックテスト結果レポート】

💰 資金推移
   初期資金: ¥10,000
   最終資金: ¥12,400
   ROI: 24.0%

📈 パフォーマンス
   勝率: 35.0%
   最大連敗: 4回
```

## 💻 ローカル開発

```bash
# クローン
git clone https://github.com/YOUR_USERNAME/keirin-bot.git
cd keirin-bot

# 依存関係インストール
pip install -r requirements.txt

# 環境変数設定
cp .env.example .env
# .env を編集してAPIキーを設定

# デモ実行
cd src
python bot.py demo

# 各ジョブ単体実行
python bot.py morning --demo
python bot.py night --demo
python bot.py report
python bot.py backtest --races 50
```

## 📊 データ構造

`data/data.json` の主要フィールド：

```json
{
  "bankroll": {
    "current_amount": 10000,
    "initial_amount": 10000
  },
  "statistics": {
    "total_bets": 0,
    "wins": 0,
    "losses": 0,
    "roi_percentage": 0.0,
    "current_losing_streak": 0
  },
  "risk_control": {
    "max_losing_streak_limit": 3,
    "daily_loss_limit": 3000,
    "is_stopped_today": false
  },
  "racer_database": {},
  "pattern_analysis": {},
  "bet_history": [],
  "learning_logs": []
}
```

## 🔧 トラブルシューティング

### GitHub Actionsが動かない

1. **Actionsが有効か確認**
   - Settings → Actions → General
   - 「Allow all actions」を選択

2. **Secretsが設定されているか確認**
   - Settings → Secrets and variables → Actions
   - 必要なSecretsがすべて登録されているか

3. **手動実行でテスト**
   - Actions → ワークフロー選択 → Run workflow
   - demo_modeをONにして実行

### LINE通知が届かない

1. LINE_CHANNEL_ACCESS_TOKEN が正しいか確認
2. LINE_USER_ID が正しいか確認（Uから始まる33文字）
3. LINE公式アカウントがブロックされていないか確認

## ⚠️ 免責事項

- このBotは**シミュレーション目的**です
- 実際の金銭を賭けることは推奨しません
- 競輪は公営ギャンブルであり、法律を遵守してください
- スクレイピングは対象サイトの利用規約に従ってください

## 📝 ライセンス

MIT License

## 🤝 コントリビューション

Issue・Pull Request歓迎！

---

**開発**: Claude (Anthropic AI)  
**バージョン**: 2.0.0
