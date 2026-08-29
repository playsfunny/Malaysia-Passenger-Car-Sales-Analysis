#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 launches_en.html 与 launches.html（ZH 源）的镜像质量。

用法：python check_en_page.py [ZH路径] [EN路径]
默认：脚本同目录 launches.html / launches_en.html

检查项：
  1) EN 存在且体积合理（>= ZH 的 70%）
  2) 正文残留中文（排除 <script>/<style> 内的代码与注释）<= 阈值
  3) 结构对齐：h2/h3 标签数之比 >= 95%（语言无关的硬指标）
  4) 标题填充率：EN 非空标题占比 >= 99%
  5) 语言切换器完整性：中文按钮保留中文、class="on" 落在 /launches_en 链接上

⚠️ 不要用「去重后的标题文本数」做覆盖率指标：英文标题天然比中文长，
   按长度过滤会不成比例地砍掉 EN 条目（实测会把 100% 完整误报成 56.7%）。
   同理，不同语言的去重标题数本就不相等，比值没有意义。一律用结构计数。

退出码 0 = 通过；1 = 未通过（CI 会失败，可重跑 workflow 断点续传）。
本文件入库公开，不含任何密钥或个人路径。
"""
import os, re, sys

BASE = os.path.dirname(os.path.abspath(__file__))
ZH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "launches.html")
EN = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE, "launches_en.html")

ZH_LEFT_MAX = 50          # 正文（排除脚本/样式）允许残留的中文字符数
STRUCT_MIN = 0.95         # EN/ZH 的 h2+h3 标签数之比下限
FILL_MIN = 0.99           # EN 非空标题占比下限
SIZE_MIN_RATIO = 0.70     # EN 体积 / ZH 体积 下限

ZH_RE = re.compile(r"[\u4e00-\u9fff]")
BLOCK_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
HEAD_OPEN_RE = re.compile(r"<h([23])\b", re.I)
HEAD_RE = re.compile(r"<h([23])[^>]*>(.*?)</h\1>", re.S | re.I)


def strip_code(h):
    return BLOCK_RE.sub(" ", h)


def head_tags(h):
    """结构计数：h2/h3 标签总数（不去重、不过滤长度，语言中立）。"""
    return len(HEAD_OPEN_RE.findall(strip_code(h)))


def head_texts(h):
    body = strip_code(h)
    return [re.sub(r"<[^>]+>", "", m[1]).strip() for m in HEAD_RE.findall(body)]


def check_nav(h):
    """返回 (是否命中, 错误列表)。EN 页语言切换器必须：中文按钮仍是中文、on 在 EN 链接。"""
    i = h.find('lang-switch"><a')
    if i < 0:
        return False, ["未找到 .lang-switch 语言切换器"]
    seg = h[i:i + 400]
    errs = []
    if "中文" not in seg:
        errs.append("语言切换器的「中文」按钮被翻译掉了（用户将无法切回中文）")
    on_links = re.findall(r'<a[^>]*class="[^"]*\bon\b[^"]*"[^>]*href="([^"]*)"', seg)
    on_links += re.findall(r'<a[^>]*href="([^"]*)"[^>]*class="[^"]*\bon\b[^"]*"', seg)
    if not on_links:
        errs.append("语言切换器没有任何链接带 class=\"on\"")
    elif "launches_en" not in on_links[0]:
        errs.append(f'语言切换器的 class="on" 落在 {on_links[0]}，应为 /launches_en')
    return True, errs


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
    zh_n, en_n = head_tags(zh_html), head_tags(en_html)
    struct = (en_n / zh_n) if zh_n else 0.0
    en_txts = head_texts(en_html)
    fill = (sum(1 for t in en_txts if t) / len(en_txts)) if en_txts else 0.0
    ratio = (len(en_html.encode()) / len(zh_html.encode())) if zh_html else 0.0
    nav_hit, nav_errs = check_nav(en_html)

    print(f"残留中文字数（排除 script/style）: {zh_left}  (阈值 <= {ZH_LEFT_MAX})")
    print(f"结构对齐 h2+h3: EN {en_n} / ZH {zh_n} = {struct*100:.1f}%  (阈值 >= {STRUCT_MIN*100:.0f}%)")
    print(f"标题填充率: {fill*100:.1f}%  (阈值 >= {FILL_MIN*100:.0f}%)")
    print(f"体积: EN {len(en_html.encode())} / ZH {len(zh_html.encode())} = {ratio*100:.1f}%  (阈值 >= {SIZE_MIN_RATIO*100:.0f}%)")
    print(f"语言切换器: {'已校验' if nav_hit else '未命中'}")

    errs = []
    if zh_left > ZH_LEFT_MAX:
        errs.append(f"残留中文 {zh_left} 超过阈值 {ZH_LEFT_MAX}")
    if struct < STRUCT_MIN:
        errs.append(f"结构对齐 {struct*100:.1f}% 低于 {STRUCT_MIN*100:.0f}%（可重跑 workflow 断点续传）")
    if fill < FILL_MIN:
        errs.append(f"标题填充率 {fill*100:.1f}% 低于 {FILL_MIN*100:.0f}%")
    if ratio < SIZE_MIN_RATIO:
        errs.append(f"体积比 {ratio*100:.1f}% 低于 {SIZE_MIN_RATIO*100:.0f}%")
    errs += nav_errs

    if errs:
        print("\n❌ 未通过:")
        for e in errs:
            print("  -", e)
        return 1
    print("\n✅ 校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
