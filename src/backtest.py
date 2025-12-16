"""
バックテストモジュール
過去データを使用して予想ロジックを検証
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """バックテスト結果"""
    test_id: str
    strategy_name: str
    test_period: str
    total_races: int
    bets_placed: int
    ken_count: int
    wins: int
    losses: int
    initial_bankroll: int
    final_bankroll: int
    total_wagered: int
    total_returned: int
    roi_percentage: float
    win_rate: float
    max_drawdown: int
    max_losing_streak: int
    avg_odds_won: float
    best_bet: Dict = field(default_factory=dict)
    worst_bet: Dict = field(default_factory=dict)
    bank_type_performance: Dict = field(default_factory=dict)
    timestamp: str = ""


@dataclass 
class SimulatedRace:
    """シミュレーション用レースデータ"""
    race_id: str
    velodrome: str
    bank_type: str
    race_grade: str
    weather: str
    racers: List[Dict]
    line_formations: List[Dict]
    odds: Dict
    actual_result: Dict


class BacktestEngine:
    """バックテストエンジン"""
    
    def __init__(self, data_path: str = "data/data.json"):
        self.data_path = Path(data_path)
        self.results_history: List[BacktestResult] = []
    
    def run_backtest(self, 
                    historical_races: List[SimulatedRace],
                    strategy_name: str = "teppan_no_mamoru",
                    initial_bankroll: int = 10000,
                    kelly_multiplier: float = 0.1,
                    confidence_threshold: float = 0.70) -> BacktestResult:
        """
        バックテストを実行
        
        Args:
            historical_races: 過去レースデータ
            strategy_name: 戦略名
            initial_bankroll: 初期資金
            kelly_multiplier: ケリー係数
            confidence_threshold: ベット実行の自信度閾値
        """
        logger.info(f"Starting backtest: {strategy_name}, {len(historical_races)} races")
        
        # 初期化
        bankroll = initial_bankroll
        stats = {
            "bets_placed": 0,
            "ken_count": 0,
            "wins": 0,
            "losses": 0,
            "total_wagered": 0,
            "total_returned": 0,
            "losing_streak": 0,
            "max_losing_streak": 0,
            "max_drawdown": 0,
            "peak_bankroll": initial_bankroll,
            "odds_won": [],
            "best_bet": {"profit": 0},
            "worst_bet": {"loss": 0},
            "bank_type_stats": {}
        }
        
        bankroll_history = [initial_bankroll]
        
        for race in historical_races:
            # 予想をシミュレート
            prediction = self._simulate_prediction(race, strategy_name)
            
            if prediction["decision"] == "KEN":
                stats["ken_count"] += 1
                continue
            
            if prediction["confidence"] < confidence_threshold:
                stats["ken_count"] += 1
                continue
            
            # ベット額計算
            bet_amount = int(bankroll * prediction["confidence"] * kelly_multiplier / 100) * 100
            bet_amount = max(100, min(bet_amount, int(bankroll * 0.1)))
            
            if bet_amount > bankroll:
                logger.warning(f"Insufficient bankroll for {race.race_id}")
                continue
            
            # ベット実行
            bankroll -= bet_amount
            stats["bets_placed"] += 1
            stats["total_wagered"] += bet_amount
            
            # バンク別統計
            if race.bank_type not in stats["bank_type_stats"]:
                stats["bank_type_stats"][race.bank_type] = {"bets": 0, "wins": 0, "profit": 0}
            stats["bank_type_stats"][race.bank_type]["bets"] += 1
            
            # 的中判定
            is_won, payout = self._check_result(
                prediction["combinations"],
                race.actual_result,
                race.odds,
                bet_amount
            )
            
            if is_won:
                bankroll += payout
                stats["wins"] += 1
                stats["total_returned"] += payout
                stats["losing_streak"] = 0
                stats["odds_won"].append(payout / bet_amount)
                stats["bank_type_stats"][race.bank_type]["wins"] += 1
                stats["bank_type_stats"][race.bank_type]["profit"] += payout - bet_amount
                
                profit = payout - bet_amount
                if profit > stats["best_bet"]["profit"]:
                    stats["best_bet"] = {
                        "race_id": race.race_id,
                        "profit": profit,
                        "odds": payout / bet_amount
                    }
            else:
                stats["losses"] += 1
                stats["losing_streak"] += 1
                stats["bank_type_stats"][race.bank_type]["profit"] -= bet_amount
                
                if stats["losing_streak"] > stats["max_losing_streak"]:
                    stats["max_losing_streak"] = stats["losing_streak"]
                
                if bet_amount > stats["worst_bet"]["loss"]:
                    stats["worst_bet"] = {
                        "race_id": race.race_id,
                        "loss": bet_amount
                    }
            
            # ドローダウン計算
            if bankroll > stats["peak_bankroll"]:
                stats["peak_bankroll"] = bankroll
            drawdown = stats["peak_bankroll"] - bankroll
            if drawdown > stats["max_drawdown"]:
                stats["max_drawdown"] = drawdown
            
            bankroll_history.append(bankroll)
        
        # 結果集計
        total_bets = stats["bets_placed"]
        win_rate = (stats["wins"] / total_bets * 100) if total_bets > 0 else 0
        roi = ((stats["total_returned"] - stats["total_wagered"]) / 
               stats["total_wagered"] * 100) if stats["total_wagered"] > 0 else 0
        avg_odds = sum(stats["odds_won"]) / len(stats["odds_won"]) if stats["odds_won"] else 0
        
        result = BacktestResult(
            test_id=f"bt_{strategy_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            strategy_name=strategy_name,
            test_period=f"{historical_races[0].race_id} - {historical_races[-1].race_id}" if historical_races else "",
            total_races=len(historical_races),
            bets_placed=stats["bets_placed"],
            ken_count=stats["ken_count"],
            wins=stats["wins"],
            losses=stats["losses"],
            initial_bankroll=initial_bankroll,
            final_bankroll=bankroll,
            total_wagered=stats["total_wagered"],
            total_returned=stats["total_returned"],
            roi_percentage=round(roi, 2),
            win_rate=round(win_rate, 2),
            max_drawdown=stats["max_drawdown"],
            max_losing_streak=stats["max_losing_streak"],
            avg_odds_won=round(avg_odds, 2),
            best_bet=stats["best_bet"],
            worst_bet=stats["worst_bet"],
            bank_type_performance=stats["bank_type_stats"],
            timestamp=datetime.now().isoformat()
        )
        
        self.results_history.append(result)
        self._save_result(result)
        
        logger.info(f"Backtest completed: ROI={roi:.1f}%, Win Rate={win_rate:.1f}%")
        return result
    
    def _simulate_prediction(self, race: SimulatedRace, strategy: str) -> Dict:
        """予想をシミュレート（簡易版）"""
        # 実際の実装ではAIエンジンを使用
        # ここでは簡易的なルールベース予想
        
        confidence = 0.5
        decision = "KEN"
        combinations = []
        
        # バンク特性による補正
        if race.bank_type == "33":
            # 33バンクは先行有利
            for formation in race.line_formations:
                if formation.get("strategy") in ["先行", "逃げ"]:
                    confidence += 0.15
                    break
        elif race.bank_type == "500":
            # 500バンクは追込有利
            for formation in race.line_formations:
                if formation.get("strategy") in ["追込", "差し"]:
                    confidence += 0.15
                    break
        
        # 選手の得点による補正
        if race.racers:
            top_scorer = max(race.racers, key=lambda x: x.get("score", 0))
            if top_scorer.get("score", 0) > 115:
                confidence += 0.1
        
        # ライン結束力（コメント分析の簡易版）
        for racer in race.racers:
            comment = racer.get("comment", "")
            if "信頼" in comment or "任せる" in comment:
                confidence += 0.05
            if "自力" in comment or "単騎" in comment:
                confidence -= 0.05
        
        # 閾値判定
        if confidence >= 0.65:
            decision = "GO"
            # 買い目作成（簡易版：得点上位3人の組み合わせ）
            sorted_racers = sorted(race.racers, key=lambda x: x.get("score", 0), reverse=True)
            if len(sorted_racers) >= 3:
                top3 = [r.get("waku", i+1) for i, r in enumerate(sorted_racers[:3])]
                combinations = [f"{top3[0]}-{top3[1]}-{top3[2]}"]
        
        return {
            "decision": decision,
            "confidence": min(confidence, 0.95),
            "combinations": combinations
        }
    
    def _check_result(self, combinations: List[str], actual_result: Dict,
                     odds: Dict, bet_amount: int) -> tuple:
        """的中判定と払戻計算"""
        finish_order = actual_result.get("finish_order", [])
        
        if len(finish_order) < 3:
            return False, 0
        
        actual_combo = f"{finish_order[0]}-{finish_order[1]}-{finish_order[2]}"
        
        for combo in combinations:
            if combo == actual_combo:
                combo_odds = odds.get("sanrentan", {}).get(combo, 10.0)
                payout = int(bet_amount * combo_odds)
                return True, payout
        
        return False, 0
    
    def _save_result(self, result: BacktestResult):
        """結果を保存"""
        if self.data_path.exists():
            with open(self.data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {"backtest_results": []}
        
        if "backtest_results" not in data:
            data["backtest_results"] = []
        
        data["backtest_results"].append(asdict(result))
        
        # 最新20件のみ保持
        data["backtest_results"] = data["backtest_results"][-20:]
        
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def generate_report(self, result: BacktestResult) -> str:
        """バックテストレポート生成"""
        profit = result.final_bankroll - result.initial_bankroll
        profit_sign = "+" if profit >= 0 else ""
        
        report = f"""
📊 【バックテスト結果レポート】

🔬 テスト情報
   戦略: {result.strategy_name}
   期間: {result.test_period}
   対象レース数: {result.total_races}

💰 資金推移
   初期資金: ¥{result.initial_bankroll:,}
   最終資金: ¥{result.final_bankroll:,}
   損益: {profit_sign}¥{profit:,}
   最大ドローダウン: -¥{result.max_drawdown:,}

📈 パフォーマンス
   ベット数: {result.bets_placed}回
   見送り: {result.ken_count}回
   的中: {result.wins}回
   不的中: {result.losses}回
   勝率: {result.win_rate}%
   回収率: {result.roi_percentage}%
   平均的中オッズ: {result.avg_odds_won}倍

⚠️ リスク指標
   最大連敗: {result.max_losing_streak}回

🏟️ バンク別成績
"""
        for bank, stats in result.bank_type_performance.items():
            win_rate = (stats["wins"] / stats["bets"] * 100) if stats["bets"] > 0 else 0
            report += f"   {bank}バンク: {stats['wins']}/{stats['bets']} ({win_rate:.0f}%) {'+' if stats['profit'] >= 0 else ''}¥{stats['profit']:,}\n"
        
        if result.best_bet.get("profit", 0) > 0:
            report += f"""
🎯 ベストベット
   {result.best_bet.get('race_id', '-')}
   利益: +¥{result.best_bet.get('profit', 0):,} ({result.best_bet.get('odds', 0):.1f}倍)
"""
        
        return report.strip()


def create_sample_historical_data() -> List[SimulatedRace]:
    """サンプル過去データを作成（デモ用）"""
    import random
    
    velodromes = ["前橋", "川崎", "平塚", "小倉", "京王閣"]
    bank_types = {"前橋": "33", "川崎": "400", "平塚": "400", "小倉": "33", "京王閣": "500"}
    strategies = ["先行", "捲り", "追込", "自在"]
    kimarites = ["逃げ", "捲り", "差し", "マーク"]
    
    races = []
    
    for i in range(50):
        velodrome = random.choice(velodromes)
        
        # 選手データ
        racers = []
        for waku in range(1, 10):
            racers.append({
                "waku": waku,
                "name": f"選手{waku}",
                "score": round(random.uniform(100, 120), 1),
                "comment": random.choice(["信頼して付く", "自力で勝負", "展開次第", "任せる"])
            })
        
        # ライン編成
        formations = [
            {"line_members": [1, 2, 4], "strategy": random.choice(strategies)},
            {"line_members": [3, 7], "strategy": random.choice(strategies)},
            {"line_members": [5, 8, 9], "strategy": random.choice(strategies)},
        ]
        
        # 実際の結果
        finish = list(range(1, 10))
        random.shuffle(finish)
        
        # オッズ
        odds = {"sanrentan": {}}
        for a in range(1, 10):
            for b in range(1, 10):
                if a == b:
                    continue
                for c in range(1, 10):
                    if c in [a, b]:
                        continue
                    combo = f"{a}-{b}-{c}"
                    odds["sanrentan"][combo] = round(random.uniform(5, 100), 1)
        
        races.append(SimulatedRace(
            race_id=f"{velodrome}_{random.randint(1,12)}_{20241201+i}",
            velodrome=velodrome,
            bank_type=bank_types[velodrome],
            race_grade=random.choice(["GI", "GII", "GIII", "FI", "FII"]),
            weather=random.choice(["晴", "曇", "雨"]),
            racers=racers,
            line_formations=formations,
            odds=odds,
            actual_result={
                "finish_order": finish,
                "winning_pattern": random.choice(kimarites)
            }
        ))
    
    return races


if __name__ == "__main__":
    import tempfile
    import os
    
    print("=" * 60)
    print("バックテストエンジン - デモ実行")
    print("=" * 60)
    
    # サンプルデータ作成
    print("\n過去データを生成中...")
    historical_races = create_sample_historical_data()
    print(f"生成完了: {len(historical_races)}レース")
    
    # バックテスト実行
    with tempfile.TemporaryDirectory() as tmpdir:
        data_path = os.path.join(tmpdir, "data.json")
        engine = BacktestEngine(data_path)
        
        print("\nバックテスト実行中...")
        result = engine.run_backtest(
            historical_races,
            strategy_name="teppan_no_mamoru",
            initial_bankroll=10000,
            kelly_multiplier=0.1,
            confidence_threshold=0.65
        )
        
        print("\n" + engine.generate_report(result))
