"""Decrypt a *.enc.json file made by encrypt_json.py / build_data.py.
Usage: python3 decrypt_json.py <password> <in.enc.json> <out.json>"""
import base64, json, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
pw, src, out = sys.argv[1:4]
e = json.load(open(src))
d = lambda x: base64.b64decode(x)
key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=d(e['salt']), iterations=e['iter']).derive(pw.encode())
open(out, 'wb').write(AESGCM(key).decrypt(d(e['iv']), d(e['ct']), None))
print('ok ->', out)
