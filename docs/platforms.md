# Platformy

| Platforma | Stav |
| --- | --- |
| macOS Apple Silicon | Desktopová aplikace a DMG, podpis aktualizací. |
| Windows x64 | Desktopová aplikace, instalátor a ZIP; verze 0.15.1 prošla testy, instalací, spuštěním a odinstalací na Windows runneru. |
| macOS Intel / Windows ARM64 | Zatím bez samostatně ověřeného nativního balíčku. |
| Android / Android TV / Google TV | Klient 0.16.1: jeden APK pro ARMv7, ARM64, x86 a x86_64, Android 7+. Telefon má dotykové ovládání a import přes systémový výběr souborů; TV ovládání dálkovým ovladačem a výchozí roli ovládaného zařízení. |
| Fire TV | Univerzální APK podporuje 32bitový i 64bitový ARM; konkrétní zařízení zatím není ověřené. |
| 32bitový Android / TV | Od Android klienta 0.16.1 používáme Python 3.11 a adaptér veřejného OpenSSL API, který zachovává TLS 1.3 PSK a stejný protokol jako desktop. Původní APK 0.16.0 byl jen 64bitový. |
| iPhone / Apple TV | Nativní klient sestavený a spuštěný v simulátorech. Balíčky pro fyzické zařízení vyžadují Apple podpis a provisioning; zatím nejsou dodané jako instalovatelné IPA. |

Mobilní klienti používají stejný párovací a přenosový protokol jako desktop. Výslovné potvrzení párování zpřístupní pouze složku `Shared` uvnitř aplikace. Desktop ji zobrazí přes nabídku Zařízení jako virtuální disk v panelu. Lze procházet obsah, nahrávat, stahovat a vytvářet složky; vzdálené mazání a přejmenování nejsou zatím zpřístupněné. Vlastní místní soubory lze v klientovi smazat.

Android má nativní Java rozhraní, Apple klient UIKit; sdílejí přenosové jádro v Pythonu. Android klient prošel párováním s desktopem a nahráním i stažením souboru s kontrolou SHA-256 v emulátoru. Test na skutečné TV je stále potřeba. Udržujte aplikaci otevřenou během přenosů. Automatické vyhledávání zařízení, změna IP adresy a provoz na pozadí zatím nejsou vyřešené. Apple TV ukládá soubory do mezipaměti aplikace, kterou systém může uvolnit; neslouží jako trvalá záloha.

[Sestavení a instalace mobilních testovacích klientů](mobile.md). [Podporované ABI v Chaquopy](https://chaquo.com/chaquopy/doc/current/android.html#abiFilters).
