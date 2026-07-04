#!/usr/bin/env python3
"""
Eternal Hosting 自动续期（修正数字ID + 冷却检测增强）
"""

import os
import sys
import re
import json
import time
import logging
import requests

PANEL_URL = os.getenv("PANEL_URL", "https://eternalzero.cloud").rstrip("/")
USERNAME = os.getenv("PANEL_USERNAME")
PASSWORD = os.getenv("PANEL_PASSWORD")
SERVER_ID = os.getenv("SERVER_ID", "6423")          # 数字ID
LOGIN_URL = os.getenv("LOGIN_URL", f"{PANEL_URL}/login")
INFO_PAGE = os.getenv("INFO_PAGE", f"/servers/{SERVER_ID}/info")
RENEW_API = os.getenv("RENEW_API", f"/servers/{SERVER_ID}/renew")
WAIT = os.getenv("WAIT_FOR_COOLDOWN", "false").lower() == "true"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

def check_env():
    missing = []
    if not USERNAME:
        missing.append("PANEL_USERNAME")
    if not PASSWORD:
        missing.append("PANEL_PASSWORD")
    if missing:
        logger.error("缺少必需的环境变量: %s", ", ".join(missing))
        sys.exit(1)

def get_csrf_token_from_page(session, url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        resp = session.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        html = resp.text
        match = re.search(r'<meta[^>]*name="csrf-token"[^>]*content="([^"]+)"', html)
        if match:
            return match.group(1)
        match = re.search(r'<input[^>]*name="_token"[^>]*value="([^"]+)"', html)
        if match:
            return match.group(1)
        return None
    except Exception as e:
        logger.error("获取 CSRF Token 失败: %s", e)
        return None

def parse_cooldown(html):
    """优先从 div#cooldown-display 中提取，否则从全文匹配"""
    # 定位冷却显示div
    match = re.search(r'<div[^>]*id="cooldown-display"[^>]*>(.*?)</div>', html, re.DOTALL)
    if match:
        text = match.group(1).strip()
        # 提取类似 "1h 23m" 或 "23m"
        time_match = re.search(r'(\d+)h\s+(\d+)m', text)
        if time_match:
            h, m = int(time_match.group(1)), int(time_match.group(2))
            return h * 3600 + m * 60
        time_match = re.search(r'(\d+)m', text)
        if time_match:
            return int(time_match.group(1)) * 60
        # 如果只有数字（如 "83m"），但已覆盖
    # 备用全文搜索
    patterns = [
        r'You can renew again in\s+(\d+)h\s+(\d+)m',
        r'You can renew again in\s+(\d+)h\s+(\d+)\s*min',
        r'You can renew again in\s+(\d+)m',
        r'(\d+)h\s+(\d+)m\s+left',
        r'(\d+)h\s+(\d+)\s*min\s+left',
        r'(\d+)m\s+left',
    ]
    for pat in patterns:
        match = re.search(pat, html, re.IGNORECASE)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                return int(groups[0]) * 3600 + int(groups[1]) * 60
            elif len(groups) == 1:
                return int(groups[0]) * 60
    return 0

def login(session):
    token = get_csrf_token_from_page(session, LOGIN_URL)
    if not token:
        logger.error("无法获取 CSRF Token，登录终止")
        return False

    payload = {
        "_token": token,
        "email": USERNAME,
        "password": PASSWORD,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": LOGIN_URL,
        "Origin": PANEL_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    logger.info("正在登录 %s ...", LOGIN_URL)
    try:
        resp = session.post(LOGIN_URL, data=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        if "login" in resp.url.lower():
            logger.error("登录失败，可能用户名或密码错误")
            return False
        logger.info("登录成功")
        return True
    except Exception as e:
        logger.error("登录请求失败: %s", e)
        return False

def renew_server(session):
    info_url = f"{PANEL_URL}{INFO_PAGE}"
    token = get_csrf_token_from_page(session, info_url)
    if not token:
        logger.error("无法获取 CSRF Token，续期终止")
        return False

    if RENEW_API.startswith("http"):
        renew_url = RENEW_API
    else:
        renew_url = f"{PANEL_URL}{RENEW_API}"
    renew_url = renew_url.replace("{server_id}", SERVER_ID)

    logger.info("正在续期: %s", renew_url)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": info_url,
        "Origin": PANEL_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    xsrf = session.cookies.get('XSRF-TOKEN')
    if xsrf:
        headers['X-XSRF-TOKEN'] = xsrf

    payload = {"_token": token}

    try:
        resp = session.post(renew_url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if result.get("success") or result.get("status") == "success":
            logger.info("✅ 续期成功！")
            return True
        else:
            error_msg = result.get("message") or result.get("error") or "未知错误"
            logger.error("续期失败: %s", error_msg)
            return False
    except Exception as e:
        logger.error("续期请求异常: %s", e)
        if hasattr(e, 'response') and e.response:
            logger.error("响应状态码: %s", e.response.status_code)
            logger.error("响应内容: %s", e.response.text[:500])
        return False

def check_and_handle_cooldown(session):
    info_url = f"{PANEL_URL}{INFO_PAGE}"
    logger.info("检查冷却状态: %s", info_url)
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        resp = session.get(info_url, headers=headers, timeout=30)
        resp.raise_for_status()
        html = resp.text

        cooldown_seconds = parse_cooldown(html)
        if cooldown_seconds > 0:
            hours = cooldown_seconds // 3600
            minutes = (cooldown_seconds % 3600) // 60
            logger.info("⏳ 冷却中，剩余 %dh %dm", hours, minutes)
            if WAIT:
                logger.info("等待 %d 秒后继续...", cooldown_seconds + 10)
                time.sleep(cooldown_seconds + 10)
                return True
            else:
                logger.info("跳过本次续期，等待下次定时任务")
                sys.exit(0)
        else:
            logger.info("✅ 无冷却，可以续期")
            return True
    except Exception as e:
        logger.error("检查冷却失败: %s", e)
        return True

def main():
    check_env()
    logger.info("PANEL_URL = %s", PANEL_URL)
    logger.info("LOGIN_URL = %s", LOGIN_URL)
    logger.info("INFO_PAGE = %s", INFO_PAGE)
    logger.info("RENEW_API = %s", RENEW_API)
    logger.info("WAIT_FOR_COOLDOWN = %s", WAIT)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })

    if not login(session):
        sys.exit(1)

    if not check_and_handle_cooldown(session):
        sys.exit(0)

    if renew_server(session):
        logger.info("自动续期完成")
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
