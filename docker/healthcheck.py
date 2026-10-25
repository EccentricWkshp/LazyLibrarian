""" Docker health check: ask LazyLibrarian's /ping, at the port and web root set in config.ini """

import configparser
import ssl
import sys
import urllib.request

config = configparser.ConfigParser(interpolation=None)
config.read('/config/config.ini')
port = config.get('WebServer', 'http_port', fallback='5299')
root = config.get('WebServer', 'http_root', fallback='').strip('/')
https = config.get('WebServer', 'https_enabled', fallback='0').lower() in ('1', 'true', 'yes', 'on')

url = f"{'https' if https else 'http'}://127.0.0.1:{port}/{root + '/' if root else ''}ping"
# A self-signed certificate is fine here, it's our own server
context = ssl._create_unverified_context() if https else None
try:
    with urllib.request.urlopen(url, timeout=8, context=context) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception as e:
    print(f'{url}: {e}')
    sys.exit(1)
