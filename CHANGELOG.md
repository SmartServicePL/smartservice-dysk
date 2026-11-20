# Changelog

## 0.1.2

- Okno integracji w Home Assistant bez pola klucza: mówi tylko, że Dysk Google łączysz w Smart Service HA (Pomoc i konto → Kopia zapasowa). Klucz przekazuje sam Smart Service HA.

## 0.1.1

- Logo Smart Service w Home Assistant i HACS, odnośniki do opisu i zgłoszeń na GitHubie.
- Testy bez połączeń sieciowych (atrapa panelu w testach).

## 0.1.0

- Sposób logowania „Smart Service” dla integracji Dysk Google z Home Assistant: logowanie i odnawianie dostępu przez panel Smart Service, sekret klienta Google w panelu, tokeny tylko w domu, zakres `drive.file`.
- Wpis zakłada Smart Service HA kluczem Dysku z panelu; zmiana klucza bez usuwania wpisu.
- Stan logowania i unieważnienie dostępu dla Smart Service HA.
