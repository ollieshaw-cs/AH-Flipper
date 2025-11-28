import requests
import json

class DiscordNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_flip(
        self,
        name: str,
        item_id: str,
        profit: int,
        lowest: int,
        secondLowest: int,
        volume: float,
        uuid: str
    ):
        """
        Sends an embed to the Discord webhook with flip information.
        """

        embed = {
            "title": "💰 Flip Found!",
            "color": 0x2ECC71,
            "fields": [
                {"name": "Item", "value": name, "inline": False},
                {"name": "SkyBlock ID", "value": f"`{item_id}`", "inline": False},
                {"name": "Lowest BIN", "value": f"`{lowest:,}`", "inline": True},
                {"name": "Second Lowest BIN", "value": f"`{secondLowest:,}`", "inline": True},
                {"name": "Profit", "value": f"`{profit:,}`", "inline": True},
                {"name": "Daily Volume", "value": f"`{volume:.2f}`", "inline": True},
                {"name": "UUID", "value": f"`{uuid}`", "inline": False},
            ],
        }

        payload = {"embeds": [embed]}

        try:
            requests.post(self.webhook_url, json=payload)
        except Exception as e:
            print(f"[Webhook Error] {e}")
