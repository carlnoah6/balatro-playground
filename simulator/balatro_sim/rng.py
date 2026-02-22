"""RNG system — precise port of Balatro's pseudohash + LÖVE2D PRNG.

Ported from SpectralPack/Immolate (OpenCL implementation).
Uses LFSR113 (Tausworthe combined generator), matching LuaJIT's math.random.
"""

from __future__ import annotations

import math
import struct

# ---------------------------------------------------------------------------
# Low-level PRNG — LFSR113 (matches LuaJIT / LÖVE2D)
# ---------------------------------------------------------------------------

_MASK64 = (1 << 64) - 1
_MASK32 = (1 << 32) - 1


def _to_u64(x: int) -> int:
    return x & _MASK64


def _to_i64(x: int) -> int:
    x = x & _MASK64
    if x >= (1 << 63):
        x -= (1 << 64)
    return x


class LuaRandom:
    """LFSR113 PRNG matching LuaJIT's math.random implementation.

    Ported from Immolate's util.cl `lrandom` struct.
    """

    def __init__(self):
        self.state = [0, 0, 0, 0]  # 4 x uint64
        self._out_bits = 0  # uint64

    def _randint(self):
        """Advance PRNG state and produce a 64-bit integer.

        Direct port of Immolate's _randint().
        Each component is a Tausworthe generator with different parameters.
        """
        r = 0

        # Component 0: (31, 45, 1, 18)
        z = _to_u64(self.state[0])
        z = _to_u64(((z << 31) ^ z) >> 45) ^ _to_u64((z & _to_u64(_to_i64(-1) << 1)) << 18)
        r ^= z
        self.state[0] = z

        # Component 1: (19, 30, 6, 28)
        z = _to_u64(self.state[1])
        z = _to_u64(((z << 19) ^ z) >> 30) ^ _to_u64((z & _to_u64(_to_i64(-1) << 6)) << 28)
        r ^= z
        self.state[1] = z

        # Component 2: (24, 48, 9, 7)
        z = _to_u64(self.state[2])
        z = _to_u64(((z << 24) ^ z) >> 48) ^ _to_u64((z & _to_u64(_to_i64(-1) << 9)) << 7)
        r ^= z
        self.state[2] = z

        # Component 3: (21, 39, 17, 8)
        z = _to_u64(self.state[3])
        z = _to_u64(((z << 21) ^ z) >> 39) ^ _to_u64((z & _to_u64(_to_i64(-1) << 17)) << 8)
        r ^= z
        self.state[3] = z

        self._out_bits = r

    def random(self) -> float:
        """Generate a random double in [0, 1).

        Matches LÖVE2D's math.random().
        """
        self._randint()
        # Set exponent to 1.0 (0x3FF), keep random mantissa
        bits = (self._out_bits & 0x000FFFFFFFFFFFFF) | 0x3FF0000000000000
        val = struct.unpack('d', struct.pack('Q', bits))[0]
        return val - 1.0

    def randint(self, min_val: int, max_val: int) -> int:
        """Generate a random integer in [min_val, max_val] inclusive."""
        r = self.random()
        return int(r * (max_val - min_val + 1)) + min_val


def lua_randomseed(d: float) -> LuaRandom:
    """Seed the PRNG from a float, matching LÖVE2D's math.randomseed().

    Direct port of Immolate's randomseed() function.
    """
    lr = LuaRandom()
    r = 0x11090601

    for i in range(4):
        m = 1 << (r & 0xFF)
        r >>= 8

        d = d * 3.14159265358979323846
        d = d + 2.7182818284590452354

        # Reinterpret double as uint64
        u = struct.unpack('Q', struct.pack('d', d))[0]
        if u < m:
            u += m
        lr.state[i] = _to_u64(u)

    # Warm up: discard first 10 values
    for _ in range(10):
        lr._randint()

    return lr


# ---------------------------------------------------------------------------
# pseudohash — string to float hash (Balatro's core RNG seed function)
# ---------------------------------------------------------------------------

def pseudohash(s: str) -> float:
    """Convert a string to a float in [0, 1).

    Precise port from Immolate's pseudohash() in util.cl.
    Uses the k=32 precision trick to match floating-point behavior.
    """
    num = 1.0
    k = 32
    scale = 1 << k  # 2^32

    for i in range(len(s) - 1, -1, -1):
        byte_val = ord(s[i])
        pos = i + 1  # 1-indexed

        # Full expression (what Lua computes, but with precision issues)
        raw = 1.1239285023 / num * byte_val * math.pi + math.pi * pos

        # Split into integer and fractional parts with k-bit scaling
        int_part = int(raw * scale)
        fract_a = math.modf((1.1239285023 / num * byte_val * math.pi) * scale)[0]
        fract_b = math.modf((math.pi * pos) * scale)[0]
        fract_part = math.modf(fract_a + fract_b)[0]

        num = math.modf((int_part + fract_part) / scale)[0]

    return num


def round_digits(f: float, d: int) -> float:
    """Round to d decimal digits, matching Immolate's roundDigits."""
    power = 10.0 ** d
    return round(f * power) / power


# ---------------------------------------------------------------------------
# RNGState — per-key state manager (mirrors G.GAME.pseudorandom)
# ---------------------------------------------------------------------------

class RNGState:
    """Manages per-key RNG state, mirroring G.GAME.pseudorandom in Balatro.

    Uses precise pseudohash + LFSR113 PRNG matching the actual game.
    """

    def __init__(self, seed: str):
        self.seed = seed
        self.hashed_seed = pseudohash(seed)
        self._state: dict[str, float] = {}

    def pseudoseed(self, key: str) -> float:
        """Get next random value for a given key.

        Each key maintains independent state. First call initializes from
        pseudohash(key + seed), subsequent calls advance via linear congruence.
        """
        if key not in self._state:
            self._state[key] = pseudohash(key + self.seed)

        # Advance state: linear congruential step
        raw = (2.134453429141 + self._state[key] * 1.72431234) % 1
        self._state[key] = round_digits(abs(raw), 13)
        return (self._state[key] + self.hashed_seed) / 2

    def pseudoseed_predict(self, key: str, predict_seed: str) -> float:
        """Predict mode — does not modify global state."""
        _pseed = pseudohash(key + predict_seed)
        _pseed = round_digits(abs((2.134453429141 + _pseed * 1.72431234) % 1), 13)
        return (_pseed + pseudohash(predict_seed)) / 2

    def pseudorandom(self, key: str, min_val: float = 0, max_val: float = 1) -> float:
        """Get a random value in [min_val, max_val] for the given key.

        Uses the precise LFSR113 PRNG seeded from pseudoseed output.
        """
        seed_val = self.pseudoseed(key)
        lr = lua_randomseed(seed_val)
        r = lr.random()
        return min_val + r * (max_val - min_val)

    def pseudorandom_int(self, key: str, min_val: int, max_val: int) -> int:
        """Get a random integer in [min_val, max_val] inclusive."""
        seed_val = self.pseudoseed(key)
        lr = lua_randomseed(seed_val)
        return lr.randint(min_val, max_val)

    def random_element(self, key: str, lst: list):
        """Pick a random element from a list."""
        if not lst:
            raise ValueError("Cannot pick from empty list")
        idx = self.pseudorandom_int(key, 0, len(lst) - 1)
        return lst[idx]

    def shuffle(self, key: str, lst: list) -> list:
        """Fisher-Yates shuffle using LFSR113 PRNG, returns new list.

        Matches Immolate's shuffle_deck implementation.
        """
        seed_val = self.pseudoseed(key)
        lr = lua_randomseed(seed_val)
        result = list(lst)
        for i in range(len(result) - 1, 0, -1):
            j = lr.randint(1, i + 1) - 1  # Lua is 1-indexed
            result[i], result[j] = result[j], result[i]
        return result

    def copy(self) -> "RNGState":
        """Deep copy for MCTS branching."""
        new = RNGState(self.seed)
        new.hashed_seed = self.hashed_seed
        new._state = dict(self._state)
        return new

    def get_state_dict(self) -> dict:
        """Serialize for save/load."""
        return {"seed": self.seed, "states": dict(self._state)}

    @classmethod
    def from_state_dict(cls, d: dict) -> "RNGState":
        rng = cls(d["seed"])
        rng._state = dict(d["states"])
        return rng
