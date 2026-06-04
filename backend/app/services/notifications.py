from __future__ import annotations

import json
import urllib.request


FEISHU_TIPS_ENDPOINT = "https://7n3ztxp6.fn.bytedance.net/sendtips"


def send_feishu_tip(
    msg: str,
    user_email: str | None,
    endpoint: str = FEISHU_TIPS_ENDPOINT,
    timeout: float = 8.0,
) -> bool:
    email = (user_email or "").strip()
    if not email:
        return False
    payload = json.dumps({"msg": msg, "userEmail": email}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return 200 <= response.status < 300
