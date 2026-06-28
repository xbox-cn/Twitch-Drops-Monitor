import httpx
import json
import uuid
import os
import sys

# ========== 配置 ==========
CHANNEL_NAME = "adnogpu"

CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
CLIENT_VERSION = "a54467d0-815e-46db-b05d-1b4c6ac650b2"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
GQL_URL = "https://gql.twitch.tv/gql"
INTEGRITY_URL = "https://gql.twitch.tv/integrity"


# ========== 读取 cookie ==========

def load_cookies():
    """从环境变量 TWITCH_COOKIES 读取，返回 cookie 列表的列表（每个子列表是一个账号的 cookies）"""
    raw = os.environ.get("TWITCH_COOKIES", "").strip()
    if not raw:
        print("[!] 环境变量 TWITCH_COOKIES 为空")
        return []
    accounts = []
    # 先尝试整体解析
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            # 判断是 [cookie, ...] 还是 [[cookie, ...], ...]
            if data and isinstance(data[0], dict) and "name" in data[0]:
                accounts.append(data)
            else:
                for item in data:
                    if isinstance(item, list):
                        accounts.append(item)
            return accounts
    except Exception:
        pass
    # 否则按行解析
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            data = json.loads(line)
            if isinstance(data, list):
                accounts.append(data)
        except Exception:
            print(f"  [!] 跳过无法解析的行: {line[:60]}...")
    return accounts


def extract_auth(cookies):
    auth_token = None
    device_id = None
    for c in cookies:
        if c.get("name") == "auth-token":
            auth_token = c.get("value")
        elif c.get("name") == "unique_id":
            device_id = c.get("value")
    return auth_token, device_id or uuid.uuid4().hex


# ========== Twitch GQL ==========

def get_client_integrity(client, auth_token, device_id):
    resp = client.post(INTEGRITY_URL, json={}, headers={
        "Authorization": f"OAuth {auth_token}",
        "Client-Id": CLIENT_ID,
        "x-device-id": device_id,
        "Client-Version": CLIENT_VERSION,
        "Client-Session-Id": device_id[:16],
        "Referer": "https://www.twitch.tv/",
    }, timeout=30)
    if resp.status_code == 401:
        return None
    return resp.json().get("token", "")


def gql_query(client, auth_token, device_id, client_integrity, ops):
    headers = {
        "Authorization": f"OAuth {auth_token}",
        "Client-Id": CLIENT_ID,
        "x-device-id": device_id,
        "Client-Version": CLIENT_VERSION,
        "Client-Session-Id": device_id[:16],
        "Content-Type": "application/json",
    }
    if client_integrity:
        headers["Client-Integrity"] = client_integrity
    resp = client.post(GQL_URL, json=ops, headers=headers, timeout=60)
    if resp.status_code != 200:
        return None, resp.status_code
    try:
        return resp.json(), resp.status_code
    except Exception:
        return None, resp.status_code


def get_stream_info(client, auth_token, device_id, client_integrity, channel_name):
    ops = [{
        "operationName": "GetStreamInfo",
        "query": "query GetStreamInfo($login: String!) { user(login: $login) { id login displayName description stream { id title type createdAt viewersCount game { id name } } } }",
        "variables": {"login": channel_name}
    }]
    result, status = gql_query(client, auth_token, device_id, client_integrity, ops)
    if status == 401:
        return None, "401 Unauthorized"
    if not result or len(result) == 0:
        return None, "无返回数据"
    return result[0].get("data", {}).get("user", {}), status


# ========== 挂宝 (Drops) 查询 ==========

def get_channel_drops_campaigns(client, auth_token, device_id, client_integrity, channel_id):
    ops = [{
        "operationName": "ChannelDropsCampaigns",
        "variables": {"channelID": channel_id},
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": "fc300a8a0d30c710b4e4df5693ebdbfc158fd8e011e503a0e63b656eac869496"}},
    }]
    result, _ = gql_query(client, auth_token, device_id, client_integrity, ops)
    return result[0].get("data", {}) if (result and len(result) > 0) else {}


def get_drops_progress(client, auth_token, device_id, client_integrity, channel_id):
    ops = [{
        "operationName": "DropChannelCampaignsProgress",
        "variables": {"channelID": channel_id},
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": "ec6d1267667ef9e0bfbe11eef9e04e344b0a5384c4300dc685e75c27ac7b5a0b"}},
    }]
    result, _ = gql_query(client, auth_token, device_id, client_integrity, ops)
    return result[0].get("data", {}) if (result and len(result) > 0) else {}


def format_drops_info(drops_data):
    if not drops_data:
        return ["  (无挂宝数据)"]

    lines = []

    progress_list = drops_data.get("channelDropCampaignsProgress")
    if isinstance(progress_list, list) and len(progress_list) > 0:
        for camp in progress_list:
            if not isinstance(camp, dict):
                continue
            name = camp.get("name", "未知活动")
            game = camp.get("game", {}) or {}
            game_name = game.get("name", "")
            start = camp.get("startAt", "")
            end = camp.get("endAt", "")
            time_range = f" ~{end[:10]}" if end else ""

            for rg in camp.get("rewardGroups", []):
                if not isinstance(rg, dict):
                    continue
                criteria = rg.get("progressCriteria", {}) or {}
                reqs = criteria.get("requirements", {}) or {}
                required_min = reqs.get("minutesWatched", 0)
                self_data = rg.get("self", {}) or {}
                current_min = self_data.get("currentMinutesWatched") or 0
                status = self_data.get("status", "")

                rewards = [r.get("name", "") for r in rg.get("rewards", []) if isinstance(r, dict)]
                reward_str = f" -> {', '.join(rewards)}" if rewards else ""

                if current_min > 0 and required_min > 0:
                    pct_line = f"{current_min}/{required_min}min"
                elif required_min > 0:
                    pct_line = f"0/{required_min}min [{status}]"
                elif status:
                    pct_line = f"[{status}]"
                else:
                    pct_line = ""

                game_str = f" [{game_name}]" if game_name else ""
                time_str = f" ({start[:10]}{time_range})" if start else ""
                lines.append(f"    * {name}{game_str}{time_str}{reward_str}  {pct_line}")
    else:
        channel_campaigns = drops_data.get("channelDropCampaigns", [])
        if isinstance(channel_campaigns, list):
            for camp in channel_campaigns:
                if not isinstance(camp, dict):
                    continue
                name = camp.get("name", "未知活动")
                game = camp.get("game", {}) or {}
                game_name = game.get("name", "")
                start = camp.get("startAt", "")
                end = camp.get("endAt", "")
                time_range = f" ~{end[:10]}" if end else ""
                reward_groups = camp.get("rewardGroups", [])
                required_min = 0
                rewards_list = []
                for rg in reward_groups:
                    if isinstance(rg, dict):
                        criteria = rg.get("progressCriteria", {}) or {}
                        reqs = criteria.get("requirements", {}) or {}
                        required_min = max(required_min, reqs.get("minutesWatched", 0))
                        for r in rg.get("rewards", []):
                            if isinstance(r, dict):
                                rewards_list.append(r.get("name", ""))
                reward_str = f" -> {', '.join(rewards_list)}" if rewards_list else ""
                pct_line = f"0/{required_min}min" if required_min else ""
                game_str = f" [{game_name}]" if game_name else ""
                time_str = f" ({start[:10]}{time_range})" if start else ""
                lines.append(f"    * {name}{game_str}{time_str}{reward_str}  {pct_line}")

    if not lines:
        lines.append("  (暂无可用挂宝)")
    return lines


# ========== 主流程 ==========

def main():
    accounts = load_cookies()
    if not accounts:
        print("[!] 环境变量 TWITCH_COOKIES 中没有可用的 cookie")
        sys.exit(1)

    print(f"[*] 频道: {CHANNEL_NAME} | 账号数: {len(accounts)}")
    print("=" * 60)

    for idx, raw_cookies in enumerate(accounts, 1):
        auth_token, device_id = extract_auth(raw_cookies)
        if not auth_token:
            print(f"[acc{idx}] 未找到 auth-token，跳过")
            print("-" * 60)
            continue

        # 构建 cookie jar
        cookie_jar = httpx.Cookies()
        for c in raw_cookies:
            cookie_jar.set(c.get("name", ""), c.get("value", ""),
                           domain=c.get("domain", ""), path=c.get("path", "/"))

        client = httpx.Client(cookies=cookie_jar,
                              headers={"User-Agent": USER_AGENT}, verify=False, timeout=60)

        # 获取 integrity token
        ci = get_client_integrity(client, auth_token, device_id)
        if ci is None:
            print(f"[acc{idx}] device_id={device_id} | 401 - Cookie 失效")
            client.close()
            print("-" * 60)
            continue
        if not ci:
            print(f"[acc{idx}] device_id={device_id} | Integrity 获取失败，使用无签名模式继续...")

        # 查询直播信息
        user, status = get_stream_info(client, auth_token, device_id, ci or "", CHANNEL_NAME)
        if user is None:
            print(f"[acc{idx}] device_id={device_id} | 查询失败: {status}")
            client.close()
            print("-" * 60)
            continue

        stream = user.get("stream")
        print(f"[acc{idx}] device_id={device_id}")
        print(f"  频道: {user.get('displayName') or user.get('login', '')} (ID: {user.get('id', '')})")
        desc = user.get('description') or ''
        print(f"  简介: {desc[:80]}")

        if stream:
            print(f"  直播状态: 在线")
            print(f"  标题: {stream.get('title', '')}")
            print(f"  类型: {stream.get('type', '')}")
            print(f"  观众数: {stream.get('viewersCount', 0)}")
            print(f"  开播时间: {stream.get('createdAt', '')}")
            game = stream.get("game") or {}
            print(f"  游戏: {game.get('name', '')} (ID: {game.get('id', '')})")
            print(f"  Stream ID: {stream.get('id', '')}")
        else:
            print(f"  直播状态: 离线")

        # 查询挂宝活动
        channel_id = user.get("id", "")
        if channel_id:
            print(f"\n  挂宝活动:")
            try:
                drops_data = get_drops_progress(client, auth_token, device_id, ci or "", channel_id)
                if not drops_data.get("channelDropCampaignsProgress"):
                    drops_data = get_channel_drops_campaigns(client, auth_token, device_id, ci or "", channel_id)
                for line in format_drops_info(drops_data):
                    print(line)
            except Exception as e:
                print(f"    查询失败: {e}")

        client.close()
        print("-" * 60)


if __name__ == "__main__":
    main()
