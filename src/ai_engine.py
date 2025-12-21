diff --git a/src/ai_engine.py b/src/ai_engine.py
index 658ec0bb3db08fe5915ab48a232631b1b251fd07..7e90707a681ac16cbe5e529504a05459d82fa75a 100644
--- a/src/ai_engine.py
+++ b/src/ai_engine.py
@@ -1,46 +1,50 @@
 """
 AI予想エンジン v2.0 - 鉄板の守 (Teppan no Mamoru)
 - 過去データ学習機能
 - 天候・風向き分析
 - マルチベット対応（3連単、3連複、2車単、ワイド）
 - 期待値計算
 """
 import os
 import json
 import logging
 from typing import Optional, List, Dict, Any
 from dataclasses import dataclass, field, asdict
 
+from dotenv import load_dotenv
 import google.generativeai as genai
 
 from scraper import RaceInfo, Racer, LineFormation, WeatherInfo, OddsInfo
 
 logging.basicConfig(level=logging.INFO)
 logger = logging.getLogger(__name__)
 
 
+load_dotenv()
+
+
 @dataclass
 class DevilsProof:
     """悪魔の証明"""
     scenarios: List[str]
     risk_probability: float
 
 
 @dataclass
 class BetRecommendation:
     """賭け推奨（マルチベット対応）"""
     bet_type: str  # "sanrentan", "sanrenpuku", "nirentan", "wide"
     combinations: List[str]
     expected_value: float = 0.0  # 期待値
     odds: Dict[str, float] = field(default_factory=dict)
 
 
 @dataclass
 class PredictionResult:
     """予想結果"""
     race_id: str
     reasoning: str
     devils_proof: DevilsProof
     decision: str
     confidence_score: float
     bet_recommendations: List[BetRecommendation]  # 複数の賭け式に対応
@@ -297,50 +301,51 @@ class TeppanNoMamoruEngine:
             primary = BetRecommendation(
                 bet_type=pb.get("bet_type", "sanrentan"),
                 combinations=pb.get("combinations", []),
                 expected_value=float(pb.get("expected_value", 0.0))
             )
         
         return PredictionResult(
             race_id=race_info.race_id,
             reasoning=data.get("reasoning", ""),
             devils_proof=devils_proof,
             decision=data.get("decision", "KEN"),
             confidence_score=float(data.get("confidence_score", 0.0)),
             bet_recommendations=bet_recs,
             primary_bet=primary,
             comment=data.get("comment", ""),
             weather_analysis=data.get("weather_analysis", ""),
             learning_applied=data.get("learning_applied", "")
         )
     
     def _attach_odds(self, result: PredictionResult, odds: OddsInfo):
         """予想結果にオッズ情報を付与"""
         odds_map = {
             "sanrentan": odds.sanrentan,
             "sanrenpuku": odds.sanrenpuku,
             "nirentan": odds.nirentan,
+            "nirenpuku": odds.nirenpuku,
             "wide": odds.wide
         }
         
         for bet_rec in result.bet_recommendations:
             if bet_rec.bet_type in odds_map:
                 for combo in bet_rec.combinations:
                     if combo in odds_map[bet_rec.bet_type]:
                         bet_rec.odds[combo] = odds_map[bet_rec.bet_type][combo]
         
         if result.primary_bet and result.primary_bet.bet_type in odds_map:
             for combo in result.primary_bet.combinations:
                 if combo in odds_map[result.primary_bet.bet_type]:
                     result.primary_bet.odds[combo] = odds_map[result.primary_bet.bet_type][combo]
     
     def _create_demo_prediction(self, race_info: RaceInfo) -> PredictionResult:
         """デモ用の予想結果を生成"""
         return PredictionResult(
             race_id=race_info.race_id,
             reasoning=f"{race_info.bank_type}バンクの{race_info.velodrome}。"
                      f"1番の先行を軸に関東ラインが盤石。コメントからも結束力の高さが伺える。",
             devils_proof=DevilsProof(
                 scenarios=[
                     "スタートで出遅れ位置取り失敗",
                     "早めの仕掛けでスタミナ切れ",
                     "後方からの突っ込みで接触"
