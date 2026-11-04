SPAKE2 0.9 from https://github.com/warner/python-spake2 (MIT).
Bundled for Android because cryptography wheels are unavailable for embedded Python 3.14.
Only groups.py changes: the two HKDF calls use the shared RFC 5869 HMAC implementation.
Group arithmetic, parameters and the SPAKE2 exchange are unchanged.
Desktop/Android interoperability and RFC 5869 vectors are tested.
