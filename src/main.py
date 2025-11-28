import json
import asyncio
import aiohttp
import time
import os
import gzip
import atexit

from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Any, Optional, Set
from NBT_Decoder import ItemDecoder
from discord_notify import DiscordNotifier
from aiohttp import ClientSession, TCPConnector

# -----------------------------
# CONFIG AND SETTINGS
# -----------------------------

def parseSettingsValue(v: str) -> int:
    return int(v.replace(",", ""))

with open("Settings.json", "r") as file:
    data = json.load(file)

ALLOWED_CATEGORIES = set(data["ALLOWED_CATEGORIES"])
WEBHOOK_URL = data["WEBHOOK_URL"]

MIN_PROFIT = parseSettingsValue(data["MIN_PROFIT"])
MAX_COST = parseSettingsValue(data["MAX_COST"])
MIN_LISTINGS = parseSettingsValue(data["MIN_LISTINGS"])
MIN_DAILY_VOLUME = parseSettingsValue(data["MIN_DAILY_VOLUME"])

notifier = DiscordNotifier(WEBHOOK_URL)

with open("Reforges.json", "r") as f:
    REFORGES = set(json.load(f).get("Reforges", []))

# -----------------------------
# PERSISTENT CACHES
# -----------------------------

_name_cache: Dict[str, str] = {}
_tag_cache: Dict[str, Optional[str]] = {}

name_cache_path = "Cache\\name_cache.json"
tag_cache_path = "Cache\\tag_cache"

def load_caches():
    # --- load name cache ---
    if os.path.exists(name_cache_path):
        try:
            with open(name_cache_path, "r") as f:
                _name_cache.update(json.load(f))
            print(f"[Cache] Loaded {_name_cache.__len__():,} names")
        except:
            print("[Cache] Failed to load name_cache.json")
    else:
        print(f"{name_cache_path} doesn't exist")

    # --- load tag cache (gzip) ---
    gz_path = tag_cache_path + ".gz"
    if os.path.exists(gz_path):
        try:
            with gzip.open(gz_path, "rt", encoding="utf-8") as f:
                _tag_cache.update(json.load(f))
            print(f"[Cache] Loaded {_tag_cache.__len__():,} tags")
        except:
            print("[Cache] Failed to load tag_cache.json.gz")
    else:
        print(f"{gz_path} doesn't exist")


def save_caches():
    try:
        with open(name_cache_path, "w") as f:
            json.dump(_name_cache, f)
        with gzip.open(tag_cache_path + ".gz", "wt", encoding="utf-8") as f:
            json.dump(_tag_cache, f)
        print("[Cache] Saved caches")
    except Exception as e:
        print(f"[Cache] Failed to save caches: {e}")

# Save on shutdown
atexit.register(save_caches)

# Load on startup
load_caches()

async def auto_save_cache_task():
    while True:
        await asyncio.sleep(300)
        save_caches()

# -----------------------------
# OPTIMIZED HELPER FUNCTIONS
# -----------------------------

def clean_name(name: str) -> str:
    if name in _name_cache:
        return _name_cache[name]
    
    if not hasattr(clean_name, 'banned_chars'):
        clean_name.banned_chars = str.maketrans('', '', "✪✿⚚✦➊➋➌➍➎")
    
    name = name.translate(clean_name.banned_chars).strip()

    # remove reforges
    parts = name.split()
    while parts and parts[0] in REFORGES:
        parts.pop(0)
    name = " ".join(parts)

    # perfect armor fix
    hyphen = name.find("-", 5) > 0
    for p in ["Helmet", "Chestplate", "Leggings", "Boots"]:
        if name.startswith(p) and hyphen:
            name = "Perfect " + name
            break

    _name_cache[name] = name
    return name

def get_item_id(item_bytes: Any) -> Optional[str]:
    if item_bytes is None:
        return None
    key = str(item_bytes)
    if key in _tag_cache:
        return _tag_cache[key]
    try:
        decoded = ItemDecoder.decode(item_bytes)
        tag = decoded.get("SkyBlock_id")
    except Exception:
        tag = None
    _tag_cache[key] = tag
    return tag

def get_item_ids_batch(item_bytes_list: List[Any]) -> List[Optional[str]]:
    return [get_item_id(item_bytes) for item_bytes in item_bytes_list]

# -----------------------------
# OPTIMIZED ASYNC AUCTION FETCHING
# -----------------------------

async def fetch_page(session: ClientSession, page: int, semaphore: asyncio.Semaphore) -> List[Dict[str, Any]]:
    async with semaphore:
        try:
            url = f"https://api.hypixel.net/v2/skyblock/auctions?page={page}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("auctions", [])
                elif resp.status == 429:
                    await asyncio.sleep(1)
                    return []
                else:
                    return []
        except Exception:
            return []

async def fetch_bins_async() -> Dict[str, List[Dict[str, Any]]]:
    grouped = defaultdict(list)
    
    connector = TCPConnector(limit=50, limit_per_host=10, keepalive_timeout=30)
    timeout = aiohttp.ClientTimeout(total=120, sock_connect=10, sock_read=20)
    
    async with ClientSession(connector=connector, timeout=timeout) as session:
        async with session.get("https://api.hypixel.net/v2/skyblock/auctions") as meta_resp:
            meta = await meta_resp.json()
            total_pages = meta.get("totalPages", 0)

        semaphore = asyncio.Semaphore(15)
        
        tasks = []
        for i in range(total_pages):
            tasks.append(fetch_page(session, i, semaphore))
            if i % 10 == 0:
                await asyncio.sleep(0.01)

        all_pages = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_auctions = []
        for page in all_pages:
            if isinstance(page, list):
                all_auctions.extend(page)

        filtered_auctions = [
            auc for auc in all_auctions
            if auc.get("bin") and auc.get("category") in ALLOWED_CATEGORIES
        ]

        CHUNK_SIZE = 500
        
        for i in range(0, len(filtered_auctions), CHUNK_SIZE):
            chunk = filtered_auctions[i:i + CHUNK_SIZE]
            item_bytes_chunk = [auc.get("item_bytes") for auc in chunk]
            
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=4) as executor:
                item_ids = await loop.run_in_executor(
                    executor, get_item_ids_batch, item_bytes_chunk
                )
            
            for auc, item_id in zip(chunk, item_ids):
                full_name = auc["item_name"]
                display_name = clean_name(full_name)
                price = auc["starting_bid"]
                uuid = auc["uuid"]

                if not item_id:
                    item_id = f"UNKNOWN::{display_name}"

                entry = {
                    "price": price,
                    "uuid": uuid,
                    "full_name": full_name,
                    "display_name": display_name,
                    "item_bytes": auc.get("item_bytes"),
                    "id": item_id,
                }

                grouped[item_id].append(entry)

    return dict(grouped)

# -----------------------------
# VOLUME FETCHING
# -----------------------------

_volume_cache: Dict[str, tuple[float, float]] = {}
VOLUME_CACHE_TTL = 300 # In Seconds

async def get_avg_daily_volume(session: ClientSession, item_id: str) -> Optional[float]:
    now = time.time()
    if item_id in _volume_cache:
        volume, ts = _volume_cache[item_id]
        if now - ts < VOLUME_CACHE_TTL:
            return volume
    
    try:
        url = f"https://sky.coflnet.com/api/item/price/{item_id}/history/day"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, list) and len(data) > 0:
                    volume = sum(x.get("volume", 0) for x in data) / len(data)
                    _volume_cache[item_id] = (volume, now)
                    return volume
            return 0.0
    except:
        return None

# -----------------------------
# FLIP FINDER
# -----------------------------

sent_uuids = deque(maxlen=10000)

async def find_flips():
    print("\n[Flip Finder] Running scan…")
    start_time = time.time()

    groups = await fetch_bins_async()
    fetch_time = time.time() - start_time
    print(f"[API] Fetched {sum(len(v) for v in groups.values()):,} bins in {fetch_time:.2f}s")

    if not groups:
        print("No auction data found")
        return

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        tasks = []
        valid_items = []
        
        for item_id, auctions in groups.items():
            if len(auctions) < MIN_LISTINGS:
                continue
                
            auctions.sort(key=lambda x: x["price"])
            a1 = auctions[0]
            a2 = auctions[1]

            lowest = a1["price"]
            second = a2["price"]
            profit = second - lowest

            if profit >= MIN_PROFIT and lowest <= MAX_COST:
                uid = a1["uuid"]
                if uid not in sent_uuids:
                    tasks.append(get_avg_daily_volume(session, item_id))
                    valid_items.append((item_id, a1, a2, lowest, second, profit, uid))

        if not valid_items:
            print("No potential flips found")
            return

        volumes = await asyncio.gather(*tasks)
        
        found_flips = 0
        for (item_id, a1, a2, lowest, second, profit, uid), avg_vol in zip(valid_items, volumes):
            if avg_vol is not None and avg_vol >= MIN_DAILY_VOLUME:
                sent_uuids.append(uid)
                found_flips += 1

                print(
                    f"{a1['full_name']} | ID={item_id} | Profit: {profit:,} | "
                    f"Lowest: {lowest:,} | Volume: {avg_vol:.2f} | UUID: {uid}"
                )

                notifier.send_flip(
                    name=a1["full_name"],
                    item_id=item_id,
                    profit=profit,
                    lowest=lowest,
                    secondLowest=second,
                    volume=avg_vol,
                    uuid=f"/viewauction {uid}"
                )

        print(f"Found {found_flips} flips")

# -----------------------------
# MAIN LOOP
# -----------------------------

cooldown = 10
min_sleep = 2

async def main_loop():
    asyncio.create_task(auto_save_cache_task())

    while True:
        loop_start = time.time()
        await find_flips()
        elapsed = time.time() - loop_start
        sleep_time = max(min_sleep, cooldown - elapsed)
        print(f"Waiting {sleep_time:.1f} seconds before searching again")
        await asyncio.sleep(sleep_time)

if __name__ == "__main__":
    asyncio.run(main_loop())
