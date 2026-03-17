import os
import pytest
from db.security import encrypt_string, decrypt_string, hash_string

# Set dummy env vars for tests
os.environ["ENCRYPTION_KEY"] = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
os.environ["HASH_PEPPER"] = "test_pepper"

def test_encryption_decryption():
    plaintext = "Hello BauClock"
    encrypted = encrypt_string(plaintext)
    assert encrypted != plaintext
    decrypted = decrypt_string(encrypted)
    assert decrypted == plaintext

def test_empty_string_encryption():
    assert encrypt_string("") == ""
    assert decrypt_string("") == ""

def test_hashing():
    plaintext = "user_123"
    hashed1 = hash_string(plaintext)
    hashed2 = hash_string(plaintext)
    assert hashed1 == hashed2
    assert hashed1 != plaintext
    
    # Verify pepper works
    os.environ["HASH_PEPPER"] = "different_pepper"
    hashed3 = hash_string(plaintext)
    assert hashed3 != hashed1
