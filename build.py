#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Spectroid 汉化 + 玻璃 UI 一键构建工具（纯 Python，无外部依赖，可离线运行）

用法:
    python build.py 原版.apk [输出.apk]

流程:
    1. 汉化: 将 translations.json 的中文写入 resources.arsc 的字符串池并重定向条目
    2. 美化: 深色玻璃窗口底色、霓虹频谱配色、玻璃设置项、新启动图标
    3. 重打包: 外科手术式重建 zip(未改动文件逐字节保留) + v1/v2 签名

注意:
    - 需要提供你自己合法获取的原版 Spectroid APK(Google Play / apkmirror)
    - 生成结果需要自签名后安装(如 MT 管理器), 与原版签名不同, 无法覆盖升级
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'tools'))

from arsc_parser import ArscFile, TYPE_STRING          # noqa: E402
from arsc_edit import ArscEditor                        # noqa: E402
from binxml import XmlDoc                               # noqa: E402
import signing                                         # noqa: E402

# ---------------------------------------------------------------- 汉化
TRANSLATIONS = json.load(open(os.path.join(HERE, 'translations.json'), encoding='utf-8'))


def translate_arsc(arsc_bytes):
    """把中文写入全局字符串池, 并将 string 类型(default 配置)对应条目重定向到中文。"""
    ed = ArscEditor(arsc_bytes)
    gpool = ed.global_pool()
    keypool = ed.key_pool()
    # 1) 追加中文(去重)
    zh_index = {}
    for zh in TRANSLATIONS.values():
        if zh not in gpool.strings and zh not in zh_index:
            zh_index[zh] = len(gpool.strings)
            gpool.strings.append(zh)
        elif zh in gpool.strings:
            zh_index[zh] = gpool.strings.index(zh)
    # 2) 重定向 default 配置的 string 条目
    for kind, off, obj in ed.arsc.package_children[0]:
        if kind == 'type' and obj.id == 9 and obj.config_str() == 'default':
            for e in obj.entries:
                if e is None or e.complex or e.value.data_type != TYPE_STRING:
                    continue
                kn = keypool.strings[e.key] if e.key < len(keypool.strings) else None
                if kn in TRANSLATIONS:
                    e.value.data = zh_index[TRANSLATIONS[kn]]
    return ed.serialize()


# ---------------------------------------------------------------- 玻璃 UI
WINDOW_BG_COLOR = 0xFF0E141E   # 深蓝黑
ICON_BG_COLOR = 0xFF0D1526     # 启动图标背景

# 频谱配色 (自定义属性, 资源 ID 对应 type-2 条目索引)
SPECTRUM_COLORS = {
    'spectrumColor': 0xFF33D9FF,        # 频谱(电光青)
    'peakSpectrumColor': 0xFF9D8CFF,    # 峰值保持(紫)
    'gridMajorColor': 0x1EFFFFFF,
    'gridMinorColor': 0x0DFFFFFF,
    'markerColor': 0xFFFFC94D,          # 标记(琥珀)
    'markerLabelTextColor': 0xD9FFFFFF,
    'markerStubTextColor': 0x59FFFFFF,
    'peakMarkerColor': 0xFF9D8CFF,
    'peakMarkerLabelTextColor': 0xD9FFFFFF,
    'peakMarkerStubTextColor': 0x59FFFFFF,
    'stubTextColor': 0x59FFFFFF,
}
ATTR_IDS = {
    'gridMajorColor': 0x7f020001, 'gridMinorColor': 0x7f020002, 'markerColor': 0x7f020003,
    'markerLabelTextColor': 0x7f020004, 'markerStubTextColor': 0x7f020006,
    'peakMarkerColor': 0x7f02000a, 'peakMarkerLabelTextColor': 0x7f02000b,
    'peakMarkerStubTextColor': 0x7f02000d, 'peakSpectrumColor': 0x7f02000f,
    'spectrumColor': 0x7f020010, 'stubTextColor': 0x7f020011,
}
APP_URI = 'http://schemas.android.com/apk/res-auto'
APP_NS = 'app'
ATTR_WINDOW_BACKGROUND = 0x01010054


def glass_arsc(translated):
    ed = ArscEditor(translated)
    ed.retarget_style_bag('Theme.Spectroid', ATTR_WINDOW_BACKGROUND, 0x1c, WINDOW_BG_COLOR)
    ed.retarget_style_bag('Theme.Spectroid.Spectrum', ATTR_WINDOW_BACKGROUND, 0x1c, WINDOW_BG_COLOR)
    for kind, off, obj in ed.arsc.package_children[0]:
        if kind == 'type' and obj.id == 3:
            for e in obj.entries:
                if e is not None and not e.complex and ed.key_pool().strings[e.key] == 'ic_launcher_background':
                    e.value.data_type = 0x1c
                    e.value.data = ICON_BG_COLOR
    return ed.serialize()


def glass_o7_xml(orig_bytes):
    """主布局: 给 SpectrumView 加霓虹配色自定义属性。"""
    d = XmlDoc(orig_bytes)
    if APP_URI not in d.strings:
        d.strings.append(APP_URI)
    if APP_NS not in d.strings:
        d.strings.append(APP_NS)
    uri_i = d.strings.index(APP_URI)
    d.nodes.insert(1, {'type': 0x0100, 'line': 1, 'ns': uri_i, 'name': d.strings.index(APP_NS)})
    view = None
    for n in d.nodes:
        if n['type'] == 0x0102 and d.s(n['name']) == 'org.intoorbit.spectrum.views.SpectrumView':
            view = n
            break
    if view is None:
        raise RuntimeError('SpectrumView not found in layout')
    for name, color in SPECTRUM_COLORS.items():
        if name not in d.strings:
            d.strings.append(name)
        d.resmap[name] = ATTR_IDS[name]
        view['attrs'].append({'ns': uri_i, 'name': d.strings.index(name), 'raw': 0xFFFFFFFF,
                              'size': 8, 'type': 0x1c, 'data': color})
    d.nodes.append({'type': 0x0101, 'line': 1, 'ns': uri_i, 'name': d.strings.index(APP_NS)})
    return d.to_binary()


def glass_vx_xml(orig_bytes):
    """SeekBar 偏好行: 半透明玻璃底色。"""
    d = XmlDoc(orig_bytes)
    for s in ('android', 'background'):
        if s not in d.strings:
            d.strings.append(s)
    android_i = d.strings.index('android')
    bg_i = d.strings.index('background')
    for n in d.nodes:
        if n['type'] == 0x0102 and d.s(n['name']) == 'LinearLayout':
            found = False
            for a in n['attrs']:
                if d.s(a['name']) == 'background':
                    a['type'] = 0x1c
                    a['data'] = 0x14FFFFFF
                    found = True
            if not found:
                n['attrs'].append({'ns': android_i, 'name': bg_i, 'raw': 0xFFFFFFFF,
                                   'size': 8, 'type': 0x1c, 'data': 0x14FFFFFF})
    return d.to_binary()


def gen_icons(out_dir):
    """生成 5 个密度的启动图标(深蓝玻璃底 + 青色频谱柱)。"""
    from gen_icons import gen_icon
    os.makedirs(out_dir, exist_ok=True)
    for fname, size in [('u3.png', 48), ('SD.png', 72), ('jy.png', 96),
                        ('D2.png', 144), ('CG.png', 192)]:
        with open(os.path.join(out_dir, fname), 'wb') as f:
            f.write(gen_icon(size))


# ---------------------------------------------------------------- 主流程
def build(original_apk, out_apk):
    import zipfile
    priv = signing.gen_rsa(2048)
    cert, serial, spki = signing.build_cert_and_spki(priv)

    zin = zipfile.ZipFile(original_apk)
    arsc = zin.read('resources.arsc')
    print('[1/5] 汉化资源表...')
    translated = translate_arsc(arsc)
    print('      字符串池: %d -> %d' % (len(ArscFile(arsc).string_pools[0][1].strings),
                                      len(ArscFile(translated).string_pools[0][1].strings)))
    print('[2/5] 玻璃主题...')
    final_arsc = glass_arsc(translated)
    print('[3/5] 生成启动图标...')
    tmp = os.path.join(HERE, '.build_icons')
    gen_icons(tmp)
    print('[4/5] 布局美化...')
    o7 = glass_o7_xml(zin.read('res/O7.xml'))
    vx = glass_vx_xml(zin.read('res/Vx.xml'))

    replacements = {
        'resources.arsc': (0, final_arsc),
        'res/O7.xml': (8, o7),
        'res/Vx.xml': (8, vx),
        'res/u3.png': (0, open(os.path.join(tmp, 'u3.png'), 'rb').read()),
        'res/SD.png': (0, open(os.path.join(tmp, 'SD.png'), 'rb').read()),
        'res/jy.png': (0, open(os.path.join(tmp, 'jy.png'), 'rb').read()),
        'res/D2.png': (0, open(os.path.join(tmp, 'D2.png'), 'rb').read()),
        'res/CG.png': (0, open(os.path.join(tmp, 'CG.png'), 'rb').read()),
    }
    print('[5/5] 重打包 + 签名...')
    size = signing.assemble(original_apk, replacements, [], priv, cert, serial, spki, out_apk)
    shutil.rmtree(tmp, ignore_errors=True)
    print('完成: %s (%d bytes)' % (out_apk, size))
    print()
    print('下一步: 用 MT 管理器对 %s 自签名后安装(需先卸载已装的 Spectroid)' % out_apk)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else 'Spectroid_hanhua_glass.apk'
    build(src, dst)
