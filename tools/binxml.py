# -*- coding: utf-8 -*-
"""Binary Android XML decode/encode (aapt2 format: RES_XML_TYPE 0x0003 root)."""
import struct

RES_STRING_POOL_TYPE = 0x0001
RES_XML_RESOURCE_MAP_TYPE = 0x0180
RES_XML_START_NAMESPACE_TYPE = 0x0100
RES_XML_END_NAMESPACE_TYPE = 0x0101
RES_XML_START_ELEMENT_TYPE = 0x0102
RES_XML_END_ELEMENT_TYPE = 0x0103
RES_XML_CDATA_TYPE = 0x0104

UTF8_FLAG = 1 << 8

TYPE_REFERENCE = 0x01
TYPE_ATTRIBUTE = 0x02
TYPE_STRING = 0x03
TYPE_FLOAT = 0x04
TYPE_DIMENSION = 0x05
TYPE_FRACTION = 0x06
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11
TYPE_INT_BOOLEAN = 0x12
TYPE_INT_COLOR_ARGB8 = 0x1c
TYPE_INT_COLOR_RGB8 = 0x1d
TYPE_INT_COLOR_ARGB4 = 0x1e
TYPE_INT_COLOR_RGB4 = 0x1f
TYPE_NULL = 0x00


def u16(b, o): return struct.unpack_from('<H', b, o)[0]
def u32(b, o): return struct.unpack_from('<I', b, o)[0]


def _utf8_len(b, o):
    x = b[o]; o += 1
    if x & 0x80:
        x = ((x & 0x7F) << 8) | b[o]; o += 1
    return x, o


def encode_len(n):
    if n < 0x80:
        return bytes([n])
    return bytes([(n >> 8) & 0x7F | 0x80, n & 0xFF])


def utf16_len(s):
    return len(s.encode('utf-16-le')) // 2


def build_string_pool(strings):
    n = len(strings)
    data_parts = []
    for s in strings:
        b = s.encode('utf-8')
        data_parts.append(encode_len(utf16_len(s)) + encode_len(len(b)) + b + b'\x00')
    data = b''.join(data_parts)
    header_size = 28
    strings_start = header_size + 4 * n
    offs = []
    pos = 0
    for s in strings:
        offs.append(pos)
        b = s.encode('utf-8')
        pos += len(encode_len(utf16_len(s))) + len(encode_len(len(b))) + len(b) + 1
    offs_bytes = b''.join(struct.pack('<I', o) for o in offs)
    # aapt2 pads the whole pool chunk to a 4-byte multiple so the following
    # map/node chunks stay 4-byte aligned (required by Android's XML parser)
    total = header_size + 4 * n + len(data)
    data += b'\x00' * ((-total) % 4)
    header = struct.pack('<HHI', RES_STRING_POOL_TYPE, header_size,
                         header_size + 4 * n + len(data))
    pool_head = struct.pack('<IIIII', n, 0, UTF8_FLAG, strings_start, 0)
    return header + pool_head + offs_bytes + data


class XmlDoc(object):
    def __init__(self, data=None):
        self.strings = []
        self.resmap = {}       # name -> resource id
        self._resmap_ids = []  # original id list (parallel to original string idx)
        self.nodes = []
        if data is not None:
            self.data = data
            self._parse(data)

    # ---------------- parsing ----------------
    def _parse(self, data):
        off = 8
        end = u32(data, 4)
        while off < end:
            ctype, hsize, csize = struct.unpack_from('<HHI', data, off)
            if ctype == RES_STRING_POOL_TYPE:
                self.strings = self._parse_pool(data, off)
            elif ctype == RES_XML_RESOURCE_MAP_TYPE:
                cnt = (csize - hsize) // 4
                self._resmap_ids = [u32(data, off + hsize + 4 * i) for i in range(cnt)]
            elif ctype in (RES_XML_START_NAMESPACE_TYPE, RES_XML_END_NAMESPACE_TYPE):
                self.nodes.append({'type': ctype, 'line': u32(data, off + 8),
                                   'ns': u32(data, off + 16), 'name': u32(data, off + 20)})
            elif ctype == RES_XML_START_ELEMENT_TYPE:
                attrStart = u16(data, off + 24)
                attrSize = u16(data, off + 26)
                attrCount = u16(data, off + 28)
                attrs = []
                base = off + hsize
                for a in range(attrCount):
                    ao = base + attrStart + a * attrSize
                    attrs.append({
                        'ns': u32(data, ao),
                        'name': u32(data, ao + 4),
                        'raw': u32(data, ao + 8),
                        'size': u16(data, ao + 12),
                        'res0': data[ao + 14],
                        'type': data[ao + 15],
                        'data': u32(data, ao + 16),
                    })
                self.nodes.append({'type': ctype, 'line': u32(data, off + 8),
                                   'ns': u32(data, off + 16), 'name': u32(data, off + 20),
                                   'attrs': attrs,
                                   'idIdx': u16(data, off + 30),
                                   'classIdx': u16(data, off + 32),
                                   'styleIdx': u16(data, off + 34)})
            elif ctype == RES_XML_END_ELEMENT_TYPE:
                self.nodes.append({'type': ctype, 'line': u32(data, off + 8),
                                   'ns': u32(data, off + 16), 'name': u32(data, off + 20)})
            elif ctype == RES_XML_CDATA_TYPE:
                self.nodes.append({'type': ctype, 'line': u32(data, off + 8),
                                   'data': u32(data, off + 16),
                                   'size': u16(data, off + 20),
                                   'type2': data[off + 22],
                                   'data2': u32(data, off + 24)})
            if csize == 0:
                break
            off += csize
        for i, rid in enumerate(self._resmap_ids):
            if i < len(self.strings) and rid != 0:
                self.resmap[self.strings[i]] = rid

    def _parse_pool(self, data, off):
        sc, stc, fl, ss, sts = struct.unpack_from('<IIIII', data, off + 8)
        utf8 = bool(fl & UTF8_FLAG)
        strings = []
        po = off + 28
        offs = [u32(data, po + 4 * i) for i in range(sc)]
        base = off + ss
        for so in offs:
            p = base + so
            if utf8:
                _, p = _utf8_len(data, p)
                ln, p = _utf8_len(data, p)
                strings.append(data[p:p + ln].decode('utf-8', errors='replace'))
            else:
                ln = u16(data, p); p += 2
                strings.append(data[p:p + ln * 2].decode('utf-16-le', errors='replace'))
        return strings

    # ---------------- helpers for editing ----------------
    def s(self, i):
        return self.strings[i] if i < len(self.strings) and i != 0xFFFFFFFF else ''

    def find_attr(self, element, name):
        for a in element['attrs']:
            if self.s(a['name']) == name:
                return a
        return None

    def set_attr(self, element, name, value_type, value_data, raw_str=None, ns_name='android'):
        """Set/replace an attribute. ns_name=None -> no namespace."""
        name_i = self.strings.index(name) if name in self.strings else None
        ns_i = self.strings.index(ns_name) if ns_name and ns_name in self.strings else 0xFFFFFFFF
        for a in element['attrs']:
            if self.s(a['name']) == name:
                a['type'] = value_type
                a['data'] = value_data
                a['raw'] = self.strings.index(raw_str) if raw_str is not None and raw_str in self.strings else 0xFFFFFFFF
                a['ns'] = ns_i
                return a
        # append new attr
        a = {'ns': ns_i, 'name': self.strings.index(name) if name in self.strings else len(self.strings),
             'raw': self.strings.index(raw_str) if raw_str is not None and raw_str in self.strings else 0xFFFFFFFF,
             'size': 8, 'type': value_type, 'data': value_data}
        element['attrs'].append(a)
        return a

    # ---------------- encoding ----------------
    def to_binary(self):
        used = []
        def add(s):
            if s not in used:
                used.append(s)
            return used.index(s)
        # 1) collect strings in node order
        def add_ref(idx):
            if idx != 0xFFFFFFFF and idx < len(self.strings):
                add(self.strings[idx])
        for n in self.nodes:
            if n['type'] in (RES_XML_START_NAMESPACE_TYPE, RES_XML_END_NAMESPACE_TYPE,
                             RES_XML_END_ELEMENT_TYPE):
                add_ref(n['ns']); add_ref(n['name'])
            elif n['type'] == RES_XML_START_ELEMENT_TYPE:
                add_ref(n['ns']); add_ref(n['name'])
                for a in n['attrs']:
                    add_ref(a['ns']); add_ref(a['name'])
                    add_ref(a['raw'])
            elif n['type'] == RES_XML_CDATA_TYPE:
                add_ref(n['data'])
        # 2) resource map by name (indexed by new string index)
        max_idx = 0
        name_ids = {}
        for n in self.nodes:
            if n['type'] == RES_XML_START_ELEMENT_TYPE:
                for a in n['attrs']:
                    nm = self.s(a['name'])
                    if nm in self.resmap:
                        name_ids[nm] = self.resmap[nm]
        for nm in name_ids:
            idx = used.index(nm)
            max_idx = max(max_idx, idx)
        # also keep the original trailing length if it was longer
        map_len = max(len(self._resmap_ids), max_idx + 1)
        resmap_arr = [0] * map_len
        for nm, rid in name_ids.items():
            resmap_arr[used.index(nm)] = rid
        pool = build_string_pool(used)
        # 3) nodes
        body = bytearray()
        for n in self.nodes:
            t = n['type']
            if t in (RES_XML_START_NAMESPACE_TYPE, RES_XML_END_NAMESPACE_TYPE):
                body += struct.pack('<HHIIII', t, 16, 24, n['line'], 0xFFFFFFFF,
                                    used.index(self.s(n['ns'])) if self.s(n['ns']) in used else 0xFFFFFFFF)
                body += struct.pack('<I', used.index(self.s(n['name'])) if self.s(n['name']) in used else 0xFFFFFFFF)
            elif t == RES_XML_END_ELEMENT_TYPE:
                body += struct.pack('<HHIIII', t, 16, 24, n['line'], 0xFFFFFFFF,
                                    used.index(self.s(n['ns'])) if self.s(n['ns']) in used else 0xFFFFFFFF)
                body += struct.pack('<I', used.index(self.s(n['name'])) if self.s(n['name']) in used else 0xFFFFFFFF)
            elif t == RES_XML_START_ELEMENT_TYPE:
                attrCount = len(n['attrs'])
                sz = 16 + 20 + 20 * attrCount
                body += struct.pack('<HHIIII', t, 16, sz, n['line'], 0xFFFFFFFF,
                                    used.index(self.s(n['ns'])) if self.s(n['ns']) in used else 0xFFFFFFFF)
                body += struct.pack('<I', used.index(self.s(n['name'])) if self.s(n['name']) in used else 0xFFFFFFFF)
                body += struct.pack('<HHHHHH', 20, 20, attrCount, n['idIdx'], n['classIdx'], n['styleIdx'])
                for a in n['attrs']:
                    ns_i = used.index(self.s(a['ns'])) if a['ns'] < len(self.strings) and self.s(a['ns']) in used else 0xFFFFFFFF
                    nm_i = used.index(self.s(a['name'])) if self.s(a['name']) in used else 0xFFFFFFFF
                    raw_i = used.index(self.strings[a['raw']]) if a['raw'] < len(self.strings) else 0xFFFFFFFF
                    body += struct.pack('<III', ns_i, nm_i, raw_i)
                    body += struct.pack('<HBB', a['size'], a.get('res0', 0), a['type'])
                    body += struct.pack('<I', a['data'])
            elif t == RES_XML_CDATA_TYPE:
                sz = 16 + 4 + 8
                body += struct.pack('<HHIIII', t, 16, sz, n['line'], 0xFFFFFFFF,
                                    used.index(self.strings[n['data']]) if n['data'] < len(self.strings) else 0xFFFFFFFF)
                body += struct.pack('<HBB', n['size'], 0, n['type2'])
                body += struct.pack('<I', n['data2'])
        total = 8 + len(pool) + 8 + 4 * map_len + len(body)
        out = bytearray()
        out += struct.pack('<HHI', 0x0003, 8, total)
        out += pool
        out += struct.pack('<HHI', RES_XML_RESOURCE_MAP_TYPE, 8, 8 + 4 * map_len)
        for v in resmap_arr:
            out += struct.pack('<I', v)
        out += body
        return bytes(out)
