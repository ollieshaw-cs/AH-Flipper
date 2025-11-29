from collections import deque

# Shared central state for flips so both `main.py` and `dashboard_server.py`
# use the exact same deque instance instead of creating separate ones via
# accidentally importing `main` twice (as `__main__` and `main`).
latest_flips = deque(maxlen=200)
