#!/usr/bin/env python3
"""
Eternal Hosting 服务器自动续期脚本（支持 CSRF Token）
用于 GitHub Actions 定时运行
"""

import os
import sys
import re
import json
import logging
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# ---------- 配置 ----------
PANEL_URL = os.getenv("PANEL_URL", "https://eternalzero.cloud").rstrip("/")
USERNAME = os.getenv("PANEL_USERNAME")
PASSWORD = os.getenv("PANEL_PASSWORD")
SERVER_ID = os.getenv("SERVER_ID")
# 登录接口（完整 URL 或相对路径均可）
LOGIN_URL = os.getenv("LOGIN_URL", f"{PANEL_URL}/login")
# 续期接口（可包含占位符 {server_id}）
RENEW_API = os.getenv("RENEW_API", f"/servers/{SERVER_ID}/renew")

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

def check_env():
    """检查必要的环境变量是否已设置"""
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
    """
    访问登录页面，从 HTML 中提取 CSRF Token
    返回 token 字符串，若未找到则返回 None
    """
    logger.info("正在获取 CSRF Token ...")
    try:
        resp = session.get(login_page_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # 查找 <input type="hidden" name="_token" value="...">
        token_input = soup.find("input", {"name": "_token"})
        if token_input and token_input.get("value"):
            token = token_input["value"]
            logger.info("CSRF Token 获取成功")
            return token
        else:
            # 尝试通过 meta 标签
            meta_token = soup.find("meta", {"name": "csrf-token"})
            if meta_token and meta_token.get("content"):
                token = meta_token["content"]
                logger.info("CSRF Token 获取成功 (from meta)")
                return token
            logger.error("未能在登录页面找到 CSRF Token")
            return None
    except Exception as e:
        logger.error("获取 CSRF Token 失败: %s", e)
        return None

def login(session):
    """登录面板，获取会话（Cookie）"""
    # 先获取 CSRF Token
    token = get_csrf_token(session, LOGIN_URL)
    if not token:
        logger.error("无法获取 CSRF Token，登录终止")
        return False

    # 准备登录数据
    payload = {
        "_token": token,
        "username": USERNAME,   # 或 "email"，请根据实际字段调整
        "password": PASSWORD,
    }
    # 可能还需要其他隐藏字段，如 "remember"，但一般不是必需的
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Referer": LOGIN_URL,
        "Origin": PANEL_URL,
    }
    logger.info("正在登录 %s ...", LOGIN_URL)
    try:
        # POST 登录请求
        resp = session.post(LOGIN_URL, data=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        # 判断登录是否成功（可根据响应内容或状态码）
        # 通常登录成功会重定向到仪表板，或者返回 JSON
        if resp.status_code == 200:
            # 检查响应内容是否包含登录失败信息
            if "login" in resp.url or "login" in resp.text.lower():
                logger.error("登录失败，可能用户名或密码错误")
                return False
            logger.info("登录成功")
            return True
        elif resp.status_code in [302, 301]:
            # 重定向通常表示登录成功
            logger.info("登录成功（重定向）")
            return True
        else:
            logger.error("登录异常，状态码: %s", resp.status_code)
            return False
    except requests.exceptions.RequestException as e:
        logger.error("登录请求失败: %s", e)
        return False

def renew_server(session):
    """执行续期操作"""
    # 构建续期 URL
    if RENEW_API.startswith("http"):
        renew_url = RENEW_API
    else:
        renew_url = f"{PANEL_URL}{RENEW_API}"
    # 替换占位符
    renew_url = renew_url.replace("{server_id}", SERVER_ID)
    logger.info("正在续期: %s", renew_url)

    # 续期请求通常需要 CSRF Token，可以从 session 中获取（如果有 cookie）
    # 但根据抓包，续期接口可能只需要 cookie 认证
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Referer": f"{PANEL_URL}/servers/{SERVER_ID}",
        "Origin": PANEL_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    }
    # 如果续期需要 CSRF Token 作为请求头，可从 session 中取，但通常 session 已包含
    # 若需要，可以从 session.cookies 中获取，但此处省略

    try:
        # POST 续期请求，body 可能为空
        resp = session.post(renew_url, json={}, headers=headers, timeout=30)
        resp.raise_for_status()
        # 解析响应
        result = resp.json()
        if result.get("success") or result.get("status") == "success":
            logger.info("✅ 续期成功！")
            return True
        else:
            error_msg = result.get("message") or result.get("error") or "未知错误"
            logger.error("续期失败: %s", error_msg)
            return False
    except requests.exceptions.RequestException as e:
        logger.error("续期请求异常: %s", e)
        if e.response:
            logger.error("响应内容: %s", e.response.text[:200])
        return False
    except json.JSONDecodeError:
        logger.error("续期响应不是有效的 JSON，可能接口路径错误")
        return False

def main():
    check_env()
    session = requests.Session()
    # 设置默认请求头
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
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
