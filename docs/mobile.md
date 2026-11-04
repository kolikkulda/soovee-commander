# Mobilní a TV testovací klienti

Android APK 0.19.0 obsahuje ARMv7, ARM64, x86 a x86_64. Telefon a TV používají stejný balíček, rozhraní se volí podle zařízení. Podporuje i 32bitový systém na zařízení s 64bitovým procesorem. Vyžaduje Android 7 nebo novější. Pro automatické hledání a kapacitu zařízení použijte desktop 0.19.0.

Android používá Python 3.11, který má 32bitové balíčky. Chybějící Python TLS-PSK API doplňuje adaptér veřejného OpenSSL API s paměťovými BIO. Šifrování, párování a protokol se nemění: TLS 1.3, ověřený PSK a kontrola SHA-256. Adaptér nepovoluje certifikátovou náhradu ani starší TLS. Desktop nadále upřednostňuje vestavěnou podporu Pythonu 3.13+.

## Propojení s desktopem

1. Připojte zařízení do stejné místní sítě a otevřete obě aplikace.
2. Na desktopu otevřete Zařízení → V okolí. Vyberte TV podle názvu a napište její osmimístný kód. Na telefonu lze místo toho načíst QR.
3. Potvrďte párování a ověřovací údaj. Zařízení se otevře jako disk v panelu.
4. Na TV otevřete Úložiště a soubory. U každého úložiště je skutečná cesta a kapacita. Shared je soukromá složka aplikace; již uložené soubory zůstávají na místě.
5. Pro interní úložiště a USB zvolte povolení přístupu, potvrďte sdílení a povolte přístup k souborům v nastavení Androidu. Teprve potom jsou tyto složky dostupné spárovaným zařízením. Android/data a Android/obb ostatních aplikací zůstávají chráněné.
6. Na počítači nebo telefonu procházejte zpřístupněné složky a zvolte cílový adresář kopírování. Panel zobrazuje kapacitu vybraného úložiště; úložiště stejného svazku se nesčítají.

TV je standardně ovládaná; v Nastavení lze povolit oba směry. Párování a soubory přežijí aktualizaci podepsanou stejným klíčem. Odinstalování nebo vymazání dat aplikace odstraní její soukromé soubory a párování. Odvolání sdílení soubory nemaže.

Automatické hledání používá Bonjour/mDNS a vyžaduje běžící aplikace a síť bez izolace klientů. Kódy ani klíče se neoznamují. Při změně IP adresy se uložená adresa změní až po ověření klíčem zařízení. Ruční adresa zůstává v rozšířené nabídce jako náhradní cesta. Na obou zařízeních od verze 0.18.0 funguje také přejmenování a trvalé mazání uvnitř zapisovatelných sdílených složek. Kořeny a chráněné stromy změnit nelze. Desktop si pamatuje zapnuté přenosy a obnoví je po spuštění; výslovné vypnutí se zachová.

## Sestavení Androidu

Vyžaduje Java 17, Gradle 8.9, Android SDK 35 a hostitelský Python 3.11:

```sh
export ANDROID_HOME=/path/to/Android/sdk
export SOOVEE_BUILD_PYTHON=/path/to/python3.11
gradle --no-daemon -p mobile/android :app:assembleRelease
python scripts/sign_android.py mobile/android/app/build/outputs/apk/release/app-release-unsigned.apk --output dist/SooveeCommander-0.19.0-android-universal.apk
```

Podpisový skript při prvním běhu vytvoří soukromý klíč v ignorované složce `.release`. Klíč a heslo bezpečně zálohujte; další aktualizace musí být podepsané stejným klíčem. Soukromé klíče nepatří do repozitáře ani do Releases. GitHub Actions vytváří nepodepsaný artefakt, finální APK se podepisuje lokálně.

## Apple simulátory

`scripts/build_apple_clients.py` sestaví UIKit klienty pro simulátor iPhone a Apple TV s oficiálním Python-Apple-support 3.14-b14. Parametr `--runtime-directory` ukazuje na složku s `iOS/Python.xcframework` a `tvOS/Python.xcframework`. Výstupní ZIP je určený pro simulátor na Macu s Apple Silicon. Není instalačním balíčkem pro fyzický iPhone nebo Apple TV.

Fyzická zařízení vyžadují vlastní Apple podpis, provisioning a ověření na zařízení. iPhone klient 0.19.0 má hledání Bonjour, zadání kódu a čtečku QR kamerou. Vyžaduje povolení místní sítě a pro QR fotoaparátu. Na skutečný iPhone se instaluje samostatný vývojově podepsaný balíček; nejde o veřejnou App Store distribuci. Licence běhového prostředí a knihoven jsou v `mobile/shared/licenses`. Stav veřejné distribuce popisuje hlavní `THIRD_PARTY_NOTICES.md`.

## Vývojový iPhone

V Xcode musí být přihlášený účet s vývojovým certifikátem. `scripts/prepare_apple_signing.py --team TEAM_ID --device DEVICE_ID --output /tmp/soovee-signing` požádá automatické podepisování Xcode o profil pro `cz.soovee.commander.ios`. Potom použijte `scripts/build_apple_clients.py --platform ios-device --runtime-directory /path/to/runtimes --output /tmp/soovee-apple --provisioning-profile /path/to/embedded.mobileprovision --signing-identity "Apple Development: ..."`. Skript podepisuje a kontroluje každý vložený framework zvlášť. Osobní profily, soukromé klíče a takto podepsané osobní sestavení nepatří do veřejných Releases.

## iPhone a iPad jako správce souborů (0.20)

Klient funguje i bez spárovaného zařízení. Vidí vlastní složku `Shared` (Na mém iPhonu › Soovee Commander) a složky, které uživatel jednou vybere v aplikaci Soubory; přístup drží záložky se zabezpečeným rozsahem. K celému systému souborů ani k datům jiných aplikací iOS přístup nedá.

| Soubor | Obsah |
| --- | --- |
| `mobile/apple/FileList.inc` | Seznam souborů (`UICollectionView`, seznam/mřížka), miniatury, kontextová nabídka, potažení řádku, výběr s lištou akcí, hledání v podsložkách, archivy, oblíbené a nedávné. |
| `mobile/apple/Preview.inc` | Quick Look s listováním ve složce, editor textových souborů, nový textový soubor, duplikace. |
| `mobile/apple/Overview.inc` | Přehled a Přenosy. |
| `mobile/apple/SecondPanel.inc` | Druhý (cílový) panel od šířky 700 bodů, přetahování, klávesové zkratky. |
| `mobile/apple/GroupedList.inc` | Seskupené sekce a řádky ve stylu Nastavení iOS (Zařízení, Nastavení, log). |

Jádro je společné s Androidem (`mobile/shared/python/soovee_mobile.py`): `search_local` čte jen názvy a metadata, takže soubory, které jsou jen v iCloudu, nestahuje; `extract_archive` a `compress_items` běží přes stejný průběh a zrušení jako kopírování; `preview_copy` stáhne soubor ze spárovaného zařízení do soukromé mezipaměti pro náhled.

Ruční kontrola: simulátor iPhone 17 Pro (světlý i tmavý režim) a iPad Pro 11" (dva panely). Přetažení mezi panely ověřit na skutečném iPadu.
