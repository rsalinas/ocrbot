# Telegram OCR bot

Bot en Python que rep imatges per Telegram, executa el binari `tesseract` instal.lat en el sistema i respon amb el text detectat.

## Requisits

- Python 3.10 o superior
- `tesseract` disponible en el `PATH`

## Instal.lacio

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Execucio

```bash
export TELEGRAM_BOT_TOKEN='el_teu_token'
./run_bot.py
```

## Variables opcionals

- `TESSERACT_LANG`: llengua per a Tesseract, per exemple `spa` o `eng`
- `ALBUM_SETTLE_SECONDS`: espera curta per a agrupar imatges d'un mateix album
- `TESSERACT_TIMEOUT_SECONDS`: temps maxim d'execucio per imatge
- `BOT_AUTO_RELOAD_POLL_SECONDS`: freqüencia de comprovacio de canvis de codi

## Comportament

- Si arriba una imatge solta, el bot respon nomes amb el text extret.
- Si arriba un album, el bot respon en un unic missatge, separant cada resultat amb `----`.
- Durant el processament mostra l'estat de "typing" pero no envia missatges intermedis.
- Si canvia qualsevol fitxer Python del projecte, el procés es reinicia automaticament.

## Servei systemd d'usuari

Hi ha un script per a instal.lar o desinstal.lar el bot com a servici de `systemd --user`.

### Instal.lar

```bash
chmod +x scripts/manage_service.sh
./scripts/manage_service.sh install --token 'el_teu_token'
```

Opcionalment pots passar `--lang spa` o qualsevol altra variable suportada per Tesseract.

### Desinstal.lar

```bash
./scripts/manage_service.sh uninstall
```

Si tambe vols eliminar el fitxer de configuracio generat:

```bash
./scripts/manage_service.sh uninstall --purge
```

### Fitxers generats

- `~/.config/systemd/user/telegram-ocr-bot.service`
- `~/.config/telegram-ocr-bot/bot.env`
