#!/usr/bin/env python3
"""
Eternal Hosting 自动续期（优先），若续期失败则自动降级为到期提醒
支持 HTTP/HTTPS/SOCKS5 代理
"""

import os
import sys
import re
import time
import json
import logging
import requests
from datetime import datetime

# ---------- 环境变量 ----------
PANEL_URL = os.getenv("PANEL_URL", "https://eternalzero.cloud").rstrip("/")
USERNAME = os.getenv("PANEL_USERNAME")
PASSWORD = os.getenv("PANEL_PASSWORD")
SERVER_ID = os.getenv("SERVER_ID", "6423")
LOGIN_URL = os.getenv("LOGIN_URL", f"{PANEL_URL}/login")
INFO_PAGE = os.getenv("INFO_PAGE", f"/servers/{SERVER_ID}/info")
RENEW_API = os.getenv("RENEW_API", f"/proxycheck-renew/{SERVER_ID}")
WAIT = os.getenv("WAIT_FOR_COOLDOWN", "false").lower() == "true"
THRESHOLD_HOURS = float(os.getenv("THRESHOLD_HOURS", "24"))

# 代理配置（格式: http://user:pass@host:port 或 socks5://host:port）
PROXY_URL = os.getenv("PROXY_URL")

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ---------- 辅助函数（不变） ----------
# ... 所有辅助函数（get_csrf_token_from_page, parse_cooldown, parse_expiry, send_telegram, check_env 等）保持不变 ...

# ---------- 登录、冷却检查、续期、提醒（均不变） ----------
# 这些函数与您提供的完全相同，此处省略以节省空间
# 您需要将上面列出的所有函数原样保留

# ---------- 修改后的主流程 ----------
def main():
    check_env()
    logger.info("PANEL_URL = %s", PANEL_URL)
    logger.info("SERVER_ID = %s", SERVER_ID)
    logger.info("RENEW_API = %s", RENEW_API)
    logger.info("WAIT_FOR_COOLDOWN = %s", WAIT)

    # ------ 代理配置 ------
    proxies = None
    if PROXY_URL:
        proxies = {
            "http": PROXY_URL,
            "https": PROXY_URL,
        }
        logger.info("代理已启用（URL 已隐藏）")
    else:
        logger.info("未使用代理")

    session = requests.Session()
    if proxies:
        session.proxies.update(proxies)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })

    if not login(session):
        sys.exit(1)

    if not check_and_handle_cooldown(session):
        sys.exit(0)

    success, reason = renew_server(session)
    if success:
        logger.info("自动续期完成")
        sys.exit(0)
    else:
        logger.warning("续期失败（原因: %s），执行到期提醒", reason)
        send_expiry_reminder(session)
        sys.exit(0)

if __name__ == "__main__":
    main()
