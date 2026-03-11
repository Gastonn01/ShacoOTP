import requests
import os
import time
import json
from dotenv import load_dotenv
from database import SessionLocal, ShacoMatch, init_db

load_dotenv()

API_KEY = os.getenv("RIOT_API_KEY")
SUMMONER_NAME = os.getenv("SUMMONER_NAME")
SUMMONER_TAG = os.getenv("SUMMONER_TAG")
CLUSTER = os.getenv("REGION_CLUSTER")
REGION = os.getenv("REGION")

HEADERS = {"X-Riot-Token": API_KEY}

def load_item_data():
    version = requests.get("https://ddragon.leagueoflegends.com/api/versions.json").json()[0]
    items_url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/item.json"
    return requests.get(items_url).json()["data"], version

def detect_build(items, item_data):
    ap_score = ad_score = 0
    for item_id in items:
        if item_id == 0:
            continue
        item = item_data.get(str(item_id))
        if not item:
            continue
        stats = item.get("stats", {})
        ap_score += stats.get("FlatMagicDamageMod", 0)
        ad_score += (stats.get("FlatPhysicalDamageMod", 0) +
                     stats.get("FlatArmorPenetrationMod", 0) +
                     stats.get("FlatCritChanceMod", 0) * 50)
    if ap_score > ad_score and ap_score > 20:
        return "AP"
    elif ad_score > ap_score and ad_score > 20:
        return "AD"
    return "UNKNOWN"

def get_puuid(name, tag):
    url = f"https://{CLUSTER}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()["puuid"]

def get_match_ids(puuid, count=150):
    all_ids = []
    start = 0
    while len(all_ids) < count:
        batch = min(100, count - len(all_ids))
        url = f"https://{CLUSTER}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
        r = requests.get(url, headers=HEADERS, params={"count": batch, "start": start, "queue": 420})
        r.raise_for_status()
        ids = r.json()
        if not ids:
            break
        all_ids.extend(ids)
        start += batch
        if len(ids) < batch:
            break
    return all_ids

def get_match(match_id):
    url = f"https://{CLUSTER}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()

def get_shaco_stats(match, puuid, item_data):
    participants = match["info"]["participants"]
    for p in participants:
        if p["puuid"] == puuid and p["championName"] == "Shaco":
            items = [p[f"item{i}"] for i in range(7)]
            shaco_team = p["teamId"]
            allies = []
            enemies = []

            all_participants = []
            for other in participants:
                is_me = other["puuid"] == puuid
                # items 0-5 = main slots, item6 = trinket
                main_items   = [other[f"item{i}"] for i in range(6)]
                trinket      = other.get("item6", 0)
                other_items  = main_items + [trinket]

                # Runes: keystone + primary path
                keystone_id  = 0
                primary_path = 0
                secondary_path = 0
                perks = other.get("perks", {})
                styles = perks.get("styles", [])
                if styles:
                    primary_path = styles[0].get("style", 0)
                    sels = styles[0].get("selections", [])
                    if sels:
                        keystone_id = sels[0].get("perk", 0)
                    if len(styles) > 1:
                        secondary_path = styles[1].get("style", 0)

                all_participants.append({
                    "champion":       other["championName"],
                    "name":           other.get("riotIdGameName") or other.get("riotIdName") or other["championName"],
                    "tag":            other.get("riotIdTagline", ""),
                    "team":           "blue" if other["teamId"] == 100 else "red",
                    "is_me":          is_me,
                    "kills":          other["kills"],
                    "deaths":         other["deaths"],
                    "assists":        other["assists"],
                    "cs":             other.get("totalMinionsKilled", 0) + other.get("neutralMinionsKilled", 0),
                    "slots":          [i for i in main_items if i != 0],
                    "trinket":        trinket,
                    "keystone_id":    keystone_id,
                    "primary_path":   primary_path,
                    "secondary_path": secondary_path,
                    "summoner1_id":   other.get("summoner1Id", 0),
                    "summoner2_id":   other.get("summoner2Id", 0),
                    "champ_level":    other.get("champLevel", 0),
                })
                if not is_me:
                    if other["teamId"] == shaco_team:
                        allies.append(other["championName"])
                    else:
                        enemies.append(other["championName"])

            side = "blue" if shaco_team == 100 else "red"
            position = p.get("teamPosition", "") or p.get("individualPosition", "") or "JUNGLE"
            if not position:
                position = "JUNGLE"

            # Team-level data: bans
            teams_data = match["info"].get("teams", [])
            bans = []
            for team in teams_data:
                for ban in team.get("bans", []):
                    bans.append({"champ_id": ban.get("championId", -1), "team": "blue" if team["teamId"] == 100 else "red"})

            # Multi-kill label
            pentas   = p.get("pentaKills", 0)
            quadras  = p.get("quadraKills", 0)
            triples  = p.get("tripleKills", 0)
            doubles  = p.get("doubleKills", 0)
            largest  = p.get("largestMultiKill", 0)

            # ── Team-level objectives ─────────────────────────────
            team_kills = team_dragons = team_barons = 0
            void_grubs = rift_herald = 0
            for team in match["info"].get("teams", []):
                obj = team.get("objectives", {})
                if team["teamId"] == shaco_team:
                    team_kills   = obj.get("champion",   {}).get("kills", 0)
                    team_dragons = obj.get("dragon",     {}).get("kills", 0)
                    team_barons  = obj.get("baron",      {}).get("kills", 0)
                    void_grubs   = obj.get("horde",      {}).get("kills", 0)
                    rift_herald  = obj.get("riftHerald", {}).get("kills", 0)

            raw_version = match["info"].get("gameVersion", "")
            parts = raw_version.split(".")
            patch = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else raw_version

            return {
                "match_id":              match["metadata"]["matchId"],
                "win":                   p["win"],
                "kills":                 p["kills"],
                "deaths":                p["deaths"],
                "assists":               p["assists"],
                "build":                 detect_build(items, item_data),
                "duration":              match["info"]["gameDuration"] // 60,
                "cs":                    p.get("totalMinionsKilled", 0) + p.get("neutralMinionsKilled", 0),
                "damage_dealt":          p.get("totalDamageDealtToChampions", 0),
                "gold_earned":           p.get("goldEarned", 0),
                "game_timestamp":        match["info"].get("gameStartTimestamp", 0) // 1000,
                "ally_champs":           ",".join(allies),
                "enemy_champs":          ",".join(enemies),
                "position":              position,
                "side":                  side,
                "own_items":             ",".join(str(i) for i in items if i != 0),
                "participants_json":     json.dumps(all_participants),
                "queue_type":            _queue_label(match["info"].get("queueId", 420)),
                # batch 1
                "objectives_stolen":         p.get("objectivesStolen", 0),
                "objectives_stolen_assists": p.get("objectivesStolenAssists", 0),
                "first_blood":               p.get("firstBloodKill", False),
                "first_blood_assist":        p.get("firstBloodAssist", False),
                "largest_multi_kill":        largest,
                "double_kills":              doubles,
                "triple_kills":              triples,
                "quadra_kills":              quadras,
                "penta_kills":               pentas,
                "champ_level":               p.get("champLevel", 0),
                "time_dead_sec":             p.get("totalTimeSpentDead", 0),
                "vision_score":              p.get("visionScore", 0),
                "wards_placed":              p.get("wardsPlaced", 0),
                "control_wards":             p.get("visionWardsBoughtInGame", 0),
                "cc_dealt":                  p.get("totalTimeCCDealt", 0),
                "summoner1_id":              p.get("summoner1Id", 0),
                "summoner2_id":              p.get("summoner2Id", 0),
                "summoner1_casts":           p.get("summoner1Casts", 0),
                "summoner2_casts":           p.get("summoner2Casts", 0),
                "surrendered":               p.get("gameEndedInSurrender", False),
                "bans_json":                 json.dumps(bans),
                # batch 2 — objectives
                "dragon_kills":       p.get("dragonKills", 0),
                "baron_kills":        p.get("baronKills", 0),
                "void_grub_kills":    void_grubs,
                "rift_herald_kills":  rift_herald,
                "turret_kills":       p.get("turretKills", 0),
                "first_tower_kill":   p.get("firstTowerKill", False),
                "team_kills":         team_kills,
                "team_dragons":       team_dragons,
                "team_barons":        team_barons,
                # batch 2 — damage
                "damage_taken":           p.get("totalDamageTaken", 0),
                "magic_damage_dealt":     p.get("magicDamageDealtToChampions", 0),
                "physical_damage_dealt":  p.get("physicalDamageDealtToChampions", 0),
                "true_damage_dealt":      p.get("trueDamageDealtToChampions", 0),
                "total_damage_dealt":     p.get("totalDamageDealt", 0),
                "damage_to_objectives":   p.get("damageDealtToObjectives", 0),
                "damage_to_turrets":      p.get("damageDealtToTurrets", 0),
                "healing_done":           p.get("totalHeal", 0),
                # batch 2 — combat
                "largest_killing_spree":  p.get("largestKillingSpree", 0),
                "killing_sprees":         p.get("killingSprees", 0),
                "longest_time_alive":     p.get("longestTimeSpentLiving", 0),
                "first_tower_assist":     p.get("firstTowerAssist", False),
                "wards_killed":           p.get("wardsKilled", 0),
                "enemy_jungle_cs":        p.get("totalEnemyJungleMinionsKilled", 0),
                "ally_jungle_cs":         p.get("totalAllyJungleMinionsKilled", 0),
                "gold_spent":             p.get("goldSpent", 0),
                # batch 2 — spell casts
                "spell1_casts":     p.get("spell1Casts", 0),
                "spell2_casts":     p.get("spell2Casts", 0),
                "spell3_casts":     p.get("spell3Casts", 0),
                "spell4_casts":     p.get("spell4Casts", 0),
                # meta
                "patch":          patch,
                "game_version":   raw_version,
                "shaco_raw_json": json.dumps(p),
            }
    return None

QUEUE_MAP = {
    420: "ranked_solo",
    440: "ranked_flex",
    450: "aram",
    400: "normal_draft",
    430: "normal_blind",
    900: "urf",
    1020: "one_for_all",
}

def _queue_label(queue_id):
    return QUEUE_MAP.get(queue_id, "other")

def save_match(stats, puuid):
    db = SessionLocal()
    try:
        existe = db.query(ShacoMatch).filter_by(match_id=stats["match_id"]).first()
        if existe:
            return False
        match = ShacoMatch(
            match_id=stats["match_id"],
            puuid=puuid,
            summoner_name=f"{SUMMONER_NAME}#{SUMMONER_TAG}",
            region=REGION,
            win=stats["win"],
            kills=stats["kills"],
            deaths=stats["deaths"],
            assists=stats["assists"],
            build=stats["build"],
            duration_min=stats["duration"],
            cs=stats["cs"],
            damage_dealt=stats["damage_dealt"],
            gold_earned=stats["gold_earned"],
            game_timestamp=stats["game_timestamp"],
            ally_champs=stats["ally_champs"],
            enemy_champs=stats["enemy_champs"],
            position=stats["position"],
            side=stats["side"],
            own_items=stats["own_items"],
            participants_json=stats["participants_json"],
            queue_type=stats.get("queue_type", "ranked_solo"),
        )
        db.add(match)
        db.commit()
        return True
    finally:
        db.close()

if __name__ == "__main__":
    init_db()
    print("Cargando items...")
    item_data, version = load_item_data()
    print(f"Patch: {version}")

    print(f"\nBuscando partidas de {SUMMONER_NAME}#{SUMMONER_TAG}...\n")
    puuid = get_puuid(SUMMONER_NAME, SUMMONER_TAG)
    match_ids = get_match_ids(puuid, count=150)

    nuevas = 0
    shaco_games = []
    ap_wins = ap_total = ad_wins = ad_total = 0

    for mid in match_ids:
        try:
            time.sleep(1.2)
            match = get_match(mid)
            stats = get_shaco_stats(match, puuid, item_data)
            if not stats:
                continue
            guardada = save_match(stats, puuid)
            estado = "💾 NUEVA" if guardada else "⏭️  YA GUARDADA"
            resultado = "✅ WIN" if stats["win"] else "❌ LOSS"
            kda = f"{stats['kills']}/{stats['deaths']}/{stats['assists']}"
            print(f"{resultado} | {stats['build']:7} | {stats['position']:10} | {stats['side']:4} | {kda} | {stats['duration']}min | {estado}")
            shaco_games.append(stats)
            if guardada:
                nuevas += 1
            if stats["build"] == "AP":
                ap_total += 1
                if stats["win"]: ap_wins += 1
            elif stats["build"] == "AD":
                ad_total += 1
                if stats["win"]: ad_wins += 1
        except Exception as e:
            print(f"⚠️  Error en {mid}: {e}")
            continue

    total = len(shaco_games)
    wins = sum(1 for g in shaco_games if g["win"])
    print("\n" + "="*60)
    print(f"Total: {total} | Nuevas: {nuevas}" + (f" | WR: {wins/total*100:.1f}%" if total else ""))
    if ap_total: print(f"AP → {ap_wins}/{ap_total} ({ap_wins/ap_total*100:.1f}%)")
    if ad_total: print(f"AD → {ad_wins}/{ad_total} ({ad_wins/ad_total*100:.1f}%)")
