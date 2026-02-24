"""RNG system — precise port of Balatro's pseudohash + LÖVE2D PRNG.

Ported from SpectralPack/Immolate (OpenCL implementation).
Uses LFSR113 (Tausworthe combined generator), matching LuaJIT's math.random.

v2: Immolate node-key architecture for exact RNG chain reproduction.
"""

from __future__ import annotations

import math
import struct
from enum import IntEnum

# ---------------------------------------------------------------------------
# Immolate-compatible enums (from cache.cl)
# ---------------------------------------------------------------------------

class RType(IntEnum):
    """Random type — determines the type_str component of a node key."""
    Joker1 = 0
    Joker2 = 1
    Joker3 = 2
    Joker4 = 3
    JokerRarity = 4
    JokerEdition = 5
    Misprint = 6
    StdHasEnhancement = 7
    Enhancement = 8
    Card = 9
    StdEdition = 10
    StdHasSeal = 11
    StdSeal = 12
    ShopPack = 13
    Tarot = 14
    Spectral = 15
    Tags = 16
    ShuffleNewRound = 17
    CardType = 18
    Planet = 19
    LuckyMult = 20
    LuckyMoney = 21
    Sigil = 22
    Ouija = 23
    WheelOfFortune = 24
    GrosMichel = 25
    Cavendish = 26
    Voucher = 27
    VoucherTag = 28
    OrbitalTag = 29
    Soul = 30
    Erratic = 31
    Eternal = 32
    Perishable = 33
    EternalPerishable = 34
    EternalPerishablePack = 35
    RentalPack = 36
    Rental = 37
    Boss = 38


_TYPE_STR: dict[int, str] = {
    RType.Joker1: "Joker1",
    RType.Joker2: "Joker2",
    RType.Joker3: "Joker3",
    RType.Joker4: "Joker4",
    RType.JokerRarity: "rarity",
    RType.JokerEdition: "edi",
    RType.Misprint: "misprint",
    RType.StdHasEnhancement: "stdset",
    RType.Enhancement: "Enhanced",
    RType.Card: "front",
    RType.StdEdition: "standard_edition",
    RType.StdHasSeal: "stdseal",
    RType.StdSeal: "stdsealtype",
    RType.ShopPack: "shop_pack",
    RType.Tarot: "Tarot",
    RType.Spectral: "Spectral",
    RType.Tags: "Tag",
    RType.ShuffleNewRound: "nr",
    RType.CardType: "cdt",
    RType.Planet: "Planet",
    RType.LuckyMult: "lucky_mult",
    RType.LuckyMoney: "lucky_money",
    RType.Sigil: "sigil",
    RType.Ouija: "ouija",
    RType.WheelOfFortune: "wheel_of_fortune",
    RType.GrosMichel: "gros_michel",
    RType.Cavendish: "cavendish",
    RType.Voucher: "Voucher",
    RType.VoucherTag: "Voucher_fromtag",
    RType.OrbitalTag: "orbital",
    RType.Soul: "soul_",
    RType.Erratic: "erratic",
    RType.Eternal: "stake_shop_joker_eternal",
    RType.Perishable: "ssjp",
    RType.EternalPerishable: "etperpoll",
    RType.EternalPerishablePack: "packetper",
    RType.RentalPack: "packssjr",
    RType.Rental: "ssjr",
    RType.Boss: "boss",
}


class RSource(IntEnum):
    """RNG source — determines the source_str component of a node key."""
    Shop = 0
    Emperor = 1
    HighPriestess = 2
    Judgement = 3
    Wraith = 4
    Arcana = 5
    Celestial = 6
    Spectral = 7
    Standard = 8
    Buffoon = 9
    Vagabond = 10
    Superposition = 11
    Seance = 12
    SixthSense = 13
    TopUp = 14
    RareTag = 15
    UncommonTag = 16
    BlueSeal = 17
    PurpleSeal = 18
    EightBall = 19
    Soul = 20
    RiffRaff = 21
    Cartomancer = 22
    Null = 23


_SOURCE_STR: dict[int, str] = {
    RSource.Shop: "sho",
    RSource.Emperor: "emp",
    RSource.HighPriestess: "pri",
    RSource.Judgement: "jud",
    RSource.Wraith: "wra",
    RSource.Arcana: "ar1",
    RSource.Celestial: "pl1",
    RSource.Spectral: "spe",
    RSource.Standard: "sta",
    RSource.Buffoon: "buf",
    RSource.Vagabond: "vag",
    RSource.Superposition: "sup",
    RSource.Seance: "sea",
    RSource.SixthSense: "sixth",
    RSource.TopUp: "top",
    RSource.RareTag: "rta",
    RSource.UncommonTag: "uta",
    RSource.BlueSeal: "blusl",
    RSource.PurpleSeal: "8ba",
    RSource.EightBall: "8ba",
    RSource.Soul: "sou",
    RSource.RiffRaff: "rif",
    RSource.Cartomancer: "car",
    RSource.Null: "",
}


def _resample_str(n: int) -> str:
    """Resample suffix matching Immolate's resample_str()."""
    if n == 0:
        return ""
    return f"_resample{n + 1}"


# ---------------------------------------------------------------------------
# Node types — mirrors Immolate's ntype enum (cache.cl:74-77)
# ---------------------------------------------------------------------------

class NType(IntEnum):
    """Node parameter types — determines how each (ntype, value) pair
    is converted to a string component of the node key."""
    Type = 0      # N_Type → type_str(value)
    Source = 1    # N_Source → source_str(value)
    Ante = 2      # N_Ante → str(value)
    Resample = 3  # N_Resample → resample_str(value)


def _node_str(nt: NType, value: int) -> str:
    """Convert a single (ntype, value) pair to its string component.
    Mirrors Immolate's node_str() in cache.cl:180-185."""
    if nt == NType.Type:
        return _TYPE_STR.get(value, "")
    elif nt == NType.Source:
        return _SOURCE_STR.get(value, "")
    elif nt == NType.Ante:
        return str(value)
    elif nt == NType.Resample:
        return _resample_str(value)
    return ""


def build_node_key(*pairs: tuple[NType, int]) -> str:
    """Build an Immolate-compatible node key from (ntype, value) pairs.

    Each pair is converted via _node_str() and concatenated in order.
    The seed is appended by RNGState.pseudoseed() when hashing.

    This matches Immolate's get_node_child() which iterates:
        phvalue = node_str(nts[0], ids[0])
        for i in 1..num: phvalue += node_str(nts[i], ids[i])
        phvalue += seed
    """
    return "".join(_node_str(nt, val) for nt, val in pairs)


# Legacy convenience wrapper (deprecated — use build_node_key for precision)
def node_key(
    rtype: RType,
    source: RSource | None = None,
    ante: int | None = None,
    resample: int = 0,
) -> str:
    """Build node key with fixed order: type [+ source] [+ ante] [+ resample].
    WARNING: This does NOT match all Immolate call sites. Use build_node_key()
    for precise control over parameter order."""
    key = _TYPE_STR[rtype]
    if source is not None:
        key += _SOURCE_STR[source]
    if ante is not None:
        key += str(ante)
    key += _resample_str(resample)
    return key


# ---------------------------------------------------------------------------
# Low-level PRNG — LFSR113 (matches LuaJIT / LÖVE2D)
# ---------------------------------------------------------------------------

_MASK64 = (1 << 64) - 1


def _to_u64(x: int) -> int:
    return x & _MASK64


def _to_i64(x: int) -> int:
    x = x & _MASK64
    if x >= (1 << 63):
        x -= (1 << 64)
    return x


class LuaRandom:
    """LFSR113 PRNG matching LuaJIT's math.random implementation."""

    __slots__ = ("state", "_out_bits")

    def __init__(self):
        self.state = [0, 0, 0, 0]
        self._out_bits = 0

    def _randint(self):
        r = 0
        # Each component: z = ((_to_u64(z<<A) ^ z) >> B) ^ _to_u64((z & mask_C) << D)
        # Must mask left-shifts to 64 bits to match C overflow semantics.
        z = _to_u64(self.state[0])
        z = (_to_u64(_to_u64(z << 31) ^ z) >> 45) ^ _to_u64((z & _to_u64(_to_i64(-1) << 1)) << 18)
        r ^= z; self.state[0] = z

        z = _to_u64(self.state[1])
        z = (_to_u64(_to_u64(z << 19) ^ z) >> 30) ^ _to_u64((z & _to_u64(_to_i64(-1) << 6)) << 28)
        r ^= z; self.state[1] = z

        z = _to_u64(self.state[2])
        z = (_to_u64(_to_u64(z << 24) ^ z) >> 48) ^ _to_u64((z & _to_u64(_to_i64(-1) << 9)) << 7)
        r ^= z; self.state[2] = z

        z = _to_u64(self.state[3])
        z = (_to_u64(_to_u64(z << 21) ^ z) >> 39) ^ _to_u64((z & _to_u64(_to_i64(-1) << 17)) << 8)
        r ^= z; self.state[3] = z

        self._out_bits = r

    def random(self) -> float:
        self._randint()
        bits = (self._out_bits & 0x000FFFFFFFFFFFFF) | 0x3FF0000000000000
        val = struct.unpack('d', struct.pack('Q', bits))[0]
        return val - 1.0

    def randint(self, min_val: int, max_val: int) -> int:
        r = self.random()
        return int(r * (max_val - min_val + 1)) + min_val


def lua_randomseed(d: float) -> LuaRandom:
    """Seed the PRNG from a float, matching LÖVE2D's math.randomseed()."""
    lr = LuaRandom()
    r = 0x11090601
    for i in range(4):
        m = 1 << (r & 0xFF)
        r >>= 8
        d = d * 3.14159265358979323846
        d = d + 2.7182818284590452354
        u = struct.unpack('Q', struct.pack('d', d))[0]
        if u < m:
            u += m
        lr.state[i] = _to_u64(u)
    for _ in range(10):
        lr._randint()
    return lr


# ---------------------------------------------------------------------------
# pseudohash — string to float hash
# ---------------------------------------------------------------------------

def pseudohash(s: str) -> float:
    """Convert a string to a float in [0, 1). Matches Immolate's pseudohash()."""
    num = 1.0
    k = 32
    scale = 1 << k

    for i in range(len(s) - 1, -1, -1):
        byte_val = ord(s[i])
        pos = i + 1
        raw = 1.1239285023 / num * byte_val * math.pi + math.pi * pos
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
# RNGState — per-key state manager (mirrors Immolate's cache)
# ---------------------------------------------------------------------------

class RNGState:
    """Manages per-key RNG state using Immolate's node-key architecture.

    Each unique key string maps to an independent RNG node. The key is built
    from type_str + source_str + ante_str + resample_str (see node_key()).
    The seed is appended when computing the initial pseudohash.
    """

    __slots__ = ("seed", "hashed_seed", "_state")

    def __init__(self, seed: str):
        self.seed = seed
        self.hashed_seed = pseudohash(seed)
        self._state: dict[str, float] = {}

    def pseudoseed(self, key: str) -> float:
        """Get next random value for a given key.

        Each key maintains independent state. First call initializes from
        pseudohash(key + seed), subsequent calls advance via linear congruence.
        Matches Immolate's get_node_child().
        """
        if key not in self._state:
            self._state[key] = pseudohash(key + self.seed)

        raw = (2.134453429141 + self._state[key] * 1.72431234) % 1
        self._state[key] = round_digits(abs(raw), 13)
        return (self._state[key] + self.hashed_seed) / 2

    def pseudoseed_predict(self, key: str, predict_seed: str) -> float:
        """Predict mode — does not modify global state."""
        _pseed = pseudohash(key + predict_seed)
        _pseed = round_digits(abs((2.134453429141 + _pseed * 1.72431234) % 1), 13)
        return (_pseed + pseudohash(predict_seed)) / 2

    # -- High-level convenience methods using node_key (legacy, fixed order) --

    def node_random(
        self,
        rtype: RType,
        source: RSource | None = None,
        ante: int | None = None,
        resample: int = 0,
    ) -> float:
        """Get a random float using legacy node_key (fixed order).
        WARNING: Use raw_random() with build_node_key() for precise control."""
        key = node_key(rtype, source, ante, resample)
        seed_val = self.pseudoseed(key)
        lr = lua_randomseed(seed_val)
        return lr.random()

    def node_randint(
        self,
        rtype: RType,
        source: RSource | None = None,
        ante: int | None = None,
        resample: int = 0,
        *,
        min_val: int = 0,
        max_val: int = 1,
    ) -> int:
        """Get a random int using legacy node_key (fixed order)."""
        key = node_key(rtype, source, ante, resample)
        seed_val = self.pseudoseed(key)
        lr = lua_randomseed(seed_val)
        return lr.randint(min_val, max_val)

    def node_element(
        self,
        rtype: RType,
        lst: list,
        source: RSource | None = None,
        ante: int | None = None,
        resample: int = 0,
    ):
        """Pick a random element using legacy node_key (fixed order)."""
        if not lst:
            raise ValueError("Cannot pick from empty list")
        key = node_key(rtype, source, ante, resample)
        seed_val = self.pseudoseed(key)
        lr = lua_randomseed(seed_val)
        idx = lr.randint(0, len(lst) - 1)
        return lst[idx]

    # -- Precise methods using build_node_key (matches Immolate exactly) --

    def raw_random(self, key: str) -> float:
        """Get random float using a pre-built node key string.
        Use with build_node_key() for exact Immolate RNG reproduction."""
        seed_val = self.pseudoseed(key)
        lr = lua_randomseed(seed_val)
        return lr.random()

    def raw_randint(self, key: str, min_val: int, max_val: int) -> int:
        """Get random int using a pre-built node key string."""
        seed_val = self.pseudoseed(key)
        lr = lua_randomseed(seed_val)
        return lr.randint(min_val, max_val)

    def raw_element(self, key: str, lst: list):
        """Pick random element using a pre-built node key string.
        Matches Immolate's randchoice: l_randint(1, len) then 0-indexed."""
        if not lst:
            raise ValueError("Cannot pick from empty list")
        seed_val = self.pseudoseed(key)
        lr = lua_randomseed(seed_val)
        idx = lr.randint(1, len(lst)) - 1
        return lst[idx]

    # -- Legacy flat-key API (still used by some callers) --

    def pseudorandom(self, key: str, min_val: float = 0, max_val: float = 1) -> float:
        """Get a random value in [min_val, max_val] for the given key."""
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
        """Fisher-Yates shuffle using LFSR113 PRNG, returns new list."""
        seed_val = self.pseudoseed(key)
        lr = lua_randomseed(seed_val)
        result = list(lst)
        for i in range(len(result) - 1, 0, -1):
            j = lr.randint(1, i + 1) - 1
            result[i], result[j] = result[j], result[i]
        return result

    def copy(self) -> "RNGState":
        """Deep copy for MCTS branching."""
        new = RNGState.__new__(RNGState)
        new.seed = self.seed
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
