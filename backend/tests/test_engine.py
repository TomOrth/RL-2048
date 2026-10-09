from random import Random

from app.engine import legal_moves, play, slide


def test_left_merges_pairs_once_and_scores_each_created_tile():
    board = [[2, 2, 2, 2], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    result, score, transitions = slide(board, "left")
    assert result[0] == [4, 4, 0, 0]
    assert score == 8
    assert sum(t.merged for t in transitions) == 4


def test_new_merge_cannot_merge_again_in_same_move():
    board = [[2, 2, 4, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    result, score, _ = slide(board, "left")
    assert result[0] == [4, 4, 0, 0]
    assert score == 4


def test_all_directions_compact_and_merge_toward_edge():
    board = [[0, 2, 0, 2], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    assert slide(board, "right")[0][0] == [0, 0, 0, 4]
    assert slide(board, "left")[0][0] == [4, 0, 0, 0]
    vertical = [[0, 0, 0, 0], [2, 0, 0, 0], [0, 0, 0, 0], [2, 0, 0, 0]]
    assert [row[0] for row in slide(vertical, "up")[0]] == [4, 0, 0, 0]
    assert [row[0] for row in slide(vertical, "down")[0]] == [0, 0, 0, 4]


def test_noop_does_not_advance_rng_or_spawn():
    board = [[2, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    rng = Random(41)
    expected_rng = Random(41)
    result = play(board, "left", rng)
    assert not result.moved
    assert result.spawned_tile is None
    assert result.score_delta == 0
    assert result.transitions == []
    assert rng.getstate() == expected_rng.getstate()


def test_seeded_replay_and_legal_move_detection():
    rng_a, rng_b = Random(90210), Random(90210)
    board_a = [[0] * 4 for _ in range(4)]
    board_b = [[0] * 4 for _ in range(4)]
    for _ in range(2):
        from app.engine import spawn_tile
        spawn_tile(board_a, rng_a)
        spawn_tile(board_b, rng_b)
    assert board_a == board_b
    for direction in ("left", "up", "right", "down", "left"):
        result_a = play(board_a, direction, rng_a)
        result_b = play(board_b, direction, rng_b)
        assert result_a == result_b
        board_a, board_b = result_a.board, result_b.board

    full_terminal = [
        [2, 4, 2, 4], [4, 2, 4, 2], [2, 4, 2, 4], [4, 2, 4, 2],
    ]
    assert legal_moves(full_terminal) == []
    assert slide(full_terminal, "left")[0] == full_terminal
