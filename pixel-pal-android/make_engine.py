# -*- coding: utf-8 -*-
"""从桌面版 main.py 提取「像素引擎 + 养成逻辑」生成 pet_engine.py。

用法：python make_engine.py
每次桌面版更新了绘制/数值逻辑后，重新运行一次即可同步到安卓版。
"""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.join(HERE, '..', 'pixel-pal-desktop', 'main.py')
OUT = os.path.join(HERE, 'pet_engine.py')

src = io.open(DESKTOP, 'r', encoding='utf-8').read().splitlines()

# 1) 取引擎范围：文件开头 -> 「界面工具」分区标记之前
end = None
for i, l in enumerate(src):
    if l.startswith('#  界面工具'):
        # 往上找到分区分隔线（=#.... 的上一行）
        end = i - 1
        break
assert end, '未找到引擎结束标记'
eng = src[:end]

# 2) 去掉桌面专属内容
out = []
skip_dpi = False
for l in eng:
    if l.startswith('# ---------------- DPI 感知'):
        skip_dpi = True
        out.append('# 安卓版不需要 Windows DPI 感知')
        out.append('DPI = 1.0')
        continue
    if skip_dpi:
        if l.startswith('def u('):
            skip_dpi = False      # u() 继续保留
        else:
            continue
    if l.strip() in ('import tkinter as tk',
                     'import tkinter.font as tkfont',
                     'import ctypes',
                     'import subprocess'):
        continue
    out.append(l)

# 3) 头部说明替换
header = '''# -*- coding: utf-8 -*-
"""
像素宠物 · Pixel Pal Android —— 像素引擎 + 养成逻辑层
本文件由 make_engine.py 从桌面版 main.py 自动提取生成，请勿手工修改；
桌面版更新后重新运行 make_engine.py 即可同步。
"""
'''
# 跳过原文件头（docstring + imports 注释），从 import datetime 开始
start = None
for i, l in enumerate(out):
    if l.startswith('import datetime'):
        start = i
        break
assert start is not None
body = '\n'.join(out[start:])

io.open(OUT, 'w', encoding='utf-8').write(
    header + body + '''

def hex_rgb(h):
    """'#rrggbb' -> (r, g, b)"""
    h = h.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
''')
print('pet_engine.py written:', len(body.splitlines()), 'lines')
