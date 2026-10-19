"""
Free Growth Items: Gospels, Grimoires, Sutras, Balms and Incenses are sold
by the shop from the start of the game for 0 Macca.

Both tables are MMI binary blobs ("TBL1" sections) extracted from the
player's own pakchunk0 and repacked as a small override pak:

  ItemTable  section 0: 100-byte rows, row N-1 = item N
             (+16 item ID, +92 buying price)
  ShopTable  section 0: 16-byte rows (u16 item, u16 sort, u32 unlock A,
             u32 unlock B, u32); rows with A = B = 0 are always for sale
"""

from __future__ import annotations

import os
import struct

SHOP_PAK = "pakchunk98_FreeplayShop_P.pak"
TABLE_ROOT = "Project/Content/Blueprints/Gamedata/BinTable/"
ITEM_TABLE = TABLE_ROOT + "Item/ItemTable"
SHOP_TABLE = TABLE_ROOT + "Facility/Table/ShopTable"

GOSPEL = 82
GRIMOIRE = 83
SUTRAS = list(range(98, 109))      # Battle .. Calamity Sutra
BALMS = list(range(84, 91))       # Health .. Luck Balm
INCENSES = list(range(91, 98))    # Health .. Luck Incense
FREE_ITEMS = [GOSPEL, GRIMOIRE] + SUTRAS + BALMS + INCENSES

ITEM_ROW = 100
ITEM_ID_OFF = 16
ITEM_BUY_OFF = 92
SHOP_ROW = 16

# Offsets in the .uasset that track the .uexp length.
UASSET_SERIAL_SIZE = 590    # int64: len(uexp) - 4
UASSET_BULK_START = 169     # int32: len(uasset) + len(uexp) - 4


def _section(data: bytes | bytearray, index: int) -> tuple[int, int, int]:
    """(header offset, data offset, size) of the index-th TBL1 section."""
    pos = -1
    for _ in range(index + 1):
        pos = data.find(b"TBL1", pos + 1)
        if pos < 0:
            raise RuntimeError("table layout not recognised")
    size = struct.unpack_from("<I", data, pos + 4)[0]
    return pos, pos + 16, size


def edit_item_table(uexp: bytes) -> bytes:
    data = bytearray(uexp)
    _, base, size = _section(data, 0)
    for item in FREE_ITEMS:
        row = base + (item - 1) * ITEM_ROW
        if row + ITEM_ROW > base + size or struct.unpack_from("<i", data, row + ITEM_ID_OFF)[0] != item:
            raise RuntimeError(f"ItemTable row for item {item} not found - game update?")
        struct.pack_into("<i", data, row + ITEM_BUY_OFF, 0)
    return bytes(data)


def edit_shop_table(uasset: bytes, uexp: bytes) -> tuple[bytes, bytes]:
    data = bytearray(uexp)
    head, base, size = _section(data, 0)
    if size % SHOP_ROW:
        raise RuntimeError("ShopTable layout not recognised - game update?")
    rows = size // SHOP_ROW
    present, max_sort = set(), 0
    for i in range(rows):
        o = base + i * SHOP_ROW
        item, sort = struct.unpack_from("<HH", data, o)
        max_sort = max(max_sort, sort)
        if item in FREE_ITEMS:
            present.add(item)
            struct.pack_into("<II", data, o + 4, 0, 0)
    missing = [i for i in FREE_ITEMS if i not in present]
    if not missing:
        return uasset, bytes(data)

    # Append rows for items the shop never stocks.
    extra = b"".join(struct.pack("<HHIII", item, max_sort + 1 + n, 0, 0, 0)
                     for n, item in enumerate(missing))
    grow = len(extra)
    end = base + size
    data[end:end] = extra
    struct.pack_into("<I", data, head + 4, size + grow)

    # TBCR directory: section offsets after the first move with it.
    tbcr = data.find(b"TBCR")
    if tbcr < 0 or tbcr > head:
        raise RuntimeError("ShopTable directory not found - game update?")
    hdr_len, count = struct.unpack_from("<II", data, tbcr + 4)
    for k in range(1, count):
        p = tbcr + 12 + 4 * k
        struct.pack_into("<I", data, p, struct.unpack_from("<I", data, p)[0] + grow)

    # Byte-array property tag: int64 property size (= count + 4) and the
    # int32 element count right before the blob.
    count_at = tbcr - 4
    n_elems = struct.unpack_from("<i", data, count_at)[0]
    prop_size_at = data.rfind(struct.pack("<q", n_elems + 4), 0, count_at)
    if prop_size_at < 0:
        raise RuntimeError("ShopTable property header not found - game update?")
    struct.pack_into("<i", data, count_at, n_elems + grow)
    struct.pack_into("<q", data, prop_size_at, n_elems + 4 + grow)

    asset = bytearray(uasset)
    if struct.unpack_from("<q", asset, UASSET_SERIAL_SIZE)[0] != len(uexp) - 4 or \
       struct.unpack_from("<i", asset, UASSET_BULK_START)[0] != len(uasset) + len(uexp) - 4:
        raise RuntimeError("ShopTable header not recognised - game update?")
    struct.pack_into("<q", asset, UASSET_SERIAL_SIZE, len(uexp) - 4 + grow)
    struct.pack_into("<i", asset, UASSET_BULK_START, len(uasset) + len(uexp) - 4 + grow)
    return bytes(asset), bytes(data)


def build_shop_pak(game_dir: str, paks_subpath: str, source_pak: str,
                   repak: str, run_repak) -> None:
    """Build SHOP_PAK in the game's Paks folder. Raises RuntimeError."""
    import shutil
    import tempfile

    paks_dir = os.path.join(game_dir, paks_subpath)
    src = os.path.join(paks_dir, source_pak)
    if not os.path.isfile(src):
        raise RuntimeError(f"{source_pak} not found in {paks_dir}")

    def get(entry: str) -> bytes:
        return run_repak(repak, "get", src, entry)

    item_asset, item_exp = get(ITEM_TABLE + ".uasset"), get(ITEM_TABLE + ".uexp")
    shop_asset, shop_exp = get(SHOP_TABLE + ".uasset"), get(SHOP_TABLE + ".uexp")
    item_exp = edit_item_table(item_exp)
    files = {
        ITEM_TABLE + ".uasset": item_asset,
        ITEM_TABLE + ".uexp": item_exp,
    }
    files[SHOP_TABLE + ".uasset"], files[SHOP_TABLE + ".uexp"] = edit_shop_table(shop_asset, shop_exp)

    staging = tempfile.mkdtemp(prefix="smtvv_shop_")
    try:
        for entry, blob in files.items():
            path = os.path.join(staging, *entry.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(blob)
        out = os.path.join(paks_dir, SHOP_PAK)
        tmp = out + ".tmp"
        try:
            run_repak(repak, "pack", "--version", "V11", staging, tmp)
            os.replace(tmp, out)
        finally:
            if os.path.isfile(tmp):
                os.remove(tmp)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
