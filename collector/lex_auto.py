"""Rules of the Lex Auto channel: raw posts -> cars, upcoming cars and posts that need a human.

A car goes through the channel like this:
  teaser ("Далее в программе", hero photo) -> video notes -> "АВТОТЕКА" post with the price
  -> album without text -> listing ("Зазор", album) -> "СТОП! ЗАДАТОК", often a reply to the album.
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from build_data import NO_BARGAIN_GAP, clean, money, paint_map, parse  # same text rules as the first import

CHANNEL = 'lexautospb13'
SELLER = 'lex-auto'
KEEP_DAYS = 14
MAX_GALLERY = 21
TEASER = re.compile(r'Далее в программе|Первая на сегодня|ВНИМАНИЕ АНОНС')
STOP = re.compile(r'СТОП\W*ЗАДАТОК')
AUTOTEKA = re.compile(r'АВТОТЕКА\s+([А-ЯЁA-Z0-9]+(?:\s+[А-ЯЁA-Z0-9]+)?)')
PROMO = re.compile(r'приз|розыгр|наклейк|Доброе утро|Условия|стикер|MacBook|iPhone|обучени|курс', re.I)
NOTE = re.compile(r'кузов|мотор|окрас|салон|автомат|подвеск|DSG|вариатор', re.I)
YEAR = re.compile(r'(19|20)\d\d')
LISTING = re.compile(r'Зазор|цена всего|Старт рынка')
STOP_WINDOW = timedelta(hours=12)


def is_listing(p):
    """Most listings open with "Зазор", some with free text, so look at the whole post."""
    return len(p['photos']) >= 2 and len(p['text']) > 300 and bool(LISTING.search(p['text']))


def span(p):
    """Telegram gives an album one post, its photos take the following ids."""
    return range(p['id'], p['id'] + max(len(p['photos']), 1))


def stem(s):
    return s.split()[0][:3] if s else ''


def price_of(post):
    return money(post['text'].split('цена всего')[-1])


def problem(d, announced=None):
    if not d.get('price') or not 50_000 <= d['price'] <= 50_000_000:
        return 'нет цены'
    if announced and announced != d['price']:
        return f"цена {d['price']} не совпадает с постом Автотеки {announced}"
    if not 1985 <= d.get('year', 0) <= datetime.now().year + 1:
        return 'нет года'
    if not d.get('make') or not d.get('model'):
        return 'нет марки или модели'
    return None


def link_posts(posts, ids, k, floor):
    """Teaser, price post, the text-less album and notes between the previous listing and this one."""
    between = [j for j in ids if floor < j < k]
    teaser = next((j for j in reversed(between) if TEASER.search(posts[j]['text'])), None)
    own = [j for j in between if teaser is None or j >= teaser]
    autoteka = next((j for j in reversed(own) if AUTOTEKA.search(posts[j]['text'])), None)
    albums = [j for j in own if not posts[j]['text'] and len(posts[j]['photos']) >= 2]
    notes = []
    for j in own:
        t = posts[j]['text']
        if j in (teaser, autoteka) or PROMO.search(t) or not NOTE.search(t) or len(t) >= 600:
            continue
        for para in re.split(r'\n\s*\n', t):
            c = clean(para.replace('\n', ' '))
            if len(c) > 15:
                notes.append(c + ('' if c.endswith(('!', '?', '.')) else '.'))
    tg = [j for j in own + [k] if not PROMO.search(posts[j]['text']) and not STOP.search(posts[j]['text'])]
    return teaser, autoteka, albums, notes[:6], tg


def stops(posts, ids, listings):
    """Listing id -> post that took the car off sale."""
    out = {}
    for j in ids:
        if not STOP.search(posts[j]['text']) or 'ВТОРОЙ' in posts[j]['text']:
            continue
        before = [k for k in listings if k < j]
        if not before:
            continue
        reply = posts[j].get('reply_to')
        word = stem(re.sub(r'[^А-ЯЁA-Z0-9 ]', '', posts[j]['text']).strip())
        if reply:
            # a reply names the car exactly; its listing may be older than what we keep
            target = next((k for k in before if reply in listings[k]['range']), None)
        else:
            at = datetime.fromisoformat(posts[j]['date'])
            recent = [k for k in before if at - datetime.fromisoformat(posts[k]['date']) <= STOP_WINDOW]
            target = next((k for k in reversed(recent) if word and listings[k]['nick'] == word), before[-1])
        if target:
            out.setdefault(target, j)
    return out


def build(posts):
    """-> cars, upcoming, review. Nothing here touches the network."""
    ids = sorted(posts)
    keys = [k for k in ids if is_listing(posts[k])]
    listings, cars, review = {}, [], []
    for n, k in enumerate(keys):
        floor = keys[n - 1] if n else 0
        teaser, autoteka, albums, notes, tg = link_posts(posts, ids, k, floor)
        rng = set(span(posts[k])) | set(tg)
        for j in albums:
            rng.update(span(posts[j]))
        nick = AUTOTEKA.search(posts[autoteka]['text']).group(1) if autoteka else ''
        listings[k] = {'range': rng, 'nick': stem(nick)}
        try:
            d = parse(posts[k])
        except Exception as e:
            review.append({'id': k, 'why': f'не разобрался: {e}', 'text': posts[k]['text'][:200]})
            continue
        why = problem(d, price_of(posts[autoteka]) if autoteka else None)
        if why:
            review.append({'id': k, 'why': why, 'text': posts[k]['text'][:200]})
            continue
        slug = re.sub(r'[^a-z0-9]+', '-', f"{d['make']} {d['model']} {d['year']}".lower()).strip('-')
        d.update(slug=f'{slug}-{k}', seller=SELLER, status='active', notes=notes, tg_posts=tg, proof=[],
                 bargain=(d['gap'] or 0) < NO_BARGAIN_GAP)
        d['paint'], d['painted_count'] = paint_map(d)
        photos = (posts[teaser]['photos'][:1] if teaser else []) + posts[k]['photos']
        for j in albums:
            photos += posts[j]['photos']
        d['_photos'] = photos[:MAX_GALLERY]
        d['_reports'] = posts[autoteka]['photos'][:1] if autoteka else []
        cars.append(d)
    gone = stops(posts, ids, listings)
    for d in cars:
        if d['id'] in gone:
            d['status'] = 'reserved'
            d['reserved_at'] = posts[gone[d['id']]]['date']
    return cars, upcoming(posts, ids, keys), review


def upcoming(posts, ids, keys):
    """Teasers whose listing is not out yet. Cars go to deposit minutes after the listing, this is the head start."""
    last = keys[-1] if keys else 0
    now = datetime.now(timezone.utc)
    out = []
    for j in ids:
        p = posts[j]
        if j < last or not TEASER.search(p['text']) or not p['photos'] or not p['date']:
            continue
        later = [i for i in ids if i > j]
        if any('втором канале' in posts[i]['text'] for i in later[:2]):  # sold on the seller's other channel
            continue
        if now - datetime.fromisoformat(p['date']) > timedelta(hours=12):
            continue
        lines = [clean(l) for l in p['text'].split('\n') if l.strip()]
        ti = next((i for i, l in enumerate(lines) if YEAR.search(l)), None)
        if ti is None:
            continue
        price = next((price_of(posts[i]) for i in later if AUTOTEKA.search(posts[i]['text'])), None)
        out.append({'title': lines[ti], 'price': price, 'avito': None, 'specs': lines[ti + 1:ti + 4],
                    'note': '', 'source': f'https://t.me/{CHANNEL}/{j}', '_photo': p['photos'][0], 'id': j,
                    'date': p['date']})
    return out
