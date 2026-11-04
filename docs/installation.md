# Instalace a aktualizace

## macOS

Otevřete DMG, přetáhněte `SooveeCommander.app` do Applications a spusťte ji z této složky. Disk s instalátorem lze potom vysunout.

U starší instalace pojmenované `StereoCommander.app` lze použít nový DMG. Po ověření, že nová aplikace funguje, odstraňte starou aplikaci z Applications. Uložené nastavení, připojení a spárovaná zařízení nejsou součástí `.app` a při tomto přechodu se zachovají. Nemažte uživatelské datové složky aplikace.

Balíčky pro Mac mají zatím ad-hoc podpis, nejsou notarizované společností Apple.

## Windows

Instalátor je určený pro x64 Windows a instaluje program pro aktuálního uživatele. Vytvoří zástupce a odinstalátor. Přenosný ZIP se rozbalí celý, včetně složky `_internal`; spouští se `SooveeCommander.exe`. Tato varianta používá běžné uživatelské nastavení a logy, ne vlastní profil uložený u ZIP.

Instalátor zatím nemá Authenticode certifikát vydavatele.

## Aktualizace

V nabídce aktualizací vyberte konkrétní soubor `.stereoupdate`, nebo složku, která jej přímo obsahuje. Balíček nerozbalujte. Program ověří podpis, správnou platformu a verzi a teprve potom nabídne výměnu aplikace.

Hledání ukazuje vybranou cestu a kontrolovaný soubor. Složka bez aktualizace skončí chybou. Cloudový zástupce je na macOS odmítnut s pokynem nejprve soubor stáhnout ve Finderu.

Pro kompatibilitu se starými aktualizacemi zůstává formát `.stereoupdate` a několik interních identifikátorů původního programu. Veřejný název aplikace i Python modul jsou Soovee Commander.

## Logy

**Nápověda → Diagnostický log…** umožňuje zobrazit a místně exportovat záznamy. Export může obsahovat cesty a adresy serverů; nic se samo neodesílá.

- macOS: `~/Library/Logs/SooveeCommander/application.jsonl`
- Windows: uživatelská složka LocalAppData, podadresář `SooveeCommander/logs`
