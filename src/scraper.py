diff --git a/src/scraper.py b/src/scraper.py
index 2a7f3c5b09b34b037aecfdbdb30605251971c3a8..cff332ba7d0c2aa0b40b420025f1165acd404e49 100644
--- a/src/scraper.py
+++ b/src/scraper.py
@@ -1,32 +1,33 @@
 """
 競輪データスクレイパー v2.1
 - KEIRIN.JP（公式サイト）対応
 - 楽天Kドリームス対応
 - オッズ取得機能
 - 天候・風向き取得
 """
+import os
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
@@ -98,80 +99,109 @@ class KeirinScraper:
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
     
-    def __init__(self, timeout: int = 30):
+    def __init__(self, timeout: int = 30, use_system_proxy: bool = False):
+        env_proxy_flag = os.getenv("USE_SYSTEM_PROXY", "").lower() in ("1", "true", "yes")
+        use_system_proxy = use_system_proxy or env_proxy_flag
+
         self.session = requests.Session()
+        # CI環境などでプロキシ経由になると403が返ってしまうケースがあるため、
+        # 明示的に無効化（必要に応じて use_system_proxy=True で切り替え）
+        if not use_system_proxy:
+            self.session.trust_env = False
         self.session.headers.update({
             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
             "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
             "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
         })
         self.timeout = timeout
+        self._proxy_retry_used = False
+
+    def _has_system_proxy(self) -> bool:
+        return any(os.getenv(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"))
     
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
+        except requests.exceptions.ProxyError as e:
+            logger.error("ProxyError: keirin.jp への到達がブロックされています。use_system_proxy=True も試してください。")
+            logger.debug(f"Proxy error detail: {e}")
+            if not self.session.trust_env and not self._proxy_retry_used and self._has_system_proxy():
+                logger.info("Retrying with system proxy settings from environment")
+                self.session.trust_env = True
+                self._proxy_retry_used = True
+                return self._fetch_page(url)
+            return None
+        except requests.exceptions.ConnectionError as e:
+            logger.error("ConnectionError: ネットワークに接続できません。デモモードを利用してください。")
+            logger.debug(f"Connection error detail: {e}")
+            if not self.session.trust_env and not self._proxy_retry_used and self._has_system_proxy():
+                logger.info("Retrying with system proxy settings from environment")
+                self.session.trust_env = True
+                self._proxy_retry_used = True
+                return self._fetch_page(url)
+            return None
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
