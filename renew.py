#!/usr/bin/env python3
"""
Eternal Hosting 服务器自动续期脚本
用于 GitHub Actions 定时运行
"""

import os
import sys
import json
import logging
from datetime import datetime
import requests

# ---------- 配置 ----------
PANEL_URL = os.getenv("PANEL_URL", "https://panel.eternalzero.cloud").rstrip("/")
USERNAME = os.getenv("PANEL_USERNAME")
PASSWORD = os.getenv("PANEL_PASSWORD")
SERVER_ID = os.getenv("SERVER_ID")
LOGIN_API = os.getenv("LOGIN_API", "/api/login")          # 可自定义，默认为 /api/login
RENEW_API = os.getenv("RENEW_API")                        # 建议直接写死，如 /servers/sxdazg/renew

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
    if not RENEW_API:
        missing.append("RENEW_API")
    if missing:
        logger.error("缺少必需的环境变量: %s", ", ".join(missing))
        sys.exit(1)

def login(session):
    """登录面板，获取会话（Cookie）"""
    login_url = f"{PANEL_URL}{LOGIN_API}"
    payload = {
        "username": USERNAME,
        "password": PASSWORD
    }
    logger.info("正在登录 %s ...", login_url)
    try:
        resp = session.post(login_url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # 如果登录返回 token，将其添加到后续请求的 Header 中
        if "token" in data:
            session.headers.update({"Authorization": f"Bearer {data['token']}"})
            logger.info("登录成功 (Bearer Token)")
        else:
            # 否则依赖 cookie，session 会自动保存
            logger.info("登录成功 (Session Cookie)")
        return True
    except requests.exceptions.RequestException as e:
        logger.error("登录请求失败: %s", e)
        return False
    except json.JSONDecodeError:
        logger.error("登录响应不是有效的 JSON，可能登录接口路径错误")
        return False

def renew_server(session):
    """执行续期操作"""
    # 如果 RENEW_API 包含占位符 {server_id}，进行替换
    renew_url = f"{PANEL_URL}{RENEW_API}".replace("{server_id}", SERVER_ID)
    # 如果 RENEW_API 中未包含占位符，但用户写的是 /servers/sxdazg/renew，也可以直接拼接
    # 但为了兼容，若未替换且不包含占位符，直接使用
    logger.info("正在续期: %s", renew_url)
    try:
        # 根据抓包结果，续期为 POST 请求，body 为空或包含必要参数
        # 部分面板可能需要传 {"server_id": SERVER_ID}，根据实际情况调整
        payload = {}  # 多数续期接口 body 为空
        # 如果截图中看到有 body，可以在这里添加，例如：
        # payload = {"server_id": SERVER_ID}
        resp = session.post(renew_url, json=payload, timeout=30)
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
        return False
    except json.JSONDecodeError:
        logger.error("续期响应不是有效的 JSON，可能接口路径错误或需要附加参数")
        return False

def main():
    check_env()
    session = requests.Session()
    # 设置默认请求头，模拟浏览器
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": f"{PANEL_URL}/servers/{SERVER_ID}",
        "Origin": PANEL_URL,
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
