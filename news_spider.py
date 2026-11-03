import requests
from bs4 import BeautifulSoup
import json
import time
import re
import os
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse
import logging
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ============ 关键词配置（对齐前端） ============
SUBJECTS = ['国铁', '铁路', '城际', '地铁']
AREAS = ['规划', '城市设计', '建筑', '交通', '产业', '投融资', '招商', '运营', '站城融合', 'TOD', '获奖']
ALLOWED_KEYWORDS = set(SUBJECTS + AREAS)

KEYWORD_FILTERS = ['TOD', '综合开发', '枢纽', '城际', '地铁', '轨道', '铁路', '站城',
                   '高铁', '轨道交通', '上盖', '国铁', '投融资', '运营', '招商']

FALLBACK_SELECTORS = [
    'div.news-list li a', 'div.news_list li a', 'ul.news-list li a',
    'ul.list li a', 'div.newslist ul li a', 'div.newsList ul li a',
    'div.list ul li a', 'div.list_box ul li a', 'h3 a', 'h2 a',
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

# 关键词映射（清理时使用）
KW_MAP = {
    '可持续经营运营': '运营',
    '轨道': '铁路',
}


# ============================================================
# 基础工具
# ============================================================
def fetch(url, encoding='utf-8', retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20, verify=False)
            r.encoding = encoding
            return r
        except Exception:
            if i < retries - 1:
                time.sleep(2)
    return None


def clean_html(text):
    if not text:
        return ''
    text = text.replace('&amp;', '&').replace('&quot;', '"').replace('&nbsp;', ' ')
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def clean_title(title):
    """深度清洗标题：去换行、快资讯后缀、多余空白"""
    if not title:
        return ''
    title = clean_html(title)
    # 去 "快资讯X小时前/天前/分钟前"
    title = re.sub(r'\s*快资讯\s*\d+\s*(小时|天|分钟)前\s*$', '', title)
    # 去单独的时间戳后缀，如 "2026-08-31 08:14"
    title = re.sub(r'\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s*$', '', title)
    # 去 "X天前/小时前/分钟前"
    title = re.sub(r'\s*\d+\s*(天|小时|分钟)前\s*$', '', title)
    title = re.sub(r'\s+', ' ', title).strip()
    return title


def normalize_url(url):
    """URL 归一化：去掉 query，统一 mpost_/BIG5 等变体"""
    try:
        p = urlparse(url)
        path = p.path.replace('/mpost_', '/post_').replace('/BIG5/', '/')
        return urlunparse((p.scheme, p.netloc, path, '', '', '')).rstrip('/')
    except Exception:
        return url or ''


def is_bad_link(url):
    if not url or url.startswith(('javascript', '#', 'mailto:')):
        return True
    bad_ext = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg',
               '.pdf', '.zip', '.rar', '.mp4', '.mp3')
    return urlparse(url).path.lower().endswith(bad_ext)


def get_date(url):
    """从 URL 提取日期，失败返回今天"""
    m = re.search(r'(20\d{2})[/-]?([01]\d)[/-]?([0-3]\d)', url)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 2020 <= y <= 2030 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y}-{mo:02d}-{d:02d}"
    return datetime.now().strftime("%Y-%m-%d")


def detect_scope(title):
    if any(w in title for w in ['世界', '国际', '全球']):
        return '世界'
    if '广州' in title:
        return '广州市'
    if any(w in title for w in ['广东', '深圳', '佛山', '东莞', '珠海', '中山', '汕头']):
        return '广东省'
    return '全国'


def detect_type(title):
    type_map = {
        '项目建设进展': ['封顶', '开工', '竣工', '通车', '开通', '投运', '贯通', '合龙', '铺轨', '盾构', '进展'],
        '规划公示/获批': ['规划', '公示', '获批', '审议', '批复', '可研', '立项'],
        '政策/行业观点': ['政策', '出台', '发布', '意见', '条例', '观点', '论坛', '会议'],
        '商业配套/招商': ['商业', '招商', '签约', '入驻', '开业'],
        '投融资': ['投资', '融资', '资本', '基金', '债券', '亿元'],
        '可持续经营运营': ['运营', '客流', '获奖', '表彰', '可持续'],
    }
    for t, kws in type_map.items():
        if any(k in title for k in kws):
            return t
    return '综合'


def build_keywords(title):
    kws = []
    for s in SUBJECTS:
        if s in title:
            kws.append(s)
    if '高铁' in title and '国铁' not in kws:
        kws.append('国铁')
    if ('轨道' in title or '轨交' in title) and not any(x in kws for x in ['地铁', '城际', '铁路', '国铁']):
        kws.append('铁路')
    for a in AREAS:
        if a in title:
            kws.append(a)
    kws = list(dict.fromkeys(kws))
    return kws if kws else ['铁路', '交通']


def save_atomic(data, path='news_data.json'):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ============================================================
# 清理函数：每次爬完自动跑一遍
# ============================================================
def clean_dataset(data):
    """清洗数据集：
       1. 标题去脏字符
       2. 关键词对齐前端（过滤非法词，映射别名）
       3. 按归一化 URL + 标题 去重
       4. 按日期降序排列
    """
    before = len(data)
    cleaned = []
    seen = set()

    for item in data:
        if not isinstance(item, dict):
            continue

        title = clean_title(item.get('标题', ''))
        if not title or len(title) < 4:
            continue

        url = item.get('链接', '')
        if not url:
            continue

        # 去重 key：清洗后标题前30字 + 归一化 URL
        key = title[:30] + normalize_url(url)[:80]
        if key in seen:
            continue
        seen.add(key)

        # 关键词清洗
        raw_kws = item.get('关键词', [])
        if not isinstance(raw_kws, list):
            raw_kws = []
        kws = []
        for k in raw_kws:
            k = KW_MAP.get(k, k)
            if k in ALLOWED_KEYWORDS and k not in kws:
                kws.append(k)
        if not kws:
            kws = build_keywords(title)

        item['标题'] = title
        item['关键词'] = kws
        # 类型不在规定枚举里的归为综合
        if item.get('类型') not in ['项目建设进展', '规划公示/获批', '政策/行业观点',
                                    '商业配套/招商', '投融资', '可持续经营运营', '综合']:
            item['类型'] = '综合'
        cleaned.append(item)

    cleaned.sort(key=lambda x: x.get('日期', ''), reverse=True)
    logging.info(f"🧹 清理：{before} → {len(cleaned)} 条（去重 {before - len(cleaned)} 条）")
    return cleaned


# ============================================================
# 主流程
# ============================================================
def main():
    logging.info("🤖 爬虫启动")

    # 读历史数据
    news = []
    if os.path.exists('news_data.json'):
        try:
            with open('news_data.json', 'r', encoding='utf-8') as f:
                news = json.load(f)
            if not isinstance(news, list):
                logging.warning("⚠️ news_data.json 不是数组，备份重置")
                os.replace('news_data.json', 'news_data.json.bak')
                news = []
            else:
                logging.info(f"📚 历史 {len(news)} 条")
        except json.JSONDecodeError:
            logging.error("❌ JSON 损坏，备份为 .bak 并重置")
            os.replace('news_data.json', 'news_data.json.bak')
            news = []

    # 先用历史数据建立去重索引
    keys = {clean_title(i.get('标题', ''))[:30] + normalize_url(i.get('链接', ''))[:80]
            for i in news if isinstance(i, dict)}

    # 加载数据源
    try:
        with open('sources.json', 'r', encoding='utf-8') as f:
            sources = json.load(f)
        if not isinstance(sources, list):
            raise ValueError("sources.json 不是数组")
    except Exception as e:
        logging.error(f"❌ 读取 sources.json 失败: {e}")
        return

    logging.info(f"📡 加载 {len(sources)} 个数据源")

    added = 0
    ok, fail = [], []

    try:
        for src in sources:
            name = src.get('name', '未知')
            url = src.get('url', '')
            sel = src.get('select', 'a')
            limit = src.get('limit_per_page') or src.get('limit') or 10
            enc = src.get('encoding', 'utf-8')
            pages = src.get('pages', 1)

            if not url:
                logging.warning(f"⏭️ {name} 缺少 URL")
                continue

            logging.info(f"🔍 {name}")
            cnt = 0

            for p in range(1, pages + 1):
                page_url = url if p == 1 else url + ('&' if '?' in url else '?') + f'page={p}'
                r = fetch(page_url, encoding=enc)

                if not r or r.status_code != 200:
                    code = r.status_code if r else 'ERR'
                    logging.warning(f"  ⚠️ 第{p}页 状态 {code}")
                    continue

                soup = BeautifulSoup(r.text, 'html.parser')

                # 主选择器 → 备选选择器
                items = []
                for s in [sel] + FALLBACK_SELECTORS:
                    try:
                        items = soup.select(s)
                        if items:
                            break
                    except Exception:
                        continue

                if not items:
                    logging.warning(f"  ⚠️ 第{p}页 无匹配（HTML {len(r.text)} 字节）")
                    continue

                for item in items[:limit]:
                    try:
                        a = item if item.name == 'a' else item.find('a')
                        if not a:
                            continue

                        href = a.get('href') or ''
                        raw_title = a.get('title') or a.text or ''
                        title = clean_title(raw_title)

                        if not href or is_bad_link(href):
                            continue
                        if len(title) < 6:
                            continue
                        if not any(k in title for k in KEYWORD_FILTERS):
                            continue

                        link = urljoin(page_url, href)
                        key = title[:30] + normalize_url(link)[:80]
                        if key in keys:
                            continue
                        keys.add(key)

                        news.append({
                            '日期': get_date(link),
                            '标题': title,
                            '链接': link,
                            '来源': name,
                            '范围': detect_scope(title),
                            '关键词': build_keywords(title),
                            '类型': detect_type(title),
                        })
                        cnt += 1
                        added += 1
                        time.sleep(0.3)

                    except Exception as e:
                        logging.debug(f"处理条目失败: {e}")
                        continue

                time.sleep(1)

            logging.info(f"  ✅ 新增 {cnt} 条")
            (ok if cnt > 0 else fail).append(name)

            # 每抓完一个源就清理并落盘
            news = clean_dataset(news)
            save_atomic(news)

    finally:
        # 最终清理并保存（即使中途异常也执行）
        news = clean_dataset(news)
        save_atomic(news)

        logging.info("=" * 50)
        logging.info(f"✅ 成功源 {len(ok)}: {', '.join(ok) if ok else '-'}")
        logging.info(f"❌ 失败源 {len(fail)}: {', '.join(fail) if fail else '-'}")
        logging.info(f"🎉 完成！本次新增 {added} 条，共 {len(news)} 条")


if __name__ == '__main__':
    main()
