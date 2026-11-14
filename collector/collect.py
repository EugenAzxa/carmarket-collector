"""Collect cars from Telegram and write what the site needs.

Usage:
  python3 collector/collect.py --state <state.json> --out <dir> [--review <review.json>] [--recheck]

A normal run reads only posts newer than the last one seen. --recheck (twice a day) reads every post we
still keep: sellers often write "ПРОДАНО" into the old listing or delete it, and no new post says so.

Writes <dir>/assets/js/cars.js and <dir>/media/<slug>/*.webp. Posts we could not read go to
review.json next to the state file, outside the site. If a channel does not answer, its cars
stay as they were and the run exits with an error: a network failure never takes cars off the site.
"""
import argparse
import io
import json
import os
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boards
import lex_auto
import nizherinka
import telegram

SOURCES = (lex_auto, nizherinka, *boards.SOURCES)
WORKERS = 6
MAX_DELETE = 600  # files deleted on the server per run
MAX_GONE = .5  # more posts than this vanishing at once is a Telegram glitch, not sellers deleting them
SOLD = re.compile(r'ПРОДАН')       # capitals in the head of the post: the seller's mark, not a word in the text
RESERVED = re.compile(r'БРОНЬ|ЗАДАТОК')


def load_state(path):
    if not os.path.exists(path):
        return {'channels': {}, 'media': {}, 'rechecked': None}  # first run: every post is read fresh
    with open(path, encoding='utf-8') as f:
        state = json.load(f)
    out = {'channels': state.get('channels', {}), 'media': state.get('media', {}), 'rechecked': state.get('rechecked'), 'checked': state.get('checked', {})}
    if 'notified' in state:  # absent = push notifications never ran: the first run only remembers
        out['notified'] = state['notified']
    return out


def merge_recheck(posts, fresh):
    """Kept posts after a full re-read: edits replace the text, deleted posts go away.
    Only the range the re-read really covered counts, and a mass disappearance is ignored."""
    if not fresh:
        return dict(posts), 0
    low = min(fresh)
    gone = [k for k in posts if k >= low and k not in fresh]
    merged = {**posts, **fresh}
    if len(gone) > len(posts) * MAX_GONE:
        print(f'recheck: {len(gone)} of {len(posts)} posts missing, keeping them', file=sys.stderr)
        return merged, 0
    for k in gone:
        del merged[k]
    return merged, len(gone)


def edited_status(text, status):
    """Status from a mark the seller put at the top of the listing itself."""
    head = text[:120]
    if SOLD.search(head):
        return 'sold'
    if status == 'active' and RESERVED.search(head):
        return 'reserved'
    return status


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or '.')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def save_webp(data, path, size, q):
    im = Image.open(io.BytesIO(data)).convert('RGB')
    im.thumbnail((size, size), Image.LANCZOS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path, 'WEBP', quality=q, method=4)
    return list(im.size)


def image(job, out, media):
    """Telegram links expire within days, so a file is stored the first time we see it.
    `media` remembers what is already on the server: the machine running this starts empty."""
    url, rel, size, q = job
    if rel in media:
        return media[rel]
    for attempt in range(3):  # the CDN answers 500 now and then
        try:
            media[rel] = save_webp(telegram.get(url), os.path.join(out, rel), size, q)
            return media[rel]
        except Exception as e:
            err = e
            time.sleep(2)
    print(f'photo failed {rel}: {err}', file=sys.stderr)
    return None


GONE = ('reserved', 'sold')  # deposit taken or sold: the card stays with its mark, big photos go


def attach_photos(car, out, media, pool):
    """Gallery 1200 px + card 640 px. A car that opens its Telegram post, or is already under a deposit
    or sold, needs only the card: nobody opens its gallery, so it is not kept on the server."""
    base = f"media/{car['slug']}"
    urls, reports = car.pop('_photos'), car.pop('_reports')
    card = f'{base}/card.webp'
    if car.get('via_channel') or car['status'] in GONE:
        if card not in media and os.path.exists(os.path.join(out, f'{base}/00.webp')):
            with open(os.path.join(out, f'{base}/00.webp'), 'rb') as f:
                media[card] = save_webp(f.read(), os.path.join(out, card), 640, 72)
        size = image((urls[0], card, 640, 72), out, media) if urls else None
        if not size:
            return False
        car['card'], car['gallery'], car['reports'] = card, [{'src': card, 'w': size[0], 'h': size[1]}], []
        car['via_channel'] = True  # the card opens the Telegram post, there is no page with photos any more
        return True
    jobs = [(u, f'{base}/{n:02d}.webp', 1200, 76) for n, u in enumerate(urls)]
    jobs += [(u, f'{base}/report-{n}.webp', 1200, 80) for n, u in enumerate(reports)]
    sizes = list(pool.map(lambda j: image(j, out, media), jobs))
    car['gallery'] = [{'src': j[1], 'w': s[0], 'h': s[1]} for j, s in zip(jobs[:len(urls)], sizes) if s]
    car['reports'] = [j[1] for j, s in zip(jobs[len(urls):], sizes[len(urls):]) if s]
    if not car['gallery']:
        return False
    first, src = car['gallery'][0]['src'], os.path.join(out, car['gallery'][0]['src'])
    if card not in media and os.path.exists(src):
        with open(src, 'rb') as f:
            media[card] = save_webp(f.read(), os.path.join(out, card), 640, 72)
    car['card'] = card if card in media else first
    return True


def trash(media, cars, soon, failed):
    """Files on the server that no car on the site uses any more. Forgotten in `media` and listed for
    push.py delete. Nothing is deleted when a channel failed or the run found almost no cars."""
    keep = {u['img'] for items in soon.values() for u in items if u.get('img')}
    for c in cars:
        keep |= {c['card'], *(g['src'] for g in c['gallery']), *c['reports']}
    if failed or len(cars) < 10:
        return []
    gone = sorted(k for k in media if k.startswith('media/') and k not in keep)[:MAX_DELETE]
    for k in gone:
        del media[k]
    return gone


MARKUP = re.compile(r'[<>"`\\]')
SAFE_URL = re.compile(r'^https://(?:t\.me|autoteka\.ru)/[\w\-/?=&.+%]*$')


def defang(x):
    """Text comes from other people's posts. The site escapes it on every page; this is the second
    lock: no markup characters in any string and only Telegram/Autoteka links in URL fields."""
    if isinstance(x, dict):
        return {k: (v if not isinstance(v, str) or not k in ('source', 'invite', 'autoteka_url') or SAFE_URL.match(v) else None)
                if k in ('source', 'invite', 'autoteka_url') else defang(v) for k, v in x.items()}
    if isinstance(x, list):
        return [defang(v) for v in x]
    return MARKUP.sub('', x) if isinstance(x, str) else x


NOTIFY_HOURS = 6  # a car older than this is not news any more (a channel added later, a long outage)


def new_cars(state, ready, now):
    """Cars for push notifications (tools/notify.py): free, not announced before, posted recently.
    The very first run only remembers what is already on the site, so nobody gets a flood."""
    first = 'notified' not in state
    seen = set(state.get('notified', []))
    state['notified'] = sorted(c['slug'] for c in ready)
    if first:
        return []
    return [{'slug': c['slug'], 'title': f"{c['make']} {c['model']}" + (f" {c['year']}" if c.get('year') else ''),
             'price': c['price'], 'market': c.get('market') or c.get('avito'), 'gap': c.get('gap'), 'card': c.get('card'),
             'seller': c['seller']}
            for c in ready if c['slug'] not in seen and c['status'] == 'active'
            and now - datetime.fromisoformat(c['date']) <= timedelta(hours=NOTIFY_HOURS)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--review')
    ap.add_argument('--max-pages', type=int, default=40)
    ap.add_argument('--recheck', action='store_true', help='re-read every kept post, not only new ones')
    a = ap.parse_args()

    state = load_state(a.state)
    media, cars, soon, review, failed = state['media'], [], {}, [], []
    now = datetime.now(timezone.utc)
    for src in SOURCES:
        posts = {int(k): v for k, v in state['channels'].get(src.CHANNEL, {}).items()}
        last = max(posts, default=0)
        try:
            if a.recheck and posts:
                posts, removed = merge_recheck(posts, telegram.fetch(src.CHANNEL, min(posts), a.max_pages))
                print(f'{src.CHANNEL}: rechecked {len(posts)} posts, {removed} deleted by the seller')
            else:
                # a channel seen for the first time is read only as deep as its cars are kept
                since = None if posts else now - timedelta(days=src.KEEP_DAYS)
                posts.update(telegram.fetch(src.CHANNEL, max(posts, default=0), a.max_pages, since))
        except Exception as e:
            print(f'{src.CHANNEL}: {e}', file=sys.stderr)
            failed.append(src.CHANNEL)
        edge = now - timedelta(days=src.KEEP_DAYS)
        posts = {k: p for k, p in posts.items() if p['date'] and datetime.fromisoformat(p['date']) >= edge}
        state['channels'][src.CHANNEL] = posts
        c, u, r = src.build(posts)
        for car in c:
            if car['id'] in posts:
                car['status'] = edited_status(posts[car['id']]['text'], car['status'])
        cars += c
        soon[src.SELLER] = u
        review += r
        # one line per channel in the run log: every channel is read every run, a silent one shows here
        newest = max((p['date'] for p in posts.values() if p['date']), default=None)
        quiet = f', тишина {(now - datetime.fromisoformat(newest)).days} дн.' if newest and now - datetime.fromisoformat(newest) > timedelta(days=3) else ''
        state.setdefault('checked', {})[src.CHANNEL] = {'at': now.isoformat(timespec='seconds'), 'ok': src.CHANNEL not in failed, 'newest': newest}
        print(f"  {src.CHANNEL}: {'НЕ ПРОЧИТАН' if src.CHANNEL in failed else 'ok'}, новых постов {sum(k > last for k in posts)}, "
              f"машин {len(c)}, последний пост {newest[:16] if newest else 'нет за ' + str(src.KEEP_DAYS) + ' дн.'}{quiet}")

    ready = []
    with ThreadPoolExecutor(WORKERS) as pool:
        for car in cars:
            if attach_photos(car, a.out, media, pool):
                ready.append(car)
            else:
                review.append({'id': car['id'], 'why': 'нет фото', 'text': car['source']})
        for items in soon.values():
            for u in items:
                rel = f"media/upcoming-{u['id']}.webp"
                u['img'] = rel if image((u.pop('_photo'), rel, 1200, 76), a.out, media) else None
    ready = [defang(c) for c in ready if SAFE_URL.match(c.get('source') or '')]
    soon = {k: [defang(u) for u in v] for k, v in soon.items()}
    ready.sort(key=lambda c: c['date'], reverse=True)
    news = new_cars(state, ready, now)
    write_atomic(os.path.join(os.path.dirname(a.state) or '.', 'notify.json'), json.dumps(news, ensure_ascii=False))
    if (a.recheck or not state['rechecked']) and not failed:
        state['rechecked'] = now.isoformat(timespec='seconds')

    js = ('// Generated by collector/collect.py - do not edit by hand\nwindow.CARS = '
          + json.dumps(ready, ensure_ascii=False, indent=1) + ';\nwindow.UPCOMING = '
          + json.dumps(soon, ensure_ascii=False, indent=1) + ';\nwindow.UPDATED_AT = '
          + json.dumps(now.isoformat(timespec='seconds')) + ';\nwindow.RECHECKED_AT = '
          + json.dumps(state['rechecked']) + ';\n')
    write_atomic(os.path.join(a.out, 'assets', 'js', 'cars.js'), js)
    write_atomic(a.review or os.path.join(os.path.dirname(a.state) or '.', 'review.json'),
                 json.dumps(review, ensure_ascii=False, indent=1))
    gone = trash(media, ready, soon, failed)
    write_atomic(os.path.join(os.path.dirname(a.state) or '.', 'delete.json'), json.dumps(gone))
    write_atomic(a.state, json.dumps(state, ensure_ascii=False))
    print(f"cars {len(ready)}, reserved {sum(c['status'] == 'reserved' for c in ready)}, "
          f'upcoming {sum(len(u) for u in soon.values())}, review {len(review)}, to delete {len(gone)}, to notify {len(news)}, failed {failed}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
