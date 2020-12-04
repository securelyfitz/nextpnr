#!/usr/bin/env python3
import argparse
import json
import sys

tiletype_names = dict()

parser = argparse.ArgumentParser(description="import MachXO2 routing and bels from Project Trellis")
parser.add_argument("device", type=str, help="target device")
parser.add_argument("-p", "--constids", type=str, help="path to constids.inc")
parser.add_argument("-g", "--gfxh", type=str, help="path to gfx.h (unused)")
parser.add_argument("-L", "--libdir", type=str, action="append", help="extra Python library path")
args = parser.parse_args()

sys.path += args.libdir
import pytrellis
import database

# Get the index for a tiletype
def get_tiletype_index(name):
    if name in tiletype_names:
        return tiletype_names[name]
    idx = len(tiletype_names)
    tiletype_names[name] = idx
    return idx


constids = dict()


class BinaryBlobAssembler:
    def l(self, name, ltype = None, export = False):
        if ltype is None:
            print("label %s" % (name,))
        else:
            print("label %s %s" % (name, ltype))

    def r(self, name, comment):
        if comment is None:
            print("ref %s" % (name,))
        else:
            print("ref %s %s" % (name, comment))

    def s(self, s, comment):
        assert "|" not in s
        print("str |%s| %s" % (s, comment))

    def u8(self, v, comment):
        if comment is None:
            print("u8 %d" % (v,))
        else:
            print("u8 %d %s" % (v, comment))

    def u16(self, v, comment):
        if comment is None:
            print("u16 %d" % (v,))
        else:
            print("u16 %d %s" % (v, comment))

    def u32(self, v, comment):
        if comment is None:
            print("u32 %d" % (v,))
        else:
            print("u32 %d %s" % (v, comment))

    def pre(self, s):
        print("pre %s" % s)

    def post(self, s):
        print("post %s" % s)

    def push(self, name):
        print("push %s" % name)

    def pop(self):
        print("pop")

def write_database(dev_name, chip, rg, endianness):
    def write_loc(loc, sym_name):
        bba.u16(loc.x, "%s.x" % sym_name)
        bba.u16(loc.y, "%s.y" % sym_name)

    # Use Lattice naming conventions, so convert to 1-based col indexing.
    def get_wire_name(loc, idx):
        tile = rg.tiles[loc]
        return "R{}C{}_{}".format(loc.y, loc.x + 1, rg.to_str(tile.wires[idx].name))

    # Before doing anything, ensure sorted routing graph iteration matches
    # y, x
    tile_iter = list(sorted(rg.tiles, key=lambda l : (l.key().y, l.key().x)))

    i = 1 # Drop (-2, -2) location.
    for y in range(0, max_row+1):
        for x in range(0, max_col+1):
            l = tile_iter[i]
            assert((y, x) == (l.key().y, l.key().x))
            i = i + 1

    bba = BinaryBlobAssembler()
    bba.pre('#include "nextpnr.h"')
    bba.pre('#include "embed.h"')
    bba.pre('NEXTPNR_NAMESPACE_BEGIN')
    bba.post('EmbeddedFile chipdb_file_%s("machxo2/chipdb-%s.bin", chipdb_blob_%s);' % (dev_name, dev_name, dev_name))
    bba.post('NEXTPNR_NAMESPACE_END')
    bba.push("chipdb_blob_%s" % args.device)
    bba.r("chip_info", "chip_info")

    # Nominally should be in order, but support situations where python
    # decides to iterate over rg.tiles out-of-order.
    for lt in sorted(rg.tiles, key=lambda l : (l.key().y, l.key().x)):
        l = lt.key()
        t = lt.data()

        # Do not include special globals location for now.
        if (l.x, l.y) == (-2, -2):
            continue

        if len(t.arcs) > 0:
            bba.l("loc%d_%d_pips" % (l.y, l.x), "PipInfoPOD")
            for arc in t.arcs:
                write_loc(arc.srcWire.rel, "src")
                write_loc(arc.sinkWire.rel, "dst")
                bba.u32(arc.srcWire.id, "src_idx {}".format(get_wire_name(arc.srcWire.rel, arc.srcWire.id)))
                bba.u32(arc.sinkWire.id, "dst_idx {}".format(get_wire_name(arc.sinkWire.rel, arc.sinkWire.id)))
                src_name = get_wire_name(arc.srcWire.rel, arc.srcWire.id)
                snk_name = get_wire_name(arc.sinkWire.rel, arc.sinkWire.id)
                # bba.u32(get_pip_class(src_name, snk_name), "timing_class")
                bba.u16(get_tiletype_index(rg.to_str(arc.tiletype)), "tile_type")
                cls = arc.cls
                bba.u8(arc.cls, "pip_type")
                bba.u8(0, "padding")

        if len(t.wires) > 0:
            for wire_idx in range(len(t.wires)):
                wire = t.wires[wire_idx]
                if len(wire.arcsDownhill) > 0:
                    bba.l("loc%d_%d_wire%d_downpips" % (l.y, l.x, wire_idx), "PipLocatorPOD")
                    for dp in wire.arcsDownhill:
                        write_loc(dp.rel, "rel_loc")
                        bba.u32(dp.id, "index")
                if len(wire.arcsUphill) > 0:
                    bba.l("loc%d_%d_wire%d_uppips" % (l.y, l.x, wire_idx), "PipLocatorPOD")
                    for up in wire.arcsUphill:
                        write_loc(up.rel, "rel_loc")
                        bba.u32(up.id, "index")
                if len(wire.belPins) > 0:
                    bba.l("loc%d_%d_wire%d_belpins" % (l.y, l.x, wire_idx), "BelPortPOD")
                    for bp in wire.belPins:
                        write_loc(bp.bel.rel, "rel_bel_loc")
                        bba.u32(bp.bel.id, "bel_index")
                        bba.u32(constids[rg.to_str(bp.pin)], "port")

            bba.l("loc%d_%d_wires" % (l.y, l.x), "WireInfoPOD")
            for wire_idx in range(len(t.wires)):
                wire = t.wires[wire_idx]
                bba.s(rg.to_str(wire.name), "name")
                # bba.u32(constids[wire_type(ddrg.to_str(wire.name))], "type")
                # if ("TILE_WIRE_" + ddrg.to_str(wire.name)) in gfx_wire_ids:
                #     bba.u32(gfx_wire_ids["TILE_WIRE_" + ddrg.to_str(wire.name)], "tile_wire")
                # else:
                bba.u32(0, "tile_wire")
                bba.u32(len(wire.arcsUphill), "num_uphill")
                bba.u32(len(wire.arcsDownhill), "num_downhill")
                bba.r("loc%d_%d_wire%d_uppips" % (l.y, l.x, wire_idx) if len(wire.arcsUphill) > 0 else None, "pips_uphill")
                bba.r("loc%d_%d_wire%d_downpips" % (l.y, l.x, wire_idx) if len(wire.arcsDownhill) > 0 else None, "pips_downhill")
                bba.u32(len(wire.belPins), "num_bel_pins")
                bba.r("loc%d_%d_wire%d_belpins" % (l.y, l.x, wire_idx) if len(wire.belPins) > 0 else None, "bel_pins")

        if len(t.bels) > 0:
            for bel_idx in range(len(t.bels)):
                bel = t.bels[bel_idx]
                bba.l("loc%d_%d_bel%d_wires" % (l.y, l.x, bel_idx), "BelWirePOD")
                for pin in bel.wires:
                    write_loc(pin.wire.rel, "rel_wire_loc")
                    bba.u32(pin.wire.id, "wire_index")
                    bba.u32(constids[rg.to_str(pin.pin)], "port")
                    bba.u32(int(pin.dir), "dir")
            bba.l("loc%d_%d_bels" % (l.y, l.x), "BelInfoPOD")
            for bel_idx in range(len(t.bels)):
                bel = t.bels[bel_idx]
                bba.s(rg.to_str(bel.name), "name")
                bba.u32(constids[rg.to_str(bel.type)], "type")
                bba.u32(bel.z, "z")
                bba.u32(len(bel.wires), "num_bel_wires")
                bba.r("loc%d_%d_bel%d_wires" % (l.y, l.x, bel_idx), "bel_wires")

    bba.l("tiles", "TileTypePOD")
    for lt in sorted(rg.tiles, key=lambda l : (l.key().y, l.key().x)):
        l = lt.key()
        t = lt.data()

        if (l.y, l.x) == (-2, -2):
            continue

        bba.u32(len(t.bels), "num_bels")
        bba.u32(len(t.wires), "num_wires")
        bba.u32(len(t.arcs), "num_pips")
        bba.r("loc%d_%d_bels" % (l.y, l.x) if len(t.bels) > 0 else None, "bel_data")
        bba.r("loc%d_%d_wires" % (l.y, l.x) if len(t.wires) > 0 else None, "wire_data")
        bba.r("loc%d_%d_pips" % (l.y, l.x) if len(t.arcs) > 0 else None, "pips_data")

    for y in range(0, max_row+1):
        for x in range(0, max_col+1):
            bba.l("tile_info_%d_%d" % (x, y), "TileNamePOD")
            for tile in chip.get_tiles_by_position(y, x):
                bba.s(tile.info.name, "name")
                bba.u16(get_tiletype_index(tile.info.type), "type_idx")
                bba.u16(0, "padding")

    bba.l("tiles_info", "TileInfoPOD")
    for y in range(0, max_row+1):
        for x in range(0, max_col+1):
            bba.u32(len(chip.get_tiles_by_position(y, x)), "num_tiles")
            bba.r("tile_info_%d_%d" % (x, y), "tile_names")

    bba.l("tiletype_names", "RelPtr<char>")
    for tt, idx in sorted(tiletype_names.items(), key=lambda x: x[1]):
        bba.s(tt, "name")


    bba.l("chip_info")
    bba.u32(max_col + 1, "width")
    bba.u32(max_row + 1, "height")
    bba.u32((max_col + 1) * (max_row + 1), "num_tiles")
    bba.u32(0, "num_packages") # len(packages)
    bba.u32(0, "num_pios") # len(pindata)
    bba.u32(const_id_count, "const_id_count")

    bba.r("tiles", "tiles")
    bba.r("tiletype_names", "tiletype_names")
    bba.r("tiles_info", "tile_info")

    bba.pop()


dev_names = {"1200": "LCMXO2-1200HC"}

def main():
    global max_row, max_col, const_id_count

    pytrellis.load_database(database.get_db_root())
    args = parser.parse_args()

    const_id_count = 1 # count ID_NONE
    with open(args.constids) as f:
        for line in f:
            line = line.replace("(", " ")
            line = line.replace(")", " ")
            line = line.split()
            if len(line) == 0:
                continue
            assert len(line) == 2
            assert line[0] == "X"
            idx = len(constids) + 1
            constids[line[1]] = idx
            const_id_count += 1

    constids["SLICE"] = constids["FACADE_SLICE"]
    constids["PIO"] = constids["FACADE_IO"]

    chip = pytrellis.Chip(dev_names[args.device])
    rg = pytrellis.make_optimized_chipdb(chip)
    max_row = chip.get_max_row()
    max_col = chip.get_max_col()
    bba = write_database(args.device, chip, rg, "le")



if __name__ == "__main__":
    main()
