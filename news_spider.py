import requests
from bs4 import BeautifulSoup
import json
import time
import random
from datetime import datetime
from urllib.parse import urljoin
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ===== 关键词过滤 =====
KEYWORD_FILTERS = ['TOD', '综合开发', '枢纽', '城际', '地铁', '轨道', '铁路', '站城', '高铁', '轨道交通', '上盖', '国铁']

# ===== 从 sources.json 读取数据源 =====
def load_sources():
    try:
        with open('sources.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"读取 sources.json 失败: {e}")
        # 默认使用几个基本数据源
        return [
            {"name": "百度新闻", "url": "https://news.baidu.com/s?tn=news&word=TOD", "select": "div.result a", "limit": 15, "pages": 1},
            {"name": "360新闻", "url": "https://news.so.com/ns?q=%E5%9C%B0%E9%93%81%20TOD", "select": "li.res-list a", "limit": 12, "pages": 1},
        ]

def fetch_news():
    logging.info("🤖 爬虫启动（无摘要版）")
    
    # ===== 读取旧数据 =====
    try:
        with open('news_data.json', 'r', encoding='utf-8') as f:
            all_news = json.load(f)
        logging.info(f"📚 成功读取 {len(all_news)} 条历史数据")
    except FileNotFoundError:
        all_news = []
        logging.info("📚 没有历史数据，从零开始")
    except json.JSONDecodeError:
        logging.error("❌ news_data.json 格式错误，请手动修复！")
        return
    
    existing_keys = {item["标题"][:20] + item.get("链接", "")[:50] for item in all_news}
    
    # ===== 加载数据源 =====
    sources = load_sources()
    logging.info(f"📡 加载 {len(sources)} 个数据源")
    
    new_count = 0
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    
    for src in sources:
        name = src.get('name', '未知')
        base_url = src.get('url', '')
        selector = src.get('select', 'a')
        limit = src.get('limit', 10)
        pages = src.get('pages', 1)
        
        if not base_url:
            continue
        
        logging.info(f"🔍 抓取: {name}")
        
        for page in range(1, pages + 1):
            page_url = base_url if page == 1 else base_url + (f'&page={page}' if '?' in base_url else f'?page={page}')
            
            try:
                resp = session.get(page_url, timeout=15)
                if resp.status_code != 200:
                    continue
                
                soup = BeautifulSoup(resp.text, 'html.parser')
                items = soup.select(selector)
                
                if not items:
                    continue
                
                count = 0
                for item in items[:limit]:
                    try:
                        title = item.text.strip()
                        link = item.get('href')
                        
                        if not title or not link or len(title) < 6:
                            continue
                        
                        if not any(k in title for k in KEYWORD_FILTERS):
                            continue
                        
                        full_link = urljoin(page_url, link)
                        
                        key = title[:20] + full_link[:50]
                        if key in existing_keys:
                            continue
                        existing_keys.add(key)
                        
                        # 范围判断
                        scope = "全国"
                        if "广州" in title:
                            scope = "广州市"
                        elif any(w in title for w in ["广东", "深圳", "佛山", "东莞"]):
                            scope = "广东省"
                        
                        # 类型判断
                        news_type = "综合"
                        type_keywords = {
                            "项目建设进展": ["封顶", "开工", "竣工", "通车", "开通", "投运", "动工", "建设", "进展", "完成", "交付", "贯通"],
                            "规划公示/获批": ["规划", "公示", "获批", "审议", "通过", "方案", "批复"],
                            "政策/行业观点": ["政策", "出台", "发布", "意见", "办法", "条例"],
                            "商业配套/招商": ["商业", "招商", "商场", "签约", "入驻", "开业"],
                            "投融资": ["投资", "融资", "资本", "基金", "授信", "债券"],
                            "可持续经营运营": ["可持续", "经营", "运营", "营收", "盈利"]
                        }
                        for t, kws in type_keywords.items():
                            if any(kw in title for kw in kws):
                                news_type = t
                                break
                        
                        # 关键词
                        keywords = []
                        kw_map = {
                            '国铁': ['高铁', '铁路', '国铁'],
                            '城际': ['城际'],
                            '地铁': ['地铁'],
                            '轨道': ['轨道', '轨交'],
                            '综合交通枢纽': ['枢纽'],
                            '综合开发': ['TOD', '综合开发', '上盖'],
                            '投融资': ['融资', '投资'],
                            '可持续经营运营': ['可持续', '经营', '运营']
                        }
                        for kw, words in kw_map.items():
                            if any(w in title for w in words):
                                keywords.append(kw)
                        if not keywords:
                            keywords = ["轨道"]
                        
                        # ===== 关键改动：没有摘要字段！ =====
                        all_news.append({
                            "日期": datetime.now().strftime("%Y-%m-%d"),
                            "标题": title,
                            "链接": full_link,
                            "来源": name,
                            "范围": scope,
                            "关键词": keywords,
                            "类型": news_type
                        })
                        count += 1
                        new_count += 1
                        time.sleep(random.uniform(0.2, 0.5))
                    except Exception as e:
                        logging.debug(f"处理条目失败: {e}")
                        continue
                
                logging.info(f"✅ {name} 第 {page} 页新增 {count} 条")
                
            except Exception as e:
                logging.error(f"❌ {name} 第 {page} 页出错: {e}")
            
            time.sleep(random.uniform(0.5, 1.5))
    
    all_news.sort(key=lambda x: x["日期"], reverse=True)
    
    with open('news_data.json', 'w', encoding='utf-8') as f:
        json.dump(all_news, f, ensure_ascii=False, indent=2)
    
    logging.info(f"🎉 完成！新增 {new_count} 条，共 {len(all_news)} 条")

if __name__ == "__main__":
    fetch_news()
