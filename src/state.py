from collections import deque
import queue
import threading

# Simple `queue.Queue` used as a threadsafe bridge for server-sent events.
# We maintain a subscriber list with thread-safe access. For each connected
# EventSource client, an individual `queue.Queue` is created and added as a
# subscriber; when `main.py` wants to broadcast, it puts the event in all
# subscriber queues (so every client sees every event).
subscribers_lock = threading.Lock()
subscribers: list[queue.Queue] = []

def add_subscriber(q: queue.Queue):
	with subscribers_lock:
		subscribers.append(q)

def remove_subscriber(q: queue.Queue):
	with subscribers_lock:
		try:
			subscribers.remove(q)
		except ValueError:
			pass

def publish_to_subscribers(msg: str):
	with subscribers_lock:
		for q in list(subscribers):
			try:
				q.put_nowait(msg)
			except Exception:
				# ignore individual subscriber failures
				pass

latest_flips = deque(maxlen=200)
