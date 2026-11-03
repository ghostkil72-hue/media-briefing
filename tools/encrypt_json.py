"""Encrypt one JSON file with the site password (same format as build_data.py).
Usage: python3 encrypt_json.py <password> <in.json> <out.enc.json>"""
import base64, json, os, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
ITER = 310000
pw, src, out = sys.argv[1:4]
plain = open(src, 'rb').read()
salt, iv = os.urandom(16), os.urandom(12)
key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(pw.encode())
ct = AESGCM(key).encrypt(iv, plain, None)
b = lambda x: base64.b64encode(x).decode()
json.dump({'v': 1, 'iter': ITER, 'salt': b(salt), 'iv': b(iv), 'ct': b(ct)}, open(out, 'w'))
print('ok', len(plain), '->', out)
