"""
資金管理モジュール v2.0
- 簡易ケリー基準
- 損切りルール（連敗停止、日次損失上限）
- 選手別成績DB
- マルチベット対応
- パターン分析・学習
"""
import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict, field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class BetRecord:
    """ベット記録（マルチベット対応）"""
    bet_id: str
    race_id: str
    timestamp: str
    decision: str
    confidence_score: float
    bets: List[Dict]  # [{type, combinations, amount, odds}]
    total_amount: int
    expected_return: float
    actual_return: Optional[int] = None
    is_won: Optional[bool] = None
    result_checked: bool = False
    winning_combination: str = ""
    kimarite: str = ""


@dataclass
class RacerRecord:
    """選手成績レコード"""
    racer_id: str
    name: str
    total_races: int = 0
    wins: int = 0
    second: int = 0
    third: int = 0
    avg_score: float = 0.0
    favorite_bank: str = ""
    results_by_bank: Dict[str, Dict] = field(default_factory=dict)
    last_updated: str = ""


@dataclass
class RiskControl:
    """リスク管理設定"""
    max_losing_streak_limit: int = 3
    daily_loss_limit: int = 3000
    is_stopped_today: bool = False
    stop_reason: Optional[str] = None


class BankrollManager:
    """バンクロール管理クラス v2.0"""
    
    INITIAL_BANKROLL = 10000
    KELLY_MULTIPLIER = 0.1
    MAX_BET_RATIO = 0.1
    MIN_BET_AMOUNT = 100
    
    # 賭け式ごとの資金配分比率
    BET_TYPE_ALLOCATION = {
        "sanrentan": 0.6,   # 3連単: 60%
        "sanrenpuku": 0.2,  # 3連複: 20%
        "nirentan": 0.15,   # 2車単: 15%
        "wide": 0.05        # ワイド: 5%
    }
    
    def __init__(self, data_path: str = "data/data.json"):
        self.data_path = Path(data_path)
        self.data = self._load_data()
        self._check_daily_reset()
    
    def _load_data(self) -> Dict:
        if self.data_path.exists():
            try:
                with open(self.data_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load data: {e}")
        
        return self._create_initial_data()
    
    def _create_initial_data(self) -> Dict:
        return {
            "bankroll": {
                "initial_amount": self.INITIAL_BANKROLL,
                "current_amount": self.INITIAL_BANKROLL,
                "last_updated": None
            },
            "statistics": {
                "total_bets": 0,
                "wins": 0,
                "losses": 0,
                "ken_count": 0,
                "total_wagered": 0,
                "total_returned": 0,
                "roi_percentage": 0.0,
                "current_losing_streak": 0,
                "max_losing_streak": 0,
                "daily_loss": 0,
                "last_bet_date": None
            },
            "risk_control": {
                "max_losing_streak_limit": 3,
                "daily_loss_limit": 3000,
                "is_stopped_today": False,
                "stop_reason": None
            },
            "bet_history": [],
            "learning_logs": [],
            "racer_database": {},
            "pattern_analysis": {
                "bank_33_stats": {"wins": 0, "total": 0, "patterns": {}},
                "bank_400_stats": {"wins": 0, "total": 0, "patterns": {}},
                "bank_500_stats": {"wins": 0, "total": 0, "patterns": {}},
                "weather_stats": {},
                "kimarite_stats": {}
            },
            "backtest_results": []
        }
    
    def _save_data(self):
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        logger.info(f"Data saved to {self.data_path}")
    
    def _check_daily_reset(self):
        """日付変更時のリセット処理"""
        today = date.today().isoformat()
        last_date = self.data["statistics"].get("last_bet_date")
        
        if last_date != today:
            self.data["statistics"]["daily_loss"] = 0
            self.data["risk_control"]["is_stopped_today"] = False
            self.data["risk_control"]["stop_reason"] = None
            logger.info("Daily counters reset")
    
    @property
    def current_bankroll(self) -> int:
        return self.data["bankroll"]["current_amount"]
    
    @property
    def risk_control(self) -> RiskControl:
        rc = self.data["risk_control"]
        return RiskControl(**rc)
    
    def can_bet(self) -> tuple:
        """ベット可能か判定"""
        rc = self.risk_control
        stats = self.data["statistics"]
        
        # 日次停止チェック
        if rc.is_stopped_today:
            return False, f"本日は停止中: {rc.stop_reason}"
        
        # 連敗チェック
        if stats["current_losing_streak"] >= rc.max_losing_streak_limit:
            self._stop_betting(f"連敗数が{rc.max_losing_streak_limit}に達しました")
            return False, f"連敗停止: {stats['current_losing_streak']}連敗"
        
        # 日次損失チェック
        if stats["daily_loss"] >= rc.daily_loss_limit:
            self._stop_betting(f"日次損失が{rc.daily_loss_limit}円に達しました")
            return False, f"損失上限: 本日-{stats['daily_loss']}円"
        
        # 資金チェック
        if self.current_bankroll < self.MIN_BET_AMOUNT:
            return False, "資金不足"
        
        return True, "OK"
    
    def _stop_betting(self, reason: str):
        """ベット停止"""
        self.data["risk_control"]["is_stopped_today"] = True
        self.data["risk_control"]["stop_reason"] = reason
        self._save_data()
        logger.warning(f"Betting stopped: {reason}")
    
    def calculate_bet_amount(self, confidence_score: float, 
                            bet_type: str = "sanrentan") -> int:
        """ベット額を計算（賭け式別）"""
        can, reason = self.can_bet()
        if not can:
            logger.warning(f"Cannot bet: {reason}")
            return 0
        
        bankroll = self.current_bankroll
        
        # ケリー基準
        raw_bet = bankroll * (confidence_score * self.KELLY_MULTIPLIER)
        
        # 賭け式別の配分
        allocation = self.BET_TYPE_ALLOCATION.get(bet_type, 0.5)
        allocated_bet = raw_bet * allocation
        
        # キャップ
        max_bet = bankroll * self.MAX_BET_RATIO
        capped_bet = min(allocated_bet, max_bet)
        
        # 丸め
        rounded_bet = int(capped_bet / 100) * 100
        final_bet = max(rounded_bet, self.MIN_BET_AMOUNT)
        
        if final_bet > bankroll:
            final_bet = int(bankroll / 100) * 100
        
        return final_bet
    
    def place_multi_bet(self, race_id: str, decision: str, confidence_score: float,
                       bet_recommendations: List[Dict]) -> BetRecord:
        """マルチベットを記録"""
        timestamp = datetime.now().isoformat()
        bet_id = f"bet_{race_id}_{timestamp[:19].replace(':', '')}"
        today = date.today().isoformat()
        
        self.data["statistics"]["last_bet_date"] = today
        
        if decision == "KEN":
            self.data["statistics"]["ken_count"] += 1
            record = BetRecord(
                bet_id=bet_id,
                race_id=race_id,
                timestamp=timestamp,
                decision=decision,
                confidence_score=confidence_score,
                bets=[],
                total_amount=0,
                expected_return=0
            )
            self.data["bet_history"].append(asdict(record))
            self._save_data()
            return record
        
        # GOの場合、各賭け式でベット
        bets = []
        total_amount = 0
        total_expected = 0
        
        for rec in bet_recommendations:
            bet_type = rec.get("bet_type", "sanrentan")
            combinations = rec.get("combinations", [])
            odds = rec.get("odds", {})
            expected_value = rec.get("expected_value", 1.0)
            
            if not combinations:
                continue
            
            # この賭け式の総額を計算
            type_amount = self.calculate_bet_amount(confidence_score, bet_type)
            if type_amount == 0:
                continue
            
            # 各組み合わせに均等配分
            per_combo = (type_amount // len(combinations) // 100) * 100
            if per_combo < 100:
                per_combo = 100
            
            combo_bets = []
            for combo in combinations:
                combo_odds = odds.get(combo, 10.0)
                combo_bets.append({
                    "combination": combo,
                    "amount": per_combo,
                    "odds": combo_odds
                })
                total_amount += per_combo
                total_expected += per_combo * combo_odds * (confidence_score * expected_value)
            
            bets.append({
                "type": bet_type,
                "combinations": combo_bets,
                "subtotal": per_combo * len(combinations)
            })
        
        # 資金から差し引き
        if total_amount > 0:
            self.data["bankroll"]["current_amount"] -= total_amount
            self.data["statistics"]["total_bets"] += 1
            self.data["statistics"]["total_wagered"] += total_amount
        
        record = BetRecord(
            bet_id=bet_id,
            race_id=race_id,
            timestamp=timestamp,
            decision=decision,
            confidence_score=confidence_score,
            bets=bets,
            total_amount=total_amount,
            expected_return=total_expected
        )
        
        self.data["bet_history"].append(asdict(record))
        self.data["bankroll"]["last_updated"] = timestamp
        self._save_data()
        
        logger.info(f"Multi-bet placed: {bet_id}, total={total_amount}")
        return record
    
    def settle_bet(self, bet_id: str, actual_result: Dict) -> Optional[BetRecord]:
        """ベット結果を精算"""
        finish_order = actual_result.get("finish_order", [])
        payouts = actual_result.get("payouts", {})
        kimarite = actual_result.get("winning_pattern", "")
        
        for i, bet in enumerate(self.data["bet_history"]):
            if bet["bet_id"] != bet_id:
                continue
            
            if bet["decision"] == "KEN":
                bet["result_checked"] = True
                self.data["bet_history"][i] = bet
                self._save_data()
                return BetRecord(**bet)
            
            # 的中判定
            total_return = 0
            is_won = False
            winning_combo = ""
            
            for bet_group in bet["bets"]:
                bet_type = bet_group["type"]
                
                # 着順から的中組み合わせを作成
                if len(finish_order) >= 3:
                    if bet_type == "sanrentan":
                        actual_combo = f"{finish_order[0]}-{finish_order[1]}-{finish_order[2]}"
                    elif bet_type == "sanrenpuku":
                        sorted_top3 = sorted(finish_order[:3])
                        actual_combo = f"{sorted_top3[0]}-{sorted_top3[1]}-{sorted_top3[2]}"
                    elif bet_type == "nirentan":
                        actual_combo = f"{finish_order[0]}-{finish_order[1]}"
                    elif bet_type == "wide":
                        actual_combo = None  # ワイドは複数的中あり
                    else:
                        actual_combo = None
                    
                    for combo_bet in bet_group["combinations"]:
                        combo = combo_bet["combination"]
                        amount = combo_bet["amount"]
                        odds = combo_bet["odds"]
                        
                        hit = False
                        if bet_type == "wide":
                            # ワイドは3着以内の2車
                            combo_nums = set(map(int, combo.replace("-", "").replace("=", "")))
                            top3_set = set(finish_order[:3])
                            if combo_nums.issubset(top3_set):
                                hit = True
                        elif actual_combo and combo == actual_combo:
                            hit = True
                        
                        if hit:
                            is_won = True
                            winning_combo = combo
                            ret = int(amount * odds)
                            total_return += ret
            
            # 結果を更新
            bet["is_won"] = is_won
            bet["actual_return"] = total_return
            bet["result_checked"] = True
            bet["winning_combination"] = winning_combo
            bet["kimarite"] = kimarite
            
            # 統計更新
            if is_won:
                self.data["bankroll"]["current_amount"] += total_return
                self.data["statistics"]["wins"] += 1
                self.data["statistics"]["total_returned"] += total_return
                self.data["statistics"]["current_losing_streak"] = 0
            else:
                self.data["statistics"]["losses"] += 1
                self.data["statistics"]["current_losing_streak"] += 1
                self.data["statistics"]["daily_loss"] += bet["total_amount"]
                
                if self.data["statistics"]["current_losing_streak"] > \
                   self.data["statistics"]["max_losing_streak"]:
                    self.data["statistics"]["max_losing_streak"] = \
                        self.data["statistics"]["current_losing_streak"]
            
            # ROI更新
            wagered = self.data["statistics"]["total_wagered"]
            returned = self.data["statistics"]["total_returned"]
            if wagered > 0:
                self.data["statistics"]["roi_percentage"] = \
                    round((returned - wagered) / wagered * 100, 2)
            
            self.data["bet_history"][i] = bet
            self.data["bankroll"]["last_updated"] = datetime.now().isoformat()
            self._save_data()
            
            logger.info(f"Bet settled: {bet_id}, won={is_won}, return={total_return}")
            return BetRecord(**bet)
        
        return None
    
    def update_racer_database(self, racer_id: str, name: str, 
                             race_result: Dict, bank_type: str):
        """選手DBを更新"""
        db = self.data["racer_database"]
        
        if racer_id not in db:
            db[racer_id] = {
                "racer_id": racer_id,
                "name": name,
                "total_races": 0,
                "wins": 0,
                "second": 0,
                "third": 0,
                "results_by_bank": {},
                "last_updated": ""
            }
        
        record = db[racer_id]
        record["total_races"] += 1
        record["name"] = name
        record["last_updated"] = datetime.now().isoformat()
        
        finish = race_result.get("finish_position", 0)
        if finish == 1:
            record["wins"] += 1
        elif finish == 2:
            record["second"] += 1
        elif finish == 3:
            record["third"] += 1
        
        # バンク別成績
        if bank_type not in record["results_by_bank"]:
            record["results_by_bank"][bank_type] = {"races": 0, "wins": 0}
        record["results_by_bank"][bank_type]["races"] += 1
        if finish == 1:
            record["results_by_bank"][bank_type]["wins"] += 1
        
        self._save_data()
    
    def update_pattern_analysis(self, bank_type: str, is_won: bool, 
                               kimarite: str, weather: str = ""):
        """パターン分析を更新"""
        pa = self.data["pattern_analysis"]
        
        # バンク別統計
        bank_key = f"bank_{bank_type}_stats"
        if bank_key in pa:
            pa[bank_key]["total"] += 1
            if is_won:
                pa[bank_key]["wins"] += 1
        
        # 決まり手統計
        if kimarite:
            if kimarite not in pa["kimarite_stats"]:
                pa["kimarite_stats"][kimarite] = {"total": 0, "predicted": 0}
            pa["kimarite_stats"][kimarite]["total"] += 1
            if is_won:
                pa["kimarite_stats"][kimarite]["predicted"] += 1
        
        # 天候統計
        if weather:
            if weather not in pa["weather_stats"]:
                pa["weather_stats"][weather] = {"total": 0, "wins": 0}
            pa["weather_stats"][weather]["total"] += 1
            if is_won:
                pa["weather_stats"][weather]["wins"] += 1
        
        self._save_data()
    
    def get_learning_data(self) -> Dict:
        """学習用データを取得"""
        pa = self.data["pattern_analysis"]
        logs = self.data["learning_logs"]
        
        # 最近の失敗パターンを抽出
        recent_mistakes = []
        for log in logs[-10:]:
            if "mistake" in log.get("reflection", "").lower() or \
               "外" in log.get("reflection", ""):
                recent_mistakes.append(log.get("reflection", "")[:100])
        
        return {
            **pa,
            "recent_mistakes": recent_mistakes
        }
    
    def add_learning_log(self, race_id: str, prediction_summary: str,
                        result_summary: str, reflection: str):
        """学習ログを追加"""
        self.data["learning_logs"].append({
            "timestamp": datetime.now().isoformat(),
            "race_id": race_id,
            "prediction_summary": prediction_summary,
            "result_summary": result_summary,
            "reflection": reflection
        })
        
        if len(self.data["learning_logs"]) > 100:
            self.data["learning_logs"] = self.data["learning_logs"][-100:]
        
        self._save_data()
    
    def get_unsettled_bets(self) -> List[BetRecord]:
        """未精算ベット一覧"""
        return [
            BetRecord(**bet) for bet in self.data["bet_history"]
            if not bet.get("result_checked", False) and bet["decision"] == "GO"
        ]
    
    def generate_report(self) -> str:
        """収支レポート生成"""
        stats = self.data["statistics"]
        bankroll = self.current_bankroll
        initial = self.data["bankroll"]["initial_amount"]
        rc = self.risk_control
        
        profit = bankroll - initial
        profit_sign = "+" if profit >= 0 else ""
        win_rate = (stats["wins"] / stats["total_bets"] * 100) if stats["total_bets"] > 0 else 0
        
        status = "🟢 稼働中"
        if rc.is_stopped_today:
            status = f"🔴 停止中: {rc.stop_reason}"
        elif stats["current_losing_streak"] >= 2:
            status = f"🟡 注意: {stats['current_losing_streak']}連敗中"
        
        report = f"""
📊 【競輪Bot 収支レポート v2.0】

{status}

💰 資金状況
   現在:     ¥{bankroll:,}
   初期:     ¥{initial:,}
   損益:     {profit_sign}¥{profit:,}
   本日損失: -¥{stats['daily_loss']:,}

📈 統計
   総ベット: {stats['total_bets']}回
   的中:     {stats['wins']}回
   不的中:   {stats['losses']}回
   見送り:   {stats['ken_count']}回
   勝率:     {win_rate:.1f}%

🎯 投資効率
   総投資: ¥{stats['total_wagered']:,}
   総払戻: ¥{stats['total_returned']:,}
   回収率: {stats['roi_percentage']:.1f}%

⚠️ リスク管理
   現在連敗: {stats['current_losing_streak']}回
   最大連敗: {stats['max_losing_streak']}回
   停止条件: {rc.max_losing_streak_limit}連敗 or 日次-¥{rc.daily_loss_limit:,}
"""
        return report.strip()
    
    def reset(self):
        """完全リセット"""
        self.data = self._create_initial_data()
        self._save_data()
        logger.info("Bankroll reset")


if __name__ == "__main__":
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmpdir:
        data_path = os.path.join(tmpdir, "data.json")
        manager = BankrollManager(data_path)
        
        print("=" * 60)
        print("バンクロール管理 v2.0 - テスト")
        print("=" * 60)
        
        # ベット可能チェック
        can, reason = manager.can_bet()
        print(f"\nベット可能: {can} ({reason})")
        
        # マルチベット
        bet_recs = [
            {"bet_type": "sanrentan", "combinations": ["1-2-4", "1-2-7"], 
             "odds": {"1-2-4": 8.5, "1-2-7": 12.3}, "expected_value": 1.2},
            {"bet_type": "wide", "combinations": ["1-2"],
             "odds": {"1-2": 1.5}, "expected_value": 1.1}
        ]
        
        record = manager.place_multi_bet(
            race_id="maebashi_11",
            decision="GO",
            confidence_score=0.82,
            bet_recommendations=bet_recs
        )
        
        print(f"\nベット記録: {record.bet_id}")
        print(f"総額: ¥{record.total_amount:,}")
        for bet in record.bets:
            print(f"  {bet['type']}: {bet['subtotal']}円")
        
        # 結果精算（的中）
        result = {
            "finish_order": [1, 2, 4, 7, 3],
            "winning_pattern": "逃げ",
            "payouts": {"3連単": {"amount": 850, "combination": "1-2-4"}}
        }
        
        settled = manager.settle_bet(record.bet_id, result)
        print(f"\n精算結果: {'的中!' if settled.is_won else '不的中'}")
        print(f"払戻: ¥{settled.actual_return:,}")
        
        print("\n" + manager.generate_report())
