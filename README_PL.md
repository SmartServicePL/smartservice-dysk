# Smart Service Dysk

Integracja Home Assistant, która pozwala wbudowanej integracji **Dysk Google**
logować się przez Twoje konto **Smart Service**. Kopie zapasowe robi jak zwykle
integracja Dysku Google z Home Assistant. Ta integracja zajmuje się tylko
logowaniem i odnawianiem dostępu.

[English — README.md](README.md)

## Jak to działa

- Integracja `google_drive` z Home Assistant zapisuje kopie zapasowe na Twoim Dysku Google.
- Smart Service Dysk daje jej sposób logowania **„Smart Service”**. Nie musisz zakładać
  własnego projektu Google Cloud ani klienta OAuth.
- Sekret klienta Google zostaje w panelu Smart Service. Tokeny dostępu są tylko
  w Twoim Home Assistant.
- Dostęp obejmuje wyłącznie pliki, które Home Assistant sam utworzy na Dysku (`drive.file`).
- Integracja nie ma własnych ekranów. Ustawia ją **Smart Service HA** kluczem Dysku
  z Twojego panelu Smart Service, więc nie dodajesz jej ręcznie.

## Wymagania

- Home Assistant **2026.7.0** lub nowszy;
- Smart Service HA połączony z kontem Smart Service;
- konto Google.

## Instalacja

Smart Service HA instaluje i ustawia tę integrację sam (**Rozszerzenia → Integracje**).

Instalacja ręczna: skopiuj `custom_components/smartservice_dysk` do folderu
`custom_components` w konfiguracji i uruchom ponownie Home Assistant.

## Prywatność

- Kopie zapasowe idą z Home Assistant prosto na Twój Dysk Google. Nie przechodzą przez Smart Service.
- Panel Smart Service bierze udział tylko w logowaniu i odnawianiu dostępu. Nie przechowuje Twoich tokenów.

## Pomoc

[smartservice.net.pl](https://smartservice.net.pl) · [kontakt.smart.service@gmail.com](mailto:kontakt.smart.service@gmail.com)

Dysk Google jest znakiem towarowym Google LLC. Integracja nie jest tworzona ani rekomendowana przez Google.
