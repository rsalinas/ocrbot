#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_NAME="telegram-ocr-bot.service"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
APP_CONFIG_DIR="$HOME/.config/telegram-ocr-bot"
ENV_FILE="$APP_CONFIG_DIR/bot.env"
SERVICE_TEMPLATE="$PROJECT_DIR/systemd/telegram-ocr-bot.service.template"
SERVICE_FILE="$SYSTEMD_USER_DIR/$SERVICE_NAME"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
BOT_FILE="$PROJECT_DIR/bot.py"
RUNNER_FILE="$PROJECT_DIR/run_bot.py"

usage() {
    cat <<'EOF'
Ús:
  ./scripts/manage_service.sh install --token TOKEN [--lang LANG] [--album-seconds N] [--timeout-seconds N]
  ./scripts/manage_service.sh uninstall [--purge]

Ordres:
    install     Instal.la i arranca el servici d'usuari de systemd
    uninstall   Para i elimina el servici d'usuari de systemd

Opcions:
    --token TOKEN           Token del bot de Telegram
    --lang LANG             Llengua de Tesseract, per exemple spa o eng
    --album-seconds N       Retard d'agrupacio d'àlbums en segons
    --timeout-seconds N     Temps maxim d'OCR per imatge en segons
    --purge                 Elimina el fitxer d'entorn generat en desinstal.lar
    -h, --help              Mostra esta ajuda
EOF
}

require_command() {
    local command_name="$1"
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Falta l'ordre requerida: $command_name" >&2
        exit 1
    fi
}

require_file() {
    local file_path="$1"
    if [[ ! -f "$file_path" ]]; then
        echo "Falta el fitxer requerit: $file_path" >&2
        exit 1
    fi
}

escape_sed_replacement() {
    printf '%s' "$1" | sed -e 's/[\/&]/\\&/g'
}

write_env_file() {
    local token="$1"
    local lang="$2"
    local album_seconds="$3"
    local timeout_seconds="$4"

    mkdir -p "$APP_CONFIG_DIR"
    {
        printf 'TELEGRAM_BOT_TOKEN=%s\n' "$token"
        if [[ -n "$lang" ]]; then
            printf 'TESSERACT_LANG=%s\n' "$lang"
        fi
        if [[ -n "$album_seconds" ]]; then
            printf 'ALBUM_SETTLE_SECONDS=%s\n' "$album_seconds"
        fi
        if [[ -n "$timeout_seconds" ]]; then
            printf 'TESSERACT_TIMEOUT_SECONDS=%s\n' "$timeout_seconds"
        fi
    } > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
}

install_service() {
    local token=""
    local lang=""
    local album_seconds=""
    local timeout_seconds=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --token)
                token="${2:-}"
                shift 2
                ;;
            --lang)
                lang="${2:-}"
                shift 2
                ;;
            --album-seconds)
                album_seconds="${2:-}"
                shift 2
                ;;
            --timeout-seconds)
                timeout_seconds="${2:-}"
                shift 2
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                echo "Opció desconeguda per a install: $1" >&2
                usage >&2
                exit 1
                ;;
        esac
    done

    require_command systemctl
    require_command tesseract
    require_command sed
    require_file "$SERVICE_TEMPLATE"
    require_file "$BOT_FILE"
    require_file "$RUNNER_FILE"
    require_file "$PYTHON_BIN"

    if [[ -z "$token" && -f "$ENV_FILE" ]]; then
        token="$(grep '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -n1 | cut -d= -f2- || true)"
    fi

    if [[ -z "$token" ]]; then
        echo "Has d'indicar --token TOKEN la primera volta." >&2
        exit 1
    fi

    write_env_file "$token" "$lang" "$album_seconds" "$timeout_seconds"
    mkdir -p "$SYSTEMD_USER_DIR"

    sed \
        -e "s|__WORKDIR__|$(escape_sed_replacement "$PROJECT_DIR")|g" \
        -e "s|__ENVFILE__|$(escape_sed_replacement "$ENV_FILE")|g" \
        -e "s|__PYTHON__|$(escape_sed_replacement "$PYTHON_BIN")|g" \
        -e "s|__RUNNER__|$(escape_sed_replacement "$RUNNER_FILE")|g" \
        "$SERVICE_TEMPLATE" > "$SERVICE_FILE"

    systemctl --user daemon-reload
    systemctl --user enable --now "$SERVICE_NAME"
    systemctl --user status "$SERVICE_NAME" --no-pager || true
}

uninstall_service() {
    local purge="false"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --purge)
                purge="true"
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                echo "Opció desconeguda per a uninstall: $1" >&2
                usage >&2
                exit 1
                ;;
        esac
    done

    require_command systemctl

    if [[ -f "$SERVICE_FILE" ]]; then
        systemctl --user disable --now "$SERVICE_NAME" || true
        rm -f "$SERVICE_FILE"
        systemctl --user daemon-reload
    fi

    if [[ "$purge" == "true" ]]; then
        rm -f "$ENV_FILE"
    fi
}

main() {
    if [[ $# -lt 1 ]]; then
        usage >&2
        exit 1
    fi

    case "$1" in
        install)
            shift
            install_service "$@"
            ;;
        uninstall)
            shift
            uninstall_service "$@"
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Ordre desconeguda: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
}

main "$@"