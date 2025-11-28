# SkyBlock BIN Flip Finder  
An **asynchronous Hypixel SkyBlock BIN flip scanner** with:  
✓ Automatic profit detection  
✓ Item-ID decoding via NBT  
✓ Discord webhook notifications  
✓ Volume & listing filters  
✓ Persistent gzip caching  
✓ Optimized async + multithreaded processing

This tool continuously scans Hypixel SkyBlock BIN auctions and notifies you of profitable flips based on customized filters.

---

## 🚀 Features

### ⚡ Fast Auction Scanning
- Fetches **all auction pages concurrently** using `aiohttp` with connection pooling.  
- Uses a `ThreadPoolExecutor` for parallel NBT decoding.

### 🎯 Smart Flip Detection
Filters flips using:
- Minimum profit  
- Maximum purchase cost  
- Minimum BIN listings  
- Minimum average daily volume  

### 🧠 Persistent Caching
Stores:
- Cleaned item display names  
- Decoded item NBT → SkyBlock IDs  
- Daily volume results (with TTL)  

Caches are stored as:
```
Cache/name_cache.json  
Cache/tag_cache.gz
```

### 🔔 Discord Notifications
Automatically sends flip notifications via a webhook using `discord_notify.DiscordNotifier`.

### 🧹 Automatic Cache Saving
Caches save on shutdown and every 5 minutes while running.

---

## ▶️ Running the Flip Finder

Run:

```bash
python main.py
```

---

## 🧪 Example Output

```
[Flip Finder] Running scan…
[API] Fetched 123,412 bins in 2.84s
Aspect of the Dragons | ID=AOTE | Profit: 820,000 | Lowest: 3,100,000 | Volume: 62.14 | UUID: xxx-xxx
Found 3 flips
Waiting 7.3 seconds before searching again
```
