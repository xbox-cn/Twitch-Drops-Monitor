import httpx
import json
import uuid
import os

# ========== 配置 ==========
CHANNEL_NAME = "adnogpu"
SEEN_FILE = "seen_drops.json"

CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
CLIENT_VERSION = "a54467d0-815e-46db-b05d-1b4c6ac650b2"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
GQL_URL = "https://gql.twitch.tv/gql"


def gql_query(ops):
    device_id = uuid.uuid4().hex
    headers = {
        "Client-Id": CLIENT_ID,
        "x-device-id": device_id,
        "Client-Version": CLIENT_VERSION,
        "Client-Session-Id": device_id[:16],
        "Content-Type": "application/json",
    }
    client = httpx.Client(headers={"User-Agent": USER_AGENT},
                          verify=False, http2=False, timeout=30)
    resp = client.post(GQL_URL, json=ops, headers=headers, timeout=60)
    client.close()
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def get_channel_id(channel_name):
    ops = [{
        "operationName": "GetStreamInfo",
        "query": "query GetStreamInfo($login: String!) { user(login: $login) { id } }",
        "variables": {"login": channel_name}
    }]
    result = gql_query(ops)
    if result and len(result) > 0:
        return result[0].get("data", {}).get("user", {}).get("id", "")
    return ""


def get_drops_campaigns(channel_id):
    ops = [{
        "operationName": "ChannelDropsCampaigns",
        "query": "query ChannelDropsCampaigns($channelID: String!) { channelDropCampaigns(channelID: $channelID) { id name game { id name } startAt endAt rewardGroups { id name rewards { id name } progressCriteria { requirements { minutesWatched } } } } }",
        "variables": {"channelID": channel_id}
    }]
    result = gql_query(ops)
    return result[0].get("data", {}) if (result and len(result) > 0) else {}


def load_seen_drops():
    if not os.path.exists(SEEN_FILE):
        return set()
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(data)
    except Exception:
        pass
    return set()


def save_seen_drops(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def format_drops(drops_data, seen):
    lines = []
    new_items = []
    campaigns = drops_data.get("channelDropCampaigns", [])

    if not campaigns:
        lines.append("  (暂无挂宝)")
        return lines, new_items

    for camp in campaigns:
        if not isinstance(camp, dict):
            continue
        name = camp.get("name", "未知活动")
        game = camp.get("game", {}) or {}
        game_name = game.get("name", "")
        start = camp.get("startAt", "")[:10]
        end = camp.get("endAt", "")[:10]
        time_str = f" ({start} ~{end})" if start else ""

        for rg in camp.get("rewardGroups", []):
            if not isinstance(rg, dict):
                continue
            criteria = rg.get("progressCriteria", {}) or {}
            reqs = criteria.get("requirements", {}) or {}
            required_min = reqs.get("minutesWatched", 0)
            rewards = [r.get("name", "") for r in rg.get("rewards", []) if isinstance(r, dict)]

            for rn in rewards:
                key = f"{name}::{rn}"
                tag = " [NEW]" if key not in seen else ""
                lines.append(f"  * {name} [{game_name}] -> {rn} ({required_min}min){time_str}{tag}")

                if tag:
                    new_items.append(f"{name} [{game_name}] -> {rn} ({required_min}min){time_str}")

    if not lines:
        lines.append("  (暂无挂宝)")
    return lines, new_items


def main():
    channel_id = get_channel_id(CHANNEL_NAME)
    if not channel_id:
        print(f"[!] 无法获取频道 {CHANNEL_NAME} 的 ID")
        return

    seen = load_seen_drops()
    drops_data = get_drops_campaigns(channel_id)
    lines, new_items = format_drops(drops_data, seen)

    print(f"频道: {CHANNEL_NAME} (ID: {channel_id})")
    print("挂宝列表:")
    for line in lines:
        print(line)

    if new_items:
        for item in new_items:
            camp_name = item.split(" -> ", 1)[0]
            reward_name = item.split(" -> ", 1)[1].split(" (")[0]
            seen.add(f"{camp_name}::{reward_name}")
        save_seen_drops(seen)

        print("\n[NEW] 新掉宝:")
        for item in set(new_items):
            print(f"  {item}")

        with open("new_drops.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(set(new_items))))
    else:
        if os.path.exists("new_drops.txt"):
            os.remove("new_drops.txt")
        print("\n(无新掉宝)")


if __name__ == "__main__":
    main()
