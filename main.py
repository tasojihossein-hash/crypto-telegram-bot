import logging
import requests
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import io
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os # Diese Zeile ganz oben in der Datei hinzufügen

# --- KONFIGURATION: Keys werden aus der Umgebung geladen ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")
# -----------------------------------------------------------
# --------------------------------------------------------------

# Logging-Setup, um Fehler im Terminal zu sehen
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Liste der unterstützten Kryptowährungen
SUPPORTED_COINS = {
    "bitcoin": "bitcoin",
    "ethereum": "ethereum",
    "solana": "solana"
}


# --- Hilfsfunktionen für Charts ---

def get_historical_data(coin_id: str, days: int = 90) -> pd.DataFrame:
    """Ruft historische Marktdaten von CoinGecko ab und gibt sie als Pandas DataFrame zurück."""
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc?vs_currency=eur&days={days}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        # Daten in einen Pandas DataFrame umwandeln
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except requests.exceptions.RequestException as e:
        logger.error(f"API-Fehler bei historischen Daten für {coin_id}: {e}")
        return None


def generate_chart(df: pd.DataFrame, coin_name: str) -> bytes:
    """Erstellt einen Kerzenchart mit RSI und MACD und gibt ihn als Bytes zurück."""
    if df is None or df.empty:
        return None

    # 1. Technische Indikatoren berechnen mit pandas_ta
    df.ta.macd(close='close', fast=12, slow=26, signal=9, append=True)
    df.ta.rsi(close='close', length=14, append=True)

    # 2. Zusätzliche Plots für die Indikatoren vorbereiten
    plots = [
        # MACD Plot (Histogramm und Linien)
        mpf.make_addplot(df['MACDh_12_26_9'], type='bar', width=0.7, panel=1, color='gray', alpha=0.5,
                         secondary_y=False),
        mpf.make_addplot(df['MACD_12_26_9'], panel=1, color='blue', secondary_y=True),
        mpf.make_addplot(df['MACDs_12_26_9'], panel=1, color='orange', secondary_y=True),
        # RSI Plot
        mpf.make_addplot(df['RSI_14'], panel=2, color='purple', ylim=(10, 90)),
        # Horizontale Linien für überkauft/überverkauft beim RSI
        mpf.make_addplot([70] * len(df), panel=2, color='r', linestyle='--'),
        mpf.make_addplot([30] * len(df), panel=2, color='g', linestyle='--')
    ]

    # 3. Chart im Speicher erstellen und als Bytes speichern
    buf = io.BytesIO()
    mpf.plot(df,
             type='candle',
             style='yahoo',
             title=f'Kurschart für {coin_name.capitalize()}',
             ylabel='Preis (€)',
             addplot=plots,
             panel_ratios=(3, 1, 1),  # Hauptchart, MACD, RSI
             figscale=1.2,
             savefig=buf)
    buf.seek(0)
    return buf.read()


# --- Bot-Befehle ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sendet eine Willkommensnachricht, wenn der Befehl /start ausgeführt wird."""
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"Hallo {user_name}! Ich bin dein Krypto-Informations-Bot.\n\n"
        "Du kannst die folgenden Befehle verwenden:\n"
        "➡️ /preis [coin] - Aktueller Preis (z.B. /preis bitcoin)\n"
        "➡️ /nachrichten [coin] - Neueste Nachrichten (z.B. /nachrichten solana)\n"
        "➡️ /chart [coin] - Technischer Chart (z.B. /chart ethereum)\n\n"
        "Unterstützte Coins: Bitcoin, Ethereum, Solana"
    )


async def get_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ruft den aktuellen Preis für eine unterstützte Kryptowährung ab."""
    try:
        coin_name_input = context.args[0].lower()
        if coin_name_input not in SUPPORTED_COINS:
            await update.message.reply_text("❌ Unbekannte Kryptowährung. Bitte nutze Bitcoin, Ethereum oder Solana.")
            return

        coin_id = SUPPORTED_COINS[coin_name_input]

        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=eur"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        price = data[coin_id]['eur']

        await update.message.reply_text(f"Der aktuelle Preis für {coin_name_input.capitalize()} ist: **{price} €**",
                                        parse_mode='Markdown')

    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Bitte gib eine Kryptowährung an. Beispiel: /preis bitcoin")
    except requests.exceptions.RequestException as e:
        logger.error(f"API-Fehler bei der Preisanfrage: {e}")
        await update.message.reply_text("Fehler: Konnte die Preisdaten nicht abrufen. Versuche es später erneut.")


async def get_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ruft die neuesten Nachrichten für eine Kryptowährung ab."""
    try:
        coin_name_input = context.args[0].lower()
        if coin_name_input not in SUPPORTED_COINS:
            await update.message.reply_text("❌ Unbekannte Kryptowährung. Bitte nutze Bitcoin, Ethereum oder Solana.")
            return

        url = f"https://newsapi.org/v2/everything?q={coin_name_input}&sortBy=publishedAt&pageSize=5&language=de&apiKey={NEWS_API_KEY}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        articles = data.get("articles", [])

        if not articles:
            await update.message.reply_text(
                f"Keine aktuellen deutschen Nachrichten für {coin_name_input.capitalize()} gefunden.")
            return

        message = f"📰 Neueste Nachrichten für {coin_name_input.capitalize()}:\n\n"
        for article in articles:
            title = article['title']
            source_url = article['url']
            message += f"▪️ [{title}]({source_url})\n"

        await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)

    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Bitte gib eine Kryptowährung an. Beispiel: /nachrichten ethereum")
    except requests.exceptions.RequestException as e:
        logger.error(f"API-Fehler bei der Nachrichtenanfrage: {e}")
        await update.message.reply_text(
            "Fehler: Konnte die Nachrichten nicht abrufen. Überprüfe deinen API-Key oder versuche es später.")


async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ruft historische Daten ab, erstellt einen Chart und sendet ihn."""
    try:
        coin_name_input = context.args[0].lower()
        if coin_name_input not in SUPPORTED_COINS:
            await update.message.reply_text("❌ Unbekannte Kryptowährung. Bitte nutze Bitcoin, Ethereum oder Solana.")
            return

        coin_id = SUPPORTED_COINS[coin_name_input]

        await update.message.reply_text(
            f"⏳ Erstelle Chart für {coin_name_input.capitalize()}, bitte einen Moment Geduld...")

        # 1. Daten abrufen
        df = get_historical_data(coin_id)

        if df is None or df.empty:
            await update.message.reply_text("Fehler: Konnte keine historischen Daten für den Chart abrufen.")
            return

        # 2. Chart generieren
        chart_bytes = generate_chart(df, coin_name_input)

        if chart_bytes:
            # 3. Chart als Foto senden
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=chart_bytes,
                caption=f"Technischer Chart für {coin_name_input.capitalize()} (90 Tage)"
            )
        else:
            await update.message.reply_text("Fehler: Der Chart konnte nicht erstellt werden.")

    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Bitte gib eine Kryptowährung an. Beispiel: /chart bitcoin")
    except Exception as e:
        logger.error(f"Ein unerwarteter Fehler im Chart-Befehl ist aufgetreten: {e}")
        await update.message.reply_text("Ein unerwarteter Fehler ist aufgetreten. Bitte versuche es später erneut.")


# --- Hauptfunktion zum Starten des Bots ---

def main() -> None:
    """Startet den Bot."""
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Fügt die Befehls-Handler hinzu
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("preis", get_price))
    application.add_handler(CommandHandler("nachrichten", get_news))
    application.add_handler(CommandHandler("chart", chart))

    # Startet den Bot (Polling-Modus)
    logger.info("Bot wird gestartet...")
    application.run_polling()


if __name__ == "__main__":
    main()
