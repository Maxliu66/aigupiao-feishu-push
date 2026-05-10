#!/usr/bin/env python3
"""
爱股票 → 飞书推送服务
从 apis.aigupiao.com/Express/express_list/ 抓取重点要闻，增量推送到飞书群机器人

功能：
- 每5分钟轮询爱股票快讯API
- 过滤重要要闻（important=yes / app_push=yes）
- 增量去重，已推送的不再重复
- 推送飞书群机器人webhook
- 状态持久化（本地JSON文件 或 GitHub Actions Cache）

用法：
  本地运行：python aigupiao_feishu_push.py
  环境变量：FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ============== 配置 ==============

# 飞书 Webhook URL（从环境变量读取）
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")

# 状态文件路径（本地运行用）
STATE_FILE = Path(__file__).parent / "push_state.json"

# GitHub Actions Cache 路径（CI环境用）
GITHUB_CACHE_PATH = os.environ.get("GITHUB_CACHE_PATH", "")

# 要闻过滤模式：
#   "important"  - 仅推送 important=yes 或 app_push=yes 的要闻
#   "all"        - 推送所有要闻（较多）
#   "app_push"   - 仅推送 app_push=yes 的要闻（最少，最核心）
FILTER_MODE = os.environ.get("FILTER_MODE", "hot")

# 每次获取条数
FETCH_NUMBER = int(os.environ.get("FETCH_NUMBER", "20"))

# ============== API ==============

EXPRESS_LIST_URL = "https://apis.aigupiao.com/Express/express_list/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://stock.aigupiao.com/",
    "Accept": "application/json",
}


def fetch_express_list(before="0", after="", number=20, division=""):
    """获取爱股票快讯列表"""
    params = {
        "before": before,
        "source": "pc",
        "web_data": "yes",
        "number": str(number),
        "u_id": "",
        "division": division,
        "express_show_type": "1",
    }
    if after:
        params["after"] = after
        del params["before"]

    query = urllib.parse.urlencode(params)
    url = f"{EXPRESS_LIST_URL}?{query}"

    req = urllib.request.Request(url, headers=HEADERS)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode("utf-8"))
        return data
    except Exception as e:
        print(f"[ERROR] 获取快讯失败: {e}", file=sys.stderr)
        return None


def parse_news_items(api_data):
    """从API返回数据中解析新闻条目"""
    items = []
    if not api_data or api_data.get("rslt") != "succ":
        return items

    data = api_data.get("data", {})
    if not isinstance(data, dict):
        return items

    for date_key, date_data in data.items():
        if not isinstance(date_data, dict):
            continue
        news_list = date_data.get("data", [])
        if not isinstance(news_list, list):
            continue
        for item in news_list:
            items.append(item)

    return items


def filter_important_news(items, mode="important"):
    """根据模式过滤重要要闻"""
    if mode == "all":
        return items

    filtered = []
    for item in items:
        is_important = item.get("important") == "yes"
        is_app_push = item.get("app_push") == "yes"
        is_important_db = item.get("important_db") == "yes"
        is_24h_hot = item.get("is_24_hour_hot_news") == "yes"

        if mode == "important":
            if is_important or is_app_push or is_important_db:
                filtered.append(item)
        elif mode == "app_push":
            if is_app_push:
                filtered.append(item)
        elif mode == "hot":
            if is_24h_hot or is_important or is_app_push:
                filtered.append(item)

    return filtered


def strip_html(text):
    """去除HTML标签"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ============== 状态管理 ==============


def load_state():
    """加载推送状态"""
    # GitHub Actions 环境：从缓存文件读取
    if GITHUB_CACHE_PATH and Path(GITHUB_CACHE_PATH).exists():
        try:
            with open(GITHUB_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # 本地环境：从JSON文件读取
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return {"pushed_ids": [], "last_sort_time": "0"}


def save_state(state):
    """保存推送状态"""
    state["updated_at"] = datetime.now(
        timezone(timedelta(hours=8))
    ).isoformat()

    # 保持 pushed_ids 列表不超过500条
    if len(state.get("pushed_ids", [])) > 500:
        state["pushed_ids"] = state["pushed_ids"][-500:]

    save_path = GITHUB_CACHE_PATH if GITHUB_CACHE_PATH else str(STATE_FILE)
    try:
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] 保存状态失败: {e}", file=sys.stderr)


# ============== 飞书推送 ==============


def build_feishu_card(news_item):
    """构建飞书消息卡片"""
    content = strip_html(news_item.get("content", "") or news_item.get("web_content", ""))
    if not content:
        return None

    news_id = news_item.get("id", "")
    rec_time_desc = news_item.get("rec_time_desc", "")
    theme = news_item.get("theme", "")
    view_num = news_item.get("view_num", "0")
    detail_url = news_item.get("url", f"https://mobile.aigupiao.com/express/detail/id/{news_id}")

    # 判断重要级别
    is_app_push = news_item.get("app_push") == "yes"
    is_important = news_item.get("important") == "yes"
    level_tag = "🔴 重要推送" if is_app_push else ("🟠 重要" if is_important else "📰 要闻")

    # 内容分行：在【】标记后换行，在逗号/句号后适当换行增加可读性
    content = format_content_lines(content)

    # 构建飞书卡片JSON
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"{level_tag} | {rec_time_desc}",
                },
                "template": "red" if is_app_push else ("orange" if is_important else "blue"),
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": content,
                },
            ],
        },
    }

    return card


def format_content_lines(text):
    """将快讯内容格式化为分行显示，增加可读性"""
    # 在【标题】后换行
    text = re.sub(r'(】)\s*', r'\1\n', text)

    # 每个句号后空一行另起一行
    text = re.sub(r'。\s*', r'。\n\n', text)

    # 在分号后换行
    text = re.sub(r'；\s*', r'；\n', text)

    # 在编号列表前换行（如 "1、" "2、"）
    text = re.sub(r'(\d+、)\s*', r'\n\1', text)

    # 清理3行及以上的空行为2行
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    return text


def send_to_feishu(card_data):
    """发送消息到飞书webhook"""
    if not FEISHU_WEBHOOK_URL:
        print("[ERROR] 未设置 FEISHU_WEBHOOK_URL 环境变量", file=sys.stderr)
        return False

    try:
        payload = json.dumps(card_data, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            FEISHU_WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read().decode("utf-8"))
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            return True
        else:
            print(f"[ERROR] 飞书推送失败: {result}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[ERROR] 飞书推送异常: {e}", file=sys.stderr)
        return False


# ============== 主逻辑 ==============


def run():
    """执行一次轮询+推送"""
    print(f"[{datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')}] 开始轮询...")

    if not FEISHU_WEBHOOK_URL:
        print("[ERROR] 请设置环境变量 FEISHU_WEBHOOK_URL")
        print("  本地: set FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx")
        print("  CI:   在 GitHub Secrets 中添加 FEISHU_WEBHOOK_URL")
        sys.exit(1)

    # 加载状态
    state = load_state()
    pushed_ids = set(state.get("pushed_ids", []))
    last_sort_time = state.get("last_sort_time", "0")

    # 获取最新要闻
    api_data = fetch_express_list(before="0", number=FETCH_NUMBER)
    if not api_data:
        print("[WARN] 未获取到数据，跳过本轮")
        return

    # 解析新闻条目
    all_items = parse_news_items(api_data)
    print(f"  获取到 {len(all_items)} 条快讯")

    # 过滤重要要闻
    important_items = filter_important_news(all_items, FILTER_MODE)
    print(f"  过滤后 {len(important_items)} 条重要要闻（模式: {FILTER_MODE}）")

    # 增量去重：只推送新出现的
    new_items = [item for item in important_items if item.get("id") not in pushed_ids]

    if not new_items:
        print("  无新要闻，跳过推送")
        # 更新 last_sort_time
        if api_data.get("last_time"):
            state["last_sort_time"] = api_data["last_time"]
            save_state(state)
        return

    # 按时间正序推送（旧的先推）
    new_items.sort(key=lambda x: int(x.get("sort_time", x.get("rec_time", "0"))))

    print(f"  发现 {len(new_items)} 条新要闻，开始推送...")

    success_count = 0
    for item in new_items:
        card = build_feishu_card(item)
        if not card:
            continue

        if send_to_feishu(card):
            news_id = item.get("id")
            pushed_ids.add(news_id)
            state["pushed_ids"] = list(pushed_ids)
            success_count += 1
            content_preview = strip_html(item.get("content", ""))[:50]
            print(f"  ✅ 已推送 [{item.get('rec_time_desc')}] {content_preview}...")
            # 避免推送过快
            time.sleep(0.5)
        else:
            content_preview = strip_html(item.get("content", ""))[:50]
            print(f"  ❌ 推送失败 [{item.get('rec_time_desc')}] {content_preview}...")

    # 更新状态
    if api_data.get("last_time"):
        state["last_sort_time"] = api_data["last_time"]
    save_state(state)

    print(f"  推送完成: {success_count}/{len(new_items)} 成功")


def run_continuous(interval=300):
    """持续运行模式（本地使用）"""
    print(f"=== 爱股票→飞书推送服务 (每{interval}秒轮询) ===")
    print(f"过滤模式: {FILTER_MODE}")
    print(f"按 Ctrl+C 停止\n")

    while True:
        try:
            run()
        except KeyboardInterrupt:
            print("\n已停止")
            break
        except Exception as e:
            print(f"[ERROR] {e}")

        time.sleep(interval)


if __name__ == "__main__":
    # 检查参数
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--once":
            # 单次运行（GitHub Actions 用）
            run()
        elif cmd == "--continuous":
            # 持续运行（本地用）
            interval = int(sys.argv[2]) if len(sys.argv) > 2 else 300
            run_continuous(interval)
        elif cmd == "--test":
            # 测试模式：获取并显示新闻，不推送
            print("=== 测试模式 ===")
            api_data = fetch_express_list(before="0", number=5)
            if api_data:
                items = parse_news_items(api_data)
                important = filter_important_news(items, FILTER_MODE)
                print(f"\n获取 {len(items)} 条快讯，过滤后 {len(important)} 条重要要闻：\n")
                for item in important:
                    imp = "★重要" if item.get("important") == "yes" else ""
                    push = "🔔推送" if item.get("app_push") == "yes" else ""
                    print(f"  {imp}{push} [{item.get('rec_time_desc')}] {strip_html(item.get('content', ''))[:80]}")
                print(f"\nlast_time: {api_data.get('last_time', 'N/A')}")
        else:
            print("用法:")
            print("  python aigupiao_feishu_push.py --once        # 单次运行（CI用）")
            print("  python aigupiao_feishu_push.py --continuous  # 持续运行（本地用）")
            print("  python aigupiao_feishu_push.py --test        # 测试模式（不推送）")
    else:
        # 默认单次运行
        run()
