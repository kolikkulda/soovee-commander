# Vývoj

Hlavní balíček je `src/soovee_commander`. Kód a názvy příkazů jsou anglicky, texty českého rozhraní jsou v `locales/cs.json`.

```sh
python -m pip install -e '.[dev]'
python -m soovee_commander --version
python -m soovee_commander
python -m pytest -q
```

Testy samy nastaví `QT_QPA_PLATFORM=offscreen` (v `tests/conftest.py`); bez něj se okna v testech na macOS zaseknou. Pokud je pracovní složka v iCloudu, Python 3.14 ignoruje skryté `.pth` soubory editovatelné instalace – testy proto používají `pythonpath = ["src"]`. Windows potřebuje native libarchive DLL; workflow ji připravuje přes vcpkg.

## Sestavení

- Mac: `SOOVEE_PYTHON=/path/to/python ./scripts/build_macos.sh`
- Windows: nastavte `LIBARCHIVE` na vcpkg `archive.dll` a spusťte `./scripts/build_windows.ps1`.
- Výstupy jsou v ignorované složce `dist/`.
- CI je v `.github/workflows/build.yml`; ověřuje testy, zabalenou aplikaci, Windows instalaci/odinstalaci a přenosný ZIP.
- `scripts/collect_licenses.py` připravuje skutečný inventář knihoven a offline licenční texty. Ve Windows přidává také native vcpkg notices.
- `scripts/screenshot.py` vytváří jeden náhled z dočasných dat a izolovaného nastavení.

## Kompatibilita

`python -m stereo_commander` je ponechaný pouze jako malý kompatibilní vstup do nového modulu. Nové skripty používají `python -m soovee_commander`.

Původní identifikátory QSettings, datové složky, ID aplikace a aktualizační podpisový klíč se zachovávají, aby se neztratily profily, párování a nastavení. Mac aktualizační payload zachovává původní kořen a alias executable, které vyžadují již nainstalované updatery; nový DMG obsahuje `SooveeCommander.app`.

Soukromý podpisový klíč je pouze v ignorované `.release/`. K vytvoření a spuštění vlastního upraveného programu není tento klíč potřeba. Pro oficiální `.stereoupdate` se používá `scripts/release.py` s odpovídajícím místním klíčem. Volitelný CI secret má název `SOOVEE_UPDATE_SIGNING_KEY`.
