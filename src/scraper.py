"""
競輪データスクレイパー v2.0
- 楽天Kドリームス対応
- オッズ取得機能
- 天候・風向き取得
- 選手詳細情報取得
"""
import time
import logging
import re
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass, field, asdict

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class RacerStats:
    """選手の統計情報"""
    racer_id: str
    name: str
    total_races: int = 0
    wins: int = 0
    second_place: int = 0
    third_place: int = 0
    out_of_place: int = 0
    avg_score: float = 0.0
    favorite_bank: str = ""
    favorite_kimarite: str = ""  # 得意決まり手
    recent_form: List[int] = field(default_factory=list)  # 直近10走の着順
    
    @property
    def win_rate(self) -> float:
        return self.wins / self.total_races if self.total_races > 0 else 0.0
    
    @property
    def top3_rate(self) -> float:
        top3 = self.wins + self.second_place + self.third_place
        return top3 / self.total_races if self.total_races > 0 else 0.0


@dataclass
class Racer:
    """選手情報"""
    waku: int
    name: str
    racer_id: str = ""
    age: int = 0
    prefecture: str = ""
    rank: str = ""
    score: float = 0.0
    gear_ratio: str = ""
    comment: str = ""
    recent_results: List[str] = field(default_factory=list)
    win_rate: float = 0.0
    second_rate: float = 0.0
    third_rate: float = 0.0
    runaway_count: int = 0  # 逃げ回数
    overtake_count: int = 0  # 捲り回数
    marking_count: int = 0  # マーク回数


@dataclass
class LineFormation:
    """ライン編成"""
    line_members: List[int]
    strategy: str
    comment: str = ""
    strength_score: float = 0.0  # ライン強度スコア


@dataclass
class OddsInfo:
    """オッズ情報"""
    sanrentan: Dict[str, float] = field(default_factory=dict)  # 3連単
    sanrenpuku: Dict[str, float] = field(default_factory=dict)  # 3連複
    nirentan: Dict[str, float] = field(default_factory=dict)  # 2車単
    nirenpuku: Dict[str, float] = field(default_factory=dict)  # 2車複
    wide: Dict[str, float] = field(default_factory=dict)  # ワイド
    tansho: Dict[str, float] = field(default_factory=dict)  # 単勝
    fukusho: Dict[str, float] = field(default_factory=dict)  # 複勝


@dataclass
class WeatherInfo:
    """天候情報"""
    weather: str = "晴"  # 晴, 曇, 雨, 雪
    temperature: float = 20.0
    humidity: float = 50.0
    wind_direction: str = ""  # 北, 南, 東, 西, etc.
    wind_speed: float = 0.0  # m/s
    track_condition: str = "良"  # 良, 稍重, 重


@dataclass
class RaceInfo:
    """レース情報"""
    race_id: str
    velodrome: str
    velodrome_code: str
    race_number: int
    race_grade: str
    race_type: str
    distance: int
    bank_type: str
    racers: List[Racer]
    line_formations: List[LineFormation]
    race_datetime: datetime
    deadline: datetime
    weather: WeatherInfo = field(default_factory=WeatherInfo)
    odds: OddsInfo = field(default_factory=OddsInfo)
    race_url: str = ""


class KeirinScraper:
    """楽天Kドリームス スクレイパー v2.0"""
    
    BASE_URL = "https://keirin.kdreams.jp"
    
    VELODROME_CODES = {
        "函館": "01", "青森": "02", "いわき平": "03", "弥彦": "04",
        "前橋": "05", "取手": "06", "宇都宮": "07", "大宮": "08",
        "西武園": "09", "京王閣": "10", "立川": "11", "松戸": "12",
        "千葉": "13", "川崎": "14", "平塚": "15", "小田原": "16",
        "伊東": "17", "静岡": "18", "名古屋": "19", "岐阜": "20",
        "大垣": "21", "豊橋": "22", "富山": "23", "松阪": "24",
        "四日市": "25", "福井": "26", "奈良": "27", "向日町": "28",
        "和歌山": "29", "岸和田": "30", "玉野": "31", "広島": "32",
        "防府": "33", "高松": "34", "小松島": "35", "高知": "36",
        "松山": "37", "小倉": "38", "久留米": "39", "武雄": "40",
        "佐世保": "41", "別府": "42", "熊本": "43"
    }
    
    BANK_TYPES = {
        "33": ["前橋", "小倉"],
        "500": ["宇都宮", "大宮", "京王閣"],
    }
    
    # 屋外バンク一覧（風の影響あり）
    OUTDOOR_BANKS = [
        "函館", "青森", "いわき平", "弥彦", "取手", "宇都宮",
        "千葉", "川崎", "平塚", "小田原", "静岡", "豊橋",
        "富山", "福井", "奈良", "和歌山", "岸和田", "玉野",
        "広島", "防府", "高松", "小松島", "高知", "松山",
        "小倉", "久留米", "武雄", "佐世保", "別府", "熊本"
    ]
    
    def __init__(self, timeout: int = 30):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        self.timeout = timeout
    
    def _get_bank_type(self, velodrome: str) -> str:
        for bank_type, velodromes in self.BANK_TYPES.items():
            if velodrome in velodromes:
                return bank_type
        return "400"
    
    def _is_outdoor(self, velodrome: str) -> bool:
        return velodrome in self.OUTDOOR_BANKS
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _fetch_page(self, url: str) -> BeautifulSoup:
        logger.info(f"Fetching: {url}")
        time.sleep(1.5)
        
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        
        return BeautifulSoup(response.text, "lxml")
    
    def get_weather_info(self, velodrome: str) -> WeatherInfo:
        """天候情報を取得（簡易版：実際はAPIや専用ページから取得）"""
        weather = WeatherInfo()
        
        if not self._is_outdoor(velodrome):
            weather.weather = "屋内"
            weather.wind_speed = 0.0
            weather.wind_direction = "なし"
            return weather
        
        # 実際の実装では天気APIを使用
        # ここではダミーデータを返す
        weather.weather = "晴"
        weather.temperature = 15.0
        weather.wind_speed = 3.5
        weather.wind_direction = "北"
        weather.track_condition = "良"
        
        return weather
    
    def get_odds(self, race_url: str) -> OddsInfo:
        """オッズ情報を取得"""
        odds = OddsInfo()
        
        try:
            odds_url = race_url.replace("/race/", "/odds/")
            soup = self._fetch_page(odds_url)
            
            # 3連単オッズ
            sanrentan_table = soup.select_one(".odds-3rentan, .sanrentan-odds")
            if sanrentan_table:
                rows = sanrentan_table.select("tr")
                for row in rows:
                    combo_elem = row.select_one(".combination, .kumiban")
                    odds_elem = row.select_one(".odds, .odds-value")
                    if combo_elem and odds_elem:
                        combo = combo_elem.get_text(strip=True).replace("−", "-")
                        try:
                            odds_val = float(odds_elem.get_text(strip=True).replace(",", ""))
                            odds.sanrentan[combo] = odds_val
                        except ValueError:
                            pass
            
            # 2車単オッズ
            nirentan_table = soup.select_one(".odds-2rentan, .nirentan-odds")
            if nirentan_table:
                rows = nirentan_table.select("tr")
                for row in rows:
                    combo_elem = row.select_one(".combination, .kumiban")
                    odds_elem = row.select_one(".odds, .odds-value")
                    if combo_elem and odds_elem:
                        combo = combo_elem.get_text(strip=True).replace("−", "-")
                        try:
                            odds_val = float(odds_elem.get_text(strip=True).replace(",", ""))
                            odds.nirentan[combo] = odds_val
                        except ValueError:
                            pass
            
            # ワイドオッズ
            wide_table = soup.select_one(".odds-wide, .wide-odds")
            if wide_table:
                rows = wide_table.select("tr")
                for row in rows:
                    combo_elem = row.select_one(".combination, .kumiban")
                    odds_elem = row.select_one(".odds, .odds-value")
                    if combo_elem and odds_elem:
                        combo = combo_elem.get_text(strip=True).replace("−", "-")
                        try:
                            odds_val = float(odds_elem.get_text(strip=True).replace(",", ""))
                            odds.wide[combo] = odds_val
                        except ValueError:
                            pass
            
            logger.info(f"Odds fetched: {len(odds.sanrentan)} 3rentan combinations")
            
        except Exception as e:
            logger.warning(f"Failed to get odds: {e}")
        
        return odds
    
    def get_race_schedule(self, date: Optional[datetime] = None) -> List[Dict]:
        """指定日のレース一覧を取得"""
        if date is None:
            date = datetime.now()
        
        date_str = date.strftime("%Y%m%d")
        url = f"{self.BASE_URL}/race/schedule/{date_str}/"
        
        try:
            soup = self._fetch_page(url)
            races = []
            
            race_tables = soup.select(".race-schedule-table, .raceCard, .race-list")
            
            for table in race_tables:
                velodrome_elem = table.select_one(".velodrome-name, .stadium-name, .jyo-name")
                if not velodrome_elem:
                    continue
                    
                velodrome = velodrome_elem.get_text(strip=True)
                
                race_links = table.select("a[href*='/race/']")
                for link in race_links:
                    href = link.get("href", "")
                    if "/race/" in href:
                        races.append({
                            "velodrome": velodrome,
                            "url": self.BASE_URL + href if href.startswith("/") else href,
                            "date": date_str
                        })
            
            logger.info(f"Found {len(races)} races for {date_str}")
            return races
            
        except Exception as e:
            logger.error(f"Failed to get race schedule: {e}")
            return []
    
    def get_race_detail(self, race_url: str, fetch_odds: bool = True) -> Optional[RaceInfo]:
        """レース詳細情報を取得"""
        try:
            soup = self._fetch_page(race_url)
            
            race_header = soup.select_one(".race-header, .raceHeader, .race-info")
            if not race_header:
                logger.warning(f"Race header not found: {race_url}")
                return None
            
            velodrome_elem = race_header.select_one(".velodrome, .stadium, .jyo")
            velodrome = velodrome_elem.get_text(strip=True) if velodrome_elem else "不明"
            
            race_num_elem = race_header.select_one(".race-number, .raceNo")
            race_number = 1
            if race_num_elem:
                match = re.search(r"(\d+)", race_num_elem.get_text(strip=True))
                if match:
                    race_number = int(match.group(1))
            
            grade_elem = race_header.select_one(".grade, .race-grade")
            race_grade = grade_elem.get_text(strip=True) if grade_elem else "FII"
            
            distance_elem = race_header.select_one(".distance, .kyori")
            distance = 2000
            if distance_elem:
                match = re.search(r"(\d+)", distance_elem.get_text(strip=True))
                if match:
                    distance = int(match.group(1))
            
            racers = self._parse_racers(soup)
            line_formations = self._parse_line_formations(soup)
            weather = self.get_weather_info(velodrome)
            
            odds = OddsInfo()
            if fetch_odds:
                odds = self.get_odds(race_url)
            
            race_info = RaceInfo(
                race_id=f"{velodrome}_{race_number}_{datetime.now().strftime('%Y%m%d')}",
                velodrome=velodrome,
                velodrome_code=self.VELODROME_CODES.get(velodrome, "00"),
                race_number=race_number,
                race_grade=race_grade,
                race_type="予選",
                distance=distance,
                bank_type=self._get_bank_type(velodrome),
                racers=racers,
                line_formations=line_formations,
                race_datetime=datetime.now(),
                deadline=datetime.now(),
                weather=weather,
                odds=odds,
                race_url=race_url
            )
            
            return race_info
            
        except Exception as e:
            logger.error(f"Failed to get race detail: {e}")
            return None
    
    def _parse_racers(self, soup: BeautifulSoup) -> List[Racer]:
        """出走表から選手情報を解析"""
        racers = []
        
        racer_table = soup.select_one(".shutsuhyo, .race-table, .playerTable, .entry-table")
        if not racer_table:
            logger.warning("Racer table not found")
            return racers
        
        rows = racer_table.select("tr.racer-row, tbody tr, .player-row")
        
        for idx, row in enumerate(rows, start=1):
            try:
                cells = row.select("td")
                if len(cells) < 3:
                    continue
                
                waku_elem = row.select_one(".waku, .frame-number, .waku-num")
                waku = int(waku_elem.get_text(strip=True)) if waku_elem else idx
                
                name_elem = row.select_one(".racer-name, .player-name, a.name")
                name = name_elem.get_text(strip=True) if name_elem else "不明"
                
                racer_id = ""
                if name_elem and name_elem.get("href"):
                    match = re.search(r"/player/(\d+)", name_elem.get("href", ""))
                    if match:
                        racer_id = match.group(1)
                
                age_elem = row.select_one(".age")
                age = 30
                if age_elem:
                    match = re.search(r"(\d+)", age_elem.get_text())
                    if match:
                        age = int(match.group(1))
                
                pref_elem = row.select_one(".prefecture, .pref, .pref-name")
                prefecture = pref_elem.get_text(strip=True) if pref_elem else ""
                
                rank_elem = row.select_one(".rank, .class, .kyu")
                rank = rank_elem.get_text(strip=True) if rank_elem else "A3"
                
                score_elem = row.select_one(".score, .point, .kyoso-score")
                score = 0.0
                if score_elem:
                    try:
                        score = float(score_elem.get_text(strip=True))
                    except ValueError:
                        pass
                
                gear_elem = row.select_one(".gear, .gear-ratio")
                gear_ratio = gear_elem.get_text(strip=True) if gear_elem else "3.92"
                
                comment_elem = row.select_one(".comment, .player-comment")
                comment = comment_elem.get_text(strip=True) if comment_elem else ""
                
                # 直近成績
                recent_elem = row.select_one(".recent, .recent-results")
                recent_results = []
                if recent_elem:
                    recent_text = recent_elem.get_text(strip=True)
                    recent_results = re.findall(r"\d", recent_text)
                
                racer = Racer(
                    waku=waku,
                    name=name,
                    racer_id=racer_id,
                    age=age,
                    prefecture=prefecture,
                    rank=rank,
                    score=score,
                    gear_ratio=gear_ratio,
                    comment=comment,
                    recent_results=recent_results
                )
                racers.append(racer)
                
            except Exception as e:
                logger.warning(f"Failed to parse racer row: {e}")
                continue
        
        return racers
    
    def _parse_line_formations(self, soup: BeautifulSoup) -> List[LineFormation]:
        """ライン編成を解析"""
        formations = []
        
        line_section = soup.select_one(".line-info, .narabi, .formation, .line-prediction")
        if not line_section:
            logger.warning("Line formation section not found")
            return formations
        
        line_items = line_section.select(".line-item, .line-group, li, .line-row")
        
        for item in line_items:
            try:
                member_elems = item.select(".member, .waku-number, span.waku, .frame")
                members = []
                for elem in member_elems:
                    text = elem.get_text(strip=True)
                    match = re.search(r"(\d)", text)
                    if match:
                        members.append(int(match.group(1)))
                
                if not members:
                    text = item.get_text(strip=True)
                    members = [int(x) for x in re.findall(r"\d", text)]
                
                if not members:
                    continue
                
                strategy_elem = item.select_one(".strategy, .tactics, .senpou")
                strategy = strategy_elem.get_text(strip=True) if strategy_elem else "自在"
                
                formation = LineFormation(
                    line_members=members,
                    strategy=strategy
                )
                formations.append(formation)
                
            except Exception as e:
                logger.warning(f"Failed to parse line formation: {e}")
                continue
        
        return formations
    
    def get_race_result(self, race_url: str) -> Optional[Dict]:
        """レース結果を取得"""
        result_url = race_url.replace("/race/", "/result/")
        
        try:
            soup = self._fetch_page(result_url)
            
            result = {
                "finish_order": [],
                "winning_pattern": "",
                "payouts": {},
                "race_time": "",
                "last_3f": ""
            }
            
            order_table = soup.select_one(".result-table, .finish-order, .chakujun")
            if order_table:
                order_rows = order_table.select("tr")
                for row in order_rows:
                    waku_elem = row.select_one(".waku, .frame, .wakuban")
                    if waku_elem:
                        match = re.search(r"(\d)", waku_elem.get_text())
                        if match:
                            result["finish_order"].append(int(match.group(1)))
            
            pattern_elem = soup.select_one(".winning-pattern, .kimarite, .kime-te")
            if pattern_elem:
                result["winning_pattern"] = pattern_elem.get_text(strip=True)
            
            payout_table = soup.select_one(".payout-table, .haraimodoshi, .payout")
            if payout_table:
                payout_rows = payout_table.select("tr")
                for row in payout_rows:
                    bet_type_elem = row.select_one(".bet-type, th, .shikibetsu")
                    amount_elem = row.select_one(".amount, .payout, td.yen")
                    combo_elem = row.select_one(".combination, .kumiban")
                    
                    if bet_type_elem and amount_elem:
                        bet_type = bet_type_elem.get_text(strip=True)
                        amount_text = amount_elem.get_text(strip=True)
                        match = re.search(r"([\d,]+)", amount_text)
                        if match:
                            amount = int(match.group(1).replace(",", ""))
                            combo = combo_elem.get_text(strip=True) if combo_elem else ""
                            result["payouts"][bet_type] = {
                                "amount": amount,
                                "combination": combo
                            }
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get race result: {e}")
            return None


def create_demo_race_info() -> RaceInfo:
    """デモ用のレースデータを作成"""
    racers = [
        Racer(1, "山田太郎", "12345", 32, "埼玉", "S1", 117.5, "3.92", 
              "今日は先行一本。信頼して付いてきてほしい", ["1", "2", "1", "3"]),
        Racer(2, "佐藤次郎", "12346", 28, "埼玉", "S1", 115.2, "3.92", 
              "山田さんの番手から", ["2", "1", "2", "2"]),
        Racer(3, "鈴木三郎", "12347", 35, "群馬", "S2", 112.3, "3.93", 
              "自力で勝負する", ["3", "4", "2", "1"]),
        Racer(4, "田中四郎", "12348", 30, "東京", "A1", 108.7, "3.92", 
              "位置取りを大事にしたい", ["4", "3", "5", "2"]),
        Racer(5, "伊藤五郎", "12349", 26, "神奈川", "A1", 110.1, "3.92", 
              "脚を溜めて直線勝負", ["2", "2", "3", "4"]),
        Racer(6, "渡辺六郎", "12350", 33, "静岡", "A2", 105.4, "3.93", 
              "捲り一発狙い", ["5", "6", "4", "3"]),
        Racer(7, "中村七郎", "12351", 29, "愛知", "S2", 113.8, "3.92", 
              "鈴木さんに付いていく", ["3", "2", "2", "1"]),
        Racer(8, "小林八郎", "12352", 31, "大阪", "A1", 107.2, "3.92", 
              "展開次第で動く", ["4", "5", "3", "5"]),
        Racer(9, "山本九郎", "12353", 27, "福岡", "A2", 104.9, "3.93", 
              "後方待機で差し狙い", ["6", "4", "5", "4"]),
    ]
    
    line_formations = [
        LineFormation([1, 2, 4], "先行", "関東ライン", 0.85),
        LineFormation([3, 7], "捲り", "北関東ライン", 0.70),
        LineFormation([5, 8], "追込", "南関東ライン", 0.60),
        LineFormation([6, 9], "捲り", "混成ライン", 0.50),
    ]
    
    weather = WeatherInfo(
        weather="晴",
        temperature=18.0,
        humidity=45.0,
        wind_direction="北",
        wind_speed=2.5,
        track_condition="良"
    )
    
    odds = OddsInfo(
        sanrentan={"1-2-4": 8.5, "1-2-7": 12.3, "1-4-2": 15.6, "2-1-4": 18.2, "3-7-1": 45.0},
        nirentan={"1-2": 3.2, "1-4": 5.8, "2-1": 4.5, "3-7": 12.0},
        wide={"1-2": 1.5, "1-4": 2.3, "2-4": 3.1}
    )
    
    return RaceInfo(
        race_id="maebashi_11_20241216",
        velodrome="前橋",
        velodrome_code="05",
        race_number=11,
        race_grade="GI",
        race_type="決勝",
        distance=2025,
        bank_type="33",
        racers=racers,
        line_formations=line_formations,
        race_datetime=datetime.now(),
        deadline=datetime.now(),
        weather=weather,
        odds=odds,
        race_url="https://keirin.kdreams.jp/maebashi/race/11/"
    )


def create_demo_result() -> Dict:
    """デモ用のレース結果"""
    return {
        "finish_order": [1, 2, 4, 7, 3, 5, 8, 6, 9],
        "winning_pattern": "逃げ",
        "payouts": {
            "3連単": {"amount": 850, "combination": "1-2-4"},
            "3連複": {"amount": 320, "combination": "1-2-4"},
            "2車単": {"amount": 320, "combination": "1-2"},
            "2車複": {"amount": 180, "combination": "1-2"},
            "ワイド": {"amount": 150, "combination": "1-2"}
        },
        "race_time": "1:52.3",
        "last_3f": "11.2"
    }


if __name__ == "__main__":
    demo_race = create_demo_race_info()
    print(f"Race: {demo_race.velodrome} {demo_race.race_number}R ({demo_race.bank_type}バンク)")
    print(f"Weather: {demo_race.weather.weather}, Wind: {demo_race.weather.wind_direction} {demo_race.weather.wind_speed}m/s")
    print("\n--- 出走表 ---")
    for racer in demo_race.racers:
        print(f"{racer.waku}枠 {racer.name} ({racer.rank}) 得点:{racer.score}")
    print("\n--- オッズ（3連単上位5つ） ---")
    for combo, odds in list(demo_race.odds.sanrentan.items())[:5]:
        print(f"  {combo}: {odds}倍")
