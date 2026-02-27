from .base import *

DEBUG = False

ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']

SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_PROXY_SSL_HEADER = None

EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend' 

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

