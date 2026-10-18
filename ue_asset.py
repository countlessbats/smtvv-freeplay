"""
Minimal editor for cooked UE 4.27 packages (.uasset + .uexp) with tagged
properties: adds names to the name map, appends DataTable rows and replaces
strings, keeping every size and offset in the package consistent.
"""

from __future__ import annotations

import struct

PACKAGE_TAG = 0x9E2A83C1
PKG_FILTER_EDITOR_ONLY = 0x80000000


def _crc_tables() -> tuple[list[int], list[int]]:
    reflected, legacy = [], []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
        reflected.append(c)
        c = i << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if c & 0x80000000 else (c << 1) & 0xFFFFFFFF
        legacy.append(c)
    return reflected, legacy


_CRC, _LEGACY = _crc_tables()


def name_hash(s: str) -> int:
    """FNameEntrySerialized hashes: Strihash_DEPRECATED low, StrCrc32 high."""
    crc = 0xFFFFFFFF
    for ch in s:
        c = ord(ch)
        for _ in range(4):
            crc = (crc >> 8) ^ _CRC[(crc ^ c) & 0xFF]
            c >>= 8
    crc = ~crc & 0xFFFFFFFF
    h = 0
    for ch in s:
        h = ((h >> 8) & 0x00FFFFFF) ^ _LEGACY[(h ^ ord(ch.upper())) & 0xFF]
    return (h & 0xFFFF) | ((crc & 0xFFFF) << 16)


def fstring(s: str) -> bytes:
    if s.isascii():
        b = s.encode("ascii") + b"\0"
        return struct.pack("<i", len(b)) + b
    b = s.encode("utf-16-le") + b"\0\0"
    return struct.pack("<i", -(len(b) // 2)) + b


class _Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.d, self.p = data, pos

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def skip(self, n: int) -> None:
        self.p += n

    def fstr(self) -> str:
        n = self.i32()
        if n == 0:
            return ""
        if n < 0:
            s = self.d[self.p:self.p - 2 * n].decode("utf-16-le")[:-1]
            self.p += -2 * n
            return s
        s = self.d[self.p:self.p + n - 1].decode("latin-1")
        self.p += n
        return s


class Package:
    """One cooked package. Offsets in the summary are recorded as they are read."""

    def __init__(self, uasset: bytes, uexp: bytes):
        self.a, self.e = bytearray(uasset), bytearray(uexp)
        r = _Reader(self.a)
        if struct.unpack_from("<I", self.a, 0)[0] != PACKAGE_TAG:
            raise RuntimeError("not a UE package")
        r.skip(4)
        if r.i32() != -7:
            raise RuntimeError("unsupported package version")
        r.skip(12)
        r.skip(20 * r.i32())                     # custom versions
        self.at = {"header": r.p}
        r.skip(4)
        r.fstr()
        flags = struct.unpack_from("<I", self.a, r.p)[0]
        r.skip(4)
        self.at["name_count"] = r.p
        self.name_count = r.i32()
        self.name_offset = r.i32()
        if not flags & PKG_FILTER_EDITOR_ONLY:
            r.fstr()
        self.at["gatherable"] = r.p + 4
        r.skip(8)
        self.at["export_count"] = r.p
        self.export_count = r.i32()
        self.at["export_offset"] = r.p
        self.export_offset = r.i32()
        r.skip(4)
        self.at["import_offset"] = r.p
        r.skip(4)
        self.at["depends"] = r.p
        r.skip(8)
        self.at["soft_refs"] = r.p
        self.at["searchable"] = r.p + 4
        self.at["thumbnails"] = r.p + 8
        r.skip(12 + 16)
        gens = r.i32()
        self.at["gen_names"] = r.p + 8 * (gens - 1) + 4 if gens else None
        r.skip(8 * gens)
        for _ in range(2):                       # saved-by / compatible engine versions
            r.skip(10)
            r.fstr()
        r.skip(4)
        if r.i32():
            raise RuntimeError("compressed packages are not supported")
        r.skip(4)
        for _ in range(r.i32()):
            r.fstr()
        self.at["asset_registry"] = r.p
        self.at["bulk"] = r.p + 4
        self.at["world_tile"] = r.p + 12
        r.skip(16)
        r.skip(4 * r.i32())
        r.skip(4)
        self.at["preload"] = r.p

        r = _Reader(self.a, self.name_offset)
        self.names = []
        for _ in range(self.name_count):
            self.names.append(r.fstr())
            r.skip(4)
        self.name_end = r.p
        self.name_ix = {n: i for i, n in enumerate(self.names)}
        self.new_names: list[str] = []
        self.header_size = struct.unpack_from("<i", self.a, self.at["header"])[0]

    # -- names ------------------------------------------------------------
    def name(self, s: str) -> int:
        if s not in self.name_ix:
            self.name_ix[s] = len(self.names)
            self.names.append(s)
            self.new_names.append(s)
        return self.name_ix[s]

    def fname(self, s: str) -> bytes:
        return struct.pack("<ii", self.name(s), 0)

    def name_of(self, data: bytes, pos: int) -> str:
        i, n = struct.unpack_from("<ii", data, pos)
        return self.names[i] if n == 0 else f"{self.names[i]}_{n - 1}"

    # -- exports ------------------------------------------------------------
    def _export(self, k: int) -> int:
        """File offset of the k-th export entry in the .uasset."""
        return self.export_offset + k * 104

    def export_range(self, k: int = 0) -> tuple[int, int]:
        """[start, end) of the k-th export's data in the .uexp."""
        size, off = struct.unpack_from("<qq", self.a, self._export(k) + 28)
        return off - self.header_size, off - self.header_size + size

    # -- tagged properties ----------------------------------------------------
    def walk(self, pos: int, end: int, out: list) -> int:
        """Collect (size_field_pos, value_start, value_end, name, type) for each
        tag from pos, recursing into structs and struct arrays. Returns the
        position after the terminating None."""
        d = self.e
        while True:
            name = self.name_of(d, pos)
            pos += 8
            if name == "None":
                return pos
            typ = self.name_of(d, pos)
            size_at = pos + 8
            size = struct.unpack_from("<i", d, size_at)[0]
            pos += 16
            struct_name = inner = None
            if typ == "StructProperty":
                struct_name = self.name_of(d, pos)
                pos += 24
            elif typ == "BoolProperty":
                pos += 1
            elif typ in ("ByteProperty", "EnumProperty", "ArrayProperty", "SetProperty"):
                inner = self.name_of(d, pos)
                pos += 8
            elif typ == "MapProperty":
                pos += 16
            has_guid = d[pos]
            pos += 1
            if has_guid:
                pos += 16
            start = pos
            out.append((size_at, start, start + size, name, typ))
            if typ == "StructProperty" and struct_name not in (
                    "Vector", "Vector2D", "Rotator", "Quat", "Guid", "LinearColor", "Color",
                    "SoftObjectPath", "DateTime", "Timespan", "IntPoint"):
                self.walk(start, start + size, out)
            elif typ == "ArrayProperty" and inner == "StructProperty":
                n = struct.unpack_from("<i", d, start)[0]
                q = start + 4
                q += 16                                   # inner tag name + type
                inner_size_at = q
                inner_size = struct.unpack_from("<i", d, q)[0]
                q += 8
                inner_struct = self.name_of(d, q)
                q += 24 + 1
                out.append((inner_size_at, q, q + inner_size, name + "[]", inner_struct))
                for _ in range(n):
                    q = self.walk(q, start + size, out)
            pos = start + size

    def replace(self, at: int, old: bytes, new: bytes) -> None:
        """Replace bytes inside the first export's tagged properties, growing
        every enclosing property tag and the export itself."""
        if self.e[at:at + len(old)] != old:
            raise RuntimeError("asset contents not as expected")
        start, end = self.export_range(0)
        tags: list = []
        self.walk(start, end, tags)
        delta = len(new) - len(old)
        for size_at, v0, v1, _n, _t in tags:
            if v0 <= at and at + len(old) <= v1:
                struct.pack_into("<i", self.e, size_at,
                                 struct.unpack_from("<i", self.e, size_at)[0] + delta)
        self.e[at:at + len(old)] = new
        self._grow_export(0, delta)

    def _grow_export(self, k: int, delta: int) -> None:
        o = self._export(k) + 28
        struct.pack_into("<q", self.a, o, struct.unpack_from("<q", self.a, o)[0] + delta)
        self.exp_delta = getattr(self, "exp_delta", 0) + delta

    # -- data tables ------------------------------------------------------------
    def table_rows(self) -> tuple[int, list[tuple[str, int, int]]]:
        """(row-count position, [(row name, start, end)]) of a DataTable."""
        start, end = self.export_range(0)
        pos = self.walk(start, end, []) + 4
        count_at = pos
        n = struct.unpack_from("<i", self.e, pos)[0]
        pos += 4
        rows = []
        for _ in range(n):
            rn = self.name_of(self.e, pos)
            q = self.walk(pos + 8, end, [])
            rows.append((rn, pos, q))
            pos = q
        return count_at, rows

    def row_fields(self, start: int) -> dict[str, tuple[int, str]]:
        tags: list = []
        self.walk(start + 8, len(self.e), tags)
        return {n: (v0, t) for _s, v0, _v1, n, t in tags}

    def append_rows(self, blobs: list[bytes]) -> None:
        count_at, rows = self.table_rows()
        end = rows[-1][2] if rows else count_at + 4
        blob = b"".join(blobs)
        self.e[end:end] = blob
        struct.pack_into("<i", self.e, count_at, len(rows) + len(blobs))
        self._grow_export(0, len(blob))

    # -- output -------------------------------------------------------------
    def build(self) -> tuple[bytes, bytes]:
        a = self.a
        add = b"".join(fstring(s) + struct.pack("<I", name_hash(s)) for s in self.new_names)
        grow = len(add)
        exp_delta = getattr(self, "exp_delta", 0)

        def bump(at: int, by: int) -> None:
            v = struct.unpack_from("<i", a, at)[0]
            if v > self.name_offset:
                struct.pack_into("<i", a, at, v + by)

        if grow:
            struct.pack_into("<i", a, self.at["name_count"], len(self.names))
            if self.at["gen_names"] is not None:
                struct.pack_into("<i", a, self.at["gen_names"], len(self.names))
            for key in ("gatherable", "import_offset", "depends", "soft_refs", "searchable",
                        "thumbnails", "asset_registry", "world_tile", "preload"):
                bump(self.at[key], grow)
            struct.pack_into("<i", a, self.at["export_offset"], self.export_offset + grow)
            struct.pack_into("<i", a, self.at["header"], self.header_size + grow)
            for k in range(self.export_count):
                o = self._export(k) + 36
                struct.pack_into("<q", a, o, struct.unpack_from("<q", a, o)[0] + grow)
        bulk = self.at["bulk"]
        struct.pack_into("<q", a, bulk, struct.unpack_from("<q", a, bulk)[0] + grow + exp_delta)
        out = a[:self.name_end] + add + a[self.name_end:]
        return bytes(out), bytes(self.e)
