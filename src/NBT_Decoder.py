import base64
import zlib
import io
import nbtlib
from nbtlib.tag import Compound

class ItemDecoder:
    @staticmethod
    def decode(item_bytes_b64: str) -> dict:
        """
        Decode Hypixel/SkyBlock item_bytes (Base64 + GZIP + NBT) into a readable dict.
        Returns the important fields:
          - id
          - Count
          - Damage
          - Name
          - Lore
          - SkyBlock_id
          - uuid
          - timestamp
        """
        # Base64 → bytes
        compressed = base64.b64decode(item_bytes_b64)
        
        # GZIP decompress
        decompressed = zlib.decompress(compressed, 16 + zlib.MAX_WBITS)
        
        # Parse binary NBT
        buf = io.BytesIO(decompressed)
        buf.seek(0)
        try:
            root = Compound.parse(buf)
        except Exception:
            buf.seek(0)
            try:
                root = nbtlib.File.from_fileobj(buf).root
            except Exception as e:
                raise RuntimeError("Could not parse NBT") from e
        
        # Unpack to JSON-like dict
        unpacked = root.unpack(json=True)

        # Extract important fields
        try:
            item = unpacked[""]["i"][0]
            tag = item.get("tag", {})
            display = tag.get("display", {})
            extra = tag.get("ExtraAttributes", {})

            important_values = {
                "id": item.get("id"),
                "Count": item.get("Count"),
                "Damage": item.get("Damage"),
                "Name": display.get("Name"),
                "Lore": display.get("Lore"),
                "SkyBlock_id": extra.get("id"),
                "uuid": extra.get("uuid"),
                "timestamp": extra.get("timestamp")
            }
        except (KeyError, IndexError):
            important_values = None

        return important_values


if __name__ == "__main__":
    item_bytes_b64 = "H4sIAAAAAAAA/01RzU7bQBCehFASS9DSA/RULRIHUJRiwPmBGw1OghQQUiIuCKGNPXZXrNfRehfRN+gLVEJ9gfQCZ855FB4EMQ4IuH37/cw3q3EAKlAQDgAUilAUIdwXYL6dWmUKDswZHs9BpSdC7EgeZ+R6cmAhFNlY8t8VKPVTjWViF+HrdNI8xAhVhvtsOuHVpgsrxA21RfZBiKp1WCX+WCihYjYYI4Y536huu/DtXeik2liFL1IdvpDy5o1y73cCrXOiHx/+Erp4fbYeb2/zJy21QdGOlZIN0LCfqbLZPvNvxqgNoxLUlGhuuFveJtQIdTVXJpvV7dBI9nHB3Em5V2625uBK0GSJ1yiZVTINrjD8QaW5lfqHv0TGhMGEBVyxETKNUapjDNdgeTqpTyfSPz1qs57fP/aHZSid8ARnSlfygHKshzJBAw589m+M5gfGaDGyBrPy7EpL3f5B+2joX75NsJbo9agVBPVgd7fmNoJRzQsJ7UXIa5EXeN5eY9sdNcMSVIxIMDM8GdPZ//3/c3YHUIRPhzzhMdIn4BnIpiTBFwIAAA=="

    decoded_item = ItemDecoder.decode(item_bytes_b64)
    
    from pprint import pprint
    pprint(decoded_item)
