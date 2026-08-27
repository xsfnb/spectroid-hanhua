# -*- coding: utf-8 -*-
"""Pure-python parser for Android resources.arsc (ResTable)."""
import struct

RES_NULL_TYPE = 0x0000
RES_STRING_POOL_TYPE = 0x0001
RES_TABLE_TYPE = 0x0002
RES_XML_TYPE = 0x0003
RES_TABLE_PACKAGE_TYPE = 0x0200
RES_TABLE_TYPE_TYPE = 0x0201
RES_TABLE_TYPE_SPEC_TYPE = 0x0202

SORTED_FLAG = 1 << 0
UTF8_FLAG = 1 << 8

TYPE_REFERENCE = 0x01
TYPE_ATTRIBUTE = 0x02
TYPE_STRING = 0x03
TYPE_FLOAT = 0x04
TYPE_DIMENSION = 0x05
TYPE_FRACTION = 0x06
TYPE_DYNAMIC_REFERENCE = 0x07
TYPE_DYNAMIC_ATTRIBUTE = 0x08
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11
TYPE_INT_BOOLEAN = 0x12
TYPE_INT_COLOR_ARGB8 = 0x1c
TYPE_INT_COLOR_RGB8 = 0x1d
TYPE_INT_COLOR_ARGB4 = 0x1e
TYPE_INT_COLOR_RGB4 = 0x1f
TYPE_NULL = 0x00

TYPE_NAMES = {
    0x01: 'reference', 0x02: 'attribute', 0x03: 'string', 0x04: 'float',
    0x05: 'dimension', 0x06: 'fraction', 0x07: 'dynamic_ref', 0x08: 'dynamic_attr',
    0x10: 'int_dec', 0x11: 'int_hex', 0x12: 'bool', 0x1c: 'color_argb8',
    0x1d: 'color_rgb8', 0x1e: 'color_argb4', 0x1f: 'color_rgb4', 0x00: 'null',
}


def u16(b, o): return struct.unpack_from('<H', b, o)[0]
def u32(b, o): return struct.unpack_from('<I', b, o)[0]


def decode_utf8_len(b, o):
    """Decode a variable-length length in the UTF-8 string pool format.
    Returns (length, new_offset)."""
    x = b[o]
    o += 1
    if x & 0x80:
        x = ((x & 0x7F) << 8) | b[o]
        o += 1
    return x, o


class StringPool(object):
    def __init__(self, data, offset):
        self.chunk_type, self.header_size, self.chunk_size = struct.unpack_from('<HHI', data, offset)
        (self.string_count, self.style_count, self.flags,
         self.strings_start, self.styles_start) = struct.unpack_from('<IIIII', data, offset + 8)
        self.offset = offset
        self.data = data
        self.utf8 = bool(self.flags & UTF8_FLAG)
        self.strings = []
        off = offset + self.header_size
        self.string_offsets = [u32(data, off + 4 * i) for i in range(self.string_count)]
        self.style_offsets = [u32(data, off + 4 * (self.string_count + i)) for i in range(self.style_count)]
        base = offset + self.strings_start
        for so in self.string_offsets:
            self.strings.append(self._read_string(base + so))

    def _read_string(self, p):
        d = self.data
        if self.utf8:
            u16len, p = decode_utf8_len(d, p)
            u8len, p = decode_utf8_len(d, p)
            end = p + u8len
            return d[p:end].decode('utf-8', errors='replace')
        else:
            length = u16(d, p)
            p += 2
            end = p + length * 2
            return d[p:end].decode('utf-16-le', errors='replace')

    def __repr__(self):
        return ('StringPool(count=%d styles=%d utf8=%s sorted=%s)' %
                (self.string_count, self.style_count, self.utf8, bool(self.flags & SORTED_FLAG)))


class ResValue(object):
    def __init__(self, data, offset):
        self.size, self.res0, self.data_type = struct.unpack_from('<HBB', data, offset)
        self.data = u32(data, offset + 4)

    def __repr__(self):
        return 'ResValue(type=%s data=%d)' % (TYPE_NAMES.get(self.data_type, hex(self.data_type)), self.data)


class Entry(object):
    def __init__(self, data, offset):
        self.offset = offset
        self.size, self.flags = struct.unpack_from('<HH', data, offset)
        self.key = u32(data, offset + 4)  # index into key pool
        self.complex = bool(self.flags & 0x0001)
        self.value = None
        self.map = None
        if not self.complex:
            self.value = ResValue(data, offset + 8)
        else:
            self.parent = u32(data, offset + 8)
            self.count = u32(data, offset + 12)
            self.map = []
            p = offset + 16
            for _ in range(self.count):
                name = u32(data, p)
                v = ResValue(data, p + 4)
                self.map.append((name, v))
                p += 12

    def __repr__(self):
        return 'Entry(key=%d complex=%s %s)' % (self.key, self.complex,
                                                self.value if self.value else ('map<%d>' % self.count))


class TypeChunk(object):
    """One ResTable_type (one config for one type)."""
    def __init__(self, data, offset):
        self.offset = offset
        self.chunk_type, self.header_size, self.chunk_size = struct.unpack_from('<HHI', data, offset)
        self.id, self.res0, self.res1 = struct.unpack_from('<BBH', data, offset + 8)
        self.entry_count = u32(data, offset + 12)
        self.entries_start = u32(data, offset + 16)
        self.config_size = u32(data, offset + 20)  # config starts at offset+20; its first field is its size
        self.config = data[offset + 20: offset + 20 + self.config_size]
        self.entry_offsets = [u32(data, offset + self.header_size + 4 * i)
                              for i in range(self.entry_count)]
        base = offset + self.entries_start
        self.entries = []
        for eo in self.entry_offsets:
            if eo == 0xFFFFFFFF:
                self.entries.append(None)
            else:
                self.entries.append(Entry(data, base + eo))

    def config_str(self):
        return config_to_string(self.config)

    def __repr__(self):
        return 'TypeChunk(id=%d entries=%d config=%s)' % (self.id, self.entry_count, self.config_str())


def config_to_string(cfg):
    out = []
    size = u32(cfg, 0)
    mcc, mnc = u16(cfg, 4), u16(cfg, 6)
    lang = cfg[8:10].decode('latin-1', errors='replace')
    country = cfg[10:12].decode('latin-1', errors='replace')
    if mcc != 0: out.append('mcc%d' % mcc)
    if mnc != 0: out.append('mnc%d' % mnc)
    if lang != '\x00\x00':
        # handle localeScript for android 7+
        ls = ''
        if size >= 48:
            ls = cfg[40:44].decode('latin-1', errors='replace').rstrip('\x00')
        if ls:
            out.append('b+%s+%s' % (ls, country if country != '\x00\x00' else ''))
        else:
            out.append(lang + (('-' + country) if country != '\x00\x00' else ''))
    orient, touch = cfg[12], cfg[13]
    density = u16(cfg, 14)
    if orient == 1: out.append('port')
    elif orient == 2: out.append('land')
    if density == 0xffff: out.append('nodpi')
    elif density != 0: out.append('dpi%d' % density)
    sdk = u16(cfg, 24)
    if sdk != 0: out.append('v%d' % sdk)
    sw = u16(cfg, 28)
    if sw != 0: out.append('sw%ddp' % sw)
    return '+'.join(out) if out else 'default'


class TypeSpecChunk(object):
    def __init__(self, data, offset):
        self.offset = offset
        self.chunk_type, self.header_size, self.chunk_size = struct.unpack_from('<HHI', data, offset)
        self.id, self.res0, self.res1 = struct.unpack_from('<BBH', data, offset + 8)
        self.entry_count = u32(data, offset + 12)
        self.flags = [u32(data, offset + 16 + 4 * i) for i in range(self.entry_count)]

    def __repr__(self):
        return 'TypeSpec(id=%d entries=%d)' % (self.id, self.entry_count)


class Package(object):
    def __init__(self, data, offset):
        self.offset = offset
        self.chunk_type, self.header_size, self.chunk_size = struct.unpack_from('<HHI', data, offset)
        self.id = u32(data, offset + 8)
        name_bytes = data[offset + 12: offset + 12 + 256]
        self.name = name_bytes.decode('utf-16-le', errors='replace').rstrip('\x00')
        self.type_strings = u32(data, offset + 268)
        self.last_public_type = u32(data, offset + 272)
        self.key_strings = u32(data, offset + 276)
        self.last_public_key = u32(data, offset + 280)
        self.type_id_offset = u32(data, offset + 284)

    def __repr__(self):
        return 'Package(id=%d name=%s)' % (self.id, self.name)


class ArscFile(object):
    def __init__(self, data):
        self.data = data
        assert u16(data, 0) == RES_TABLE_TYPE, 'not a resource table'
        self.header_size = u16(data, 2)
        self.total_size = u32(data, 4)
        self.package_count = u32(data, 8)
        self.string_pools = []   # (offset, StringPool) global pools
        self.packages = []       # Package
        # walk chunks sequentially
        off = self.header_size
        end = self.total_size
        while off < end:
            ctype, hsize, csize = struct.unpack_from('<HHI', data, off)
            if ctype == RES_STRING_POOL_TYPE:
                self.string_pools.append((off, StringPool(data, off)))
            elif ctype == RES_TABLE_PACKAGE_TYPE:
                self.packages.append(Package(data, off))
            elif ctype in (RES_TABLE_TYPE_TYPE, RES_TABLE_TYPE_SPEC_TYPE):
                pass  # parsed later inside package
            else:
                pass
            if csize == 0:
                break
            off += csize
        # parse package internals
        self.package_children = []  # (package_index, list of (offset, chunk))
        for pkg in self.packages:
            children = []
            off = pkg.offset + pkg.header_size
            pend = pkg.offset + pkg.chunk_size
            while off < pend:
                ctype, hsize, csize = struct.unpack_from('<HHI', data, off)
                if ctype == RES_STRING_POOL_TYPE:
                    children.append(('pool', off, StringPool(data, off)))
                elif ctype == RES_TABLE_TYPE_SPEC_TYPE:
                    children.append(('spec', off, TypeSpecChunk(data, off)))
                elif ctype == RES_TABLE_TYPE_TYPE:
                    children.append(('type', off, TypeChunk(data, off)))
                else:
                    children.append(('unknown', off, None))
                if csize == 0:
                    break
                off += csize
            self.package_children.append(children)


def main():
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else 'apk/resources.arsc'
    data = open(path, 'rb').read()
    arsc = ArscFile(data)
    print('total_size=%d packages=%d' % (arsc.total_size, arsc.package_count))
    for off, sp in arsc.string_pools:
        print('GLOBAL POOL at %d: %s' % (off, sp))
        for i, s in enumerate(sp.strings):
            print('   [%3d] %r' % (i, s))
    for pi, pkg in enumerate(arsc.packages):
        print('PACKAGE %d: %s' % (pi, pkg))
        for kind, off, obj in arsc.package_children[pi]:
            if kind == 'pool':
                print('  POOL at %d: %s' % (off, obj))
                for i, s in enumerate(obj.strings):
                    print('     [%3d] %r' % (i, s))
            elif kind == 'spec':
                print('  SPEC at %d: %s' % (off, obj))
            elif kind == 'type':
                print('  TYPE at %d: %s' % (off, obj))
                t = obj
                for idx, e in enumerate(t.entries):
                    if e is None:
                        continue
                    if not e.complex and e.value is not None and e.value.data_type == TYPE_STRING:
                        sp = arsc.string_pools[0][1]
                        sval = sp.strings[e.value.data] if e.value.data < len(sp.strings) else '<oob>'
                        print('     entry[%d] key=%d %r value=%r' % (idx, e.key, sval, sval))
                    else:
                        print('     entry[%d] key=%d %r' % (idx, e.key, e))


if __name__ == '__main__':
    main()
