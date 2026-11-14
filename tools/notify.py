#!/usr/bin/env python3
"""Send "new car" push notifications (since 14.11.2026).

Usage: python3 tools/notify.py work/notify.json [--test ENDPOINT_HASH]

notify.json is written by collector/collect.py: free cars that appeared since the last run.
Subscriptions live on the site (cm-push.php writes ../carmarket-data/subs.json), read here through
cm-deploy.php; ones the push service no longer knows (404/410) are removed with action=unsub.
Every subscriber gets at most one notification per run: one car, or "N new cars" with the best one.
Needs pywebpush and VAPID_PRIVATE (env, or .env.local next to the repo). No sends 00:00-08:00 MSK.
"""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import push

QUIET = range(0, 8)  # Moscow hours without notifications
MSK = timezone(timedelta(hours=3))


def vapid_key():
    k = os.environ.get('VAPID_PRIVATE', '')
    if not k:
        try:
            for line in open(os.path.join(push.ROOT, '.env.local'), encoding='utf-8'):
                if line.startswith('VAPID_PRIVATE='):
                    k = line.split('=', 1)[1].strip()
        except FileNotFoundError:
            pass
    if not k:
        sys.exit('no VAPID_PRIVATE')
    return k


def rub(v):
    return f'{v:,}'.replace(',', ' ') + ' ₽'


def short(v):
    return f'{v / 1e6:.1f}'.replace('.', ',').replace(',0', '') + ' млн' if v >= 1_000_000 else f'{round(v / 1000)}к'


def plural(n, one, few, many):
    n = abs(n) % 100
    return many if 10 < n < 20 else one if n % 10 == 1 else few if 1 < n % 10 < 5 else many


def message(cars):
    """Title says the car and the gap, the body says the price: what the reader decides on."""
    site = push.SITE
    best = max(cars, key=lambda c: c.get('gap') or 0)
    image = f"{site}/{best['card']}" if best.get('card') else None
    if len(cars) == 1:
        c = cars[0]
        title = f"{c['title']}: -{short(c['gap'])} к рынку" if c.get('gap') else f"Новая тачка: {c['title']}"
        body = rub(c['price']) + (f", рынок {short(c['market'])}" if c.get('market') else '') + '. Открыть объявление'
        return {'title': title, 'body': body, 'url': f"{site}/car.html?id={c['slug']}", 'image': image, 'tag': 'cm-' + c['slug']}
    n = len(cars)
    lead = f"Лучшая: {best['title']}, {rub(best['price'])}" + (f", -{short(best['gap'])} к рынку" if best.get('gap') else '')
    return {'title': f"{n} {plural(n, 'новая машина', 'новые машины', 'новых машин')} ниже рынка", 'body': lead,
            'url': f'{site}/#catalog', 'image': image, 'tag': 'cm-batch'}


def main(a):
    path = a[0]
    cars = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else []
    test = a[a.index('--test') + 1] if '--test' in a else None
    if not cars and not test:
        print('notify: no new cars'); return
    if not test and datetime.now(MSK).hour in QUIET:
        print(f'notify: {len(cars)} new cars, night - not sending'); return
    code, body = push.post({'action': 'get', 'name': 'subs.json'})
    if code == 204:
        print('notify: no subscribers'); return
    if code != 200:
        sys.exit(f'notify: subs failed {code}: {body[:200]!r}')
    subs = json.loads(body)
    if test:
        subs = {k: v for k, v in subs.items() if k.startswith(test)}
        cars = cars or [{'slug': 'test', 'title': 'Проверка уведомлений', 'price': 1_000_000, 'market': 1_300_000, 'gap': 300_000, 'card': None}]
    from pywebpush import WebPushException, webpush
    key = vapid_key()

    def send(item):
        sid, s = item
        mine = [c for c in cars if (c.get('gap') or 0) >= s.get('gap', 0)] if s.get('gap') else cars
        if not mine:
            return 'skip', sid
        try:
            webpush(subscription_info={'endpoint': s['endpoint'], 'keys': s['keys']},
                    data=json.dumps(message(mine), ensure_ascii=False), vapid_private_key=key,
                    vapid_claims={'sub': push.SITE}, ttl=3 * 3600, headers={'Urgency': 'high'}, timeout=20)
            return 'ok', sid
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else 0
            return ('dead' if status in (404, 410) else f'err {status}'), sid
        except Exception as e:  # network trouble with one push service must not stop the others
            return f'err {type(e).__name__}', sid

    with ThreadPoolExecutor(8) as pool:
        res = list(pool.map(send, subs.items()))
    dead = [sid for r, sid in res if r == 'dead']
    if dead:
        code, body = push.post({'action': 'unsub', 'ids': json.dumps(dead)})
        print('notify: unsub', code, body.decode(errors='replace').strip())
    tally = {}
    for r, _ in res:
        tally[r] = tally.get(r, 0) + 1
    print(f'notify: {len(cars)} new cars, {len(subs)} subscribers, {tally}')


if __name__ == '__main__':
    main(sys.argv[1:])
