import aiohttp
import asyncio
import json
import time

from NBT_Decoder import ItemDecoder

# Load cached icons
with open("Cache\\item_icons.json", "r") as f:
    cached_icons: dict = json.load(f)
    print(f"[DEBUG] Loaded {len(cached_icons)} cached icons")


async def fetch_json(session, url, retries=40, delay=2):
    """Fetch JSON data with retries and exponential backoff."""
    for attempt in range(retries):
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 429:
                    wait_time = delay * (attempt + 1)
                    print(f"[DEBUG] Rate limited (429). Waiting {wait_time:.2f}s before retry...")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"[DEBUG] Request failed with status {response.status}, retrying...")
        except Exception as e:
            print(f"[ERROR] Exception during request: {e}")
            await asyncio.sleep(delay * (attempt + 1))
    print(f"[ERROR] Failed to fetch {url} after {retries} retries")
    return None


async def getItemBytesFromAuctions(session):
    print("[DEBUG] Fetching total auction pages...")
    data = await fetch_json(session, "https://api.hypixel.net/v2/skyblock/auctions")
    if not data:
        return []

    totalPages = data.get("totalPages", 0)
    print(f"[DEBUG] Total pages to fetch: {totalPages}")

    AuctionBytes = []

    for page in range(totalPages):
        print(f"[DEBUG] Fetching auctions for page {page}...")
        page_data = await fetch_json(session, f"https://api.hypixel.net/v2/skyblock/auctions?page={page}")
        if not page_data:
            continue

        auctionsForPage = page_data.get("auctions", [])
        print(f"[DEBUG] Found {len(auctionsForPage)} auctions on page {page}")

        for idx, auction in enumerate(auctionsForPage):
            if auction.get("bin"):
                item_bytes = auction.get("item_bytes")
                AuctionBytes.append(item_bytes)
                if idx < 5:
                    print(f"[DEBUG] Auction {idx} item_bytes: {item_bytes[:50]}...")

    print(f"[DEBUG] Total auction items fetched: {len(AuctionBytes)}")
    return AuctionBytes


async def fetch_icon(session, item_tag, semaphore):
    """Fetch item icon, respecting the semaphore to limit concurrency."""
    if item_tag in cached_icons:
        print(f"[DEBUG] Item {item_tag} already cached")
        return

    async with semaphore:  # Limit concurrent requests
        print(f"[DEBUG] Item {item_tag} not in cache, fetching icon...")
        data = await fetch_json(session, f"https://sky.coflnet.com/api/item/{item_tag}/details")
        if data and "iconUrl" in data:
            cached_icons[item_tag] = data["iconUrl"]
            print(f"[DEBUG] Cached icon for {item_tag}: {data['iconUrl']}")
            with open("Cache\\item_icons.json", "w") as file:
                json.dump(cached_icons, file, indent=4)
                print(f"[DEBUG] Updated cache file")


async def cacheIcons():
    while True:
        try:
            CONCURRENT_REQUESTS = 3
            semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)

            async with aiohttp.ClientSession() as session:
                AuctionBytes = await getItemBytesFromAuctions(session)
                print(f"[DEBUG] Decoding and caching icons for {len(AuctionBytes)} items...")

                tasks = []
                for idx, itemBytes in enumerate(AuctionBytes):
                    item_tag = ItemDecoder.decode(itemBytes).get("SkyBlock_id")
                    print(f"[DEBUG] Processing item {idx}: {item_tag}")
                    tasks.append(fetch_icon(session, item_tag, semaphore))

                # Run all tasks concurrently, respecting the semaphore
                await asyncio.gather(*tasks)

        except Exception as e:
            print(f"Something went wrong: \n{e}")
    
        print("[DEBUG] Done")
        await asyncio.sleep(60)  # wait 60 seconds before next run


if __name__ == "__main__":
    asyncio.run(cacheIcons())
    
