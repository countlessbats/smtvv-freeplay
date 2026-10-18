"""
Timed Quest Markers: the collectibles of the time-limited quests are marked
on the map and minimap while a run is under way.

  Mission 170  She Who Rules the Night   10 Young Stars
  Mission 181  (Cu Chulainn, Scathach)   38 Four-Leaf Clovers
  Mission 203  (Mad Gasser)              20 Poisonous Flower Buds placed in
                                         the field; buds dropped by Zhens
                                         are not marked

Each collectible becomes a quest-target row (ACTOR / SUB_TARGET) in the map's
minimap icon table. A row is shown while the quest's condition flag
(mis_..._3, set while the collection count runs; the game's own Zhen markers
use it too) is on and hidden by the collectible's own flag
(mis_..._ItemNN), which the quest clears at the start of every run.
Positions are the collectibles' placements in the quests' event levels.
"""

from __future__ import annotations

import os
import struct

import ue_asset

MAP_PAK = "pakchunk95_FreeplayMap_P.pak"
MAP_SOURCE_PAK = "pakchunk0-WindowsNoEditor.pak"
MINIMAP = "Project/Content/Blueprints/Gamedata/BinTable/Minimap/"

QUESTS = [
    {   # She Who Rules the Night (Tzitzimitl), Young Stars
        "table": "MinimapIcon_061_00_man_add", "template": "25",
        "on": "mis_m061_em2220_3", "item": "mis_m061_em2220_Item%02d", "data_id": 31700,
        "items": {
            1: (57453.6, -53023.2, 3263.8), 2: (58241.4, -49621.3, 3137.9),
            3: (56398.5, -46899.2, 2525.5), 4: (53437.6, -43640.1, 2324.6),
            5: (49894.1, -45389.2, 2763.9), 6: (51013.9, -48607.1, 2629.3),
            7: (49017.5, -51693.1, 3515.0), 8: (53949.6, -55272.3, 3382.3),
            9: (57883.0, -58415.5, 3605.5), 10: (58016.5, -59633.1, 3820.0),
        },
    },
    {   # Four-Leaf Clovers (Cu Chulainn and Scathach)
        "table": "MinimapIcon_060_00_man_add", "template": "21",
        "on": "mis_m062_em2330_3", "item": "mis_m062_em2330_Item%02d", "data_id": 31800,
        "items": {
            1: (-37031.3, -58242.2, 2047.6), 2: (-33563.4, -51031.5, 2091.2),
            3: (-35548.5, -49248.5, 2097.7), 4: (-34789.0, -48745.2, 2098.4),
            5: (-36051.2, -48761.6, 2097.7), 6: (-35424.6, -48759.6, 2097.6),
            7: (-35445.7, -48185.5, 2098.1), 8: (-31506.8, -47796.3, 2111.4),
            9: (-30189.8, -47844.0, 2098.4), 10: (-29331.3, -47914.8, 2094.9),
            11: (-26217.0, -48309.7, 2154.7), 12: (-24732.3, -49651.1, 2452.7),
            13: (-23097.2, -53270.1, 2394.6), 14: (-22327.1, -54987.2, 3194.7),
            15: (-38866.3, -62318.9, 1950.9), 16: (-34291.2, -64630.6, 1326.9),
            17: (-31207.9, -65227.4, 2136.1), 18: (-41301.9, -57059.7, 1932.9),
            19: (-44523.2, -54351.4, 1853.1), 20: (-46328.2, -49815.6, 1855.9),
            21: (-47103.7, -46052.9, 2098.3), 22: (-45934.8, -44058.5, 2261.7),
            23: (-36954.5, -33180.5, 2391.9), 24: (-34359.0, -33906.2, 2365.9),
            25: (-30567.1, -39256.0, 2177.1), 26: (-28239.4, -42325.4, 2181.4),
            27: (-21804.0, -46070.6, 5888.6), 28: (-21445.5, -47259.5, 5526.4),
            29: (-21381.2, -48444.9, 5428.3), 30: (-21461.4, -49213.6, 5468.1),
            31: (-21778.1, -50073.1, 5516.7), 32: (-25181.2, -57513.1, 2261.6),
            33: (-25810.9, -57238.4, 2177.4), 34: (-25920.2, -57751.2, 2185.3),
            35: (-26541.2, -57246.0, 2149.7), 36: (-25309.7, -58009.2, 2312.4),
            37: (-39614.3, -45074.3, 1667.9), 38: (-21852.6, -56659.2, 3671.8),
        },
    },
    {   # Poisonous Flower Buds (Mad Gasser), buds placed in the field
        "table": "MinimapIcon_064_00_man", "template": "70",
        "on": "mis_m064_em2550_3", "item": "mis_m064_em2550_Item%02d", "data_id": 32000,
        "items": {
            1: (108099.5, 54116.1, -8177.9), 2: (105101.8, 53292.9, -8801.8),
            3: (102831.9, 52763.9, -8993.2), 4: (98815.4, 47529.1, -8966.6),
            5: (99442.8, 43758.6, -8878.6), 6: (96950.8, 41770.5, -9233.1),
            7: (95198.5, 40650.4, -9036.7), 8: (110833.6, 68958.7, -8477.1),
            9: (109414.8, 72060.4, -8326.4), 10: (108439.8, 74883.3, -8183.8),
            11: (99913.3, 67783.2, -10136.6), 12: (98132.9, 64202.2, -10226.4),
            13: (94341.8, 55894.6, -8469.0), 14: (85832.1, 54302.7, -8996.3),
            15: (92120.1, 41974.6, -8687.7), 16: (88959.2, 45587.3, -8705.7),
            17: (86128.4, 58901.4, -8997.0), 18: (86513.8, 62242.5, -8974.9),
            19: (112879.9, 63851.3, -5359.1), 20: (104587.4, 75156.5, -7840.9),
        },
    },
]

SUB_TARGET = "E_MINIMAP_POI_ICON::E_MINIMAP_POI_ICON_SUB_TARGET"


def edit_table(uasset: bytes, uexp: bytes, quest: dict) -> tuple[bytes, bytes]:
    pk = ue_asset.Package(uasset, uexp)
    _count_at, rows = pk.table_rows()
    template = next((r for r in rows if r[0] == quest["template"]), None)
    if template is None:
        raise RuntimeError(f"{quest['table']}: template row not found - game update?")
    fields = pk.row_fields(template[1])
    if pk.name_of(pk.e, fields["MinimapIcon"][0]) != SUB_TARGET:
        raise RuntimeError(f"{quest['table']}: template row is not a quest target - game update?")
    used = {struct.unpack_from("<i", pk.e, pk.row_fields(r[1])["DataId"][0])[0] for r in rows}
    last = max(int(r[0]) for r in rows)
    base = template[1]
    blobs = []
    for n, (x, y, z) in sorted(quest["items"].items()):
        data_id = quest["data_id"] + n
        if data_id in used:
            raise RuntimeError(f"{quest['table']}: marker id {data_id} already used")
        row = bytearray(pk.e[template[1]:template[2]])
        index = last + len(blobs) + 1

        def put(field: str, blob: bytes) -> None:
            o = fields[field][0] - base
            row[o:o + len(blob)] = blob

        row[0:8] = pk.fname(str(index))
        put("DataId", struct.pack("<i", data_id))
        put("SaveId", struct.pack("<i", index))
        put("OnFlag", pk.fname(quest["on"]))
        put("OffFlag", pk.fname(quest["item"] % n))
        put("InactiveFlag", pk.fname("None"))
        put("WorldLocation", struct.pack("<3f", x, y, z))
        blobs.append(bytes(row))
    pk.append_rows(blobs)
    return pk.build()


def build_map_pak(game_dir: str, paks_subpath: str, repak: str, run_repak) -> None:
    """Build MAP_PAK in the game's Paks folder. Raises RuntimeError."""
    import shutil
    import tempfile

    paks_dir = os.path.join(game_dir, paks_subpath)
    src = os.path.join(paks_dir, MAP_SOURCE_PAK)
    if not os.path.isfile(src):
        raise RuntimeError(f"{MAP_SOURCE_PAK} not found in {paks_dir}")

    files = {}
    for quest in QUESTS:
        entry = MINIMAP + quest["table"]
        a, e = edit_table(run_repak(repak, "get", src, entry + ".uasset"),
                          run_repak(repak, "get", src, entry + ".uexp"), quest)
        files[entry + ".uasset"], files[entry + ".uexp"] = a, e

    staging = tempfile.mkdtemp(prefix="smtvv_map_")
    try:
        for entry, blob in files.items():
            path = os.path.join(staging, *entry.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(blob)
        out = os.path.join(paks_dir, MAP_PAK)
        tmp = out + ".tmp"
        try:
            run_repak(repak, "pack", "--version", "V11", staging, tmp)
            os.replace(tmp, out)
        finally:
            if os.path.isfile(tmp):
                os.remove(tmp)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
