"""Password and session primitives; no credentials in browser storage."""
import base64
import hashlib
import hmac
import secrets

def hash_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ValueError('Das Passwort muss 12 bis 128 Zeichen lang sein.')
    salt = secrets.token_bytes(16)
    result = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=32768, r=8, p=1, maxmem=67108864, dklen=64)
    return 'scrypt$32768$8$1$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(result).decode()

def verify_password(password, stored):
    if not isinstance(password, str) or len(password) > 128:
        return False
    try:
        method, n, r, p, salt, expected = stored.split('$')
        if (method, n, r, p) != ('scrypt', '32768', '8', '1'):
            return False  # Phase 2 fictitious hash strings are intentionally not login credentials.
        result = hashlib.scrypt(password.encode('utf-8'), salt=base64.b64decode(salt, validate=True), n=32768, r=8, p=1, maxmem=67108864, dklen=64)
        return hmac.compare_digest(result, base64.b64decode(expected, validate=True))
    except (ValueError, TypeError):
        return False

def token_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()
