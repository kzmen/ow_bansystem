"""Overwatch custom hero-ban calculation.

Rules implemented:
- Each player's ranked choices are worth 7 / 5 / 3 points.
- Four normal bans: first team's top choice, second team's top two valid
  choices, then first team's next valid choice.
- A hero cannot be banned twice.
- At most two normal bans may come from the same role.
- Score ties are resolved by the number of distinct lobby players who voted
  for the hero, then by a deterministic per-round pseudo-random tiebreak.
- Optional fifth lobby ban: a remaining hero must have votes from both teams
  and at least 10 combined points. The normal role cap is ignored.

The fifth-ban rule is intentionally isolated so it can be changed later.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from hashlib import sha256
from typing import Iterable, Mapping, Sequence

POINTS_BY_RANK: tuple[int, int, int] = (7, 5, 3)

HEROES_BY_ROLE: dict[str, tuple[str, ...]] = {
    "Tank": (
        "D.Va",
        "D.Mon",
        "Domina",
        "Doomfist",
        "Hazard",
        "Junker Queen",
        "Mauga",
        "Orisa",
        "Ramattra",
        "Reinhardt",
        "Roadhog",
        "Sigma",
        "Winston",
        "Wrecking Ball",
        "Zarya",
    ),
    "Damage": (
        "Anran",
        "Ashe",
        "Bastion",
        "Cassidy",
        "Echo",
        "Emre",
        "Freja",
        "Genji",
        "Hanzo",
        "Junkrat",
        "Mei",
        "Pharah",
        "Reaper",
        "Shion",
        "Sierra",
        "Sojourn",
        "Soldier: 76",
        "Symmetra",
        "Torbjörn",
        "Tracer",
        "Vendetta",
        "Venture",
        "Widowmaker",
    ),
    "Support": (
        "Ana",
        "Baptiste",
        "Brigitte",
        "Doctrine",
        "Illari",
        "Jetpack Cat",
        "Juno",
        "Kiriko",
        "Lifeweaver",
        "Lúcio",
        "Mercy",
        "Mizuki",
        "Moira",
        "Sombra",
        "Wuyang",
        "Zenyatta",
    ),
}

HERO_ROLE: dict[str, str] = {
    hero: role for role, heroes in HEROES_BY_ROLE.items() for hero in heroes
}
ALL_HEROES: tuple[str, ...] = tuple(
    hero for role in ("Tank", "Damage", "Support") for hero in HEROES_BY_ROLE[role]
)


@dataclass(frozen=True)
class Vote:
    player_id: str
    team: str
    choices: tuple[str, ...]


@dataclass(frozen=True)
class Ban:
    hero: str
    role: str
    source_team: str | None
    kind: str
    score: int


@dataclass(frozen=True)
class BanResult:
    bans: tuple[Ban, ...]
    first_team: str | None
    scores: dict[str, dict[str, int]]
    voter_counts: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "bans": [asdict(ban) for ban in self.bans],
            "first_team": self.first_team,
            "scores": self.scores,
            "voter_counts": self.voter_counts,
        }


def validate_choices(choices: Sequence[str]) -> tuple[str, ...]:
    """Validate and normalize a player's choices.

    An empty list is allowed and represents passing. Otherwise exactly three
    distinct valid heroes are required.
    """
    normalized = tuple(str(hero).strip() for hero in choices if str(hero).strip())
    if not normalized:
        return ()
    if len(normalized) != 3:
        raise ValueError("3人のヒーローを選ぶか、パスしてください。")
    if len(set(normalized)) != 3:
        raise ValueError("同じヒーローを複数の枠に選ぶことはできません。")
    unknown = [hero for hero in normalized if hero not in HERO_ROLE]
    if unknown:
        raise ValueError(f"不明なヒーローです: {', '.join(unknown)}")
    return normalized


def _stable_random(seed: str, label: str) -> int:
    digest = sha256(f"{seed}|{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def aggregate_votes(votes: Iterable[Vote]) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    scores: dict[str, dict[str, int]] = {"A": defaultdict(int), "B": defaultdict(int)}
    voters_by_hero: dict[str, set[str]] = defaultdict(set)

    for vote in votes:
        if vote.team not in {"A", "B"}:
            raise ValueError(f"Invalid team: {vote.team}")
        choices = validate_choices(vote.choices)
        for index, hero in enumerate(choices):
            scores[vote.team][hero] += POINTS_BY_RANK[index]
            voters_by_hero[hero].add(vote.player_id)

    plain_scores = {
        team: dict(team_scores)
        for team, team_scores in scores.items()
    }
    voter_counts = {hero: len(players) for hero, players in voters_by_hero.items()}
    return plain_scores, voter_counts


def _ranked_heroes(
    team: str,
    scores: Mapping[str, Mapping[str, int]],
    voter_counts: Mapping[str, int],
    seed: str,
) -> list[str]:
    team_scores = scores.get(team, {})
    return sorted(
        team_scores,
        key=lambda hero: (
            -team_scores[hero],
            -voter_counts.get(hero, 0),
            -_stable_random(seed, f"rank:{team}:{hero}"),
            hero,
        ),
    )


def _choose_first_team(
    rankings: Mapping[str, Sequence[str]],
    scores: Mapping[str, Mapping[str, int]],
    seed: str,
) -> str | None:
    top_a = rankings["A"][0] if rankings["A"] else None
    top_b = rankings["B"][0] if rankings["B"] else None

    if top_a is None and top_b is None:
        return None
    if top_b is None:
        return "A"
    if top_a is None:
        return "B"

    score_a = scores["A"].get(top_a, 0)
    score_b = scores["B"].get(top_b, 0)
    if score_a > score_b:
        return "A"
    if score_b > score_a:
        return "B"
    return "A" if _stable_random(seed, "first-team") % 2 == 0 else "B"


def _next_valid(
    ranking: Sequence[str],
    already_banned: set[str],
    role_counts: Counter[str],
    enforce_role_cap: bool,
) -> str | None:
    for hero in ranking:
        if hero in already_banned:
            continue
        role = HERO_ROLE[hero]
        if enforce_role_cap and role_counts[role] >= 2:
            continue
        return hero
    return None


def calculate_bans(
    votes: Iterable[Vote],
    *,
    seed: str,
    enable_lobby_ban: bool = True,
    lobby_ban_threshold: int = 10,
) -> BanResult:
    votes = tuple(votes)
    scores, voter_counts = aggregate_votes(votes)
    rankings = {
        team: _ranked_heroes(team, scores, voter_counts, seed)
        for team in ("A", "B")
    }
    first_team = _choose_first_team(rankings, scores, seed)

    if first_team is None:
        return BanResult((), None, scores, voter_counts)

    second_team = "B" if first_team == "A" else "A"
    sequence = (first_team, second_team, second_team, first_team)
    banned: set[str] = set()
    role_counts: Counter[str] = Counter()
    bans: list[Ban] = []

    for team in sequence:
        hero = _next_valid(
            rankings[team],
            already_banned=banned,
            role_counts=role_counts,
            enforce_role_cap=True,
        )
        if hero is None:
            continue
        banned.add(hero)
        role = HERO_ROLE[hero]
        role_counts[role] += 1
        bans.append(
            Ban(
                hero=hero,
                role=role,
                source_team=team,
                kind="normal",
                score=scores[team][hero],
            )
        )

    if enable_lobby_ban:
        eligible: list[str] = []
        for hero in ALL_HEROES:
            if hero in banned:
                continue
            score_a = scores["A"].get(hero, 0)
            score_b = scores["B"].get(hero, 0)
            if score_a <= 0 or score_b <= 0:
                continue
            if score_a + score_b < lobby_ban_threshold:
                continue
            eligible.append(hero)

        if eligible:
            lobby_hero = sorted(
                eligible,
                key=lambda hero: (
                    -(scores["A"].get(hero, 0) + scores["B"].get(hero, 0)),
                    -voter_counts.get(hero, 0),
                    -_stable_random(seed, f"lobby:{hero}"),
                    hero,
                ),
            )[0]
            bans.append(
                Ban(
                    hero=lobby_hero,
                    role=HERO_ROLE[lobby_hero],
                    source_team=None,
                    kind="lobby",
                    score=scores["A"].get(lobby_hero, 0)
                    + scores["B"].get(lobby_hero, 0),
                )
            )

    return BanResult(tuple(bans), first_team, scores, voter_counts)
