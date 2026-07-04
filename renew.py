import requests
import os
import sys
from datetime import datetime

# ---------- 配置区（通过环境变量传入） ----------
PANEL_URL = os.getenv("PANEL_URL", "https://panel.eternalzero.cloud")
USERNAME = os.getenv("PANEL_USERNAME")
PASSWORD = os.getenv("PANEL_PASSWORD")
SERVER_ID = os.getenv("SERVER_ID", "sxdazg")   # 从截图中的 "View details for sxdazg" 可得
RENEW_API = os.getenv("RENEW_API", "/api/renew")  # 实际续期接口

# ---------- 登录（获取 Cookie 或 Token） ----------
def login(session):
    login_url = f"{PANEL_URL}/api/login"  # 实际登录接口，请替换
    payload = {
        "username": USERNAME,
        "password": PASSWORD
    }
    resp = session.post(login_url, json=payload)
    resp.raise_for_status()
    # 假设登录成功返回 token，保存在 session 中
    data = resp.json()
    if "token" in data:
        session.headers.update({"Authorization": f"Bearer {data['token']}"})
    # 如果是基于 Cookie，则 session 会自动保存

# ---------- 续期函数 ----------
def renew_server(session):
    renew_url = f"{PANEL_URL}{RENEW_API}"
    # 根据抓包结果构造请求体
    payload = {
        "server_id": SERVER_ID,
        "renew_type": "full"   # 或者 "24h" 等，根据实际情况
    }
    resp = session.post(renew_url, json=payload)
    if resp.status_code == 200:
        result = resp.json()
        if result.get("success"):
            print(f"[{datetime.now()}] Renew successful.")
            return True
        else:
            print(f"[{datetime.now()}] Renew failed: {result.get('message', 'Unknown error')}")
            return False
    else:
        print(f"[{datetime.now()}] HTTP error {resp.status_code}: {resp.text}")
        return False

# ---------- 主流程 ----------
def main():
    if not USERNAME or not PASSWORD:
        print("Error: PANEL_USERNAME and PANEL_PASSWORD must be set in environment.")
        sys.exit(1)

    session = requests.Session()
    try:
        login(session)
        success = renew_server(session)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"[{datetime.now()}] Exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
