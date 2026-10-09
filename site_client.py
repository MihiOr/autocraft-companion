"""Delta Cross's observed HTML form workflow; tracks an exact order ID."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
import re
import requests

BASE = 'https://delta-cross.com/'


class SiteError(RuntimeError):
    pass


def needs_submission(pending, observed):
    """The website calls a successfully uploaded, unsubmitted file 'copied'."""
    if observed:
        if observed['name'] != pending['name']:
            raise SiteError('Order filename mismatch. No submission was made.')
        return observed['status'] in ('copied', 'uploaded')
    # Only a fresh upload may be submitted without a visible status. After an
    # ambiguous POST, require an explicit remote status before attempting again.
    return pending['state'] == 'uploaded'


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.forms, self.rows, self.links = [], [], []
        self.row_links, self.current_row_links = [], None
        self.form = self.row = self.cell = self.link = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form':
            self.form = {'action': a.get('action', '#'), 'fields': {}, 'files': []}
            self.forms.append(self.form)
        elif tag == 'input' and self.form is not None and a.get('name'):
            if a.get('type') == 'file':
                self.form['files'].append(a['name'])
            else:
                self.form['fields'][a['name']] = a.get('value', '')
        elif tag == 'tr':
            self.row = []
            self.current_row_links = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []
        elif tag == 'a':
            self.link = {'href': a.get('href', ''), 'text': '', 'attrs': a}
            self.links.append(self.link)
            if self.current_row_links is not None:
                self.current_row_links.append(self.link)

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        if self.link is not None:
            self.link['text'] += data

    def handle_endtag(self, tag):
        if tag == 'form':
            self.form = None
        elif tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row_links.append(self.current_row_links or [])
            self.row = None
            self.current_row_links = None
        elif tag == 'a':
            self.link = None


class Client:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'AutoCraftCompanion/1.0 (personal export helper)'

    def request(self, method, url, **kwargs):
        url = urljoin(BASE, url)
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != 'delta-cross.com':
            raise SiteError('Unexpected website URL; operation stopped.')
        # Do not retry POSTs: an ambiguous reply must never duplicate a conversion.
        r = self.session.request(method, url, timeout=(15, 90), **kwargs)
        r.raise_for_status()
        if 'Login.php' in r.url and not url.endswith('Login.php'):
            raise SiteError('Website session expired. Log in again to resume this order.')
        return r

    def login(self, email, password):
        page = self.request('GET', 'Login.php')
        form = next((f for f in Page(page.text).forms if 'password' in f['fields']), None)
        if not form:
            raise SiteError('Login form changed; cannot safely log in.')
        data = dict(form['fields'], email=email, password=password)
        r = self.request('POST', urljoin(page.url, form['action']), data=data)
        if 'logout.php' not in r.text.lower():
            raise SiteError('Login failed. Check the email and password in Settings.')

    def upload(self, path):
        path = Path(path)
        if path.suffix.lower() != '.vcl' or not 0 < path.stat().st_size <= 5 * 1024 * 1024:
            raise SiteError('Choose a .vcl file smaller than 5 MB.')
        r = self.request('GET', 'UploadVCL.php')
        form = next((f for f in Page(r.text).forms if 'vFile' in f['files']), None)
        if not form:
            raise SiteError('Upload form changed; no file was submitted.')
        with path.open('rb') as f:
            result = self.request('POST', urljoin(r.url, form['action']),
                                  data=form['fields'], files={'vFile': (path.name, f, 'application/octet-stream')})
        submit = next((f for f in Page(result.text).forms if {'rid', 'vFile', 'submit2'} <= f['fields'].keys()), None)
        if not submit:
            raise SiteError('Website did not accept the VCL or its submission form changed.')
        fields = submit['fields']
        if not fields['rid'].isdigit():
            raise SiteError('Unexpected order ID in upload response.')
        return {'id': fields['rid'], 'name': path.stem, 'state': 'uploaded',
                'fields': fields, 'action': urljoin(result.url, submit['action'])}

    def submit(self, pending):
        if not {'rid', 'vFile', 'submit2'} <= pending.get('fields', {}).keys():
            raise SiteError('Saved submission details are missing. Open this order on the website.')
        if str(pending['fields']['rid']) != str(pending['id']):
            raise SiteError('Saved submission ID does not match the order.')
        r = self.request('POST', pending['action'], data=pending['fields'])
        if not re.search(r'Mod request id#' + re.escape(str(pending['id'])) + r'\s+submitted successful', r.text, re.I):
            observed = self.orders().get(str(pending['id']))
            if not observed or observed['status'] not in ('submitted', 'processing', 'processed', 'queued', 'pending'):
                raise SiteError('Submission was not confirmed. Resume the saved order to check its status; do not create another conversion.')

    def orders(self):
        r = self.request('GET', 'Orders.php')
        return parse_orders(r.text)

    def delete_order(self, order_id, expected_name):
        order_id = str(order_id)
        current = self.orders()
        row = current.get(order_id)
        if row is None:
            return current  # Already deleted; do not request a fabricated link.
        if row['name'] != expected_name:
            raise SiteError('The selected order changed. Refresh Orders before deleting.')
        link = row.get('delete_url')
        if not link or not valid_delete_url(link, order_id):
            raise SiteError('The website does not currently offer deletion for this order.')
        # This GET is a mutation on this website. Never retry it automatically.
        self.request('GET', link)
        remaining = self.orders()
        if order_id in remaining:
            raise SiteError('The website still lists this order. Refresh to check before trying again.')
        return remaining

    def garage_html(self):
        return self.request('GET', 'Garage.php').text

    def download(self, url, target, cancel):
        from storage import atomic_bytes
        r = self.request('GET', url, stream=True)
        chunks, size = [], 0
        try:
            for chunk in r.iter_content(1024 * 1024):
                if cancel.is_set():
                    raise SiteError('Download cancelled. Resume the same order later.')
                chunks.append(chunk)
                size += len(chunk)
                if size > 300 * 1024 * 1024:
                    raise SiteError('Download exceeds the 300 MB limit.')
        finally:
            r.close()
        data = b''.join(chunks)
        if not data.startswith(b'PK\x03\x04'):
            raise SiteError('Download response is not a ZIP; nothing was installed.')
        atomic_bytes(target, data)


def valid_delete_url(url, order_id):
    parsed = urlparse(urljoin(BASE, url))
    return (parsed.scheme == 'https' and parsed.netloc == 'delta-cross.com'
            and parsed.path == '/deletereq.php'
            and parse_qs(parsed.query) == {'rid': [str(order_id)]})


def parse_orders(html):
    page = Page(html)
    if not any(len(row) >= 3 and row[0].lower() == 'id' and row[2].lower() == 'status' for row in page.rows):
        raise SiteError('Orders table was not found. Could not verify the website order list.')
    result = {}
    for row, links in zip(page.rows, page.row_links):
        if len(row) < 3 or not row[0].isdigit():
            continue
        delete_links = [a for a in links if valid_delete_url(a['href'], row[0])]
        if len(delete_links) > 1:
            raise SiteError('Ambiguous delete links in Orders. No changes made.')
        link = delete_links[0] if delete_links else None
        result[row[0]] = {'id': row[0], 'name': row[1], 'status': row[2].lower().strip(),
                         'delete_url': urljoin(BASE, link['href']) if link else None,
                         'delete_label': link['text'].strip() if link else 'Unavailable'}
    return result


def garage_download(html, pending):
    """Filled against the observed Garage markup; never select an unrelated newest car."""
    candidates = []
    for link in Page(html).links:
        href = link['href']
        if re.search(r'\.zip(?:[?#]|$)', href, re.I):
            parsed = urlparse(href)
            filename = Path(parse_qs(parsed.query).get('fp', [parsed.path])[0]).name
            # Server export filenames include exact request ID followed by account ID/name.
            if filename.startswith(str(pending['id']) + '_'):
                candidates.append(urljoin(BASE, href))
    if len(set(candidates)) != 1:
        raise SiteError('Could not identify the ZIP for order ' + str(pending['id']) + '. Check Garage; no unrelated download was selected.')
    return candidates[0]
