import json
import requests
import time
from typing import Dict, List, Any, Optional
from NBT_Decoder import ItemDecoder
from discord_notify import DiscordNotifier

def parseSettingsValue(v : str):
    new = v.replace(",", "") 
    return int(new)

# -----------------------------
# LOAD CONFIG
# -----------------------------
with open("Settings.json", "r") as file:
    data = json.load(file)

ALLOWED_CATEGORIES = data["ALLOWED_CATEGORIES"]
WEBHOOK_URL = data["WEBHOOK_URL"]

MIN_PROFIT = parseSettingsValue(data["MIN_PROFIT"]) 
MAX_COST = parseSettingsValue(data["MAX_COST"])
MIN_LISTINGS = parseSettingsValue(data["MIN_LISTINGS"])
MIN_DAILY_VOLUME = parseSettingsValue(data["MIN_DAILY_VOLUME"])

notifier = DiscordNotifier(WEBHOOK_URL)

with open("Reforges.json", "r") as f:
    REFORGES = json.load(f).get("Reforges", [])


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
# DAILY VOLUME FROM COFL API
# -----------------------------
def get_avg_daily_volume(item_id: str) -> Optional[float]:
    try:
        data = requests.get(
            f"https://sky.coflnet.com/api/item/price/{item_id}/history/day"
        ).json()

        if not isinstance(data, list) or len(data) == 0:
            return 0.0

        return sum(hour.get("volume", 0) for hour in data) / len(data)

    except Exception:
        return None


# -----------------------------
# FETCH AUCTIONS + GROUP BY SKYBLOCK-ID
# -----------------------------
def fetch_bins() -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    meta = requests.get("https://api.hypixel.net/v2/skyblock/auctions").json()
    total_pages = meta.get("totalPages", 0)

    for page in range(total_pages):
        page_data = requests.get(
            f"https://api.hypixel.net/v2/skyblock/auctions?page={page}"
        ).json()

        for auc in page_data.get("auctions", []):
            if not auc.get("bin"):
                continue
            if auc.get("category") not in ALLOWED_CATEGORIES:
                continue

            full_name = auc.get("item_name")
            display_name = clean_name(full_name)
            price = auc.get("starting_bid")
            uuid = auc.get("uuid")
            item_bytes = auc.get("item_bytes")

            item_id = get_item_id(item_bytes)
            if not item_id:
                # items missing a proper SkyBlock_id (rare)
                # fallback: keep them separated safely
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
# FLIP FINDER
# -----------------------------
sent_uuids: List[str] = []


def find_flips():
    print("Running scan…")
    groups = fetch_bins()

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

        avg_vol = get_avg_daily_volume(item_id)
        if avg_vol is None or avg_vol < MIN_DAILY_VOLUME:
            continue

        uid = a1["uuid"]
        if uid in sent_uuids:
            continue

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
            volume=avg_vol,
            uuid=f"/viewauction {uid}"
        )


# -----------------------------
# MAIN LOOP
# -----------------------------
if __name__ == "__main__":
    while True:
        find_flips()
        time.sleep(30)
