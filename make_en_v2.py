#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 launches_en.html（v2：手动词典 + 规则 + DeepL 补全）。
优先级：LOCAL 词典 > en_b1/en_b2 手动 > 规则引擎 > DeepL（zh→en）。
DeepL key 从同目录 .translate_key 读取（chmod 600，不入库、不回显）。
缓存映射存项目内 .cache/（旧 /tmp 位置自动回退并迁移）；支持断点续传。
路径基于脚本目录推导，可用环境变量覆盖：LAUNCHES_SRC / LAUNCHES_DST / DEEPL_KEY_FILE。
目标：英文版覆盖 100% 内容（0 残留中文，134 车型章节）。"""
import re, json, os, time, urllib.parse, urllib.request, urllib.error, threading
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
            with urllib.request.urlopen(req, timeout=30) as r:
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

# ---------------- 主流程 ----------------
def main():
    html = open(SRC, encoding="utf-8").read()
    soup = BeautifulSoup(html, "html.parser")
    text_strs = set()
    for el in soup.find_all(string=True):
        if el.parent.name in ("script", "style"):
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
    main()
