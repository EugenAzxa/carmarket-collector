"""Rules of the board channel "НИЖЕ РЫНКА СПБ": strangers' cars in free text.

Sellers here are private people, so their phones and names never leave this file. On the site
a car is one card that opens its post in the channel. A post we are not sure about stays out.
"""
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from build_data import BODY, HIST, TECH, clean, paint_map

from lex_auto import STOP

CHANNEL = 'nizherinkaspb1'
SELLER = 'nizherinka'
KEEP_DAYS = 4  # no "sold" signal for most posts, so old ones leave the site
STOP_MINUTES = 60

PRIVATE = re.compile(r'(?:\d[\s()+.\-]*){10,}|@\w+')
SERVICE = re.compile(r'от Л[её]хи|Л[её]хе|закин|пацанам|Привет|Бронь|развити|АВТОТЕКА|Автотека выше|^В продаже\s*$'
                     r'|Зазор|Задор|Старт в поколении|^☝|^⚡|[Цц]ен[аеу]|Внимание|^\s*\d[\d\s.,]*\s*(?:₽|к|р)?\s*$', re.I)
BRANDS = [(r'Mercedes(?:-Benz)?|Мерседес', 'Mercedes'), (r'BMW|БМВ', 'BMW'), (r'Audi|Ауди', 'Audi'),
          (r'Volkswagen|VW|Фольксваген', 'Volkswagen'), (r'Skoda|Шкода', 'Skoda'), (r'Toyota|Тойота', 'Toyota'),
          (r'Lexus|Лексус', 'Lexus'), (r'Nissan|Ниссан', 'Nissan'), (r'Mazda|Мазда', 'Mazda'), (r'Honda|Хонда', 'Honda'),
          (r'Mitsubishi|Мицубиси|Митсубиши', 'Mitsubishi'), (r'Subaru|Субару', 'Subaru'), (r'Suzuki|Сузуки', 'Suzuki'),
          (r'Hyundai|Хендай|Хундай', 'Hyundai'), (r'Kia|Киа', 'Kia'), (r'Chevrolet|Шевроле', 'Chevrolet'),
          (r'Ford|Форд', 'Ford'), (r'Opel|Опель', 'Opel'), (r'Renault|Рено', 'Renault'), (r'Peugeot|Пежо', 'Peugeot'),
          (r'Citroen|Ситроен', 'Citroen'), (r'Volvo|Вольво', 'Volvo'), (r'Lada|Лада|ВАЗ', 'Lada'), (r'Land Rover', 'Land Rover'),
          (r'Geely|Джили', 'Geely'), (r'Chery|Чери', 'Chery'), (r'Haval|Хавейл', 'Haval'), (r'Infiniti|Инфинити', 'Infiniti'),
          (r'Daewoo|Дэу', 'Daewoo'), (r'Porsche|Порше', 'Porsche'), (r'Jeep|Джип', 'Jeep'), (r'Mini', 'Mini')]
MODELS = {'соната': ('Hyundai', 'Sonata'), 'солярис': ('Hyundai', 'Solaris'), 'лансер': ('Mitsubishi', 'Lancer'),
          'фокус': ('Ford', 'Focus'), 'логан': ('Renault', 'Logan'), 'дастер': ('Renault', 'Duster'),
          'камри': ('Toyota', 'Camry'), 'королла': ('Toyota', 'Corolla'), 'октавия': ('Skoda', 'Octavia'),
          'поло': ('Volkswagen', 'Polo'), 'гранта': ('Lada', 'Granta'), 'приора': ('Lada', 'Priora'), 'веста': ('Lada', 'Vesta')}
CUT = re.compile(r"\s*(?:,|\(|\b(?:19|20)\d\d|\b\d\.\d\b|\b\d\d\s*год|\bгод\b|\bг\.|\bконец\b|\bрест|\bлет\b).*$", re.I)


def is_listing(p):
    return len(p['photos']) >= 2 and len(p['text']) > 150 and bool(re.search(r'от Л[её]хи|цена всего', p['text']))


def number(s, unit=''):
    """"260.000", "890", "1,1" + a unit -> rubles. Sellers often drop the thousands."""
    s = s.strip().rstrip('.,')
    if unit == '🍋':
        return round(float(s.replace(',', '.')) * 1_000_000)
    v = int(re.sub(r'\D', '', s) or 0)
    return v * 1000 if v < 5000 else v


def price_of(lines):
    for l in reversed(lines):
        if PRIVATE.search(l) or re.search(r'Зазор|Задор|Старт|\+', l):
            continue
        m = (re.search(r'(\d+[.,]?\d*)\s*(🍋)', l)
             or re.search(r'[Цц]ен[аеу][^\d\n]*(\d[\d\s.]*)\s*(к|₽|р|руб)?', l)
             or re.match(r'^\W*(\d[\d\s.]*)\s*(к|₽|р|руб)?\W*(?:,.*)?$', l))
        if m and not (not m.group(2) and re.fullmatch(r'(?:19|20)\d\d', m.group(1).strip())):  # a bare year is not a price
            return number(m.group(1), m.group(2) or '')
    return None


def year_of(body):
    t = '\n'.join(body[:6])
    m = re.search(r'(?<![\d.])((?:19[89]|20[012])\d)(?![\d.])', t)
    if m:
        return int(m.group(1))
    m = re.search(r'\b(\d\d)\s*год', t)
    return 2000 + int(m.group(1)) if m and int(m.group(1)) <= datetime.now().year - 2000 else None


def tidy(model):
    words = [w.capitalize() if w.isupper() and len(w) > 3 else w for w in model.split()[:2]]
    words = [w.capitalize() if re.match('[а-яё]', w) else w for w in words]
    return ' '.join(words).strip(' -:,.!')


def name_of(body):
    for l in body[:5]:
        s = clean(re.sub(r'[🚘☑️✅«»]', ' ', l))
        for pat, make in BRANDS:
            m = re.search(rf'(?<![\wа-яА-Я])(?:{pat})(?![\wа-яА-Я])', s, re.I)
            if m:
                return make, tidy(CUT.sub('', s[m.end():]))
        for word, pair in MODELS.items():
            if word in s.lower():
                return pair
    return None, None


def mileage_of(text):
    for pat in (r'(?:на щитке|на приборке|щиток|пробега?)[^\d\n]{0,14}(\d[\d\s.]*)\s*(к|тыс)?', r'(\d{2,3}[\s.]?\d{3})\s*км'):
        m = re.search(pat, text, re.I)
        if m:
            v = number(m.group(1))
            if 1_000 <= v <= 900_000:
                return v
    return None


def gearbox_of(t):
    if re.search(r'dsg', t, re.I): return 'DSG'
    if re.search(r'вариатор|cvt', t, re.I): return 'Вариатор'
    if re.search(r'робот', t, re.I): return 'Робот'
    if re.search(r'механик|\bМТ\b|\d\.\dМТ|МКПП', t): return 'Механика'
    if re.search(r'автомат|\bАТ\b|АКПП', t, re.I): return 'Автомат'
    return None


def car(p):
    """-> car dict or the reason why not."""
    lines = [l.strip() for l in p['text'].split('\n') if l.strip()]
    public = [l for l in lines if not PRIVATE.search(l)]
    body = [l for l in public if not SERVICE.search(l)]
    text = '\n'.join(public)
    specs = '\n'.join(body)  # the head line brags about other cars: "с пробегом до 200к"
    make, model = name_of(body)
    year, price = year_of(body), price_of(lines)
    if not make or not model:
        return 'нет марки или модели'
    if not year:
        return 'нет года'
    if not price or not 30_000 <= price <= 50_000_000:
        return 'нет цены'
    gap = re.search(r'За[зд]ор\s*(\d+)к', lines[0])
    start = re.search(r'Старт в поколении\s*-\s*(\d+)к', lines[0])
    vol = re.search(r'(?<![\d.])(\d\.\d)(?![\d.])', text)
    hp = re.search(r'(\d{2,3})\s*(?:л\.?\s?с|лошад)', text, re.I)
    owners = re.search(r'(\d)\s*(?:влад|хоз)', text, re.I)
    groups = {'body': [], 'tech': [], 'history': [], 'equipment': []}
    for l in body:
        c = clean(l)
        if len(c) < 6 or c.lower().startswith(make.lower()):
            continue
        key = 'tech' if TECH.search(c) else 'body' if BODY.search(c) else 'history' if HIST.search(c) else 'equipment'
        groups[key].append(c)
    slug = re.sub(r'[^a-z0-9]+', '-', f'{make} {model} {year}'.lower()).strip('-') or 'car'
    d = {'id': p['id'], 'gap': int(gap.group(1)) * 1000 if gap else None, 'year': year, 'make': make, 'model': model,
         'restyle': bool(re.search(r'рест', text, re.I)), 'engine_line': '', 'volume': vol.group(1) if vol else None,
         'hp': int(hp.group(1)) if hp else None, 'fuel': 'Дизель' if re.search('дизел', text, re.I) else 'Бензин',
         'gearbox': gearbox_of(text), 'awd': bool(re.search(r'полный привод|4х4|4wd|quattro', text, re.I)),
         'owners': int(owners.group(1)) if owners else None, 'pts': False, 'keys2': False, 'not_taxi': False,
         'not_on_avito': False, 'no_accidents': False, 'direct_owner': False, 'mileage': mileage_of(specs),
         'mileage_base': None, 'autoteka': None, 'market': int(start.group(1)) * 1000 if start else None, 'avito': None,
         'price': price, 'groups': groups, 'views': p['views'], 'date': p['date'],
         'source': f"https://t.me/{CHANNEL}/{p['id']}", 'slug': f"{slug}-{p['id']}", 'seller': SELLER, 'status': 'active',
         'via_channel': True, 'bargain': False, 'notes': [], 'tg_posts': [p['id']], 'proof': []}
    if d['market'] and not d['gap'] and d['market'] > price:
        d['gap'] = d['market'] - price
    d['paint'], d['painted_count'] = paint_map(d)
    return d


def build(posts):
    """-> cars, upcoming, review. Review keeps only the reason and a post link, no seller text."""
    ids = sorted(posts)
    keys = [k for k in ids if is_listing(posts[k])]
    cars, review = [], []
    for k in keys:
        try:
            d = car(posts[k])
        except Exception as e:
            d = f'не разобрался: {e}'
        if isinstance(d, str):
            review.append({'id': k, 'why': d, 'text': f'https://t.me/{CHANNEL}/{k}'})
            continue
        d['_photos'], d['_reports'] = posts[k]['photos'][:1], []  # a card needs one photo, the rest stays in the post
        cars.append(d)
    newest = {(d['make'], d['model'], d['year'], d['price']): d for d in cars}  # the same car gets reposted
    cars = list(newest.values())
    by_id = {d['id']: d for d in cars}
    for j in ids:
        if not STOP.search(posts[j]['text']) or 'ВТОРОЙ' in posts[j]['text']:
            continue
        before = [k for k in keys if k < j]
        if not before or before[-1] not in by_id:
            continue
        k = before[-1]
        at, listed = (datetime.fromisoformat(posts[x]['date']) for x in (j, k))
        if (at - listed).total_seconds() <= STOP_MINUTES * 60:
            by_id[k]['status'] = 'reserved'
            by_id[k]['reserved_at'] = posts[j]['date']
    return cars, [], review
