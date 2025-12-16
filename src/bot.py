"""
競輪予想LINE Bot v2.0 - メインモジュール
- LINEリッチメニュー対応
- マルチベット対応
- 損切りルール統合
- バックテスト機能
"""
import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
    FlexMessage,
    FlexContainer,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

sys.path.insert(0, str(Path(__file__).parent))
from scraper import KeirinScraper, RaceInfo, create_demo_race_info, create_demo_result
from ai_engine import TeppanNoMamoruEngine, PredictionResult, prediction_to_dict
from trader import BankrollManager, BetRecord
from backtest import BacktestEngine, create_sample_historical_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


class KeirinBot:
    """競輪予想LINE Bot v2.0"""
    
    # リッチメニューコマンド
    COMMANDS = {
        "今日の予想": "prediction",
        "収支確認": "report", 
        "本日停止": "stop",
        "再開": "resume",
        "バックテスト": "backtest",
        "ヘルプ": "help"
    }
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # LINE API
        self.line_channel_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
        self.line_user_id = os.getenv("LINE_USER_ID")
        self.line_channel_secret = os.getenv("LINE_CHANNEL_SECRET")
        
        # モジュール初期化
        self.scraper = KeirinScraper()
        self.trader = BankrollManager(str(self.data_dir / "data.json"))
        self.backtest_engine = BacktestEngine(str(self.data_dir / "data.json"))
        
        # AI Engine
        self.ai_engine = None
        if os.getenv("GEMINI_API_KEY"):
            try:
                self.ai_engine = TeppanNoMamoruEngine()
            except Exception as e:
                logger.warning(f"AI Engine init failed: {e}")
        
        # Webhook Handler
        if self.line_channel_secret:
            self.handler = WebhookHandler(self.line_channel_secret)
            self._setup_handlers()
        else:
            self.handler = None
    
    def _setup_handlers(self):
        """Webhookハンドラーをセットアップ"""
        @self.handler.add(MessageEvent, message=TextMessageContent)
        def handle_message(event):
            text = event.message.text.strip()
            
            # コマンド判定
            command = self.COMMANDS.get(text)
            
            if command == "prediction":
                response = self._get_today_prediction_summary()
            elif command == "report":
                response = self.trader.generate_report()
            elif command == "stop":
                response = self._stop_today()
            elif command == "resume":
                response = self._resume_betting()
            elif command == "backtest":
                response = self._run_quick_backtest()
            elif command == "help":
                response = self._get_help_message()
            else:
                response = self._handle_free_text(text)
            
            self._reply_message(event.reply_token, response)
    
    def _reply_message(self, reply_token: str, message: str):
        """メッセージを返信"""
        if not self.line_channel_token:
            print(f"[Reply] {message}")
            return
        
        try:
            config = Configuration(access_token=self.line_channel_token)
            with ApiClient(config) as api_client:
                api = MessagingApi(api_client)
                api.reply_message(
                    ReplyMessageRequest(
                        reply_token=reply_token,
                        messages=[TextMessage(text=message[:5000])]
                    )
                )
        except Exception as e:
            logger.error(f"Reply failed: {e}")
    
    def _send_line_message(self, message: str) -> bool:
        """LINEメッセージをプッシュ送信"""
        if not self.line_channel_token or not self.line_user_id:
            logger.warning("LINE credentials not configured")
            print("\n" + "=" * 50)
            print("[LINE Message Preview]")
            print("=" * 50)
            print(message)
            print("=" * 50 + "\n")
            return False
        
        try:
            config = Configuration(access_token=self.line_channel_token)
            with ApiClient(config) as api_client:
                api = MessagingApi(api_client)
                api.push_message(
                    PushMessageRequest(
                        to=self.line_user_id,
                        messages=[TextMessage(text=message[:5000])]
                    )
                )
            logger.info("LINE message sent")
            return True
        except Exception as e:
            logger.error(f"Push message failed: {e}")
            return False
    
    def _get_today_prediction_summary(self) -> str:
        """今日の予想サマリーを取得"""
        today_bets = self.trader.get_today_bets() if hasattr(self.trader, 'get_today_bets') else []
        
        if not today_bets:
            return "📊 本日の予想はまだありません。\n朝のジョブ実行をお待ちください。"
        
        go_bets = [b for b in today_bets if b.decision == "GO"]
        ken_count = len([b for b in today_bets if b.decision == "KEN"])
        
        lines = ["🚴 【本日の予想サマリー】\n"]
        
        for bet in go_bets:
            status = "⏳ 未確定" if not bet.result_checked else ("✅ 的中" if bet.is_won else "❌ 不的中")
            lines.append(f"📍 {bet.race_id}")
            lines.append(f"   {status}")
            lines.append(f"   投資: ¥{bet.total_amount:,}")
            if bet.result_checked and bet.actual_return:
                lines.append(f"   払戻: ¥{bet.actual_return:,}")
            lines.append("")
        
        if ken_count > 0:
            lines.append(f"⏸️ 見送り: {ken_count}レース")
        
        return "\n".join(lines)
    
    def _stop_today(self) -> str:
        """本日のベットを停止"""
        self.trader.data["risk_control"]["is_stopped_today"] = True
        self.trader.data["risk_control"]["stop_reason"] = "手動停止"
        self.trader._save_data()
        return "🔴 本日のベットを停止しました。\n「再開」で再開できます。"
    
    def _resume_betting(self) -> str:
        """ベットを再開"""
        self.trader.data["risk_control"]["is_stopped_today"] = False
        self.trader.data["risk_control"]["stop_reason"] = None
        self.trader._save_data()
        return "🟢 ベットを再開しました。"
    
    def _run_quick_backtest(self) -> str:
        """クイックバックテスト実行"""
        try:
            races = create_sample_historical_data()[:20]
            result = self.backtest_engine.run_backtest(
                races, 
                strategy_name="quick_test",
                initial_bankroll=10000
            )
            return self.backtest_engine.generate_report(result)
        except Exception as e:
            return f"バックテストエラー: {e}"
    
    def _get_help_message(self) -> str:
        """ヘルプメッセージ"""
        return """
🤖 【競輪予想Bot ヘルプ】

📝 コマンド一覧:
・今日の予想 - 本日の予想状況
・収支確認 - 現在の収支レポート
・本日停止 - 本日のベットを停止
・再開 - ベットを再開
・バックテスト - 戦略検証を実行
・ヘルプ - このメッセージ

⚙️ 自動機能:
・毎朝9時: 予想配信
・毎晩21時: 結果報告

⚠️ 損切りルール:
・3連敗で自動停止
・日次損失3000円で停止
"""
    
    def _handle_free_text(self, text: str) -> str:
        """フリーテキスト処理"""
        if "予想" in text:
            return self._get_today_prediction_summary()
        elif "収支" in text or "残高" in text:
            return self.trader.generate_report()
        elif "停止" in text:
            return self._stop_today()
        else:
            return "コマンドが認識できませんでした。「ヘルプ」と送信してください。"
    
    def _format_prediction_message(self, race: RaceInfo,
                                   prediction: PredictionResult,
                                   bet_record: BetRecord) -> str:
        """予想メッセージをフォーマット"""
        decision_emoji = "🔥" if prediction.decision == "GO" else "⏸️"
        
        lines = [
            f"🚴 【鉄板の守 本日の予想】",
            f"",
            f"📍 {race.velodrome} {race.race_number}R",
            f"🏟️ {race.bank_type}バンク / {race.race_grade}",
            f"🌤️ {race.weather.weather} / 風:{race.weather.wind_direction}{race.weather.wind_speed}m/s",
            f"",
            f"{decision_emoji} 判定: {prediction.decision}",
            f"📊 自信度: {prediction.confidence_score:.0%}",
        ]
        
        if prediction.decision == "GO" and prediction.primary_bet:
            lines.extend([
                f"",
                f"🎯 メイン推奨（{prediction.primary_bet.bet_type}）",
            ])
            for combo in prediction.primary_bet.combinations:
                odds = prediction.primary_bet.odds.get(combo, "?")
                lines.append(f"   {combo} ({odds}倍)")
            
            # サブ推奨
            for rec in prediction.bet_recommendations:
                if rec.bet_type != prediction.primary_bet.bet_type:
                    lines.append(f"")
                    lines.append(f"📌 サブ推奨（{rec.bet_type}）")
                    for combo in rec.combinations[:2]:
                        odds = rec.odds.get(combo, "?")
                        lines.append(f"   {combo} ({odds}倍)")
            
            lines.extend([
                f"",
                f"💰 総投資額: ¥{bet_record.total_amount:,}",
            ])
        
        lines.extend([
            f"",
            f"📝 分析:",
            f"{prediction.reasoning[:200]}",
        ])
        
        if prediction.weather_analysis:
            lines.extend([
                f"",
                f"🌤️ 天候分析:",
                f"{prediction.weather_analysis}",
            ])
        
        lines.extend([
            f"",
            f"⚠️ リスク: {prediction.devils_proof.risk_probability:.0%}",
        ])
        for scenario in prediction.devils_proof.scenarios[:2]:
            lines.append(f"・{scenario[:50]}")
        
        lines.extend([
            f"",
            f"💬 {prediction.comment}",
        ])
        
        # 損切り状況
        can_bet, reason = self.trader.can_bet()
        if not can_bet:
            lines.extend([
                f"",
                f"⚠️ 注意: {reason}",
            ])
        
        return "\n".join(lines)
    
    def _format_result_message(self, bet_record: BetRecord,
                               actual_result: Dict,
                               reflection: str) -> str:
        """結果メッセージをフォーマット"""
        result_emoji = "🎉" if bet_record.is_won else "😢"
        
        lines = [
            f"🌙 【本日の結果報告】",
            f"",
            f"📍 {bet_record.race_id}",
            f"",
            f"{result_emoji} 結果: {'的中！' if bet_record.is_won else '不的中...'}",
        ]
        
        if actual_result:
            finish = actual_result.get("finish_order", [])
            if len(finish) >= 3:
                lines.append(f"🏁 着順: {finish[0]}-{finish[1]}-{finish[2]}")
            
            pattern = actual_result.get("winning_pattern", "")
            if pattern:
                lines.append(f"💨 決まり手: {pattern}")
        
        if bet_record.is_won:
            profit = bet_record.actual_return - bet_record.total_amount
            lines.extend([
                f"",
                f"💰 投資: ¥{bet_record.total_amount:,}",
                f"💵 払戻: ¥{bet_record.actual_return:,}",
                f"📈 収支: +¥{profit:,}",
            ])
        else:
            lines.extend([
                f"",
                f"💸 損失: -¥{bet_record.total_amount:,}",
            ])
            
            # 連敗警告
            streak = self.trader.data["statistics"]["current_losing_streak"]
            if streak >= 2:
                lines.append(f"⚠️ {streak}連敗中")
        
        lines.extend([
            f"",
            f"📖 【反省会】",
            f"{reflection[:300]}",
        ])
        
        # 現在の状況
        bankroll = self.trader.current_bankroll
        initial = self.trader.data["bankroll"]["initial_amount"]
        profit = bankroll - initial
        lines.extend([
            f"",
            f"📊 現在: ¥{bankroll:,} ({'+' if profit >= 0 else ''}{profit:,})",
        ])
        
        return "\n".join(lines)
    
   def run_morning_job(self, target_velodrome: str = None, demo_mode: bool = False):
    ...
    # デモモードならリセット
    if demo_mode:
        self.trader.data["risk_control"]["is_stopped_today"] = False
        self.trader.data["statistics"]["current_losing_streak"] = 0
        self.trader.data["statistics"]["daily_loss"] = 0
    
    # ベット可能チェック
    can_bet, reason = self.trader.can_bet()
            self._send_line_message(msg)
            return
        
        # 学習データ取得
        learning_data = self.trader.get_learning_data()
        
        if demo_mode:
            logger.info("Running in demo mode")
            races = [create_demo_race_info()]
        else:
            today = datetime.now()
            schedule = self.scraper.get_race_schedule(today)
            
            if target_velodrome:
                schedule = [r for r in schedule if target_velodrome in r.get("velodrome", "")]
            
            if not schedule:
                logger.info("No races found")
                self._send_line_message("🚴 本日の対象レースはありません。")
                return
            
            races = []
            for race_info in schedule[:5]:
                detail = self.scraper.get_race_detail(race_info["url"])
                if detail:
                    races.append(detail)
        
        go_predictions = []
        
        for race in races:
            logger.info(f"Processing: {race.velodrome} {race.race_number}R")
            
            # 再度ベット可能チェック（連敗などで変わる可能性）
            can_bet, reason = self.trader.can_bet()
            if not can_bet:
                logger.warning(f"Betting stopped: {reason}")
                break
            
            # AI予想
            if self.ai_engine:
                prediction = self.ai_engine.predict(race, learning_data)
            else:
                from ai_engine import DevilsProof, BetRecommendation
                prediction = PredictionResult(
                    race_id=race.race_id,
                    reasoning="デモモード",
                    devils_proof=DevilsProof(["デモ"], 0.05),
                    decision="GO",
                    confidence_score=0.80,
                    bet_recommendations=[
                        BetRecommendation("sanrentan", ["1-2-4"], 1.2, {"1-2-4": 8.5})
                    ],
                    primary_bet=BetRecommendation("sanrentan", ["1-2-4"], 1.2, {"1-2-4": 8.5}),
                    comment="デモ予想",
                    weather_analysis="デモ"
                )
            
            # マルチベット記録
            bet_recs = [
                {
                    "bet_type": rec.bet_type,
                    "combinations": rec.combinations,
                    "odds": rec.odds,
                    "expected_value": rec.expected_value
                }
                for rec in prediction.bet_recommendations
            ]
            
            bet_record = self.trader.place_multi_bet(
                race_id=race.race_id,
                decision=prediction.decision,
                confidence_score=prediction.confidence_score,
                bet_recommendations=bet_recs
            )
            
            if prediction.decision == "GO":
                go_predictions.append((race, prediction, bet_record))
        
        # LINE配信
        if go_predictions:
            for race, prediction, bet_record in go_predictions:
                message = self._format_prediction_message(race, prediction, bet_record)
                self._send_line_message(message)
        else:
            self._send_line_message(
                "🚴 【本日の予想】\n\n"
                "鉄板の守の判定: 全レース見送り（KEN）\n"
                "リスクが高いと判断しました。"
            )
        
        logger.info(f"Morning job completed. GO: {len(go_predictions)}")
    
    def run_night_job(self, demo_mode: bool = False):
        """夜のジョブ: 結果報告・反省会"""
        logger.info("=" * 50)
        logger.info("Starting night job v2.0")
        logger.info("=" * 50)
        
        unsettled_bets = self.trader.get_unsettled_bets()
        
        if not unsettled_bets:
            logger.info("No unsettled bets")
            report = self.trader.generate_report()
            self._send_line_message(f"🌙 【本日の収支報告】\n\n{report}")
            return
        
        for bet in unsettled_bets:
            logger.info(f"Checking: {bet.race_id}")
            
            if demo_mode:
                actual_result = create_demo_result()
                # デモでは的中率50%
                import random
                if random.random() > 0.5:
                    actual_result["finish_order"] = [3, 5, 7, 1, 2, 4, 6, 8, 9]
            else:
                # 実際の結果取得（race_urlから）
                actual_result = None
                # TODO: bet.race_idからURLを復元して取得
            
            if not actual_result:
                logger.warning(f"Result not found: {bet.race_id}")
                continue
            
            # 精算
            settled = self.trader.settle_bet(bet.bet_id, actual_result)
            
            if not settled:
                continue
            
            # パターン分析更新
            # bank_typeを取得（race_idから抽出）
            bank_type = "400"  # デフォルト
            if "前橋" in bet.race_id or "小倉" in bet.race_id:
                bank_type = "33"
            elif "京王閣" in bet.race_id or "宇都宮" in bet.race_id:
                bank_type = "500"
            
            self.trader.update_pattern_analysis(
                bank_type=bank_type,
                is_won=settled.is_won,
                kimarite=actual_result.get("winning_pattern", "")
            )
            
            # 反省コメント
            if self.ai_engine and not settled.is_won:
                # TODO: race_infoを復元してAI反省会
                reflection = "AI反省会は実装中です。"
            else:
                if settled.is_won:
                    reflection = f"的中！{actual_result.get('winning_pattern', '')}で予想通りの展開。"
                else:
                    reflection = f"不的中。決まり手は{actual_result.get('winning_pattern', '')}。次回に活かす。"
            
            # 学習ログ
            self.trader.add_learning_log(
                race_id=bet.race_id,
                prediction_summary=f"投資:¥{bet.total_amount:,}",
                result_summary=str(actual_result.get("finish_order", [])[:3]),
                reflection=reflection
            )
            
            # 結果配信
            message = self._format_result_message(settled, actual_result, reflection)
            self._send_line_message(message)
        
        # 日次レポート
        report = self.trader.generate_report()
        self._send_line_message(report)
        
        logger.info("Night job completed")
    
    def run_backtest(self, num_races: int = 50):
        """バックテスト実行"""
        logger.info(f"Running backtest with {num_races} races")
        
        races = create_sample_historical_data()[:num_races]
        result = self.backtest_engine.run_backtest(
            races,
            strategy_name="teppan_no_mamoru",
            initial_bankroll=10000
        )
        
        report = self.backtest_engine.generate_report(result)
        print(report)
        return result
    
    def run_full_demo(self):
        """フルデモ実行"""
        logger.info("Running full demo...")
        
        print("\n" + "=" * 60)
        print("🚴 競輪予想Bot v2.0 - フルデモ")
        print("=" * 60)
        
        print("\n📌 朝のジョブ実行中...")
        self.run_morning_job(demo_mode=True)
        
        print("\n📌 夜のジョブ実行中...")
        self.run_night_job(demo_mode=True)
        
        print("\n📌 バックテスト実行中...")
        self.run_backtest(num_races=20)
        
        print("\n" + "=" * 60)
        print("デモ完了！")
        print("=" * 60)


def main():
    """メインエントリーポイント"""
    import argparse
    
    parser = argparse.ArgumentParser(description="競輪予想LINE Bot v2.0")
    parser.add_argument(
        "job",
        choices=["morning", "night", "demo", "report", "backtest", "reset"],
        help="実行するジョブ"
    )
    parser.add_argument("--velodrome", help="対象競輪場")
    parser.add_argument("--demo", action="store_true", help="デモモード")
    parser.add_argument("--races", type=int, default=50, help="バックテストのレース数")
    
    args = parser.parse_args()
    
    script_dir = Path(__file__).parent.parent
    data_dir = script_dir / "data"
    
    bot = KeirinBot(data_dir=str(data_dir))
    
    if args.job == "morning":
        bot.run_morning_job(target_velodrome=args.velodrome, demo_mode=args.demo)
    elif args.job == "night":
        bot.run_night_job(demo_mode=args.demo)
    elif args.job == "demo":
        bot.run_full_demo()
    elif args.job == "report":
        print(bot.trader.generate_report())
    elif args.job == "backtest":
        bot.run_backtest(num_races=args.races)
    elif args.job == "reset":
        bot.trader.reset()
        print("データをリセットしました。")


if __name__ == "__main__":
    main()
