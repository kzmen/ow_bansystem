import unittest

from ban_logic import Vote, aggregate_votes, calculate_bans, validate_choices


class BanLogicTests(unittest.TestCase):
    def test_points_are_7_5_3(self):
        scores, voters = aggregate_votes([
            Vote("a1", "A", ("Ana", "Tracer", "Winston")),
        ])
        self.assertEqual(scores["A"]["Ana"], 7)
        self.assertEqual(scores["A"]["Tracer"], 5)
        self.assertEqual(scores["A"]["Winston"], 3)
        self.assertEqual(voters["Ana"], 1)

    def test_duplicate_hero_is_skipped_and_next_candidate_is_used(self):
        votes = [
            Vote("a1", "A", ("Ana", "Tracer", "Genji")),
            Vote("a2", "A", ("Ana", "Tracer", "Genji")),
            Vote("a3", "A", ("Ana", "Tracer", "Genji")),
            Vote("b1", "B", ("Ana", "Kiriko", "Winston")),
            Vote("b2", "B", ("Ana", "Kiriko", "Winston")),
            Vote("b3", "B", ("Ana", "Kiriko", "Winston")),
        ]
        result = calculate_bans(votes, seed="duplicate", enable_lobby_ban=False)
        heroes = [ban.hero for ban in result.bans]
        self.assertEqual(heroes[0], "Ana")
        self.assertEqual(len(heroes), len(set(heroes)))
        self.assertIn("Kiriko", heroes)
        self.assertIn("Winston", heroes)
        self.assertIn("Tracer", heroes)

    def test_normal_bans_never_exceed_two_per_role(self):
        votes = [
            Vote("a1", "A", ("Tracer", "Genji", "Ana")),
            Vote("a2", "A", ("Tracer", "Genji", "Ana")),
            Vote("a3", "A", ("Tracer", "Genji", "Ana")),
            Vote("b1", "B", ("Sombra", "Ashe", "Winston")),
            Vote("b2", "B", ("Sombra", "Ashe", "Winston")),
            Vote("b3", "B", ("Sombra", "Ashe", "Winston")),
        ]
        result = calculate_bans(votes, seed="role-cap", enable_lobby_ban=False)
        damage_count = sum(1 for ban in result.bans if ban.role == "Damage")
        self.assertLessEqual(damage_count, 2)
        self.assertEqual(len(result.bans), 4)

    def test_lobby_ban_requires_both_teams_and_ten_points(self):
        votes = [
            Vote("a1", "A", ("Ana", "Tracer", "Sombra")),
            Vote("a2", "A", ("Ana", "Tracer", "Sombra")),
            Vote("a3", "A", ("Ana", "Tracer", "Sombra")),
            Vote("b1", "B", ("Kiriko", "Winston", "Sombra")),
            Vote("b2", "B", ("Kiriko", "Winston", "Sombra")),
            Vote("b3", "B", ("Kiriko", "Winston", "Sombra")),
        ]
        result = calculate_bans(votes, seed="lobby", enable_lobby_ban=True)
        lobby_bans = [ban for ban in result.bans if ban.kind == "lobby"]
        self.assertEqual(len(lobby_bans), 1)
        self.assertEqual(lobby_bans[0].hero, "Sombra")
        self.assertEqual(lobby_bans[0].score, 18)

    def test_lobby_ban_is_not_created_from_one_team_only(self):
        votes = [
            Vote("a1", "A", ("Ana", "Sombra", "Tracer")),
            Vote("a2", "A", ("Ana", "Sombra", "Tracer")),
            Vote("b1", "B", ("Kiriko", "Winston", "Zarya")),
            Vote("b2", "B", ("Kiriko", "Winston", "Zarya")),
        ]
        result = calculate_bans(votes, seed="no-lobby", enable_lobby_ban=True)
        self.assertFalse(any(ban.kind == "lobby" for ban in result.bans))

    def test_pass_is_valid_but_partial_vote_is_not(self):
        self.assertEqual(validate_choices([]), ())
        with self.assertRaises(ValueError):
            validate_choices(["Ana", "Tracer"])

    def test_same_seed_produces_same_tie_result(self):
        votes = [
            Vote("a1", "A", ("Ana", "Tracer", "Genji")),
            Vote("b1", "B", ("Kiriko", "Winston", "Zarya")),
        ]
        first = calculate_bans(votes, seed="same-seed").to_dict()
        second = calculate_bans(votes, seed="same-seed").to_dict()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
