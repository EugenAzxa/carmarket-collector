"""Read the public preview of a Telegram channel (t.me/s/<channel>). No account, no API key."""
import html
import re
import time
import urllib.request
from datetime import datetime

UA = 'Mozilla/5.0'
PAUSE = 1.5  # seconds between pages


def get(url, timeout=25):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    return urllib.request.urlopen(req, timeout=timeout).read()


def parse_page(src, channel):
    """Posts of one preview page: {id: {id, text, photos, video, views, date, reply_to}}."""
    posts = {}
    for blk in re.split(r'(?=<div class="tgme_widget_message_wrap)', src)[1:]:
        m = re.search(r'data-post="%s/(\d+)"' % re.escape(channel), blk, re.I)
        if not m:
            continue
        pid = int(m.group(1))
        # a reply quotes the parent's text first, drop the quote before reading ours
        reply = re.search(r'<a class="tgme_widget_message_reply[^>]*href="[^"]*/(\d+)".*?</a>', blk, re.S)
        body = blk.replace(reply.group(0), '') if reply else blk
        txt = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', body, re.S)
        text = ''
        if txt:
            text = re.sub(r'<br\s*/?>', '\n', txt.group(1))
            text = html.unescape(re.sub(r'<[^>]+>', '', text)).strip()
        views = re.search(r'tgme_widget_message_views">([^<]+)', blk)
        date = re.search(r'datetime="([^"]+)"', blk)
        posts[pid] = {
            'id': pid,
            'text': text,
            'photos': re.findall(r"tgme_widget_message_photo_wrap[^>]*background-image:url\('([^']+)'\)", body),
            'video': 'tgme_widget_message_video_player' in body,
            # cover frame of a video; a channel that posts only reels has no other picture
            'thumbs': re.findall(r"tgme_widget_message_video_thumb[^>]*background-image:url\('([^']+)'\)", body),
            'views': views.group(1) if views else None,
            'date': date.group(1) if date else None,
            'reply_to': int(reply.group(1)) if reply else None,
        }
    return posts


def fetch(channel, after=0, max_pages=40, since=None):
    """Walk the channel back from the newest post until `after` (or posts older than `since`, a datetime).
    Raises if nothing could be read."""
    posts, before = {}, None
    for _ in range(max_pages):
        url = f'https://t.me/s/{channel}' + (f'?before={before}' if before else '')
        page = parse_page(get(url).decode('utf-8', 'replace'), channel)
        if not page:
            break
        posts.update(page)
        before = min(page)
        if before <= after:
            break
        dates = [p['date'] for p in page.values() if p['date']]
        if since and dates and datetime.fromisoformat(min(dates)) < since:
            break
        time.sleep(PAUSE)
    if not posts:
        raise RuntimeError(f'no posts read from {channel}')
    return posts
