"""Reseller channels written in free text (since 13.11.2026): AMSTEPDAM, АвтоБутик74, DESHMAN_AUTO, EVGEN AVTO.

One rule set, small differences per channel in SOURCES at the bottom. Like the board channel, a car
here is one card that opens its post: phones, VIN, addresses and names never leave this file.

A listing is a post with a car name and a price. The price may come later in the "бронируй"
post under the review video. Short posts "Гранта бронь" / "Киа продана" set the status of the
latest listing with that name. A post we are not sure about goes to review, not to the site.
"""
import os
import re
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from build_data import BODY, HIST, TECH, clean, paint_map

import nizherinka as nz

UNIT = r'(к|тыс|млн|🍋|₽|р)?'
NUM = r'(\d[\d\s.,]*\d|\d)'
PRICE = [re.compile(p, re.I | re.S) for p in (
    r'(?:мо[яю]|наш[аеу])\s+цен[аеу][^\d]{0,40}?' + NUM + r'\s*' + UNIT,
    r'(?<![а-яё])цен(?:[аеу]|ник)(?![а-яё])[^\d]{0,40}?' + NUM + r'\s*' + UNIT,
    r'(?<![\wа-яё])за\s+' + NUM + r'\s*' + UNIT + r'(?![\wа-яё])',
)]
MARKET = re.compile(r'(?:рын(?:ок|очн\w*)|оценк\w*|стоимост\w*|старт цен\w*)[^\d\n]{0,30}' + NUM + r'\s*' + UNIT, re.I)
MARKET_LINE = re.compile(r'рын(?:ок|очн)|оценк|стоимост|старт цен|запас|зазор', re.I)
FOLLOW = re.compile(r'брониру', re.I)          # "бронируй", "Бронируем": the post under the review video
RESERVED = re.compile(r'(?<![а-яё])(?:бронь|в брони|забронир\w+)(?![а-яё])', re.I)
SOLD = re.compile(r'(?<![а-яё])продан[аыо]?(?![а-яё])', re.I)
HIDDEN = re.compile(r'\bVIN\b|\b[A-HJ-NPR-Z0-9]{17}\b|\bул\.|улиц|адрес|☎|📲|звонк|t\.me/|https?://|кредит', re.I)
CITY = re.compile(r'\bг\.\s?[А-ЯЁ][а-яё]')  # "г.Казань", case matters: "2013г.в" is a year
PROMO = re.compile(r'розыгр|Условия максимально|подписан\w* на наши каналы|курс', re.I)
RU_MODELS = {'круз': 'Cruze', 'лачетти': 'Lacetti', 'авео': 'Aveo', 'солярис': 'Solaris', 'рио': 'Rio', 'поло': 'Polo',
             'фокус': 'Focus', 'октавия': 'Octavia', 'камри': 'Camry', 'королла': 'Corolla', 'ланцер': 'Lancer',
             'аутлендер': 'Outlander', 'спектра': 'Spectra', 'церато': 'Cerato', 'спортейдж': 'Sportage', 'туссан': 'Tucson',
             'крета': 'Creta', 'элантра': 'Elantra', 'джетта': 'Jetta', 'пассат': 'Passat', 'тигуан': 'Tiguan', 'логан': 'Logan',
             'дастер': 'Duster', 'сандеро': 'Sandero', 'меган': 'Megane', 'астра': 'Astra', 'корса': 'Corsa', 'мондео': 'Mondeo',
             'кашкай': 'Qashqai', 'альмера': 'Almera', 'теана': 'Teana', 'тиида': 'Tiida', 'нексия': 'Nexia', 'матиз': 'Matiz'}
LADA = re.compile(r'granta|гранта|vesta|веста|priora|приора|kalina|калина|largus|ларгус|xray|niva|нива|4x4', re.I)
MODEL_ONLY = {  # the brand is often left out: "LANCER 2005 г.в", "Escalade за 2.250"
    'lancer': ('Mitsubishi', 'Lancer'), 'pajero': ('Mitsubishi', 'Pajero'), 'outlander': ('Mitsubishi', 'Outlander'),
    'escalade': ('Cadillac', 'Escalade'), 'land cruiser': ('Toyota', 'Land Cruiser'), 'camry': ('Toyota', 'Camry'),
    'corolla': ('Toyota', 'Corolla'), 'rav4': ('Toyota', 'RAV4'), 'solaris': ('Hyundai', 'Solaris'),
    'creta': ('Hyundai', 'Creta'), 'rio': ('Kia', 'Rio'), 'polo': ('Volkswagen', 'Polo'), 'octavia': ('Skoda', 'Octavia'),
    'focus': ('Ford', 'Focus'), 'logan': ('Renault', 'Logan'), 'duster': ('Renault', 'Duster'),
    'granta': ('Lada', 'Granta'), 'vesta': ('Lada', 'Vesta'), 'priora': ('Lada', 'Priora'),
    'ланцер': ('Mitsubishi', 'Lancer'), 'паджеро': ('Mitsubishi', 'Pajero'), 'крузак': ('Toyota', 'Land Cruiser'),
    'гелик': ('Mercedes', 'G-Класс'), 'кольт': ('Mitsubishi', 'Colt'),
}
MORE_BRANDS = [(r'Cadillac|Кадиллак', 'Cadillac'), (r'Genesis', 'Genesis'), (r'Exeed', 'Exeed'), (r'Changan', 'Changan'),
               (r'Omoda', 'Omoda'), (r'Tank', 'Tank'), (r'Datsun|Датсун', 'Datsun'), (r'УАЗ|UAZ', 'УАЗ'),
               (r'Chrysler', 'Chrysler'), (r'Dodge', 'Dodge'), (r'Smart', 'Smart'), (r'Acura', 'Acura')]
TRANS = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',
                 ['a', 'b', 'v', 'g', 'd', 'e', 'e', 'zh', 'z', 'i', 'i', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's', 't', 'u', 'f',
                  'h', 'ts', 'ch', 'sh', 'sch', '', 'y', '', 'e', 'yu', 'ya']))


def rub(s, unit=''):
    """"209.900к", "1.199.999", "1.5🍋", "2.250", "350" -> rubles. Sellers drop the thousands."""
    s, unit = s.strip(' .,'), (unit or '').lower()
    if unit in ('млн', '🍋') and re.fullmatch(r'\d{1,2}(?:[.,]\d{1,3})?', s):
        return round(float(s.replace(',', '.')) * 1_000_000)
    v = int(re.sub(r'\D', '', s) or 0)
    return v * 1000 if v < 10_000 else v


def price_of(text):
    """Asking price, not the market: lines about the market are left out first."""
    t = '\n'.join(l for l in text.split('\n') if not MARKET_LINE.search(l))
    for rx in PRICE:
        for m in rx.finditer(t):
            v = rub(m.group(1), m.group(2))
            if 50_000 <= v <= 50_000_000:
                return v
    return None


def market_of(text):
    for m in MARKET.finditer(text):
        v = rub(m.group(1), m.group(2))
        if 50_000 <= v <= 60_000_000:
            return v
    return None


def follow_price(text):
    for m in re.finditer(NUM + r'\s*' + UNIT, text):
        v = rub(m.group(1), m.group(2))
        if 50_000 <= v <= 50_000_000:
            return v
    return None


def name_of(lines):
    lines = [re.sub(r'\((?:LADA|ЛАДА|ВАЗ)\)', ' ', l, flags=re.I) for l in lines[:10]]
    for l in lines:
        s = clean(re.sub(r'[🚘☑️✅«»🏎🔥💥]', ' ', l))
        for pat, make in nz.BRANDS + MORE_BRANDS:
            m = re.search(rf'(?<![\wа-яА-Я])(?:{pat})(?![\wа-яА-Я])', s, re.I)
            if m:
                model = nz.tidy(nz.CUT.sub('', s[m.end():]))
                if make == 'Lada' and LADA.search(s):
                    model = LADA.search(s).group(0).capitalize().replace('Гранта', 'Granta').replace('Веста', 'Vesta')
                model = re.sub(r'(?i)^([a-z])\s*-?\s*kla(?:ss|sse)\b', lambda x: x.group(1).upper() + '-класс', model.split('!')[0])
                model = re.sub(r'\s+\d\.\d\w*.*$', '', model).strip(' -:,.!')
                model = RU_MODELS.get(model.lower(), model)
                if re.search(r'[A-Za-z0-9]', model):  # "X3 кузове F25" -> "X3"
                    model = ' '.join(w for w in model.split() if not re.search(r'[а-яёА-ЯЁ]', w) or w.endswith('-класс'))
                model = ' '.join(w.upper() if re.search(r'\d', w) and len(w) <= 6 else w for w in model.split())
                if model:
                    return make, model
        low = s.lower()
        for word, pair in {**MODEL_ONLY, **nz.MODELS}.items():
            if re.search(rf'(?<![\wа-яё]){word}', low):
                return pair
    return None, None


def year_of(lines):
    for l in lines[:12]:
        m = re.search(r'(?<![\d.,])((?:19[89]|20[0-2])\d)(?![\d.,])', l)
        if m and int(m.group(1)) <= datetime.now().year:
            return int(m.group(1))
        m = re.search(r'(?<![\d.,])(\d\d)\s*г(?:\.|од|\b)', l)  # "94г", "08 год"
        if m:
            y = int(m.group(1))
            y += 2000 if y <= datetime.now().year - 2000 else 1900
            if y >= 1980:
                return y
    return None


def key(word):
    """Rough sound of a word in Latin letters, so "Кольт" meets "Colt" and "спектра" meets "Spectra"."""
    w = ''.join(TRANS.get(c, c) for c in word.lower())
    w = w.replace('ts', 'k').replace('c', 'k').replace('w', 'v').replace('y', 'i').replace('ph', 'f')
    return re.sub(r'(.)\1+', r'\1', re.sub(r'[^a-z0-9]', '', w))


def same_car(text, d):
    words = {key(w)[:4] for w in re.findall(r'[A-Za-zА-Яа-яЁё]{3,}', text)} - {'', 'bron', 'prod', 'pozd', 'avto'}
    names = {key(w)[:4] for w in re.findall(r'[A-Za-zА-Яа-яЁё0-9]{2,}', f"{d['make']} {d['model']}")}
    nick = {key(k)[:4] for k, v in MODEL_ONLY.items() if v == (d['make'], d['model'])}
    return bool(words & (names | nick))


def car(p, cfg, photo):
    lines = [l.strip() for l in p['text'].split('\n') if l.strip()]
    public = [l for l in lines if not nz.PRIVATE.search(l) and not HIDDEN.search(l) and not CITY.search(l)]
    text = '\n'.join(public)
    make, model = name_of(public)
    if not make or not model:
        return 'нет марки или модели'
    year = year_of(public)
    if not year and not cfg.year_optional:
        return 'нет года'
    price = price_of(p['text'])
    vol = re.search(r'(?<![\d.])(\d\.\d)(?![\d.])', text)
    hp = re.search(r'(\d{2,3})\s*(?:л\.?\s?с|сил|лошад)', text, re.I)
    owners = re.search(r'(\d)\s*(?:влад|хоз|вл\b)', text, re.I)
    groups = {'body': [], 'tech': [], 'history': [], 'equipment': []}
    for l in public:
        c = clean(l)
        if len(c) < 6 or MARKET_LINE.search(c) or price_of(c) or c.lower().startswith(make.lower()):
            continue
        k = 'tech' if TECH.search(c) else 'body' if BODY.search(c) else 'history' if HIST.search(c) else 'equipment'
        groups[k].append(c)
    slug = re.sub(r'[^a-z0-9]+', '-', f"{make} {model} {year or ''}".lower()).strip('-') or 'car'
    d = {'id': p['id'], 'gap': None, 'year': year, 'make': make, 'model': model,
         'restyle': bool(re.search(r'рест', text, re.I)), 'engine_line': '', 'volume': vol.group(1) if vol else None,
         'hp': int(hp.group(1)) if hp else None, 'fuel': 'Дизель' if re.search(r'дизел|diesel', text, re.I) else 'Бензин',
         'gearbox': nz.gearbox_of(text), 'awd': bool(re.search(r'полный привод|4х4|4wd|quattro|4matic|xdrive', text, re.I)),
         'owners': int(owners.group(1)) if owners else None, 'pts': False, 'keys2': bool(re.search(r'2 ключа|два ключа', text, re.I)),
         'not_taxi': bool(re.search(r'не такси|без (?:отметок )?такси', text, re.I)), 'not_on_avito': False,
         'no_accidents': bool(re.search(r'без дтп|в дтп (?:никогда )?не', text, re.I)), 'direct_owner': False,
         'mileage': nz.mileage_of(text), 'mileage_base': None, 'autoteka': None, 'market': market_of(text), 'avito': None,
         'price': price, 'groups': groups, 'views': p['views'], 'date': p['date'],
         'source': f"https://t.me/{cfg.CHANNEL}/{p['id']}", 'slug': f"{slug}-{cfg.SELLER}-{p['id']}", 'seller': cfg.SELLER,
         'status': 'active', 'via_channel': True, 'bargain': False, 'notes': [], 'tg_posts': [p['id']], 'proof': [],
         '_photos': [photo], '_reports': []}
    return d


def photo_of(posts, ids, i, floor):
    """Own photo, else an album sent just before the text (DESHMAN), else the video cover."""
    p = posts[ids[i]]
    if p['photos']:
        return p['photos'][0]
    at = datetime.fromisoformat(p['date'])
    album = [posts[j] for j in ids[:i] if j > floor and posts[j]['photos'] and not posts[j]['text'].strip()
             and abs((at - datetime.fromisoformat(posts[j]['date'])).total_seconds()) <= 300]
    if album:
        return album[0]['photos'][0]
    return (p.get('thumbs') or [None])[0]


def build(posts, cfg):
    """-> cars, upcoming, review. Review keeps only the reason and a post link, no seller text."""
    ids = sorted(posts)
    cars, review, floor = [], [], 0
    for i, k in enumerate(ids):
        p = posts[k]
        if len(p['text']) < cfg.min_text or FOLLOW.search(p['text'][:80]) and len(p['text']) < 400 or PROMO.search(p['text']):
            continue
        photo = photo_of(posts, ids, i, floor)
        d = car(p, cfg, photo)
        if isinstance(d, str):
            if d != 'нет марки или модели' and (photo or p['video']):
                review.append({'id': k, 'why': d, 'text': f"https://t.me/{cfg.CHANNEL}/{k}"})
            continue
        if not d['price']:  # the price comes in the post under the video: "229.990ккк бронируй"
            at = datetime.fromisoformat(p['date'])
            for j in ids[i + 1:]:
                q = posts[j]
                if datetime.fromisoformat(q['date']) - at > timedelta(hours=12):
                    break
                if FOLLOW.search(q['text']) and follow_price(q['text']):
                    d['price'] = follow_price(q['text'])
                    break
        if not d['price']:
            review.append({'id': k, 'why': 'нет цены', 'text': d['source']})
            continue
        if not photo:
            review.append({'id': k, 'why': 'нет фото', 'text': d['source']})
            continue
        if d['market'] and d['price'] < d['market'] < d['price'] * 3:
            d['gap'] = d['market'] - d['price']
        d['paint'], d['painted_count'] = paint_map(d)
        cars.append(d)
        floor = k
    cars = dedupe(cars)
    for j in ids:  # "Гранта 2015 бронь ✅", "Киа спектра продана ✅"
        t = posts[j]['text']
        if len(t) > 120 or FOLLOW.search(t):
            continue
        status = 'sold' if SOLD.search(t) else 'reserved' if RESERVED.search(t) else None
        if not status:
            continue
        at = datetime.fromisoformat(posts[j]['date'])
        for d in reversed([d for d in cars if d['id'] < j]):
            if at - datetime.fromisoformat(d['date']) > timedelta(days=cfg.KEEP_DAYS):
                break
            if same_car(t, d):
                if status == 'sold' or d['status'] == 'active':
                    d['status'] = status
                    d[f'{status}_at'] = posts[j]['date']
                break
    return cars, [], review


def dedupe(cars):
    """The same car gets reposted, sometimes with a new price or without the year: keep the newest post."""
    out = []
    for d in sorted(cars, key=lambda d: d['id'], reverse=True):
        twin = any(o['make'] == d['make'] and o['model'].split()[0] == d['model'].split()[0]
                   and (not o['year'] or not d['year'] or o['year'] == d['year'])
                   and abs(o['price'] - d['price']) <= o['price'] * .2
                   and datetime.fromisoformat(o['date']) - datetime.fromisoformat(d['date']) <= timedelta(days=7) for o in out)
        if not twin:
            out.append(d)
    return sorted(out, key=lambda d: d['id'])


def source(channel, seller, keep_days=10, min_text=120, year_optional=False):
    cfg = SimpleNamespace(CHANNEL=channel, SELLER=seller, KEEP_DAYS=keep_days, min_text=min_text, year_optional=year_optional)
    cfg.build = lambda posts: build(posts, cfg)
    return cfg


SOURCES = (
    source('AMSTEPDAM174', 'amstepdam'),
    source('avtodarom74', 'avtobutik74'),
    source('deshman_autokzn', 'deshman-auto'),
    source('evgenavtooo', 'evgen-avto', min_text=60, year_optional=True),  # reels with a short caption
)
