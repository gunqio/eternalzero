#!/usr/bin/env python3
"""
Eternal Hosting 服务器自动续期脚本
登录地址：https://eternalzero.cloud/login
依赖：requests（pip install requests）
"""

import os
import sys
import re
import json
import logging
import requests

# ---------- 从环境变量读取配置 ----------
PANEL_URL = os.getenv("PANEL_URL", "https://eternalzero.cloud").rstrip("/")
USERNAME = os.getenv("PANEL_USERNAME")          # 登录邮箱
PASSWORD = os.getenv("PANEL_PASSWORD")
SERVER_ID = os.getenv("SERVER_ID")              # 例如 sxdazg
LOGIN_URL = os.getenv("LOGIN_URL", f"{PANEL_URL}/login")
RENEW_API = os.getenv("RENEW_API", f"/servers/{SERVER_ID}/renew")

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

def check_env():
    """检查必需的环境变量"""
    missing = []
    if not USERNAME:
        missing.append("PANEL_USERNAME")
    if not PASSWORD:
        missing.append("PANEL_PASSWORD")
    if not SERVER_ID:
        missing.append("SERVER_ID")
    if missing:
        logger.error("缺少必需的环境变量: %s", ", ".join(missing))
        sys.exit(1)

def get_csrf_token(session, login_page_url):
    """从登录页 HTML 中提取 CSRF Token（使用正则）"""
    logger.info("正在获取 CSRF Token ...")
    try:
        resp = session.get(login_page_url, timeout=30)
        resp.raise_for_status()
        html = resp.text

        # 查找 <input type="hidden" name="_token" value="...">
        match = re.search(r'<input[^>]*name="_token"[^>]*value="([^"]+)"', html)
        if match:
            token = match.group(1)
            logger.info("CSRF Token 获取成功")
            return token

        # 备选：<meta name="csrf-token" content="...">
        match = re.search(r'<meta[^>]*name="csrf-token"[^>]*content="([^"]+)"', html)
        if match:
            token = match.group(1)
            logger.info("CSRF Token 获取成功 (meta)")
            return token

        logger.error("未能在登录页面找到 CSRF Token")
        return None
    except Exception as e:
        logger.error("获取 CSRF Token 失败: %s", e)
        return None

def login(session):
    """登录面板"""
    token = get_csrf_token(session, LOGIN_URL)
    if not token:
        logger.error("无法获取 CSRF Token，登录终止")
        return False

    # 登录表单数据（字段名来自网页源码）
    payload = {
        "_token": token,
        "email": USERNAME,      # 重要：字段名是 email，不是 username
        "password": PASSWORD,
        # "remember": "on"     // 如果需要记住登录，可取消注释
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": LOGIN_URL,
        "Origin": PANEL_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    logger.info("正在登录 %s ...", LOGIN_URL)
    try:
        resp = session.post(LOGIN_URL, data=payload, headers=headers, timeout=30)
        resp.raise_for_status()

        # 登录成功后通常会重定向到 /servers 或 /dashboard
        if "login" in resp.url.lower():
            logger.error("登录失败，可能用户名或密码错误")
            return False
        logger.info("登录成功")
        return True
    except requests.exceptions.RequestException as e:
        logger.error("登录请求失败: %s", e)
        return False

def renew_server(session):
    """执行续期"""
    if RENEW_API.startswith("http"):
        renew_url = RENEW_API
    else:
        renew_url = f"{PANEL_URL}{RENEW_API}"
    renew_url = renew_url.replace("{server_id}", SERVER_ID)

    logger.info("正在续期: %s", renew_url)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"{PANEL_URL}/servers/{SERVER_ID}",
        "Origin": PANEL_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    }

    try:
        resp = session.post(renew_url, json={}, headers=headers, timeout=30)
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
        return False

def main():
    check_env()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })

    if not login(session):
        logger.error("登录失败，终止脚本")
        sys.exit(1)

    if renew_server(session):
        logger.info("自动续期完成")
        sys.exit(0)
    else:
        logger.error("自动续期失败")
        sys.exit(1)

if __name__ == "__main__":
    main()
