#!/usr/bin/env python3
"""Deploy to SpaceWeb over HTTPS through /cm-deploy.php (deploy/receive.php).

SSH and FTP on SpaceWeb do not answer from abroad, HTTPS does. Stdlib only.

  push.py package OUT.zip [--data DIR]   zip for the one-time manual upload: site + cm-deploy.php (+ cars.js, media)
  push.py site DIR [--code]              send DIR to the site; --code first stages the repo through deploy/rsync-filter
  push.py data FILE...                   send state.json / review.json to ../carmarket-data
  push.py get NAME OUT                   download state.json or review.json (prints "none" if absent)
  push.py ping                           PHP version and upload limits
  push.py indexnow [PATH...]             tell Yandex (IndexNow) about new or changed pages; no PATH = whole sitemap.xml

Token: env CM_DEPLOY_TOKEN or .env.local. Site: env CM_SITE (default https://машиныпонизурынка.рф).
"""
import hashlib, io, json, os, subprocess, sys, tempfile, time, urllib.error, urllib.request, uuid, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.environ.get('CM_SITE', 'https://xn--80aaudanjkachlr5b5d7bh.xn--p1ai')
CHUNK = 12 * 1024 * 1024  # stay under small upload_max_filesize limits
LAST = ('assets/js/cars.js',)  # data that points to media goes after the media


def token():
    t = os.environ.get('CM_DEPLOY_TOKEN', '')
    if not t:
        try:
            for line in open(os.path.join(ROOT, '.env.local'), encoding='utf-8'):
                if line.startswith('CM_DEPLOY_TOKEN='):
                    t = line.split('=', 1)[1].strip()
        except FileNotFoundError:
            pass
    if not t:
        sys.exit('no CM_DEPLOY_TOKEN')
    return t


def ours():
    """Never send the token to a host that is not our site (stale DNS, VPN cache, parking page)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(SITE + '/robots.txt', headers={'User-Agent': 'carmarket-deploy'}), timeout=30) as r:
            body = r.read(2000).decode('utf-8', 'replace')
    except Exception as e:
        sys.exit(f'site check failed: {e}')
    if 'Sitemap: ' + SITE not in body:
        sys.exit('site check failed: ' + SITE + ' does not serve our robots.txt yet (DNS or VPN cache), token not sent')


def post(fields, file_bytes=None, timeout=300):
    ours()
    b = uuid.uuid4().hex
    body = io.BytesIO()
    for k, v in fields.items():
        body.write(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    if file_bytes is not None:
        body.write(f'--{b}\r\nContent-Disposition: form-data; name="bundle"; filename="bundle.zip"\r\nContent-Type: application/zip\r\n\r\n'.encode())
        body.write(file_bytes)
        body.write(b'\r\n')
    body.write(f'--{b}--\r\n'.encode())
    req = urllib.request.Request(SITE + '/cm-deploy.php', data=body.getvalue(), method='POST', headers={
        'Content-Type': f'multipart/form-data; boundary={b}', 'X-Deploy-Token': token(), 'User-Agent': 'carmarket-deploy'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 2:
                raise
            print('retry after', e, file=sys.stderr)
            time.sleep(5 * (attempt + 1))


def files_in(d):
    out = []
    for base, dirs, names in os.walk(d):
        dirs[:] = [x for x in dirs if not x.startswith('.')]
        for n in names:
            if n.startswith('.'):
                continue
            p = os.path.join(base, n)
            out.append((os.path.relpath(p, d).replace(os.sep, '/'), p))
    return sorted(out, key=lambda x: (x[0] in LAST, x[0]))


def bundles(items):
    """Group (name, path) into zips of about CHUNK bytes, keeping order."""
    cur, size = [], 0
    for name, path in items:
        s = os.path.getsize(path)
        if cur and size + s > CHUNK:
            yield cur
            cur, size = [], 0
        cur.append((name, path))
        size += s
    if cur:
        yield cur


def make_zip(items):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, path in items:
            z.write(path, name)
    return buf.getvalue()


def stage_code(dst):
    subprocess.run(['rsync', '-a', '--filter=merge ' + os.path.join(ROOT, 'deploy/rsync-filter'), ROOT + '/', dst + '/'], check=True)


def size_limit():
    """Bundle size that fits the server's upload_max_filesize and post_max_size."""
    global CHUNK
    code, body = post({'action': 'ping'})
    if code != 200:
        sys.exit(f'ping failed {code}: {body[:200]!r}')
    info = json.loads(body)
    def mb(v):
        v = str(v).strip().upper()
        n = float(v.rstrip('KMG') or 0)
        return n * {'K': 1 / 1024, 'M': 1, 'G': 1024}.get(v[-1:], 1 / 1048576)
    lim = min(mb(info.get('upload_max', '8M')), mb(info.get('post_max', '8M')))
    CHUNK = int(max(1, min(12, lim * 0.7)) * 1024 * 1024)
    print('server', info.get('php'), 'upload', info.get('upload_max'), 'post', info.get('post_max'), '-> bundles of', CHUNK // 1048576, 'MB')


def send_site(d):
    size_limit()
    items = files_in(d)
    sent = 0
    for group in bundles(items):
        code, body = post({'action': 'site'}, make_zip(group))
        if code != 200:
            sys.exit(f'site upload failed {code}: {body[:300]!r}')
        sent += len(group)
        print(f'  {sent}/{len(items)} files')
    print('site ok,', sent, 'files')


def cmd_package(out, data_dir=None):
    th = hashlib.sha256(token().encode()).hexdigest()
    php = open(os.path.join(ROOT, 'deploy/receive.php'), encoding='utf-8').read().replace('__TOKEN_SHA256__', th)
    with tempfile.TemporaryDirectory() as tmp:
        stage_code(tmp)
        if data_dir:
            subprocess.run(['rsync', '-a', '--include=/assets/', '--include=/assets/js/', '--include=/assets/js/cars.js',
                            '--include=/media/***', '--exclude=*', data_dir.rstrip('/') + '/', tmp + '/'], check=True)
        with open(os.path.join(tmp, 'cm-deploy.php'), 'w', encoding='utf-8') as f:
            f.write(php)
        n = 0
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            for base, dirs, names in os.walk(tmp):
                for nm in names:
                    p = os.path.join(base, nm)
                    z.write(p, os.path.relpath(p, tmp))
                    n += 1
    print(out, n, 'files', round(os.path.getsize(out) / 1e6, 1), 'MB')


INDEXNOW_KEY = 'c053c808c552470eac5267622fe34a51'  # public by design: the same key is served as /<key>.txt


def cmd_indexnow(paths):
    import re
    if not paths:
        with open(os.path.join(ROOT, 'sitemap.xml'), encoding='utf-8') as f:
            urls = re.findall(r'<loc>([^<]+)</loc>', f.read())
    else:
        urls = [SITE + '/' + p.lstrip('/') for p in paths]
    host = SITE.split('//', 1)[1]
    body = json.dumps({'host': host, 'key': INDEXNOW_KEY, 'keyLocation': f'{SITE}/{INDEXNOW_KEY}.txt', 'urlList': urls[:10000]}).encode()
    req = urllib.request.Request('https://yandex.com/indexnow', data=body, method='POST', headers={'Content-Type': 'application/json; charset=utf-8', 'User-Agent': 'carmarket-deploy'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print('indexnow', r.status, len(urls), 'urls')
    except urllib.error.HTTPError as e:
        sys.exit(f'indexnow failed {e.code}: {e.read()[:300]!r}')


def main(a):
    if not a or a[0] in ('-h', '--help'):
        print(__doc__); return
    c = a[0]
    if c == 'package':
        cmd_package(a[1], a[a.index('--data') + 1] if '--data' in a else None)
    elif c == 'indexnow':
        cmd_indexnow(a[1:])
    elif c == 'ping':
        print(*post({'action': 'ping'}))
    elif c == 'get':
        code, body = post({'action': 'get', 'name': a[1]})
        if code == 204:
            print('none'); return
        if code != 200:
            sys.exit(f'get failed {code}: {body[:200]!r}')
        json.loads(body)  # never save an error page as state
        open(a[2], 'wb').write(body)
        print('got', a[1], len(body), 'bytes')
    elif c == 'data':
        items = [(os.path.basename(p), p) for p in a[1:] if os.path.exists(p)]
        code, body = post({'action': 'data'}, make_zip(items))
        if code != 200:
            sys.exit(f'data upload failed {code}: {body[:300]!r}')
        print('data ok', [n for n, _ in items])
    elif c == 'site':
        if '--code' in a:
            with tempfile.TemporaryDirectory() as tmp:
                stage_code(tmp)
                send_site(tmp)
        else:
            send_site(a[1])
    else:
        sys.exit('unknown command ' + c)


if __name__ == '__main__':
    main(sys.argv[1:])
