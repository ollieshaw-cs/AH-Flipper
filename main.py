import json
import asyncio
import aiohttp
import time
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
# OPTIMIZED HELPER FUNCTIONS
# -----------------------------

# Cache clean_name results
_name_cache: Dict[str, str] = {}

def clean_name(name: str) -> str:
    if name in _name_cache:
        return _name_cache[name]
    
    # Use translation table for character removal (faster than replace in loop)
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

# -----------------------------
# OPTIMIZED SKYBLOCK ID DECODER
# -----------------------------

_tag_cache: Dict[str, Optional[str]] = {}

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

# Batch processing for item IDs
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
                elif resp.status == 429:  # Rate limited
                    await asyncio.sleep(1)
                    return []
                else:
                    return []
        except Exception:
            return []

async def fetch_bins_async() -> Dict[str, List[Dict[str, Any]]]:
    grouped = defaultdict(list)
    
    # More conservative limits to avoid rate limiting
    connector = TCPConnector(limit=50, limit_per_host=10, keepalive_timeout=30)
    timeout = aiohttp.ClientTimeout(total=120, sock_connect=10, sock_read=20)
    
    async with ClientSession(connector=connector, timeout=timeout) as session:
        # Get total pages first
        async with session.get("https://api.hypixel.net/v2/skyblock/auctions") as meta_resp:
            meta = await meta_resp.json()
            total_pages = meta.get("totalPages", 0)

        # Use semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(15)  # Reduced concurrency
        
        # Fetch all pages with better error handling
        tasks = []
        for i in range(total_pages):
            task = fetch_page(session, i, semaphore)
            tasks.append(task)
            
            # Small delay to avoid overwhelming the API
            if i % 10 == 0:
                await asyncio.sleep(0.01)

        all_pages = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process pages as they complete
        all_auctions = []
        for page in all_pages:
            if isinstance(page, list):
                all_auctions.extend(page)

        # Early filtering to reduce data processing
        filtered_auctions = []
        for auc in all_auctions:
            if auc.get("bin") and auc.get("category") in ALLOWED_CATEGORIES:
                filtered_auctions.append(auc)

        # Process in smaller chunks with batch item ID decoding
        CHUNK_SIZE = 500  # Smaller chunks for better memory usage
        
        for i in range(0, len(filtered_auctions), CHUNK_SIZE):
            chunk = filtered_auctions[i:i + CHUNK_SIZE]
            item_bytes_chunk = [auc.get("item_bytes") for auc in chunk]
            
            # Process item IDs in batches
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=4) as executor:
                item_ids = await loop.run_in_executor(
                    executor, get_item_ids_batch, item_bytes_chunk
                )
            
            # Process the chunk
            for auc, item_id in zip(chunk, item_ids):
                full_name = auc.get("item_name")
                display_name = clean_name(full_name)
                price = auc.get("starting_bid")
                uuid = auc.get("uuid")

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
# OPTIMIZED DAILY VOLUME FETCHING
# -----------------------------

# Cache for daily volumes to avoid repeated API calls
_volume_cache: Dict[str, tuple[float, float]] = {}  # item_id -> (volume, timestamp)
VOLUME_CACHE_TTL = 300  # 5 minutes

async def get_avg_daily_volume(session: ClientSession, item_id: str) -> Optional[float]:
    now = time.time()
    
    # Check cache first
    if item_id in _volume_cache:
        volume, timestamp = _volume_cache[item_id]
        if now - timestamp < VOLUME_CACHE_TTL:
            return volume
    
    try:
        url = f"https://sky.coflnet.com/api/item/price/{item_id}/history/day"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, list) and len(data) > 0:
                    volume = sum(hour.get("volume", 0) for hour in data) / len(data)
                    _volume_cache[item_id] = (volume, now)
                    return volume
            return 0.0
    except Exception:
        return None

# -----------------------------
# OPTIMIZED FLIP FINDER
# -----------------------------

# Use deque with maxlen to automatically limit memory usage
sent_uuids = deque(maxlen=10000)

async def find_flips():
    print("[Flip Finder] Running scan…")
    start_time = time.time()

    groups = await fetch_bins_async()
    fetch_time = time.time() - start_time
    print(f"[API] Fetched {sum(len(v) for v in groups.values()):,} bins in {fetch_time:.2f}s")

    # Early exit if no data
    if not groups:
        print("No auction data found")
        return

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        tasks = []
        valid_items = []
        
        # Pre-filter items before making API calls
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

        # Fetch volumes concurrently
        volumes = await asyncio.gather(*tasks)
        
        # Process results
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
# OPTIMIZED MAIN LOOP
# -----------------------------

cooldown = 10
min_sleep = 2

async def main_loop():
    while True:
        loop_start = time.time()
        await find_flips()
        elapsed = time.time() - loop_start
        sleep_time = max(min_sleep, cooldown - elapsed)
        print(f"Waiting {sleep_time:.1f} seconds before searching again\n")
        await asyncio.sleep(sleep_time)

if __name__ == "__main__":
    asyncio.run(main_loop())