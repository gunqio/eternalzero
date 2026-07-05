#!/usr/bin/env python3
"""
Eternal Hosting 自动续期（优先），若检测到 VPN 拦截则自动降级为到期提醒
"""

import os
import sys
import re
import time
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

# 提醒阈值（小时），默认 24 小时，仅降级时使用
THRESHOLD_HOURS = float(os.getenv("THRESHOLD_HOURS", "24"))

# Telegram 通知（可选，建议配置）
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ---------- 通用辅助函数 ----------
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
    """从 HTML 页面中提取 CSRF Token（meta 或 input）"""
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
    """从页面中解析冷却剩余时间（秒）"""
    match = re.search(r'<div[^>]*id="cooldown-display"[^>]*>(.*?)</div>', html, re.DOTALL)
    if match:
        text = match.group(1).strip()
        time_match = re.search(r'(\d+)h\s+(\d+)m', text)
        if time_match:
            h, m = int(time_match.group(1)), int(time_match.group(2))
            return h * 3600 + m * 60
        time_match = re.search(r'(\d+)m', text)
        if time_match:
            return int(time_match.group(1)) * 60
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

def parse_expiry(html):
    """从页面中解析 Expires 时间，返回 datetime 对象（假设 UTC）"""
    patterns = [
        r'Expires\s+([A-Za-z]{3}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2})',
        r'Expires:\s*([A-Za-z]{3}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2})',
        r'expires\s+([A-Za-z]{3}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2})',
    ]
    for pat in patterns:
        match = re.search(pat, html, re.IGNORECASE)
        if match:
            date_str = match.group(1)
            try:
                dt = datetime.strptime(date_str, "%b %d, %Y %H:%M")
                return dt
            except ValueError:
                continue
    return None

def send_telegram(message):
    """通过 Telegram 发送消息"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        logger.warning("未配置 Telegram 通知，跳过发送")
        return False
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": TG_CHAT_ID,
            "text": message,
            "disable_web_page_preview": True
        }, timeout=10)
        if resp.status_code == 200:
            logger.info("Telegram 通知发送成功")
            return True
        else:
            logger.error("Telegram 发送失败: %s", resp.text)
            return False
    except Exception as e:
        logger.error("Telegram 异常: %s", e)
        return False

# ---------- 登录 ----------
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

# ---------- 冷却检查 ----------
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
                logger.info("冷却中，跳过本次任务（等待下次定时）")
                sys.exit(0)
        else:
            logger.info("✅ 无冷却")
            return True
    except Exception as e:
        logger.error("检查冷却失败: %s", e)
        return True

# ---------- 核心续期函数（增强头部） ----------
def renew_server(session):
    info_url = f"{PANEL_URL}{INFO_PAGE}"
    token = get_csrf_token_from_page(session, info_url)
    if not token:
        logger.error("无法获取 CSRF Token，续期终止")
        return False, None

    renew_api = RENEW_API if RENEW_API else f"/proxycheck-renew/{SERVER_ID}"
    if renew_api.startswith("http"):
        renew_url = renew_api
    else:
        renew_url = f"{PANEL_URL}{renew_api}"
    renew_url = renew_url.replace("{server_id}", SERVER_ID)

    logger.info("正在续期: %s", renew_url)

    # ----- 补全所有浏览器头部（模仿真实请求） -----
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Content-Type": "application/json",
        "Referer": info_url,
        "Origin": PANEL_URL,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Priority": "u=1, i",
        "x-csrf-token": token,
    }
    # 添加 X-XSRF-TOKEN（如果有 cookie）
    xsrf = session.cookies.get('XSRF-TOKEN')
    if xsrf:
        headers['X-XSRF-TOKEN'] = xsrf

    safe_headers = {k: v for k, v in headers.items() if k not in ['x-csrf-token', 'X-XSRF-TOKEN']}
    logger.info("请求 Headers (脱敏): %s", safe_headers)
    logger.info("请求 Body: {}")

    payload = {}
    try:
        resp = session.post(renew_url, json=payload, headers=headers, timeout=30)
        logger.info("响应状态码: %s", resp.status_code)
        body = resp.text[:500]
        logger.info("响应内容: %s", body)
        resp.raise_for_status()
        result = resp.json()
        # 判断续期是否成功
        if result.get("success") or result.get("status") == "success" or "success" in str(result).lower():
            logger.info("✅ 续期成功！")
            return True, None
        else:
            # 检查是否为 VPN 拦截
            if "VPN or proxy detected" in body or "disable your VPN" in body:
                logger.warning("⚠️ 续期被拦截：VPN/代理检测")
                return False, "vpn_blocked"
            else:
                error_msg = result.get("message") or result.get("error") or "未知错误"
                logger.error("续期失败: %s", error_msg)
                return False, "other_error"
    except requests.exceptions.HTTPError as e:
        logger.error("HTTP 错误: %s", e)
        if hasattr(e, 'response') and e.response:
            logger.error("响应状态码: %s", e.response.status_code)
            logger.error("响应内容: %s", e.response.text[:500])
        return False, "http_error"
    except Exception as e:
        logger.error("续期请求异常: %s", e)
        if hasattr(e, 'response') and e.response:
            logger.error("响应状态码: %s", e.response.status_code)
            logger.error("响应内容: %s", e.response.text[:500])
        return False, "exception"

# ---------- 降级提醒函数 ----------
def send_expiry_reminder(session):
    """获取到期时间并发送提醒"""
    info_url = f"{PANEL_URL}{INFO_PAGE}"
    logger.info("获取服务器信息: %s", info_url)
    try:
        resp = session.get(info_url, timeout=30)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.error("获取详情页失败: %s", e)
        return

    expiry = parse_expiry(html)
    if not expiry:
        logger.error("无法解析到期时间，无法发送提醒")
        return

    now = datetime.utcnow()
    remaining = expiry - now
    hours_left = remaining.total_seconds() / 3600

    logger.info("服务器到期时间: %s (UTC)", expiry.strftime("%Y-%m-%d %H:%M"))
    logger.info("剩余时间: %.1f 小时", hours_left)

    if hours_left < THRESHOLD_HOURS:
        msg = (
            f"⚠️ Eternal Hosting 服务器即将到期（自动续期因 IP 风控失败）\n"
            f"服务器 ID: {SERVER_ID}\n"
            f"到期时间: {expiry.strftime('%Y-%m-%d %H:%M')} (UTC)\n"
            f"剩余时间: {hours_left:.1f} 小时\n"
            f"请尽快手动登录续期：{PANEL_URL}{INFO_PAGE}"
        )
        logger.warning(msg)
        send_telegram(msg)
    else:
        logger.info("✅ 剩余时间充足，暂不提醒")

# ---------- 主流程 ----------
def main():
    check_env()
    logger.info("PANEL_URL = %s", PANEL_URL)
    logger.info("SERVER_ID = %s", SERVER_ID)
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

    # 尝试续期（自动）
    success, reason = renew_server(session)
    if success:
        logger.info("自动续期完成")
        sys.exit(0)
    else:
        # 如果续期失败且原因是 VPN 拦截，降级为提醒模式
        if reason == "vpn_blocked":
            logger.info("由于 IP 风控，自动续期不可用，切换为到期提醒模式")
            send_expiry_reminder(session)
            sys.exit(0)   # 提醒发送后正常退出
        else:
            # 其他错误（如网络问题、CSRF 失效等），也尝试发送提醒以防万一
            logger.warning("续期失败（原因: %s），尝试发送到期提醒", reason)
            send_expiry_reminder(session)
            sys.exit(1)   # 仍标记为失败

if __name__ == "__main__":
    main()
