import requests
import json

from PIL import Image
from io import BytesIO

class DiscordNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def _resize_image(self, url: str, size=(50, 50)) -> BytesIO:
        resp = requests.get(url)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGBA")
        img = img.resize(size, Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    def send_flip(self, name, profit, lowest, volume, uuid, itemURL):
        try:
            # Resize image
            resized_buf = self._resize_image(itemURL, (50, 50))

            embed = {
                "title": "💰 Flip Found!",
                "color": 0x2ECC71,
                "fields": [
                    {"name": "Item", "value": name, "inline": False},
                    {"name": "Cost", "value": f"`{lowest:,}`", "inline": True},
                    {"name": "Profit", "value": f"```ansi\n[32m{profit:,}[0m\n```", "inline": True},
                    {"name": "Daily Volume", "value": f"`{volume:.2f}`", "inline": False},
                    {"name": "Auction", "value": f"```/viewauction {uuid}                       ```", "inline": False}
                ],
                "thumbnail": {"url": "attachment://thumbnail.png"}
            }


            multipart_data = {
                'payload_json': (None, json.dumps({"embeds": [embed]})),
                'file': ('thumbnail.png', resized_buf, 'image/png')
            }

            requests.post(self.webhook_url, files=multipart_data)

        except Exception as e:
            print("[Thumbnail error] Could not process image:", e)
