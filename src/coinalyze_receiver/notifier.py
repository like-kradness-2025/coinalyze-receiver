from __future__ import annotations

import requests
from pathlib import Path
from typing import Any

def send_discord_notification(
    webhook_url: str,
    message: str,
    image_path: Path | None = None
) -> bool:
    """
    Discord Webhook を使用して通知を送信する。
    """
    if not webhook_url:
        print("Discord Webhook URL is not configured.")
        return False
    
    payload = {"content": message}
    files = None
    
    if image_path and image_path.exists():
        # Discordで画像を添付して送信する場合
        files = {"file": (image_path.name, open(image_path, "rb"), "image/png")}
        # メッセージにファイル参照を追加 (Discordの仕様に合わせて)
        payload["content"] += f"\\n attachment://{image_path.name}"

    try:
        response = requests.post(webhook_url, data=payload, files=files, timeout=30)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Discord notification failed: {e}")
        return False
    finally:
        if files:
            files["file"][1].close()
