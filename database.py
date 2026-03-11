import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, String, Boolean, Integer, BigInteger, DateTime, Text
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=5,
    max_overflow=10,
    connect_args={"connect_timeout": 10},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

class ShacoMatch(Base):
    __tablename__ = "shaco_matches"

    match_id          = Column(String, primary_key=True)
    puuid             = Column(String, nullable=False)
    summoner_name     = Column(String, nullable=False)
    region            = Column(String, nullable=False)
    win               = Column(Boolean, nullable=False)
    kills             = Column(Integer, nullable=False)
    deaths            = Column(Integer, nullable=False)
    assists           = Column(Integer, nullable=False)
    build             = Column(String, nullable=False)
    duration_min      = Column(Integer, nullable=False)
    cs                = Column(Integer, default=0)
    damage_dealt      = Column(Integer, default=0)
    gold_earned       = Column(Integer, default=0)
    game_timestamp    = Column(BigInteger, default=0)
    ally_champs       = Column(String, default="")
    enemy_champs      = Column(String, default="")
    position          = Column(String, default="JUNGLE")
    side              = Column(String, default="")
    own_items         = Column(String, default="")
    participants_json = Column(String, default="")
    queue_type        = Column(String, default="ranked_solo")

    # ── Extended stats (batch 1) ─────────────────────────────────────
    objectives_stolen  = Column(Integer, default=0)
    first_blood        = Column(Boolean, default=False)
    largest_multi_kill = Column(Integer, default=0)
    double_kills       = Column(Integer, default=0)
    triple_kills       = Column(Integer, default=0)
    quadra_kills       = Column(Integer, default=0)
    penta_kills        = Column(Integer, default=0)
    champ_level        = Column(Integer, default=0)
    time_dead_sec      = Column(Integer, default=0)
    vision_score       = Column(Integer, default=0)
    wards_placed       = Column(Integer, default=0)
    control_wards      = Column(Integer, default=0)
    cc_dealt           = Column(Integer, default=0)
    summoner1_id       = Column(Integer, default=0)
    summoner2_id       = Column(Integer, default=0)
    surrendered        = Column(Boolean, default=False)
    bans_json          = Column(String, default="")

    # ── Extended stats (batch 2) — objectives ────────────────────────
    dragon_kills        = Column(Integer, default=0)   # Shaco's dragon kills
    baron_kills         = Column(Integer, default=0)   # Shaco's baron kills
    void_grub_kills     = Column(Integer, default=0)   # team voidgrub kills
    rift_herald_kills   = Column(Integer, default=0)   # team herald kills
    turret_kills        = Column(Integer, default=0)   # towers destroyed by Shaco
    first_tower_kill    = Column(Boolean, default=False)
    team_kills          = Column(Integer, default=0)   # total team kills (for KP%)
    team_dragons        = Column(Integer, default=0)   # total team dragons
    team_barons         = Column(Integer, default=0)   # total team barons

    # ── Extended stats (batch 2) — damage ────────────────────────────
    damage_taken        = Column(Integer, default=0)
    magic_damage_dealt  = Column(Integer, default=0)
    physical_damage_dealt = Column(Integer, default=0)
    true_damage_dealt   = Column(Integer, default=0)
    total_damage_dealt  = Column(Integer, default=0)   # ALL targets, not just champs
    damage_to_objectives= Column(Integer, default=0)
    damage_to_turrets   = Column(Integer, default=0)
    healing_done        = Column(Integer, default=0)

    # ── Extended stats (batch 2) — combat ────────────────────────────
    largest_killing_spree = Column(Integer, default=0)
    killing_sprees        = Column(Integer, default=0)
    longest_time_alive    = Column(Integer, default=0)  # seconds
    first_blood_assist    = Column(Boolean, default=False)
    first_tower_assist    = Column(Boolean, default=False)
    wards_killed          = Column(Integer, default=0)
    enemy_jungle_cs       = Column(Integer, default=0)  # stolen from enemy jungle
    ally_jungle_cs        = Column(Integer, default=0)  # own jungle cs
    gold_spent            = Column(Integer, default=0)

    # ── Extended stats (batch 2) — spell casts ───────────────────────
    spell1_casts  = Column(Integer, default=0)   # Q casts
    spell2_casts  = Column(Integer, default=0)   # W casts
    spell3_casts  = Column(Integer, default=0)   # E casts
    spell4_casts  = Column(Integer, default=0)   # R casts
    summoner1_casts = Column(Integer, default=0)
    summoner2_casts = Column(Integer, default=0)

    # ── Meta ─────────────────────────────────────────────────────────
    patch           = Column(String, default="")   # e.g. "15.5"
    game_version    = Column(String, default="")   # full version string
    shaco_raw_json  = Column(Text, default="")     # full participant JSON for future use

    created_at = Column(DateTime, default=datetime.utcnow)

class ShacoPlayer(Base):
    __tablename__ = "shaco_players"

    puuid         = Column(String, primary_key=True)
    summoner_name = Column(String, nullable=False)
    region        = Column(String, nullable=False)
    tier          = Column(String, default="")       # CHALLENGER, GRANDMASTER, MASTER, etc.
    division      = Column(String, default="")       # I, II, III, IV
    lp            = Column(Integer, default=0)
    wins          = Column(Integer, default=0)
    losses        = Column(Integer, default=0)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

def init_db():
    Base.metadata.create_all(engine)
    print("Database ready.")

if __name__ == "__main__":
    init_db()
