#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 launches_en.html（v2：手动词典 + 规则 + 在线 API 兜底）。

翻译优先级（前面的命中就不会再往后走，越靠前越省钱）：
  缓存 .cache/en_map_v2.json > 回采现有 EN 产物 > LOCAL 词典 > en_b1/en_b2 手动
  > 旧映射 reuse > 规则引擎（术语 + 单位） > 在线 API（DeepL 主 → Google v2 兜底）

在线 API 闸门（TRANSLATE_API，默认 off）：
  off：绝不调用。若仍有未译条目 → 不写产物、导出清单到 .cache/untranslated.json、退出码 2。
  ask：交互式确认（本地用；非交互环境视为拒绝）。
  on ：允许调用。开启方式：TRANSLATE_API=on python make_en_v2.py

密钥：DeepL 存 .translate_key、Google 存 .google_api_key（均 chmod 600，不入库、不回显）；
      CI 走 repo secrets DEEPL_KEY / GOOGLE_API_KEY。
代理：沙箱/本机如需走 127.0.0.1:10808，设 GOOGLE_TRANSLATE_PROXY（仅影响 Google）。
缓存映射存项目内 .cache/（旧 /tmp 位置自动回退并迁移）；支持断点续传。
路径基于脚本目录推导，可用环境变量覆盖：LAUNCHES_SRC / LAUNCHES_DST / DEEPL_KEY_FILE。"""
import re, json, os, sys, time, urllib.parse, urllib.request, urllib.error, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup, NavigableString

# 路径一律基于脚本所在目录推导，不硬编码个人绝对路径（本文件已入库公开）。
# 可用环境变量覆盖：LAUNCHES_SRC（ZH 源文件）、LAUNCHES_DST（EN 输出文件）。
# 默认「ZH 源 = 脚本同目录 launches.html」，保证 EN 与已部署的 ZH 严格镜像。
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("LAUNCHES_SRC") or os.path.join(BASE, "launches.html")
DST = os.environ.get("LAUNCHES_DST") or os.path.join(BASE, "launches_en.html")
# 缓存放项目内 .cache/（原在 /tmp，会被系统清理 → 重跑重复计费 + 断点续传丢失）
CACHE_DIR = os.path.join(BASE, ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)
MAP = os.path.join(CACHE_DIR, "en_map_v2.json")
OLD_MAP = os.path.join(CACHE_DIR, "en_map.json")
# 旧 /tmp 位置回退（若仍存在则复用并就地迁移，省额度）
MAP_TMP = "/tmp/en_map_v2.json"
OLD_MAP_TMP = "/tmp/en_map.json"


def _load_map(path, tmp_fallback):
    """读缓存映射：优先项目内 .cache，回退旧 /tmp 位置并就地迁移。"""
    if os.path.exists(path):
        p = path
    elif os.path.exists(tmp_fallback):
        p = tmp_fallback
    else:
        return {}
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}
    if p == tmp_fallback and d:
        try:
            json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
            print(f"[cache] 迁移旧缓存 {tmp_fallback} -> {path}（{len(d)} 条）")
        except Exception:
            pass
    return d

LOCAL = {
    "大马车讯记录仪": "Malaysia Car News Recorder",
    "车型总数": "Total models",
    "覆盖月份": "Months covered",
    "截至": "As of",
    "阅读全文（中/EN）→": "Read full article (ZH/EN) →",
    "阅读全文 →": "Read full article →",
    "阅读原文 →": "Read original →",
    "阅读原文": "Read original",
    "新车": "New car",
    "全新": "All-new",
    "限量": "Limited",
    "限量版": "Limited edition",
    "纪念版": "Anniversary edition",
    "改款": "Facelift",
    "小改款": "Minor facelift",
    "中期改款": "Mid-life facelift",
    "上市": "Launched",
    "正式上市": "Officially launched",
    "定价": "Priced",
    "官方定价": "Official pricing",
    "预售": "Pre-order",
    "首发": "Debut",
    "登场": "Arrives",
    "开卖": "On sale",
    "顶配": "Top",
    "顶配版": "Top variant",
    "入门": "Entry",
    "入门版": "Entry variant",
    "起价": "Starting price",
    "共": "Total",
    "台": "units",
    "款": "variants",
    "月": "month",
    "七月": "July",
    "八月": "August",
    "九月": "September",
    "六月": "June",
    "五月": "May",
    "四月": "April",
    "三月": "March",
    "二月": "February",
    "一月": "January",
    "单车型深度文章合集": "Single-model deep-dive article collection",
    "文章合集": "Article collection",
    "规格速览": "Key specifications",
    "关键规格": "Key specifications",
    "综合输出": "Combined output",
    "纯电续航": "EV range",
    "续航": "Range",
    "保固": "Warranty",
    "引擎": "Engine",
    "起": "from",
}

MANUAL = {}
for f in ("en_b1.json", "en_b2.json"):
    p = os.path.join(BASE, f)
    if os.path.exists(p):
        MANUAL.update(json.load(open(p, encoding="utf-8")))

TERMS = [
    ("插电式混合动力", "plug-in hybrid"), ("插电混动", "plug-in hybrid"), ("插混", "plug-in hybrid"),
    ("油电混合", "hybrid"), ("油电", "hybrid"), ("轻混", "mild-hybrid"), ("增程", "range-extender"),
    ("纯电", "electric"), ("纯电动", "electric"), ("电动", "electric"), ("柴油", "diesel"),
    ("汽油", "petrol"), ("混动", "hybrid"), ("燃料电池", "fuel-cell"),
    ("高性能", "high-performance"), ("性能", "performance"),
    ("轿跑SUV", "coupe-SUV"), ("轿跑", "coupe"), ("跨界", "crossover"), ("越野", "off-road"),
    ("硬派", "rugged"), ("方盒子", "boxy"), ("旅行车", "wagon"), ("猎装", "shooting-brake"),
    ("轿车", "sedan"), ("掀背", "hatchback"), ("皮卡", "pickup"), ("微面", "van"),
    ("跑车", "sports car"), ("敞篷", "convertible"), ("两厢", "hatchback"),
    ("旗舰", "flagship"), ("豪华", "luxury"), ("入门级", "entry-level"), ("中端", "mid-range"),
    ("高端", "high-end"), ("主流", "mainstream"), ("城市", "urban"), ("家用", "family"),
    ("运动", "sporty"), ("商务", "business"),
    ("大改款", "major update"), ("中期改款", "mid-life facelift"), ("小改款", "minor facelift"),
    ("改款", "facelift"), ("换代", "new generation"), ("首款", "first"), ("第二款", "second model"),
    ("第三代", "third-generation"), ("第二代", "second-generation"), ("年度", "annual"),
    ("联名", "collaboration"), ("设计师", "designer"), ("回归", "returns"), ("升级", "upgrade"),
    ("延寿", "life-extension"), ("更新", "update"), ("登场", "arrives"), ("首发", "debut"),
    ("预售", "pre-order"), ("开卖", "on sale"), ("引进", "introduced"), ("正式", "officially"),
    ("阵容", "lineup"), ("车型", "model"), ("版型", "variant"), ("版", "version"),
    ("独苗", "sole"), ("老将", "veteran"),
    ("架构", "architecture"), ("闪充", "flash-charge"), ("充电", "charging"), ("电机", "motor"),
    ("引擎", "engine"), ("变速箱", "gearbox"), ("四驱", "AWD"), ("前驱", "FWD"), ("后驱", "RWD"),
    ("全时四驱", "full-time AWD"), ("轮圈", "wheels"), ("轮毂", "wheels"), ("中控屏", "central screen"),
    ("大屏", "display"), ("天窗", "sunroof"), ("全景天窗", "panoramic sunroof"), ("座椅", "seats"),
    ("皮质座椅", "leather seats"), ("音响", "audio"), ("扬声器", "speaker"), ("尾门", "tailgate"),
    ("电动尾门", "power tailgate"), ("影像", "view monitor"), ("全景影像", "panoramic view monitor"),
    ("泊车", "parking"), ("辅助驾驶", "driver assistance"), ("互联", "connectivity"),
    ("质保", "warranty"), ("保养", "maintenance"), ("扭矩", "torque"), ("轴距", "wheelbase"),
    ("本地组装", "locally-assembled"), ("国产", "locally-built"), ("原装进口", "fully-imported"),
    ("中国", "China"), ("马来西亚", "Malaysia"), ("日本", "Japan"), ("泰国", "Thailand"),
    ("印尼", "Indonesia"), ("德国", "Germany"), ("英国", "UK"), ("韩国", "Korea"), ("美国", "USA"),
    ("法国", "France"), ("意大利", "Italy"), ("西班牙", "Spain"), ("瑞典", "Sweden"), ("捷克", "Czech"),
    ("系列", "series"), ("配备", "equipped"), ("可选", "optional"), ("标准", "standard"),
    ("全系", "across the range"), ("含", "with"), ("支持", "supports"), ("提供", "offers"),
    ("搭载", "features"), ("采用", "uses"), ("升级为", "upgrades to"), ("增至", "increased to"),
    ("由", "from"), ("至", "to"), ("与", "and"), ("及", "and"), ("或", "or"), ("均", "all"),
    ("也", "also"), ("已", "already"), ("将", "will"), ("可", "can"), ("其", "its"), ("该", "the"),
    ("每", "per"), ("最高", "maximum"), ("最低", "minimum"), ("约", "about"), ("仅", "only"),
    ("另", "plus"), ("享", "with"), ("回扣", "rebate"), ("降价", "price cut"), ("售价", "price"),
    ("定价", "pricing"), ("起售", "starting at"), ("预计", "expected"), ("可能", "possible"),
    ("新增", "new"), ("取消", "cancelled"), ("保留", "retained"), ("换装", "swaps to"),
    ("命名", "naming"), ("定位", "positioning"), ("目标", "target"), ("细分", "segment"),
    ("市场", "market"), ("大马", "Malaysia"), ("全尺寸", "full-size"), ("中型", "mid-size"),
    ("中大型", "mid-to-large"), ("小型", "small"), ("紧凑", "compact"), ("长续航", "long-range"),
    ("短续航", "short-range"), ("双门", "coupe"), ("四门", "four-door"), ("六座", "six-seat"),
    ("七座", "seven-seat"), ("五座", "five-seat"), ("八座", "eight-seat"), ("三排", "three-row"),
    ("两排", "two-row"), ("独立文章", "standalone article"), ("深度", "deep-dive"), ("文章", "article"),
    ("图集", "gallery"), ("规格", "specifications"), ("背景", "background"), ("整理", "compiled"),
    ("逐款", "model by model"), ("版权", "copyright"), ("归", "belongs to"), ("原网站", "original websites"),
    ("品牌方", "brands"), ("所有", "all"), ("飞驰", "speeds"), ("加速", "acceleration"),
    ("破百", "0-100"), ("零百", "0-100"),
]

def apply_terms(s):
    for zh, en in TERMS:
        if zh in s:
            s = s.replace(zh, en)
    return s

def fix_units(s):
    s = re.sub(r'(\d+(?:\.\d+)?)\s*吋', r'\1-inch', s)
    s = re.sub(r'(\d+(?:\.\d+)?)\s*台', r'\1 units', s)
    s = re.sub(r'(\d+(?:\.\d+)?)\s*个', r'\1 units', s)
    s = re.sub(r'(\d+(?:\.\d+)?)\s*款(?=[·\s,，、]|$)', r'\1 variants', s)
    s = re.sub(r'(\d+(?:\.\d+)?)\s*毫米', r'\1 mm', s)
    s = re.sub(r'(\d+(?:\.\d+)?)\s*公里', r'\1 km', s)
    s = re.sub(r'(\d+(?:\.\d+)?)\s*分钟', r'\1 min', s)
    s = re.sub(r'(\d+(?:\.\d+)?)\s*秒', r'\1s', s)
    s = re.sub(r'(\d+)\s*速[^\u4e00-\u9fff]{0,14}?(自排|手排|双离合)',
               lambda m: f"{m.group(1)}-speed " + {'自排': 'automatic', '手排': 'manual', '双离合': 'dual-clutch'}[m.group(2)], s)
    s = s.replace('湿式', 'wet ').replace('干式', 'dry ')
    def wan(m):
        n = float(m.group(1).replace(',', ''))
        return f"{int(n*10000):,}"
    s = re.sub(r'(\d[\d,]*)\s*万\s*km', lambda m: wan(m) + ' km', s)
    s = re.sub(r'(\d+)\s*年\s*/\s*(\d[\d,]*)\s*km', r'\1 years / \2 km', s)
    s = re.sub(r'(\d+)\s*年\s*/\s*(\d[\d,]*)\s*万\s*km',
               lambda m: f"{m.group(1)} years / {int(float(m.group(2).replace(',', '')) * 10000):,} km", s)
    s = re.sub(r'(\d+)\s*年', r'\1 years', s)
    s = re.sub(r'(\d+)\s*个月', r'\1 months', s)
    s = re.sub(r'(\d+(?:\.\d+)?)\s*千瓦时', r'\1 kWh', s)
    s = s.replace('磷酸铁锂', 'LFP (lithium iron phosphate)').replace('三元锂', 'ternary lithium') \
         .replace('锂电池', 'lithium battery').replace('电池', 'battery')
    s = s.replace('不限里程', 'unlimited mileage').replace('整车', 'vehicle').replace('油电系统', 'hybrid system')
    s = s.replace('净', 'net')
    s = re.sub(r'\s*·\s*(中国|马来西亚|日本|泰国|印尼|德国|英国|韩国|美国|法国|意大利|西班牙|瑞典|捷克)\s*/\s*', ' · ', s)
    s = re.sub(r'(\d)\s*座', r'\1-seat', s)
    s = s.replace('ASEAN NCAP 5 星', 'ASEAN NCAP 5-star').replace('ASEAN NCAP 5星', 'ASEAN NCAP 5-star')
    s = s.replace('手自一体', 'torque-converter automatic').replace('混动自动', 'hybrid automatic')
    s = s.replace('直流快充', 'DC fast-charging').replace('快充', 'fast-charging')
    s = s.replace('风阻系数', 'drag coefficient').replace('车身尺寸', 'dimensions')
    return s

def has_zh(s):
    return bool(re.search(r"[\u4e00-\u9fff]", s))

def split_sub(s):
    return re.match(r'^(//\s*\d{4}\.\d{2}\.\d{2}\s*·\s*[^··]+\s*·\s*)(.*)$', s)

# ---------------- 翻译引擎：DeepL 主 + Google v2 兜底 ----------------
# key 来源优先级：环境变量（CI: repo secrets）> 同目录文件（本地: chmod 600，不入库）
KEY_FILE = os.path.join(BASE, os.environ.get("DEEPL_KEY_FILE", ".translate_key"))
DEEPL_KEY = (os.environ.get("DEEPL_KEY") or "").strip()
if not DEEPL_KEY and os.path.exists(KEY_FILE):
    DEEPL_KEY = open(KEY_FILE, encoding="utf-8").read().strip()

GOOGLE_KEY_FILE = os.path.join(BASE, os.environ.get("GOOGLE_KEY_FILE", ".google_api_key"))
GOOGLE_KEY = (os.environ.get("GOOGLE_API_KEY") or "").strip()
if not GOOGLE_KEY and os.path.exists(GOOGLE_KEY_FILE):
    GOOGLE_KEY = open(GOOGLE_KEY_FILE, encoding="utf-8").read().strip()
# 端点可覆盖（自测/代理场景）；默认官方 v2
GOOGLE_ENDPOINT = os.environ.get("GOOGLE_TRANSLATE_ENDPOINT",
                                 "https://translation.googleapis.com/language/translate/v2")
# 可选：显式指定出网代理。CI/服务器直连时留空即可（走标准 http(s)_proxy 或直接出网）；
# 本地若 HTTPS_PROXY 被上游代理劫持（该代理屏蔽 Google 时 urllib 会 502），
# 可用 GOOGLE_TRANSLATE_PROXY=http://127.0.0.1:10808 强制走指定出口。
GOOGLE_PROXY = (os.environ.get("GOOGLE_TRANSLATE_PROXY") or "").strip()

# ---------------- 在线翻译 API 闸门 ----------------
#   off（默认）：一律不调用在线 API。若仍有未译条目 → 不写产物、导出清单、退出码 2。
#   ask        ：交互式确认（本地用；CI/非交互环境视为拒绝）。
#   on         ：允许调用（需显式开启）。
TRANSLATE_API = (os.environ.get("TRANSLATE_API") or "off").strip().lower()

def _gate_api(todo):
    """闸门。返回 True=允许调用；False=调用方必须立即退出且不写产物。"""
    if not todo:
        return True
    chars = sum(len(x[1]) for x in todo)
    if TRANSLATE_API == "on":
        print(f"[api] 闸门=on，将调用在线翻译：{len(todo)} 条 / {chars} 字符")
        return True
    try:
        with open(os.path.join(CACHE_DIR, "untranslated.json"), "w", encoding="utf-8") as f:
            json.dump([{"zh": k, "payload": p} for k, p, _ in todo],
                      f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"[api] 待译清单导出失败：{e}")
    if TRANSLATE_API == "ask":
        try:
            ans = input(f"[api] 待译 {len(todo)} 条 / {chars} 字符，调用在线翻译？[y/N] ").strip().lower()
        except EOFError:                      # CI / 非交互环境
            ans = "n"
        if ans in ("y", "yes"):
            print("[api] 已确认，继续调用")
            return True
    print("\n❌ 在线翻译 API 已关闭（TRANSLATE_API=off），但仍有未译条目：")
    print(f"   待译 {len(todo)} 条 / {chars} 字符"
          f"（约占 DeepL 免费档 50 万/月的 {chars/500000*100:.1f}%）")
    print("   清单已导出：.cache/untranslated.json —— 人工译好后填入 en_b1/en_b2，重跑即命中")
    print("   确认要调用时：TRANSLATE_API=on python make_en_v2.py")
    print("   产物未写入，launches_en.html 保持原样。")
    return False

def _gopen(req, timeout=30):
    if GOOGLE_PROXY:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": GOOGLE_PROXY, "https": GOOGLE_PROXY}))
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)
_google_warned = False
# 先试 pro 端点，再回退 free 端点（free 仅 EU IP 可用，非 EU 会 456）
DEEPL_HOSTS = ["https://api.deepl.com", "https://api-free.deepl.com"]

def _deepl_call(texts):
    """一次性翻译多个文本；返回与 texts 等长的英文列表。失败/无 key 返回原文。"""
    if not DEEPL_KEY:
        return list(texts)
    texts = list(texts)
    data = {"source_lang": "ZH", "target_lang": "EN", "text": texts}
    body = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded",
               "Authorization": "DeepL-Auth-Key " + DEEPL_KEY}
    for host in DEEPL_HOSTS:
        req = urllib.request.Request(host + "/v2/translate", data=body, headers=headers)
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    d = json.load(r)
                trs = d.get("translations", [])
                out = []
                for i, t in enumerate(trs):
                    out.append(t.get("text", texts[i]))
                # 不足补原文
                out += texts[len(out):]
                if len(out) == len(texts):
                    return out
                return out[:len(texts)]  # 保险
            except urllib.error.HTTPError as e:
                if e.code in (403, 456):
                    break  # 该 host 不可用，换下一个
                if e.code == 429:
                    time.sleep(2 * (attempt + 1)); continue  # 限流退避
                return list(texts)
            except Exception:
                time.sleep(1.5); continue
    return list(texts)

def _google_call(texts):
    """Google Cloud Translation v2 批量翻译（zh→en）。失败/未配置/项目被阻 → 返回原文。
    注：v2 对未启用结算或受组织策略限制的项目会返回 403 '... are blocked.'，
    此处静默降级，保证 EN 构建不被打断。网络走标准 http(s)_proxy 环境变量。"""
    global _google_warned
    texts = list(texts)
    if not GOOGLE_KEY:
        return texts
    import html as _html
    body = json.dumps({"q": texts, "source": "zh-CN", "target": "en",
                       "format": "text"}).encode("utf-8")
    url = GOOGLE_ENDPOINT + "?key=" + urllib.parse.quote(GOOGLE_KEY)
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    for attempt in range(3):
        try:
            with _gopen(req, timeout=30) as r:
                d = json.load(r)
            trs = d.get("data", {}).get("translations", [])
            out = [_html.unescape(t.get("translatedText", texts[i])) for i, t in enumerate(trs)]
            out += texts[len(out):]
            return out[:len(texts)]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 * (attempt + 1)); continue
            # 403 blocked（未开结算/组织策略）、400、401… 只提示一次后彻底降级
            if not _google_warned:
                _google_warned = True
                try:
                    detail = json.load(e).get("error", {}).get("message", str(e))
                except Exception:
                    detail = str(e)
                print(f"[google] 不可用（HTTP {e.code}），本轮跳过 Google 兜底：{detail}")
            return texts
        except Exception:
            time.sleep(1.5); continue
    return texts

def translate_batch(texts):
    """两级引擎：DeepL 主 → 仍未译出（残留中文）的条目交给 Google 兜底。"""
    texts = list(texts)
    out = _deepl_call(texts)
    missing = [i for i, t in enumerate(out) if has_zh(t)]
    if missing and GOOGLE_KEY:
        gout = _google_call([texts[i] for i in missing])
        for j, i in enumerate(missing):
            if not has_zh(gout[j]):
                out[i] = gout[j]
    return out

def api_tr(batch):
    return translate_batch(batch)

def api_one(q):
    res = translate_batch([q])
    return res[0] if res else q

# 主导航链接的 EN 化映射。EN 页若仍链 / 或 /news，用户点进去会被入口页
# 把 wb_lang 落定成 zh，等于把整站语言翻回中文（V299 修的就是这个）。
# /tool 是单文件双语，保持不变。
NAV_HREF_EN = {"/": "/index_en", "/index": "/index_en",
               "/news": "/news_en", "/launches": "/launches_en"}

def fix_body_lang(soup):
    """EN 页 <body data-lang> 必须写死 en。
    V300 定稿原则：结果写死在资源本身，不依赖运行时推断。
    照抄 ZH 源的 data-lang="zh" 会让英文 URL 渲染出中文内容。"""
    if soup.body is None:
        return False
    soup.body["data-lang"] = "en"
    return True

def fix_nav_hrefs(soup):
    """主导航链接改指向英文页；语言切换器内的链接必须跳过。"""
    n = 0
    for nav in soup.find_all("nav", class_="links"):
        for a in nav.find_all("a"):
            if a.find_parent(class_="lang-switch"):
                continue
            h = a.get("href")
            if h in NAV_HREF_EN:
                a["href"] = NAV_HREF_EN[h]
                n += 1
    return n

def fix_lang_switch(soup):
    """修正 EN 页顶部语言切换器（翻译管线无法处理，必须后处理）。

    ZH 源里 class="on" 落在中文链接上（对 ZH 页正确），照抄到 EN 页会导致：
      ① EN 页却高亮「中文」；② 「中文」按钮被译成 Chinese，用户切不回中文。
    这里强制还原为 EN 页应有的形态，并返回是否命中。
    """
    box = soup.find(class_="lang-switch")
    if not box:
        return False
    links = box.find_all("a")
    if len(links) < 2:
        return False
    zh_a, en_a = links[0], links[1]
    zh_a.string = "中文"          # 必须是中文，否则中文用户看不懂切回入口
    en_a.string = "EN"
    zh_a["href"] = "/launches"
    en_a["href"] = "/launches_en"
    for a in (zh_a, en_a):        # 清掉所有 on，稍后只给 EN 加
        cls = [c for c in (a.get("class") or []) if c != "on"]
        if cls:
            a["class"] = cls
        elif "class" in a.attrs:
            del a["class"]        # 不留空 class=""
    en_a["class"] = (en_a.get("class") or []) + ["on"]
    return True

def harvest_from_dst(soup):
    """从已存在的 EN 产物按位回采译文，防止缓存缺失时用机器翻译覆盖人工润色。

    典型场景：CI 首次运行（actions/cache 为空）、或本地 .cache 被清掉。
    只在文本节点数严格相等时启用——结构一致才敢按位配对，绝不猜。
    """
    import os as _os
    if not _os.path.exists(DST):
        return {}
    try:
        prev = BeautifulSoup(open(DST, encoding="utf-8").read(), "html.parser")
    except Exception as e:
        print(f"[harvest] 读取现有 EN 失败，跳过：{e}")
        return {}
    cur, old = [], []
    for s in soup.find_all(string=True):
        if s.parent.name in ("script", "style"):
            continue
        cur.append(str(s).strip())
    for s in prev.find_all(string=True):
        if s.parent.name in ("script", "style"):
            continue
        old.append(str(s).strip())
    if len(cur) != len(old):
        print(f"[harvest] 跳过：结构已变，不敢按位配对"
              f"（ZH {len(cur)} 节点 / 现有 EN {len(old)} 节点）")
        return {}
    out = {}
    for a, b in zip(cur, old):
        if a and b and has_zh(a) and not has_zh(b) and a != b:
            out[a] = b
    return out

# ---------------- 主流程 ----------------
def main():
    html = open(SRC, encoding="utf-8").read()
    soup = BeautifulSoup(html, "html.parser")
    text_strs = set()
    for el in soup.find_all(string=True):
        if el.parent.name in ("script", "style"):
            continue
        # 语言切换器的「中文/EN」由 fix_lang_switch 后处理，不参与翻译管线，
        # 否则 "中文" 会被当作未译条目，在 API 关闭时触发闸门失败。
        if el.find_parent(class_="lang-switch"):
            continue
        s = str(el).strip()
        if s and has_zh(s):
            text_strs.add(s)
    attr_strs = set()
    attr_targets = []
    for tag in soup.find_all():
        for attr in ("alt", "title", "aria-label", "data-lang", "placeholder"):
            v = tag.get(attr)
            if isinstance(v, str) and has_zh(v):
                attr_strs.add(v.strip())
                attr_targets.append((tag, attr))
    all_strs = sorted(text_strs | attr_strs)
    print(f"含中文唯一串: {len(all_strs)}")

    # 复用旧映射中已译条目
    reuse = {}
    for k, v in _load_map(OLD_MAP, OLD_MAP_TMP).items():
        if v != k and not has_zh(v):
            reuse[k] = v
    print(f"复用旧映射已译条目: {len(reuse)}")

    tr_map = {}
    # 断点续传：复用已译条目（value 非中文），避免重复调用/丢失进度
    prev = _load_map(MAP, MAP_TMP)
    if prev:
        for k, v in prev.items():
            if not has_zh(v):
                tr_map[k] = v
        print(f"续传：载入已译 {len(tr_map)} 条")

    # 自愈：缓存缺失时从现有 EN 产物按位回采，避免机器翻译覆盖人工润色
    # （CI 首跑 actions/cache 为空时若不回采，会把线上已润色过的译法全冲掉）
    _hv = harvest_from_dst(soup)
    _hv = {k: v for k, v in _hv.items() if k not in tr_map}
    if _hv:
        print(f"[harvest] 从现有 EN 页回采 {len(_hv)} 条既有译文")
        tr_map.update(_hv)

    todo = []  # (key, payload, head_or_None)
    for s in all_strs:
        if s in tr_map:
            continue  # 已译（含 LOCAL/MANUAL/reuse/续传）
        if s in LOCAL:
            tr_map[s] = LOCAL[s]; continue
        if s in MANUAL:
            tr_map[s] = MANUAL[s]; continue
        if s in reuse:
            tr_map[s] = reuse[s]; continue
        m = split_sub(s)
        if m:
            head, desc = m.group(1), m.group(2)
            rd = fix_units(apply_terms(desc))
            if not has_zh(rd):
                tr_map[s] = head + rd; continue
            todo.append((s, desc, head))  # MyMemory on original desc
        else:
            t = fix_units(apply_terms(s))
            if not has_zh(t):
                tr_map[s] = t; continue
            todo.append((s, s, None))  # MyMemory on original s

    print(f"需 MyMemory 翻译: {len(todo)}")
    if not _gate_api(todo):
        return 2          # 闸门拦下：不写产物，CI 会红

    # 分批：长串(>400)单独，其余每 3 个
    long_items = [x for x in todo if len(x[1]) > 400]
    short_items = [x for x in todo if len(x[1]) <= 400]
    batches = [ [x] for x in long_items ]
    batches += [ short_items[i:i+3] for i in range(0, len(short_items), 3) ]

    lock = threading.Lock()
    done = 0
    def save():
        json.dump(tr_map, open(MAP, "w", encoding="utf-8"), ensure_ascii=False, indent=0)

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {}
        for b in batches:
            payloads = [x[1] for x in b]
            futs[ex.submit(api_tr, payloads)] = b
        for fut in as_completed(futs):
            b = futs[fut]
            res = fut.result()
            with lock:
                for item, en in zip(b, res):
                    key, payload, head = item
                    if has_zh(en):
                        en = api_one(payload)  # 兜底单条
                    # 仅写入非中文结果；失败则留空，下次续传重试
                    if not has_zh(en):
                        tr_map[key] = (head + en) if head is not None else en
                done += len(b)
                save()  # 每批后立即落盘，断点续传
                if done % 30 == 0 or done == len(todo):
                    print(f"  进度 {done}/{len(todo)}")

    save()

    # 回写
    for el in soup.find_all(string=True):
        if el.parent.name in ("script", "style"):
            continue
        s = str(el).strip()
        if s and has_zh(s):
            new = tr_map.get(s, s)
            if new != s:
                el.replace_with(NavigableString(new))
    for tag, attr in attr_targets:
        v = tag.get(attr)
        if isinstance(v, str) and has_zh(v):
            nv = tr_map.get(v.strip(), v)
            tag[attr] = nv
    soup.html["lang"] = "en"
    n_body = fix_body_lang(soup)
    n_href = fix_nav_hrefs(soup)
    n_switch = fix_lang_switch(soup)
    print(f"[en-ify] body data-lang={'ok' if n_body else 'MISS'} / "
          f"导航链接改写 {n_href} 条 / 语言切换器={'ok' if n_switch else 'MISS'}")
    if not (n_body and n_switch):
        print("[en-ify] 警告：EN 化未全部命中，产物可能仍是中文态")
    title_tag = soup.find("title")
    if title_tag:
        ts = title_tag.get_text().strip()
        if has_zh(ts):
            title_tag.string = tr_map.get(ts, ts)
    out = str(soup)
    open(DST, "w", encoding="utf-8").write(out)
    print("已写出:", DST, "| 大小:", len(out.encode()), "bytes")
    zh_left = len(re.findall(r"[\u4e00-\u9fff]", out))
    print("残留中文字数:", zh_left)
    h3 = re.findall(r"<h3[^>]*>(.*?)</h3>", out, re.S)
    h2 = re.findall(r"<h2[^>]*>(.*?)</h2>", out, re.S)
    cars = set()
    for s in h2 + h3:
        s = re.sub(r"<[^>]+>", "", s).strip()
        if s and len(s) < 60:
            cars.add(s)
    print("英文版车型章节数:", len(cars))

if __name__ == "__main__":
    sys.exit(main() or 0)
