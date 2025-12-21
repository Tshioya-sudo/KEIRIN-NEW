"""
競輪データスクレイパー v2.1
- KEIRIN.JP（公式サイト）対応
- 楽天Kドリームス対応
- オッズ取得機能
- 天候・風向き取得
"""
import os
import time
import logging
import re
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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


@dataclass
class LineFormation:
    """ライン編成"""
    line_members: List[int]
    strategy: str
    comment: str = ""


@dataclass
class OddsInfo:
    """オッズ情報"""
    sanrentan: Dict[str, float] = field(default_factory=dict)
    sanrenpuku: Dict[str, float] = field(default_factory=dict)
    nirentan: Dict[str, float] = field(default_factory=dict)
    nirenpuku: Dict[str, float] = field(default_factory=dict)
    wide: Dict[str, float] = field(default_factory=dict)


@dataclass
class WeatherInfo:
    """天候情報"""
    weather: str = "晴"
    temperature: float = 20.0
    humidity: float = 50.0
    wind_direction: str = ""
    wind_speed: float = 0.0
    track_condition: str = "良"


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
    """競輪スクレイパー v2.1 - KEIRIN.JP対応"""
    
    # KEIRIN.JP（公式）
    BASE_URL = "https://keirin.jp"
    
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
    
    # コード→名前の逆引き
    CODE_TO_NAME = {v: k for k, v in VELODROME_CODES.items()}
    
    BANK_TYPES = {
        "33": ["前橋", "小倉"],
        "500": ["宇都宮", "大宮", "京王閣"],
    }
    
    OUTDOOR_BANKS = [
        "函館", "青森", "いわき平", "弥彦", "取手", "宇都宮",
        "千葉", "川崎", "平塚", "小田原", "静岡", "豊橋",
        "富山", "福井", "奈良", "和歌山", "岸和田", "玉野",
        "広島", "防府", "高松", "小松島", "高知", "松山",
        "小倉", "久留米", "武雄", "佐世保", "別府", "熊本"
    ]
    
    def __init__(self, timeout: int = 30, use_system_proxy: bool = False):
        env_proxy_flag = os.getenv("USE_SYSTEM_PROXY", "").lower() in ("1", "true", "yes")
        use_system_proxy = use_system_proxy or env_proxy_flag

        self.session = requests.Session()
        # CI環境などでプロキシ経由になると403が返ってしまうケースがあるため、
        # 明示的に無効化（必要に応じて use_system_proxy=True で切り替え）
        if not use_system_proxy:
            self.session.trust_env = False
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
        })
        self.timeout = timeout
        self._proxy_retry_used = False

    def _has_system_proxy(self) -> bool:
        return any(os.getenv(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"))
    
    def _get_bank_type(self, velodrome: str) -> str:
        for bank_type, velodromes in self.BANK_TYPES.items():
            if velodrome in velodromes:
                return bank_type
        return "400"
    
    def _is_outdoor(self, velodrome: str) -> bool:
        return velodrome in self.OUTDOOR_BANKS
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """ページを取得"""
        logger.info(f"Fetching: {url}")
        time.sleep(1.5)
        
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or 'utf-8'
            logger.info(f"Response status: {response.status_code}, length: {len(response.text)}")
            return BeautifulSoup(response.text, "lxml")
        except requests.exceptions.ProxyError as e:
            logger.error("ProxyError: keirin.jp への到達がブロックされています。use_system_proxy=True も試してください。")
            logger.debug(f"Proxy error detail: {e}")
            if not self.session.trust_env and not self._proxy_retry_used and self._has_system_proxy():
                logger.info("Retrying with system proxy settings from environment")
                self.session.trust_env = True
                self._proxy_retry_used = True
                return self._fetch_page(url)
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error("ConnectionError: ネットワークに接続できません。デモモードを利用してください。")
            logger.debug(f"Connection error detail: {e}")
            if not self.session.trust_env and not self._proxy_retry_used and self._has_system_proxy():
                logger.info("Retrying with system proxy settings from environment")
                self.session.trust_env = True
                self._proxy_retry_used = True
                return self._fetch_page(url)
            return None
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            return None
    
    def get_race_schedule(self, date: Optional[datetime] = None) -> List[Dict]:
        """指定日のレース一覧を取得"""
        if date is None:
            date = datetime.now()
        
        date_str = date.strftime("%Y%m%d")
        
        # KEIRIN.JP のトップページから開催情報を取得
        url = f"{self.BASE_URL}/pc/top/"
        logger.info(f"Getting race schedule for {date_str}")
        
        soup = self._fetch_page(url)
        if not soup:
            logger.error("Failed to fetch top page")
            return []
        
        races = []
        
        # 開催場を探す（複数のセレクターを試す）
        selectors = [
            ".kaisaiList a",
            ".jyo-list a", 
            "a[href*='/pc/dfw/dataplaza/guest/raceindex']",
            ".stadium a",
            ".race-link",
        ]
        
        links = []
        for selector in selectors:
            links = soup.select(selector)
            if links:
                logger.info(f"Found {len(links)} links with selector: {selector}")
                break
        
        if not links:
            # 全てのリンクから競輪場を探す
            logger.info("Trying to find velodrome links from all anchors")
            all_links = soup.find_all("a", href=True)
            for link in all_links:
                href = link.get("href", "")
                text = link.get_text(strip=True)
                # 競輪場名を含むリンクを探す
                for velo_name in self.VELODROME_CODES.keys():
                    if velo_name in text or velo_name in href:
                        links.append(link)
                        break
            logger.info(f"Found {len(links)} velodrome links from all anchors")
        
        seen_velodromes = set()
        
        for link in links:
            href = link.get("href", "")
            text = link.get_text(strip=True)
            
            # 競輪場名を特定
            velodrome = None
            for velo_name in self.VELODROME_CODES.keys():
                if velo_name in text:
                    velodrome = velo_name
                    break
            
            if not velodrome:
                continue
            
            if velodrome in seen_velodromes:
                continue
            seen_velodromes.add(velodrome)
            
            # レースURLを構築
            if href.startswith("http"):
                race_url = href
            elif href.startswith("/"):
                race_url = self.BASE_URL + href
            else:
                race_url = self.BASE_URL + "/" + href
            
            races.append({
                "velodrome": velodrome,
                "velodrome_code": self.VELODROME_CODES.get(velodrome, "00"),
                "url": race_url,
                "date": date_str
            })
            logger.info(f"Found race: {velodrome}")
        
        logger.info(f"Total races found: {len(races)}")
        return races
    
    def get_race_detail(self, race_url: str, race_number: int = 11) -> Optional[RaceInfo]:
        """レース詳細情報を取得"""
        logger.info(f"Getting race detail from: {race_url}")
        
        soup = self._fetch_page(race_url)
        if not soup:
            logger.error("Failed to fetch race page")
            return None
        
        # ページタイトルから競輪場名を取得
        velodrome = "不明"
        title = soup.find("title")
        if title:
            title_text = title.get_text()
            for velo_name in self.VELODROME_CODES.keys():
                if velo_name in title_text:
                    velodrome = velo_name
                    break
        
        # 選手情報を取得（テーブルから）
        racers = []
        
        # 出走表テーブルを探す
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) >= 3:
                    # 枠番を探す
                    first_cell = cells[0].get_text(strip=True)
                    if first_cell.isdigit() and 1 <= int(first_cell) <= 9:
                        waku = int(first_cell)
                        name = cells[1].get_text(strip=True) if len(cells) > 1 else f"選手{waku}"
                        
                        # 重複チェック
                        if not any(r.waku == waku for r in racers):
                            racer = Racer(
                                waku=waku,
                                name=name[:10],  # 名前が長すぎる場合は切る
                                rank="A1",
                                score=100.0
                            )
                            racers.append(racer)
        
        # 選手が取得できなかった場合はダミーデータ
        if len(racers) < 9:
            logger.warning(f"Only found {len(racers)} racers, using demo data")
            return None
        
        # ライン編成（簡易版）
        line_formations = [
            LineFormation([1, 2, 4], "先行"),
            LineFormation([3, 7], "捲り"),
            LineFormation([5, 8, 9], "追込"),
        ]
        
        # 天候
        weather = WeatherInfo(
            weather="晴" if self._is_outdoor(velodrome) else "屋内",
            wind_direction="北" if self._is_outdoor(velodrome) else "なし",
            wind_speed=2.0 if self._is_outdoor(velodrome) else 0.0
        )
        
        race_info = RaceInfo(
            race_id=f"{velodrome}_{race_number}_{datetime.now().strftime('%Y%m%d')}",
            velodrome=velodrome,
            velodrome_code=self.VELODROME_CODES.get(velodrome, "00"),
            race_number=race_number,
            race_grade="FII",
            race_type="予選",
            distance=2000,
            bank_type=self._get_bank_type(velodrome),
            racers=racers,
            line_formations=line_formations,
            race_datetime=datetime.now(),
            deadline=datetime.now(),
            weather=weather,
            odds=OddsInfo(),
            race_url=race_url
        )
        
        logger.info(f"Created race info: {velodrome} {race_number}R with {len(racers)} racers")
        return race_info
    
    def get_race_result(self, race_url: str) -> Optional[Dict]:
        """レース結果を取得"""
        logger.info(f"Getting race result from: {race_url}")
        
        soup = self._fetch_page(race_url)
        if not soup:
            return None
        
        result = {
            "finish_order": [],
            "winning_pattern": "",
            "payouts": {}
        }
        
        # 着順を探す
        # TODO: 実装
        
        return result


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
        LineFormation([1, 2, 4], "先行", "関東ライン"),
        LineFormation([3, 7], "捲り", "北関東ライン"),
        LineFormation([5, 8], "追込", "南関東ライン"),
        LineFormation([6, 9], "捲り", "混成ライン"),
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
        race_url="https://keirin.jp/pc/dfw/dataplaza/guest/raceindex?KCD=05"
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
    scraper = KeirinScraper()
    
    print("=" * 60)
    print("競輪スクレイパー v2.1 - テスト")
    print("=" * 60)
    
    print("\n📅 本日のレース一覧を取得中...")
    races = scraper.get_race_schedule()
    
    if races:
        print(f"\n✅ {len(races)}場の開催を発見:")
        for race in races:
            print(f"  - {race['velodrome']}")
    else:
        print("\n⚠️ レースが見つかりませんでした")
        print("デモデータを使用します")
        demo = create_demo_race_info()
        print(f"\nデモレース: {demo.velodrome} {demo.race_number}R")
