#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 launches_en.html 与 launches.html（ZH 源）的镜像质量。

用法：python check_en_page.py [ZH路径] [EN路径]
默认：脚本同目录 launches.html / launches_en.html

检查项：
  1) EN 存在且体积合理（>= ZH 的 70%）
  2) 正文残留中文（排除 <script>/<style> 内的代码与注释）<= 阈值
  3) 车型章节（h2/h3 去重）覆盖率 >= 95%（相对 ZH）——核心质量门

退出码 0 = 通过；1 = 未通过（CI 会失败，可重跑 workflow 继续断点续传）。
本文件入库公开，不含任何密钥或个人路径。
"""
import os, re, sys

BASE = os.path.dirname(os.path.abspath(__file__))
ZH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "launches.html")
EN = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE, "launches_en.html")

ZH_LEFT_MAX = 50          # 正文（排除脚本/样式）允许残留的中文字符数
COVER_MIN = 0.95          # 车型章节覆盖率下限
SIZE_MIN_RATIO = 0.70     # EN 体积 / ZH 体积 下限

ZH_RE = re.compile(r"[\u4e00-\u9fff]")
BLOCK_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)


def strip_code(h):
    return BLOCK_RE.sub(" ", h)


def sections(h):
    body = strip_code(h)
    out = set()
    for m in re.findall(r"<h([23])[^>]*>(.*?)</h\1>", body, re.S):
        s = re.sub(r"<[^>]+>", "", m[1]).strip()
        if s and len(s) < 60:
            out.add(s)
    return out


def main():
    if not os.path.exists(EN):
        print("FAIL: 未找到", EN)
        return 1
    if not os.path.exists(ZH):
        print("FAIL: 未找到 ZH 源", ZH)
        return 1
    zh_html = open(ZH, encoding="utf-8").read()
    en_html = open(EN, encoding="utf-8").read()

    zh_left = len(ZH_RE.findall(strip_code(en_html)))
    zh_secs, en_secs = sections(zh_html), sections(en_html)
    cover = (len(en_secs) / len(zh_secs)) if zh_secs else 0.0
    ratio = (len(en_html.encode()) / len(zh_html.encode())) if zh_html else 0.0

    print(f"残留中文字数（排除 script/style）: {zh_left}  (阈值 <= {ZH_LEFT_MAX})")
    print(f"车型章节: EN {len(en_secs)} / ZH {len(zh_secs)} = {cover*100:.1f}%  (阈值 >= {COVER_MIN*100:.0f}%)")
    print(f"体积: EN {len(en_html.encode())} / ZH {len(zh_html.encode())} = {ratio*100:.1f}%  (阈值 >= {SIZE_MIN_RATIO*100:.0f}%)")

    errs = []
    if zh_left > ZH_LEFT_MAX:
        errs.append(f"残留中文 {zh_left} 超过阈值 {ZH_LEFT_MAX}")
    if cover < COVER_MIN:
        errs.append(f"章节覆盖 {cover*100:.1f}% 低于 {COVER_MIN*100:.0f}%（可重跑 workflow 断点续传）")
    if ratio < SIZE_MIN_RATIO:
        errs.append(f"体积比 {ratio*100:.1f}% 低于 {SIZE_MIN_RATIO*100:.0f}%")

    if errs:
        print("\n❌ 未通过:")
        for e in errs:
            print("  -", e)
        return 1
    print("\n✅ 校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
