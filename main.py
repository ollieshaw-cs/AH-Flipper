import json
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Any, Optional
from NBT_Decoder import ItemDecoder
from discord_notify import DiscordNotifier
import time

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
# HELPER FUNCTIONS
# -----------------------------

def clean_name(name: str) -> str:
    banned = ["✪", "✿", "⚚", "✦", "➊", "➋", "➌", "➍", "➎"]
    for c in banned:
        name = name.replace(c, "")
    name = name.strip()

    # remove reforges
    parts = name.split()
    while parts and parts[0] in REFORGES:
        parts.pop(0)
    name = " ".join(parts)

    # perfect armor fix
    hyphen = name.find("-", 5) > 0
    for p in ["Helmet", "Chestplate", "Leggings", "Boots"]:
        if name.startswith(p) and hyphen:
            return "Perfect " + name

    return name

# -----------------------------
# SKYBLOCK ID DECODER (CACHED)
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

# -----------------------------
# ASYNC AUCTION FETCHING
# -----------------------------

async def fetch_page(session: aiohttp.ClientSession, page: int) -> List[Dict[str, Any]]:
    url = f"https://api.hypixel.net/v2/skyblock/auctions?page={page}"
    async with session.get(url) as resp:
        data = await resp.json()
        return data.get("auctions", [])

async def fetch_bins_async() -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    async with aiohttp.ClientSession() as session:
        # Get total pages first
        meta_resp = await session.get("https://api.hypixel.net/v2/skyblock/auctions")
        meta = await meta_resp.json()
        total_pages = meta.get("totalPages", 0)

        # Fetch all pages concurrently
        tasks = [fetch_page(session, i) for i in range(total_pages)]
        all_pages = await asyncio.gather(*tasks)

        # Flatten auctions
        all_auctions = [auc for page in all_pages for auc in page]

        # Decode item_ids in parallel
        item_bytes_list = [auc.get("item_bytes") for auc in all_auctions]
        with ThreadPoolExecutor() as executor:
            item_ids = list(executor.map(get_item_id, item_bytes_list))

        # Process auctions
        for auc, item_id in zip(all_auctions, item_ids):
            if not auc.get("bin"):
                continue
            if auc.get("category") not in ALLOWED_CATEGORIES:
                continue

            full_name = auc.get("item_name")
            display_name = clean_name(full_name)
            price = auc.get("starting_bid")
            uuid = auc.get("uuid")
            item_bytes = auc.get("item_bytes")

            if not item_id:
                item_id = f"UNKNOWN::{display_name}"

            entry = {
                "price": price,
                "uuid": uuid,
                "full_name": full_name,
                "display_name": display_name,
                "item_bytes": item_bytes,
                "id": item_id,
            }

            grouped.setdefault(item_id, []).append(entry)

    return grouped

# -----------------------------
# ASYNC DAILY VOLUME
# -----------------------------

async def get_avg_daily_volume(session: aiohttp.ClientSession, item_id: str) -> Optional[float]:
    try:
        url = f"https://sky.coflnet.com/api/item/price/{item_id}/history/day"
        async with session.get(url) as resp:
            data = await resp.json()
            if not isinstance(data, list) or len(data) == 0:
                return 0.0
            return sum(hour.get("volume", 0) for hour in data) / len(data)
    except Exception:
        return None

# -----------------------------
# FLIP FINDER
# -----------------------------

sent_uuids: List[str] = []

async def find_flips():
    print("[Flip Finder] Running scan…")
    start_time = time.time()

    groups = await fetch_bins_async()
    end_time = time.time()
    print(f"[API] Fetched bins in {end_time - start_time:.2f}s")

    async with aiohttp.ClientSession() as session:
        tasks = []

        for item_id, auctions in groups.items():
            auctions.sort(key=lambda x: x["price"])
            if len(auctions) < MIN_LISTINGS:
                continue

            a1 = auctions[0]
            a2 = auctions[1]

            lowest = a1["price"]
            second = a2["price"]
            profit = second - lowest

            if profit < MIN_PROFIT or lowest > MAX_COST:
                continue

            uid = a1["uuid"]
            if uid in sent_uuids:
                continue

            # Schedule daily volume fetch
            tasks.append((item_id, a1, a2, lowest, second, profit))

        # Fetch all daily volumes concurrently
        results = await asyncio.gather(*[
            get_avg_daily_volume(session, item_id) for item_id, _, _, _, _, _ in tasks
        ])

        for (item_id, a1, a2, lowest, second, profit), avg_vol in zip(tasks, results):
            if avg_vol is None or avg_vol < MIN_DAILY_VOLUME:
                continue

            uid = a1["uuid"]
            sent_uuids.append(uid)

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

# -----------------------------
# MAIN LOOP
# -----------------------------

cooldown = 5

async def main_loop():
    while True:
        await find_flips()
        print(f"Waiting {cooldown} seconds before searching again \n")
        await asyncio.sleep(cooldown)

if __name__ == "__main__":
    asyncio.run(main_loop())
