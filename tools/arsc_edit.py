# -*- coding: utf-8 -*-
"""resources.arsc full-rebuild editor: add entries to a type, retarget bag/entry values,
append key strings. Serializes a complete valid arsc."""
import struct

from arsc_parser import (ArscFile, StringPool, ResValue, Entry, TypeChunk,
                         TypeSpecChunk, Package,
                         RES_TABLE_TYPE, RES_STRING_POOL_TYPE, RES_TABLE_PACKAGE_TYPE,
                         RES_TABLE_TYPE_SPEC_TYPE, RES_TABLE_TYPE_TYPE,
                         UTF8_FLAG)

TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03
TYPE_INT_COLOR_ARGB8 = 0x1c
TYPE_INT_COLOR_RGB8 = 0x1d
TYPE_NULL = 0x00


def encode_len(n):
    if n < 0x80:
        return bytes([n])
    return bytes([(n >> 8) & 0x7F | 0x80, n & 0xFF])


def utf16_len(s):
    return len(s.encode('utf-16-le')) // 2


def build_pool(strings, utf8=True):
    n = len(strings)
    if utf8:
        data_parts = []
        for s in strings:
            b = s.encode('utf-8')
            data_parts.append(encode_len(utf16_len(s)) + encode_len(len(b)) + b + b'\x00')
        data = b''.join(data_parts)
        flags = UTF8_FLAG
    else:
        data_parts = []
        for s in strings:
            b = s.encode('utf-16-le')
            data_parts.append(struct.pack('<H', len(b) // 2) + b + b'\x00\x00')
        data = b''.join(data_parts)
        flags = 0
    header_size = 28
    strings_start = header_size + 4 * n
    offs = []
    pos = 0
    for s in strings:
        offs.append(pos)
        if utf8:
            b = s.encode('utf-8')
            pos += len(encode_len(utf16_len(s))) + len(encode_len(len(b))) + len(b) + 1
        else:
            b = s.encode('utf-16-le')
            pos += 2 + len(b) + 2
    offs_bytes = b''.join(struct.pack('<I', o) for o in offs)
    # pad the whole chunk so its size is a multiple of 4 (aapt2 convention)
    total = header_size + 4 * n + len(data)
    pad = (-total) % 4
    data += b'\x00' * pad
    header = struct.pack('<HHI', RES_STRING_POOL_TYPE, header_size,
                         header_size + 4 * n + len(data))
    pool_head = struct.pack('<IIIII', n, 0, flags, strings_start, 0)
    return header + pool_head + offs_bytes + data


def ser_value(v):
    if isinstance(v, ResValue):
        return struct.pack('<HBB', 8, 0, v.data_type) + struct.pack('<I', v.data)
    vtype, vdata = v
    return struct.pack('<HBB', 8, 0, vtype) + struct.pack('<I', vdata)


def ser_entry(e, key_idx):
    if not e.complex:
        return struct.pack('<HHIHBB', 8, e.flags, key_idx, 8, 0, e.value.data_type) + struct.pack('<I', e.value.data)
    else:
        out = struct.pack('<HHIII', 16, e.flags, key_idx, e.parent, e.count)
        for name, v in e.map:
            out += struct.pack('<I', name) + ser_value(v)
        return out


def ser_simple_entry(key_idx, vtype, vdata):
    return struct.pack('<HHIHBB', 8, 0, key_idx, 8, 0, vtype) + struct.pack('<I', vdata)


class _SimpleValue(object):
    def __init__(self, vtype, vdata):
        self.data_type = vtype
        self.data = vdata


class _SimpleEntry(object):
    complex = False
    flags = 0

    def __init__(self, key, vtype, vdata):
        self.key = key
        self.value = _SimpleValue(vtype, vdata)


class ArscEditor(object):
    def __init__(self, data):
        self.arsc = ArscFile(data)
        self.data = data

    # ---- model access ----
    def global_pool(self):
        return self.arsc.string_pools[0][1]

    def key_pool(self):
        pools = [obj for kind, off, obj in self.arsc.package_children[0] if kind == 'pool']
        return pools[1]

    def type_pool(self):
        pools = [obj for kind, off, obj in self.arsc.package_children[0] if kind == 'pool']
        return pools[0]

    def specs_and_types(self):
        out = []
        for kind, off, obj in self.arsc.package_children[0]:
            if kind in ('spec', 'type'):
                out.append((kind, obj))
        return out

    def find_style(self, key_name):
        for kind, off, obj in self.arsc.package_children[0]:
            if kind == 'type' and obj.id == 10:
                for e in obj.entries:
                    if e is not None and not e.complex and False:
                        pass
        return None

    # ---- edits ----
    def retarget_style_bag(self, style_key, attr_id, vtype, vdata):
        """In every config of style type, set bag item with key attr_id to a new value.
        Value stored as (vtype, vdata) tuple."""
        count = 0
        for kind, off, obj in self.arsc.package_children[0]:
            if kind == 'type' and obj.id == 10:
                for e in obj.entries:
                    if e is None or not e.complex:
                        continue
                    if self.key_pool().strings[e.key] == style_key:
                        for i, (name, v) in enumerate(e.map):
                            if name == attr_id:
                                e.map[i] = (name, (vtype, vdata))
                                count += 1
                                break
        return count

    def add_string_entries(self, type_id, entries):
        """entries: list of (key_name, str_value). Adds to the type; only the default
        config gets the value; other configs get no-entry (0xFFFFFFFF)."""
        keypool = self.key_pool()
        gpool = self.global_pool()
        key_idx_start = len(keypool.strings)
        str_idx_start = len(gpool.strings)
        new_keys = [k for k, _ in entries]
        new_strs = [v for _, v in entries]
        keypool.strings.extend(new_keys)
        gpool.strings.extend(new_strs)
        # track modifications per type chunk
        for kind, off, obj in self.arsc.package_children[0]:
            if kind == 'spec' and obj.id == type_id:
                obj.entry_count += len(entries)
                obj.flags.extend([0] * len(entries))
            elif kind == 'type' and obj.id == type_id:
                t = obj
                is_default = (t.config_str() == 'default')
                t.entry_count += len(entries)
                for i in range(len(entries)):
                    if is_default:
                        e = _SimpleEntry(key_idx_start + i, TYPE_STRING, str_idx_start + i)
                        t.entries.append(e)
                    else:
                        t.entries.append(None)
                # keep type chunk consistent: entriesStart stays; offsets computed at serialize
        return key_idx_start, str_idx_start

    # ---- serialize ----
    def serialize(self):
        arsc = self.arsc
        data = self.data
        gpool = arsc.string_pools[0][1]
        pkg = arsc.packages[0]
        # 1. global pool (preserve original encoding/flags)
        global_pool_bytes = build_pool(gpool.strings, utf8=bool(gpool.flags & UTF8_FLAG))
        # 2. package
        type_pool = self.type_pool()
        key_pool = self.key_pool()
        type_pool_bytes = build_pool(type_pool.strings, utf8=bool(type_pool.flags & UTF8_FLAG))
        key_pool_bytes = build_pool(key_pool.strings, utf8=bool(key_pool.flags & UTF8_FLAG))
        pkg_header = struct.pack('<HHI', RES_TABLE_PACKAGE_TYPE, 288, 0)  # size patched later
        pkg_header += struct.pack('<I', pkg.id)
        pkg_header += pkg.name.encode('utf-16-le')[:256].ljust(256, b'\x00')
        pkg_header += struct.pack('<IIIII', 288, 0, 288 + len(type_pool_bytes), 0, 0)
        body = bytearray()
        body += type_pool_bytes
        body += key_pool_bytes
        type_offsets = {}  # type_id -> bytes (serialized chunks in original order)
        for kind, off, obj in arsc.package_children[0]:
            if kind == 'spec':
                s = obj
                out = struct.pack('<HHI', RES_TABLE_TYPE_SPEC_TYPE, 16, 16 + 4 * s.entry_count)
                out += struct.pack('<BBH', s.id, 0, 0)
                out += struct.pack('<I', s.entry_count)
                for f in s.flags:
                    out += struct.pack('<I', f)
                body += out
            elif kind == 'type':
                t = obj
                out = self._ser_type_chunk(t)
                body += out
        # patch package chunk size
        pkg_size = len(pkg_header) + len(body)
        pkg_header = pkg_header[:4] + struct.pack('<I', pkg_size) + pkg_header[8:]
        package_bytes = pkg_header + bytes(body)
        # 3. header
        total = 12 + len(global_pool_bytes) + len(package_bytes)
        head = struct.pack('<HHII', RES_TABLE_TYPE, 12, total, 1)
        return head + global_pool_bytes + package_bytes

    def _ser_type_chunk(self, t):
        # entry data
        entry_data = bytearray()
        offsets = []
        for e in t.entries:
            if e is None:
                offsets.append(0xFFFFFFFF)
            else:
                offsets.append(len(entry_data))
                entry_data += ser_entry(e, e.key)
        entries_start = 84 + 4 * t.entry_count  # header(8)+12 fields+config(64) = 84
        csize = entries_start + len(entry_data)
        out = struct.pack('<HHI', RES_TABLE_TYPE_TYPE, 84, csize)
        out += struct.pack('<BBH', t.id, 0, 0)
        out += struct.pack('<I', t.entry_count)
        out += struct.pack('<I', entries_start)
        out += bytes(t.config)
        for o in offsets:
            out += struct.pack('<I', o)
        out += bytes(entry_data)
        return out
