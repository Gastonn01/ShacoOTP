"""
Draft Build Recommender Engine — V4 Real Data
=============================================
Primary source: AP vs AD Shaco winrate per champion (Lolalytics Patch 16.5, Emerald+)
Fallback: heuristics for champions not in the dataset.
"""

from collections import defaultdict

# ─── AP/AD SPLIT WINRATE DATA (Lolalytics 16.5 Emerald+) ────────────────────
# Format: 'ChampName': (wr_ad, wr_ap)  — None means no data for that build
SHACO_WR_SPLIT = {
    "Aatrox": (53.71, 56.2),    "Ahri": (51.23, 56.0),      "Akali": (51.47, 55.7),
    "Akshan": (50.41, 55.0),    "Alistar": (51.95, 59.12),   "Ambessa": (49.65, 54.8),
    "Amumu": (53.2, 59.0),      "Anivia": (49.73, 50.78),    "Annie": (53.6, 57.07),
    "Aphelios": (53.09, 54.1),  "Ashe": (53.8, 53.2),        "Aurelion Sol": (48.25, 53.66),
    "Aurora": (51.91, 56.3),    "Azir": (55.42, 60.0),       "Bard": (51.21, 56.47),
    "Bel'Veth": (50.37, 54.21), "Blitzcrank": (52.6, 56.81), "Brand": (54.21, 55.4),
    "Braum": (52.99, 55.0),     "Briar": (47.43, 55.3),      "Caitlyn": (53.15, 56.02),
    "Camille": (50.0, 56.0),    "Cassiopeia": (53.5, 57.1),  "Corki": (49.97, 58.65),
    "Darius": (53.74, 54.9),    "Diana": (50.24, 53.74),     "Dr. Mundo": (49.8, 53.7),
    "Draven": (50.93, 54.89),   "Ekko": (52.92, 60.0),       "Elise": (51.92, 57.47),
    "Evelynn": (53.4, 53.2),    "Ezreal": (53.2, 57.0),      "Fiddlesticks": (50.9, 53.0),
    "Fiora": (50.61, 57.0),     "Fizz": (55.18, 55.0),       "Galio": (51.18, 56.1),
    "Gangplank": (53.11, 54.0), "Garen": (54.12, 56.8),      "Gnar": (51.35, 57.95),
    "Gragas": (53.33, 56.66),   "Graves": (51.33, 56.4),     "Gwen": (None, 53.1),
    "Hecarim": (48.95, 55.2),   "Heimerdinger": (51.4, 54.4),"Hwei": (55.65, 55.79),
    "Illaoi": (53.55, 56.0),    "Irelia": (49.66, 55.9),     "Ivern": (50.13, 53.14),
    "Janna": (48.7, 55.22),     "Jarvan IV": (48.67, 53.92), "Jax": (50.8, 58.2),
    "Jayce": (56.14, 58.0),     "Jhin": (51.92, 56.08),      "Jinx": (50.29, 53.2),
    "K'Sante": (54.83, 58.9),   "Kai'Sa": (52.85, 59.8),     "Karma": (52.2, 56.88),
    "Kassadin": (50.44, 54.0),  "Katarina": (53.48, 58.6),   "Kayle": (47.79, 51.52),
    "Kayn": (52.69, 56.7),      "Kennen": (52.62, 55.92),    "Kha'Zix": (48.7, 54.48),
    "Kled": (50.1, 55.73),      "Kog'Maw": (47.53, 55.2),    "LeBlanc": (53.35, 59.42),
    "Lee Sin": (53.41, 56.16),  "Leona": (51.73, 56.13),     "Lillia": (52.56, 57.08),
    "Lissandra": (52.17, 61.8), "Lulu": (51.15, 53.7),       "Lux": (49.88, 58.13),
    "Malphite": (50.4, 55.2),   "Malzahar": (52.01, 54.3),   "Maokai": (52.15, 59.96),
    "Master Yi": (53.98, 57.57),"Mel": (55.9, 59.0),         "Milio": (50.7, 52.49),
    "Miss Fortune": (50.77, 54.8),"Mordekaiser": (51.88, 54.76),"Morgana": (53.5, 58.2),
    "Naafiri": (49.0, 52.3),    "Nami": (49.75, 53.2),       "Nasus": (51.92, 59.12),
    "Nautilus": (52.77, 57.5),  "Neeko": (52.32, 54.06),     "Nidalee": (52.4, 53.4),
    "Nilah": (46.62, 60.54),    "Nocturne": (50.85, 54.84),  "Nunu & Willump": (49.52, 51.8),
    "Orianna": (55.1, 55.7),    "Ornn": (51.18, 53.78),      "Pantheon": (55.3, 59.9),
    "Poppy": (54.42, 55.02),    "Pyke": (52.0, 56.44),       "Qiyana": (49.4, 53.5),
    "Quinn": (53.3, 57.4),      "Rakan": (51.6, 56.48),      "Rammus": (51.4, 57.7),
    "Rek'Sai": (47.5, 53.0),    "Rell": (51.2, 57.94),       "Renata": (51.55, 58.47),
    "Renekton": (51.66, 56.75), "Rengar": (50.63, 54.67),    "Riven": (52.1, 56.53),
    "Ryze": (55.06, 60.76),     "Samira": (49.9, 57.86),     "Sejuani": (51.2, 55.0),
    "Senna": (52.3, 53.34),     "Seraphine": (50.44, 52.04), "Sett": (50.5, 54.21),
    "Shen": (49.39, 53.22),     "Singed": (48.37, 56.1),     "Sion": (49.6, 56.5),
    "Sivir": (50.62, 55.16),    "Skarner": (54.68, 57.25),   "Smolder": (49.2, 52.8),
    "Sona": (47.9, 51.51),      "Soraka": (49.9, 54.6),      "Swain": (52.5, 62.34),
    "Sylas": (52.32, 56.84),    "Syndra": (53.68, 53.4),     "Tahm Kench": (54.47, 57.32),
    "Taliyah": (53.4, 55.6),    "Talon": (49.4, 53.34),      "Taric": (44.85, 55.62),
    "Teemo": (52.08, 55.8),     "Thresh": (51.99, 55.34),    "Tristana": (54.0, 59.3),
    "Trundle": (53.4, 51.7),    "Tryndamere": (55.8, 53.3),  "Twisted Fate": (49.9, 56.3),
    "Twitch": (51.4, 53.3),     "Udyr": (50.79, 61.12),      "Urgot": (51.98, 53.2),
    "Varus": (54.2, 59.3),      "Vayne": (58.9, 57.3),       "Veigar": (51.03, 53.16),
    "Vel'Koz": (51.36, 57.6),   "Vi": (50.22, 57.81),        "Viego": (54.2, 59.86),
    "Viktor": (50.96, 52.7),    "Volibear": (53.74, 59.95),  "Warwick": (53.6, 58.6),
    "Wukong": (51.6, 61.5),     "Xayah": (51.8, 54.5),       "Xerath": (48.7, 53.47),
    "Xin Zhao": (50.8, 56.53),  "Yasuo": (49.9, 53.49),      "Yone": (51.4, 57.14),
    "Yorick": (52.9, 52.1),     "Yuumi": (53.18, 52.79),     "Zac": (49.96, 54.44),
    "Zed": (53.22, 57.85),      "Zeri": (49.85, 55.24),      "Ziggs": (52.2, 54.2),
    "Zilean": (50.91, 59.6),    "Zoe": (52.3, 58.97),        "Zyra": (53.9, 58.3),
}

_SPLIT_INDEX = {}
for k, v in SHACO_WR_SPLIT.items():
    key = k.lower().replace(" ", "").replace("'", "").replace(".", "").replace("&", "and").replace("-", "")
    _SPLIT_INDEX[key] = (k, v)

def get_wr_split(name: str):
    key = name.strip().lower().replace(" ", "").replace("'", "").replace(".", "").replace("&", "and").replace("-", "")
    if key in _SPLIT_INDEX:
        canon, (ad, ap) = _SPLIT_INDEX[key]
        return canon, ad, ap
    return name, None, None

# ─── CHAMPION ATTRIBUTE DB (for ally team balance + heuristic fallback) ──────

def champ(squishy=0, ranged=0, melee=0, engage=0, disengage=0,
          hard_cc=0, mobile=0, poke=0, ap_dmg=0, ad_dmg=0,
          tank=0, early=0, immobile=0, dmg_weight=1.0, is_dps=0,
          tankiness=0.0, dps=0.0):
    """
    tankiness (0.0-1.0): how much of a tank this champion is
      1.0 = Sion, Ornn, Malphite — pure frontline, massive HP/armor
      0.7 = Volibear, Darius, Sett — bruiser/juggernaut
      0.5 = Irelia, Camille, Jax — skirmisher with some durability
      0.2 = Jinx, Caitlyn — carries, fragile
      0.0 = pure glass cannon/enchanter

    dps (0.0-1.0): sustained damage output over time (NOT burst)
      1.0 = Vayne, Kog'Maw — hyper-carry, melts anything
      0.9 = Jinx, Tristana, Twitch, Draven, Master Yi
      0.7 = Irelia, Fiora, Tryndamere, Olaf — fighter DPS
      0.5 = Graves, Kindred — moderate sustained
      0.3 = Jax, Gwen — some sustained but not primary
      0.1 = Jhin, Zed, LeBlanc — burst/execute, minimal sustained DPS
      0.0 = Leona, Janna, Soraka — zero DPS
    """
    return dict(squishy=squishy, ranged=ranged, melee=melee, engage=engage,
                disengage=disengage, hard_cc=hard_cc, mobile=mobile, poke=poke,
                ap_dmg=ap_dmg, ad_dmg=ad_dmg, tank=tank, early=early,
                immobile=immobile, dmg_weight=dmg_weight, is_dps=is_dps,
                tankiness=tankiness, dps=dps)

CHAMPIONS = {
    "Malphite": champ(melee=1,engage=1,hard_cc=1,immobile=1,ap_dmg=1,tank=1,dmg_weight=0.4,tankiness=1.0,dps=0.1),
    "Leona": champ(melee=1,engage=1,hard_cc=1,early=1,tank=1,immobile=1,dmg_weight=0.2,tankiness=0.9,dps=0.0),
    "Nautilus": champ(melee=1,engage=1,hard_cc=1,tank=1,immobile=1,dmg_weight=0.2,tankiness=0.9,dps=0.0),
    "Amumu": champ(melee=1,engage=1,hard_cc=1,ap_dmg=1,tank=1,immobile=1,dmg_weight=0.4,tankiness=0.8,dps=0.1),
    "Jarvan IV": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,tank=1,early=1,dmg_weight=0.6,tankiness=0.6,dps=0.4),
    "Vi": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.6,tankiness=0.5,dps=0.5),
    "Sejuani": champ(melee=1,engage=1,hard_cc=1,tank=1,immobile=1,dmg_weight=0.2,tankiness=0.9,dps=0.0),
    "Zac": champ(melee=1,engage=1,hard_cc=1,mobile=1,ap_dmg=1,tank=1,dmg_weight=0.3,tankiness=0.8,dps=0.1),
    "Alistar": champ(melee=1,engage=1,hard_cc=1,tank=1,early=1,immobile=1,dmg_weight=0.1,tankiness=0.9,dps=0.0),
    "Blitzcrank": champ(melee=1,engage=1,hard_cc=1,tank=1,early=1,immobile=1,dmg_weight=0.2,tankiness=0.7,dps=0.1),
    "Thresh": champ(engage=1,hard_cc=1,early=1,disengage=1,dmg_weight=0.2,tankiness=0.5,dps=0.1),
    "Sion": champ(melee=1,engage=1,hard_cc=1,ad_dmg=1,tank=1,immobile=1,dmg_weight=0.4,tankiness=1.0,dps=0.2),
    "Maokai": champ(melee=1,engage=1,hard_cc=1,tank=1,immobile=1,dmg_weight=0.2,tankiness=0.9,dps=0.0),
    "Ornn": champ(melee=1,engage=1,hard_cc=1,ad_dmg=1,tank=1,immobile=1,dmg_weight=0.3,tankiness=1.0,dps=0.2),
    "Poppy": champ(melee=1,engage=1,hard_cc=1,ad_dmg=1,tank=1,early=1,disengage=1,dmg_weight=0.3,tankiness=0.7,dps=0.2),
    "Rell": champ(melee=1,engage=1,hard_cc=1,tank=1,immobile=1,dmg_weight=0.2,tankiness=0.9,dps=0.0),
    "Rammus": champ(melee=1,engage=1,hard_cc=1,mobile=1,tank=1,early=1,dmg_weight=0.2,tankiness=1.0,dps=0.1),
    "Warwick": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.6,is_dps=1,tankiness=0.6,dps=0.6),
    "Volibear": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,tank=1,early=1,dmg_weight=0.6,is_dps=1,tankiness=0.7,dps=0.6),
    "Hecarim": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.6,tankiness=0.5,dps=0.5),
    "Nunu & Willump": champ(melee=1,engage=1,hard_cc=1,mobile=1,ap_dmg=1,tank=1,early=1,dmg_weight=0.4,tankiness=0.8,dps=0.1),
    "Nocturne": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.7,tankiness=0.3,dps=0.5),
    "Diana": champ(melee=1,engage=1,hard_cc=1,mobile=1,ap_dmg=1,early=1,tankiness=0.2,dps=0.3),
    "Wukong": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.6,is_dps=1,tankiness=0.5,dps=0.5),
    "Renekton": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.7,is_dps=1,tankiness=0.5,dps=0.5),
    "Garen": champ(melee=1,hard_cc=1,ad_dmg=1,tank=1,early=1,immobile=1,dmg_weight=0.6,tankiness=0.7,dps=0.5),
    "Darius": champ(melee=1,hard_cc=1,ad_dmg=1,tank=1,early=1,immobile=1,dmg_weight=0.7,is_dps=1,tankiness=0.7,dps=0.7),
    "Irelia": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.9,is_dps=1,tankiness=0.5,dps=0.7),
    "Sett": champ(melee=1,engage=1,hard_cc=1,ad_dmg=1,tank=1,early=1,immobile=1,dmg_weight=0.6,is_dps=1,tankiness=0.7,dps=0.5),
    "Mordekaiser": champ(melee=1,engage=1,hard_cc=1,ap_dmg=1,tank=1,early=1,immobile=1,dmg_weight=0.8,tankiness=0.7,dps=0.5),
    "Ambessa": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.8,is_dps=1,tankiness=0.5,dps=0.6),
    "Olaf": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.7,is_dps=1,tankiness=0.5,dps=0.7),
    "Udyr": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,tank=1,early=1,dmg_weight=0.6,tankiness=0.7,dps=0.4),
    "Rengar": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,squishy=1,dmg_weight=0.9,tankiness=0.1,dps=0.2),
    "Kha'Zix": champ(melee=1,engage=1,mobile=1,ad_dmg=1,early=1,squishy=1,tankiness=0.1,dps=0.2),
    "Ekko": champ(melee=1,engage=1,hard_cc=1,mobile=1,ap_dmg=1,squishy=1,tankiness=0.2,dps=0.3),
    "Fizz": champ(melee=1,engage=1,mobile=1,ap_dmg=1,early=1,squishy=1,tankiness=0.1,dps=0.2),
    "Akali": champ(melee=1,engage=1,mobile=1,ap_dmg=1,squishy=1,tankiness=0.1,dps=0.2),
    "Zed": champ(melee=1,engage=1,mobile=1,ad_dmg=1,early=1,squishy=1,tankiness=0.1,dps=0.1),
    "Talon": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,squishy=1,tankiness=0.1,dps=0.1),
    "Qiyana": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,squishy=1,dmg_weight=0.9,tankiness=0.1,dps=0.2),
    "Katarina": champ(melee=1,engage=1,mobile=1,ap_dmg=1,squishy=1,tankiness=0.1,dps=0.3),
    "Elise": champ(engage=1,hard_cc=1,mobile=1,ap_dmg=1,early=1,squishy=1,tankiness=0.1,dps=0.2),
    "Nidalee": champ(ranged=1,mobile=1,ap_dmg=1,early=1,squishy=1,poke=1,dmg_weight=0.9,tankiness=0.1,dps=0.2),
    "Evelynn": champ(melee=1,engage=1,hard_cc=1,mobile=1,ap_dmg=1,squishy=1,tankiness=0.1,dps=0.2),
    "Naafiri": champ(melee=1,engage=1,mobile=1,ad_dmg=1,early=1,squishy=1,dmg_weight=0.9,tankiness=0.1,dps=0.2),
    "Briar": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.8,is_dps=1,tankiness=0.4,dps=0.7),
    "Viego": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.8,is_dps=1,tankiness=0.3,dps=0.7),
    "Bel'Veth": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.8,is_dps=1,tankiness=0.3,dps=0.8),
    "Lee Sin": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,squishy=1,dmg_weight=0.8,tankiness=0.2,dps=0.3),
    "Pyke": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.8,tankiness=0.2,dps=0.1),
    "Sylas": champ(melee=1,engage=1,hard_cc=1,mobile=1,ap_dmg=1,squishy=1,early=1,tankiness=0.2,dps=0.3),
    "Riven": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.9,tankiness=0.3,dps=0.6),
    "Aatrox": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.8,is_dps=1,tankiness=0.5,dps=0.6),
    "Yasuo": champ(melee=1,engage=1,mobile=1,ad_dmg=1,early=1,squishy=1,dmg_weight=0.9,tankiness=0.3,dps=0.6),
    "Yone": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,dmg_weight=0.9,tankiness=0.3,dps=0.5),
    "Fiora": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,squishy=1,dmg_weight=0.9,is_dps=1,tankiness=0.3,dps=0.9),
    "Camille": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.9,tankiness=0.4,dps=0.6),
    "Jax": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.9,is_dps=1,tankiness=0.5,dps=0.7),
    "Tryndamere": champ(melee=1,engage=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.9,is_dps=1,tankiness=0.3,dps=0.8),
    "Gragas": champ(melee=1,engage=1,hard_cc=1,mobile=1,ap_dmg=1,tank=1,early=1,disengage=1,dmg_weight=0.6,tankiness=0.7,dps=0.2),
    "Lux": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,poke=1,tankiness=0.1,dps=0.1),
    "Syndra": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,early=1,immobile=1,tankiness=0.1,dps=0.1),
    "Orianna": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,tankiness=0.1,dps=0.3),
    "Veigar": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,tankiness=0.1,dps=0.1),
    "Viktor": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,poke=1,tankiness=0.1,dps=0.4),
    "Cassiopeia": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,poke=1,tankiness=0.1,dps=0.5),
    "Xerath": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,poke=1,tankiness=0.1,dps=0.2),
    "Zoe": champ(squishy=1,ranged=1,hard_cc=1,mobile=1,ap_dmg=1,early=1,poke=1,tankiness=0.1,dps=0.1),
    "Annie": champ(squishy=1,ranged=1,engage=1,hard_cc=1,ap_dmg=1,early=1,immobile=1,tankiness=0.1,dps=0.1),
    "Ziggs": champ(squishy=1,ranged=1,ap_dmg=1,immobile=1,poke=1,dmg_weight=0.9,tankiness=0.1,dps=0.2),
    "Brand": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,early=1,immobile=1,tankiness=0.1,dps=0.3),
    "Zyra": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,poke=1,dmg_weight=0.9,tankiness=0.1,dps=0.3),
    "Karma": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,early=1,immobile=1,poke=1,disengage=1,dmg_weight=0.4,tankiness=0.2,dps=0.2),
    "Morgana": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,dmg_weight=0.8,tankiness=0.2,dps=0.2),
    "Karthus": champ(squishy=1,ranged=1,ap_dmg=1,immobile=1,tankiness=0.1,dps=0.4),
    "Taliyah": champ(squishy=1,ranged=1,hard_cc=1,mobile=1,ap_dmg=1,early=1,dmg_weight=0.9,tankiness=0.1,dps=0.2),
    "Aurelion Sol": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,tankiness=0.1,dps=0.4),
    "Seraphine": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,poke=1,dmg_weight=0.3,tankiness=0.2,dps=0.2),
    "Lissandra": champ(squishy=1,ranged=1,hard_cc=1,mobile=1,ap_dmg=1,tankiness=0.2,dps=0.1),
    "Ryze": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,tankiness=0.1,dps=0.5),
    "Twisted Fate": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,dmg_weight=0.9,tankiness=0.1,dps=0.2),
    "Neeko": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,dmg_weight=0.9,tankiness=0.1,dps=0.2),
    "Hwei": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,poke=1,tankiness=0.1,dps=0.2),
    "Ahri": champ(squishy=1,ranged=1,hard_cc=1,mobile=1,ap_dmg=1,early=1,tankiness=0.1,dps=0.2),
    "LeBlanc": champ(squishy=1,melee=1,hard_cc=1,mobile=1,ap_dmg=1,early=1,tankiness=0.1,dps=0.1),
    "Malzahar": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,tankiness=0.1,dps=0.3),
    "Teemo": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,early=1,poke=1,immobile=1,dmg_weight=0.9,is_dps=1,tankiness=0.1,dps=0.5),
    "Kennen": champ(squishy=1,ranged=1,engage=1,hard_cc=1,mobile=1,ap_dmg=1,early=1,tankiness=0.1,dps=0.3),
    "Gwen": champ(melee=1,hard_cc=1,mobile=1,ap_dmg=1,squishy=1,disengage=1,is_dps=1,tankiness=0.4,dps=0.7),
    "Vel'Koz": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,poke=1,tankiness=0.1,dps=0.3),
    "Azir": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,poke=1,tankiness=0.2,dps=0.4),
    "Mel": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,poke=1,tankiness=0.1,dps=0.2),
    "Caitlyn": champ(squishy=1,ranged=1,hard_cc=1,ad_dmg=1,early=1,poke=1,immobile=1,is_dps=1,tankiness=0.1,dps=0.7),
    "Jinx": champ(squishy=1,ranged=1,hard_cc=1,ad_dmg=1,poke=1,immobile=1,is_dps=1,tankiness=0.1,dps=0.9),
    "Jhin": champ(squishy=1,ranged=1,hard_cc=1,ad_dmg=1,early=1,poke=1,immobile=1,tankiness=0.1,dps=0.1),
    "Ezreal": champ(squishy=1,ranged=1,mobile=1,ad_dmg=1,poke=1,tankiness=0.1,dps=0.5),
    "Aphelios": champ(squishy=1,ranged=1,hard_cc=1,ad_dmg=1,immobile=1,poke=1,is_dps=1,tankiness=0.1,dps=0.8),
    "Kai'Sa": champ(squishy=1,ranged=1,engage=1,mobile=1,ad_dmg=1,tankiness=0.1,dps=0.7),
    "Vayne": champ(squishy=1,ranged=1,hard_cc=1,mobile=1,ad_dmg=1,is_dps=1,tankiness=0.1,dps=1.0),
    "Tristana": champ(squishy=1,ranged=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,disengage=1,is_dps=1,tankiness=0.1,dps=0.9),
    "Lucian": champ(squishy=1,ranged=1,mobile=1,ad_dmg=1,early=1,poke=1,is_dps=1,tankiness=0.1,dps=0.6),
    "Miss Fortune": champ(squishy=1,ranged=1,hard_cc=1,ad_dmg=1,early=1,poke=1,immobile=1,is_dps=1,tankiness=0.1,dps=0.6),
    "Samira": champ(squishy=1,ranged=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,disengage=1,is_dps=1,tankiness=0.1,dps=0.8),
    "Sivir": champ(squishy=1,ranged=1,hard_cc=1,ad_dmg=1,immobile=1,disengage=1,dmg_weight=0.9,is_dps=1,tankiness=0.1,dps=0.7),
    "Xayah": champ(squishy=1,ranged=1,hard_cc=1,mobile=1,ad_dmg=1,disengage=1,is_dps=1,tankiness=0.1,dps=0.8),
    "Draven": champ(squishy=1,ranged=1,hard_cc=1,ad_dmg=1,early=1,immobile=1,is_dps=1,tankiness=0.1,dps=0.8),
    "Twitch": champ(squishy=1,ranged=1,hard_cc=1,ad_dmg=1,immobile=1,is_dps=1,tankiness=0.1,dps=0.9),
    "Ashe": champ(squishy=1,ranged=1,engage=1,hard_cc=1,ad_dmg=1,immobile=1,poke=1,is_dps=1,tankiness=0.1,dps=0.7),
    "Kog'Maw": champ(squishy=1,ranged=1,hard_cc=1,ad_dmg=1,immobile=1,poke=1,is_dps=1,tankiness=0.1,dps=1.0),
    "Varus": champ(squishy=1,ranged=1,engage=1,hard_cc=1,ad_dmg=1,immobile=1,poke=1,is_dps=1,tankiness=0.1,dps=0.7),
    "Nilah": champ(squishy=1,melee=1,engage=1,mobile=1,ad_dmg=1,early=1,disengage=1,dmg_weight=0.9,is_dps=1,tankiness=0.3,dps=0.7),
    "Zeri": champ(squishy=1,ranged=1,mobile=1,ad_dmg=1,is_dps=1,tankiness=0.1,dps=0.8),
    "Smolder": champ(squishy=1,ranged=1,mobile=1,ad_dmg=1,poke=1,dmg_weight=0.9,is_dps=1,tankiness=0.2,dps=0.7),
    "Kalista": champ(squishy=1,ranged=1,mobile=1,ad_dmg=1,early=1,is_dps=1,tankiness=0.1,dps=0.8),
    "Graves": champ(ranged=1,engage=1,mobile=1,ad_dmg=1,early=1,squishy=1,poke=1,is_dps=1,tankiness=0.3,dps=0.6),
    "Kindred": champ(ranged=1,mobile=1,ad_dmg=1,early=1,squishy=1,dmg_weight=0.9,is_dps=1,tankiness=0.2,dps=0.6),
    "Corki": champ(squishy=1,ranged=1,mobile=1,ad_dmg=1,poke=1,dmg_weight=0.9,tankiness=0.1,dps=0.5),
    "Soraka": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,disengage=1,dmg_weight=0.0,tankiness=0.1,dps=0.0),
    "Sona": champ(squishy=1,ranged=1,engage=1,hard_cc=1,ap_dmg=1,immobile=1,disengage=1,dmg_weight=0.2,tankiness=0.1,dps=0.1),
    "Janna": champ(squishy=1,ranged=1,hard_cc=1,mobile=1,ap_dmg=1,disengage=1,dmg_weight=0.0,tankiness=0.1,dps=0.0),
    "Lulu": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,disengage=1,dmg_weight=0.2,tankiness=0.2,dps=0.0),
    "Nami": champ(squishy=1,ranged=1,engage=1,hard_cc=1,ap_dmg=1,early=1,immobile=1,dmg_weight=0.2,tankiness=0.2,dps=0.1),
    "Yuumi": champ(squishy=1,ranged=1,hard_cc=1,mobile=1,ap_dmg=1,disengage=1,dmg_weight=0.0,tankiness=0.1,dps=0.0),
    "Zilean": champ(squishy=1,ranged=1,hard_cc=1,ap_dmg=1,immobile=1,disengage=1,dmg_weight=0.2,tankiness=0.1,dps=0.1),
    "Bard": champ(squishy=1,ranged=1,engage=1,hard_cc=1,mobile=1,dmg_weight=0.2,tankiness=0.2,dps=0.1),
    "Renata": champ(squishy=1,ranged=1,hard_cc=1,immobile=1,dmg_weight=0.2,tankiness=0.2,dps=0.1),
    "Milio": champ(squishy=1,ranged=1,ap_dmg=1,immobile=1,disengage=1,dmg_weight=0.0,tankiness=0.1,dps=0.0),
    "Senna": champ(squishy=1,ranged=1,hard_cc=1,ad_dmg=1,immobile=1,poke=1,dmg_weight=0.8,tankiness=0.2,dps=0.5),
    "Rakan": champ(melee=1,engage=1,hard_cc=1,mobile=1,disengage=1,dmg_weight=0.1,tankiness=0.4,dps=0.0),
    "Taric": champ(melee=1,engage=1,hard_cc=1,tank=1,immobile=1,dmg_weight=0.1,tankiness=0.8,dps=0.0),
    "Nasus": champ(melee=1,hard_cc=1,ad_dmg=1,tank=1,immobile=1,dmg_weight=0.6,is_dps=1,tankiness=0.7,dps=0.6),
    "Illaoi": champ(melee=1,hard_cc=1,ad_dmg=1,immobile=1,early=1,dmg_weight=0.7,is_dps=1,tankiness=0.6,dps=0.7),
    "Trundle": champ(melee=1,hard_cc=1,ad_dmg=1,tank=1,early=1,immobile=1,dmg_weight=0.5,is_dps=1,tankiness=0.7,dps=0.5),
    "Urgot": champ(ranged=1,engage=1,hard_cc=1,ad_dmg=1,tank=1,early=1,immobile=1,dmg_weight=0.7,is_dps=1,tankiness=0.7,dps=0.6),
    "Swain": champ(ranged=1,engage=1,hard_cc=1,ap_dmg=1,tank=1,early=1,immobile=1,dmg_weight=0.8,tankiness=0.6,dps=0.4),
    "Galio": champ(melee=1,engage=1,hard_cc=1,mobile=1,ap_dmg=1,tank=1,dmg_weight=0.4,tankiness=0.8,dps=0.2),
    "Fiddlesticks": champ(squishy=1,ranged=1,engage=1,hard_cc=1,ap_dmg=1,immobile=1,tankiness=0.1,dps=0.4),
    "Lillia": champ(melee=1,hard_cc=1,mobile=1,ap_dmg=1,squishy=1,dmg_weight=0.9,tankiness=0.2,dps=0.3),
    "Shyvana": champ(melee=1,engage=1,mobile=1,tank=1,early=1,dmg_weight=0.6,tankiness=0.7,dps=0.4),
    "Ivern": champ(ranged=1,hard_cc=1,immobile=1,disengage=1,dmg_weight=0.0,tankiness=0.2,dps=0.0),
    "Master Yi": champ(melee=1,engage=1,mobile=1,ad_dmg=1,squishy=1,dmg_weight=0.9,is_dps=1,tankiness=0.2,dps=0.9),
    "Kayn": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,dmg_weight=0.8,tankiness=0.3,dps=0.6),
    "Rek'Sai": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.6,tankiness=0.4,dps=0.5),
    "Pantheon": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,poke=1,dmg_weight=0.8,tankiness=0.2,dps=0.3),
    "Singed": champ(melee=1,engage=1,hard_cc=1,mobile=1,ap_dmg=1,tank=1,disengage=1,dmg_weight=0.5,tankiness=0.8,dps=0.2),
    "Dr. Mundo": champ(melee=1,mobile=1,ad_dmg=1,tank=1,dmg_weight=0.4,tankiness=1.0,dps=0.3),
    "Cho'Gath": champ(melee=1,engage=1,hard_cc=1,ap_dmg=1,tank=1,immobile=1,dmg_weight=0.5,tankiness=0.9,dps=0.2),
    "Quinn": champ(ranged=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,poke=1,dmg_weight=0.8,tankiness=0.1,dps=0.5),
    "Yorick": champ(melee=1,hard_cc=1,ad_dmg=1,immobile=1,dmg_weight=0.6,tankiness=0.5,dps=0.5),
    "Gangplank": champ(ranged=1,hard_cc=1,ad_dmg=1,poke=1,dmg_weight=0.8,is_dps=1,tankiness=0.4,dps=0.6),
    "Gnar": champ(ranged=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,poke=1,dmg_weight=0.7,tankiness=0.5,dps=0.4),
    "Skarner": champ(melee=1,engage=1,hard_cc=1,mobile=1,tank=1,dmg_weight=0.3,tankiness=0.8,dps=0.2),
    "Shen": champ(melee=1,engage=1,hard_cc=1,tank=1,immobile=1,dmg_weight=0.2,tankiness=0.9,dps=0.1),
    "Aurora": champ(ranged=1,mobile=1,ap_dmg=1,squishy=1,poke=1,dmg_weight=0.9,tankiness=0.1,dps=0.2),
    "Akshan": champ(ranged=1,mobile=1,ad_dmg=1,squishy=1,poke=1,dmg_weight=0.9,tankiness=0.1,dps=0.5),
    "Heimerdinger": champ(ranged=1,ap_dmg=1,immobile=1,poke=1,squishy=1,dmg_weight=0.9,tankiness=0.1,dps=0.4),
    "Kled": champ(melee=1,engage=1,hard_cc=1,mobile=1,ad_dmg=1,early=1,dmg_weight=0.8,is_dps=1,tankiness=0.4,dps=0.6),
    "Kayle": champ(ranged=1,ad_dmg=1,ap_dmg=1,immobile=1,is_dps=1,tankiness=0.3,dps=0.8),
    "Tahm Kench": champ(melee=1,hard_cc=1,tank=1,immobile=1,disengage=1,dmg_weight=0.2),
    "Aurora": champ(ranged=1,mobile=1,ap_dmg=1,squishy=1,poke=1,dmg_weight=0.9),
}

ALIASES = {
    "jarvan": "Jarvan IV", "jarvaniv": "Jarvan IV",
    "khazix": "Kha'Zix", "kha": "Kha'Zix",
    "belveth": "Bel'Veth",
    "aurelionsol": "Aurelion Sol", "aurelion": "Aurelion Sol", "asol": "Aurelion Sol",
    "twistedfate": "Twisted Fate", "tf": "Twisted Fate",
    "masteryi": "Master Yi", "yi": "Master Yi",
    "leesin": "Lee Sin",
    "missfortune": "Miss Fortune", "mf": "Miss Fortune",
    "kogmaw": "Kog'Maw",
    "xinzhao": "Xin Zhao",
    "drmundo": "Dr. Mundo", "mundo": "Dr. Mundo",
    "chogath": "Cho'Gath",
    "leblanc": "LeBlanc", "lb": "LeBlanc",
    "reksai": "Rek'Sai",
    "kaisa": "Kai'Sa",
    "velkoz": "Vel'Koz",
    "nunuwillump": "Nunu & Willump", "nunu": "Nunu & Willump",
    "ksante": "K'Sante",
    "tahm": "Tahm Kench",
}

# Item IDs verified for patch 26.5
AP_ITEMS = [
    {"name": "Blackfire Torch",     "id": "6701", "reason": "Core first item — massive box/shiv damage over time"},
    {"name": "Liandry's Torment",   "id": "3151", "reason": "Burns tanks; stacks with boxes dealing repeated hits"},
    {"name": "Rabadon's Deathcap",  "id": "3089", "reason": "Max AP amplifier — snowball when ahead"},
    {"name": "Shadowflame",         "id": "4645", "reason": "Burst vs squishy targets, ignores small shields"},
    {"name": "Cryptbloom",          "id": "6617", "reason": "Safe all-round option: AP + MR pen + healing reduction"},
    {"name": "Zhonya's Hourglass",  "id": "3157", "reason": "Survive engage/assassins while boxes deal damage"},
]

AD_ITEMS = [
    {"name": "Youmuu's Ghostblade", "id": "3142", "reason": "Core first item — lethality + movement for ganks"},
    {"name": "The Collector",       "id": "6676", "reason": "Execute low-HP targets, great for snowballing"},
    {"name": "Infinity Edge",       "id": "3031", "reason": "Huge crit damage spike once you have crit items"},
    {"name": "Lord Dominik's Regards", "id": "3036", "reason": "Armor pen vs tanks and fed bruisers"},
    {"name": "Navori Flickerblade", "id": "6670", "reason": "CDR on crit reduces Q cooldown for more ganks"},
    {"name": "Guardian Angel",      "id": "3026", "reason": "Second life for diving deep into enemy backline"},
]

def get_champion(name: str):
    if not name:
        return None, name
    key = name.strip()
    if key in CHAMPIONS:
        return CHAMPIONS[key], key
    lower = key.lower().replace(" ", "").replace("'", "").replace(".", "").replace("&", "and").replace("-", "")
    if lower in ALIASES:
        canonical = ALIASES[lower]
        return CHAMPIONS.get(canonical), canonical
    for k, v in CHAMPIONS.items():
        if k.lower().replace(" ", "").replace("'", "").replace(".", "").replace("&", "and").replace("-", "") == lower:
            return v, k
    return None, key

def score_enemy_heuristic(c: dict) -> tuple:
    ap, ad = 0.0, 0.0
    ap_r, ad_r = [], []
    if c["ranged"]: ad += 1.5; ad_r.append("ranged")
    if c["poke"]: ad += 0.8; ad_r.append("poke")
    if c["melee"]: ap += 1.2; ap_r.append("melee")
    if c["engage"] and c["melee"]: ap += 1.2; ap_r.append("melee engage")
    if c["engage"] and c["ranged"]: ad += 0.8; ad_r.append("ranged engage")
    if c["immobile"]: ap += 0.8; ap_r.append("immobile")
    if c["mobile"] and c["ranged"]: ad += 0.6; ad_r.append("mobile ranged")
    if c["squishy"] and c["melee"]: ap += 0.6; ap_r.append("squishy melee")
    if c["squishy"] and c["ranged"]: ad += 0.4; ad_r.append("squishy ranged")
    if c["tank"]: ad += 0.6; ad_r.append("tanky")
    if c["disengage"]: ad += 0.8; ad_r.append("disengage")
    return ap, ad, ap_r, ad_r

def load_db_winrates(db_session, summoner_name: str, min_games: int = 30):
    return {}

def recommend_build(allies: list, enemies: list, role: str = "jungle",
                    db_winrates: dict = None) -> dict:
    if db_winrates is None:
        db_winrates = {}

    unknown = []
    ap_score = 0.0
    ad_score = 0.0
    reasons_ap = []
    reasons_ad = []
    matchup_context = []
    recognized_enemies = []
    enemy_tankiness = 0.0  # cumulative tankiness of enemy team (float)

    for name in enemies:
        if not name.strip():
            continue

        c, canonical = get_champion(name)
        canon_wr, wr_ad, wr_ap = get_wr_split(canonical if c else name)
        if c is None and wr_ad is None:
            # try wr_split canonical as champion lookup
            c2, canonical2 = get_champion(canon_wr)
            if c2:
                c, canonical = c2, canonical2

        if canon_wr != canonical and wr_ad is not None:
            canonical = canon_wr

        db_data = db_winrates.get(canonical, {})
        has_db_ap = db_data.get("ap_games", 0) >= 30
        has_db_ad = db_data.get("ad_games", 0) >= 30

        avg_wr = None
        wr_label = ""
        wr_note = ""
        if wr_ad is not None and wr_ap is not None:
            avg_wr = round((wr_ad + wr_ap) / 2, 1)
            if avg_wr < 49:
                wr_label = f"⚠ {avg_wr}% avg WR"; wr_note = "tough matchup"
            elif avg_wr > 55:
                wr_label = f"✓ {avg_wr}% avg WR"; wr_note = "favorable matchup"
            else:
                wr_label = f"{avg_wr}% avg WR"
        elif wr_ap is not None:
            avg_wr = wr_ap
            wr_label = f"{wr_ap}% WR (AP only)"

        data_source = "personal" if (has_db_ap and has_db_ad) else ("lolalytics" if wr_ad is not None or wr_ap is not None else "heuristic")

        matchup_context.append({
            "name": canonical,
            "general_wr": avg_wr,
            "wr_ad": wr_ad,
            "wr_ap": wr_ap,
            "wr_label": wr_label,
            "wr_note": wr_note,
            "has_personal_data": has_db_ap and has_db_ad,
            "data_source": data_source,
        })

        if c is None and wr_ad is None and wr_ap is None:
            unknown.append(name)
            continue

        recognized_enemies.append(canonical)
        if c:
            enemy_tankiness += c.get("tankiness", 0.0)

        # Priority 1: Personal DB
        if has_db_ap and has_db_ad:
            diff = db_data["ap"] - db_data["ad"]
            score = min(abs(diff) / 3, 3.0)
            if diff > 3:
                ap_score += score
                reasons_ap.append(f"{canonical}: AP {db_data['ap']:.0f}% vs AD {db_data['ad']:.0f}% in your games")
            elif diff < -3:
                ad_score += score
                reasons_ad.append(f"{canonical}: AD {db_data['ad']:.0f}% vs AP {db_data['ap']:.0f}% in your games")

        # Priority 2: Lolalytics real data
        elif wr_ad is not None and wr_ap is not None:
            diff = wr_ap - wr_ad
            score = min(abs(diff) / 3, 2.5)
            wr_str = f" (AP {wr_ap}% / AD {wr_ad}%)"
            if diff > 1.5:
                ap_score += score
                reasons_ap.append(f"{canonical}{wr_str} → AP +{diff:.1f}%")
            elif diff < -1.5:
                ad_score += score
                reasons_ad.append(f"{canonical}{wr_str} → AD +{abs(diff):.1f}%")

        # Priority 3: Heuristic (unknown champ or AP-only data)
        elif c is not None:
            ap, ad, ap_r, ad_r = score_enemy_heuristic(c)
            ap_score += ap * 0.6
            ad_score += ad * 0.6
            if ap_r:
                reasons_ap.append(f"{canonical} [heuristic]: {', '.join(ap_r[:2])}")
            if ad_r:
                reasons_ad.append(f"{canonical} [heuristic]: {', '.join(ad_r[:2])}")

    # ── ALLY TEAM BALANCE ────────────────────────────────────────────────────
    ally_ap_dmg = 0.0
    ally_ad_dmg = 0.0
    ally_total = 0
    recognized_allies = []

    ally_dps_total = 0.0  # cumulative DPS of ally team (float)

    for name in allies:
        if not name.strip():
            continue
        c, canonical = get_champion(name)
        if c is None:
            unknown.append(name)
            continue
        recognized_allies.append(canonical)
        w = c.get("dmg_weight", 1.0)
        ally_ap_dmg += c.get("ap_dmg", 0) * w
        ally_ad_dmg += c.get("ad_dmg", 0) * w
        ally_total += 1
        ally_dps_total += c.get("dps", 0.0)

    if ally_total >= 2:
        total_dmg = ally_ap_dmg + ally_ad_dmg
        if total_dmg > 0:
            ap_ratio = ally_ap_dmg / total_dmg
            ad_ratio = ally_ad_dmg / total_dmg
        else:
            ap_ratio = ad_ratio = 0.5

        ap_pct_team = int(ap_ratio * 100)
        ad_pct_team = int(ad_ratio * 100)

        # Full AP: force AD non-negotiable
        if ap_ratio >= 0.65:
            ad_score = max(ad_score, ap_score + 8.0)
            reasons_ad.insert(0, f"⚠ Team damage is ~{ap_pct_team}% AP — one Wit's End or Force of Nature shuts down your whole team. AD Shaco is non-negotiable.")
        elif ap_ratio >= 0.50:
            ad_score += 3.5
            reasons_ad.insert(0, f"Team leans AP ({ap_pct_team}% AP damage) — AD Shaco adds essential physical damage.")
        # Full AD: force AP non-negotiable
        elif ad_ratio >= 0.65:
            ap_score = max(ap_score, ad_score + 8.0)
            reasons_ap.insert(0, f"⚠ Team damage is ~{ad_pct_team}% AD — one Thornmail or Frozen Heart counters everything. AP Shaco is non-negotiable.")
        elif ad_ratio >= 0.50:
            ap_score += 3.5
            reasons_ap.insert(0, f"Team leans AD ({ad_pct_team}% AD damage) — AP Shaco adds essential magic damage.")

    # ── TANK / DPS CHECK ─────────────────────────────────────────────────────
    # ── TANK / DPS CHECK (float-based) ──────────────────────────────────────
    # AD Shaco DPS = 0.75, AP Shaco DPS = 0.60 — small but real gap.
    # We compare enemy tankiness vs ally DPS to decide how much this gap matters.
    # tankiness and dps are cumulative floats across the whole team.
    if enemy_tankiness >= 0.7:  # at least one real tank on enemy team
        tank_names = [e for e in recognized_enemies
                      if get_champion(e)[0] and get_champion(e)[0].get("tankiness", 0) >= 0.7]
        # DPS deficit: how much DPS the team lacks to deal with the tanks
        # AD Shaco adds 0.75 DPS, AP adds 0.60. Difference = 0.15 per tank score point.
        dps_gap = max(0, enemy_tankiness - ally_dps_total)  # positive = DPS shortage

        if dps_gap >= 1.5:
            # Serious DPS shortage vs heavy tanks — the 0.15 gap between builds matters a lot
            boost = min(dps_gap * 1.5, 6.0)  # cap at 6 to avoid overriding everything
            ad_score += boost
            reasons_ad.insert(0, f"⚠ Enemy tankiness ({enemy_tankiness:.1f}) vs ally DPS ({ally_dps_total:.1f}) — big DPS gap. AD Shaco (0.75 DPS) over AP (0.60) makes a real difference vs {', '.join(tank_names) if tank_names else 'tanks'}.")
        elif dps_gap >= 0.7:
            # Moderate shortage — nudge toward AD
            ad_score += dps_gap * 0.8
            reasons_ad.insert(0, f"Enemy has {', '.join(tank_names) if tank_names else 'tanks'} and ally DPS ({ally_dps_total:.1f}) is low — AD Shaco's extra DPS helps melt them.")
        # else: ally DPS covers the tanks fine, no push needed

    if role == "support":
        ap_score += 1.5
        reasons_ap.append("Support role: boxes in lane favor AP.")

    if ap_score == 0 and ad_score == 0:
        ap_score = 0.5
        reasons_ap.append("No strong draft signal — AP Shaco is the safer default.")

    total = ap_score + ad_score or 1
    ap_pct = round(ap_score / total * 100)
    ad_pct = 100 - ap_pct
    diff = abs(ap_score - ad_score)
    confidence = "High" if diff >= 5 else "Medium" if diff >= 2.5 else "Low"
    confidence_color = "green" if diff >= 5 else "yellow" if diff >= 2.5 else "gray"

    if ap_score >= ad_score:
        build = "AP"; main_reasons = reasons_ap; counter_reasons = reasons_ad; items = AP_ITEMS
    else:
        build = "AD"; main_reasons = reasons_ad; counter_reasons = reasons_ap; items = AD_ITEMS

    return {
        "build":            build,
        "confidence":       confidence,
        "confidence_color": confidence_color,
        "score_ap":         ap_pct,
        "score_ad":         ad_pct,
        "reasons":          main_reasons[:6],
        "counter_reasons":  counter_reasons[:4],
        "item_list":        items,
        "unknown_champs":   unknown,
        "allies_found":     len(recognized_allies),
        "enemies_found":    len(recognized_enemies),
        "matchup_context":  matchup_context,
    }