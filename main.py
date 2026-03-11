from fastapi import FastAPI, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from database import SessionLocal, ShacoMatch, ShacoPlayer, init_db
import requests
import os
import time
import threading
import json
from dotenv import load_dotenv
from collections import defaultdict, Counter

load_dotenv()

templates = Jinja2Templates(directory="templates")
templates.env.filters["from_json"] = lambda s: json.loads(s) if s else []
app = FastAPI(title="OTP Shaco Analytics")

# ── Stats cache (5 min TTL) ───────────────────────────────
import time as _cache_time
_stats_cache = {}
_CACHE_TTL = 300


def _clear_stats_cache():
    _stats_cache.clear()


@app.on_event("startup")
def warmup_cache():
    """Pre-load only light/common filter combos so startup doesn't time out."""
    import threading

    def _warm():
        time.sleep(3)  # wait for DB connection pool to settle
        combos = [
            ("ap", "jungle", ""),
            ("ad", "jungle", ""),
            ("all", "jungle", ""),
            ("all", "support", ""),
        ]
        for b, p, u in combos:
            try:
                stats_data(build=b, position=p, puuid=u)
                print(f"[cache] warmed {b}/{p}")
            except Exception as e:
                print(f"[cache] warmup failed {b}/{p}: {e}")

    threading.Thread(target=_warm, daemon=True).start()

# ── DDragon patch cache ───────────────────────────────────
_patch_cache = {"version": "15.5.1", "ts": 0}
_PATCH_TTL = 3600  # refresh every hour


def get_current_patch() -> str:
    global _patch_cache
    if _cache_time.time() - _patch_cache["ts"] < _PATCH_TTL:
        return _patch_cache["version"]
    try:
        v = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=4).json()[0]
        _patch_cache = {"version": v, "ts": _cache_time.time()}
        return v
    except Exception:
        return _patch_cache["version"]


# ─── BACKGROUND FETCH TRACKER ────────────────────────────────────────
# Key: "{region}:{summoner_lower}" → {status, progress, total, nuevas, error}
_fetch_status: dict = {}
_fetch_lock = threading.Semaphore(1)  # only 1 fetch at a time globally


def _fetch_key(region: str, summoner: str) -> str:
    return f"{region.lower()}:{summoner.lower()}"


API_KEY = os.getenv("RIOT_API_KEY")
HEADERS = {"X-Riot-Token": API_KEY}

# ─── HELPERS ─────────────────────────────────────────────


def get_cluster(region):
    clusters = {
        "euw1": "europe", "eun1": "europe", "tr1": "europe",
        "na1": "americas", "la1": "americas", "la2": "americas", "br1": "americas",
        "kr": "asia", "jp1": "asia",
    }
    return clusters.get(region.lower(), "europe")


def get_puuid(name, tag, cluster):
    url = f"https://{cluster}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()["puuid"], r.json().get("tagLine", tag)


# Tags comunes por región para auto-detección
REGION_COMMON_TAGS = {
    "euw1":  ["EUW", "EUW1", "EUNE", "EU"],
    "na1":   ["NA1", "NA", "1"],
    "kr":    ["KR1", "KR"],
    "eun1":  ["EUNE", "EUN1", "EU"],
    "la1":   ["LAN", "LA1", "LA"],
    "la2":   ["LAS", "LA2", "LA"],
    "br1":   ["BR1", "BR"],
    "tr1":   ["TR1", "TR"],
    "oc1":   ["OCE", "OC1"],
    "jp1":   ["JP1", "JP"],
}

def find_puuid_any_tag(name, tag_hint, cluster, region):
    """
    Tries to find a player's PUUID by testing multiple tags.
    Returns (puuid, real_tag) or raises Exception if not found.
    """
    # Build tag list: user's hint first, then common tags for region
    common = REGION_COMMON_TAGS.get(region, [])
    tags_to_try = [tag_hint] + [t for t in common if t.upper() != tag_hint.upper()]

    last_err = None
    for t in tags_to_try:
        try:
            url = f"https://{cluster}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{requests.utils.quote(name)}/{requests.utils.quote(t)}"
            print(f"[find_puuid] trying: {url}")
            r = requests.get(url, headers=HEADERS, timeout=8)
            print(f"[find_puuid] status: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                return data["puuid"], data.get("tagLine", t)
            elif r.status_code == 404:
                last_err = "not_found"
                continue
            else:
                last_err = f"HTTP {r.status_code}"
                continue
        except Exception as e:
            last_err = str(e)
            continue

    raise Exception(last_err or "not_found")


def winrate(wins, total):
    if total == 0:
        return 0
    return round(wins / total * 100, 1)


def avg(values):
    return round(sum(values) / len(values), 1) if values else 0

# ─── RANK ────────────────────────────────────────────────


def get_rank(puuid, region):
    try:
        l = requests.get(
            f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}",
            headers=HEADERS
        )
        l.raise_for_status()
        for entry in l.json():
            if entry["queueType"] == "RANKED_SOLO_5x5":
                tier = entry["tier"].capitalize()
                rank = entry["rank"]
                lp = entry["leaguePoints"]
                wins = entry["wins"]
                losses = entry["losses"]
                total = wins + losses
                return {
                    "tier": tier, "rank": rank, "lp": lp,
                    "wins": wins, "losses": losses,
                    "winrate": round(wins / total * 100, 1) if total else 0,
                    "display": f"{tier} {rank} {lp} LP",
                }
        return None
    except Exception as e:
        print(f"[get_rank ERROR] {type(e).__name__}: {e}")
        return None

# ─── PERK ICONS ──────────────────────────────────────────


_perk_icon_cache = {}


def get_perk_icons(patch):
    global _perk_icon_cache
    if _perk_icon_cache:
        return _perk_icon_cache
    try:
        url = f"https://ddragon.leagueoflegends.com/cdn/{patch}/data/en_US/runesReforged.json"
        trees = requests.get(url, timeout=5).json()
        for tree in trees:
            for slot in tree.get("slots", []):
                for rune in slot.get("runes", []):
                    icon_path = rune.get("icon", "")
                    _perk_icon_cache[rune["id"]] = f"https://ddragon.leagueoflegends.com/cdn/img/{icon_path}"
    except Exception as e:
        print(f"[perk_icons ERROR] {e}")
    return _perk_icon_cache

# ─── SUMMONER SPELLS ─────────────────────────────────────


_spell_cache = {}


def get_spell_icons(patch):
    global _spell_cache
    if _spell_cache:
        return _spell_cache
    try:
        url = f"https://ddragon.leagueoflegends.com/cdn/{patch}/data/en_US/summoner.json"
        data = requests.get(url, timeout=5).json()["data"]
        for key, spell in data.items():
            sid = int(spell.get("key", 0))
            _spell_cache[sid] = {
                "name": spell["name"],
                "key": key,
                "icon": f"https://ddragon.leagueoflegends.com/cdn/{patch}/img/spell/{spell['image']['full']}",
            }
    except Exception as e:
        print(f"[spell_icons ERROR] {e}")
    return _spell_cache

# ─── STATS ───────────────────────────────────────────────


def calc_stats(matches):
    total = len(matches)
    if total == 0:
        return None

    wins = sum(1 for m in matches if m.win)
    kills = sum(m.kills for m in matches)
    deaths = sum(m.deaths for m in matches)
    assists = sum(m.assists for m in matches)
    ap = [m for m in matches if m.build == "AP"]
    ad = [m for m in matches if m.build == "AD"]
    short = [m for m in matches if m.duration_min <= 25]
    mid = [m for m in matches if 25 < m.duration_min <= 35]
    long_ = [m for m in matches if m.duration_min > 35]
    blue = [m for m in matches if m.side == "blue"]
    red = [m for m in matches if m.side == "red"]
    jungle = [m for m in matches if m.position == "JUNGLE"]
    support = [m for m in matches if m.position == "UTILITY"]

    enemy_stats = defaultdict(lambda: {"wins": 0, "total": 0})
    for m in matches:
        if not m.enemy_champs:
            continue
        for champ in m.enemy_champs.split(","):
            champ = champ.strip()
            if champ:
                enemy_stats[champ]["total"] += 1
                if m.win:
                    enemy_stats[champ]["wins"] += 1

    matchups = [
        {"champ": c, "wins": d["wins"], "total": d["total"], "winrate": winrate(d["wins"], d["total"])}
        for c, d in enemy_stats.items() if d["total"] >= 3
    ]

    return {
        "total_games": total,
        "wins": wins,
        "losses": total - wins,
        "winrate": round(wins / total * 100, 1),
        "kda": {
            "kills": round(kills / total, 1),
            "deaths": round(deaths / total, 1),
            "assists": round(assists / total, 1),
            "ratio": round((kills + assists) / max(deaths, 1), 2),
        },
        "ap": {"games": len(ap), "wins": sum(1 for m in ap if m.win), "winrate": winrate(sum(1 for m in ap if m.win), len(ap))},
        "ad": {"games": len(ad), "wins": sum(1 for m in ad if m.win), "winrate": winrate(sum(1 for m in ad if m.win), len(ad))},
        "by_duration": {
            "short": {"label": "≤25 min", "games": len(short), "wins": sum(1 for m in short if m.win), "winrate": winrate(sum(1 for m in short if m.win), len(short))},
            "mid": {"label": "26-35 min", "games": len(mid), "wins": sum(1 for m in mid if m.win), "winrate": winrate(sum(1 for m in mid if m.win), len(mid))},
            "long": {"label": "36+ min", "games": len(long_), "wins": sum(1 for m in long_ if m.win), "winrate": winrate(sum(1 for m in long_ if m.win), len(long_))},
        },
        "by_side": {
            "blue": {"games": len(blue), "wins": sum(1 for m in blue if m.win), "winrate": winrate(sum(1 for m in blue if m.win), len(blue))},
            "red": {"games": len(red), "wins": sum(1 for m in red if m.win), "winrate": winrate(sum(1 for m in red if m.win), len(red))},
        },
        "by_position": {
            "jungle": {"games": len(jungle), "wins": sum(1 for m in jungle if m.win), "winrate": winrate(sum(1 for m in jungle if m.win), len(jungle))},
            "support": {"games": len(support), "wins": sum(1 for m in support if m.win), "winrate": winrate(sum(1 for m in support if m.win), len(support))},
        },
        "best_matchups": sorted(matchups, key=lambda x: x["winrate"], reverse=True)[:5],
        "worst_matchups": sorted(matchups, key=lambda x: x["winrate"])[:5],
        "objectives_stolen": sum(getattr(m, "objectives_stolen", 0) or 0 for m in matches),
        "first_blood_count": sum(1 for m in matches if getattr(m, "first_blood", False)),
        "first_blood_pct": round(sum(1 for m in matches if getattr(m, "first_blood", False)) / total * 100, 1),
        "pentas": sum(getattr(m, "penta_kills", 0) or 0 for m in matches),
        "quadras": sum(getattr(m, "quadra_kills", 0) or 0 for m in matches),
        "triples": sum(getattr(m, "triple_kills", 0) or 0 for m in matches),
        "doubles": sum(getattr(m, "double_kills", 0) or 0 for m in matches),
        "avg_vision": round(sum(getattr(m, "vision_score", 0) or 0 for m in matches) / total, 1),
        "avg_time_dead_min": round(sum(getattr(m, "time_dead_sec", 0) or 0 for m in matches) / total / 60, 1),
        "avg_champ_level": round(sum(getattr(m, "champ_level", 0) or 0 for m in matches) / total, 1),
        "surrendered_pct": round(sum(1 for m in matches if getattr(m, "surrendered", False)) / total * 100, 1),
    }

# ─── BUILD COMPARISON ────────────────────────────────────


def _build_stats(matches):
    if not matches:
        return None

    wins = sum(1 for m in matches if m.win)
    total = len(matches)
    kills = [m.kills for m in matches]
    deaths = [m.deaths for m in matches]
    assists = [m.assists for m in matches]
    damages = [m.damage_dealt for m in matches if m.damage_dealt]
    cs_list = [m.cs for m in matches if m.cs]
    durs = [m.duration_min for m in matches]

    item_counter = Counter()
    for m in matches:
        if m.own_items:
            for item_id in m.own_items.split(","):
                if item_id.strip():
                    item_counter[item_id.strip()] += 1
    top_items = [item_id for item_id, _ in item_counter.most_common(6)]

    return {
        "games": total,
        "wins": wins,
        "losses": total - wins,
        "winrate": winrate(wins, total),
        "avg_kills": avg(kills),
        "avg_deaths": avg(deaths),
        "avg_assists": avg(assists),
        "avg_kda": round((sum(kills) + sum(assists)) / max(sum(deaths), 1), 2),
        "avg_damage": int(avg(damages)) if damages else 0,
        "avg_cs": avg(cs_list) if cs_list else 0,
        "avg_duration": avg(durs),
        "top_items": top_items,
    }


def calc_build_comparison(matches):
    ap_matches = [m for m in matches if m.build == "AP"]
    ad_matches = [m for m in matches if m.build == "AD"]
    return {"ap": _build_stats(ap_matches), "ad": _build_stats(ad_matches)}

# ─── RECOMMENDATION ──────────────────────────────────────


def calc_recommendation(build_comparison):
    ap = build_comparison.get("ap")
    ad = build_comparison.get("ad")
    if not ap and not ad:
        return None
    if not ap or ap["games"] < 5:
        return {"type": "info", "message": "Not enough AP Shaco games to compare builds yet."}
    if not ad or ad["games"] < 5:
        return {"type": "ap", "message": f"You mainly play AP Shaco with a {ap['winrate']}% winrate. Try AD to compare!"}
    diff = round(ap["winrate"] - ad["winrate"], 1)
    if diff >= 10:
        return {"type": "ap", "message": f"You perform significantly better with AP Shaco. Your winrate is {diff}% higher than AD ({ap['winrate']}% vs {ad['winrate']}%).", "badge": "AP Recommended"}
    elif diff <= -10:
        return {"type": "ad", "message": f"You perform significantly better with AD Shaco. Your winrate is {abs(diff)}% higher ({ad['winrate']}% vs {ap['winrate']}%).", "badge": "AD Recommended"}
    elif diff > 0:
        return {"type": "ap", "message": f"AP Shaco edges ahead with a {diff}% higher winrate ({ap['winrate']}% vs {ad['winrate']}%). Both are viable.", "badge": "Slight AP Edge"}
    elif diff < 0:
        return {"type": "ad", "message": f"AD Shaco edges ahead with a {abs(diff)}% higher winrate ({ad['winrate']}% vs {ap['winrate']}%). Both are viable.", "badge": "Slight AD Edge"}
    else:
        return {"type": "neutral", "message": f"Your performance with AP and AD Shaco is identical ({ap['winrate']}%). Play what you enjoy!", "badge": "Both Equal"}

# ─── BEST CONDITIONS ─────────────────────────────────────


def calc_best_conditions(matches):
    MIN_GAMES = 5
    conditions = []

    for build in ["AP", "AD"]:
        group = [m for m in matches if m.build == build]
        if len(group) >= MIN_GAMES:
            w = sum(1 for m in group if m.win)
            conditions.append({"label": f"{build} Shaco", "category": "build", "winrate": winrate(w, len(group)), "games": len(group)})

    for side in ["blue", "red"]:
        group = [m for m in matches if m.side == side]
        if len(group) >= MIN_GAMES:
            w = sum(1 for m in group if m.win)
            conditions.append({"label": f"{side.capitalize()} side", "category": "side", "winrate": winrate(w, len(group)), "games": len(group)})

    for label, group in [
        ("Short games (≤25m)", [m for m in matches if m.duration_min <= 25]),
        ("Mid games (26-35m)", [m for m in matches if 25 < m.duration_min <= 35]),
        ("Long games (36m+)", [m for m in matches if m.duration_min > 35]),
    ]:
        if len(group) >= MIN_GAMES:
            w = sum(1 for m in group if m.win)
            conditions.append({"label": label, "category": "duration", "winrate": winrate(w, len(group)), "games": len(group)})

    for role, pos in [("Jungle", "JUNGLE"), ("Support", "UTILITY")]:
        group = [m for m in matches if m.position == pos]
        if len(group) >= MIN_GAMES:
            w = sum(1 for m in group if m.win)
            conditions.append({"label": f"{role} Shaco", "category": "role", "winrate": winrate(w, len(group)), "games": len(group)})

    if not conditions:
        return None

    by_category = {}
    for c in conditions:
        cat = c["category"]
        if cat not in by_category or c["winrate"] > by_category[cat]["winrate"]:
            by_category[cat] = c

    best_list = sorted(by_category.values(), key=lambda x: x["winrate"], reverse=True)
    parts = [
        by_category.get("build", {}).get("label", ""),
        by_category.get("side", {}).get("label", ""),
        by_category.get("duration", {}).get("label", "")
    ]
    parts = [p for p in parts if p]
    insight = ("Your best setup is " + ", ".join(parts) + ".") if parts else "Keep playing to unlock more insights."
    return {"conditions": best_list, "insight": insight}

# ─── STREAKS & FORM ──────────────────────────────────────


def calc_streaks(matches):
    if not matches:
        return {"current": 0, "current_type": None, "best_win": 0, "best_loss": 0}

    valid = sorted([m for m in matches if m.duration_min > 4], key=lambda m: m.game_timestamp or 0, reverse=True)
    if not valid:
        return {"current": 0, "current_type": None, "best_win": 0, "best_loss": 0}

    current_type = valid[0].win
    current = 0
    for m in valid:
        if m.win == current_type:
            current += 1
        else:
            break

    best_win = best_loss = cur_win = cur_loss = 0
    for m in valid:
        if m.win:
            cur_win += 1
            cur_loss = 0
        else:
            cur_loss += 1
            cur_win = 0
        best_win = max(best_win, cur_win)
        best_loss = max(best_loss, cur_loss)

    return {"current": current, "current_type": "win" if current_type else "loss", "best_win": best_win, "best_loss": best_loss}


def calc_recent_form(matches):
    valid = sorted([m for m in matches if m.duration_min > 4], key=lambda m: m.game_timestamp or 0, reverse=True)

    def wr_slice(n):
        s = valid[:n]
        if not s:
            return None
        w = sum(1 for m in s if m.win)
        return {"games": len(s), "wins": w, "winrate": winrate(w, len(s))}

    return {"last10": wr_slice(10), "last20": wr_slice(20), "last50": wr_slice(50)}


def calc_most_played_with(matches):
    ally_stats = defaultdict(lambda: {"wins": 0, "total": 0})
    for m in matches:
        if not m.ally_champs or m.duration_min <= 4:
            continue
        for champ in m.ally_champs.split(","):
            champ = champ.strip()
            if champ:
                ally_stats[champ]["total"] += 1
                if m.win:
                    ally_stats[champ]["wins"] += 1

    result = [
        {"champ": c, "wins": d["wins"], "total": d["total"], "winrate": winrate(d["wins"], d["total"])}
        for c, d in ally_stats.items() if d["total"] >= 3
    ]
    return sorted(result, key=lambda x: x["total"], reverse=True)[:8]

# ─── RECENT MATCHES ──────────────────────────────────────


def _build_recent(matches):
    result = []
    for m in matches:
        participants = []
        if m.participants_json:
            try:
                raw = json.loads(m.participants_json)
                for p in raw:
                    p["item_ids"] = p.pop("items", p.get("item_ids", []))
                    if "champion" not in p and "championName" in p:
                        p["champion"] = p["championName"]
                    if "team" not in p and "teamId" in p:
                        p["team"] = "blue" if p["teamId"] == 100 else "red"
                    if "is_me" not in p:
                        p["is_me"] = (p.get("puuid") == m.puuid)
                participants = raw
            except Exception:
                participants = []

        result.append({
            "match_id": m.match_id,
            "win": m.win,
            "kills": m.kills,
            "deaths": m.deaths,
            "assists": m.assists,
            "build": m.build,
            "duration_min": m.duration_min,
            "cs": m.cs or 0,
            "damage_dealt": m.damage_dealt or 0,
            "gold_earned": m.gold_earned or 0,
            "game_timestamp": m.game_timestamp or 0,
            "ally_champs": m.ally_champs.split(",") if m.ally_champs else [],
            "enemy_champs": m.enemy_champs.split(",") if m.enemy_champs else [],
            "position": m.position or "JUNGLE",
            "side": m.side or "",
            "own_items": [int(i) for i in m.own_items.split(",") if i] if m.own_items else [],
            "participants": participants,
            "queue_type": getattr(m, "queue_type", "ranked_solo") or "ranked_solo",
            "objectives_stolen": getattr(m, "objectives_stolen", 0) or 0,
            "first_blood": getattr(m, "first_blood", False) or False,
            "largest_multi_kill": getattr(m, "largest_multi_kill", 0) or 0,
            "penta_kills": getattr(m, "penta_kills", 0) or 0,
            "quadra_kills": getattr(m, "quadra_kills", 0) or 0,
            "triple_kills": getattr(m, "triple_kills", 0) or 0,
            "double_kills": getattr(m, "double_kills", 0) or 0,
            "champ_level": getattr(m, "champ_level", 0) or 0,
            "time_dead_sec": getattr(m, "time_dead_sec", 0) or 0,
            "vision_score": getattr(m, "vision_score", 0) or 0,
            "summoner1_id": getattr(m, "summoner1_id", 0) or 0,
            "summoner2_id": getattr(m, "summoner2_id", 0) or 0,
            "surrendered": getattr(m, "surrendered", False) or False,
            "bans_json": getattr(m, "bans_json", "") or "",
        })
    return result

# ─── ENDPOINTS ───────────────────────────────────────────


@app.get("/")
def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/search-player")
def search_player_page(request: Request, name: str = "", tag: str = "EUW", region: str = "euw1"):
    """
    Entry point when user submits the search form.
    - Accepts 'nombre#tag' format in the name field
    - If player in DB → redirect to profile
    - If not in DB → go to loading page (which fetches in background)
    """
    if not name:
        return templates.TemplateResponse("index.html", {
            "request": request, "error": "Please enter a summoner name."
        })

    name = name.strip()
    region = region.lower()

    # Handle "nombre#tag" format typed directly in name field
    if "#" in name:
        parts = name.split("#", 1)
        name = parts[0].strip()
        tag = parts[1].strip()

    tag = tag.strip().lstrip("#")

    db = SessionLocal()
    try:
        # Search by name (ignoring tag, case insensitive, partial match)
        exists = db.query(ShacoMatch).filter_by(region=region).filter(
            ShacoMatch.summoner_name.ilike(f"{name}%")
        ).first()
    finally:
        db.close()

    from fastapi.responses import RedirectResponse
    if exists:
        return RedirectResponse(url=f"/player-page/{region}/{name}?tag={tag}", status_code=302)
    else:
        return RedirectResponse(url=f"/loading/{region}/{name}?tag={tag}", status_code=302)


@app.get("/search")
def search_players(q: str = ""):
    if len(q) < 2:
        return {"results": []}

    # Strip #tag from query if present, search by name only
    name_q = q.split("#")[0].strip()

    db = SessionLocal()
    try:
        rows = db.query(ShacoMatch.summoner_name, ShacoMatch.region).filter(
            ShacoMatch.summoner_name.ilike(f"%{name_q}%")
        ).distinct().limit(8).all()
        return {"results": [{"name": r.summoner_name, "region": r.region} for r in rows]}
    finally:
        db.close()


@app.get("/player/{region}/{summoner_name}")
def get_player(region: str, summoner_name: str, tag: str = "EUW"):
    db = SessionLocal()
    try:
        matches = db.query(ShacoMatch).filter_by(region=region.lower()).filter(
            ShacoMatch.summoner_name.ilike(f"{summoner_name}%")
        ).order_by(ShacoMatch.created_at.desc()).all()

        if not matches:
            raise HTTPException(status_code=404, detail=f"No data for {summoner_name}")

        return {
            "summoner": matches[0].summoner_name,
            "region": region,
            "stats": calc_stats(matches),
            "recent_matches": _build_recent(matches[:10]),
        }
    finally:
        db.close()

# ─── CORE SAVE FUNCTION (reused by fetch + seeding) ─────────────────


def _save_match_stats(stats: dict, puuid: str, summoner_name: str, tag: str, region: str, db) -> bool:
    """Save a match to DB. Returns True if new, False if already existed."""
    existe = db.query(ShacoMatch).filter_by(match_id=stats["match_id"]).first()
    if existe:
        return False

    db.add(ShacoMatch(
        match_id=stats["match_id"], puuid=puuid,
        summoner_name=f"{summoner_name}#{tag}", region=region.lower(),
        win=stats["win"], kills=stats["kills"], deaths=stats["deaths"],
        assists=stats["assists"], build=stats["build"],
        duration_min=stats["duration"], cs=stats["cs"],
        damage_dealt=stats["damage_dealt"], gold_earned=stats["gold_earned"],
        game_timestamp=stats["game_timestamp"],
        ally_champs=stats["ally_champs"], enemy_champs=stats["enemy_champs"],
        position=stats["position"], side=stats["side"],
        own_items=stats["own_items"], participants_json=stats["participants_json"],
        queue_type=stats.get("queue_type", "ranked_solo"),
        objectives_stolen=stats.get("objectives_stolen", 0),
        first_blood=stats.get("first_blood", False),
        largest_multi_kill=stats.get("largest_multi_kill", 0),
        double_kills=stats.get("double_kills", 0),
        triple_kills=stats.get("triple_kills", 0),
        quadra_kills=stats.get("quadra_kills", 0),
        penta_kills=stats.get("penta_kills", 0),
        champ_level=stats.get("champ_level", 0),
        time_dead_sec=stats.get("time_dead_sec", 0),
        vision_score=stats.get("vision_score", 0),
        wards_placed=stats.get("wards_placed", 0),
        control_wards=stats.get("control_wards", 0),
        cc_dealt=stats.get("cc_dealt", 0),
        summoner1_id=stats.get("summoner1_id", 0),
        summoner2_id=stats.get("summoner2_id", 0),
        surrendered=stats.get("surrendered", False),
        bans_json=stats.get("bans_json", ""),
        dragon_kills=stats.get("dragon_kills", 0),
        baron_kills=stats.get("baron_kills", 0),
        void_grub_kills=stats.get("void_grub_kills", 0),
        rift_herald_kills=stats.get("rift_herald_kills", 0),
        turret_kills=stats.get("turret_kills", 0),
        first_tower_kill=stats.get("first_tower_kill", False),
        team_kills=stats.get("team_kills", 0),
        team_dragons=stats.get("team_dragons", 0),
        team_barons=stats.get("team_barons", 0),
        damage_taken=stats.get("damage_taken", 0),
        magic_damage_dealt=stats.get("magic_damage_dealt", 0),
        physical_damage_dealt=stats.get("physical_damage_dealt", 0),
        true_damage_dealt=stats.get("true_damage_dealt", 0),
        total_damage_dealt=stats.get("total_damage_dealt", 0),
        damage_to_objectives=stats.get("damage_to_objectives", 0),
        damage_to_turrets=stats.get("damage_to_turrets", 0),
        healing_done=stats.get("healing_done", 0),
        largest_killing_spree=stats.get("largest_killing_spree", 0),
        killing_sprees=stats.get("killing_sprees", 0),
        longest_time_alive=stats.get("longest_time_alive", 0),
        first_blood_assist=stats.get("first_blood_assist", False),
        first_tower_assist=stats.get("first_tower_assist", False),
        wards_killed=stats.get("wards_killed", 0),
        enemy_jungle_cs=stats.get("enemy_jungle_cs", 0),
        ally_jungle_cs=stats.get("ally_jungle_cs", 0),
        gold_spent=stats.get("gold_spent", 0),
        spell1_casts=stats.get("spell1_casts", 0),
        spell2_casts=stats.get("spell2_casts", 0),
        spell3_casts=stats.get("spell3_casts", 0),
        spell4_casts=stats.get("spell4_casts", 0),
        summoner1_casts=stats.get("summoner1_casts", 0),
        summoner2_casts=stats.get("summoner2_casts", 0),
        patch=stats.get("patch", ""),
        game_version=stats.get("game_version", ""),
        shaco_raw_json=stats.get("shaco_raw_json", ""),
    ))
    return True


def _do_fetch(region: str, summoner_name: str, tag: str, count: int = 100):
    """Background worker: fetch matches and update _fetch_status."""
    from shaco import load_item_data, get_match_ids, get_match, get_shaco_stats

    key = _fetch_key(region, summoner_name)

    # Guard: if already running, don't start a second fetch
    if _fetch_status.get(key, {}).get("status") == "running":
        return

    _fetch_status[key] = {"status": "running", "progress": 0, "total": 0, "nuevas": 0, "error": None, "games_in_db": 0}
    _fetch_lock.acquire()
    db = SessionLocal()

    try:
        cluster = get_cluster(region)

        # Try to find player with any common tag
        try:
            puuid, real_tag = find_puuid_any_tag(summoner_name, tag, cluster, region)
        except Exception:
            _fetch_status[key]["status"] = "not_found"
            _fetch_status[key]["error"] = f"Player '{summoner_name}' not found on Riot ({region.upper()})."
            return

        # Use the real tag from now on
        tag = real_tag

        item_data, _ = load_item_data()
        match_ids = get_match_ids(puuid, count=count)
        _fetch_status[key]["total"] = len(match_ids)
        nuevas = 0

        for i, mid in enumerate(match_ids):
            try:
                time.sleep(1.3)
                match = get_match(mid)
                stats = get_shaco_stats(match, puuid, item_data)
                if stats and _save_match_stats(stats, puuid, summoner_name, tag, region, db):
                    nuevas += 1
                    if nuevas % 5 == 0:
                        db.commit()
            except Exception as e:
                print(f"[fetch] skip {mid}: {e}")
                continue

            _fetch_status[key]["progress"] = i + 1
            _fetch_status[key]["nuevas"] = nuevas
            _fetch_status[key]["games_in_db"] = nuevas

        db.commit()
        _clear_stats_cache()

        # If no new Shaco games found, check if they have any in DB at all
        if nuevas == 0 and len(match_ids) > 0:
            existing_count = db.query(ShacoMatch).filter_by(region=region.lower()).filter(
                ShacoMatch.puuid == puuid
            ).count()
            if existing_count == 0:
                _fetch_status[key]["status"] = "no_shaco"
                _fetch_status[key]["error"] = f"{summoner_name}#{tag} has no ranked Shaco games."
                return

        try:
            rank_url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
            rank_data = requests.get(rank_url, headers={"X-Riot-Token": os.getenv("RIOT_API_KEY")}, timeout=5).json()

            tier = division = ""
            lp = wins = losses = 0
            if isinstance(rank_data, list):
                for entry in rank_data:
                    if entry.get("queueType") == "RANKED_SOLO_5x5":
                        tier = entry.get("tier", "")
                        division = entry.get("rank", "")
                        lp = entry.get("leaguePoints", 0)
                        wins = entry.get("wins", 0)
                        losses = entry.get("losses", 0)
                        break

            from datetime import datetime as _dt
            db2 = SessionLocal()
            try:
                existing = db2.query(ShacoPlayer).filter_by(puuid=puuid).first()
                if existing:
                    existing.summoner_name = f"{summoner_name}#{tag}"
                    existing.tier = tier
                    existing.division = division
                    existing.lp = lp
                    existing.wins = wins
                    existing.losses = losses
                    existing.updated_at = _dt.utcnow()
                else:
                    db2.add(ShacoPlayer(
                        puuid=puuid,
                        summoner_name=f"{summoner_name}#{tag}",
                        region=region.lower(),
                        tier=tier,
                        division=division,
                        lp=lp,
                        wins=wins,
                        losses=losses
                    ))
                db2.commit()
            finally:
                db2.close()
        except Exception as _e:
            print(f"[rank save] {_e}")

        _fetch_status[key]["status"] = "done"
        print(f"[fetch] {summoner_name}#{tag} → {nuevas} new games")

    except Exception as e:
        import traceback
        traceback.print_exc()
        _fetch_status[key]["status"] = "error"
        _fetch_status[key]["error"] = str(e)

    finally:
        db.close()
        _fetch_lock.release()


@app.get("/fetch/{region}/{summoner_name}/{tag}")
def fetch_player(region: str, summoner_name: str, tag: str, bg: bool = False, count: int = 100):
    """
    Fetch matches for a player.
    bg=True  → run in background thread, return immediately
    bg=False → run synchronously
    """
    key = _fetch_key(region, summoner_name)

    if _fetch_status.get(key, {}).get("status") == "running":
        return {"message": "already running", "key": key}

    if bg:
        t = threading.Thread(target=_do_fetch, args=(region, summoner_name, tag, count), daemon=True)
        t.start()
        return {"message": "fetch started", "key": key}
    else:
        _do_fetch(region, summoner_name, tag, count)
        status = _fetch_status.get(key, {})
        return {"message": f"Fetched {status.get('nuevas', 0)} new Shaco games for {summoner_name}#{tag}"}


@app.get("/fetch-status/{region}/{summoner_name}")
def fetch_status_endpoint(region: str, summoner_name: str):
    key = _fetch_key(region, summoner_name)
    status = _fetch_status.get(key, {"status": "unknown"})

    db = SessionLocal()
    try:
        count = db.query(ShacoMatch).filter_by(region=region.lower()).filter(
            ShacoMatch.summoner_name.ilike(f"{summoner_name}%")
        ).count()
        status["games_in_db"] = count
    finally:
        db.close()

    return status


@app.get("/player-page/{region}/{summoner_name}")
def player_page(
    request: Request,
    region: str,
    summoner_name: str,
    tag: str = "EUW",
    build: str = "all",
    position: str = "all",
    side: str = "all",
    limit: str = "50",
):
    db = SessionLocal()
    try:
        exists = db.query(ShacoMatch).filter_by(region=region.lower()).filter(
            ShacoMatch.summoner_name.ilike(f"{summoner_name}%")
        ).first()

        if not exists:
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=f"/loading/{region}/{summoner_name}?tag={tag}", status_code=302)

        query = db.query(ShacoMatch).filter_by(region=region.lower()).filter(
            ShacoMatch.summoner_name.ilike(f"{summoner_name}%")
        )

        if build != "all":
            query = query.filter(ShacoMatch.build == build.upper())

        if position != "all":
            pos_map = {"jungle": "JUNGLE", "support": "UTILITY"}
            query = query.filter(ShacoMatch.position == pos_map.get(position, position.upper()))

        if side != "all":
            query = query.filter(ShacoMatch.side == side.lower())

        matches = query.order_by(ShacoMatch.game_timestamp.desc()).all()
        if not matches:
            raise HTTPException(status_code=404, detail="Player not found")

        all_matches = db.query(ShacoMatch).filter_by(region=region.lower()).filter(
            ShacoMatch.summoner_name.ilike(f"{summoner_name}%")
        ).order_by(ShacoMatch.game_timestamp.desc()).all()

        patch = get_current_patch()

        rank_info = get_rank(all_matches[0].puuid, region.lower()) if all_matches and all_matches[0].puuid else None
        streaks = calc_streaks(all_matches)
        recent_form = calc_recent_form(all_matches)
        most_with = calc_most_played_with(matches)
        build_comp = calc_build_comparison(all_matches)
        recommendation = calc_recommendation(build_comp)
        best_conditions = calc_best_conditions(all_matches)

        return templates.TemplateResponse("player.html", {
            "request": request,
            "summoner": all_matches[0].summoner_name,
            "summoner_tag": all_matches[0].summoner_name.split("#")[1] if "#" in all_matches[0].summoner_name else tag,
            "region": region,
            "stats": calc_stats(matches),
            "full_stats": calc_stats(all_matches),
            "recent_matches": _build_recent(matches if limit == "all" else matches[:50]),
            "active_build": build,
            "active_position": position,
            "active_side": side,
            "total_unfiltered": len(all_matches),
            "patch": patch,
            "perk_icons": get_perk_icons(patch),
            "spell_icons": get_spell_icons(patch),
            "rank_info": rank_info,
            "streaks": streaks,
            "recent_form": recent_form,
            "most_with": most_with,
            "build_comp": build_comp,
            "recommendation": recommendation,
            "best_conditions": best_conditions,
            "puuid": all_matches[0].puuid if all_matches else "",
        })
    finally:
        db.close()

# ─── DRAFT RECOMMENDER ───────────────────────────────────


@app.get("/loading/{region}/{summoner_name}")
def loading_page(request: Request, region: str, summoner_name: str, tag: str = "EUW"):
    key = _fetch_key(region, summoner_name)
    current = _fetch_status.get(key, {})

    if current.get("status") not in ("running", "done"):
        t = threading.Thread(target=_do_fetch, args=(region, summoner_name, tag, 100), daemon=True)
        t.start()

    return templates.TemplateResponse("loading.html", {
        "request": request,
        "summoner": summoner_name,
        "tag": tag,
        "region": region.upper(),
        "region_lower": region.lower(),
    })

# ─── STATS PAGE ──────────────────────────────────────────────────────


def _stats_query(db, build: str, position: str, puuid: str):
    """Base filtered query for stats calculations."""
    q = db.query(ShacoMatch)

    if build and build != "all":
        q = q.filter(ShacoMatch.build == build.upper())

    if position and position != "all":
        pos_map = {"jungle": "JUNGLE", "support": "UTILITY", "mid": "MIDDLE", "top": "TOP", "bot": "BOTTOM"}
        q = q.filter(ShacoMatch.position == pos_map.get(position.lower(), position.upper()))

    if puuid:
        q = q.filter(ShacoMatch.puuid == puuid)

    return q


def _stats_query_fast(db, build: str, position: str, puuid: str):
    """Optimized query — only fetches columns needed for stats."""
    from sqlalchemy import text

    filters = []
    params = {}

    if build and build != "all":
        filters.append("build = :build")
        params["build"] = build.upper()

    if position and position != "all":
        pos_map = {
            "jungle": "JUNGLE",
            "support": "UTILITY",
            "mid": "MIDDLE",
            "top": "TOP",
            "bot": "BOTTOM",
        }
        filters.append("position = :position")
        params["position"] = pos_map.get(position.lower(), position.upper())

    if puuid:
        filters.append("puuid = :puuid")
        params["puuid"] = puuid

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    sql = text(f"""
        SELECT win, kills, deaths, assists, build, duration_min, position, side,
               own_items, ally_champs, enemy_champs,
               summoner1_id, summoner2_id,
               objectives_stolen, first_blood, first_tower_kill,
               team_dragons, team_barons, void_grub_kills, puuid
        FROM shaco_matches
        {where}
    """)

    return db.execute(sql, params).mappings().fetchall()


def _wr(wins, total):
    return round(wins / total * 100, 1) if total > 0 else 0


@app.get("/stats-data")
def stats_data(build: str = "all", position: str = "all", puuid: str = "", timeframe: str = "all"):
    """Returns all stat blocks as JSON using a single light query."""
    cache_key = f"{build}|{position}|{puuid}|{timeframe}"
    cached = _stats_cache.get(cache_key)
    if cached and (_cache_time.time() - cached["ts"]) < _CACHE_TTL:
        return cached["data"]

    from sqlalchemy import text
    from collections import defaultdict

    db = SessionLocal()
    try:
        filters, params = [], {}

        if build and build != "all":
            filters.append("build = :build")
            params["build"] = build.upper()

        if position and position != "all":
            pos_map = {
                "jungle": "JUNGLE",
                "support": "UTILITY",
                "mid": "MIDDLE",
                "top": "TOP",
                "bot": "BOTTOM",
            }
            filters.append("position = :position")
            params["position"] = pos_map.get(position.lower(), position.upper())

        if puuid:
            filters.append("puuid = :puuid")
            params["puuid"] = puuid

        # Timeframe filter — game_timestamp is stored in SECONDS (Unix epoch // 1000)
        import time as _time
        now = int(_time.time())  # seconds
        if timeframe == "30d":
            filters.append("game_timestamp > :ts_from")
            params["ts_from"] = now - 30 * 86400
        elif timeframe == "patch":
            filters.append("game_timestamp > :ts_from")
            params["ts_from"] = now - 14 * 86400  # ~2 weeks = 1 patch cycle

        where = ("WHERE " + " AND ".join(filters)) if filters else ""

        rows = db.execute(text(f"""
            SELECT win, kills, deaths, assists, build, duration_min, position, side,
                   own_items, ally_champs, enemy_champs,
                   summoner1_id, summoner2_id,
                   objectives_stolen, first_blood, first_tower_kill,
                   team_dragons, team_barons, void_grub_kills
            FROM shaco_matches
            {where}
        """), params).fetchall()

        if not rows:
            return {"error": "no data", "total": 0}

        total = len(rows)
        wins = sum(1 for m in rows if m[0])

        ap_g = ap_w = ad_g = ad_w = 0
        for m in rows:
            b = m[4]
            w = m[0]
            if b == "AP":
                ap_g += 1
                ap_w += 1 if w else 0
            elif b == "AD":
                ad_g += 1
                ad_w += 1 if w else 0

        wr_build = {
            "AP": {"games": ap_g, "wr": _wr(ap_w, ap_g)},
            "AD": {"games": ad_g, "wr": _wr(ad_w, ad_g)},
        }

        LANE_POS = ["top", "jungle", "mid", "bot", "support"]
        enemy_stats = defaultdict(lambda: {
            "wins": 0, "games": 0, "kills": 0, "deaths": 0, "assists": 0, "lane": "unknown"
        })

        for m in rows:
            champs = [c.strip() for c in (m[10] or "").split(",") if c.strip()]
            for i, champ in enumerate(champs[:5]):
                s = enemy_stats[champ]
                s["games"] += 1
                s["kills"] += (m[1] or 0)
                s["deaths"] += (m[2] or 0)
                s["assists"] += (m[3] or 0)
                s["lane"] = LANE_POS[i]
                if m[0]:
                    s["wins"] += 1

        vs_enemies = []
        for champ, s in enemy_stats.items():
            if s["games"] < 3:
                continue
            kda = round((s["kills"] + s["assists"]) / max(s["deaths"], 1) / s["games"], 2)
            vs_enemies.append({
                "champ": champ,
                "games": s["games"],
                "wr": _wr(s["wins"], s["games"]),
                "kda": kda,
                "lane": s["lane"],
            })
        vs_enemies.sort(key=lambda x: x["games"], reverse=True)

        ally_stats = defaultdict(lambda: {"wins": 0, "games": 0})
        for m in rows:
            for champ in (m[9] or "").split(","):
                champ = champ.strip()
                if not champ:
                    continue
                ally_stats[champ]["games"] += 1
                if m[0]:
                    ally_stats[champ]["wins"] += 1

        with_allies = [
            {"champ": c, "games": s["games"], "wr": _wr(s["wins"], s["games"])}
            for c, s in ally_stats.items() if s["games"] >= 3
        ]
        with_allies.sort(key=lambda x: x["games"], reverse=True)

        COMPONENT_IDS = {
            "1001", "1004", "1006", "1011", "1018", "1026", "1027", "1028", "1029", "1031",
            "1033", "1036", "1037", "1038", "1039", "1040", "1042", "1043", "1044", "1045",
            "1051", "1052", "1053", "1054", "1055", "1056", "1057", "1058", "1082", "1083",
            "2003", "2004", "2010", "2015", "2031", "2033", "2044", "2051", "2052", "2055",
            "3340", "3363", "3364", "3330", "3513", "2420", "2421", "2422", "2423",
        }

        item_stats = defaultdict(lambda: {"wins": 0, "games": 0})
        for m in rows:
            for item_id in (m[8] or "").split(","):
                item_id = item_id.strip()
                if not item_id or item_id in COMPONENT_IDS:
                    continue
                item_stats[item_id]["games"] += 1
                if m[0]:
                    item_stats[item_id]["wins"] += 1

        wr_items = [
            {"item_id": iid, "games": s["games"], "wr": _wr(s["wins"], s["games"])}
            for iid, s in item_stats.items() if s["games"] >= 10
        ]
        wr_items.sort(key=lambda x: x["games"], reverse=True)

        spell_stats = defaultdict(lambda: {"wins": 0, "games": 0})
        for m in rows:
            for sid in [m[11], m[12]]:
                if sid:
                    spell_stats[sid]["games"] += 1
                    if m[0]:
                        spell_stats[sid]["wins"] += 1

        wr_spells = [
            {"spell_id": sid, "games": s["games"], "wr": _wr(s["wins"], s["games"])}
            for sid, s in spell_stats.items() if s["games"] >= 5
        ]
        wr_spells.sort(key=lambda x: x["games"], reverse=True)

        side_stats = defaultdict(lambda: {"wins": 0, "games": 0})
        for m in rows:
            s = m[7] or "unknown"
            side_stats[s]["games"] += 1
            if m[0]:
                side_stats[s]["wins"] += 1
        wr_side = {
            s: {"games": v["games"], "wr": _wr(v["wins"], v["games"])}
            for s, v in side_stats.items()
        }

        dur = {
            "≤25 min": {"w": 0, "g": 0},
            "26-35 min": {"w": 0, "g": 0},
            "36+ min": {"w": 0, "g": 0},
        }
        for m in rows:
            d = m[5] or 0
            k = "≤25 min" if d <= 25 else ("26-35 min" if d <= 35 else "36+ min")
            dur[k]["g"] += 1
            if m[0]:
                dur[k]["w"] += 1
        wr_duration = {k: {"games": v["g"], "wr": _wr(v["w"], v["g"])} for k, v in dur.items()}

        fb_g = fb_w = nfb_g = nfb_w = 0
        for m in rows:
            if m[14]:
                fb_g += 1
                fb_w += 1 if m[0] else 0
            else:
                nfb_g += 1
                nfb_w += 1 if m[0] else 0

        wr_first_blood = {
            "With first blood": {"games": fb_g, "wr": _wr(fb_w, fb_g)},
            "Without first blood": {"games": nfb_g, "wr": _wr(nfb_w, nfb_g)},
        }

        drag_stats = defaultdict(lambda: {"wins": 0, "games": 0})
        for m in rows:
            d = min(m[16] or 0, 4)
            label = f"{d}+ dragons" if d == 4 else f"{d} dragon{'s' if d != 1 else ''}"
            drag_stats[label]["games"] += 1
            if m[0]:
                drag_stats[label]["wins"] += 1
        wr_dragons = {
            k: {"games": v["games"], "wr": _wr(v["wins"], v["games"])}
            for k, v in sorted(drag_stats.items())
        }

        by_g = by_w = bn_g = bn_w = 0
        for m in rows:
            if (m[17] or 0) > 0:
                by_g += 1
                by_w += 1 if m[0] else 0
            else:
                bn_g += 1
                bn_w += 1 if m[0] else 0

        wr_baron = {
            "with": {"games": by_g, "wr": _wr(by_w, by_g)},
            "without": {"games": bn_g, "wr": _wr(bn_w, bn_g)},
        }

        vg_g = vg_w = nvg_g = nvg_w = 0
        for m in rows:
            if (m[18] or 0) >= 3:
                vg_g += 1
                vg_w += 1 if m[0] else 0
            else:
                nvg_g += 1
                nvg_w += 1 if m[0] else 0

        wr_voidgrubs = {
            "3+ grubs": {"games": vg_g, "wr": _wr(vg_w, vg_g)},
            "0-2 grubs": {"games": nvg_g, "wr": _wr(nvg_w, nvg_g)},
        }

        pos_stats = defaultdict(lambda: {"wins": 0, "games": 0})
        for m in rows:
            p = m[6] or "UNKNOWN"
            pos_stats[p]["games"] += 1
            if m[0]:
                pos_stats[p]["wins"] += 1

        wr_position = {
            p: {"games": v["games"], "wr": _wr(v["wins"], v["games"])}
            for p, v in sorted(pos_stats.items(), key=lambda x: -x[1]["games"])
        }

        ft_g = ft_w = nft_g = nft_w = 0
        for m in rows:
            if m[15]:
                ft_g += 1
                ft_w += 1 if m[0] else 0
            else:
                nft_g += 1
                nft_w += 1 if m[0] else 0

        wr_first_tower = {
            "With first tower": {"games": ft_g, "wr": _wr(ft_w, ft_g)},
            "Without first tower": {"games": nft_g, "wr": _wr(nft_w, nft_g)},
        }

        st_g = st_w = nst_g = nst_w = 0
        for m in rows:
            if (m[13] or 0) > 0:
                st_g += 1
                st_w += 1 if m[0] else 0
            else:
                nst_g += 1
                nst_w += 1 if m[0] else 0

        wr_stolen = {
            "With objective steal": {"games": st_g, "wr": _wr(st_w, st_g)},
            "Without objective steal": {"games": nst_g, "wr": _wr(nst_w, nst_g)},
        }

        counter_items = []

        result = {
            "total": total,
            "wins": wins,
            "wr": _wr(wins, total),
            "wr_build": wr_build,
            "vs_enemies": vs_enemies,
            "with_allies": with_allies,
            "wr_items": wr_items,
            "wr_spells": wr_spells,
            "wr_side": wr_side,
            "wr_duration": wr_duration,
            "wr_first_blood": wr_first_blood,
            "wr_dragons": wr_dragons,
            "wr_baron": wr_baron,
            "wr_voidgrubs": wr_voidgrubs,
            "wr_position": wr_position,
            "wr_first_tower": wr_first_tower,
            "wr_stolen": wr_stolen,
            "counter_items": counter_items,
        }

        _stats_cache[cache_key] = {"data": result, "ts": _cache_time.time()}
        return result

    finally:
        db.close()


@app.get("/top-shacos")
def top_shacos_page(request: Request):
    from sqlalchemy import text
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT
                summoner_name,
                region,
                COUNT(*) as games,
                SUM(CASE WHEN win THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN build = 'AP' THEN 1 ELSE 0 END) as ap_games,
                SUM(CASE WHEN build = 'AD' THEN 1 ELSE 0 END) as ad_games,
                AVG(kills) as avg_kills,
                AVG(deaths) as avg_deaths,
                AVG(assists) as avg_assists,
                MAX(game_timestamp) as last_game
            FROM shaco_matches
            GROUP BY summoner_name, region
            HAVING COUNT(*) >= 20
            ORDER BY games DESC
            LIMIT 100
        """)).fetchall()

        players = []
        for r in rows:
            games = r[2]
            wins = r[3]
            ap = r[4]
            ad = r[5]
            preferred_build = "AP" if ap >= ad else "AD"
            wr = round(wins / games * 100, 1) if games > 0 else 0
            kda = round((r[6] + r[8]) / max(r[7], 1), 2)
            name_parts = r[0].split("#")
            players.append({
                "name": name_parts[0],
                "tag": name_parts[1] if len(name_parts) > 1 else "",
                "full_name": r[0],
                "region": r[1],
                "games": games,
                "wins": wins,
                "wr": wr,
                "build": preferred_build,
                "ap_pct": round(ap / games * 100) if games > 0 else 0,
                "kda": kda,
                "last_game": r[9] or 0,
            })
    finally:
        db.close()

    return templates.TemplateResponse("top_shacos.html", {
        "request": request,
        "players": players,
    })


@app.get("/stats")
def stats_page(request: Request):
    patch = get_current_patch()
    return templates.TemplateResponse("stats.html", {"request": request, "patch": patch})


@app.get("/not-found")
def not_found_page(request: Request, name: str = "", region: str = ""):
    return templates.TemplateResponse("404.html", {
        "request": request, "name": name, "region": region
    }, status_code=404)


@app.get("/draft")
def draft_page(request: Request):
    patch = get_current_patch()
    return templates.TemplateResponse("draft.html", {"request": request, "patch": patch})


@app.post("/draft/recommend")
def draft_recommend(
    request: Request,
    ally1: str = "",
    ally2: str = "",
    ally3: str = "",
    ally4: str = "",
    enemy1: str = "",
    enemy2: str = "",
    enemy3: str = "",
    enemy4: str = "",
    enemy5: str = "",
    role: str = "jungle",
):
    from draft_engine import recommend_build

    allies = [a for a in [ally1, ally2, ally3, ally4] if a.strip()]
    enemies = [e for e in [enemy1, enemy2, enemy3, enemy4, enemy5] if e.strip()]
    result = recommend_build(allies, enemies, role)

    patch = get_current_patch()

    return templates.TemplateResponse("draft.html", {
        "request": request,
        "patch": patch,
        "result": result,
        "allies": allies,
        "enemies": enemies,
        "role": role,
    })