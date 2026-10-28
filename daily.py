"""中文优先的正畸行业每日微信简报（零 AI API 依赖，仅 Python 标准库）。"""
import datetime as dt
import email.utils
import html
import textwrap
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = 'OrthodonticDailyDigest/2.0 (personal research digest)'
TZ = dt.timezone(dt.timedelta(hours=8))
NEWS_LIMIT = 14       # 最多14条真正相关的行业新闻
PAPER_LIMIT = 14      # 最多14篇正畸相关论文
NEWS_EXCERPT_CHARS = 260
PAPER_ABSTRACT_CHARS = 260  # 英文摘要约4–6行，按字符截断
HIGHLIGHT_LIMIT = 7  # 最多7条重点；不足时不凑数

# 注意：只根据标题判断相关性，不假称已核验正文或临床疗效。
CORE = ('正畸', '错颌', '错牙合', '牙齿矫正', '牙套', '托槽', '隐形矫治', '隐形正畸',
        'orthodont', 'malocclusion', 'clear aligner', 'clear-aligner', 'invisalign',
        'bracket', 'dentofacial orthoped', 'orthognathic')
SUPPORT = ('牙弓', '牙列', '功能矫治', '生长改良', '矫治器', '正颌', '支抗钉', '种植支抗',
           '舌侧矫治', '头影测量', '颌骨生长', '早期矫治', '时代天使', '正雅', '爱齐科技',
           'aligner', 'orthopedic appliance', 'cephalometric', 'temporary anchorage',
           'tooth movement', 'maxillary expansion', 'rapid palatal expansion',
           'class ii malocclusion', 'class iii malocclusion', 'mandibular advancement')
EXCLUDE = ('房地产', '美国会', '美国总统', '国际关系', '以色列', '俄罗斯', '美联储', '股市',
           'economic outlook', 'football', 'basketball', 'fashion week')

TOPICS = [
    ('儿童早期矫治与生长改良', ('儿童', '早期矫治', '生长改良', '功能矫治', '上颌扩弓', 'class ii', 'class iii', 'growth modification', 'maxillary expansion', 'mandibular advancement')),
    ('隐形矫治与数字化', ('隐形', '牙套', '数字化', 'aligner', 'invisalign', 'digital orthodont', '3d print', '人工智能', 'ai辅助')),
    ('临床机制与治疗技术', ('正畸', '错颌', '正颌', '支抗', '托槽', '牙移动', 'orthodont', 'malocclusion', 'bracket', 'anchorage', 'tooth movement', 'root resorption')),
    ('市场、企业与政策', ('时代天使', '正雅', '爱齐科技', '医保', '监管', '市场', '融资', '产品发布', '营收', 'acquisition', 'launch', 'market')),
]

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=25) as res:
        return res.read()

def norm(s):
    return re.sub(r'\W+', '', html.unescape(s).lower(), flags=re.UNICODE)

def related(title):
    t = html.unescape(title).lower()
    if any(x in t for x in EXCLUDE):
        return False
    return any(x in t for x in CORE) or any(x in t for x in SUPPORT)

def score(item):
    t = item['title'].lower()
    s = sum(3 for x in CORE if x in t) + sum(2 for x in SUPPORT if x in t)
    s += 2 if any(x in t for x in ('正畸', 'orthodont', '隐形矫治', 'clear aligner')) else 0
    return s

def topic(title):
    t = title.lower()
    for label, keys in TOPICS:
        if any(x in t for x in keys):
            return label
    return '其他正畸资讯'

def is_cn(s):
    return bool(re.search(r'[\u4e00-\u9fff]', s))

def clean_excerpt(raw, limit):
    """仅呈现信息源明确提供的原文摘录，不虚构中文摘要。"""
    raw = re.sub(r'<[^>]+>', ' ', raw or '')
    raw = html.unescape(raw)
    raw = re.sub(r'\s+', ' ', raw).strip()
    return raw[:limit].rstrip('，。；;,. ') + ('…' if len(raw) > limit else '') if raw else ''


def pubmed_abstracts(ids):
    """从PubMed XML获取摘要，截取原文；未提供摘要时返回空值。"""
    if not ids:
        return {}
    params = urllib.parse.urlencode({'db': 'pubmed', 'id': ','.join(ids), 'retmode': 'xml'})
    root = ET.fromstring(fetch('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?' + params))
    abstracts = {}
    for article in root.findall('.//PubmedArticle'):
        pid = article.findtext('./MedlineCitation/PMID')
        bits = []
        for part in article.findall('.//Abstract/AbstractText'):
            txt = ' '.join(part.itertext()).strip()
            if txt:
                label = part.get('Label') or part.get('NlmCategory', '')
                bits.append((label + ': ' if label and label != 'UNASSIGNED' else '') + txt)
        if pid and bits:
            abstracts[pid] = clean_excerpt(' '.join(bits), PAPER_ABSTRACT_CHARS)
    return abstracts


def pubmed():
    # 相比普通口腔检索，明确限制正畸主题；先扩量，再按标题过滤。
    q = '("Orthodontics"[MeSH Terms] OR orthodontic[Title] OR orthodontics[Title] OR malocclusion[Title] OR "clear aligner"[Title] OR "orthodontic tooth movement"[Title] OR "rapid maxillary expansion"[Title])'
    args = urllib.parse.urlencode({'db': 'pubmed', 'term': q, 'sort': 'pub date', 'retmax': 50, 'retmode': 'json', 'reldate': 7, 'datetype': 'edat'})
    search = json.loads(fetch('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?' + args))
    ids = search.get('esearchresult', {}).get('idlist', [])
    if not ids:
        return []
    time.sleep(0.45)
    params = urllib.parse.urlencode({'db': 'pubmed', 'id': ','.join(ids), 'retmode': 'json'})
    data = json.loads(fetch('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?' + params))
    result = []
    for pmid in ids:
        x = data.get('result', {}).get(pmid, {})
        title = html.unescape(x.get('title', '')).strip()
        if not title or not related(title):
            continue
        result.append({'pmid': pmid, 'title': title, 'date': x.get('pubdate', '未知'),
                       'journal': x.get('fulljournalname', '未提供'),
                       'url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/'})
    result = result[:PAPER_LIMIT]
    try:
        time.sleep(0.45)
        abstracts = pubmed_abstracts([x['pmid'] for x in result])
        for x in result:
            x['excerpt'] = abstracts.get(x['pmid'], '')
    except (urllib.error.URLError, TimeoutError, ET.ParseError) as exc:
        print('PubMed 摘要拉取失败:', str(exc)[:100], file=sys.stderr)
    return result

def news():
    # Google News RSS 为第三方新闻索引：关键词可能命中正文，必须二次校验标题。
    queries = [
        '"正畸" OR "隐形矫治" OR "错颌畸形"',
        '"正畸" "行业" OR "正畸" "研究"',
        '"orthodontics" OR "clear aligners"',
        '"orthodontic treatment" OR "malocclusion"',
    ]
    result, seen = [], set()
    for q in queries:
        args = urllib.parse.urlencode({'q': q + ' when:7d', 'hl': 'zh-CN', 'gl': 'CN', 'ceid': 'CN:zh-Hans'})
        try:
            root = ET.fromstring(fetch('https://news.google.com/rss/search?' + args))
        except (urllib.error.URLError, TimeoutError, ET.ParseError) as exc:
            print('部分新闻检索失败:', str(exc)[:100], file=sys.stderr)
            continue
        for entry in root.findall('./channel/item')[:25]:
            title = html.unescape(entry.findtext('title', '')).strip()
            url = entry.findtext('link', '').strip()
            if not title or not url or not related(title):
                continue
            key = norm(re.split(r'\s+[-–—]\s+', title)[0])
            if key in seen:
                continue
            seen.add(key)
            d = entry.findtext('pubDate', '')
            try:
                pubdate = email.utils.parsedate_to_datetime(d).astimezone(TZ).strftime('%Y-%m-%d')
            except (TypeError, ValueError):
                pubdate = d or '未提供'
            # Google News RSS 的 description 常仅包含标题+媒体名，不代表文章摘要。
            desc = entry.findtext('description', '')
            excerpt = clean_excerpt(desc, NEWS_EXCERPT_CHARS)
            if norm(title) in norm(excerpt) or len(excerpt) < 35:
                excerpt = ''
            result.append({'title': title, 'url': url, 'date': pubdate, 'excerpt': excerpt})
    result.sort(key=lambda x: (not is_cn(x['title']), -score(x), x['date']), reverse=False)
    return result[:NEWS_LIMIT]

def evidence_hint(title, abstract):
    """只按论文标题和摘要中的研究设计关键词标识，不评价实际证据质量。"""
    t = (title + ' ' + (abstract or '')[:250]).lower()
    if re.search(r'randomi[sz]ed controlled trial|randomi[sz]ed clinical trial', t):
        return '随机对照试验（需核对原文设计）'
    if 'systematic review' in t and 'meta-analysis' in t:
        return '系统综述与Meta分析（需核对纳入质量）'
    if 'systematic review' in t:
        return '系统综述（需核对纳入质量）'
    if 'meta-analysis' in t:
        return 'Meta分析（需核对纳入质量）'
    if 'case report' in t or 'case series' in t:
        return '病例报告/系列（不可外推疗效）'
    if 'in vitro' in t or 'animal' in t or 'cell' in t or 'mice' in t:
        return '基础/实验研究线索（非直接临床证据）'
    return '研究类型未自动确认'


def clinical_note(x):
    """只提供跟进方向，避免将未经审阅的摘要说成临床结论。"""
    label = topic(x['title'])
    hints = {
        '儿童早期矫治与生长改良': '关注年龄分层、骨性变化、对照组及长期稳定性。',
        '隐形矫治与数字化': '关注牙移动预测精度、完成率、复诊与偏倚。',
        '临床机制与治疗技术': '关注研究设计、效应量、风险及临床可推广性。',
        '市场、企业与政策': '关注原始公告、适用范围、商业宣传与独立证据的区别。',
    }
    return hints.get(label, '建议核对研究设计、主要终点和局限。')


def overview(items):
    lines = ['## 🔴 一、今日重要资讯 · 重点速览',
             '> 按相关性筛选；重点是“值得关注”，不等同于证据已证实。']
    if not items:
        lines.append('近7天没有检索到符合筛选要求的行业资讯。')
    for i, x in enumerate(items[:HIGHLIGHT_LIMIT], 1):
        lines.append(f"**🔸 {i:02d}｜{x['title']}**")
        lines.append(f"*{topic(x['title'])} · {x['date']}*")
    return '\n\n'.join(lines)


def format_news(items):
    lines = ['## 🔵 二、正畸行业动态 · 中文优先',
             '> 内容为信息源提供的摘录；未提供摘要时不凭标题杜撰具体报道。']
    if not items:
        lines.append('本期没有检索到符合条件的行业新闻。')
    for i, x in enumerate(items, 1):
        lines.append(f"### 🟦 {i:02d}｜{x['title']}")
        lines.append(f"**领域：** {topic(x['title'])}　|　**日期：** {x['date']}")
        lines.append('**新闻要点：** ' + (x.get('excerpt') or '信息源未开放可验证正文摘录，详情请查看文末来源。'))
    return '\n\n'.join(lines)


def format_papers(items):
    lines = ['## 🟣 三、最新正畸学术文献 · 放在最后',
             '> 每篇摘要最多约260字符（通常4–6行，依手机宽度而异）；标题和摘要保留来源原文，避免错误翻译。']
    if not items:
        lines.append('本期暂无符合条件的论文。')
    for i, x in enumerate(items, 1):
        abstract = x.get('excerpt', '')
        lines.append(f"### 🟪 {i:02d}｜{x['title']}")
        lines.append(f"**研究方向：** {topic(x['title'])}　|　**类型提示：** {evidence_hint(x['title'], abstract)}")
        lines.append(f"**期刊：** {x['journal']}　|　**日期：** {x['date']}")
        lines.append('**研究摘要（节选）：** ' + (abstract or 'PubMed未提供摘要。'))
        lines.append('**临床阅读关注点：** ' + clinical_note(x) + '（非论文结论）')
    return '\n\n'.join(lines)


def reference_list(news_items, paper_items):
    lines = ['## ⚪ 四、参考来源 · 文末集中查看',
             '**新闻来源**']
    lines.extend(f"{i}. [{x['title']}]({x['url']})" for i, x in enumerate(news_items, 1))
    lines.append('**PubMed文献**')
    lines.extend(f"{i}. [{x['title']}]({x['url']})" for i, x in enumerate(paper_items, 1))
    return '\n\n'.join(lines)

def push(title, body):
    key = os.getenv('SERVERCHAN_SENDKEY', '').strip()
    if not key.startswith('SCT'):
        raise RuntimeError('缺少SERVERCHAN_SENDKEY；请检查GitHub Actions Secrets。')
    payload = urllib.parse.urlencode({'title': title, 'desp': body}).encode('utf-8')
    req = urllib.request.Request('https://sctapi.ftqq.com/' + urllib.parse.quote(key, safe='') + '.send',
                                 data=payload, headers={'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as resp:
        ans = json.load(resp)
    if ans.get('code') != 0:
        raise RuntimeError('Server酱接口拒绝：' + str(ans.get('message') or ans.get('code')))
    print('Server酱已接受消息。')

def page_html(today, updates, papers):
    # 静态网页保持来源原文
    esc = lambda v: html.escape(str(v or ''), quote=True)
    title = f'正畸行业每日简报｜{today}'
    cards = []
    for i, item in enumerate(updates, 1):
        excerpt = item.get('excerpt') or '当前新闻源没有提供可核对的正文摘录，建议查看原始报道。'
        cards.append(f'<article class="card"><h3>{i:02d}｜{esc(item["title"])}</h3><div class="meta">{esc(topic(item["title"]))} · {esc(item["date"])}</div><p>{esc(excerpt)}</p><a href="{esc(item["url"])}" target="_blank" rel="noopener noreferrer">原始新闻 ↗</a></article>')
    pcards=[]
    for i,item in enumerate(papers,1):
        abstract=item.get('excerpt') or 'PubMed未提供可用摘要。'
        pcards.append(f'<article class="card"><h3>{i:02d}｜{esc(item["title"])}</h3><div class="meta">{esc(item["journal"])} · {esc(item["date"])}</div><p><b>研究方向：</b>{esc(topic(item["title"]))}</p><p><b>研究类型提示：</b>{esc(evidence_hint(item["title"], abstract))}</p><p class="abstract"><b>摘要节选：</b>{esc(abstract)}</p><p class="clinical"><b>临床阅读关注点：</b>{esc(clinical_note(item))} 此项并非研究结论。</p><a href="{esc(item["url"])}" target="_blank" rel="noopener noreferrer">PubMed原文 ↗</a></article>')
    highlights=''.join(f'<li><b>{i:02d}｜</b>{esc(item["title"])}</li>' for i,item in enumerate(updates[:HIGHLIGHT_LIMIT],1))
    desc=f'正畸行业资讯{len(updates)}条，近7天PubMed文献{len(papers)}篇。中文新闻优先，原始文献置后。'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><meta name="description" content="{esc(desc)}"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:type" content="article"><style>
*{{box-sizing:border-box}}body{{margin:0;background:#eef2f6;color:#283746;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.75}}.page{{max-width:720px;margin:auto;background:white;padding:28px 22px 60px}}h1{{font-size:27px;color:#173d58;line-height:1.35;margin:8px 0}}.sub,.meta{{color:#72828e;font-size:12px}}.eyebrow{{font-size:12px;color:#197c90;font-weight:700;letter-spacing:2px}}.intro{{margin-top:18px;background:#eaf4fa;border-left:4px solid #2e8aa6;padding:13px;border-radius:5px;font-size:14px}}h2{{font-size:19px;color:#195d78;border-bottom:2px solid #e2ebf0;padding-bottom:8px;margin-top:34px}}.news h2{{color:#a85b1d;border-color:#f4e3d5}}.papers h2{{color:#7151a2;border-color:#e9e0f4}}.card{{padding:16px 0;border-bottom:1px solid #edf1f4}}.card h3{{font-size:17px;color:#ad581f;line-height:1.55;margin:0 0 7px}}.papers h3{{color:#67499a}}.card p{{font-size:14px;margin:8px 0}}.abstract,.clinical{{background:#f5f7fa;padding:9px 12px;border-radius:5px}}.abstract{{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:6;overflow:hidden}}a{{color:#1477a0;word-break:break-word}}ol{{padding-left:22px}}li{{margin:8px 0}}.note{{margin-top:25px;color:#77633d;background:#fff9e9;font-size:12px;padding:12px;border-radius:6px}}.footer{{margin-top:28px;font-size:13px}}
</style></head><body><main class="page"><div class="eyebrow">ORTHODONTICS DAILY</div><h1>🦷 正畸行业每日简报</h1><div class="sub">{esc(today)} · 中文重点 · 适合微信转发</div><div class="intro"><b>今日导读</b><br>{esc(desc)}<br>直接阅读正文；点击各条目可核对原始来源。</div><h2>🔴 一、重点速览</h2><ol>{highlights or '<li>暂无符合筛选条件的行业新闻。</li>'}</ol><section class="news"><h2>📰 二、国内外行业动态</h2>{''.join(cards) or '<p>本期暂无符合筛选要求的新闻。</p>'}</section><section class="papers"><h2>📚 三、最新学术文献（文末）</h2><p class="sub">摘要限制约260字符，并按手机显示限制在6行左右。</p>{''.join(pcards) or '<p>本期暂无符合筛选条件的论文。</p>'}</section><p class="note">自动检索版：未使用付费AI，不对英文论文自动生成中文研究结论。新闻摘录与PubMed摘要均来自第三方数据源，请以原文为准。研究类型和临床关注点为规则提示，并非证据质量评价。</p><div class="footer"><a href="./archive.html">历史简报索引 ↗</a></div></main></body></html>'''

def save_pages(today, updates, papers):
    from pathlib import Path
    archive = Path('archive')
    archive.mkdir(exist_ok=True)
    page = page_html(today, updates, papers)
    # 历史归档页的相对链接需指回上一层；当天首页直接显示最新日报
    (archive / f'{today}.html').write_text(page.replace('href="./archive.html"', 'href="../archive.html"'), encoding='utf-8')
    Path('index.html').write_text(page, encoding='utf-8')
    dates = sorted((x.stem for x in archive.glob('????-??-??.html')), reverse=True)
    links=''.join(f'<li><a href="archive/{d}.html">正畸行业每日简报｜{d}</a></li>' for d in dates)
    Path('archive.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>正畸简报历史归档</title><style>body{font-family:Arial,"PingFang SC",sans-serif;margin:32px auto;padding:0 20px;max-width:680px;line-height:2}a{color:#176e99}</style><h1>正畸行业每日简报·历史归档</h1><a href="index.html">返回最新一期</a><ul>'+links+'</ul></html>', encoding='utf-8')
    Path('.nojekyll').touch()

def main():
    today = dt.datetime.now(TZ).strftime('%Y-%m-%d')
    results, errors = {}, []
    for name, fn in [('新闻', news), ('PubMed', pubmed)]:
        try:
            results[name] = fn()
        except (urllib.error.URLError, TimeoutError, ValueError, ET.ParseError, KeyError) as exc:
            results[name] = []
            errors.append(name + '失败：' + str(exc)[:110])
    updates, papers = results['新闻'], results['PubMed']
    if not (updates or papers):
        raise RuntimeError('新闻与文献均未检索到，不生成空简报。' + '; '.join(errors))
    save_pages(today, updates, papers)
    repo=os.getenv('GITHUB_REPOSITORY','').strip()
    if repo:
        page_url='https://' + repo.split('/')[0].lower() + '.github.io/' + repo.split('/')[-1] + '/'
    else:
        page_url='（本地预览不提供链接）'
    title=f'🦷 正畸行业每日简报｜{today}'
    body=f'**今日简报已生成**\n\n📰 行业资讯：{len(updates)}条\n\n📚 相关学术文献：{len(papers)}篇\n\n**[点击阅读完整中文重点简报]({page_url})**\n\n网页可转发给微信好友，支持历史归档。'
    print('新闻:',len(updates),'论文:',len(papers),'网页:',page_url)
    if os.getenv('SERVERCHAN_SENDKEY'):
        push(title, body)
    else:
        print('未配置SERVERCHAN_SENDKEY，跳过微信推送；仅生成网页。')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('运行失败：'+str(exc), file=sys.stderr)
        sys.exit(1)
