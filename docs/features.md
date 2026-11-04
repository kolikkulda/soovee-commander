# Podporované funkce

| Oblast | Současný rozsah |
| --- | --- |
| Místní soubory | Kopie, přesun, přejmenování, složky, koš, vlastnosti, velikosti výběru a složek. |
| Panely | Záložky mezi panely, historie s obnovením výběru, cesty, vlastní sloupce a zkratky. |
| Obnovování | Místní složka v panelu se obnoví sama, když jiná aplikace přidá, smaže nebo přejmenuje položku; kurzor, výběr i posun zůstanou. Po návratu do aplikace se složky znovu načtou (změny obsahu souborů, síťové disky). Volitelně pravidelná obnova i serverů a zařízení. Vypíná se v nabídce Zobrazit. |
| Data a řazení | Sloupce Změněno, Vytvořeno, Přidáno a Naposledy otevřeno s vysvětlením v popisku záhlaví. Na macOS odpovídají Přidáno a Naposledy otevřeno údajům Finderu a načítají se jen, když je sloupec zobrazený nebo se podle něj řadí. Volba Složky vždy nahoře. |
| Nové soubory | Shift+F4 a nabídka Nový: text, Markdown, prázdný soubor, HTML, JSON, CSV, skript, dokument Word, sešit Excel, OpenDocument text a tabulka, vlastní šablony ze složky šablon. Existující soubor se nikdy nepřepíše; textové soubory se mohou rovnou otevřít v F4. |
| Zobrazení | Výchozí detaily, volitelný kompaktní seznam, ikony a místní obrázkové miniatury; velikost ikon/řádků a režim se ukládají pro každý panel. Vzdálené soubory ani archivy se kvůli miniaturám automaticky nestahují. |
| Hromadné přejmenování | Živý náhled, kopírování původního názvu, výběr znaků, masky jména a přípony, počítadlo, nahrazení/regex a uložené předvolby. Rozsahy znaků jsou od jedné a zahrnují koncovou pozici, např. `[N2-5]`. |
| Disky | Název, dostupné/obsazené/celkové místo a ukazatel zaplnění v každém panelu; čtení na pozadí. Přímá FTP/FTPS/SFTP a Soovee připojení zatím kapacitu neposkytují. |
| Posouvání | Volitelné připnutí názvu, svislá gesta, ruční vodorovná lišta a šipky. |
| Archivy | Procházení a rozbalení ZIP, 7z, RAR a TAR podle možností backendu libarchive. |
| Komprese | Nový ZIP, 7z, TAR, TAR.GZ, TAR.BZ2 a TAR.XZ. Existující ZIP lze upravovat; ostatní existující archivy jsou pro zápis jen ke čtení. RAR se nevytváří. |
| Připojení | Pasivní FTP, explicitní FTPS s ověřením certifikátu a SFTP s ověřeným hostitelským klíčem. Implicitní FTPS a aktivní FTP zatím nejsou implementované. |
| F3 | Text, Hex/ASCII a obrázky; text je omezen na prvních 16 MiB s upozorněním na částečný obsah. Záložka Náhled ukáže formátovaný Markdown, zjednodušené HTML bez skriptů a externího obsahu, tabulky CSV/TSV, strukturu JSON, kresby SVG, PDF a text dokumentů Word, Excel, PowerPoint a OpenDocument (bez formátování). Dokumenty a obrázky se čtou celé do 64 MiB. PDF zobrazuje přibalený Qt PDF (PDFium) stejně na macOS i Windows; HEIC/HEIF jen na macOS. |
| Rychlý náhled | Ctrl+Q (na macOS Control+Q): druhý panel ukazuje soubor pod kurzorem a mění se s pohybem kurzoru. Vzdálené soubory a archivy jen do 8 MiB. Jednotlivé typy náhledů se zapínají v Zobrazit › Vestavěné náhledy. |
| F4 | Integrovaný editor do 16 MiB, čísla řádků, základní syntaxe, hledání/nahrazování, Undo/Redo, kódování a konce řádků. |
| Přenosy | QR/kód, potvrzení párování, výslovné zpřístupnění složek, oba směry, kontrola SHA-256. |
| Zařízení jako disk | Virtuální disk uvnitř panelu programu, nikoli systémový disk Finderu/Průzkumníka. |
| Nabídky a nastavení | Hlavní nabídka Soubor, Úpravy, Zobrazit, Přejít, Nástroje, Síť a zařízení, Nastavení, Nápověda; každý příkaz má popis ve stavovém řádku a v tooltipu tlačítek. Jedno okno Nastavení (Cmd/Ctrl+,) s kategoriemi a hledáním: Základní, Panely a obnovování, Náhledy, Klávesy a tlačítka, Externí příkazy, Přidružení souborů, Přenosy a aktualizace. Přehled všech klávesových zkratek s popisy (F1). |
| Jazyky | Čeština a angličtina; další jazyky lze přidat samostatným katalogem. |

Heslované archivy závisí na podpoře formátu v použitém backendu. Soubory ze vzdáleného serveru a archivů nelze přímo přetahovat do libovolné cizí aplikace; nativní přetažení je určené pro místní soubory.

Automatizované testy používají skutečné místní FTP/FTPS/SFTP servery, archivy a dvě instance přenosového protokolu. Nejde o ověření všech komerčních serverů, zařízení nebo všech verzí operačních systémů.
