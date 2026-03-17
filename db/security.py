import os
import hashlib
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from dotenv import load_dotenv

load_dotenv()

def get_encryption_key() -> bytes:
    key_hex = os.getenv("ENCRYPTION_KEY")
    if not key_hex:
        raise ValueError(
            "ENCRYPTION_KEY env variable is not set. "
            "Cannot start without encryption key."
        )
    return bytes.fromhex(key_hex)

def encrypt_string(plaintext: str) -> str:
    """Encrypts a string using AES-256-CBC."""
    if not plaintext:
        return plaintext
        
    key = get_encryption_key()
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_data = padder.update(plaintext.encode('utf-8')) + padder.finalize()
    
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()
    
    # Prepend IV to ciphertext and encode as base64
    return base64.b64encode(iv + ciphertext).decode('utf-8')

def decrypt_string(ciphertext_b64: str) -> str:
    """Decrypts a string encoded with AES-256-CBC."""
    if not ciphertext_b64:
        return ciphertext_b64
        
    key = get_encryption_key()
    raw_data = base64.b64decode(ciphertext_b64.encode('utf-8'))
    
    iv = raw_data[:16]
    ciphertext = raw_data[16:]
    
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    
    padded_data = decryptor.update(ciphertext) + decryptor.finalize()
    
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    plaintext = unpadder.update(padded_data) + unpadder.finalize()
    
    return plaintext.decode('utf-8')

def hash_string(plaintext: str) -> str:
    """Generates a SHA-256 hash for deterministic lookups with pepper."""
    if not plaintext:
        return plaintext
    
    pepper = os.getenv("HASH_PEPPER", "")
    return hashlib.sha256((plaintext + pepper).encode('utf-8')).hexdigest()
