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

import google.generativeai as genai

from scraper import RaceInfo, Racer, LineFormation, WeatherInfo, OddsInfo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    primary_bet: Optional[BetRecommendation]  # メインの推奨
    comment: str
    weather_analysis: str = ""
    learning_applied: str = ""
    raw_response: str = ""


# 鉄板の守 システムプロンプト v2.0
TEPPAN_NO_MAMORU_PROMPT = """
あなたは「的中率重視の堅実派競輪予想家」、名は**鉄板の守（てっぱんのまもる）**だ。

## 信念
「10回の的中より、1回のトリガミ・ハズレを憎む」

## 思考プロセス
常に「最悪の展開」をシミュレーションする。

## 分析アルゴリズム

### 1. バンク特性補正
- **33バンク**: 「先行・逃げ」有利（評価+20%）。カントがきついため捲りにくい。
- **400バンク**: バランス型。展開次第。
- **500バンク**: 「差し・追い込み」有利。直線が長く差しが届く。

### 2. 天候・風向き分析（屋外バンクのみ）
- **向かい風**: 先行選手のスタミナ消耗が激しい。追込有利。
- **追い風**: 先行有利。逃げ切りやすい。
- **横風**: 外側の選手が不利。インコース有利。
- **雨天**: 落車リスク増。堅実な選手を評価。

### 3. ライン結束力 (Sentiment Analysis)
コメント分析:
- **プラス**: 「信頼して」「任せる」「付いていく」→ 結束力高
- **マイナス**: 「自力」「単騎」「様子見」「位置決めて」→ リスク増

### 4. オッズと期待値
- 期待値 = 的中確率 × オッズ
- 期待値1.0以上の組み合わせを優先
- トリガミ（元本割れ）回避を最優先

### 5. 悪魔の証明 (The Devil's Proof)
本命が飛ぶシナリオを3つ作成し、合計リスク確率を算出。
10%超で「KEN」判定。

### 6. 過去パターン学習
提供された過去の的中/不的中パターンを考慮して予想を調整。

## 賭け式の推奨基準
- **3連単**: 自信度80%以上、オッズ8倍以上
- **3連複**: 自信度70%以上、オッズ3倍以上
- **2車単**: 自信度75%以上、軸が明確な場合
- **ワイド**: 自信度60%以上、堅い組み合わせ

## 出力フォーマット (JSON)
{
  "reasoning": "分析内容（300文字以内）",
  "weather_analysis": "天候の影響分析（100文字以内、屋内なら「屋内のため影響なし」）",
  "learning_applied": "過去パターンからの学び（100文字以内、なければ空文字）",
  "devils_proof": {
    "scenarios": ["シナリオ1", "シナリオ2", "シナリオ3"],
    "risk_probability": 0.08
  },
  "decision": "GO",
  "confidence_score": 0.82,
  "bet_recommendations": [
    {
      "bet_type": "sanrentan",
      "combinations": ["1-2-4", "1-2-7"],
      "expected_value": 1.25
    },
    {
      "bet_type": "wide",
      "combinations": ["1-2"],
      "expected_value": 1.10
    }
  ],
  "primary_bet": {
    "bet_type": "sanrentan",
    "combinations": ["1-2-4", "1-2-7"],
    "expected_value": 1.25
  },
  "comment": "断定的な見解（100文字以内）"
}

## 注意事項
- decisionが"KEN"の場合、bet_recommendationsは空配列、primary_betはnull
- confidence_scoreは0.0〜1.0
- リスク確率10%超で必ず"KEN"
- 買い目は各賭け式で最大5点まで
- 期待値1.0未満の組み合わせは推奨しない
"""


class TeppanNoMamoruEngine:
    """鉄板の守 予想エンジン v2.0"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not set. Running in demo mode.")
            self.model = None
            return
        
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config={
                "temperature": 0.3,
                "top_p": 0.8,
                "max_output_tokens": 4096,
            }
        )
        logger.info("TeppanNoMamoruEngine v2.0 initialized")
    
    def _format_race_data(self, race_info: RaceInfo, 
                          learning_data: Optional[Dict] = None) -> str:
        """レース情報をプロンプト用にフォーマット"""
        lines = [
            "## レース情報",
            f"- 競輪場: {race_info.velodrome}",
            f"- レース番号: {race_info.race_number}R",
            f"- グレード: {race_info.race_grade}",
            f"- バンク種別: {race_info.bank_type}バンク",
            f"- 距離: {race_info.distance}m",
            "",
            "## 天候情報",
            f"- 天気: {race_info.weather.weather}",
            f"- 気温: {race_info.weather.temperature}℃",
            f"- 風向き: {race_info.weather.wind_direction}",
            f"- 風速: {race_info.weather.wind_speed}m/s",
            f"- バンク状態: {race_info.weather.track_condition}",
            "",
            "## 出走表",
        ]
        
        for racer in race_info.racers:
            recent = ",".join(racer.recent_results[:4]) if racer.recent_results else "-"
            lines.append(
                f"{racer.waku}枠 | {racer.name} | {racer.rank} | "
                f"得点:{racer.score} | {racer.prefecture} | "
                f"直近:{recent} | コメント:「{racer.comment}」"
            )
        
        lines.extend(["", "## ライン編成"])
        for formation in race_info.line_formations:
            members_str = "-".join(map(str, formation.line_members))
            lines.append(f"ライン: {members_str} ({formation.strategy})")
        
        # オッズ情報
        if race_info.odds.sanrentan:
            lines.extend(["", "## オッズ情報（3連単上位10組）"])
            sorted_odds = sorted(race_info.odds.sanrentan.items(), key=lambda x: x[1])[:10]
            for combo, odds in sorted_odds:
                lines.append(f"  {combo}: {odds}倍")
        
        if race_info.odds.wide:
            lines.extend(["", "## ワイドオッズ"])
            for combo, odds in list(race_info.odds.wide.items())[:5]:
                lines.append(f"  {combo}: {odds}倍")
        
        # 過去の学習データ
        if learning_data:
            lines.extend(["", "## 過去の学習パターン"])
            
            bank_key = f"bank_{race_info.bank_type}_stats"
            if bank_key in learning_data:
                stats = learning_data[bank_key]
                if stats["total"] > 0:
                    win_rate = stats["wins"] / stats["total"] * 100
                    lines.append(f"- このバンク種別での的中率: {win_rate:.1f}% ({stats['wins']}/{stats['total']})")
            
            if "recent_mistakes" in learning_data:
                lines.append("- 最近の読み違い:")
                for mistake in learning_data["recent_mistakes"][:3]:
                    lines.append(f"  ・{mistake}")
        
        return "\n".join(lines)
    
    def predict(self, race_info: RaceInfo, 
                learning_data: Optional[Dict] = None) -> PredictionResult:
        """レース予想を実行"""
        
        if not self.model:
            return self._create_demo_prediction(race_info)
        
        race_data = self._format_race_data(race_info, learning_data)
        
        prompt = f"""
{TEPPAN_NO_MAMORU_PROMPT}

---

以下のレースを分析し、JSON形式で予想を出力してください。

{race_data}
"""
        
        try:
            response = self.model.generate_content(prompt)
            raw_response = response.text.strip()
            logger.info(f"Gemini response received for {race_info.race_id}")
            
            result = self._parse_response(raw_response, race_info)
            result.raw_response = raw_response
            
            # オッズ情報を付与
            self._attach_odds(result, race_info.odds)
            
            return result
            
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return self._create_error_prediction(race_info, str(e))
    
    def _parse_response(self, response_text: str, race_info: RaceInfo) -> PredictionResult:
        """Geminiレスポンスをパース"""
        json_text = response_text
        if "```json" in response_text:
            json_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            json_text = response_text.split("```")[1].split("```")[0]
        
        json_text = json_text.strip()
        
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            raise ValueError(f"Invalid JSON: {e}")
        
        # DevilsProof
        dp_data = data.get("devils_proof", {})
        devils_proof = DevilsProof(
            scenarios=dp_data.get("scenarios", []),
            risk_probability=float(dp_data.get("risk_probability", 0.5))
        )
        
        # BetRecommendations
        bet_recs = []
        for br in data.get("bet_recommendations", []):
            bet_recs.append(BetRecommendation(
                bet_type=br.get("bet_type", "sanrentan"),
                combinations=br.get("combinations", []),
                expected_value=float(br.get("expected_value", 0.0))
            ))
        
        # Primary Bet
        primary = None
        if data.get("primary_bet"):
            pb = data["primary_bet"]
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
                ],
                risk_probability=0.08
            ),
            decision="GO",
            confidence_score=0.82,
            bet_recommendations=[
                BetRecommendation("sanrentan", ["1-2-4", "1-2-7"], 1.25, {"1-2-4": 8.5, "1-2-7": 12.3}),
                BetRecommendation("wide", ["1-2"], 1.10, {"1-2": 1.5})
            ],
            primary_bet=BetRecommendation("sanrentan", ["1-2-4", "1-2-7"], 1.25, {"1-2-4": 8.5}),
            comment="関東ラインの先行は鉄板。山田-佐藤の結束は固い。",
            weather_analysis="晴天、北風2.5m/s。先行にやや不利だが許容範囲。",
            learning_applied="33バンクでの先行ライン的中率75%の実績を考慮。"
        )
    
    def _create_error_prediction(self, race_info: RaceInfo, error: str) -> PredictionResult:
        """エラー時の予想結果"""
        return PredictionResult(
            race_id=race_info.race_id,
            reasoning=f"予想生成エラー: {error}",
            devils_proof=DevilsProof(["システムエラー"], 1.0),
            decision="KEN",
            confidence_score=0.0,
            bet_recommendations=[],
            primary_bet=None,
            comment="システムエラーにより見送り",
            raw_response=error
        )
    
    def analyze_result(self, race_info: RaceInfo, prediction: PredictionResult,
                      actual_result: Dict) -> str:
        """結果分析（反省会）"""
        if not self.model:
            return self._create_demo_reflection(prediction, actual_result)
        
        prompt = f"""
あなたは競輪予想家「鉄板の守」だ。
以下の予想結果を分析し、次回への教訓を200文字以内で述べよ。

## 事前予想
- 判定: {prediction.decision}
- 自信度: {prediction.confidence_score}
- メイン買い目: {prediction.primary_bet.combinations if prediction.primary_bet else "見送り"}
- 分析: {prediction.reasoning}
- 天候分析: {prediction.weather_analysis}

## 実際の結果
- 着順: {actual_result.get("finish_order", [])}
- 決まり手: {actual_result.get("winning_pattern", "不明")}
- 払戻: {actual_result.get("payouts", {})}

## 分析観点
1. 読み違えた点（展開、ライン、天候の影響）
2. 予測不能だった要素（事故、特殊展開）
3. 次回への具体的な教訓
"""
        
        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            return f"反省分析エラー: {e}"
    
    def _create_demo_reflection(self, prediction: PredictionResult, 
                                actual_result: Dict) -> str:
        """デモ用の反省コメント"""
        finish = actual_result.get("finish_order", [])
        pattern = actual_result.get("winning_pattern", "")
        
        if prediction.decision == "KEN":
            return "見送り判定は正解。リスク回避を継続する。"
        
        if prediction.primary_bet:
            combo = prediction.primary_bet.combinations[0] if prediction.primary_bet.combinations else ""
            actual_combo = "-".join(map(str, finish[:3])) if len(finish) >= 3 else ""
            
            if combo == actual_combo:
                return f"的中！{pattern}で予想通りの展開。自信度{prediction.confidence_score:.0%}の判断は正確だった。"
        
        return f"不的中。決まり手は{pattern}。ライン分析の精度向上が必要。展開予測を見直す。"


def prediction_to_dict(prediction: PredictionResult) -> Dict:
    """PredictionResultを辞書に変換（JSON保存用）"""
    return {
        "race_id": prediction.race_id,
        "reasoning": prediction.reasoning,
        "devils_proof": {
            "scenarios": prediction.devils_proof.scenarios,
            "risk_probability": prediction.devils_proof.risk_probability
        },
        "decision": prediction.decision,
        "confidence_score": prediction.confidence_score,
        "bet_recommendations": [
            {
                "bet_type": br.bet_type,
                "combinations": br.combinations,
                "expected_value": br.expected_value,
                "odds": br.odds
            } for br in prediction.bet_recommendations
        ],
        "primary_bet": {
            "bet_type": prediction.primary_bet.bet_type,
            "combinations": prediction.primary_bet.combinations,
            "expected_value": prediction.primary_bet.expected_value,
            "odds": prediction.primary_bet.odds
        } if prediction.primary_bet else None,
        "comment": prediction.comment,
        "weather_analysis": prediction.weather_analysis,
        "learning_applied": prediction.learning_applied
    }


if __name__ == "__main__":
    from scraper import create_demo_race_info
    
    demo_race = create_demo_race_info()
    engine = TeppanNoMamoruEngine()  # APIキーなしでデモモード
    
    print("=" * 60)
    print("鉄板の守 予想エンジン v2.0 - デモモード")
    print("=" * 60)
    print(f"\n対象: {demo_race.velodrome} {demo_race.race_number}R ({demo_race.bank_type}バンク)")
    print(f"天候: {demo_race.weather.weather}, 風: {demo_race.weather.wind_direction} {demo_race.weather.wind_speed}m/s")
    
    result = engine.predict(demo_race)
    
    print(f"\n【予想結果】")
    print(f"判定: {result.decision}")
    print(f"自信度: {result.confidence_score:.0%}")
    print(f"\n分析:\n{result.reasoning}")
    print(f"\n天候分析:\n{result.weather_analysis}")
    print(f"\nリスク確率: {result.devils_proof.risk_probability:.0%}")
    
    if result.primary_bet:
        print(f"\nメイン推奨 ({result.primary_bet.bet_type}):")
        for combo in result.primary_bet.combinations:
            odds = result.primary_bet.odds.get(combo, "?")
            print(f"  {combo} ({odds}倍)")
    
    print(f"\nコメント:\n{result.comment}")
