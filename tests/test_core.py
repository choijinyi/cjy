import unittest

from btcminer.core import (bits_to_target, build_coinbase, build_header_prefix, build_merkle_root,
                           difficulty_to_target, header_hash, sha256d, swap_words,
                           target_to_difficulty)

GENESIS_COINBASE = (
    "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff4d04ffff001d"
    "0104455468652054696d65732030332f4a616e2f32303039204368616e63656c6c6f72206f6e206272696e6b206f66"
    "207365636f6e64206261696c6f757420666f722062616e6b73ffffffff0100f2052a01000000434104678afdb0fe55"
    "48271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba"
    "0b8d578a4c702b6bf11d5fac00000000"
)
GENESIS_HASH = "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"


def to_stratum_prevhash(display_hash: str) -> str:
    """블록 탐색기 표기 해시를 Stratum notify의 prevhash 형식으로 바꾼다."""
    return swap_words(bytes.fromhex(display_hash)[::-1]).hex()


class CoreTest(unittest.TestCase):
    def test_genesis_block_via_stratum_path(self):
        # 코인베이스를 임의 지점에서 coinb1 / extranonce1 / extranonce2 / coinb2로 나눠도 같아야 한다
        cb1, en1, en2, cb2 = (GENESIS_COINBASE[:84], GENESIS_COINBASE[84:92],
                              GENESIS_COINBASE[92:100], GENESIS_COINBASE[100:])
        coinbase = build_coinbase(cb1, en1, en2, cb2)
        root = build_merkle_root(coinbase, [])
        self.assertEqual(root[::-1].hex(),
                         "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b")
        prefix = build_header_prefix("00000001", "00" * 32, root, "495fab29", "1d00ffff")
        digest = header_hash(prefix, 2083236893)
        self.assertEqual(digest[::-1].hex(), GENESIS_HASH)
        self.assertLessEqual(int.from_bytes(digest, "little"), bits_to_target("1d00ffff"))

    def test_block_1_prevhash_conversion(self):
        merkle = bytes.fromhex("0e3e2357e806b6cdb1f70b54c3a3a17b6714ee1f0e68bebb44a74b1efd512098")[::-1]
        prefix = build_header_prefix("00000001", to_stratum_prevhash(GENESIS_HASH), merkle,
                                     format(1231469665, "08x"), "1d00ffff")
        self.assertEqual(header_hash(prefix, 2573394689)[::-1].hex(),
                         "00000000839a8e6886ab5951d76f411475428afc90947ee320161bbf18eb6048")

    def test_merkle_branch(self):
        a, b = b"\x01" * 32, b"\x02" * 32
        self.assertEqual(build_merkle_root(b"cb", [a, b]), sha256d(sha256d(sha256d(b"cb") + a) + b))

    def test_targets(self):
        self.assertEqual(bits_to_target("1d00ffff"), 0xFFFF * 2 ** 208)
        self.assertAlmostEqual(target_to_difficulty(bits_to_target("1d00ffff")), 1.0)
        self.assertAlmostEqual(target_to_difficulty(difficulty_to_target(1024)), 1024, places=6)


if __name__ == "__main__":
    unittest.main()
