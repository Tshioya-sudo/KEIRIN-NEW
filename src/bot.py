 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/src/bot.py b/src/bot.py
index a337f2d6a4df2f5c9216b3d7a6c62044d69649cd..4bf56ee2f493f4835a0638a983eb2e4f8017599f 100644
--- a/src/bot.py
+++ b/src/bot.py
@@ -1,125 +1,140 @@
 """
 競輪予想LINE Bot v2.1 - メインモジュール
 - スクレイピング失敗時はデモデータにフォールバック
 """
 import os
 import sys
 import json
 import logging
 from datetime import datetime
 from pathlib import Path
 from typing import Optional, List, Dict
 
+from dotenv import load_dotenv
 from linebot.v3.messaging import (
     Configuration,
     ApiClient,
     MessagingApi,
     PushMessageRequest,
     TextMessage,
 )
 
 sys.path.insert(0, str(Path(__file__).parent))
 from scraper import KeirinScraper, RaceInfo, create_demo_race_info, create_demo_result
 from ai_engine import TeppanNoMamoruEngine, PredictionResult, BetRecommendation, DevilsProof
 from trader import BankrollManager, BetRecord
 from backtest import BacktestEngine, create_sample_historical_data
 
 logging.basicConfig(
     level=logging.INFO,
     format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
 )
 logger = logging.getLogger(__name__)
 
 
+load_dotenv()
+
+
 class KeirinBot:
     """競輪予想LINE Bot v2.1"""
     
     def __init__(self, data_dir: str = "data"):
         self.data_dir = Path(data_dir)
         self.data_dir.mkdir(parents=True, exist_ok=True)
         
         self.line_channel_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
         self.line_user_id = os.getenv("LINE_USER_ID")
         
-        self.scraper = KeirinScraper()
+        use_system_proxy = os.getenv("USE_SYSTEM_PROXY", "").lower() in ("1", "true", "yes")
+        if use_system_proxy:
+            logger.info("KeirinScraper: using system proxy settings (USE_SYSTEM_PROXY enabled)")
+        self.scraper = KeirinScraper(use_system_proxy=use_system_proxy)
         self.trader = BankrollManager(str(self.data_dir / "data.json"))
         self.backtest_engine = BacktestEngine(str(self.data_dir / "data.json"))
         
         self.ai_engine = None
         if os.getenv("GEMINI_API_KEY"):
             try:
                 self.ai_engine = TeppanNoMamoruEngine()
                 logger.info("AI Engine initialized with Gemini API")
             except Exception as e:
                 logger.warning(f"AI Engine init failed: {e}")
     
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
     
     def _format_prediction_message(self, race: RaceInfo,
                                    prediction: PredictionResult,
                                    bet_record: BetRecord,
-                                   is_demo: bool = False) -> str:
+                                   is_demo: bool = False,
+                                   notice: str = "") -> str:
         """予想メッセージをフォーマット"""
         decision_emoji = "🔥" if prediction.decision == "GO" else "⏸️"
         demo_tag = "【デモ】" if is_demo else ""
-        
+
         lines = [
             f"🚴 {demo_tag}【鉄板の守 本日の予想】",
             f"",
+        ]
+
+        if notice:
+            lines.append(notice)
+            lines.append("")
+
+        lines.extend([
             f"📍 {race.velodrome} {race.race_number}R",
             f"🏟️ {race.bank_type}バンク / {race.race_grade}",
             f"🌤️ {race.weather.weather} / 風:{race.weather.wind_direction}{race.weather.wind_speed}m/s",
             f"",
             f"{decision_emoji} 判定: {prediction.decision}",
             f"📊 自信度: {prediction.confidence_score:.0%}",
-        ]
+        ])
         
         if prediction.decision == "GO" and prediction.primary_bet:
             lines.extend([
                 f"",
                 f"🎯 メイン推奨（{prediction.primary_bet.bet_type}）",
             ])
             for combo in prediction.primary_bet.combinations:
                 odds = prediction.primary_bet.odds.get(combo, "?")
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
@@ -262,85 +277,90 @@ class KeirinBot:
         logger.info("=" * 50)
         logger.info("Starting morning job v2.1")
         logger.info("=" * 50)
         
         # デモモードならリセット
         if demo_mode:
             logger.info("Demo mode: resetting risk controls")
             self.trader.data["risk_control"]["is_stopped_today"] = False
             self.trader.data["risk_control"]["stop_reason"] = None
             self.trader.data["statistics"]["current_losing_streak"] = 0
             self.trader.data["statistics"]["daily_loss"] = 0
             self.trader._save_data()
         
         # ベット可能チェック
         can_bet, reason = self.trader.can_bet()
         if not can_bet:
             msg = f"🚴 【本日の予想】\n\n⚠️ {reason}\n\n本日のベットは停止中です。"
             self._send_line_message(msg)
             return
         
         # 学習データ取得
         learning_data = self.trader.get_learning_data()
         
         # レースデータ取得
         use_demo_data = False
+        fallback_notice = ""
         
         if demo_mode:
             logger.info("Demo mode: using demo race data")
             races = self._create_demo_races()
             use_demo_data = True
         else:
             # 本番モード: スクレイピング試行
             logger.info("Production mode: trying to scrape real data")
             today = datetime.now()
             
             try:
                 schedule = self.scraper.get_race_schedule(today)
                 logger.info(f"Found {len(schedule)} velodromes in schedule")
                 
                 if target_velodrome:
                     schedule = [r for r in schedule if target_velodrome in r.get("velodrome", "")]
                 
                 races = []
                 for race_info in schedule[:5]:
                     logger.info(f"Getting details for: {race_info.get('velodrome', 'unknown')}")
                     detail = self.scraper.get_race_detail(race_info["url"])
                     if detail:
                         races.append(detail)
                 
                 logger.info(f"Successfully got details for {len(races)} races")
                 
             except Exception as e:
                 logger.error(f"Scraping failed: {e}")
                 races = []
-            
+
             # スクレイピング失敗時はデモデータにフォールバック
             if not races:
                 logger.warning("No races from scraping, falling back to demo data")
                 races = self._create_demo_races()
                 use_demo_data = True
+                fallback_notice = (
+                    "⚠️ スクレイピングに失敗したためデモデータで配信しています。"
+                    "ネットワークやプロキシ設定を確認し、必要に応じて USE_SYSTEM_PROXY=1 を設定してください。"
+                )
         
         go_predictions = []
         
         for race in races:
             logger.info(f"Processing: {race.velodrome} {race.race_number}R")
             
             can_bet, reason = self.trader.can_bet()
             if not can_bet:
                 logger.warning(f"Betting stopped: {reason}")
                 break
             
             # 予想生成
             if demo_mode or use_demo_data:
                 # デモモードまたはフォールバック時は必ずGO
                 logger.info("Using demo prediction (always GO)")
                 prediction = self._create_demo_prediction(race)
             elif self.ai_engine:
                 # AI予想
                 logger.info("Using AI engine for prediction")
                 prediction = self.ai_engine.predict(race, learning_data)
             else:
                 # AIなしの場合もデモ予想
                 logger.info("No AI engine: using demo prediction")
                 prediction = self._create_demo_prediction(race)
             
@@ -349,52 +369,53 @@ class KeirinBot:
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
                 message = self._format_prediction_message(
-                    race, prediction, bet_record, 
-                    is_demo=use_demo_data
+                    race, prediction, bet_record,
+                    is_demo=use_demo_data,
+                    notice=fallback_notice
                 )
                 self._send_line_message(message)
         else:
             self._send_line_message(
                 "🚴 【本日の予想】\n\n"
                 "鉄板の守の判定: 全レース見送り（KEN）\n"
                 "リスクが高いと判断しました。"
             )
         
         logger.info(f"Morning job completed. GO: {len(go_predictions)}, Demo: {use_demo_data}")
     
     def run_night_job(self, demo_mode: bool = False):
         """夜のジョブ: 結果報告・反省会"""
         logger.info("=" * 50)
         logger.info("Starting night job v2.1")
         logger.info("=" * 50)
         
         unsettled_bets = self.trader.get_unsettled_bets()
         
         if not unsettled_bets:
             logger.info("No unsettled bets")
             report = self.trader.generate_report()
             self._send_line_message(f"🌙 【本日の収支報告】\n\n{report}")
             return
         
 
EOF
)
