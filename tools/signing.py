# -*- coding: utf-8 -*-
"""Pure-Python APK signing + zip assembly (offline, no external deps).

- v1 (JAR) signature: MANIFEST.MF / CERT.SF / PKCS#7 (SHA1withRSA, matching the
  scheme used by the original APK so old devices accept it)
- v2 (APK Signature Scheme v2): content digest SHA-256 + RSA-PKCS1v1.5 signature
- surgical zip builder: byte-exact for unchanged entries (uses the original
  local headers / deflate streams), 4-byte alignment for stored entries
"""
import base64
import hashlib
import os
import random
import struct
import zlib

MAGIC = b'APK Sig Block 42'
V2_ID = 0x7109871a
ALG_RSA_PKCS1_SHA256 = 0x0101
DIGEST_SHA256 = 1
CHUNK = 1 << 20


# ------------------------------------------------------------------ RSA
def is_probable_prime(n, rounds=40):
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = random.randrange(2, n - 2)
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def gen_prime(bits):
    while True:
        n = random.getrandbits(bits) | (1 << (bits - 1)) | 1
        if is_probable_prime(n):
            return n


def gen_rsa(bits=2048, e=65537):
    while True:
        p = gen_prime(bits // 2)
        q = gen_prime(bits // 2)
        if p == q:
            continue
        phi = (p - 1) * (q - 1)
        if phi % e == 0:
            continue
        n = p * q
        d = pow(e, -1, phi)
        if pow(2, e * d, n) == 2:
            return n, e, d


# ------------------------------------------------------------------ DER
def der_len(n):
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    return bytes([0x80 | len(b)]) + b


def der(tag, content):
    return bytes([tag]) + der_len(len(content)) + content


def der_int(n):
    b = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    if b[0] & 0x80:
        b = b'\x00' + b
    return der(0x02, b)


def der_oid(*arcs):
    body = bytes([arcs[0] * 40 + arcs[1]])
    for a in arcs[2:]:
        if a < 0x80:
            body += bytes([a])
        else:
            parts = []
            while a:
                parts.append(a & 0x7F)
                a >>= 7
            for i in range(len(parts) - 1, 0, -1):
                parts[i] |= 0x80
            body += bytes(parts[::-1])
    return der(0x06, body)


def der_seq(*items):
    return der(0x30, b''.join(items))


def der_set(*items):
    return der(0x31, b''.join(items))


def der_octet(data):
    return der(0x04, data)


def der_null():
    return der(0x05, b'')


def der_utf8(s):
    return der(0x0C, s.encode('utf-8'))


def der_bitstr(data):
    return der(0x03, b'\x00' + data)


def der_utctime(y, m, d, hh, mm, ss):
    return der(0x17, ('%02d%02d%02d%02d%02d%02dZ' % (y % 100, m, d, hh, mm, ss)).encode())


OID_SHA256 = der_oid(2, 16, 840, 1, 101, 3, 4, 2, 1)
OID_SHA1 = der_oid(1, 3, 14, 3, 2, 26)
OID_RSA = der_oid(1, 2, 840, 113549, 1, 1, 1)
OID_SHA256WITHRSA = der_oid(1, 2, 840, 113549, 1, 1, 11)


def rsa_sign(priv, digest_oid, digest):
    di = der_seq(der_seq(digest_oid, der_null()), der_octet(digest))
    em_len = (priv[0].bit_length() + 7) // 8
    em = b'\x00\x01' + b'\xff' * (em_len - len(di) - 3) + b'\x00' + di
    m = int.from_bytes(em, 'big')
    return pow(m, priv[2], priv[0]).to_bytes(em_len, 'big')


# ------------------------------------------------------------------ X.509 + PKCS#7
def build_cert_and_spki(priv, cn='Spectroid Hanhua'):
    n, e, d = priv
    serial = random.getrandbits(128)
    name = der_seq(der_set(der_seq(der_oid(2, 5, 4, 3), der_utf8(cn))))
    spki = der_seq(der_seq(OID_RSA, der_null()),
                   der_bitstr(der_seq(der_int(n), der_int(e))))
    tbs = der_seq(
        der(0xA0, der(0x02, b'\x02')),
        der_int(serial),
        der_seq(OID_SHA256WITHRSA, der_null()),
        name,
        der_seq(der_utctime(2020, 1, 1, 0, 0, 0), der_utctime(2049, 12, 31, 23, 59, 59)),
        name,
        spki,
    )
    sig = rsa_sign(priv, OID_SHA256, hashlib.sha256(tbs).digest())
    cert = der_seq(tbs, der_seq(OID_SHA256WITHRSA, der_null()), der_bitstr(sig))
    return cert, serial, spki


def pkcs7_signed_data(content, cert, serial, priv, cn='Spectroid Hanhua'):
    # v1 JAR signature uses SHA1withRSA (same as the original APK)
    digest = hashlib.sha1(content).digest()
    sig = rsa_sign(priv, OID_SHA1, digest)
    name = der_seq(der_set(der_seq(der_oid(2, 5, 4, 3), der_utf8(cn))))
    signer_info = der_seq(
        der_int(1),
        der_seq(name, der_int(serial)),
        der_seq(OID_SHA1, der_null()),
        der_seq(OID_RSA, der_null()),
        der_octet(sig),
    )
    content_info = der_seq(der_oid(1, 2, 840, 113549, 1, 7, 1), der(0xA0, der_octet(content)))
    signed_data = der_seq(
        der_int(1),
        der_set(der_seq(OID_SHA1, der_null())),
        content_info,
        der(0xA0, cert),
        der_set(signer_info),
    )
    return der_seq(der_oid(1, 2, 840, 113549, 1, 7, 2), der(0xA0, signed_data))


# ------------------------------------------------------------------ v1 manifest
def b64(d):
    return base64.b64encode(d).decode('ascii')


def build_manifest(entries):
    out = [b'Manifest-Version: 1.0\r\n', b'Created-By: Spectroid-Hanhua\r\n', b'\r\n']
    for name, raw in entries:
        out.append(b'Name: ' + name.encode('ascii') + b'\r\n')
        out.append(b'SHA1-Digest: ' + b64(hashlib.sha1(raw).digest()).encode() + b'\r\n\r\n')
    return b''.join(out)


def build_sf(manifest_bytes, entries):
    out = [b'Signature-Version: 1.0\r\n', b'Created-By: Spectroid-Hanhua\r\n',
           b'SHA1-Digest-Manifest: ' + b64(hashlib.sha1(manifest_bytes).digest()).encode() + b'\r\n\r\n']
    for name, _ in entries:
        marker = b'Name: ' + name.encode('ascii') + b'\r\n'
        idx = manifest_bytes.find(marker)
        end = manifest_bytes.find(b'\r\n\r\n', idx)
        end = len(manifest_bytes) if end < 0 else end + 4
        section = manifest_bytes[idx:end]
        out.append(b'Name: ' + name.encode('ascii') + b'\r\n')
        out.append(b'SHA1-Digest: ' + b64(hashlib.sha1(section).digest()).encode() + b'\r\n\r\n')
    return b''.join(out)


# ------------------------------------------------------------------ v2 block
def chunked_sha256(*sections):
    md = hashlib.sha256()
    for sec in sections:
        for i in range(0, len(sec), CHUNK):
            chunk = sec[i:i + CHUNK]
            md.update(struct.pack('<I', len(chunk)))
            md.update(chunk)
    return md.digest()


def lenpref(b):
    return struct.pack('<I', len(b)) + b


def build_v2_block(entries_bytes, cd_bytes, eocd_template, block_offset, priv, cert, spki):
    dummy = b'\x00' * 32
    digests_d = struct.pack('<I', DIGEST_SHA256) + lenpref(dummy)
    certs_d = lenpref(cert)
    sd_d = lenpref(digests_d) + lenpref(certs_d) + lenpref(b'')
    sig_d = rsa_sign(priv, OID_SHA256, hashlib.sha256(sd_d).digest())
    signatures_d = struct.pack('<I', ALG_RSA_PKCS1_SHA256) + lenpref(sig_d)
    signer_d = lenpref(sd_d) + lenpref(signatures_d) + lenpref(spki)
    value_d = lenpref(signer_d)
    pair_d = struct.pack('<II', V2_ID, len(value_d)) + value_d
    block_size = 8 + 16 + len(pair_d)
    block_end = block_offset + 8 + block_size
    eocd = bytearray(eocd_template)
    struct.pack_into('<I', eocd, 16, block_end)
    content_digest = chunked_sha256(entries_bytes, cd_bytes, bytes(eocd))
    digests = struct.pack('<I', DIGEST_SHA256) + lenpref(content_digest)
    signed_data = lenpref(digests) + lenpref(certs_d) + lenpref(b'')
    sig = rsa_sign(priv, OID_SHA256, hashlib.sha256(signed_data).digest())
    signatures = struct.pack('<I', ALG_RSA_PKCS1_SHA256) + lenpref(sig)
    signer = lenpref(signed_data) + lenpref(signatures) + lenpref(spki)
    value = lenpref(signer)
    pair = struct.pack('<II', V2_ID, len(value)) + value
    block = struct.pack('<Q', block_size) + pair + struct.pack('<Q', block_size) + MAGIC
    assert len(block) == block_size + 8
    return block


# ------------------------------------------------------------------ surgical zip
def read_original_entries(path):
    import zipfile
    raw = open(path, 'rb').read()
    z = zipfile.ZipFile(path)
    entries = []
    for info in z.infolist():
        off = info.header_offset
        ver, flags, method = struct.unpack_from('<HHH', raw, off + 4)
        mt, md = struct.unpack_from('<HH', raw, off + 10)
        crc, csz, usz = struct.unpack_from('<III', raw, off + 14)
        nl, el = struct.unpack_from('<HH', raw, off + 26)
        lh = raw[off:off + 30 + nl + el]
        data = raw[off + 30 + nl + el:off + 30 + nl + el + csz]
        entries.append({
            'name': info.filename, 'lh': lh, 'data': data, 'method': method,
            'mt': mt, 'md': md, 'crc': crc, 'csz': csz, 'usz': usz, 'nl': nl, 'el': el,
        })
    return entries


def assemble(original_apk, replacements, new_files, priv, cert, serial, spki, out_path):
    """replacements: {name: (method, data)}; new_files: [(name, data)] (stored).
    Signature files are appended at the end; unchanged entries are byte-exact."""
    import zipfile
    zin = zipfile.ZipFile(original_apk)
    entries = read_original_entries(original_apk)
    SKIP = {'META-INF/CERT.RSA', 'META-INF/CERT.SF', 'META-INF/MANIFEST.MF'}

    body = bytearray()
    cdir = []
    for e in entries:
        name = e['name']
        if name in SKIP:
            continue
        if name in replacements:
            method, data = replacements[name]
            crc = zlib.crc32(data) & 0xFFFFFFFF
            if method == 0:
                comp = data
            else:
                co = zlib.compressobj(9, zlib.DEFLATED, -15)
                comp = co.compress(data) + co.flush()
            lh = bytearray(e['lh'])
            struct.pack_into('<H', lh, 8, method)
            struct.pack_into('<H', lh, 10, e['mt'])
            struct.pack_into('<H', lh, 12, e['md'])
            struct.pack_into('<I', lh, 14, crc)
            struct.pack_into('<I', lh, 18, len(comp))
            struct.pack_into('<I', lh, 22, len(data))
            usz = len(data)
            nl = e['nl']
            if method == 0:
                need = (4 - ((len(body) + 30 + nl) % 4)) % 4
                lh = lh[:30 + nl]
                struct.pack_into('<H', lh, 28, need)
                extra = b'\x00' * need
            else:
                extra = b''
        else:
            lh = e['lh']
            method = e['method']
            comp = e['data']
            crc = e['crc']
            usz = e['usz']
            nl = e['nl']
            if method == 0:
                need = (4 - ((len(body) + 30 + nl) % 4)) % 4
                if need != e['el']:
                    lh = bytearray(lh[:30 + nl])
                    struct.pack_into('<H', lh, 28, need)
                    extra = b'\x00' * need
                else:
                    extra = b''
            else:
                extra = b''
        lho = len(body)
        body += lh
        body += extra
        body += comp
        cdir.append((name, method, e['mt'], e['md'], crc, len(comp), usz, lho))
        if name == 'resources.arsc':
            for nf, data in new_files:
                crc = zlib.crc32(data) & 0xFFFFFFFF
                nl = len(nf.encode())
                need = (4 - ((len(body) + 30 + nl) % 4)) % 4
                extra = b'\x00' * need
                lh = struct.pack('<IHHHHHIIIHH', 0x04034b50, 0, 0, 0, 0x0821, 0x0821,
                                 crc, len(data), len(data), nl, need)
                lho = len(body)
                body += lh + nf.encode() + extra + data
                cdir.append((nf, 0, 0x0821, 0x0821, crc, len(data), len(data), lho))
    entries_bytes = bytes(body)

    manifest_entries = []
    for item in cdir:
        n = item[0]
        if not n.startswith('META-INF/'):
            if n in replacements:
                manifest_entries.append((n, replacements[n][1]))
            elif n in dict(new_files):
                manifest_entries.append((n, dict(new_files)[n]))
            else:
                manifest_entries.append((n, zin.read(n)))
    manifest = build_manifest(manifest_entries)
    sf = build_sf(manifest, manifest_entries)
    cert_rsa = pkcs7_signed_data(sf, cert, serial, priv)

    body2 = bytearray(entries_bytes)
    cdir2 = list(cdir)
    for n, (method, data) in {'META-INF/MANIFEST.MF': (8, manifest),
                              'META-INF/CERT.SF': (8, sf),
                              'META-INF/CERT.RSA': (8, cert_rsa)}.items():
        crc = zlib.crc32(data) & 0xFFFFFFFF
        co = zlib.compressobj(9, zlib.DEFLATED, -15)
        comp = co.compress(data) + co.flush()
        nl = len(n.encode())
        lh = struct.pack('<IHHHHHIIIHH', 0x04034b50, 0, 0, 8, 0x0821, 0x0821,
                         crc, len(comp), len(data), nl, 0)
        lho = len(body2)
        body2 += lh + n.encode() + comp
        cdir2.append((n, 8, 0x0821, 0x0821, crc, len(comp), len(data), lho))
    entries_bytes = bytes(body2)
    cdir = cdir2

    cd = b''
    for name, method, mt, md, crc, csz, usz, off in cdir:
        nb = name.encode('utf-8')
        cd += struct.pack('<IHHHHHHIIIHHHHHII', 0x02014b50, 768, 0, 0, method, mt, md,
                          crc, csz, usz, len(nb), 0, 0, 0, 0, 0x81b60000, off) + nb
    eocd_tpl = struct.pack('<IHHHHIIH', 0x06054b50, 0, 0, len(cdir), len(cdir), len(cd), 0, 0)
    block_offset = len(entries_bytes)
    v2block = build_v2_block(entries_bytes, cd, eocd_tpl, block_offset, priv, cert, spki)
    block_end = block_offset + len(v2block)
    eocd = bytearray(eocd_tpl)
    struct.pack_into('<I', eocd, 16, block_end)
    struct.pack_into('<I', eocd, 12, len(cd))
    apk = entries_bytes + v2block + cd + bytes(eocd)
    open(out_path, 'wb').write(apk)
    return len(apk)


def load_priv(path):
    pem = open(path, 'rb').read()
    b64part = b''.join(pem.split(b'\n')[1:-1])
    der_bytes = base64.b64decode(b64part)

    def parse_len(b, i):
        l = b[i]; i += 1
        if l & 0x80:
            n = l & 0x7F
            l = int.from_bytes(b[i:i + n], 'big')
            i += n
        return l, i

    def parse_int(b, i):
        assert b[i] == 0x02
        l, i = parse_len(b, i + 1)
        v = int.from_bytes(b[i:i + l], 'big')
        return v, i + l

    i = 0
    assert der_bytes[i] == 0x30
    l, i = parse_len(der_bytes, i + 1)
    end = i + l
    vals = []
    while i < end:
        v, i = parse_int(der_bytes, i)
        vals.append(v)
    return (vals[1], vals[2], vals[3])


def save_priv(path, priv):
    n, e, d = priv
    key_seq = der_seq(der_int(0), der_int(n), der_int(e), der_int(d))
    b64s = base64.b64encode(key_seq).decode()
    pem = '-----BEGIN RSA PRIVATE KEY-----\n%s\n-----END RSA PRIVATE KEY-----\n' % (
        '\n'.join(b64s[i:i + 64] for i in range(0, len(b64s), 64)))
    with open(path, 'w') as f:
        f.write(pem)
